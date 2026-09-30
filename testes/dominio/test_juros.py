"""Cálculo de juros: o cerne do sistema."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from honorarios.dominio.juros import (
    AbatimentoParcial,
    TaxaVigente,
    calcular_juros,
    calcular_juros_com_parciais,
    dias_em_atraso,
)


def taxa(valor, inicio=date(2020, 1, 1)):
    return TaxaVigente(vigencia_inicio=inicio, valor_dia=Decimal(valor))


def test_exemplo_da_especificacao():
    """Vencimento 01/09, 0,50 até 14/09 e 1,00 a partir de 15/09, hoje 20/09."""
    resultado = calcular_juros(
        date(2026, 9, 1),
        date(2026, 9, 20),
        [taxa("0.50"), taxa("1.00", date(2026, 9, 15))],
    )
    assert resultado.dias_atraso == 19
    assert resultado.juros == Decimal("12.50")
    assert [(s.dias, s.valor_dia) for s in resultado.segmentos] == [
        (13, Decimal("0.50")),
        (6, Decimal("1.00")),
    ]


def test_paridade_com_a_planilha():
    """ROUND(dias * juros; 2) da coluna "Juros até Hoje"."""
    resultado = calcular_juros(date(2026, 7, 6), date(2026, 7, 30), [taxa("1.01")])
    assert resultado.dias_atraso == 24
    assert resultado.juros == Decimal("24.24")


def test_vencimento_hoje_nao_tem_juros():
    resultado = calcular_juros(date(2026, 9, 29), date(2026, 9, 29), [taxa("2.16")])
    assert resultado.dias_atraso == 0
    assert resultado.juros == Decimal("0.00")
    assert resultado.segmentos == ()


def test_vencimento_futuro_nao_tem_juros():
    resultado = calcular_juros(date(2026, 10, 10), date(2026, 9, 29), [taxa("2.16")])
    assert resultado.dias_atraso == 0
    assert resultado.juros == Decimal("0.00")


def test_virada_de_mes():
    resultado = calcular_juros(date(2026, 8, 30), date(2026, 9, 2), [taxa("0.54")])
    assert resultado.dias_atraso == 3
    assert resultado.juros == Decimal("1.62")


def test_ano_bissexto_conta_29_de_fevereiro():
    resultado = calcular_juros(date(2024, 2, 27), date(2024, 3, 1), [taxa("1.00")])
    assert resultado.dias_atraso == 3  # 28, 29 e 01


def test_taxa_zero():
    resultado = calcular_juros(date(2026, 1, 1), date(2026, 9, 29), [taxa("0")])
    assert resultado.juros == Decimal("0.00")
    assert resultado.dias_atraso == 271


def test_sem_historico_de_taxa_nao_estoura():
    resultado = calcular_juros(date(2026, 9, 1), date(2026, 9, 10), [])
    assert resultado.juros == Decimal("0.00")
    assert resultado.dias_atraso == 9


def test_primeira_taxa_cobre_os_dias_anteriores_a_vigencia():
    """Decisão documentada: a taxa mais antiga vale para trás."""
    resultado = calcular_juros(
        date(2026, 9, 1), date(2026, 9, 11), [taxa("1.00", date(2026, 9, 6))]
    )
    assert resultado.juros == Decimal("10.00")


def test_tres_mudancas_de_taxa_no_meio_do_atraso():
    resultado = calcular_juros(
        date(2026, 1, 31),
        date(2026, 3, 2),
        [
            taxa("0.10", date(2026, 1, 1)),
            taxa("0.20", date(2026, 2, 10)),
            taxa("0.30", date(2026, 2, 20)),
        ],
    )
    # 01..09/02 = 9 x 0,10 | 10..19/02 = 10 x 0,20 | 20/02..02/03 = 11 x 0,30
    assert resultado.dias_atraso == 30
    assert resultado.juros == Decimal("6.20")
    assert sum(s.dias for s in resultado.segmentos) == 30


def test_mudanca_futura_nao_afeta_o_calculo_de_hoje():
    resultado = calcular_juros(
        date(2026, 9, 1),
        date(2026, 9, 10),
        [taxa("1.00"), taxa("5.00", date(2026, 9, 20))],
    )
    assert resultado.juros == Decimal("9.00")


def test_arredondamento_acontece_uma_vez_no_total():
    """3 dias a 0,005: arredondar por segmento daria 0,00 ou 0,03."""
    resultado = calcular_juros(date(2026, 9, 1), date(2026, 9, 4), [taxa("0.005")])
    assert resultado.juros == Decimal("0.02")


def test_dias_em_atraso_nunca_negativo():
    assert dias_em_atraso(date(2026, 10, 1), date(2026, 9, 29)) == 0
    assert dias_em_atraso(None, date(2026, 9, 29)) == 0


def test_atraso_longo_usa_poucos_segmentos():
    resultado = calcular_juros(date(2020, 1, 1), date(2026, 9, 29), [taxa("0.11")])
    assert len(resultado.segmentos) == 1
    assert resultado.dias_atraso == 2463


# --------------------------------------------------------------------- parciais


def test_parcial_reduz_o_juros_na_proporcao_do_saldo():
    """1.000 com 0,67/dia; paga 600 no dia 10/09 -> 0,268/dia sobre 400."""
    resultado = calcular_juros_com_parciais(
        vencimento=date(2026, 8, 1),
        data_referencia=date(2026, 9, 20),
        taxas=[taxa("0.67")],
        valor_original=Decimal("1000.00"),
        parciais=[
            AbatimentoParcial(
                data=date(2026, 9, 10),
                principal_abatido=Decimal("600.00"),
                juros_cobrados=Decimal("26.80"),
            )
        ],
    )
    # 02/08..10/09 = 40 dias x 0,67 = 26,80 (já cobrados)
    # 11/09..20/09 = 10 dias x 0,268 = 2,68
    assert resultado.juros == Decimal("2.68")


def test_parcial_sem_juros_cobrados_mantem_a_divida_de_juros():
    resultado = calcular_juros_com_parciais(
        vencimento=date(2026, 8, 1),
        data_referencia=date(2026, 9, 20),
        taxas=[taxa("0.67")],
        valor_original=Decimal("1000.00"),
        parciais=[
            AbatimentoParcial(date(2026, 9, 10), Decimal("600.00"), Decimal("0.00"))
        ],
    )
    assert resultado.juros == Decimal("29.48")  # 26,80 + 2,68


def test_saldo_zerado_para_de_gerar_juros():
    resultado = calcular_juros_com_parciais(
        vencimento=date(2026, 8, 1),
        data_referencia=date(2026, 9, 20),
        taxas=[taxa("1.00")],
        valor_original=Decimal("500.00"),
        parciais=[
            AbatimentoParcial(date(2026, 8, 11), Decimal("500.00"), Decimal("10.00"))
        ],
    )
    assert resultado.juros == Decimal("0.00")


def test_juros_nunca_fica_negativo():
    resultado = calcular_juros_com_parciais(
        vencimento=date(2026, 9, 1),
        data_referencia=date(2026, 9, 5),
        taxas=[taxa("1.00")],
        valor_original=Decimal("100.00"),
        parciais=[
            AbatimentoParcial(date(2026, 9, 5), Decimal("100.00"), Decimal("50.00"))
        ],
    )
    assert resultado.juros == Decimal("0.00")


def test_taxa_negativa_e_rejeitada():
    with pytest.raises(ValueError):
        TaxaVigente(date(2026, 1, 1), Decimal("-1"))
