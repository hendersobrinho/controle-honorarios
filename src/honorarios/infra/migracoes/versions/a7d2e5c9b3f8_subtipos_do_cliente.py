"""subtipos do cliente cadastrados pelo usuário (tabela subtipo_cliente)

O cliente passa a guardar o nome do subtipo: "Doméstica" no lugar de DOMESTICA e
vazio no lugar de NENHUM.

Revisão: a7d2e5c9b3f8
Revisão anterior: f3b8d6a1c4e7
Criada em: 2026-11-13 14:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a7d2e5c9b3f8'
down_revision = 'f3b8d6a1c4e7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    subtipo = op.create_table(
        "subtipo_cliente",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=40), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nome"),
    )
    op.bulk_insert(subtipo, [{"nome": "Doméstica", "ativo": True}])
    with op.batch_alter_table("cliente") as tabela:
        tabela.alter_column("subtipo", existing_type=sa.String(length=20),
                            type_=sa.String(length=40), existing_nullable=False)
    op.execute("update cliente set subtipo = 'Doméstica' where subtipo = 'DOMESTICA'")
    op.execute("update cliente set subtipo = '' where subtipo = 'NENHUM'")


def downgrade() -> None:
    op.execute("update cliente set subtipo = 'DOMESTICA' where subtipo = 'Doméstica'")
    op.execute("update cliente set subtipo = 'NENHUM' where subtipo <> 'DOMESTICA'")
    with op.batch_alter_table("cliente") as tabela:
        tabela.alter_column("subtipo", existing_type=sa.String(length=40),
                            type_=sa.String(length=20), existing_nullable=False)
    op.drop_table("subtipo_cliente")
