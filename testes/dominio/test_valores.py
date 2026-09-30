"""Tipos de valor: dinheiro, competência, documento e telefone."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from honorarios.dominio.valores import (
    Competencia,
    dia_do_mes,
    dinheiro,
    formatar_documento,
    formatar_moeda,
    formatar_telefone,
    ler_data,
    ler_moeda,
    normalizar_busca,
    normalizar_telefone,
    validar_documento,
)


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        (Decimal("1234.5"), "R$ 1.234,50"),
        (0, "R$ 0,00"),
        ("1507.80", "R$ 1.507,80"),
        (1206.7, "R$ 1.206,70"),
        (-45.9, "R$ -45,90"),
        (1234567.89, "R$ 1.234.567,89"),
    ],
)
def test_formatar_moeda(entrada, esperado):
    assert formatar_moeda(entrada) == esperado


def test_ler_moeda_aceita_os_formatos_da_tela():
    assert ler_moeda("R$ 1.507,80") == Decimal("1507.80")
    assert ler_moeda("1507,80") == Decimal("1507.80")
    assert ler_moeda("1507.80") == Decimal("1507.80")
    assert ler_moeda("") == Decimal("0.00")


def test_dinheiro_nao_arrasta_erro_de_float():
    assert dinheiro(0.1) + dinheiro(0.2) == Decimal("0.30")


def test_dinheiro_arredonda_meio_para_cima_como_a_planilha():
    assert dinheiro("1.005") == Decimal("1.01")
    assert dinheiro("2.675") == Decimal("2.68")


@pytest.mark.parametrize(
    "entrada,ano,mes",
    [
        ("02/2026", 2026, 2),
        ("2/2026", 2026, 2),
        ("2026-06", 2026, 6),
        (datetime(2026, 6, 1), 2026, 6),
        (date(2026, 6, 1), 2026, 6),
        (46174, 2026, 6),          # serial do Excel que estava na planilha
        ("IRPF 2026", 2026, None),
        ("Imposto de Renda 2026", 2026, None),
        (2026, 2026, None),
    ],
)
def test_competencia_normaliza_o_que_a_planilha_tinha(entrada, ano, mes):
    competencia = Competencia.de_texto(entrada)
    assert (competencia.ano, competencia.mes) == (ano, mes)


def test_competencia_texto_sem_data_fica_vazia():
    """"ATA DE SOCIOS" estava na coluna Competência: é tipo, não competência."""
    assert Competencia.de_texto("ATA DE SOCIOS").vazia
    assert Competencia.de_texto(None).vazia
    assert Competencia.de_texto("").vazia


def test_competencia_rotulos():
    assert Competencia(2026, 8).rotulo() == "08/2026"
    assert Competencia(2026).rotulo() == "2026"
    assert Competencia().rotulo() == ""
    assert Competencia(2026, 8).rotulo_curto() == "Ago/26"


def test_competencia_proxima_vira_o_ano():
    assert Competencia(2026, 12).proxima() == Competencia(2027, 1)
    assert Competencia(2026, 1).proxima(3) == Competencia(2026, 4)


def test_competencia_mes_invalido():
    with pytest.raises(ValueError):
        Competencia(2026, 13)


def test_dia_do_mes_recua_em_mes_curto():
    assert dia_do_mes(2026, 2, 31) == date(2026, 2, 28)
    assert dia_do_mes(2024, 2, 31) == date(2024, 2, 29)


def test_validar_documento():
    assert validar_documento("529.982.247-25")       # CPF fictício válido
    assert validar_documento("11.222.333/0001-81")   # CNPJ fictício válido
    assert not validar_documento("111.111.111-11")
    assert not validar_documento("529.982.247-26")
    assert not validar_documento("123")
    assert not validar_documento("")


def test_formatar_documento():
    assert formatar_documento("52998224725") == "529.982.247-25"
    assert formatar_documento("11222333000181") == "11.222.333/0001-81"


def test_normalizar_busca_ignora_acento_e_pontuacao():
    assert normalizar_busca("Alteração Contratual Ltda.") == "alteracao contratual ltda"
    assert normalizar_busca("GASTROCENTER VITÓRIA") == "gastrocenter vitoria"


def test_normalizar_telefone_coloca_ddi():
    assert normalizar_telefone("(27) 99999-0000") == "5527999990000"
    assert normalizar_telefone("5527999990000") == "5527999990000"
    assert normalizar_telefone("") == ""


def test_formatar_telefone():
    assert formatar_telefone("5527999990000") == "+55 (27) 99999-0000"


def test_ler_data():
    assert ler_data("08/09/2026") == date(2026, 9, 8)
    with pytest.raises(ValueError):
        ler_data("31/02/2026")
