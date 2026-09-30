"""Histórico de um honorário, inclusive quando a cobrança saiu em lote."""

from __future__ import annotations

from datetime import date, datetime, time

import pytest

from honorarios.dominio.enums import ResultadoCobranca
from honorarios.dominio.valores import Competencia
from honorarios.servicos import acompanhamento, cobrancas, historico, pagamentos
from testes import fabricas

REFERENCIA = date(2026, 9, 30)


@pytest.fixture
def cenario(sessao):
    cliente = fabricas.cliente(sessao, juros_dia="1.00")
    cliente.juros[0].vigencia_inicio = date(2020, 1, 1)
    sessao.commit()
    primeiro = fabricas.honorario(sessao, cliente, valor="1000.00", vencimento=date(2026, 8, 19))
    fabricas.honorario(
        sessao, cliente, valor="500.00", vencimento=date(2026, 7, 19),
        competencia=Competencia(2026, 6),
    )
    return cliente, primeiro


def test_lancamento_sempre_aparece(sessao, cenario):
    _, honorario = cenario
    eventos = historico.do_honorario(sessao, honorario, REFERENCIA)
    assert eventos[-1].tipo == historico.LANCAMENTO
    assert "Honorário mensal lançado" in eventos[-1].titulo


def test_cobranca_em_lote_diz_com_quem_foi(sessao, cenario):
    cliente, honorario = cenario
    linhas = cobrancas.linhas_em_aberto_do_cliente(sessao, cliente.id, REFERENCIA)
    selecao = cobrancas.Selecao(cliente=cliente, linhas=linhas)
    cobrancas.registrar(
        sessao, selecao, texto=cobrancas.gerar_texto(sessao, selecao),
        quando=datetime.combine(date(2026, 9, 25), time(9, 0)),
    )
    sessao.commit()

    evento = next(
        e for e in historico.do_honorario(sessao, honorario, REFERENCIA)
        if e.tipo == historico.COBRANCA
    )
    assert evento.em_lote
    assert evento.titulo == "Cobrança enviada em lote"
    assert evento.companheiros == ["06/2026"]
    assert "mais 1 honorário(s)" in evento.rotulo_lote
    assert "Constam em aberto" in evento.texto


def test_cobranca_individual_nao_diz_lote(sessao, cenario):
    cliente, honorario = cenario
    linha = [
        item
        for item in cobrancas.linhas_em_aberto_do_cliente(sessao, cliente.id, REFERENCIA)
        if item.honorario.id == honorario.id
    ]
    selecao = cobrancas.Selecao(cliente=cliente, linhas=linha)
    cobrancas.registrar(sessao, selecao, texto="oi")
    sessao.commit()
    evento = next(
        e for e in historico.do_honorario(sessao, honorario, REFERENCIA)
        if e.tipo == historico.COBRANCA
    )
    assert not evento.em_lote
    assert evento.rotulo_lote == "Cobrança individual"
    assert evento.titulo == "Cobrança enviada"


def test_resposta_vira_evento_proprio(sessao, cenario):
    cliente, honorario = cenario
    linhas = cobrancas.linhas_em_aberto_do_cliente(sessao, cliente.id, REFERENCIA)
    cobrancas.registrar(
        sessao, cobrancas.Selecao(cliente=cliente, linhas=linhas), texto="oi"
    )
    sessao.commit()
    linha = acompanhamento.listar(
        sessao, acompanhamento.Filtro(data_referencia=REFERENCIA)
    )[0]
    acompanhamento.registrar_resposta(
        sessao, linha, ResultadoCobranca.PROMETEU_PAGAR, date(2026, 10, 10), "Vai pagar"
    )
    sessao.commit()

    eventos = historico.do_honorario(sessao, honorario, REFERENCIA)
    resposta = next(e for e in eventos if e.tipo == historico.RESPOSTA)
    assert resposta.titulo == "Prometeu pagar"
    assert "10/10/2026" in resposta.detalhe
    assert "Vai pagar" in resposta.detalhe


def test_pagamento_e_estorno_entram_na_linha_do_tempo(sessao, cenario):
    _, honorario = cenario
    previa = pagamentos.previa(honorario, REFERENCIA)
    pagamento = pagamentos.registrar(
        sessao,
        honorario,
        pagamentos.DadosPagamento(data=REFERENCIA, valor_pago=previa.total_devido),
    )
    sessao.commit()
    tipos = [e.tipo for e in historico.do_honorario(sessao, honorario, REFERENCIA)]
    assert historico.PAGAMENTO in tipos

    pagamentos.estornar(sessao, pagamento, "Comprovante de outro cliente")
    sessao.commit()
    tipos = [e.tipo for e in historico.do_honorario(sessao, honorario, REFERENCIA)]
    assert historico.ESTORNO in tipos


def test_resumo_traz_situacao_e_cobrancas(sessao, cenario):
    cliente, honorario = cenario
    cobrancas.registrar(
        sessao,
        cobrancas.Selecao(
            cliente=cliente,
            linhas=cobrancas.linhas_em_aberto_do_cliente(sessao, cliente.id, REFERENCIA),
        ),
        texto="oi",
    )
    sessao.commit()
    resumo = historico.resumo(sessao, honorario, REFERENCIA)
    assert resumo.cobrancas == 1
    assert resumo.situacao.startswith("Em atraso há 42")
    assert resumo.atualizacao.total == resumo.atualizacao.valor_original + resumo.atualizacao.juros
