"""A conta dos juros em palavras e o juros digitado à mão (tela de cobrança)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from honorarios.servicos import calculo, clientes, cobrancas, imagem_cobranca, pagamentos
from testes import fabricas


@pytest.fixture
def devedor(sessao):
    cliente = fabricas.cliente(sessao, juros_dia="1.01")
    cliente.juros[0].vigencia_inicio = date(2020, 1, 1)
    sessao.commit()
    honorario = fabricas.honorario(sessao, cliente, valor="1000.00", vencimento=date(2026, 9, 19))
    return cliente, honorario


def test_juros_e_juros_por_dia_vezes_os_dias(devedor):
    _, honorario = devedor
    atual = calculo.atualizar(honorario, date(2026, 9, 29))
    assert (atual.dias_atraso, atual.juros, atual.total) == (10, Decimal("10.10"),
                                                             Decimal("1010.10"))
    assert calculo.explicar(atual) == [
        "10 dias × R$ 1,01 por dia = R$ 10,10  (20/09/2026 a 29/09/2026)",
        "R$ 1.000,00 + R$ 10,10 de juros = R$ 1.010,10",
    ]


def test_conta_com_troca_de_juros_por_dia(sessao, devedor):
    cliente, honorario = devedor
    clientes.registrar_juros(sessao, cliente, "2.00", date(2026, 9, 25))
    atual = calculo.atualizar(honorario, date(2026, 9, 29))
    assert atual.juros == Decimal("15.05")   # 5 × 1,01 + 5 × 2,00
    conta = calculo.explicar(atual)
    assert conta[0].startswith("5 dias × R$ 1,01 por dia = R$ 5,05")
    assert conta[1].startswith("5 dias × R$ 2,00 por dia = R$ 10,00")
    assert "Juros calculados: R$ 15,05" in conta


def test_conta_com_pagamento_parcial(sessao, devedor):
    _, honorario = devedor
    pagamentos.registrar(sessao, honorario, pagamentos.DadosPagamento(
        data=date(2026, 9, 24), valor_pago=Decimal("505.05"), juros_cobrados=Decimal("5.05")))
    atual = calculo.atualizar(honorario, date(2026, 9, 29))
    conta = "\n".join(calculo.explicar(atual))
    assert "só o saldo, após pagamento parcial" in conta
    assert "já cobrados ou abonados" in conta


def test_ainda_no_prazo_nao_tem_juros(devedor):
    _, honorario = devedor
    atual = calculo.atualizar(honorario, date(2026, 9, 10))
    assert calculo.explicar(atual)[0] == "Ainda no prazo: sem juros."


def test_juros_a_mao_troca_o_total_e_guarda_o_calculado(devedor):
    _, honorario = devedor
    atual = calculo.atualizar(honorario, date(2026, 9, 29))
    manual = calculo.com_juros_manual(atual, Decimal("4.00"))
    assert (manual.juros, manual.total, manual.juros_calculado) == (
        Decimal("4.00"), Decimal("1004.00"), Decimal("10.10"))
    assert "Juros digitados à mão: R$ 4,00 (o cálculo dava R$ 10,10)" in \
        calculo.explicar(manual)
    de_volta = calculo.com_juros_manual(manual, None)
    assert (de_volta.juros, de_volta.total, de_volta.juros_manual) == (
        Decimal("10.10"), Decimal("1010.10"), False)
    with pytest.raises(ValueError):
        calculo.com_juros_manual(atual, Decimal("-1"))


def test_imagem_usa_os_valores_da_tela_e_o_vencimento_nao_mexe_nos_juros(sessao, devedor):
    cliente, honorario = devedor
    [linha] = cobrancas.linhas_em_aberto_do_cliente(sessao, cliente.id, date(2026, 9, 29))
    linha.atualizacao = calculo.com_juros_manual(linha.atualizacao, Decimal("4.00"))
    selecao = cobrancas.Selecao(cliente=cliente, linhas=[linha],
                                data_referencia=date(2026, 9, 29))

    dados = imagem_cobranca.montar(sessao, selecao, vencimento=date(2026, 10, 15))

    assert dados.campos["total"] == "R$ 1.004,00"
    assert dados.campos["vencimento"] == "15/10/2026"
    assert dados.campos["data"] == "29/09/2026"
