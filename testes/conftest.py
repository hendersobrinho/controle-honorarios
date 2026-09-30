"""Banco limpo por teste, em arquivo temporário. Nenhum dado real aqui."""

from __future__ import annotations

import os

import pytest

# a interface roda sem servidor gráfico nos testes
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from honorarios.infra import carga_inicial, db


@pytest.fixture
def pasta_dados(tmp_path, monkeypatch):
    monkeypatch.setenv("HONORARIOS_DADOS", str(tmp_path))
    return tmp_path


@pytest.fixture
def sessao(pasta_dados):
    db.encerrar()
    db.configurar(pasta_dados / "teste.db", criar=True)
    with db.sessao() as aberta:
        carga_inicial.aplicar(aberta)
        aberta.commit()
        yield aberta
    db.encerrar()


@pytest.fixture
def contexto(sessao):
    """Contexto da interface apontando para o banco do teste."""
    from datetime import date

    from honorarios.ui.contexto import Contexto

    return Contexto(sessao=sessao, data_referencia=date(2026, 9, 29))
