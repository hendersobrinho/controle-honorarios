"""Recorte de período do histórico de pagos, feito na consulta."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from honorarios.dominio.valores import Competencia
from honorarios.servicos import honorarios as servico
from honorarios.servicos import pagamentos
from honorarios.servicos.honorarios import Filtro
from testes import fabricas


@pytest.fixture
def pagos(sessao):
    cliente = fabricas.cliente(sessao, juros_dia="0.00")
    cliente.juros[0].vigencia_inicio = date(2020, 1, 1)
    sessao.commit()
    criados = []
    for mes, dia_pagamento in ((3, date(2026, 4, 10)), (6, date(2026, 7, 10)),
                               (8, date(2026, 9, 10))):
        honorario = fabricas.honorario(
            sessao,
            cliente,
            valor="500.00",
            vencimento=date(2026, mes + 1, 5),
            competencia=Competencia(2026, mes),
        )
        pagamentos.registrar(
            sessao,
            honorario,
            pagamentos.DadosPagamento(data=dia_pagamento, valor_pago=Decimal("500.00")),
        )
        criados.append(honorario)
    sessao.commit()
    return cliente, criados


def test_periodo_corta_pelo_mes_do_pagamento(sessao, pagos):
    todos = servico.pagos(sessao, Filtro(data_referencia=date(2026, 9, 30)))
    assert len(todos) == 3

    recentes = servico.pagos(
        sessao, Filtro(pago_de=date(2026, 7, 1), data_referencia=date(2026, 9, 30))
    )
    assert [linha.honorario.pago_em for linha in recentes] == [
        date(2026, 7, 10),
        date(2026, 9, 10),
    ]


def test_sem_data_de_pagamento_usa_o_vencimento(sessao, pagos):
    """Honorário importado da planilha antiga não tem data de pagamento."""
    cliente, criados = pagos
    antigo = criados[0]
    antigo.pago_em = None          # como fica na importação
    sessao.commit()

    dentro = servico.pagos(
        sessao, Filtro(pago_de=date(2026, 4, 1), data_referencia=date(2026, 9, 30))
    )
    assert antigo.id in [linha.honorario.id for linha in dentro]

    fora = servico.pagos(
        sessao, Filtro(pago_de=date(2026, 8, 1), data_referencia=date(2026, 9, 30))
    )
    assert antigo.id not in [linha.honorario.id for linha in fora]


def test_agrupamento_avisa_quando_a_data_e_estimada(sessao, pagos):
    _, criados = pagos
    criados[0].pago_em = None
    sessao.commit()
    linhas = servico.pagos(sessao, Filtro(data_referencia=date(2026, 9, 30)))
    rotulos = [rotulo for rotulo, _ in servico.agrupar_por_mes_pagamento(linhas)]
    assert "Set/2026" in rotulos
    assert any("sem data de pagamento" in rotulo for rotulo in rotulos)
