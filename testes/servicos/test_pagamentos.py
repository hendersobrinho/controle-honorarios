from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from honorarios.dominio.enums import FormaPagamento, StatusPagamento
from honorarios.servicos import calculo, clientes, pagamentos
from honorarios.servicos.erros import ErroDeValidacao
from testes import fabricas


def cenario(sessao, juros="1.00", valor="1000.00", vencimento=date(2026, 8, 1)):
    cliente = fabricas.cliente(sessao, juros_dia=juros)
    cliente.juros[0].vigencia_inicio = date(2020, 1, 1)
    sessao.commit()
    honorario = fabricas.honorario(sessao, cliente, valor=valor, vencimento=vencimento)
    return cliente, honorario


def test_previa_mostra_juros_e_total(sessao):
    _, honorario = cenario(sessao)
    previa = pagamentos.previa(honorario, date(2026, 8, 11))
    assert previa.dias_atraso == 10
    assert previa.juros_devidos == Decimal("10.00")
    assert previa.total_devido == Decimal("1010.00")


def test_baixa_total_congela_os_valores(sessao):
    cliente, honorario = cenario(sessao)
    pagamentos.registrar(
        sessao,
        honorario,
        pagamentos.DadosPagamento(
            data=date(2026, 8, 11),
            valor_pago=Decimal("1010.00"),
            forma_pagamento=FormaPagamento.PIX,
        ),
    )
    sessao.commit()
    assert honorario.status is StatusPagamento.PAGO
    assert honorario.saldo_aberto == Decimal("0.00")
    assert honorario.total_congelado == Decimal("1010.00")
    pagamento = honorario.pagamentos[0]
    assert (pagamento.dias_atraso, pagamento.juros_devidos, pagamento.juros_cobrados) == (
        10, Decimal("10.00"), Decimal("10.00"),
    )
    # mudar o juros do cliente depois não mexe no que foi pago
    clientes.definir_juros(sessao, cliente, Decimal("99.00"), "teste")
    sessao.commit()
    atualizacao = calculo.atualizar(honorario, date(2026, 12, 31))
    assert atualizacao.total == Decimal("1010.00")
    assert atualizacao.congelado


def test_pagamento_parcial_deixa_saldo_e_reduz_o_juros(sessao):
    _, honorario = cenario(sessao, juros="0.67")
    pagamentos.registrar(
        sessao,
        honorario,
        pagamentos.DadosPagamento(
            data=date(2026, 9, 10),
            valor_pago=Decimal("626.80"),
            juros_cobrados=Decimal("26.80"),
        ),
    )
    sessao.commit()
    assert honorario.status is StatusPagamento.EM_ABERTO
    assert honorario.saldo_aberto == Decimal("400.00")
    assert honorario.pagamentos[0].parcial

    atualizacao = calculo.atualizar(honorario, date(2026, 9, 20))
    # 10 dias sobre 400/1000 do juros de 0,67: 10 x 0,268
    assert atualizacao.juros == Decimal("2.68")
    assert atualizacao.total == Decimal("402.68")
    assert atualizacao.parcialmente_pago


def test_abono_de_juros_exige_justificativa(sessao):
    _, honorario = cenario(sessao)
    with pytest.raises(ErroDeValidacao, match="justificativa"):
        pagamentos.registrar(
            sessao,
            honorario,
            pagamentos.DadosPagamento(
                data=date(2026, 8, 11),
                valor_pago=Decimal("1000.00"),
                juros_cobrados=Decimal("0.00"),
            ),
        )


def test_abono_com_justificativa_quita(sessao):
    _, honorario = cenario(sessao)
    pagamentos.registrar(
        sessao,
        honorario,
        pagamentos.DadosPagamento(
            data=date(2026, 8, 11),
            valor_pago=Decimal("1000.00"),
            juros_cobrados=Decimal("0.00"),
            justificativa_desconto="Cliente antigo, juros abonado pela Karla",
        ),
    )
    sessao.commit()
    assert honorario.status is StatusPagamento.PAGO
    assert honorario.pagamentos[0].desconto == Decimal("10.00")


def test_juros_cobrado_acima_do_devido_e_recusado(sessao):
    _, honorario = cenario(sessao)
    with pytest.raises(ErroDeValidacao, match="maior que o devido"):
        pagamentos.registrar(
            sessao,
            honorario,
            pagamentos.DadosPagamento(
                data=date(2026, 8, 11),
                valor_pago=Decimal("1100.00"),
                juros_cobrados=Decimal("100.00"),
            ),
        )


def test_pagamento_acima_do_saldo_e_recusado(sessao):
    _, honorario = cenario(sessao)
    with pytest.raises(ErroDeValidacao, match="saldo"):
        pagamentos.registrar(
            sessao,
            honorario,
            pagamentos.DadosPagamento(date(2026, 8, 11), Decimal("2000.00")),
        )


def test_valor_zero_e_data_futura_recusados(sessao):
    _, honorario = cenario(sessao)
    with pytest.raises(ErroDeValidacao, match="maior que zero"):
        pagamentos.registrar(
            sessao, honorario, pagamentos.DadosPagamento(date(2026, 8, 11), Decimal("0"))
        )
    with pytest.raises(ErroDeValidacao, match="futuro"):
        pagamentos.registrar(
            sessao, honorario, pagamentos.DadosPagamento(date(2099, 1, 1), Decimal("10"))
        )


def test_dois_parciais_quitam_o_honorario(sessao):
    _, honorario = cenario(sessao, juros="0.00")
    for _ in range(2):
        pagamentos.registrar(
            sessao, honorario, pagamentos.DadosPagamento(date(2026, 8, 11), Decimal("500.00"))
        )
    sessao.commit()
    assert honorario.status is StatusPagamento.PAGO
    assert honorario.total_congelado == Decimal("1000.00")


def test_estorno_reabre_o_honorario(sessao):
    _, honorario = cenario(sessao)
    pagamento = pagamentos.registrar(
        sessao, honorario, pagamentos.DadosPagamento(date(2026, 8, 11), Decimal("1010.00"))
    )
    sessao.commit()
    pagamentos.estornar(sessao, pagamento, "Comprovante era de outro cliente")
    sessao.commit()
    assert honorario.status is StatusPagamento.EM_ABERTO
    assert honorario.saldo_aberto == Decimal("1000.00")
    assert honorario.total_congelado is None
    assert not pagamento.ativo
    assert pagamento.id is not None  # nada é apagado


def test_estorno_sem_motivo_recusado(sessao):
    _, honorario = cenario(sessao)
    pagamento = pagamentos.registrar(
        sessao, honorario, pagamentos.DadosPagamento(date(2026, 8, 11), Decimal("1010.00"))
    )
    with pytest.raises(ErroDeValidacao):
        pagamentos.estornar(sessao, pagamento, "")


def test_honorario_pago_nao_recebe_nova_baixa(sessao):
    _, honorario = cenario(sessao)
    pagamentos.registrar(
        sessao, honorario, pagamentos.DadosPagamento(date(2026, 8, 11), Decimal("1010.00"))
    )
    sessao.commit()
    with pytest.raises(ErroDeValidacao, match="já está pago"):
        pagamentos.registrar(
            sessao, honorario, pagamentos.DadosPagamento(date(2026, 8, 12), Decimal("10.00"))
        )
