"""Dias úteis: fim de semana e feriados nacionais, do Espírito Santo e de Vila Velha.

O vencimento gerado pelo contrato que cai em sábado, domingo ou feriado vai para
o próximo dia útil (como o boleto do banco), e o juros só conta a partir dele.

Feriados móveis saem da Páscoa: Carnaval (segunda e terça, -48 e -47 dias),
Sexta-feira Santa (-2), Corpus Christi (+60) e Nossa Senhora da Penha, padroeira
do ES (segunda-feira oito dias depois da Páscoa, +8).
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

# (mês, dia) fixos
NACIONAIS = {
    (1, 1): "Confraternização Universal",
    (4, 21): "Tiradentes",
    (5, 1): "Dia do Trabalho",
    (9, 7): "Independência",
    (10, 12): "Nossa Senhora Aparecida",
    (11, 2): "Finados",
    (11, 15): "Proclamação da República",
    (11, 20): "Dia Nacional de Zumbi e da Consciência Negra",
    (12, 25): "Natal",
}
VILA_VELHA = {
    (5, 23): "Colonização do Solo Espírito-Santense (Vila Velha)",
}


def pascoa(ano: int) -> date:
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher, calendário gregoriano)."""
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    mes, dia = divmod(h + m - 7 * n + 114, 31)
    return date(ano, mes, dia + 1)


@lru_cache(maxsize=64)
def feriados(ano: int) -> dict[date, str]:
    datas = {date(ano, mes, dia): nome for (mes, dia), nome in NACIONAIS.items()}
    datas.update({date(ano, mes, dia): nome for (mes, dia), nome in VILA_VELHA.items()})
    domingo = pascoa(ano)
    for dias, nome in (
        (-48, "Carnaval"),
        (-47, "Carnaval"),
        (-2, "Sexta-feira Santa"),
        (8, "Nossa Senhora da Penha (ES)"),
        (60, "Corpus Christi"),
    ):
        datas[domingo + timedelta(days=dias)] = nome
    return datas


def dia_util(data: date) -> bool:
    return data.weekday() < 5 and data not in feriados(data.year)


def proximo_dia_util(data: date) -> date:
    """A própria data, se for dia útil; senão, o próximo dia útil."""
    while not dia_util(data):
        data += timedelta(days=1)
    return data
