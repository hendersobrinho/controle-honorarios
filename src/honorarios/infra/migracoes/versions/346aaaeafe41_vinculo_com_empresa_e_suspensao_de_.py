"""vinculo com empresa e suspensao de cobranca

Revisão: 346aaaeafe41
Revisão anterior: 1a21c075cab5
Criada em: 2026-09-30 09:04:16.218069
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '346aaaeafe41'
down_revision = '1a21c075cab5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # As colunas obrigatórias levam server_default: o banco existente já tem
    # clientes, e sem valor padrão as linhas antigas violariam o NOT NULL.
    with op.batch_alter_table("cliente", schema=None) as batch_op:
        batch_op.add_column(sa.Column("empresa_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "cobranca_suspensa",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch_op.add_column(sa.Column("suspensa_em", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("suspensa_ate", sa.Date(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "motivo_suspensao", sa.Text(), nullable=False, server_default=sa.text("''")
            )
        )
        batch_op.create_index(batch_op.f("ix_cliente_empresa_id"), ["empresa_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_cliente_empresa", "cliente", ["empresa_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("cliente", schema=None) as batch_op:
        batch_op.drop_constraint("fk_cliente_empresa", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_cliente_empresa_id"))
        batch_op.drop_column("motivo_suspensao")
        batch_op.drop_column("suspensa_ate")
        batch_op.drop_column("suspensa_em")
        batch_op.drop_column("cobranca_suspensa")
        batch_op.drop_column("empresa_id")
