"""Tarefas: o lembrete de enviar cada parcela dos parcelamentos."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from honorarios.dominio.valores import Competencia
from honorarios.infra.modelos import TipoHonorario
from honorarios.servicos import cobrancas, configuracoes, pagamentos, parcelamentos, tarefas
from testes import fabricas

REFERENCIA = date(2026, 10, 16)


@pytest.fixture
def parcelamento(sessao):
    cliente = fabricas.cliente(sessao, juros_dia="1.00")
    fabricas.honorario(sessao, cliente, valor="900.00", vencimento=date(2026, 7, 19),
                       competencia=Competencia(2026, 6))
    linhas = cobrancas.linhas_em_aberto_do_cliente(sessao, cliente.id, REFERENCIA)
    tipo = sessao.scalar(select(TipoHonorario).where(TipoHonorario.nome == "Parcela de acordo"))
    # vencimentos 20/10, 20/11 e 20/12
    parcelamentos.criar(sessao, cliente, linhas, Decimal("900.00"), 3, date(2026, 10, 20),
                        tipo.id)
    sessao.commit()
    return cliente


def test_lembrete_aparece_dias_antes_do_vencimento(sessao, parcelamento):
    antes = tarefas.quadro(sessao, date(2026, 10, 14))      # 6 dias antes: ainda não
    assert antes.parcelas == []
    assert [t.periodo for t in antes.parcelas_proximas] == ["1/3"]
    assert antes.parcelas_proximas[0].prazo == date(2026, 10, 15)

    quadro = tarefas.quadro(sessao, REFERENCIA)             # 4 dias antes: para enviar
    [tarefa] = quadro.parcelas
    assert (tarefa.periodo, tarefa.vencimento) == ("1/3", date(2026, 10, 20))
    assert [t.periodo for t in quadro.parcelas_proximas] == ["2/3"]   # só a próxima
    assert tarefas.contar_pendentes(sessao, REFERENCIA) == 1


def test_dias_antes_vem_das_configuracoes(sessao, parcelamento):
    configuracoes.gravar(sessao, tarefas.CHAVE_DIAS_PARCELA, "10")
    sessao.commit()
    assert [t.periodo for t in tarefas.quadro(sessao, date(2026, 10, 11)).parcelas] == ["1/3"]


def test_baixa_e_desfazer(sessao, parcelamento):
    [tarefa] = tarefas.quadro(sessao, REFERENCIA).parcelas
    tarefas.concluir(sessao, tarefa, "boleto por e-mail")
    sessao.commit()
    quadro = tarefas.quadro(sessao, REFERENCIA)
    assert quadro.parcelas == [] and [t.periodo for t in quadro.parcelas_feitas] == ["1/3"]
    assert quadro.parcelas_feitas[0].feita.contrato_id is None
    tarefas.reabrir(sessao, tarefa.chave)
    sessao.commit()
    assert len(tarefas.quadro(sessao, REFERENCIA).parcelas) == 1


def test_parcela_paga_nao_pede_envio(sessao, parcelamento):
    [tarefa] = tarefas.quadro(sessao, REFERENCIA).parcelas
    pagamentos.registrar(sessao, tarefa.honorario, pagamentos.DadosPagamento(
        data=REFERENCIA, valor_pago=Decimal("300.00")))
    sessao.commit()
    assert tarefas.quadro(sessao, REFERENCIA).parcelas == []


def test_parcelamento_cancelado_some_das_tarefas(sessao, parcelamento):
    [atual] = parcelamentos.listar(sessao, REFERENCIA)
    parcelamentos.cancelar(sessao, atual, "desistiu")
    sessao.commit()
    quadro = tarefas.quadro(sessao, REFERENCIA)
    assert quadro.parcelas == [] and quadro.parcelas_proximas == []
