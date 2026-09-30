"""Ambiente do Alembic: usa o mesmo caminho de banco do aplicativo."""

from __future__ import annotations

from alembic import context
from sqlalchemy import event

from honorarios.config.caminhos import caminho_banco
from honorarios.infra.db import criar_engine
from honorarios.infra.modelos import Base

config = context.config
target_metadata = Base.metadata


def render_item(tipo, obj, autogen_context):  # noqa: ANN001
    """Grava Dinheiro/Taxa como NUMERIC na migration, sem importar o pacote."""
    if tipo == "type" and obj.__class__.__name__ in {"Dinheiro", "Taxa"}:
        return f"sa.Numeric(precision={obj.impl.precision}, scale={obj.impl.scale})"
    if tipo == "type" and obj.__class__.__name__ == "EnumTexto":
        return f"sa.String(length={obj.length})"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=f"sqlite:///{caminho_banco()}",
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = criar_engine()

    # O SQLite altera coluna recriando a tabela (batch). Com as chaves
    # estrangeiras ligadas, o DROP TABLE intermediário é recusado — então elas
    # ficam desligadas durante a migration. O listener é registrado depois do
    # que o aplicativo instala, e por isso é o último a valer.
    @event.listens_for(engine, "connect")
    def _sem_chaves_estrangeiras(conexao, _registro):  # noqa: ANN001
        cursor = conexao.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    with engine.connect() as conexao:
        context.configure(
            connection=conexao,
            target_metadata=target_metadata,
            render_as_batch=True,
            render_item=render_item,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
