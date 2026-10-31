"""juros ajustado à mão no honorário

Revisão: c9d2e7a4b1f6
Revisão anterior: f2c6a9d41b83
Criada em: 2026-10-31 12:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c9d2e7a4b1f6'
down_revision = 'f2c6a9d41b83'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("honorario") as tabela:
        tabela.add_column(sa.Column("juros_ajustado", sa.Numeric(14, 2), nullable=True))
        tabela.add_column(sa.Column("juros_ajustado_em", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("honorario") as tabela:
        tabela.drop_column("juros_ajustado_em")
        tabela.drop_column("juros_ajustado")
