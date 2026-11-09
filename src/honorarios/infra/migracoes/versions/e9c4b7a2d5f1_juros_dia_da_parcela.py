"""juros ao dia estipulado à mão na parcela de parcelamento

Revisão: e9c4b7a2d5f1
Revisão anterior: d4a8e1c7f2b9
Criada em: 2026-11-09 16:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'e9c4b7a2d5f1'
down_revision = 'd4a8e1c7f2b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("honorario") as tabela:
        tabela.add_column(sa.Column("juros_dia", sa.Numeric(12, 6), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("honorario") as tabela:
        tabela.drop_column("juros_dia")
