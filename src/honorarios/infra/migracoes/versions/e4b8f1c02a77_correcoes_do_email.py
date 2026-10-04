"""correções da conferência do e-mail feitas à mão

Revisão: e4b8f1c02a77
Revisão anterior: d7a3c9e15b42
Criada em: 2026-10-04 12:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'e4b8f1c02a77'
down_revision = 'd7a3c9e15b42'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("email_mensagem") as tabela:
        tabela.add_column(sa.Column("correcoes", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("email_mensagem") as tabela:
        tabela.drop_column("correcoes")
