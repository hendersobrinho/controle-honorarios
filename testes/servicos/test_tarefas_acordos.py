"""Tarefas: acompanhar o pagamento dos acordos feitos no Cobrar."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from honorarios.dominio.valores import Competencia
from honorarios.servicos import acordos, pagamentos, tarefas
from testes import fabricas

REFERENCIA = date(2026, 10, 16)


@pytest.fixture
def cliente(sessao):
    cliente = fabricas.cliente(sessao, juros_dia="1.00")
    cliente.juros[0].vigencia_inicio = date(2020, 1, 1)
    fabricas.honorario(sessao, cliente, valor="500.00", vencimento=date(2026, 8, 10),
                       competencia=Competencia(2026, 7))
    fabricas.honorario(sessao, cliente, valor="300.00", vencimento=date(2026, 9, 10),
                       competencia=Competencia(2026, 8))
    sessao.commit()
    return cliente


def _acordo(sessao, cliente, valido_ate=date(2026, 10, 25), honorarios=None):
    honorarios = honorarios or list(cliente.honorarios)
    criados = acordos.registrar(sessao, honorarios, REFERENCIA, valido_ate)
    sessao.commit()
    return criados


def test_acordo_vira_tarefa_ate_a_data_combinada(sessao, cliente):
    assert tarefas.quadro(sessao, REFERENCIA).acordos == []
    criados = _acordo(sessao, cliente)

    quadro = tarefas.quadro(sessao, REFERENCIA)
    [tarefa] = quadro.acordos                         # os dois honorários: uma tarefa só
    assert tarefa.cliente is cliente
    assert tarefa.vencimento == date(2026, 10, 25)
    assert tarefa.total == sum((Decimal(a.total) for a in criados), start=Decimal(0))
    assert tarefa.chave == f"acordo:{min(a.id for a in criados)}"
    assert "até 25/10/2026" in tarefa.descricao
    assert tarefas.contar_pendentes(sessao, REFERENCIA) == 1


def test_passado_o_prazo_continua_na_lista(sessao, cliente):
    _acordo(sessao, cliente)
    [tarefa] = tarefas.quadro(sessao, date(2026, 11, 3)).acordos
    assert tarefa.dias_esperando(date(2026, 11, 3)) == 9


def test_pago_sai_sozinho(sessao, cliente):
    _acordo(sessao, cliente)
    for honorario in list(cliente.honorarios):
        previa = pagamentos.previa(honorario, REFERENCIA)
        pagamentos.registrar(sessao, honorario, pagamentos.DadosPagamento(
            data=REFERENCIA, valor_pago=previa.total_devido))
    sessao.commit()
    quadro = tarefas.quadro(sessao, REFERENCIA)
    assert quadro.acordos == [] and quadro.acordos_feitos == []


def test_pago_em_parte_mostra_o_que_falta(sessao, cliente):
    _acordo(sessao, cliente)
    primeiro = min(cliente.honorarios, key=lambda h: h.vencimento)
    previa = pagamentos.previa(primeiro, REFERENCIA)
    pagamentos.registrar(sessao, primeiro, pagamentos.DadosPagamento(
        data=REFERENCIA, valor_pago=previa.total_devido))
    sessao.commit()
    [tarefa] = tarefas.quadro(sessao, REFERENCIA).acordos
    assert len(tarefa.em_aberto) == 1 and len(tarefa.honorarios) == 2


def test_acordo_novo_substitui_o_antigo(sessao, cliente):
    _acordo(sessao, cliente)
    _acordo(sessao, cliente, valido_ate=date(2026, 10, 30))
    [tarefa] = tarefas.quadro(sessao, REFERENCIA).acordos
    assert tarefa.vencimento == date(2026, 10, 30)


def test_baixa_e_desfazer(sessao, cliente):
    _acordo(sessao, cliente)
    [tarefa] = tarefas.quadro(sessao, REFERENCIA).acordos
    tarefas.concluir(sessao, tarefa, "cliente avisou que paga dia 25")
    sessao.commit()
    quadro = tarefas.quadro(sessao, REFERENCIA)
    assert quadro.acordos == [] and [t.chave for t in quadro.acordos_feitos] == [tarefa.chave]
    assert quadro.acordos_feitos[0].feita.periodo_fim == date(2026, 10, 25)
    tarefas.reabrir(sessao, tarefa.chave)
    sessao.commit()
    assert [t.chave for t in tarefas.quadro(sessao, REFERENCIA).acordos] == [tarefa.chave]
