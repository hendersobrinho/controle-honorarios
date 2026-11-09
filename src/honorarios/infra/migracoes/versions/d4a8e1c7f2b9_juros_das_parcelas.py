"""juros das parcelas: desde o parcelamento, na proporção da parcela

Revisão: d4a8e1c7f2b9
Revisão anterior: c9d2e7a4b1f6
Criada em: 2026-11-09 12:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'd4a8e1c7f2b9'
down_revision = 'c9d2e7a4b1f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("honorario") as tabela:
        tabela.add_column(sa.Column("juros_desde", sa.Date(), nullable=True))
        tabela.add_column(sa.Column("juros_fator", sa.Numeric(12, 6), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("honorario") as tabela:
        tabela.drop_column("juros_fator")
        tabela.drop_column("juros_desde")
