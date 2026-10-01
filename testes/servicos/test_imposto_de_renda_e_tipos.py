"""Clientes só de Imposto de Renda e o cadastro de grupos e tipos."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from honorarios.dominio.enums import ExigeCompetencia, TipoPessoa
from honorarios.dominio.valores import Competencia
from honorarios.infra.modelos import GrupoHonorario
from honorarios.servicos import honorarios as servico_honorarios
from honorarios.servicos import tipos
from honorarios.servicos.erros import ErroDeValidacao, RegistroDuplicado
from honorarios.servicos.honorarios import Filtro
from testes import fabricas


def pessoa(sessao, codigo, nome, documento=""):
    return fabricas.cliente(
        sessao, codigo=codigo, nome=nome, documento=documento, tipo=TipoPessoa.PF
    )


def irpf(sessao, cliente, ano=2026, vencimento=date(2026, 6, 25)):
    return fabricas.honorario(
        sessao, cliente, valor="400.00", vencimento=vencimento,
        competencia=Competencia(ano), tipo=fabricas.tipo_irpf(sessao),
    )


# ------------------------------------------------------ quem é cliente só de IR


def test_quem_so_tem_irpf_e_cliente_so_de_ir(sessao):
    cliente = pessoa(sessao, "1", "SO IMPOSTO", fabricas.CPF_FICTICIO)
    irpf(sessao, cliente)
    assert servico_honorarios.clientes_so_imposto_de_renda(sessao) == {cliente.id}


def test_quem_tem_mensal_e_irpf_continua_cliente_comum(sessao):
    cliente = fabricas.cliente(sessao, codigo="2", nome="MENSAL COM IR")
    fabricas.honorario(sessao, cliente)
    irpf(sessao, cliente)
    assert servico_honorarios.clientes_so_imposto_de_renda(sessao) == set()


def test_contrato_mensal_ativo_impede_ser_so_de_ir(sessao):
    cliente = fabricas.cliente(sessao, codigo="3", nome="CONTRATO SEM LANCAMENTO")
    irpf(sessao, cliente)
    fabricas.contrato(sessao, cliente)
    assert servico_honorarios.clientes_so_imposto_de_renda(sessao) == set()


def test_honorario_cancelado_de_outro_tipo_nao_conta(sessao):
    cliente = pessoa(sessao, "4", "IR COM AVULSO CANCELADO", fabricas.CPF_FICTICIO)
    irpf(sessao, cliente)
    avulso = fabricas.honorario(
        sessao, cliente, valor="100.00", vencimento=date(2026, 7, 1),
        competencia=Competencia(), tipo=fabricas.tipo_avulso(sessao), descricao="ata",
    )
    servico_honorarios.cancelar(sessao, avulso, "lançado por engano")
    sessao.commit()
    assert servico_honorarios.clientes_so_imposto_de_renda(sessao) == {cliente.id}


def test_regra_segue_a_marcacao_do_grupo_e_nao_o_nome(sessao):
    cliente = pessoa(sessao, "5", "SO IMPOSTO", fabricas.CPF_FICTICIO)
    irpf(sessao, cliente)
    grupo = tipos.grupo_do_imposto_de_renda(sessao)
    tipos.salvar_grupo(sessao, grupo, "IRPF (declarações)", imposto_de_renda=True)
    sessao.commit()
    assert servico_honorarios.clientes_so_imposto_de_renda(sessao) == {cliente.id}


def test_filtro_separa_os_clientes_so_de_ir(sessao):
    so_ir = pessoa(sessao, "6", "SO IMPOSTO", fabricas.CPF_FICTICIO)
    irpf(sessao, so_ir)
    comum = fabricas.cliente(sessao, codigo="7", nome="MENSAL")
    fabricas.honorario(sessao, comum)

    referencia = date(2026, 9, 30)
    sem_ir = servico_honorarios.pendentes(
        sessao, Filtro(clientes_so_ir=False, data_referencia=referencia)
    )
    so = servico_honorarios.pendentes(
        sessao, Filtro(clientes_so_ir=True, data_referencia=referencia)
    )
    todos = servico_honorarios.pendentes(sessao, Filtro(data_referencia=referencia))
    assert [linha.cliente.id for linha in sem_ir] == [comum.id]
    assert [linha.cliente.id for linha in so] == [so_ir.id]
    assert len(todos) == 2


# -------------------------------------------------------------- grupos e tipos


def test_so_um_grupo_pode_ser_o_de_imposto_de_renda(sessao):
    novo = tipos.salvar_grupo(sessao, None, "Declarações", imposto_de_renda=True)
    sessao.commit()
    marcados = sessao.scalars(
        select(GrupoHonorario).where(GrupoHonorario.imposto_de_renda.is_(True))
    ).all()
    assert [grupo.id for grupo in marcados] == [novo.id]


def test_grupo_com_nome_repetido_e_recusado(sessao):
    with pytest.raises(RegistroDuplicado):
        tipos.salvar_grupo(sessao, None, "Mensais")
    with pytest.raises(ErroDeValidacao):
        tipos.salvar_grupo(sessao, None, "   ")


def test_mover_grupo_troca_a_ordem(sessao):
    antes = [grupo.nome for grupo in tipos.listar_grupos(sessao)]
    segundo = tipos.listar_grupos(sessao)[1]
    tipos.mover_grupo(sessao, segundo, -1)
    sessao.commit()
    depois = [grupo.nome for grupo in tipos.listar_grupos(sessao)]
    assert depois[0] == antes[1] and depois[1] == antes[0]

    # nas pontas, não sai do lugar
    primeiro = tipos.listar_grupos(sessao)[0]
    tipos.mover_grupo(sessao, primeiro, -1)
    assert tipos.listar_grupos(sessao)[0].id == primeiro.id


def test_desativar_grupo_com_tipo_ativo_e_bloqueado(sessao):
    mensais = next(g for g in tipos.listar_grupos(sessao) if g.nome == "Mensais")
    with pytest.raises(ErroDeValidacao, match="tipo"):
        tipos.desativar_grupo(sessao, mensais)


def test_previa_dos_textos_de_cada_competencia(sessao):
    um, empresa, item = tipos.previa_dos_textos(
        "Honorário mensal", ExigeCompetencia.MES,
        "honorário referente à competência {competencia}",
        "honorário da {empresa}", "{nome_do_tipo} – {valor}",
    )
    assert um == "honorário referente à competência 08/2026"
    assert empresa == "honorário da EMPRESA EXEMPLO LTDA"
    assert item == "Honorário mensal – R$ 599,70"

    um, _, _ = tipos.previa_dos_textos(
        "IRPF", ExigeCompetencia.ANO, "imposto de renda/{ano}", "", ""
    )
    assert um == "imposto de renda/2026"


def test_previa_avisa_variavel_inexistente(sessao):
    um, _, _ = tipos.previa_dos_textos(
        "X", ExigeCompetencia.MES, "referente a {competencai}", "", ""
    )
    assert "⚠" in um and "{competencai}" in um
