"""Subtipos do cliente pessoa física, cadastrados pelo usuário."""

from __future__ import annotations

import pytest

from honorarios.dominio.enums import TipoPessoa
from honorarios.servicos import clientes, subtipos
from honorarios.servicos.erros import ErroDeValidacao, RegistroDuplicado
from testes import fabricas


def _pf(sessao, nome="FULANA DOMESTICA", subtipo=""):
    cliente = fabricas.cliente(sessao, codigo="", nome=nome, documento="",
                               tipo=TipoPessoa.PF)
    if subtipo:
        dados = _dados(cliente)
        dados.subtipo = subtipo
        clientes.atualizar(sessao, cliente, dados)
    return cliente


def _dados(cliente):
    return clientes.DadosCliente(
        codigo=cliente.codigo, nome=cliente.nome, documento=cliente.documento,
        tipo_pessoa=cliente.tipo_pessoa, subtipo=cliente.subtipo,
        juros_dia=clientes.juros_atual(cliente),
        contatos=[clientes.DadosContato(id=c.id, nome=c.nome, nome_tratamento=c.nome_tratamento,
                                        telefone=c.telefone, email=c.email,
                                        principal=c.principal) for c in cliente.contatos],
    )


def test_domestica_vem_cadastrada(sessao):
    assert [s.nome for s in subtipos.listar(sessao)] == ["Doméstica"]


def test_criar_e_usar_no_cliente(sessao):
    subtipos.criar(sessao, "  Produtor   rural ")
    cliente = _pf(sessao, subtipo="produtor RURAL")        # acento/maiúscula não importam
    assert cliente.subtipo == "Produtor rural"
    assert subtipos.uso(sessao) == {"Produtor rural": 1}


def test_nome_repetido_e_recusado(sessao):
    with pytest.raises(RegistroDuplicado, match="Doméstica"):
        subtipos.criar(sessao, "domestica")
    with pytest.raises(ErroDeValidacao):
        subtipos.criar(sessao, "   ")


def test_subtipo_que_nao_existe_e_recusado_no_cadastro(sessao):
    with pytest.raises(ErroDeValidacao, match="não existe"):
        _pf(sessao, subtipo="Inventado")


def test_pessoa_juridica_fica_sem_subtipo(sessao):
    cliente = fabricas.cliente(sessao)
    dados = _dados(cliente)
    dados.subtipo = "Doméstica"
    clientes.atualizar(sessao, cliente, dados)
    assert cliente.subtipo == ""


def test_renomear_muda_nos_clientes(sessao):
    cliente = _pf(sessao, subtipo="Doméstica")
    [domestica] = subtipos.listar(sessao)
    subtipos.renomear(sessao, domestica, "Empregada doméstica")
    sessao.refresh(cliente)
    assert cliente.subtipo == "Empregada doméstica"


def test_desativado_some_da_escolha_mas_o_cliente_continua(sessao):
    cliente = _pf(sessao, subtipo="Doméstica")
    [domestica] = subtipos.listar(sessao)
    subtipos.alternar(sessao, domestica)
    assert subtipos.listar(sessao) == []
    clientes.atualizar(sessao, cliente, _dados(cliente))    # salvar de novo não quebra
    assert cliente.subtipo == "Doméstica"


def test_importacao_cadastra_o_subtipo_que_falta(sessao):
    assert subtipos.resolver(sessao, "Caseiro", criar_se_faltar=True) == "Caseiro"
    assert subtipos.resolver(sessao, "-") == ""
    assert "Caseiro" in [s.nome for s in subtipos.listar(sessao)]
