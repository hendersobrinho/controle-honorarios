from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from honorarios.dominio.enums import StatusPagamento
from honorarios.dominio.valores import ZERO, Competencia
from honorarios.infra.modelos import TipoHonorario
from honorarios.servicos import cobrancas, pagamentos, parcelamentos
from honorarios.servicos import honorarios as servico_honorarios
from honorarios.servicos.erros import ErroDeValidacao
from honorarios.servicos.honorarios import Filtro
from testes import fabricas

REFERENCIA = date(2026, 9, 29)


@pytest.fixture(autouse=True)
def parcelado_na_referencia(monkeypatch):
    """O parcelamento fica com a data do teste, não com a de hoje de verdade."""
    from honorarios.servicos import renegociacoes

    monkeypatch.setattr(renegociacoes, "hoje", lambda: REFERENCIA)


@pytest.fixture
def cenario(sessao):
    cliente = fabricas.cliente(sessao, juros_dia="1.00")
    cliente.juros[0].vigencia_inicio = date(2020, 1, 1)
    sessao.commit()
    fabricas.honorario(sessao, cliente, valor="1000.00", vencimento=date(2026, 7, 19),
                       competencia=Competencia(2026, 6))
    fabricas.honorario(sessao, cliente, valor="500.00", vencimento=date(2026, 8, 19),
                       competencia=Competencia(2026, 7))
    linhas = cobrancas.linhas_em_aberto_do_cliente(sessao, cliente.id, REFERENCIA)
    return cliente, linhas


def _parcelar(sessao, cliente, linhas, valor="1500.00", parcelas=3,
              primeiro=date(2026, 9, 10)):
    tipo = sessao.scalar(select(TipoHonorario).where(TipoHonorario.nome == "Parcela de acordo"))
    acordo = parcelamentos.criar(
        sessao, cliente=cliente, linhas=linhas, valor_acordado=Decimal(valor),
        parcelas=parcelas, primeiro_vencimento=primeiro, tipo_id=tipo.id)
    sessao.commit()
    return acordo


def test_dividir_poe_a_sobra_na_ultima():
    previstas = parcelamentos.dividir(Decimal("100.00"), 3, date(2026, 1, 31))
    assert [p.valor for p in previstas] == [Decimal("33.33"), Decimal("33.33"),
                                            Decimal("33.34")]
    assert [p.vencimento for p in previstas] == [date(2026, 1, 31), date(2026, 2, 28),
                                                 date(2026, 3, 31)]


def test_um_honorario_so_tambem_parcela(sessao, cenario):
    cliente, linhas = cenario
    _parcelar(sessao, cliente, linhas[:1], valor="1000.00", parcelas=2)
    [parcelamento] = parcelamentos.listar(sessao, REFERENCIA)
    assert [h.id for h in parcelamento.originais] == [linhas[0].honorario.id]
    assert len(parcelamento.parcelas) == 2


def test_parcelas_saem_de_vencimentos_e_ficam_no_parcelamento(sessao, cenario):
    cliente, linhas = cenario
    _parcelar(sessao, cliente, linhas)
    vencimentos = servico_honorarios.pendentes(
        sessao, Filtro(cliente_id=cliente.id, incluir_parcelas=False))
    assert vencimentos == []
    # relatórios e ficha continuam vendo as parcelas
    assert len(servico_honorarios.pendentes(sessao, Filtro(cliente_id=cliente.id))) == 3
    contagem = servico_honorarios.contar_pendentes(sessao, REFERENCIA)
    assert (contagem.atrasados, contagem.a_vencer) == (0, 0)
    # a primeira parcela venceu em 10/09: atrasada, no contador da tela
    assert parcelamentos.contar_atrasados(sessao, REFERENCIA) == 1

    [parcelamento] = parcelamentos.listar(sessao, REFERENCIA)
    assert [p.numero for p in parcelamento.parcelas] == [1, 2, 3]
    assert [p.numero for p in parcelamento.atrasadas] == [1]
    assert parcelamento.proxima.numero == 1
    # dois honorários a R$ 1,00/dia viram 3 parcelas com 2/3 de R$ 1,00 cada: a 1ª,
    # vencida em 10/09, tem 19 dias × R$ 0,666667
    assert parcelamento.falta == Decimal("1512.67")
    assert parcelamento.pago == Decimal("0.00") and not parcelamento.quitado


def test_pagar_todas_quita(sessao, cenario):
    cliente, linhas = cenario
    _parcelar(sessao, cliente, linhas, primeiro=date(2026, 10, 10))
    [parcelamento] = parcelamentos.listar(sessao, REFERENCIA)
    for parcela in parcelamento.parcelas:
        pagamentos.registrar(sessao, parcela.honorario, pagamentos.DadosPagamento(
            data=REFERENCIA, valor_pago=parcela.honorario.valor_original))
    sessao.commit()
    [parcelamento] = parcelamentos.listar(sessao, REFERENCIA)
    assert parcelamento.quitado and parcelamento.pago == Decimal("1500.00")
    assert parcelamento.falta == Decimal("0.00") and parcelamento.proxima is None


def test_cancelar_com_parcela_paga_pede_estorno(sessao, cenario):
    cliente, linhas = cenario
    _parcelar(sessao, cliente, linhas, primeiro=date(2026, 10, 10))
    [parcelamento] = parcelamentos.listar(sessao, REFERENCIA)
    primeira = parcelamento.parcelas[0].honorario
    pagamento = pagamentos.registrar(sessao, primeira, pagamentos.DadosPagamento(
        data=REFERENCIA, valor_pago=primeira.valor_original))
    sessao.commit()
    [parcelamento] = parcelamentos.listar(sessao, REFERENCIA)
    with pytest.raises(ErroDeValidacao, match="Estorne"):
        parcelamentos.cancelar(sessao, parcelamento, "desistiu")

    pagamentos.estornar(sessao, pagamento, "lançado errado")
    sessao.commit()
    [parcelamento] = parcelamentos.listar(sessao, REFERENCIA)
    parcelamentos.cancelar(sessao, parcelamento, "desistiu")
    sessao.commit()
    assert all(linha.honorario.status is StatusPagamento.EM_ABERTO for linha in linhas)
    assert parcelamentos.listar(sessao, REFERENCIA) == []
    [cancelado] = parcelamentos.listar(sessao, REFERENCIA, incluir_cancelados=True)
    assert cancelado.cancelado
    # os originais voltam para Vencimentos
    assert len(servico_honorarios.pendentes(
        sessao, Filtro(cliente_id=cliente.id, incluir_parcelas=False))) == 2


def test_honorarios_de_outro_cliente_nao_entram(sessao, cenario):
    _cliente, linhas = cenario
    outro = fabricas.cliente(sessao, nome="OUTRA LTDA", codigo="901", documento="")
    with pytest.raises(ErroDeValidacao, match="mesmo cliente"):
        _parcelar(sessao, outro, linhas)


def test_busca_pelo_nome(sessao, cenario):
    cliente, linhas = cenario
    _parcelar(sessao, cliente, linhas)
    assert len(parcelamentos.listar(sessao, REFERENCIA, "exemplo")) == 1
    assert parcelamentos.listar(sessao, REFERENCIA, "inexistente") == []


def test_juros_corre_desde_o_parcelamento_ate_o_vencimento(sessao, cenario):
    from honorarios.servicos import calculo

    cliente, linhas = cenario
    _parcelar(sessao, cliente, linhas, primeiro=date(2026, 10, 29))
    [parcelamento] = parcelamentos.listar(sessao, REFERENCIA)
    primeira, segunda, terceira = (p.honorario for p in parcelamento.parcelas)
    assert primeira.juros_desde == REFERENCIA
    assert primeira.juros_fator == Decimal("0.666667")
    # no vencimento da 1ª (30 dias depois): 30 × R$ 0,666667, sem estar atrasada
    no_vencimento = calculo.atualizar(primeira, date(2026, 10, 29))
    assert (no_vencimento.juros, no_vencimento.dias_atraso) == (Decimal("20.00"), 0)
    assert calculo.atualizar(terceira, date(2026, 10, 29)).juros == Decimal("20.00")
    # pagando atrasado, continua correndo no mesmo ritmo
    atrasada = calculo.atualizar(primeira, date(2026, 11, 8))
    assert (atrasada.juros, atrasada.dias_atraso) == (Decimal("26.67"), 10)
    # o total ao dia das três é o mesmo que os dois honorários pagavam
    assert sum(p.juros_fator for p in (primeira, segunda, terceira)) == Decimal("2.000001")


def test_juros_so_depois_do_vencimento_se_escolhido(sessao, cenario):
    from honorarios.servicos import calculo

    cliente, linhas = cenario
    tipo = sessao.scalar(select(TipoHonorario).where(TipoHonorario.nome == "Parcela de acordo"))
    parcelamentos.criar(sessao, cliente, linhas, Decimal("1500.00"), 3, date(2026, 10, 29),
                        tipo.id, juros_ate_o_vencimento=False)
    sessao.commit()
    [parcelamento] = parcelamentos.listar(sessao, REFERENCIA)
    primeira = parcelamento.parcelas[0].honorario
    assert primeira.juros_desde is None
    assert calculo.atualizar(primeira, date(2026, 10, 29)).juros == Decimal("0.00")
    assert calculo.atualizar(primeira, date(2026, 11, 8)).juros == Decimal("6.67")


def test_previsao_do_juros_de_cada_parcela(sessao, cenario):
    from honorarios.servicos import renegociacoes

    cliente, linhas = cenario
    previstas = parcelamentos.dividir(Decimal("1500.00"), 3, date(2026, 10, 29))
    fatores = renegociacoes.fatores_das_parcelas(renegociacoes.fator_do_juros(linhas),
                                                 previstas)
    juros = renegociacoes.juros_previstos(cliente, previstas, fatores, REFERENCIA)
    assert juros == [Decimal("20.00"), Decimal("40.67"), Decimal("60.67")]


def test_tirar_o_juros_da_parcela_antes_do_vencimento(sessao, cenario):
    from honorarios.servicos import calculo
    from honorarios.servicos import honorarios as servico

    cliente, linhas = cenario
    _parcelar(sessao, cliente, linhas, primeiro=date(2026, 10, 29))
    [parcelamento] = parcelamentos.listar(sessao, REFERENCIA)
    primeira = parcelamento.parcelas[0].honorario
    servico.ajustar_juros(sessao, primeira, Decimal("0.00"), date(2026, 10, 9))
    assert calculo.atualizar(primeira, date(2026, 10, 9)).juros == Decimal("0.00")
    # e dali em diante volta a correr (20 dias 13,33 − os 10 já tirados 6,67)
    assert calculo.atualizar(primeira, date(2026, 10, 19)).juros == Decimal("6.66")


def test_juros_ao_dia_estipulado_a_mao(sessao, cenario):
    from honorarios.servicos import calculo, renegociacoes

    cliente, linhas = cenario
    tipo = sessao.scalar(select(TipoHonorario).where(TipoHonorario.nome == "Parcela de acordo"))
    parcelamentos.criar(sessao, cliente, linhas, Decimal("1500.00"), 3, date(2026, 10, 29),
                        tipo.id, juros_dia=Decimal("2.00"))
    sessao.commit()
    [parcelamento] = parcelamentos.listar(sessao, REFERENCIA)
    primeira = parcelamento.parcelas[0].honorario
    assert (primeira.juros_dia, primeira.juros_fator) == (Decimal("2.00"), None)
    # R$ 2,00 por dia desde o parcelamento: 30 dias até o vencimento, mais 10 de atraso
    assert calculo.atualizar(primeira, date(2026, 10, 29)).juros == Decimal("60.00")
    assert calculo.atualizar(primeira, date(2026, 11, 8)).juros == Decimal("80.00")
    # a prévia usa o mesmo juros
    previstas = parcelamentos.dividir(Decimal("1500.00"), 3, date(2026, 10, 29))
    assert renegociacoes.juros_previstos(cliente, previstas, [ZERO] * 3, REFERENCIA,
                                         Decimal("2.00"))[0] == Decimal("60.00")


def test_juros_ao_dia_zero_nao_corre_juros(sessao, cenario):
    from honorarios.servicos import calculo

    cliente, linhas = cenario
    tipo = sessao.scalar(select(TipoHonorario).where(TipoHonorario.nome == "Parcela de acordo"))
    parcelamentos.criar(sessao, cliente, linhas, Decimal("1500.00"), 3, date(2026, 10, 29),
                        tipo.id, juros_dia=ZERO)
    sessao.commit()
    [parcelamento] = parcelamentos.listar(sessao, REFERENCIA)
    assert calculo.atualizar(parcelamento.parcelas[0].honorario,
                             date(2026, 12, 31)).juros == Decimal("0.00")


def test_juros_ao_dia_negativo_nao_deixa(sessao, cenario):
    cliente, linhas = cenario
    tipo = sessao.scalar(select(TipoHonorario).where(TipoHonorario.nome == "Parcela de acordo"))
    with pytest.raises(ErroDeValidacao, match="negativo"):
        parcelamentos.criar(sessao, cliente, linhas, Decimal("1500.00"), 3, date(2026, 10, 29),
                            tipo.id, juros_dia=Decimal("-1"))
