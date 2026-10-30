"""Tarefas do honorário trimestral, contado da entrada da empresa no escritório."""

from __future__ import annotations

from datetime import date

import pytest

from honorarios.dominio.enums import Periodicidade
from honorarios.servicos import contratos, tarefas
from honorarios.servicos.erros import ErroDeValidacao
from testes import fabricas


@pytest.fixture
def trimestral(sessao):
    """Entrou em 15/08/2025, com honorário trimestral."""
    cliente = fabricas.cliente(sessao, codigo="500", nome="TRIMESTRAL EXEMPLO LTDA")
    cliente.cliente_desde = date(2025, 8, 15)
    contrato = fabricas.contrato(sessao, cliente, valor="900.00",
                                 periodicidade=Periodicidade.TRIMESTRAL)
    sessao.commit()
    return cliente, contrato


def test_trimestre_conta_da_competencia_de_entrada(sessao, trimestral):
    quadro = tarefas.quadro(sessao, date(2026, 2, 10))

    # 08–10/2025 completou e venceu em 01/11; 11/2025–01/2026, em 01/02/2026
    assert [t.periodo for t in quadro.pendentes] == ["08/2025 a 10/2025",
                                                     "11/2025 a 01/2026"]
    assert [t.prazo for t in quadro.pendentes] == [date(2025, 11, 1), date(2026, 2, 1)]
    assert [(t.periodo, t.prazo) for t in quadro.proximas] == [
        ("02/2026 a 04/2026", date(2026, 5, 1))]
    assert quadro.pendentes[0].dias_esperando(date(2026, 2, 10)) == 101


def test_no_dia_seguinte_ao_trimestre_a_tarefa_aparece(sessao, trimestral):
    antes = tarefas.quadro(sessao, date(2025, 10, 31))
    depois = tarefas.quadro(sessao, date(2025, 11, 1))
    assert antes.pendentes == [] and antes.proximas[0].prazo == date(2025, 11, 1)
    assert [t.periodo for t in depois.pendentes] == ["08/2025 a 10/2025"]


def test_dar_baixa_e_desfazer(sessao, trimestral):
    referencia = date(2026, 2, 10)
    [primeira, segunda] = tarefas.quadro(sessao, referencia).pendentes

    tarefas.concluir(sessao, primeira, "mandado por e-mail")
    sessao.commit()
    quadro = tarefas.quadro(sessao, referencia)
    assert [t.periodo for t in quadro.pendentes] == [segunda.periodo]
    assert [t.feita.observacao for t in quadro.feitas] == ["mandado por e-mail"]
    with pytest.raises(ErroDeValidacao, match="já teve baixa"):
        tarefas.concluir(sessao, quadro.feitas[0])

    tarefas.reabrir(sessao, primeira.chave)
    sessao.commit()
    assert len(tarefas.quadro(sessao, referencia).pendentes) == 2


def test_so_os_ultimos_doze_meses_e_so_trimestral_ativo(sessao, trimestral):
    cliente, contrato = trimestral
    cliente.cliente_desde = date(2020, 1, 10)
    mensal = fabricas.cliente(sessao, codigo="501", nome="MENSAL LTDA", documento="")
    mensal.cliente_desde = date(2025, 1, 1)
    fabricas.contrato(sessao, mensal)
    sessao.commit()

    quadro = tarefas.quadro(sessao, date(2026, 2, 10))
    assert all(t.prazo >= date(2025, 2, 10) for t in quadro.pendentes)
    assert len(quadro.pendentes) == 4
    assert {t.cliente.codigo for t in quadro.pendentes + quadro.proximas} == {"500"}

    contratos.suspender(sessao, contrato)
    sessao.commit()
    assert tarefas.quadro(sessao, date(2026, 2, 10)).pendentes == []


def test_trimestral_sem_data_de_entrada_e_avisado(sessao, trimestral):
    cliente, _ = trimestral
    cliente.cliente_desde = None
    sessao.commit()
    quadro = tarefas.quadro(sessao, date(2026, 2, 10))
    assert quadro.pendentes == [] and quadro.sem_data == [cliente]
