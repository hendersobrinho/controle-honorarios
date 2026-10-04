"""Dias úteis: fim de semana e feriados (nacionais, ES e Vila Velha)."""

from __future__ import annotations

from datetime import date

from honorarios.dominio.feriados import feriados, pascoa, proximo_dia_util


def test_pascoa():
    assert pascoa(2026) == date(2026, 4, 5)
    assert pascoa(2027) == date(2027, 3, 28)


def test_feriados_moveis_e_fixos_de_2026():
    dias = feriados(2026)
    assert dias[date(2026, 2, 16)] == dias[date(2026, 2, 17)] == "Carnaval"
    assert dias[date(2026, 4, 3)] == "Sexta-feira Santa"
    assert dias[date(2026, 4, 13)] == "Nossa Senhora da Penha (ES)"
    assert dias[date(2026, 6, 4)] == "Corpus Christi"
    assert date(2026, 5, 23) in dias and date(2026, 11, 20) in dias


def test_proximo_dia_util():
    assert proximo_dia_util(date(2026, 10, 7)) == date(2026, 10, 7)    # quarta
    assert proximo_dia_util(date(2026, 10, 10)) == date(2026, 10, 13)  # sáb → (12 é feriado) ter
    assert proximo_dia_util(date(2026, 1, 10)) == date(2026, 1, 12)    # sábado → segunda
    assert proximo_dia_util(date(2026, 4, 3)) == date(2026, 4, 6)      # Sexta Santa → segunda
