"""Backup e restauração com o banco no PostgreSQL (roda com HONORARIOS_TESTE_PG)."""

from __future__ import annotations

import os
import sqlite3
from datetime import date

import pytest

from honorarios.dominio.enums import TipoPessoa
from honorarios.dominio.valores import Competencia
from honorarios.infra import esquema
from honorarios.infra.modelos import Cliente, Honorario
from honorarios.servicos import backup
from testes import fabricas

pytestmark = pytest.mark.skipif(not os.environ.get("HONORARIOS_TESTE_PG"),
                                reason="só com um PostgreSQL de teste")


def test_backup_e_restauracao_no_postgres(sessao):
    from sqlalchemy import select

    esquema.preparar(os.environ["HONORARIOS_TESTE_PG"])   # marca a versão do banco
    empresa = fabricas.cliente(sessao, codigo="700", nome="EMPRESA PAGADORA", documento="")
    pessoa = fabricas.cliente(sessao, codigo="701", nome="SOCIO", documento="",
                              tipo=TipoPessoa.PF)
    pessoa.empresa_id = empresa.id                         # referência à própria tabela
    fabricas.honorario(sessao, empresa, valor="1234.56", vencimento=date(2026, 9, 10),
                       competencia=Competencia(2026, 8))
    sessao.commit()

    arquivo = backup.gerar("teste")
    copia = sqlite3.connect(arquivo)
    assert copia.execute("select count(*) from cliente").fetchone()[0] == 2
    assert copia.execute("select version_num from alembic_version").fetchone()[0]

    # estraga o banco e restaura
    sessao.query(Honorario).delete()
    sessao.commit()
    sessao.close()
    backup.restaurar(arquivo)
    sessao.expire_all()
    [honorario] = sessao.scalars(select(Honorario)).all()
    assert str(honorario.valor_original) == "1234.56"
    assert sessao.get(Cliente, pessoa.id).empresa_id == empresa.id
    # os ids continuam depois do maior (o contador foi acertado)
    novo = fabricas.cliente(sessao, codigo="702", nome="OUTRO", documento="")
    assert novo.id > pessoa.id
    assert any("antes-da-restauracao" in b.caminho.name for b in backup.listar())
