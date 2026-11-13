"""código do cliente opcional na pessoa física: único só quando preenchido

Revisão: f3b8d6a1c4e7
Revisão anterior: e9c4b7a2d5f1
Criada em: 2026-11-13 10:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'f3b8d6a1c4e7'
down_revision = 'e9c4b7a2d5f1'
branch_labels = None
depends_on = None

PREENCHIDO = "codigo <> ''"


def upgrade() -> None:
    with op.batch_alter_table("cliente") as tabela:
        tabela.drop_constraint("uq_cliente_codigo", type_="unique")
        tabela.create_index("ix_cliente_codigo", ["codigo"], unique=True,
                            sqlite_where=sa.text(PREENCHIDO),
                            postgresql_where=sa.text(PREENCHIDO))


def downgrade() -> None:
    with op.batch_alter_table("cliente") as tabela:
        tabela.drop_index("ix_cliente_codigo", sqlite_where=sa.text(PREENCHIDO),
                          postgresql_where=sa.text(PREENCHIDO))
        tabela.create_unique_constraint("uq_cliente_codigo", ["codigo"])
