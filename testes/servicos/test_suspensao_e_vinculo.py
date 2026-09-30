"""Suspensão da cobrança e vínculo de pessoa física com a empresa que paga."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from honorarios.dominio.enums import TipoPessoa
from honorarios.dominio.valores import Competencia, hoje
from honorarios.servicos import clientes, cobrancas
from honorarios.servicos import honorarios as servico_honorarios
from honorarios.servicos.erros import ErroDeValidacao
from honorarios.servicos.honorarios import Filtro
from testes import fabricas


@pytest.fixture
def empresa(sessao):
    cliente = fabricas.cliente(sessao, codigo="700", nome="EMPRESA PAGADORA LTDA")
    fabricas.honorario(sessao, cliente, valor="1000.00", vencimento=date(2026, 8, 10))
    return cliente


@pytest.fixture
def pessoa(sessao, empresa):
    cliente = fabricas.cliente(
        sessao,
        codigo="701",
        nome="SOCIO EXEMPLO DA SILVA",
        documento=fabricas.CPF_FICTICIO,
        tipo=TipoPessoa.PF,
        juros_dia="0.20",
    )
    fabricas.honorario(
        sessao,
        cliente,
        valor="500.00",
        vencimento=date(2026, 8, 20),
        competencia=Competencia(2026, 7),
    )
    return cliente


# ------------------------------------------------------------------ suspensão


def test_suspender_tira_das_filas_sem_mexer_na_divida(sessao, empresa):
    clientes.suspender_cobranca(sessao, empresa, "Empresa em acordo judicial")
    sessao.commit()

    assert empresa.suspensao_ativa()
    assert "Cobrança suspensa" in clientes.suspensao(empresa)
    # a dívida continua: só a cobrança parou
    pendentes = servico_honorarios.pendentes(sessao, Filtro(data_referencia=date(2026, 9, 30)))
    assert len(pendentes) == 1
    assert pendentes[0].atualizacao.juros > Decimal("0.00")
    assert pendentes[0].cobranca_suspensa

    sem_suspensos = servico_honorarios.pendentes(
        sessao, Filtro(data_referencia=date(2026, 9, 30), incluir_cobranca_suspensa=False)
    )
    assert sem_suspensos == []


def test_fila_do_dia_e_de_envio_ignoram_suspensos(sessao, empresa):
    assert cobrancas.fila_de_envio(sessao)
    clientes.suspender_cobranca(sessao, empresa, "Negociação em curso")
    sessao.commit()
    assert cobrancas.fila_de_envio(sessao) == []
    assert all(not secao.linhas for secao in cobrancas.fila_do_dia(sessao))


def test_registrar_cobranca_de_suspenso_e_recusado(sessao, empresa):
    linhas = cobrancas.linhas_em_aberto_do_cliente(sessao, empresa.id)
    clientes.suspender_cobranca(sessao, empresa, "Empresa baixada")
    sessao.commit()
    with pytest.raises(ErroDeValidacao, match="suspensa"):
        cobrancas.registrar(
            sessao, cobrancas.Selecao(cliente=empresa, linhas=linhas), texto="oi"
        )


def test_suspensao_com_prazo_expira_sozinha(sessao, empresa):
    clientes.suspender_cobranca(
        sessao, empresa, "Espera do acordo", ate=hoje() + timedelta(days=10)
    )
    sessao.commit()
    assert empresa.suspensao_ativa(hoje())
    assert not empresa.suspensao_ativa(hoje() + timedelta(days=11))
    assert "até" in clientes.suspensao(empresa)


def test_suspensao_exige_motivo_e_data_futura(sessao, empresa):
    with pytest.raises(ErroDeValidacao, match="por que"):
        clientes.suspender_cobranca(sessao, empresa, "  ")
    with pytest.raises(ErroDeValidacao, match="já passou"):
        clientes.suspender_cobranca(
            sessao, empresa, "motivo", ate=hoje() - timedelta(days=1)
        )


def test_retomar_libera_a_cobranca(sessao, empresa):
    clientes.suspender_cobranca(sessao, empresa, "Acordo")
    sessao.commit()
    clientes.retomar_cobranca(sessao, empresa, "Acordo encerrado")
    sessao.commit()
    assert not empresa.suspensao_ativa()
    assert clientes.suspensao(empresa) == ""
    assert cobrancas.fila_de_envio(sessao)
    with pytest.raises(ErroDeValidacao, match="não está suspensa"):
        clientes.retomar_cobranca(sessao, empresa)


# -------------------------------------------------------------------- vínculo


def test_vincular_pessoa_fisica_a_empresa(sessao, empresa, pessoa):
    dados = clientes.DadosCliente(
        codigo=pessoa.codigo,
        nome=pessoa.nome,
        documento=pessoa.documento,
        tipo_pessoa=TipoPessoa.PF,
        empresa_id=empresa.id,
    )
    clientes.atualizar(sessao, pessoa, dados)
    sessao.commit()

    assert pessoa.empresa_id == empresa.id
    assert [c.id for c in clientes.vinculados(sessao, empresa)] == [pessoa.id]


def test_empresa_cobra_os_honorarios_da_pessoa_vinculada(sessao, empresa, pessoa):
    pessoa.empresa_id = empresa.id
    sessao.commit()

    sozinha = cobrancas.linhas_em_aberto_do_cliente(sessao, empresa.id)
    assert len(sozinha) == 1

    com_vinculados = cobrancas.linhas_em_aberto_do_cliente(
        sessao, empresa.id, incluir_vinculados=True
    )
    assert len(com_vinculados) == 2
    assert {linha.cliente.id for linha in com_vinculados} == {empresa.id, pessoa.id}


def test_mensagem_diz_de_quem_e_cada_honorario(sessao, empresa, pessoa):
    pessoa.empresa_id = empresa.id
    sessao.commit()
    linhas = cobrancas.linhas_em_aberto_do_cliente(
        sessao, empresa.id, date(2026, 9, 30), incluir_vinculados=True
    )
    texto = cobrancas.gerar_texto(
        sessao,
        cobrancas.Selecao(cliente=empresa, linhas=linhas, data_referencia=date(2026, 9, 30)),
    )
    assert "SOCIO EXEMPLO DA SILVA: honorário referente à competência 07/2026" in texto
    assert "Constam em aberto os seguintes honorários" in texto


def test_um_honorario_de_terceiro_ainda_usa_a_lista(sessao, empresa, pessoa):
    """Com honorário de outra pessoa, a mensagem precisa dizer de quem é."""
    pessoa.empresa_id = empresa.id
    sessao.commit()
    linhas = [
        linha
        for linha in cobrancas.linhas_em_aberto_do_cliente(
            sessao, empresa.id, date(2026, 9, 30), incluir_vinculados=True
        )
        if linha.cliente.id == pessoa.id
    ]
    texto = cobrancas.gerar_texto(
        sessao,
        cobrancas.Selecao(cliente=empresa, linhas=linhas, data_referencia=date(2026, 9, 30)),
    )
    assert "SOCIO EXEMPLO DA SILVA" in texto
    assert "Constam em aberto" in texto


def test_vinculo_so_de_pessoa_fisica_para_empresa(sessao, empresa, pessoa):
    outra = fabricas.cliente(sessao, codigo="702", nome="OUTRA EMPRESA LTDA", documento="")
    dados = clientes.DadosCliente(
        codigo=outra.codigo, nome=outra.nome, tipo_pessoa=TipoPessoa.PJ, empresa_id=empresa.id
    )
    with pytest.raises(ErroDeValidacao, match="Só pessoa física"):
        clientes.atualizar(sessao, outra, dados)

    dados_pessoa = clientes.DadosCliente(
        codigo=pessoa.codigo,
        nome=pessoa.nome,
        documento=pessoa.documento,
        tipo_pessoa=TipoPessoa.PF,
        empresa_id=pessoa.id,
    )
    with pytest.raises(ErroDeValidacao, match="ele mesmo"):
        clientes.atualizar(sessao, pessoa, dados_pessoa)


def test_vinculo_nao_encadeia(sessao, empresa, pessoa):
    pessoa.empresa_id = empresa.id
    sessao.commit()
    outra = fabricas.cliente(
        sessao, codigo="703", nome="TERCEIRA PESSOA", documento="", tipo=TipoPessoa.PF
    )
    dados = clientes.DadosCliente(
        codigo=outra.codigo, nome=outra.nome, tipo_pessoa=TipoPessoa.PF, empresa_id=pessoa.id
    )
    with pytest.raises(ErroDeValidacao, match="pessoa jurídica"):
        clientes.atualizar(sessao, outra, dados)


def test_empresas_disponiveis_para_vinculo(sessao, empresa, pessoa):
    disponiveis = clientes.empresas_para_vinculo(sessao)
    assert empresa.id in [c.id for c in disponiveis]
    assert pessoa.id not in [c.id for c in disponiveis]
