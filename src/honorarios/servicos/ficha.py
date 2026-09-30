"""Dados consolidados da ficha da empresa, inclusive a linha do tempo."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from ..dominio.enums import StatusPagamento
from ..dominio.valores import ZERO, formatar_moeda, hoje
from ..infra.modelos import Cliente
from . import calculo, clientes, cobrancas
from . import honorarios as servico_honorarios
from .honorarios import Filtro, LinhaHonorario


@dataclass
class Evento:
    quando: date
    tipo: str
    descricao: str


@dataclass
class Resumo:
    cliente: Cliente
    juros_dia: Decimal
    total_em_aberto: Decimal
    quantidade_em_aberto: int
    maior_atraso: int
    ultima_cobranca: date | None
    proxima_acao: str
    pendentes: list[LinhaHonorario] = field(default_factory=list)
    pagos: list[LinhaHonorario] = field(default_factory=list)


def resumo(sessao: Session, cliente: Cliente, data_referencia: date | None = None) -> Resumo:
    referencia = data_referencia or hoje()
    pendentes = servico_honorarios.pendentes(
        sessao, Filtro(cliente_id=cliente.id, data_referencia=referencia)
    )
    pagos = servico_honorarios.pagos(
        sessao, Filtro(cliente_id=cliente.id, data_referencia=referencia)
    )
    ultima = cobrancas.ultima_cobranca_do_cliente(sessao, cliente.id)
    promessas = [linha.promessa for linha in pendentes if linha.promessa]
    if not pendentes:
        proxima = "Nada em aberto"
    elif any(linha.promessa_vencida for linha in pendentes):
        proxima = "Promessa de pagamento vencida: cobrar hoje"
    elif promessas:
        proxima = f"Aguardando pagamento prometido para {min(promessas):%d/%m/%Y}"
    elif not ultima:
        proxima = "Nunca cobrado: gerar a primeira cobrança"
    else:
        dias = (referencia - ultima.data_hora.date()).days
        proxima = f"Última cobrança há {dias} dia(s)"

    return Resumo(
        cliente=cliente,
        juros_dia=clientes.juros_atual(cliente, referencia),
        total_em_aberto=sum((linha.atualizacao.total for linha in pendentes), start=ZERO),
        quantidade_em_aberto=len(pendentes),
        maior_atraso=max((linha.atualizacao.dias_atraso for linha in pendentes), default=0),
        ultima_cobranca=ultima.data_hora.date() if ultima else None,
        proxima_acao=proxima,
        pendentes=pendentes,
        pagos=pagos,
    )


def pagos_com_atraso(pagos: list[LinhaHonorario]) -> list[LinhaHonorario]:
    return [
        linha
        for linha in pagos
        if any(p.ativo and p.dias_atraso > 0 for p in linha.honorario.pagamentos)
    ]


def linha_do_tempo(sessao: Session, cliente: Cliente) -> list[Evento]:
    """Eventos do cliente em ordem decrescente, montados do próprio histórico."""
    eventos: list[Evento] = []

    for linha in cliente.juros:
        anterior = (
            f"{formatar_moeda(linha.valor_anterior)} → " if linha.valor_anterior is not None else ""
        )
        eventos.append(
            Evento(
                linha.vigencia_inicio,
                "Juros ao dia",
                f"{anterior}{formatar_moeda(linha.valor_dia)} por dia"
                + (f" · {linha.motivo}" if linha.motivo else ""),
            )
        )

    for contrato in cliente.contratos:
        if contrato.excluido_em is not None:
            continue
        for registro in contrato.historico:
            eventos.append(
                Evento(
                    registro.vigencia_inicio,
                    "Reajuste",
                    f"{contrato.tipo.nome}: {formatar_moeda(Decimal(registro.valor_anterior))} → "
                    f"{formatar_moeda(Decimal(registro.valor_novo))}"
                    + (f" · {registro.motivo}" if registro.motivo else ""),
                )
            )

    for honorario in cliente.honorarios:
        rotulo = f"{honorario.tipo.nome} {honorario.competencia_rotulo}".strip()
        eventos.append(
            Evento(
                honorario.criado_em.date(),
                "Lançamento",
                f"{rotulo} – {formatar_moeda(honorario.valor_original)}, "
                f"vence {honorario.vencimento:%d/%m/%Y}",
            )
        )
        if honorario.cancelado_em:
            eventos.append(
                Evento(
                    honorario.cancelado_em.date(),
                    "Cancelamento",
                    f"{rotulo} · {honorario.motivo_cancelamento}",
                )
            )
        for pagamento in honorario.pagamentos:
            situacao = "Estornado" if not pagamento.ativo else (
                "Pagamento parcial" if pagamento.parcial else "Pagamento"
            )
            eventos.append(
                Evento(
                    pagamento.data,
                    situacao,
                    f"{rotulo} – {formatar_moeda(pagamento.valor_pago)}"
                    + (
                        f" (juros {formatar_moeda(pagamento.juros_cobrados)}"
                        f", {pagamento.dias_atraso} dia(s) de atraso)"
                        if pagamento.dias_atraso
                        else ""
                    ),
                )
            )
        for cobranca in honorario.cobrancas:
            if not cobranca.ativa:
                continue
            detalhe = cobranca.resultado.rotulo
            if cobranca.promessa_data:
                detalhe += f" em {cobranca.promessa_data:%d/%m/%Y}"
            if cobranca.observacao:
                detalhe += f" · {cobranca.observacao}"
            eventos.append(
                Evento(
                    cobranca.data_hora.date(),
                    "Cobrança",
                    f"{rotulo} – {cobranca.canal.rotulo}: {detalhe}",
                )
            )

    eventos.sort(key=lambda evento: evento.quando, reverse=True)
    return eventos


def extrato(sessao: Session, cliente: Cliente, data_referencia: date | None = None) -> dict:
    """Base do extrato de débitos em PDF."""
    dados = resumo(sessao, cliente, data_referencia)
    return {
        "cliente": cliente,
        "referencia": data_referencia or hoje(),
        "linhas": dados.pendentes,
        "total": dados.total_em_aberto,
        "juros_dia": dados.juros_dia,
    }


__all__ = [
    "Evento",
    "Resumo",
    "StatusPagamento",
    "calculo",
    "extrato",
    "linha_do_tempo",
    "pagos_com_atraso",
    "resumo",
]
