"""Juros acertado à mão no Editar do honorário: vale no dia e segue somando."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from honorarios.dominio.enums import FormaPagamento
from honorarios.infra.modelos import LogAlteracao
from honorarios.servicos import calculo, pagamentos
from honorarios.servicos import honorarios as servico
from honorarios.servicos.erros import ErroDeValidacao
from testes import fabricas

DIA_DO_ACERTO = date(2026, 9, 29)   # 10 dias de atraso: o cálculo dá R$ 10,10


@pytest.fixture
def honorario(sessao):
    cliente = fabricas.cliente(sessao, juros_dia="1.01")
    cliente.juros[0].vigencia_inicio = date(2020, 1, 1)
    sessao.commit()
    return fabricas.honorario(sessao, cliente, valor="1000.00", vencimento=date(2026, 9, 19))


def test_juros_digitado_vale_no_lugar_do_calculado(sessao, honorario):
    servico.ajustar_juros(sessao, honorario, Decimal("15.00"), DIA_DO_ACERTO)
    atual = calculo.atualizar(honorario, DIA_DO_ACERTO)
    assert (atual.juros, atual.total) == (Decimal("15.00"), Decimal("1015.00"))
    assert atual.juros_manual and atual.juros_calculado == Decimal("10.10")


def test_os_dias_seguintes_continuam_somando_por_cima(sessao, honorario):
    servico.ajustar_juros(sessao, honorario, Decimal("15.00"), DIA_DO_ACERTO)
    # 5 dias depois: 15,00 + 5 × 1,01
    assert calculo.atualizar(honorario, date(2026, 10, 4)).juros == Decimal("20.05")
    # antes do acerto (simulação de data passada) vale o calculado
    assert calculo.atualizar(honorario, date(2026, 9, 25)).juros == Decimal("6.06")


def test_acertar_so_os_centavos_e_voltar_ao_calculado(sessao, honorario):
    # tira só os 10 centavos
    servico.ajustar_juros(sessao, honorario, Decimal("10.00"), DIA_DO_ACERTO)
    assert calculo.atualizar(honorario, DIA_DO_ACERTO).total == Decimal("1010.00")
    servico.ajustar_juros(sessao, honorario, None, DIA_DO_ACERTO)
    atual = calculo.atualizar(honorario, DIA_DO_ACERTO)
    assert (atual.juros, atual.juros_manual) == (Decimal("10.10"), False)
    acoes = [log.acao for log in sessao.query(LogAlteracao).filter_by(entidade_id=honorario.id)]
    assert acoes.count("AJUSTAR_JUROS") == 2


def test_juros_zerado_a_mao(sessao, honorario):
    servico.ajustar_juros(sessao, honorario, Decimal("0"), DIA_DO_ACERTO)
    atual = calculo.atualizar(honorario, DIA_DO_ACERTO)
    assert (atual.juros, atual.total) == (Decimal("0.00"), Decimal("1000.00"))


def test_juros_negativo_ou_honorario_pago_recusam(sessao, honorario):
    with pytest.raises(ErroDeValidacao):
        servico.ajustar_juros(sessao, honorario, Decimal("-1"), DIA_DO_ACERTO)
    pagamentos.registrar(sessao, honorario, pagamentos.DadosPagamento(
        data=DIA_DO_ACERTO, valor_pago=Decimal("1010.10"), forma_pagamento=FormaPagamento.PIX))
    with pytest.raises(ErroDeValidacao):
        servico.ajustar_juros(sessao, honorario, Decimal("5"), DIA_DO_ACERTO)


def test_baixa_sugere_o_total_com_o_juros_acertado(sessao, honorario):
    servico.ajustar_juros(sessao, honorario, Decimal("12.00"), DIA_DO_ACERTO)
    atual = calculo.atualizar(honorario, DIA_DO_ACERTO)
    assert atual.total == Decimal("1012.00")
    assert "Juros digitados à mão: R$ 12,00 (o cálculo dava R$ 10,10)" in calculo.explicar(atual)


def test_mesmo_valor_de_novo_nao_regrava(sessao, honorario):
    servico.ajustar_juros(sessao, honorario, Decimal("15.00"), DIA_DO_ACERTO)
    servico.ajustar_juros(sessao, honorario, Decimal("15.00"), date(2026, 10, 2))
    assert honorario.juros_ajustado_em == DIA_DO_ACERTO
    acoes = [log.acao for log in sessao.query(LogAlteracao).filter_by(entidade_id=honorario.id)]
    assert acoes.count("AJUSTAR_JUROS") == 1


def test_vencimento_para_a_frente_tira_o_acerto_antigo(sessao, honorario):
    servico.ajustar_juros(sessao, honorario, Decimal("40.00"), DIA_DO_ACERTO)
    honorario.vencimento = date(2026, 11, 30)          # remarcado: no prazo de novo
    atual = calculo.atualizar(honorario, date(2026, 10, 5))
    assert (atual.juros, atual.juros_manual) == (Decimal("0.00"), False)
