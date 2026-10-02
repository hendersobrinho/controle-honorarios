"""notificações (vence hoje, não foi pago na data…)

Revisão: b51d0e7f3c28
Revisão anterior: 8c4f2a1b7d93
Criada em: 2026-10-02 15:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b51d0e7f3c28'
down_revision = '8c4f2a1b7d93'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notificacao",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chave", sa.String(length=120), nullable=False),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("titulo", sa.String(length=200), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("tela", sa.String(length=60), nullable=False),
        sa.Column("cliente_id", sa.Integer(), nullable=True),
        sa.Column("criada_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lida_em", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["cliente_id"], ["cliente.id"],
                                name="fk_notificacao_cliente"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chave", name="uq_notificacao_chave"),
    )
    op.create_index("ix_notificacao_cliente_id", "notificacao", ["cliente_id"])


def downgrade() -> None:
    op.drop_index("ix_notificacao_cliente_id", table_name="notificacao")
    op.drop_table("notificacao")
