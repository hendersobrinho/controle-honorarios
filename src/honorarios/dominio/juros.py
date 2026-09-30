"""Cálculo dos juros de atraso.

Regra (item 5.1 da especificação): os dias em atraso são as datas
``vencimento+1 … data de referência``; para cada dia vale o juros/dia que estava
vigente **naquele dia**, segundo o histórico do cliente. O total é a soma dos
segmentos, arredondada só no fim — é assim que o resultado bate com o
``ROUND(dias * juros; 2)`` da planilha quando existe uma taxa só.

Duas decisões que a especificação não fixava e que estão documentadas em
docs/DECISOES.md:

* Dias anteriores à primeira vigência usam a **primeira** taxa do histórico. Sem
  isso, um cliente cadastrado hoje com um honorário vencido há dois meses teria
  juros zero — o oposto da intenção. Alterações posteriores continuam valendo só
  para frente.
* Em pagamento parcial, o juros/dia passa a valer na proporção
  ``saldo / valor original`` a partir do dia seguinte ao pagamento.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from .valores import ZERO, arredondar, dinheiro


@dataclass(frozen=True, order=True)
class TaxaVigente:
    """Uma linha do histórico de juros do cliente."""

    vigencia_inicio: date
    valor_dia: Decimal

    def __post_init__(self) -> None:
        if self.valor_dia < 0:
            raise ValueError("Juros ao dia não pode ser negativo.")


@dataclass(frozen=True)
class SegmentoJuros:
    inicio: date
    fim: date
    valor_dia: Decimal
    proporcao: Decimal = Decimal(1)

    @property
    def dias(self) -> int:
        return (self.fim - self.inicio).days + 1

    @property
    def juros(self) -> Decimal:
        """Sem arredondar: o arredondamento acontece uma única vez, no total."""
        return self.valor_dia * self.proporcao * self.dias


@dataclass(frozen=True)
class ResultadoJuros:
    dias_atraso: int
    juros: Decimal
    segmentos: tuple[SegmentoJuros, ...] = field(default_factory=tuple)

    @property
    def em_atraso(self) -> bool:
        return self.dias_atraso > 0


def _taxas_ordenadas(taxas: Sequence[TaxaVigente]) -> list[TaxaVigente]:
    return sorted(taxas, key=lambda t: t.vigencia_inicio)


def segmentar(
    primeiro_dia: date,
    ultimo_dia: date,
    taxas: Sequence[TaxaVigente],
    proporcao: Decimal = Decimal(1),
) -> list[SegmentoJuros]:
    """Divide o intervalo em faixas de taxa constante.

    Trabalha por segmento, não dia a dia: o custo depende do número de mudanças
    de taxa, não do tamanho do atraso.
    """
    if primeiro_dia > ultimo_dia:
        return []
    ordenadas = _taxas_ordenadas(taxas)
    if not ordenadas:
        return [SegmentoJuros(primeiro_dia, ultimo_dia, ZERO, proporcao)]

    segmentos: list[SegmentoJuros] = []
    for indice, taxa in enumerate(ordenadas):
        inicio = taxa.vigencia_inicio
        if indice == 0:
            inicio = min(inicio, primeiro_dia)  # primeira taxa cobre o que vem antes
        inicio = max(inicio, primeiro_dia)
        if indice + 1 < len(ordenadas):
            fim = min(ultimo_dia, ordenadas[indice + 1].vigencia_inicio - timedelta(days=1))
        else:
            fim = ultimo_dia
        if inicio > fim:
            continue
        segmentos.append(SegmentoJuros(inicio, fim, taxa.valor_dia, proporcao))
    return segmentos


def dias_em_atraso(vencimento: date | None, data_referencia: date) -> int:
    """``data_referencia - vencimento``, nunca negativo (item 3 da planilha)."""
    if vencimento is None:
        return 0
    return max(0, (data_referencia - vencimento).days)


def calcular_juros(
    vencimento: date | None,
    data_referencia: date,
    taxas: Sequence[TaxaVigente],
    proporcao: Decimal = Decimal(1),
) -> ResultadoJuros:
    """Juros de um honorário sem pagamento parcial."""
    dias = dias_em_atraso(vencimento, data_referencia)
    if dias == 0 or vencimento is None:
        return ResultadoJuros(0, ZERO, ())
    segmentos = segmentar(
        vencimento + timedelta(days=1), data_referencia, taxas, proporcao
    )
    total = sum((s.juros for s in segmentos), start=Decimal(0))
    return ResultadoJuros(dias, arredondar(total), tuple(segmentos))


@dataclass(frozen=True)
class AbatimentoParcial:
    """Pagamento parcial já registrado, na ordem em que aconteceu."""

    data: date
    principal_abatido: Decimal
    juros_cobrados: Decimal = ZERO
    juros_abonados: Decimal = ZERO


def calcular_juros_com_parciais(
    vencimento: date | None,
    data_referencia: date,
    taxas: Sequence[TaxaVigente],
    valor_original: Decimal,
    parciais: Sequence[AbatimentoParcial] = (),
) -> ResultadoJuros:
    """Juros considerando pagamentos parciais.

    Cada parcial reduz o saldo e, a partir do dia seguinte, o juros/dia passa a
    valer na proporção ``saldo / valor original``. O juros já cobrado (ou
    abonado) em parciais anteriores é abatido do total, para não cobrar duas
    vezes o mesmo período.
    """
    dias = dias_em_atraso(vencimento, data_referencia)
    if dias == 0 or vencimento is None:
        return ResultadoJuros(0, ZERO, ())

    valor_original = dinheiro(valor_original)
    if valor_original <= 0:
        return ResultadoJuros(dias, ZERO, ())

    relevantes = sorted(
        (p for p in parciais if p.data <= data_referencia), key=lambda p: p.data
    )
    segmentos: list[SegmentoJuros] = []
    cursor = vencimento + timedelta(days=1)
    saldo = valor_original
    ja_liquidado = ZERO

    for parcial in relevantes:
        limite = max(parcial.data, vencimento)
        if limite >= cursor:
            segmentos.extend(
                segmentar(cursor, limite, taxas, saldo / valor_original)
            )
            cursor = limite + timedelta(days=1)
        saldo = max(ZERO, saldo - dinheiro(parcial.principal_abatido))
        ja_liquidado += dinheiro(parcial.juros_cobrados) + dinheiro(parcial.juros_abonados)

    if cursor <= data_referencia and saldo > 0:
        segmentos.extend(
            segmentar(cursor, data_referencia, taxas, saldo / valor_original)
        )

    total = sum((s.juros for s in segmentos), start=Decimal(0))
    return ResultadoJuros(dias, max(ZERO, arredondar(total) - ja_liquidado), tuple(segmentos))
