"""Acompanhamento das cobranças: o que foi enviado e o que respondeu.

A resposta do cliente não é anotada na hora de cobrar — quando a mensagem sai,
ainda não existe resposta. Cada cobrança nasce "aguardando resposta" e é aqui
que o retorno entra, no mesmo lugar em que se enxerga o que está parado.

A unidade de acompanhamento é a **mensagem enviada** (o lote), não cada
honorário: foi uma conversa só com a empresa, e a resposta vale para todos os
honorários que estavam nela.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..dominio.enums import Canal, ResultadoCobranca, StatusPagamento
from ..dominio.valores import ZERO, hoje, normalizar_busca
from ..infra.modelos import Cliente, Cobranca, CobrancaLote
from . import calculo
from .erros import ErroDeValidacao

# situações, na ordem em que pedem ação
AGUARDANDO = "Aguardando resposta"
PROMESSA_VENCIDA = "Promessa vencida"
PROMESSA_EM_ABERTO = "Promessa em aberto"
PRECISA_DECISAO = "Precisa de decisão"
NAO_RESPONDEU = "Não respondeu"
ENCERRADA = "Encerrada"

ORDEM_SITUACOES = (
    PROMESSA_VENCIDA,
    AGUARDANDO,
    PRECISA_DECISAO,
    PROMESSA_EM_ABERTO,
    NAO_RESPONDEU,
    ENCERRADA,
)

DESCRICOES = {
    PROMESSA_VENCIDA: "Prometeu pagar e a data passou",
    AGUARDANDO: "Mensagem enviada, resposta ainda não anotada",
    PRECISA_DECISAO: "Pediu renegociação ou contestou o valor",
    PROMESSA_EM_ABERTO: "Prometeu pagar em data que ainda não chegou",
    NAO_RESPONDEU: "Cobrado e sem retorno",
    ENCERRADA: "Honorários já quitados ou cobrança estornada",
}


@dataclass
class LinhaAcompanhamento:
    """Uma mensagem enviada, com o que aconteceu com ela desde então."""

    lote: CobrancaLote
    cobrancas: list[Cobranca] = field(default_factory=list)
    quitados: int = 0
    saldo_atual: Decimal = ZERO
    referencia: date = field(default_factory=hoje)

    @property
    def cliente(self) -> Cliente:
        return self.lote.cliente

    @property
    def data(self) -> date:
        return self.lote.data_hora.date()

    @property
    def dias(self) -> int:
        return (self.referencia - self.data).days

    @property
    def canal(self) -> Canal:
        return self.lote.canal

    @property
    def quantidade(self) -> int:
        return len(self.cobrancas)

    @property
    def resultado(self) -> ResultadoCobranca:
        return self.cobrancas[0].resultado if self.cobrancas else ResultadoCobranca.AGUARDANDO

    @property
    def promessa(self) -> date | None:
        return self.cobrancas[0].promessa_data if self.cobrancas else None

    @property
    def observacao(self) -> str:
        return self.cobrancas[0].observacao if self.cobrancas else ""

    @property
    def texto(self) -> str:
        return self.lote.texto_enviado

    @property
    def competencias(self) -> str:
        rotulos = [c.honorario.competencia_rotulo for c in self.cobrancas]
        if len(rotulos) <= 2:
            return " · ".join(r for r in rotulos if r)
        return f"{rotulos[0]} … {rotulos[-1]} ({len(rotulos)} honorários)"

    @property
    def tudo_quitado(self) -> bool:
        return bool(self.cobrancas) and self.quitados == len(self.cobrancas)

    @property
    def situacao(self) -> str:
        if not self.cobrancas or self.tudo_quitado:
            return ENCERRADA
        resultado = self.resultado
        if resultado is ResultadoCobranca.PAGOU:
            return ENCERRADA
        if resultado is ResultadoCobranca.AGUARDANDO:
            return AGUARDANDO
        if resultado is ResultadoCobranca.PROMETEU_PAGAR:
            if self.promessa is not None and self.promessa < self.referencia:
                return PROMESSA_VENCIDA
            return PROMESSA_EM_ABERTO
        if resultado in (
            ResultadoCobranca.PEDIU_RENEGOCIACAO,
            ResultadoCobranca.CONTESTOU,
        ):
            return PRECISA_DECISAO
        return NAO_RESPONDEU

    @property
    def pede_acao(self) -> bool:
        return self.situacao in (PROMESSA_VENCIDA, AGUARDANDO, PRECISA_DECISAO)


@dataclass
class Filtro:
    termo: str = ""
    cliente_id: int | None = None
    canal: Canal | None = None
    situacao: str | None = None
    somente_pendentes: bool = False
    desde: date | None = None
    ate: date | None = None
    data_referencia: date | None = None


def listar(sessao: Session, filtro: Filtro | None = None) -> list[LinhaAcompanhamento]:
    filtro = filtro or Filtro()
    referencia = filtro.data_referencia or hoje()

    consulta = select(CobrancaLote).join(Cliente).order_by(CobrancaLote.data_hora.desc())
    if filtro.cliente_id:
        consulta = consulta.where(CobrancaLote.cliente_id == filtro.cliente_id)
    if filtro.canal is not None:
        consulta = consulta.where(CobrancaLote.canal == filtro.canal)
    consulta = consulta.where(Cliente.excluido_em.is_(None))

    linhas: list[LinhaAcompanhamento] = []
    alvo = normalizar_busca(filtro.termo)
    for lote in sessao.scalars(consulta).unique().all():
        quando = lote.data_hora.date()
        if filtro.desde is not None and quando < filtro.desde:
            continue
        if filtro.ate is not None and quando > filtro.ate:
            continue
        if alvo and alvo not in lote.cliente.nome_busca:
            continue
        cobrancas = [c for c in lote.cobrancas if c.ativa]
        if not cobrancas:
            continue
        quitados = sum(
            1 for c in cobrancas if c.honorario.status is StatusPagamento.PAGO
        )
        abertos = [
            c.honorario
            for c in cobrancas
            if c.honorario.status is StatusPagamento.EM_ABERTO
        ]
        atualizacoes = calculo.atualizar_varios(abertos, referencia)
        linha = LinhaAcompanhamento(
            lote=lote,
            cobrancas=cobrancas,
            quitados=quitados,
            saldo_atual=sum((a.total for a in atualizacoes.values()), start=ZERO),
            referencia=referencia,
        )
        if filtro.situacao and linha.situacao != filtro.situacao:
            continue
        if filtro.somente_pendentes and not linha.pede_acao:
            continue
        linhas.append(linha)
    return linhas


def por_situacao(
    linhas: Sequence[LinhaAcompanhamento],
) -> list[tuple[str, list[LinhaAcompanhamento]]]:
    grupos: dict[str, list[LinhaAcompanhamento]] = {}
    for linha in linhas:
        grupos.setdefault(linha.situacao, []).append(linha)
    saida = []
    for situacao in ORDEM_SITUACOES:
        itens = grupos.get(situacao)
        if not itens:
            continue
        itens.sort(key=lambda linha: linha.data, reverse=True)
        saida.append((situacao, itens))
    return saida


def por_mes(
    linhas: Sequence[LinhaAcompanhamento],
) -> list[tuple[str, list[LinhaAcompanhamento]]]:
    """Agrupa por mês da cobrança, do mais recente para o mais antigo."""
    from ..dominio.valores import MESES_ABREVIADOS

    grupos: dict[tuple[int, int], list[LinhaAcompanhamento]] = {}
    for linha in linhas:
        grupos.setdefault((linha.data.year, linha.data.month), []).append(linha)
    saida = []
    for ano, mes in sorted(grupos, reverse=True):
        itens = grupos[(ano, mes)]
        itens.sort(key=lambda linha: linha.data, reverse=True)
        saida.append((f"{MESES_ABREVIADOS[mes - 1]}/{ano}", itens))
    return saida


def por_empresa(
    linhas: Sequence[LinhaAcompanhamento],
) -> list[tuple[str, list[LinhaAcompanhamento]]]:
    grupos: dict[str, list[LinhaAcompanhamento]] = {}
    for linha in linhas:
        grupos.setdefault(f"{linha.cliente.codigo} – {linha.cliente.nome}", []).append(linha)
    saida = []
    for rotulo in sorted(grupos):
        itens = grupos[rotulo]
        itens.sort(key=lambda linha: linha.data, reverse=True)
        saida.append((rotulo, itens))
    return saida


def registrar_resposta(
    sessao: Session,
    linha: LinhaAcompanhamento,
    resultado: ResultadoCobranca,
    promessa_data: date | None = None,
    observacao: str = "",
) -> None:
    """Anota o retorno do cliente em todos os honorários daquela mensagem."""
    if resultado is ResultadoCobranca.PROMETEU_PAGAR and promessa_data is None:
        raise ErroDeValidacao("Informe a data prometida para o pagamento.", "promessa_data")
    if resultado is not ResultadoCobranca.PROMETEU_PAGAR:
        promessa_data = None
    for cobranca in linha.cobrancas:
        cobranca.resultado = resultado
        cobranca.promessa_data = promessa_data
        cobranca.observacao = observacao.strip()
    sessao.flush()


def linha_do_lote(
    sessao: Session, lote: CobrancaLote, data_referencia: date | None = None
) -> LinhaAcompanhamento:
    """Monta a linha de acompanhamento de uma mensagem específica."""
    referencia = data_referencia or hoje()
    cobrancas = [c for c in lote.cobrancas if c.ativa]
    abertos = [
        c.honorario for c in cobrancas if c.honorario.status is StatusPagamento.EM_ABERTO
    ]
    atualizacoes = calculo.atualizar_varios(abertos, referencia)
    return LinhaAcompanhamento(
        lote=lote,
        cobrancas=cobrancas,
        quitados=sum(1 for c in cobrancas if c.honorario.status is StatusPagamento.PAGO),
        saldo_atual=sum((a.total for a in atualizacoes.values()), start=ZERO),
        referencia=referencia,
    )


def contar_pendentes(sessao: Session, data_referencia: date | None = None) -> int:
    """Quantas mensagens ainda esperam uma resposta anotada."""
    return sum(
        1
        for linha in listar(sessao, Filtro(data_referencia=data_referencia))
        if linha.pede_acao
    )


__all__ = [
    "AGUARDANDO",
    "DESCRICOES",
    "ENCERRADA",
    "Filtro",
    "LinhaAcompanhamento",
    "NAO_RESPONDEU",
    "ORDEM_SITUACOES",
    "PRECISA_DECISAO",
    "PROMESSA_EM_ABERTO",
    "PROMESSA_VENCIDA",
    "contar_pendentes",
    "linha_do_lote",
    "listar",
    "por_empresa",
    "por_mes",
    "por_situacao",
    "registrar_resposta",
]
