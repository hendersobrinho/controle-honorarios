"""cliente desde, tarefas e juros único por cliente

Revisão: f2c6a9d41b83
Revisão anterior: e4b8f1c02a77
Criada em: 2026-10-30 12:00:00
"""
from __future__ import annotations

from datetime import date

from alembic import op
import sqlalchemy as sa


revision = 'f2c6a9d41b83'
down_revision = 'e4b8f1c02a77'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("cliente") as tabela:
        tabela.add_column(sa.Column("cliente_desde", sa.Date(), nullable=True))

    op.create_table(
        "tarefa",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chave", sa.String(120), nullable=False, unique=True),
        sa.Column("cliente_id", sa.Integer(), sa.ForeignKey("cliente.id"), nullable=False),
        sa.Column("contrato_id", sa.Integer(), sa.ForeignKey("contrato.id"), nullable=True),
        sa.Column("descricao", sa.String(200), nullable=False, server_default=""),
        sa.Column("periodo_inicio", sa.Date(), nullable=True),
        sa.Column("periodo_fim", sa.Date(), nullable=True),
        sa.Column("concluida_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observacao", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index("ix_tarefa_cliente_id", "tarefa", ["cliente_id"])

    # juros único: quem tinha histórico de vigências fica com o valor que vale hoje,
    # e ele passa a valer para tudo o que está em aberto
    juros = sa.table(
        "cliente_juros",
        sa.column("id", sa.Integer()), sa.column("cliente_id", sa.Integer()),
        sa.column("vigencia_inicio", sa.Date()),
    )
    conexao = op.get_bind()
    hoje = date.today()
    por_cliente: dict[int, list[tuple[int, date]]] = {}
    for identificador, cliente_id, vigencia in conexao.execute(
            sa.select(juros.c.id, juros.c.cliente_id, juros.c.vigencia_inicio)):
        por_cliente.setdefault(cliente_id, []).append((identificador, vigencia))
    for linhas in por_cliente.values():
        if len(linhas) < 2:
            continue
        linhas.sort(key=lambda linha: linha[1])
        vigentes = [linha for linha in linhas if linha[1] <= hoje]
        fica = (vigentes or linhas)[-1 if vigentes else 0][0]
        apagar = [identificador for identificador, _ in linhas if identificador != fica]
        conexao.execute(sa.delete(juros).where(juros.c.id.in_(apagar)))


def downgrade() -> None:
    op.drop_index("ix_tarefa_cliente_id", table_name="tarefa")
    op.drop_table("tarefa")
    with op.batch_alter_table("cliente") as tabela:
        tabela.drop_column("cliente_desde")
