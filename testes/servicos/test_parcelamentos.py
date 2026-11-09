from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from honorarios.dominio.enums import StatusPagamento
from honorarios.dominio.valores import Competencia
from honorarios.infra.modelos import TipoHonorario
from honorarios.servicos import cobrancas, pagamentos, parcelamentos
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
    assert parcelamento.falta == Decimal("1519.00")   # 1.500 + 19 dias de juros da 1ª
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
