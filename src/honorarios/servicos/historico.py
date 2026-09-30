"""Histórico de um honorário: tudo o que aconteceu com ele, em ordem.

Quando a cobrança saiu numa mensagem com outros honorários da mesma empresa, o
evento diz que foi em lote e quais competências foram junto — é a pergunta que
aparece primeiro quando se olha "por que esse aqui foi cobrado?".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from ..dominio.enums import ResultadoCobranca, StatusPagamento
from ..dominio.valores import formatar_data, formatar_moeda, hoje
from ..infra.modelos import Cobranca, Honorario
from . import calculo

LANCAMENTO = "Lançamento"
ENVIO = "Envio ao cliente"
COBRANCA = "Cobrança"
RESPOSTA = "Resposta"
PAGAMENTO = "Pagamento"
ESTORNO = "Estorno"
CANCELAMENTO = "Cancelamento"
RENEGOCIACAO = "Renegociação"


@dataclass
class Evento:
    quando: date
    tipo: str
    titulo: str
    detalhe: str = ""
    valor: Decimal | None = None
    em_lote: bool = False
    companheiros: list[str] = field(default_factory=list)
    texto: str = ""
    cobranca: Cobranca | None = None

    @property
    def rotulo_lote(self) -> str:
        if not self.em_lote:
            return "Cobrança individual"
        return f"Em lote · mais {len(self.companheiros)} honorário(s)"

    @property
    def resumo_companheiros(self) -> str:
        """Primeiras competências que foram na mesma mensagem."""
        if not self.companheiros:
            return ""
        if len(self.companheiros) <= 4:
            return ", ".join(self.companheiros)
        restantes = len(self.companheiros) - 4
        return ", ".join(self.companheiros[:4]) + f" e mais {restantes}"


def do_honorario(
    sessao: Session, honorario: Honorario, data_referencia: date | None = None
) -> list[Evento]:
    referencia = data_referencia or hoje()
    eventos: list[Evento] = []

    eventos.append(
        Evento(
            quando=honorario.criado_em.date(),
            tipo=LANCAMENTO,
            titulo=f"{honorario.tipo.nome} lançado",
            detalhe=(
                f"Competência {honorario.competencia_rotulo or '—'} · "
                f"vencimento {formatar_data(honorario.vencimento)} · "
                f"{honorario.meio.rotulo}"
            ),
            valor=honorario.valor_original,
        )
    )

    if honorario.enviado_em:
        eventos.append(
            Evento(
                quando=honorario.enviado_em,
                tipo=ENVIO,
                titulo="Boleto enviado ao cliente",
                detalhe=(
                    honorario.forma_envio.nome
                    if honorario.forma_envio
                    else "forma de envio não informada"
                ),
            )
        )

    for cobranca in honorario.cobrancas:
        lote = cobranca.lote
        companheiros = []
        if lote is not None:
            companheiros = [
                outra.honorario.competencia_rotulo or outra.honorario.tipo.nome
                for outra in lote.cobrancas
                if outra.honorario_id != honorario.id and outra.ativa
            ]
        detalhe = cobranca.canal.rotulo
        if not cobranca.ativa:
            detalhe += " · ESTORNADA"
        eventos.append(
            Evento(
                quando=cobranca.data_hora.date(),
                tipo=COBRANCA,
                titulo=(
                    "Cobrança enviada em lote"
                    if companheiros
                    else "Cobrança enviada"
                ),
                detalhe=detalhe,
                valor=cobranca.valor_atualizado_no_momento,
                em_lote=bool(companheiros),
                companheiros=companheiros,
                texto=cobranca.texto,
                cobranca=cobranca,
            )
        )
        if cobranca.ativa and cobranca.resultado.respondida:
            complemento = cobranca.observacao or ""
            if cobranca.promessa_data:
                promessa = f"Prometeu pagar em {formatar_data(cobranca.promessa_data)}"
                complemento = f"{promessa}. {complemento}".strip()
            eventos.append(
                Evento(
                    quando=cobranca.data_hora.date(),
                    tipo=RESPOSTA,
                    titulo=cobranca.resultado.rotulo,
                    detalhe=complemento,
                    cobranca=cobranca,
                )
            )

    for pagamento in honorario.pagamentos:
        partes = [f"{pagamento.dias_atraso} dia(s) de atraso"]
        if pagamento.juros_cobrados:
            partes.append(f"juros {formatar_moeda(pagamento.juros_cobrados)}")
        if pagamento.desconto:
            partes.append(f"abono {formatar_moeda(pagamento.desconto)}")
        partes.append(pagamento.forma_pagamento.rotulo)
        eventos.append(
            Evento(
                quando=pagamento.data,
                tipo=PAGAMENTO,
                titulo="Pagamento parcial" if pagamento.parcial else "Pagamento",
                detalhe=" · ".join(partes),
                valor=pagamento.valor_pago,
            )
        )
        if not pagamento.ativo and pagamento.estornado_em:
            eventos.append(
                Evento(
                    quando=pagamento.estornado_em.date(),
                    tipo=ESTORNO,
                    titulo="Pagamento estornado",
                    detalhe=pagamento.motivo_estorno,
                    valor=pagamento.valor_pago,
                )
            )

    if honorario.cancelado_em:
        eventos.append(
            Evento(
                quando=honorario.cancelado_em.date(),
                tipo=CANCELAMENTO,
                titulo="Honorário cancelado",
                detalhe=honorario.motivo_cancelamento,
            )
        )
    if honorario.status is StatusPagamento.RENEGOCIADO:
        eventos.append(
            Evento(
                quando=referencia,
                tipo=RENEGOCIACAO,
                titulo="Incluído em acordo de renegociação",
                detalhe="O valor passou para as parcelas do acordo.",
            )
        )

    eventos.sort(key=lambda evento: (evento.quando, evento.tipo != LANCAMENTO), reverse=True)
    return eventos


@dataclass
class Resumo:
    honorario: Honorario
    atualizacao: calculo.Atualizacao
    cobrancas: int
    ultima_cobranca: date | None
    promessa: date | None

    @property
    def situacao(self) -> str:
        if self.honorario.status is not StatusPagamento.EM_ABERTO:
            return self.honorario.status.rotulo
        if self.atualizacao.dias_atraso > 0:
            return f"Em atraso há {self.atualizacao.dias_atraso} dia(s)"
        return "Em dia"


def resumo(
    sessao: Session, honorario: Honorario, data_referencia: date | None = None
) -> Resumo:
    referencia = data_referencia or hoje()
    ativas = [c for c in honorario.cobrancas if c.ativa]
    promessas = [
        c.promessa_data
        for c in ativas
        if c.resultado is ResultadoCobranca.PROMETEU_PAGAR and c.promessa_data
    ]
    return Resumo(
        honorario=honorario,
        atualizacao=calculo.atualizar(honorario, referencia),
        cobrancas=len(ativas),
        ultima_cobranca=max((c.data_hora.date() for c in ativas), default=None),
        promessa=max(promessas) if promessas else None,
    )
