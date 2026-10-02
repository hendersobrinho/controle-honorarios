"""Baixa de pagamento, com congelamento dos valores (item 5.3).

Depois da baixa, mudar o juros do cliente não altera nada aqui: o que está
gravado no pagamento é o que aconteceu.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from ..dominio.enums import FormaPagamento, StatusPagamento
from ..dominio.valores import ZERO, agora_utc, dinheiro, formatar_moeda, hoje
from ..infra.modelos import Honorario, LogAlteracao, Pagamento
from . import calculo
from .erros import ErroDeValidacao


@dataclass
class DadosPagamento:
    data: date
    valor_pago: Decimal
    juros_cobrados: Decimal | None = None
    desconto: Decimal = ZERO
    justificativa_desconto: str = ""
    forma_pagamento: FormaPagamento = FormaPagamento.PIX
    observacoes: str = ""


@dataclass
class Previa:
    """O que a tela de baixa mostra antes de confirmar."""

    dias_atraso: int
    saldo: Decimal
    juros_devidos: Decimal
    total_devido: Decimal
    sugestao_valor: Decimal
    # acordo vigente na data do pagamento: o juros combinado e o texto do abono
    juros_acordo: Decimal | None = None
    justificativa_acordo: str = ""


def previa(honorario: Honorario, data_pagamento: date | None = None) -> Previa:
    from . import acordos

    referencia = data_pagamento or hoje()
    atualizacao = calculo.atualizar(honorario, referencia)
    resultado = Previa(
        dias_atraso=atualizacao.dias_atraso,
        saldo=atualizacao.saldo,
        juros_devidos=atualizacao.juros,
        total_devido=atualizacao.total,
        sugestao_valor=atualizacao.total,
    )
    acordo = acordos.vigente(honorario, referencia)
    if acordo is not None:
        # dentro do prazo vale o juros congelado; a diferença vira abono justificado
        resultado.juros_acordo = min(dinheiro(acordo.juros), atualizacao.juros)
        resultado.sugestao_valor = atualizacao.saldo + resultado.juros_acordo
        resultado.justificativa_acordo = acordos.descricao(acordo)
    return resultado


def registrar(sessao: Session, honorario: Honorario, dados: DadosPagamento) -> Pagamento:
    if honorario.status is StatusPagamento.PAGO:
        raise ErroDeValidacao("Este honorário já está pago.")
    if honorario.status in (StatusPagamento.CANCELADO, StatusPagamento.RENEGOCIADO):
        raise ErroDeValidacao(
            f"Honorário {honorario.status.rotulo.lower()} não recebe baixa."
        )

    valor_pago = dinheiro(dados.valor_pago)
    if valor_pago <= 0:
        raise ErroDeValidacao("O valor pago deve ser maior que zero.", "valor_pago")
    if dados.data > hoje():
        raise ErroDeValidacao("A data do pagamento não pode ser no futuro.", "data")

    atual = calculo.atualizar(honorario, dados.data)
    juros_devidos = atual.juros
    juros_cobrados = (
        juros_devidos if dados.juros_cobrados is None else dinheiro(dados.juros_cobrados)
    )
    if juros_cobrados < 0:
        raise ErroDeValidacao("Juros cobrados não pode ser negativo.", "juros_cobrados")
    if juros_cobrados > valor_pago:
        raise ErroDeValidacao(
            "Os juros cobrados não podem ser maiores que o valor pago.", "juros_cobrados"
        )
    if juros_cobrados > juros_devidos:
        raise ErroDeValidacao(
            f"Juros cobrados ({formatar_moeda(juros_cobrados)}) maior que o devido "
            f"({formatar_moeda(juros_devidos)}).",
            "juros_cobrados",
        )

    desconto = dinheiro(dados.desconto) if dados.desconto else juros_devidos - juros_cobrados
    if desconto > 0 and not (dados.justificativa_desconto or "").strip():
        raise ErroDeValidacao(
            f"Abono de {formatar_moeda(desconto)} em juros exige justificativa.",
            "justificativa_desconto",
        )

    principal = valor_pago - juros_cobrados
    saldo_atual = dinheiro(honorario.saldo_aberto)
    if principal > saldo_atual:
        raise ErroDeValidacao(
            f"O pagamento abateria {formatar_moeda(principal)} de principal, mas o "
            f"saldo é {formatar_moeda(saldo_atual)}. Confira o valor e os juros.",
            "valor_pago",
        )

    saldo_final = dinheiro(saldo_atual - principal)
    quitado = saldo_final <= 0 and (juros_devidos - juros_cobrados - desconto) <= 0

    pagamento = Pagamento(
        honorario_id=honorario.id,
        data=dados.data,
        valor_pago=valor_pago,
        principal_abatido=principal,
        dias_atraso=atual.dias_atraso,
        juros_devidos=juros_devidos,
        juros_cobrados=juros_cobrados,
        desconto=desconto,
        justificativa_desconto=(dados.justificativa_desconto or "").strip(),
        total=valor_pago,
        forma_pagamento=dados.forma_pagamento,
        parcial=not quitado,
        observacoes=dados.observacoes or "",
    )
    honorario.pagamentos.append(pagamento)
    honorario.saldo_aberto = max(ZERO, saldo_final)

    if quitado:
        honorario.status = StatusPagamento.PAGO
        honorario.pago_em = dados.data
        honorario.total_congelado = sum(
            (dinheiro(p.total) for p in honorario.pagamentos if p.ativo), start=ZERO
        )
    sessao.add(
        LogAlteracao(
            entidade="honorario",
            entidade_id=honorario.id,
            acao="BAIXA" if quitado else "BAIXA_PARCIAL",
            resumo=(
                f"{formatar_moeda(valor_pago)} em {dados.data:%d/%m/%Y} "
                f"(juros {formatar_moeda(juros_cobrados)}, saldo "
                f"{formatar_moeda(honorario.saldo_aberto)})"
            ),
        )
    )
    sessao.flush()
    return pagamento


def estornar(sessao: Session, pagamento: Pagamento, motivo: str) -> None:
    """Estorno em vez de exclusão: o registro fica, marcado."""
    if not (motivo or "").strip():
        raise ErroDeValidacao("Descreva o motivo do estorno.", "motivo")
    if not pagamento.ativo:
        raise ErroDeValidacao("Este pagamento já está estornado.")
    pagamento.estornado_em = agora_utc()
    pagamento.motivo_estorno = motivo.strip()

    honorario = pagamento.honorario
    abatido = sum(
        (dinheiro(p.principal_abatido) for p in honorario.pagamentos if p.ativo), start=ZERO
    )
    honorario.saldo_aberto = max(ZERO, dinheiro(honorario.valor_original) - abatido)
    if honorario.saldo_aberto > 0 or not any(p.ativo for p in honorario.pagamentos):
        honorario.status = StatusPagamento.EM_ABERTO
        honorario.pago_em = None
        honorario.total_congelado = None
    sessao.add(
        LogAlteracao(
            entidade="pagamento",
            entidade_id=pagamento.id,
            acao="ESTORNO",
            resumo=motivo.strip(),
        )
    )
    sessao.flush()


def pagos_com_atraso(honorario: Honorario) -> bool:
    return any(p.ativo and p.dias_atraso > 0 for p in honorario.pagamentos)
