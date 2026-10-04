"""Criação e atualização do esquema via Alembic.

Banco novo: cria as tabelas pelo metadata e marca a revisão mais recente.
Banco existente: aplica as migrations que faltam.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from . import db
from .modelos import Base

MIGRACOES = Path(__file__).resolve().parent / "migracoes"


def _config_alembic() -> Config:
    """Sem o alembic.ini: as migrations vão junto do pacote (também no instalado)."""
    config = Config()
    config.set_main_option("script_location", str(MIGRACOES))
    return config


def preparar(caminho: Path | str | None = None) -> None:
    """Banco novo (sem tabelas): cria tudo e marca a última versão; banco que já
    existe: aplica as migrations que faltam. Vale para SQLite e PostgreSQL."""
    engine = db.configurar(caminho, criar=False)
    config = _config_alembic()
    config.attributes["engine"] = engine
    tabelas = inspect(engine).get_table_names()
    novo = not tabelas
    if novo:
        Base.metadata.create_all(engine)
        command.stamp(config, "head")
        return
    if "alembic_version" not in tabelas:
        # banco criado antes do Alembic entrar: alinha sem recriar nada
        Base.metadata.create_all(engine)
        command.stamp(config, "head")
        return
    command.upgrade(config, "head")
