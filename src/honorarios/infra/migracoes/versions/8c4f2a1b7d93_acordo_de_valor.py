"""acordo de valor (valor congelado válido até uma data)

Revisão: 8c4f2a1b7d93
Revisão anterior: 6e1bd3d6710f
Criada em: 2026-10-02 10:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '8c4f2a1b7d93'
down_revision = '6e1bd3d6710f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acordo_valor",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("honorario_id", sa.Integer(), nullable=False),
        sa.Column("data_base", sa.Date(), nullable=False),
        sa.Column("valido_ate", sa.Date(), nullable=False),
        sa.Column("saldo", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("juros", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["honorario_id"], ["honorario.id"],
                                name="fk_acordo_valor_honorario"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_acordo_valor_honorario_id", "acordo_valor", ["honorario_id"])


def downgrade() -> None:
    op.drop_index("ix_acordo_valor_honorario_id", table_name="acordo_valor")
    op.drop_table("acordo_valor")
