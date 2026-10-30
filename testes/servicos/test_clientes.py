from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from honorarios.dominio.enums import SituacaoCliente, TipoPessoa
from honorarios.servicos import calculo, clientes
from honorarios.servicos.erros import ErroDeValidacao, RegistroDuplicado
from testes import fabricas


def test_criar_cliente_com_contato_e_juros(sessao):
    cliente = fabricas.cliente(sessao)
    assert cliente.id
    assert cliente.documento == "11222333000181"
    assert cliente.nome_busca == "empresa exemplo ltda"
    assert cliente.contato_principal.nome_tratamento == "Carol"
    assert cliente.contato_principal.telefone == "5527999990000"
    assert clientes.juros_atual(cliente) == Decimal("1.0100")


def test_codigo_duplicado_e_recusado(sessao):
    fabricas.cliente(sessao, codigo="900")
    with pytest.raises(RegistroDuplicado, match="código 900"):
        fabricas.cliente(sessao, codigo="900", nome="OUTRA", documento="")


def test_documento_duplicado_aponta_o_cliente_existente(sessao):
    fabricas.cliente(sessao, codigo="900", nome="PRIMEIRA LTDA")
    with pytest.raises(RegistroDuplicado, match="PRIMEIRA LTDA"):
        fabricas.cliente(sessao, codigo="901", nome="SEGUNDA LTDA")


def test_documento_invalido(sessao):
    with pytest.raises(ErroDeValidacao, match="CPF/CNPJ inválido"):
        fabricas.cliente(sessao, documento="11.222.333/0001-99")


def test_pf_precisa_de_cpf(sessao):
    with pytest.raises(ErroDeValidacao, match="precisa de CPF"):
        fabricas.cliente(sessao, tipo=TipoPessoa.PF, documento=fabricas.CNPJ_FICTICIO)


def test_juros_obrigatorio(sessao):
    dados = clientes.DadosCliente(codigo="950", nome="SEM JUROS LTDA", juros_dia=None)
    with pytest.raises(ErroDeValidacao, match="juros por dia"):
        clientes.criar(sessao, dados)


def test_juros_novo_vale_para_tudo_que_esta_em_aberto(sessao):
    """Um valor só por empresa: trocar vale também para os juros já corridos."""
    from honorarios.infra.modelos import LogAlteracao

    cliente = fabricas.cliente(sessao, juros_dia="0.50")
    honorario = fabricas.honorario(sessao, cliente, valor="1000.00",
                                   vencimento=date(2026, 9, 1))
    assert calculo.atualizar(honorario, date(2026, 9, 21)).juros == Decimal("10.00")

    clientes.definir_juros(sessao, cliente, Decimal("1.00"), "Reajuste do boleto")
    sessao.commit()

    assert len(cliente.juros) == 1
    assert clientes.juros_atual(cliente) == Decimal("1.0000")
    assert calculo.atualizar(honorario, date(2026, 9, 21)).juros == Decimal("20.00")
    log = sessao.scalars(select(LogAlteracao).where(LogAlteracao.acao == "JUROS")).all()
    assert (Decimal(log[-1].antes), Decimal(log[-1].depois)) == (Decimal("0.5"), Decimal("1"))


def test_juros_igual_nao_mexe_e_negativo_recusado(sessao):
    cliente = fabricas.cliente(sessao, juros_dia="0.50")
    linha = cliente.juros[0]
    assert clientes.definir_juros(sessao, cliente, "0,50") is linha
    with pytest.raises(ErroDeValidacao, match="negativo"):
        clientes.definir_juros(sessao, cliente, Decimal("-1"))


def test_juros_pelo_cadastro_e_cliente_desde(sessao):
    cliente = fabricas.cliente(sessao, juros_dia="0.50")
    dados = clientes.DadosCliente(
        codigo=cliente.codigo, nome=cliente.nome, documento=cliente.documento,
        juros_dia=Decimal("0.75"), cliente_desde=date(2024, 3, 10),
        contatos=[clientes.DadosContato(id=c.id, nome=c.nome, telefone=c.telefone,
                                        principal=c.principal) for c in cliente.contatos])
    clientes.atualizar(sessao, cliente, dados)
    sessao.commit()
    assert clientes.juros_atual(cliente) == Decimal("0.7500")
    assert cliente.cliente_desde == date(2024, 3, 10)


def test_listar_com_busca_sem_acento_e_pontuacao(sessao):
    fabricas.cliente(sessao, nome="CLÍNICA SAÚDE VITÓRIA", codigo="307")
    assert len(clientes.listar(sessao, termo="clinica saude vitoria")) == 1
    assert len(clientes.listar(sessao, termo="307")) == 1
    assert len(clientes.listar(sessao, termo="11.222.333")) == 1
    assert len(clientes.listar(sessao, termo="inexistente")) == 0


def test_listar_traz_total_em_aberto_atualizado(sessao):
    cliente = fabricas.cliente(sessao, juros_dia="1.00")
    fabricas.honorario(sessao, cliente, valor="1000.00", vencimento=date(2026, 9, 19))
    linhas = clientes.listar(sessao, data_referencia=date(2026, 9, 29))
    assert linhas[0].quantidade_em_aberto == 1
    assert linhas[0].maior_atraso == 10
    assert linhas[0].total_em_aberto == Decimal("1010.00")


def test_filtro_pf_pj_e_situacao(sessao):
    fabricas.cliente(sessao, codigo="1", nome="PJ LTDA", documento=fabricas.CNPJ_FICTICIO)
    fabricas.cliente(
        sessao, codigo="2", nome="PESSOA FISICA", documento=fabricas.CPF_FICTICIO,
        tipo=TipoPessoa.PF,
    )
    assert len(clientes.listar(sessao, tipo_pessoa=TipoPessoa.PF)) == 1
    assert len(clientes.listar(sessao, tipo_pessoa=TipoPessoa.PJ)) == 1
    assert len(clientes.listar(sessao, situacao=SituacaoCliente.ATIVO)) == 2


def test_somente_com_debito(sessao):
    com = fabricas.cliente(sessao, codigo="1", nome="COM DEBITO", documento=fabricas.CNPJ_FICTICIO)
    fabricas.cliente(sessao, codigo="2", nome="SEM DEBITO", documento=fabricas.CPF_FICTICIO,
                     tipo=TipoPessoa.PF)
    fabricas.honorario(sessao, com)
    linhas = clientes.listar(sessao, somente_com_debito=True)
    assert [linha.cliente.nome for linha in linhas] == ["COM DEBITO"]


def test_excluir_com_debito_em_aberto_e_bloqueado(sessao):
    cliente = fabricas.cliente(sessao)
    fabricas.honorario(sessao, cliente)
    with pytest.raises(ErroDeValidacao, match="em aberto"):
        clientes.excluir(sessao, cliente)


def test_exclusao_e_logica(sessao):
    cliente = fabricas.cliente(sessao)
    clientes.excluir(sessao, cliente, "Encerrou o contrato")
    sessao.commit()
    assert cliente.excluido_em is not None
    assert clientes.listar(sessao) == []
    assert clientes.obter(sessao, cliente.id) is not None


def test_um_unico_contato_principal(sessao):
    cliente = fabricas.cliente(sessao)
    dados = clientes.DadosCliente(
        codigo=cliente.codigo,
        nome=cliente.nome,
        documento=cliente.documento,
        juros_dia=None,
        contatos=[
            clientes.DadosContato(nome="A", telefone="27999990001", principal=True),
            clientes.DadosContato(nome="B", telefone="27999990002", principal=True),
        ],
    )
    clientes.atualizar(sessao, cliente, dados)
    sessao.commit()
    assert sum(1 for c in cliente.contatos if c.principal) == 1
