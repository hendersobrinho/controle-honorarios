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


class _CofreDeTeste:
    """Cofre de senhas em memória: os testes nunca tocam o cofre de verdade."""

    def __init__(self) -> None:
        self.dados: dict[tuple[str, str], str] = {}

    def set_password(self, servico, nome, valor):
        self.dados[(servico, nome)] = valor

    def get_password(self, servico, nome):
        return self.dados.get((servico, nome))

    def delete_password(self, servico, nome):
        self.dados.pop((servico, nome), None)


@pytest.fixture(autouse=True)
def cofre(monkeypatch):
    from honorarios.servicos import caixa_email

    falso = _CofreDeTeste()
    monkeypatch.setattr(caixa_email, "_cofre", lambda: falso)
    return falso
