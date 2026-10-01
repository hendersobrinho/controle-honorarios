"""Rankings de clientes e a busca leve usada pelo seletor de cliente."""

from __future__ import annotations

from datetime import date

import pytest

from honorarios.dominio.enums import TipoPessoa
from honorarios.dominio.valores import Competencia
from honorarios.servicos import clientes, cobrancas, rankings
from testes import fabricas

REFERENCIA = date(2026, 9, 30)


@pytest.fixture
def carteira(sessao):
    """Três clientes com dívidas de tamanhos e idades diferentes."""
    grande = fabricas.cliente(
        sessao, codigo="10", nome="GRANDE DEVEDORA LTDA", juros_dia="1.00"
    )
    antiga = fabricas.cliente(
        sessao, codigo="11", nome="ANTIGA E PEQUENA", documento=fabricas.CPF_FICTICIO,
        tipo=TipoPessoa.PF, juros_dia="0.10",
    )
    fabricas.cliente(sessao, codigo="12", nome="EM DIA LTDA", documento="", juros_dia="0.50")
    for cliente in (grande, antiga):
        cliente.juros[0].vigencia_inicio = date(2020, 1, 1)
    sessao.commit()

    for mes in (6, 7, 8):
        fabricas.honorario(
            sessao, grande, valor="3000.00",
            vencimento=date(2026, mes + 1, 5), competencia=Competencia(2026, mes),
        )
    fabricas.honorario(
        sessao, antiga, valor="100.00",
        vencimento=date(2026, 1, 10), competencia=Competencia(2025, 12),
    )
    return grande, antiga


def test_ranking_de_valor_e_de_tempo_ordenam_diferente(sessao, carteira):
    grande, antiga = carteira
    resultado = rankings.calcular(sessao, REFERENCIA)

    devedores = resultado["devedores"].itens
    assert [item.cliente.id for item in devedores] == [grande.id, antiga.id]
    assert devedores[0].rotulo.startswith("R$ 9.")

    tempo = resultado["tempo"].itens
    assert [item.cliente.id for item in tempo] == [antiga.id, grande.id]
    assert tempo[0].rotulo == "263 dias"
    assert "≈ 8 meses" in tempo[0].detalhe


def test_ranking_de_quantidade_usa_plural_certo(sessao, carteira):
    resultado = rankings.calcular(sessao, REFERENCIA)
    rotulos = [item.rotulo for item in resultado["honorarios"].itens]
    assert rotulos == ["3 boletos", "1 boleto"]


def test_tentativas_contam_mensagens_e_nao_honorarios(sessao, carteira):
    grande, _ = carteira
    linhas = cobrancas.linhas_em_aberto_do_cliente(sessao, grande.id, REFERENCIA)
    # uma mensagem com os 3 honorários = uma tentativa só
    cobrancas.registrar(sessao, cobrancas.Selecao(cliente=grande, linhas=linhas), texto="oi")
    cobrancas.registrar(sessao, cobrancas.Selecao(cliente=grande, linhas=linhas[:1]), texto="oi")
    sessao.commit()
    procurados = rankings.calcular(sessao, REFERENCIA)["cobrados"]
    assert procurados.itens[0].rotulo == "2 tentativas"
    assert "2 tentativas registradas" in procurados.curiosidade


def test_limite_do_ranking(sessao, carteira):
    resultado = rankings.calcular(sessao, REFERENCIA, limite=1)
    assert all(len(ranking.itens) <= 1 for ranking in resultado.values())


def test_sem_dividas_mostra_mensagem_de_vazio(sessao):
    resultado = rankings.calcular(sessao, REFERENCIA)
    assert all(ranking.itens == [] for ranking in resultado.values())
    assert "🎉" in resultado["devedores"].vazio


# --------------------------------------------------------------------- busca


def test_busca_ignora_acento_e_caixa(sessao):
    fabricas.cliente(sessao, codigo="20", nome="CLÍNICA SÃO JOSÉ LTDA")
    assert [c.codigo for c in clientes.buscar(sessao, "clinica sao jose")] == ["20"]


def test_busca_por_codigo_exato_vem_primeiro(sessao):
    fabricas.cliente(sessao, codigo="1302", nome="AAA PRIMEIRA", documento="")
    fabricas.cliente(sessao, codigo="302", nome="ZZZ SEGUNDA", documento=fabricas.CPF_FICTICIO,
                     tipo=TipoPessoa.PF)
    assert [c.codigo for c in clientes.buscar(sessao, "302")][0] == "302"


def test_busca_por_parte_do_documento(sessao):
    fabricas.cliente(sessao, codigo="30", nome="EMPRESA X")
    assert [c.codigo for c in clientes.buscar(sessao, "222.333")] == ["30"]


def test_busca_filtra_tipo_e_exclui_o_proprio(sessao):
    empresa = fabricas.cliente(sessao, codigo="40", nome="EMPRESA PJ")
    pessoa = fabricas.cliente(
        sessao, codigo="41", nome="PESSOA PF", documento=fabricas.CPF_FICTICIO, tipo=TipoPessoa.PF
    )
    so_pj = clientes.buscar(sessao, "", tipo_pessoa=TipoPessoa.PJ)
    assert [c.id for c in so_pj] == [empresa.id]
    sem_ele = clientes.buscar(sessao, "", excluir_id=pessoa.id)
    assert pessoa.id not in [c.id for c in sem_ele]
