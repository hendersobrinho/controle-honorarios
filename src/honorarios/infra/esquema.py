"""Criação e atualização do esquema via Alembic.

Banco novo: cria as tabelas pelo metadata e marca a revisão mais recente.
Banco existente: aplica as migrations que faltam.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from ..config.caminhos import caminho_banco, raiz_projeto
from . import db
from .modelos import Base


def _config_alembic() -> Config:
    config = Config(str(raiz_projeto() / "alembic.ini"))
    config.set_main_option(
        "script_location", str(raiz_projeto() / "src/honorarios/infra/migracoes")
    )
    return config


def preparar(caminho: Path | str | None = None) -> None:
    destino = Path(caminho) if caminho else caminho_banco()
    novo = not destino.exists() or destino.stat().st_size == 0
    engine = db.configurar(destino, criar=False)
    config = _config_alembic()
    if novo:
        Base.metadata.create_all(engine)
        command.stamp(config, "head")
        return
    if "alembic_version" not in inspect(engine).get_table_names():
        # banco criado antes do Alembic entrar: alinha sem recriar nada
        Base.metadata.create_all(engine)
        command.stamp(config, "head")
        return
    command.upgrade(config, "head")
