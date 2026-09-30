"""Acompanhamento: a resposta entra depois, e a situação vem dela."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

import pytest

from honorarios.dominio.enums import Canal, ResultadoCobranca
from honorarios.dominio.valores import Competencia
from honorarios.servicos import acompanhamento, cobrancas, pagamentos
from honorarios.servicos.erros import ErroDeValidacao
from testes import fabricas

REFERENCIA = date(2026, 9, 30)


def cobrar(sessao, cliente, quando: date, linhas=None):
    linhas = linhas or cobrancas.linhas_em_aberto_do_cliente(sessao, cliente.id, quando)
    selecao = cobrancas.Selecao(cliente=cliente, linhas=linhas, data_referencia=quando)
    lote = cobrancas.registrar(
        sessao,
        selecao,
        texto=cobrancas.gerar_texto(sessao, selecao),
        quando=datetime.combine(quando, time(9, 0)),
    )
    sessao.commit()
    return lote


@pytest.fixture
def cenario(sessao):
    cliente = fabricas.cliente(sessao, juros_dia="1.00")
    cliente.juros[0].vigencia_inicio = date(2020, 1, 1)
    sessao.commit()
    fabricas.honorario(sessao, cliente, valor="1000.00", vencimento=date(2026, 8, 19))
    fabricas.honorario(
        sessao, cliente, valor="500.00", vencimento=date(2026, 7, 19),
        competencia=Competencia(2026, 6),
    )
    return cliente


def test_cobranca_nasce_aguardando_resposta(sessao, cenario):
    cobrar(sessao, cenario, date(2026, 9, 25))
    linhas = acompanhamento.listar(sessao, acompanhamento.Filtro(data_referencia=REFERENCIA))
    assert len(linhas) == 1
    linha = linhas[0]
    assert linha.resultado is ResultadoCobranca.AGUARDANDO
    assert linha.situacao == acompanhamento.AGUARDANDO
    assert linha.pede_acao
    assert linha.quantidade == 2
    assert linha.dias == 5


def test_registrar_resposta_vale_para_todos_os_honorarios(sessao, cenario):
    cobrar(sessao, cenario, date(2026, 9, 25))
    linha = acompanhamento.listar(sessao, acompanhamento.Filtro(data_referencia=REFERENCIA))[0]
    acompanhamento.registrar_resposta(
        sessao, linha, ResultadoCobranca.PROMETEU_PAGAR, date(2026, 10, 5), "Falou com o sócio"
    )
    sessao.commit()
    assert all(c.resultado is ResultadoCobranca.PROMETEU_PAGAR for c in linha.cobrancas)
    assert all(c.promessa_data == date(2026, 10, 5) for c in linha.cobrancas)
    assert all(c.observacao == "Falou com o sócio" for c in linha.cobrancas)


def test_promessa_exige_data(sessao, cenario):
    cobrar(sessao, cenario, date(2026, 9, 25))
    linha = acompanhamento.listar(sessao, acompanhamento.Filtro(data_referencia=REFERENCIA))[0]
    with pytest.raises(ErroDeValidacao, match="data prometida"):
        acompanhamento.registrar_resposta(sessao, linha, ResultadoCobranca.PROMETEU_PAGAR)


def test_promessa_vence_e_muda_de_situacao(sessao, cenario):
    cobrar(sessao, cenario, date(2026, 9, 20))
    filtro = acompanhamento.Filtro(data_referencia=REFERENCIA)
    linha = acompanhamento.listar(sessao, filtro)[0]
    acompanhamento.registrar_resposta(
        sessao, linha, ResultadoCobranca.PROMETEU_PAGAR, date(2026, 10, 10)
    )
    sessao.commit()
    assert acompanhamento.listar(sessao, filtro)[0].situacao == acompanhamento.PROMESSA_EM_ABERTO

    depois = acompanhamento.Filtro(data_referencia=date(2026, 10, 15))
    assert acompanhamento.listar(sessao, depois)[0].situacao == acompanhamento.PROMESSA_VENCIDA


def test_pagar_encerra_a_cobranca(sessao, cenario):
    cobrar(sessao, cenario, date(2026, 9, 25))
    filtro = acompanhamento.Filtro(data_referencia=REFERENCIA)
    linha = acompanhamento.listar(sessao, filtro)[0]
    for cobranca in linha.cobrancas:
        honorario = cobranca.honorario
        previa = pagamentos.previa(honorario, REFERENCIA)
        pagamentos.registrar(
            sessao,
            honorario,
            pagamentos.DadosPagamento(data=REFERENCIA, valor_pago=previa.total_devido),
        )
    sessao.commit()
    atualizada = acompanhamento.listar(sessao, filtro)[0]
    assert atualizada.situacao == acompanhamento.ENCERRADA
    assert atualizada.saldo_atual == Decimal("0.00")
    assert not atualizada.pede_acao


def test_renegociacao_e_contestacao_pedem_decisao(sessao, cenario):
    cobrar(sessao, cenario, date(2026, 9, 25))
    filtro = acompanhamento.Filtro(data_referencia=REFERENCIA)
    linha = acompanhamento.listar(sessao, filtro)[0]
    acompanhamento.registrar_resposta(sessao, linha, ResultadoCobranca.PEDIU_RENEGOCIACAO)
    sessao.commit()
    assert acompanhamento.listar(sessao, filtro)[0].situacao == acompanhamento.PRECISA_DECISAO


def test_filtro_de_periodo(sessao, cenario):
    cobrar(sessao, cenario, date(2026, 7, 10))
    cobrar(sessao, cenario, date(2026, 9, 25))
    todas = acompanhamento.Filtro(data_referencia=REFERENCIA)
    assert len(acompanhamento.listar(sessao, todas)) == 2

    setembro = acompanhamento.Filtro(desde=date(2026, 9, 1), data_referencia=REFERENCIA)
    linhas = acompanhamento.listar(sessao, setembro)
    assert len(linhas) == 1
    assert linhas[0].data == date(2026, 9, 25)


def test_agrupar_por_mes_e_por_situacao(sessao, cenario):
    cobrar(sessao, cenario, date(2026, 7, 10))
    cobrar(sessao, cenario, date(2026, 9, 25))
    linhas = acompanhamento.listar(sessao, acompanhamento.Filtro(data_referencia=REFERENCIA))
    assert [rotulo for rotulo, _ in acompanhamento.por_mes(linhas)] == ["Set/2026", "Jul/2026"]
    assert [rotulo for rotulo, _ in acompanhamento.por_situacao(linhas)] == [
        acompanhamento.AGUARDANDO
    ]
    assert len(acompanhamento.por_empresa(linhas)) == 1


def test_somente_pendentes_esconde_encerradas(sessao, cenario):
    cobrar(sessao, cenario, date(2026, 9, 25))
    filtro = acompanhamento.Filtro(data_referencia=REFERENCIA)
    linha = acompanhamento.listar(sessao, filtro)[0]
    acompanhamento.registrar_resposta(sessao, linha, ResultadoCobranca.PAGOU)
    sessao.commit()
    assert acompanhamento.listar(sessao, filtro)[0].situacao == acompanhamento.ENCERRADA
    pendentes = acompanhamento.Filtro(somente_pendentes=True, data_referencia=REFERENCIA)
    assert acompanhamento.listar(sessao, pendentes) == []


def test_cobranca_estornada_some_do_acompanhamento(sessao, cenario):
    lote = cobrar(sessao, cenario, date(2026, 9, 25))
    for cobranca in list(lote.cobrancas):
        cobrancas.estornar(sessao, cobranca, "Cobrei a empresa errada")
    sessao.commit()
    assert acompanhamento.listar(sessao, acompanhamento.Filtro(data_referencia=REFERENCIA)) == []


def test_contar_pendentes(sessao, cenario):
    cobrar(sessao, cenario, date(2026, 9, 25))
    assert acompanhamento.contar_pendentes(sessao, REFERENCIA) == 1


def test_canal_diferente_de_whatsapp(sessao, cenario):
    linhas = cobrancas.linhas_em_aberto_do_cliente(sessao, cenario.id, REFERENCIA)
    cobrancas.registrar_sem_mensagem(sessao, linhas, "Cobrei por telefone", canal=Canal.TELEFONE)
    sessao.commit()
    filtro = acompanhamento.Filtro(canal=Canal.TELEFONE, data_referencia=REFERENCIA)
    assert len(acompanhamento.listar(sessao, filtro)) == 1
    assert acompanhamento.listar(
        sessao, acompanhamento.Filtro(canal=Canal.EMAIL, data_referencia=REFERENCIA)
    ) == []
