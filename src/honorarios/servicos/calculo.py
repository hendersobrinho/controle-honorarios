"""Ponte entre o banco e o cálculo de juros do domínio.

Toda tela que mostra "total atualizado" passa por aqui, para não existirem duas
versões da regra.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal

from ..dominio.enums import StatusPagamento
from ..dominio.juros import (
    AbatimentoParcial,
    SegmentoJuros,
    TaxaVigente,
    calcular_juros_com_parciais,
    dias_em_atraso,
)
from ..dominio.valores import ZERO, arredondar, dinheiro, formatar_data, formatar_moeda, hoje
from ..infra.modelos import Cliente, Honorario


@dataclass(frozen=True)
class Atualizacao:
    """Fotografia de um honorário numa data de referência."""

    honorario_id: int | None
    data_referencia: date
    status: StatusPagamento
    valor_original: Decimal
    saldo: Decimal
    juros: Decimal
    total: Decimal
    dias_atraso: int
    segmentos: tuple[SegmentoJuros, ...] = field(default_factory=tuple)
    congelado: bool = False
    # preenchido quando o juros foi digitado à mão: o que o cálculo dava
    juros_calculado: Decimal | None = None

    @property
    def em_atraso(self) -> bool:
        return self.dias_atraso > 0 and not self.congelado

    @property
    def juros_manual(self) -> bool:
        return self.juros_calculado is not None

    @property
    def parcialmente_pago(self) -> bool:
        return self.saldo > 0 and self.saldo < self.valor_original


def taxas_do_cliente(cliente: Cliente) -> tuple[TaxaVigente, ...]:
    return tuple(
        TaxaVigente(vigencia_inicio=linha.vigencia_inicio, valor_dia=Decimal(str(linha.valor_dia)))
        for linha in sorted(cliente.juros, key=lambda linha: linha.vigencia_inicio)
    )


def taxa_vigente_em(cliente: Cliente, referencia: date | None = None) -> Decimal:
    referencia = referencia or hoje()
    atual = ZERO
    for taxa in taxas_do_cliente(cliente):
        if taxa.vigencia_inicio <= referencia:
            atual = taxa.valor_dia
    taxas = taxas_do_cliente(cliente)
    if taxas and referencia < taxas[0].vigencia_inicio:
        return taxas[0].valor_dia  # ver docs/DECISOES.md
    return atual


def _parciais(honorario: Honorario) -> list[AbatimentoParcial]:
    return [
        AbatimentoParcial(
            data=pagamento.data,
            principal_abatido=dinheiro(pagamento.principal_abatido),
            juros_cobrados=dinheiro(pagamento.juros_cobrados),
            juros_abonados=dinheiro(pagamento.desconto),
        )
        for pagamento in honorario.pagamentos
        if pagamento.ativo
    ]


def atualizar(
    honorario: Honorario,
    data_referencia: date | None = None,
    taxas: Sequence[TaxaVigente] | None = None,
) -> Atualizacao:
    """Total atualizado do honorário na data pedida.

    Pago, cancelado e renegociado não recalculam nada: o que ficou registrado na
    baixa está congelado (item 5.3).
    """
    referencia = data_referencia or hoje()
    if taxas is None:
        taxas = taxas_do_cliente(honorario.cliente)

    valor_original = dinheiro(honorario.valor_original)
    saldo = dinheiro(honorario.saldo_aberto)

    if honorario.status is StatusPagamento.PAGO:
        pagos = [p for p in honorario.pagamentos if p.ativo]
        ultimo = pagos[-1] if pagos else None
        return Atualizacao(
            honorario_id=honorario.id,
            data_referencia=referencia,
            status=honorario.status,
            valor_original=valor_original,
            saldo=ZERO,
            juros=sum((dinheiro(p.juros_cobrados) for p in pagos), start=ZERO),
            total=dinheiro(honorario.total_congelado)
            if honorario.total_congelado is not None
            else sum((dinheiro(p.total) for p in pagos), start=ZERO),
            dias_atraso=ultimo.dias_atraso if ultimo else 0,
            congelado=True,
        )

    if honorario.status in (StatusPagamento.CANCELADO, StatusPagamento.RENEGOCIADO):
        return Atualizacao(
            honorario_id=honorario.id,
            data_referencia=referencia,
            status=honorario.status,
            valor_original=valor_original,
            saldo=ZERO,
            juros=ZERO,
            total=ZERO,
            dias_atraso=0,
            congelado=True,
        )

    resultado = calcular_juros_com_parciais(
        vencimento=honorario.vencimento,
        data_referencia=referencia,
        taxas=taxas,
        valor_original=valor_original,
        parciais=_parciais(honorario),
    )
    return Atualizacao(
        honorario_id=honorario.id,
        data_referencia=referencia,
        status=honorario.status,
        valor_original=valor_original,
        saldo=saldo,
        juros=resultado.juros,
        total=saldo + resultado.juros,
        dias_atraso=dias_em_atraso(honorario.vencimento, referencia),
        segmentos=resultado.segmentos,
    )


def atualizar_varios(
    honorarios: Iterable[Honorario], data_referencia: date | None = None
) -> dict[int, Atualizacao]:
    """Calcula em lote reaproveitando o histórico de juros por cliente."""
    referencia = data_referencia or hoje()
    cache: dict[int, tuple[TaxaVigente, ...]] = {}
    resultado: dict[int, Atualizacao] = {}
    for honorario in honorarios:
        taxas = cache.get(honorario.cliente_id)
        if taxas is None:
            taxas = taxas_do_cliente(honorario.cliente)
            cache[honorario.cliente_id] = taxas
        resultado[honorario.id] = atualizar(honorario, referencia, taxas)
    return resultado


def total_em_aberto(
    honorarios: Iterable[Honorario], data_referencia: date | None = None
) -> Decimal:
    atualizacoes = atualizar_varios(honorarios, data_referencia)
    return sum(
        (a.total for a in atualizacoes.values() if a.status is StatusPagamento.EM_ABERTO),
        start=ZERO,
    )


def com_juros_manual(atualizacao: Atualizacao, juros: Decimal | None) -> Atualizacao:
    """O mesmo honorário com o juros digitado à mão (None volta ao calculado).

    O total passa a ser saldo + juros digitado; o calculado fica guardado para a
    conferência mostrar a diferença.
    """
    calculado = atualizacao.juros_calculado if atualizacao.juros_manual else atualizacao.juros
    if juros is None:
        return replace(atualizacao, juros=calculado, total=atualizacao.saldo + calculado,
                       juros_calculado=None)
    juros = dinheiro(juros)
    if juros < 0:
        raise ValueError("O juros não pode ser negativo.")
    return replace(atualizacao, juros=juros, total=atualizacao.saldo + juros,
                   juros_calculado=calculado)


def explicar(atualizacao: Atualizacao) -> list[str]:
    """A conta dos juros em palavras, para conferir na tela de cobrança.

    Uma linha por faixa de juros/dia ("10 dias × R$ 1,01 por dia = R$ 10,10"), o
    abatimento de pagamento parcial, quando houver, e a soma final.
    """
    if atualizacao.congelado:
        return [f"{atualizacao.status.rotulo}: sem juros a cobrar."]
    linhas = []
    if atualizacao.dias_atraso == 0:
        linhas.append("Ainda no prazo: sem juros.")
    else:
        bruto = ZERO
        for segmento in atualizacao.segmentos:
            conta = (f"{segmento.dias} dia{'s' if segmento.dias > 1 else ''} × "
                     f"{formatar_moeda(segmento.valor_dia)} por dia")
            if segmento.proporcao != 1:
                conta += f" × {segmento.proporcao * 100:.0f}% (só o saldo, após pagamento parcial)"
            conta += (f" = {formatar_moeda(arredondar(segmento.juros))}"
                      f"  ({formatar_data(segmento.inicio)} a {formatar_data(segmento.fim)})")
            linhas.append(conta)
            bruto += segmento.juros
        calculado = atualizacao.juros_calculado if atualizacao.juros_manual \
            else atualizacao.juros
        ja_cobrado = arredondar(bruto) - calculado
        if ja_cobrado > 0:
            linhas.append(f"− {formatar_moeda(ja_cobrado)} de juros já cobrados ou abonados "
                          "em pagamentos parciais")
        if len(atualizacao.segmentos) > 1 or ja_cobrado > 0:
            linhas.append(f"Juros calculados: {formatar_moeda(calculado)}")
    if atualizacao.juros_manual:
        linhas.append(f"Juros digitados à mão: {formatar_moeda(atualizacao.juros)} "
                      f"(o cálculo dava {formatar_moeda(atualizacao.juros_calculado)})")
    linhas.append(f"{formatar_moeda(atualizacao.saldo)} + {formatar_moeda(atualizacao.juros)}"
                  f" de juros = {formatar_moeda(atualizacao.total)}")
    return linhas
