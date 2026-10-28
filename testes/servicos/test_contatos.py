"""Contatos: um por um e a lista das empresas cruzada com o cadastro."""

from __future__ import annotations

import pytest

from honorarios.servicos import contatos
from honorarios.servicos.erros import ErroDeValidacao
from testes import fabricas


@pytest.fixture
def empresas(sessao):
    """Alfa tem o telefone (27) 99999-0000 cadastrado; Beta, CNPJ; Gama, só o nome."""
    alfa = fabricas.cliente(sessao, codigo="100", nome="ALFA COMERCIO LTDA", documento="",
                            telefone="27999990000")
    beta = fabricas.cliente(sessao, codigo="200", nome="BETA SERVICOS LTDA",
                            documento=fabricas.CNPJ_FICTICIO, telefone="27988880000")
    gama = fabricas.cliente(sessao, codigo="300", nome="GAMA ÓTICA LTDA", documento="",
                            telefone="27977770000")
    return alfa, beta, gama


def test_telefone_igual_com_ou_sem_55_e_o_nono_digito():
    assert contatos.mesmo_telefone("27 99999-0000", "+55 (27) 99999-0000")
    assert contatos.mesmo_telefone("(27) 9999-0000", "5527999990000")   # sem o 9
    assert contatos.mesmo_telefone("99999-0000", "27999990000")         # sem DDD
    assert not contatos.mesmo_telefone("27999990000", "11999990000")    # outro DDD


def test_cruza_por_codigo_cnpj_telefone_e_nome(sessao, empresas):
    alfa, beta, gama = empresas
    itens = [
        contatos.ItemContato(codigo="100", nome="Ana Souza", telefone="27911112222"),
        contatos.ItemContato(documento="11222333000181", nome="Bruno", telefone="27933334444"),
        contatos.ItemContato(telefone_empresa="(27) 9999-0000", nome="Carla",
                             telefone="27955556666"),
        contatos.ItemContato(nome_empresa="Gama Otica Ltda", nome="Davi", email="d@gama.com"),
    ]

    cruzados = contatos.cruzar(sessao, itens)

    assert [(c.cliente, c.achado_por, c.acao) for c in cruzados] == [
        (alfa, "código", "novo"), (beta, "CPF/CNPJ", "novo"),
        (alfa, "telefone", "novo"), (gama, "nome", "novo"),
    ]


def test_cruzar_nao_grava_e_gravar_cadastra(sessao, empresas):
    alfa, _, _ = empresas
    itens = [contatos.ItemContato(codigo="100", nome="Ana Souza", tratamento="Ana",
                                  telefone="27911112222", principal=True)]

    cruzados = contatos.cruzar(sessao, itens)
    assert len(alfa.contatos) == 1

    assert contatos.gravar(sessao, cruzados) == 1
    sessao.commit()
    nova = alfa.contato_principal
    assert (nova.nome, nova.nome_tratamento, nova.telefone) == ("Ana Souza", "Ana",
                                                                 "5527911112222")
    assert sum(c.principal for c in alfa.contatos) == 1


def test_telefone_ja_cadastrado_atualiza_o_contato(sessao, empresas):
    alfa, _, _ = empresas
    existente = alfa.contatos[0]
    itens = [contatos.ItemContato(codigo="100", nome="Responsável Novo",
                                  telefone="(27) 9999-0000", email="r@alfa.com")]

    cruzado = contatos.cruzar(sessao, itens)[0]
    assert (cruzado.acao, cruzado.contato) == ("atualizar", existente)
    assert set(cruzado.mudancas) >= {"nome", "e-mail"}

    contatos.gravar(sessao, [cruzado])
    sessao.commit()
    assert len(alfa.contatos) == 1
    assert (existente.nome, existente.email) == ("Responsável Novo", "r@alfa.com")
    assert existente.nome_tratamento == "Carol"   # vazio na lista: não apaga


def test_o_que_nao_bate_nao_grava_e_diz_o_motivo(sessao, empresas):
    fabricas.cliente(sessao, codigo="400", nome="OUTRA LTDA", documento="",
                     telefone="27966660000")
    from honorarios.servicos import clientes

    # o mesmo telefone em duas empresas
    clientes.atualizar(sessao, empresas[1], clientes.DadosCliente(
        codigo="200", nome="BETA SERVICOS LTDA", documento=fabricas.CNPJ_FICTICIO,
        juros_dia=None, contatos=[
            clientes.DadosContato(id=empresas[1].contatos[0].id, nome="x",
                                  telefone="27988880000", principal=True),
            clientes.DadosContato(nome="y", telefone="27966660000"),
        ]))
    sessao.commit()
    itens = [
        contatos.ItemContato(codigo="999", nome="Fulano", telefone="27900000000"),
        contatos.ItemContato(telefone_empresa="27966660000", nome="Ciclano",
                             telefone="27900000001"),
        contatos.ItemContato(nome="Sem empresa", telefone="27900000002"),
        contatos.ItemContato(codigo="100"),
        contatos.ItemContato(codigo="100", nome="Ana", telefone="27911112222"),
        contatos.ItemContato(codigo="100", nome="Ana de novo", telefone="27 91111-2222"),
    ]

    cruzados = contatos.cruzar(sessao, itens)

    assert [c.acao for c in cruzados] == ["ignorado"] * 4 + ["novo", "ignorado"]
    assert "nenhum cliente com 999" in cruzados[0].motivo
    assert "mais de um cliente" in cruzados[1].motivo
    assert "não diz de qual empresa" in cruzados[2].motivo
    assert "sem nome, telefone nem e-mail" in cruzados[3].motivo
    assert cruzados[5].motivo == "repetido na lista"


def test_adicionar_recusa_telefone_repetido_e_remover_passa_o_principal(sessao, empresas):
    alfa, _, _ = empresas
    with pytest.raises(ErroDeValidacao, match="já tem um contato"):
        contatos.adicionar(sessao, alfa, "Outro", telefone="27 99999-0000")

    novo = contatos.adicionar(sessao, alfa, "Segundo", telefone="27922223333")
    principal = alfa.contato_principal
    contatos.remover(sessao, principal)
    sessao.commit()
    assert alfa.contatos == [novo] and novo.principal
