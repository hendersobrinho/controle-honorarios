"""Fábricas de dados fictícios para os testes.

Nomes, CPF/CNPJ e telefones daqui são inventados — nenhum dado de cliente real
entra no repositório.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from honorarios.dominio.enums import Periodicidade, TipoPessoa
from honorarios.dominio.valores import Competencia
from honorarios.infra.modelos import TipoHonorario
from honorarios.servicos import clientes, contratos, honorarios

CNPJ_FICTICIO = "11.222.333/0001-81"
CPF_FICTICIO = "529.982.247-25"


def cliente(
    sessao,
    nome="EMPRESA EXEMPLO LTDA",
    codigo="900",
    documento=CNPJ_FICTICIO,
    tipo=TipoPessoa.PJ,
    juros_dia="1.01",
    tratamento="Carol",
    telefone="27999990000",
):
    dados = clientes.DadosCliente(
        codigo=codigo,
        nome=nome,
        documento=documento,
        tipo_pessoa=tipo,
        juros_dia=Decimal(juros_dia),
        contatos=[
            clientes.DadosContato(
                nome="Contato Exemplo",
                nome_tratamento=tratamento,
                telefone=telefone,
                principal=True,
            )
        ],
    )
    criado = clientes.criar(sessao, dados)
    sessao.commit()
    return criado


def tipo_mensal(sessao) -> TipoHonorario:
    return sessao.scalar(select(TipoHonorario).where(TipoHonorario.nome == "Honorário mensal"))


def tipo_irpf(sessao) -> TipoHonorario:
    return sessao.scalar(select(TipoHonorario).where(TipoHonorario.nome == "Imposto de Renda"))


def tipo_avulso(sessao) -> TipoHonorario:
    return sessao.scalar(
        select(TipoHonorario).where(TipoHonorario.nome == "Alteração contratual")
    )


def honorario(
    sessao,
    cli,
    valor="1507.80",
    vencimento=date(2026, 9, 8),
    competencia=Competencia(2026, 8),  # noqa: B008 - dataclass imutável
    tipo=None,
    descricao="",
):
    dados = honorarios.DadosHonorario(
        cliente_id=cli.id,
        tipo_id=(tipo or tipo_mensal(sessao)).id,
        valor=Decimal(valor),
        vencimento=vencimento,
        competencia=competencia,
        descricao=descricao,
    )
    criado = honorarios.criar(sessao, dados)
    sessao.commit()
    return criado


def contrato(sessao, cli, valor="1507.80", dia=8, periodicidade=Periodicidade.MENSAL, tipo=None):
    dados = contratos.DadosContrato(
        cliente_id=cli.id,
        tipo_id=(tipo or tipo_mensal(sessao)).id,
        valor=Decimal(valor),
        periodicidade=periodicidade,
        dia_vencimento=dia,
        vigencia_inicio=date(2025, 1, 1),
    )
    criado = contratos.criar(sessao, dados)
    sessao.commit()
    return criado
