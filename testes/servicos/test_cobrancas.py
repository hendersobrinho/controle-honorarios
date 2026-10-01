from __future__ import annotations

from datetime import date, time

import pytest

from honorarios.dominio.enums import ResultadoCobranca
from honorarios.dominio.valores import Competencia
from honorarios.servicos import cobrancas
from honorarios.servicos import honorarios as servico_honorarios
from honorarios.servicos.erros import ErroDeValidacao
from honorarios.servicos.honorarios import Filtro
from testes import fabricas


def cenario(sessao, juros="1.00"):
    cliente = fabricas.cliente(sessao, juros_dia=juros)
    cliente.juros[0].vigencia_inicio = date(2020, 1, 1)
    sessao.commit()
    honorario = fabricas.honorario(
        sessao, cliente, valor="1000.00", vencimento=date(2026, 9, 19)
    )
    return cliente, honorario


def selecao(sessao, cliente, referencia=date(2026, 9, 29), **kwargs):
    linhas = cobrancas.linhas_em_aberto_do_cliente(sessao, cliente.id, referencia)
    return cobrancas.Selecao(
        cliente=cliente,
        linhas=linhas,
        data_referencia=referencia,
        hora_referencia=kwargs.pop("hora", time(9, 0)),
        **kwargs,
    )


def test_texto_gerado_usa_os_dados_do_banco(sessao):
    cliente, _ = cenario(sessao)
    texto = cobrancas.gerar_texto(sessao, selecao(sessao, cliente))
    assert "Bom dia, Carol! Tudo bem?" in texto
    assert "competência 08/2026" in texto
    assert "o valor atualizado é de R$ 1.010,00." in texto
    assert "PIX – Métodos Serviços Contábeis Ltda" in texto


def test_marcar_como_cobrado_cria_uma_cobranca_por_honorario(sessao):
    cliente, honorario = cenario(sessao)
    fabricas.honorario(
        sessao, cliente, valor="500.00", vencimento=date(2026, 8, 19),
        competencia=Competencia(2026, 7),
    )
    alvo = selecao(sessao, cliente)
    texto = cobrancas.gerar_texto(sessao, alvo)
    lote = cobrancas.registrar(sessao, alvo, texto=texto)
    sessao.commit()
    assert len(lote.cobrancas) == 2
    assert lote.texto_enviado == texto
    assert lote.total_no_momento == alvo.total
    linha = servico_honorarios.pendentes(sessao, Filtro(cliente_id=cliente.id))[0]
    assert linha.cobrancas == 1
    assert linha.honorario.cobrancas[0].texto == texto


def test_promessa_de_pagamento_exige_data(sessao):
    cliente, _ = cenario(sessao)
    alvo = selecao(sessao, cliente)
    with pytest.raises(ErroDeValidacao, match="data prometida"):
        cobrancas.registrar(
            sessao, alvo, resultado=ResultadoCobranca.PROMETEU_PAGAR
        )


def test_promessa_aparece_na_linha(sessao):
    cliente, _ = cenario(sessao)
    cobrancas.registrar(
        sessao,
        selecao(sessao, cliente),
        resultado=ResultadoCobranca.PROMETEU_PAGAR,
        promessa_data=date(2026, 9, 25),
    )
    sessao.commit()
    linha = servico_honorarios.pendentes(sessao, Filtro(cliente_id=cliente.id))[0]
    assert linha.promessa == date(2026, 9, 25)
    assert linha.promessa_vencida


def test_cancelado_nao_pode_ser_cobrado(sessao):
    cliente, honorario = cenario(sessao)
    alvo = selecao(sessao, cliente)
    servico_honorarios.cancelar(sessao, honorario, "Serviço não prestado")
    sessao.commit()
    with pytest.raises(ErroDeValidacao, match="Cancelado"):
        cobrancas.registrar(sessao, alvo)


def test_registro_em_lote_sem_mensagem(sessao):
    cliente, _ = cenario(sessao)
    linhas = cobrancas.linhas_em_aberto_do_cliente(sessao, cliente.id)
    total = cobrancas.registrar_sem_mensagem(sessao, linhas, "Cobrei por telefone")
    sessao.commit()
    assert total == 1
    cobranca = cobrancas.historico_do_cliente(sessao, cliente.id)[0]
    assert cobranca.observacao == "Cobrei por telefone"
    assert cobranca.texto == ""


def test_estorno_de_cobranca_nao_conta_mais(sessao):
    cliente, _ = cenario(sessao)
    lote = cobrancas.registrar(sessao, selecao(sessao, cliente))
    sessao.commit()
    cobrancas.estornar(sessao, lote.cobrancas[0], "Cobrei o cliente errado")
    sessao.commit()
    linha = servico_honorarios.pendentes(sessao, Filtro(cliente_id=cliente.id))[0]
    assert linha.cobrancas == 0


def test_link_whatsapp_precisa_de_telefone(sessao):
    cliente, _ = cenario(sessao)
    contato = cliente.contato_principal
    assert cobrancas.link_whatsapp(sessao, contato, "oi").startswith("https://wa.me/55")
    contato.telefone = ""
    sessao.commit()
    with pytest.raises(ErroDeValidacao, match="telefone"):
        cobrancas.link_whatsapp(sessao, contato, "oi")


def test_filtro_nunca_cobrado_e_sem_cobranca_ha_dias(sessao):
    cliente, _ = cenario(sessao)
    assert len(servico_honorarios.pendentes(sessao, Filtro(nunca_cobrado=True))) == 1
    cobrancas.registrar(sessao, selecao(sessao, cliente))
    sessao.commit()
    assert servico_honorarios.pendentes(sessao, Filtro(nunca_cobrado=True)) == []
    assert servico_honorarios.pendentes(
        sessao, Filtro(sem_cobranca_dias=7, data_referencia=date(2026, 9, 29))
    ) == []
    assert len(
        servico_honorarios.pendentes(
            sessao, Filtro(sem_cobranca_dias=7, data_referencia=date(2026, 10, 20))
        )
    ) == 1


def test_faixas_de_atraso(sessao):
    cliente, _ = cenario(sessao)
    referencia = date(2026, 9, 29)
    assert len(
        servico_honorarios.pendentes(
            sessao, Filtro(atraso_minimo=1, atraso_maximo=30, data_referencia=referencia)
        )
    ) == 1
    assert servico_honorarios.pendentes(
        sessao, Filtro(atraso_minimo=31, data_referencia=referencia)
    ) == []
