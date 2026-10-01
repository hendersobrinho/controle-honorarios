"""grupo de imposto de renda

Revisão: 6e1bd3d6710f
Revisão anterior: 346aaaeafe41
Criada em: 2026-09-30 13:42:50.560603
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '6e1bd3d6710f'
down_revision = '346aaaeafe41'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("grupo_honorario", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "imposto_de_renda",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
    # o grupo criado pela carga inicial já é o de Imposto de Renda
    op.execute(
        "UPDATE grupo_honorario SET imposto_de_renda = 1 WHERE nome = 'Imposto de Renda'"
    )


def downgrade() -> None:
    with op.batch_alter_table("grupo_honorario", schema=None) as batch_op:
        batch_op.drop_column("imposto_de_renda")
