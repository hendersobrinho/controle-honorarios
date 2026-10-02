"""e-mails da conversa "Clientes c/Honorários vencidos"

Revisão: d7a3c9e15b42
Revisão anterior: b51d0e7f3c28
Criada em: 2026-10-02 20:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'd7a3c9e15b42'
down_revision = 'b51d0e7f3c28'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_mensagem",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conta", sa.String(length=20), nullable=False),
        sa.Column("message_id", sa.String(length=400), nullable=False),
        sa.Column("ref_provedor", sa.String(length=400), nullable=False),
        sa.Column("conversa", sa.String(length=400), nullable=False),
        sa.Column("assunto", sa.String(length=400), nullable=False),
        sa.Column("de", sa.String(length=400), nullable=False),
        sa.Column("para", sa.Text(), nullable=False),
        sa.Column("cc", sa.Text(), nullable=False),
        sa.Column("recebido_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("corpo_html", sa.Text(), nullable=False),
        sa.Column("corpo_texto", sa.Text(), nullable=False),
        sa.Column("in_reply_to", sa.String(length=400), nullable=False),
        sa.Column("referencias", sa.Text(), nullable=False),
        sa.Column("enviada", sa.Boolean(), nullable=False),
        sa.Column("lida_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("respondida_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("criada_em", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conta", "message_id",
                            name="uq_email_mensagem_conta_message_id"),
    )
    op.create_index("ix_email_mensagem_recebido_em", "email_mensagem", ["recebido_em"])


def downgrade() -> None:
    op.drop_index("ix_email_mensagem_recebido_em", table_name="email_mensagem")
    op.drop_table("email_mensagem")
