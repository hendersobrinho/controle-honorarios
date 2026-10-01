"""Cobrança: monta a mensagem, registra a tentativa e alimenta as filas.

O sistema nunca envia nada: gera o texto, copia e (se você pedir) abre a
conversa. O registro da cobrança só acontece quando você confirma, porque copiar
não é enviar.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..dominio.enums import Canal, ResultadoCobranca, StatusPagamento
from ..dominio.mensagens import (
    ContextoMensagem,
    ItemCobranca,
    montar_link_whatsapp,
    montar_mensagem,
)
from ..dominio.valores import ZERO, Competencia, agora_local, agora_utc, hoje
from ..infra.modelos import (
    Cliente,
    ClienteContato,
    Cobranca,
    CobrancaLote,
    Honorario,
)
from . import configuracoes
from . import honorarios as servico_honorarios
from .erros import ErroDeValidacao
from .honorarios import Filtro, LinhaHonorario


@dataclass
class Selecao:
    """O que a tela "Cobrar" tem em mãos quando monta a mensagem."""

    cliente: Cliente
    linhas: list[LinhaHonorario]
    contato: ClienteContato | None = None
    citar_empresa: bool = False
    data_referencia: date = field(default_factory=hoje)
    hora_referencia: time | None = None
    forcar_lembrete: bool = False

    @property
    def total(self) -> Decimal:
        return sum((linha.atualizacao.total for linha in self.linhas), start=ZERO)


def _item_de(linha: LinhaHonorario, cobrado_de: Cliente | None = None) -> ItemCobranca:
    honorario = linha.honorario
    tipo = honorario.tipo
    competencia = Competencia(honorario.competencia_ano, honorario.competencia_mes)
    # quando a empresa cobra pela pessoa vinculada, a mensagem precisa dizer de quem
    titular = ""
    if cobrado_de is not None and honorario.cliente_id != cobrado_de.id:
        titular = honorario.cliente.nome
    return ItemCobranca(
        tipo_nome=tipo.nome,
        texto_mensagem=tipo.texto_mensagem,
        texto_mensagem_empresa=tipo.texto_mensagem_empresa,
        texto_item_lista=tipo.texto_item_lista,
        competencia=competencia,
        vencimento=honorario.vencimento,
        valor_original=linha.atualizacao.valor_original,
        juros=linha.atualizacao.juros,
        valor_atualizado=linha.atualizacao.total,
        dias_atraso=linha.atualizacao.dias_atraso,
        honorario_id=honorario.id,
        titular=titular,
    )


def _recusar_suspensos(
    cliente: Cliente, linhas: Sequence[LinhaHonorario], referencia: date | None = None
) -> None:
    """Cobrança suspensa não é registrada: foi uma decisão consciente de parar."""
    suspensos = {
        linha.cliente.nome
        for linha in linhas
        if linha.cliente.suspensao_ativa(referencia)
    }
    if cliente.suspensao_ativa(referencia):
        suspensos.add(cliente.nome)
    if not suspensos:
        return
    nomes = ", ".join(sorted(suspensos))
    raise ErroDeValidacao(
        f"A cobrança de {nomes} está suspensa. Retome a cobrança na ficha do "
        "cliente antes de registrar."
    )


def montar_contexto(sessao: Session, selecao: Selecao) -> ContextoMensagem:
    if not selecao.linhas:
        raise ErroDeValidacao("Selecione ao menos um honorário para cobrar.")
    contato = selecao.contato or selecao.cliente.contato_principal
    hora = selecao.hora_referencia or agora_local().time()
    return ContextoMensagem(
        empresa=selecao.cliente.nome,
        itens=[_item_de(linha, selecao.cliente) for linha in selecao.linhas],
        recebedor=configuracoes.recebedor(sessao),
        data_referencia=selecao.data_referencia,
        hora_referencia=hora,
        nome_tratamento=contato.tratamento_ou_nome if contato else "",
        citar_empresa=selecao.citar_empresa,
        ordem_saudacao=configuracoes.ordem_saudacao(sessao),
        modelos=configuracoes.modelos(sessao),
        forcar_lembrete=selecao.forcar_lembrete,
    )


def gerar_texto(sessao: Session, selecao: Selecao) -> str:
    return montar_mensagem(montar_contexto(sessao, selecao))


def link_whatsapp(sessao: Session, contato: ClienteContato | None, texto: str) -> str:
    if contato is None or not contato.telefone:
        raise ErroDeValidacao(
            "O contato selecionado não tem telefone de WhatsApp cadastrado."
        )
    return montar_link_whatsapp(
        contato.telefone, texto, configuracoes.formato_link(sessao)
    )


def registrar(
    sessao: Session,
    selecao: Selecao,
    texto: str = "",
    canal: Canal = Canal.WHATSAPP,
    resultado: ResultadoCobranca = ResultadoCobranca.AGUARDANDO,
    promessa_data: date | None = None,
    observacao: str = "",
    quando: datetime | None = None,
) -> CobrancaLote:
    """Uma cobrança por honorário marcado, todas apontando para a mesma mensagem."""
    if not selecao.linhas:
        raise ErroDeValidacao("Nenhum honorário marcado para registrar a cobrança.")
    if resultado is ResultadoCobranca.PROMETEU_PAGAR and promessa_data is None:
        raise ErroDeValidacao(
            "Informe a data prometida para o pagamento.", "promessa_data"
        )
    for linha in selecao.linhas:
        if not linha.honorario.status.cobravel:
            raise ErroDeValidacao(
                f"{linha.honorario.status.rotulo} não entra em cobrança: "
                f"{linha.cliente.nome}, {linha.honorario.competencia_rotulo}."
            )
    _recusar_suspensos(selecao.cliente, selecao.linhas, selecao.data_referencia)

    contato = selecao.contato or selecao.cliente.contato_principal
    momento = quando or agora_utc()
    lote = CobrancaLote(
        cliente_id=selecao.cliente.id,
        contato_id=contato.id if contato else None,
        canal=canal,
        data_hora=momento,
        texto_enviado=texto,
        total_no_momento=selecao.total,
    )
    sessao.add(lote)
    sessao.flush()

    for linha in selecao.linhas:
        # anexado pelo relacionamento (não por sessao.add) para que as coleções já
        # carregadas em memória fiquem consistentes sem precisar recarregar
        linha.honorario.cobrancas.append(
            Cobranca(
                lote=lote,
                data_hora=momento,
                canal=canal,
                resultado=resultado,
                promessa_data=promessa_data,
                observacao=observacao or "",
                valor_atualizado_no_momento=linha.atualizacao.total,
            )
        )
    sessao.flush()
    return lote


def registrar_sem_mensagem(
    sessao: Session,
    linhas: Sequence[LinhaHonorario],
    observacao: str = "",
    canal: Canal = Canal.WHATSAPP,
    resultado: ResultadoCobranca = ResultadoCobranca.AGUARDANDO,
    quando: date | None = None,
) -> int:
    """Registro em lote de cobranças feitas por fora do sistema."""
    if not linhas:
        raise ErroDeValidacao("Selecione os honorários que você cobrou.")
    por_cliente: dict[int, list[LinhaHonorario]] = {}
    for linha in linhas:
        por_cliente.setdefault(linha.cliente.id, []).append(linha)
    momento = (
        datetime.combine(quando, agora_local().time()) if quando else agora_utc()
    )
    total = 0
    for cliente_id, itens in por_cliente.items():
        cliente = sessao.get(Cliente, cliente_id)
        selecao = Selecao(cliente=cliente, linhas=itens)
        registrar(
            sessao,
            selecao,
            texto="",
            canal=canal,
            resultado=resultado,
            observacao=observacao or "Cobrança registrada sem mensagem gerada",
            quando=momento,
        )
        total += len(itens)
    return total


def estornar(sessao: Session, cobranca: Cobranca, motivo: str) -> None:
    if not (motivo or "").strip():
        raise ErroDeValidacao("Descreva o motivo do estorno da cobrança.", "motivo")
    cobranca.estornada_em = agora_utc()
    cobranca.observacao = (
        f"{cobranca.observacao}\nEstornada: {motivo.strip()}".strip()
    )
    sessao.flush()


def atualizar_resultado(
    sessao: Session,
    cobranca: Cobranca,
    resultado: ResultadoCobranca,
    promessa_data: date | None = None,
    observacao: str | None = None,
) -> None:
    if resultado is ResultadoCobranca.PROMETEU_PAGAR and promessa_data is None:
        raise ErroDeValidacao("Informe a data prometida.", "promessa_data")
    cobranca.resultado = resultado
    cobranca.promessa_data = promessa_data
    if observacao is not None:
        cobranca.observacao = observacao
    sessao.flush()


# --------------------------------------------------------------------- filas


def historico_do_cliente(sessao: Session, cliente_id: int) -> list[Cobranca]:
    return list(
        sessao.scalars(
            select(Cobranca)
            .join(Honorario)
            .where(Honorario.cliente_id == cliente_id)
            .order_by(Cobranca.data_hora.desc())
        )
        .unique()
        .all()
    )


def ultima_cobranca_do_cliente(sessao: Session, cliente_id: int) -> Cobranca | None:
    historico = historico_do_cliente(sessao, cliente_id)
    return historico[0] if historico else None


def linhas_em_aberto_do_cliente(
    sessao: Session,
    cliente_id: int,
    data_referencia: date | None = None,
    incluir_vinculados: bool = False,
) -> list[LinhaHonorario]:
    """Pendências do cliente; com ``incluir_vinculados``, também das pessoas
    físicas que pagam por esta empresa."""
    return servico_honorarios.pendentes(
        sessao,
        Filtro(
            cliente_id=cliente_id,
            incluir_vinculados_de=cliente_id if incluir_vinculados else None,
            data_referencia=data_referencia,
        ),
    )


__all__ = [
    "Selecao",
    "StatusPagamento",
    "atualizar_resultado",
    "estornar",
    "gerar_texto",
    "historico_do_cliente",
    "link_whatsapp",
    "linhas_em_aberto_do_cliente",
    "montar_contexto",
    "registrar",
    "registrar_sem_mensagem",
    "ultima_cobranca_do_cliente",
]
