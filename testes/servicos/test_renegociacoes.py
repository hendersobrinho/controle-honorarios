from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from honorarios.dominio.enums import StatusPagamento
from honorarios.dominio.valores import Competencia
from honorarios.infra.modelos import TipoHonorario
from honorarios.servicos import cobrancas, renegociacoes
from honorarios.servicos import honorarios as servico_honorarios
from honorarios.servicos.erros import ErroDeValidacao
from honorarios.servicos.honorarios import Filtro
from testes import fabricas

REFERENCIA = date(2026, 9, 29)


@pytest.fixture
def cenario(sessao):
    cliente = fabricas.cliente(sessao, juros_dia="1.00")
    cliente.juros[0].vigencia_inicio = date(2020, 1, 1)
    sessao.commit()
    fabricas.honorario(sessao, cliente, valor="1000.00", vencimento=date(2026, 7, 19),
                       competencia=Competencia(2026, 6))
    fabricas.honorario(sessao, cliente, valor="1000.00", vencimento=date(2026, 8, 19),
                       competencia=Competencia(2026, 7))
    linhas = cobrancas.linhas_em_aberto_do_cliente(sessao, cliente.id, REFERENCIA)
    return cliente, linhas


def tipo_parcela(sessao) -> TipoHonorario:
    return sessao.scalar(select(TipoHonorario).where(TipoHonorario.nome == "Parcela de acordo"))


def test_acordo_marca_originais_e_gera_parcelas(sessao, cenario):
    cliente, linhas = cenario
    total = sum(linha.atualizacao.total for linha in linhas)
    acordo = renegociacoes.criar(
        sessao,
        cliente=cliente,
        linhas=linhas,
        valor_acordado=Decimal("2000.00"),
        desconto=total - Decimal("2000.00"),
        parcelas=3,
        primeiro_vencimento=date(2026, 10, 20),
        tipo_id=tipo_parcela(sessao).id,
    )
    sessao.commit()

    assert all(linha.honorario.status is StatusPagamento.RENEGOCIADO for linha in linhas)
    assert all(linha.honorario.saldo_aberto == Decimal("0.00") for linha in linhas)

    parcelas = servico_honorarios.pendentes(sessao, Filtro(cliente_id=cliente.id))
    assert len(parcelas) == 3
    assert sum(p.atualizacao.valor_original for p in parcelas) == Decimal("2000.00")
    assert [p.honorario.vencimento for p in parcelas] == [
        date(2026, 10, 20), date(2026, 11, 20), date(2026, 12, 20)
    ]
    assert acordo.itens and acordo.valor_acordado == Decimal("2000.00")


def test_parcela_de_tipo_mensal_recebe_competencia(sessao, cenario):
    """Um tipo que exige competência não pode quebrar a geração das parcelas."""
    cliente, linhas = cenario
    renegociacoes.criar(
        sessao,
        cliente=cliente,
        linhas=linhas,
        valor_acordado=Decimal("2100.00"),
        parcelas=2,
        primeiro_vencimento=date(2026, 10, 20),
        tipo_id=fabricas.tipo_mensal(sessao).id,
    )
    sessao.commit()
    parcelas = servico_honorarios.pendentes(sessao, Filtro(cliente_id=cliente.id))
    assert [(p.honorario.competencia_ano, p.honorario.competencia_mes) for p in parcelas] == [
        (2026, 10), (2026, 11)
    ]


def test_ultima_parcela_absorve_a_diferenca_de_centavos(sessao, cenario):
    cliente, linhas = cenario
    renegociacoes.criar(
        sessao,
        cliente=cliente,
        linhas=linhas,
        valor_acordado=Decimal("1000.00"),
        parcelas=3,
        primeiro_vencimento=date(2026, 10, 20),
        tipo_id=tipo_parcela(sessao).id,
    )
    sessao.commit()
    parcelas = servico_honorarios.pendentes(sessao, Filtro(cliente_id=cliente.id))
    valores = sorted(p.atualizacao.valor_original for p in parcelas)
    assert sum(valores) == Decimal("1000.00")
    assert valores == [Decimal("333.33"), Decimal("333.33"), Decimal("333.34")]


def test_renegociado_sai_das_filas_de_cobranca(sessao, cenario):
    cliente, linhas = cenario
    renegociacoes.criar(
        sessao, cliente=cliente, linhas=linhas, valor_acordado=Decimal("2000.00"),
        parcelas=1, primeiro_vencimento=date(2026, 10, 20),
        tipo_id=tipo_parcela(sessao).id,
    )
    sessao.commit()
    with pytest.raises(ErroDeValidacao, match="Renegociado"):
        cobrancas.registrar(
            sessao, cobrancas.Selecao(cliente=cliente, linhas=linhas)
        )


def test_renegociado_nao_gera_juros(sessao, cenario):
    cliente, linhas = cenario
    renegociacoes.criar(
        sessao, cliente=cliente, linhas=linhas, valor_acordado=Decimal("2000.00"),
        parcelas=1, primeiro_vencimento=date(2026, 10, 20),
        tipo_id=tipo_parcela(sessao).id,
    )
    sessao.commit()
    from honorarios.servicos import calculo

    atualizacao = calculo.atualizar(linhas[0].honorario, date(2026, 12, 31))
    assert atualizacao.juros == Decimal("0.00")
    assert atualizacao.total == Decimal("0.00")


def test_cancelar_acordo_devolve_os_originais(sessao, cenario):
    cliente, linhas = cenario
    acordo = renegociacoes.criar(
        sessao, cliente=cliente, linhas=linhas, valor_acordado=Decimal("2000.00"),
        parcelas=2, primeiro_vencimento=date(2026, 10, 20),
        tipo_id=tipo_parcela(sessao).id,
    )
    sessao.commit()
    renegociacoes.cancelar(sessao, acordo, "Cliente não cumpriu a primeira parcela")
    sessao.commit()

    assert all(linha.honorario.status is StatusPagamento.EM_ABERTO for linha in linhas)
    assert all(
        linha.honorario.saldo_aberto == linha.honorario.valor_original for linha in linhas
    )
    abertos = servico_honorarios.pendentes(sessao, Filtro(cliente_id=cliente.id))
    assert len(abertos) == 2  # as parcelas do acordo foram canceladas


def test_acordo_sem_honorario_e_recusado(sessao, cenario):
    cliente, _ = cenario
    with pytest.raises(ErroDeValidacao, match="Selecione"):
        renegociacoes.criar(
            sessao, cliente=cliente, linhas=[], valor_acordado=Decimal("100.00"),
            parcelas=1, primeiro_vencimento=date(2026, 10, 20),
            tipo_id=tipo_parcela(sessao).id,
        )


def test_valor_e_parcelas_invalidos(sessao, cenario):
    cliente, linhas = cenario
    with pytest.raises(ErroDeValidacao, match="maior que zero"):
        renegociacoes.criar(
            sessao, cliente=cliente, linhas=linhas, valor_acordado=Decimal("0"),
            parcelas=1, primeiro_vencimento=date(2026, 10, 20),
            tipo_id=tipo_parcela(sessao).id,
        )
    with pytest.raises(ErroDeValidacao, match="parcela"):
        renegociacoes.criar(
            sessao, cliente=cliente, linhas=linhas, valor_acordado=Decimal("100"),
            parcelas=0, primeiro_vencimento=date(2026, 10, 20),
            tipo_id=tipo_parcela(sessao).id,
        )
