"""Acrescenta pendências fictícias aos dados de exemplo (para demonstrar a cobrança
e o e-mail do financeiro). Roda depois de ``dados_exemplo.py``; não apaga nada.

    .venv/bin/python scripts/mais_pendencias.py
"""

from __future__ import annotations

import sys
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import select  # noqa: E402

from honorarios.dominio.enums import Periodicidade, ResultadoCobranca  # noqa: E402
from honorarios.dominio.feriados import proximo_dia_util  # noqa: E402
from honorarios.dominio.valores import Competencia  # noqa: E402
from honorarios.infra import db, esquema  # noqa: E402
from honorarios.infra.modelos import Contrato, TipoHonorario  # noqa: E402
from honorarios.servicos import clientes, cobrancas  # noqa: E402
from honorarios.servicos import honorarios as servico  # noqa: E402

# (código do cliente, tipo, valor, vencimento, competência (mês) ou descrição)
AVULSOS = (
    ("303", "Alteração contratual", "950.00", date(2026, 9, 15), "Inclusão de atividade"),
    ("304", "Certificado digital", "280.00", date(2026, 8, 24), "e-CNPJ A1"),
    ("305", "Ata de Sócios", "350.00", date(2026, 8, 28), "Ata de aprovação de contas"),
    ("306", "Alteração contratual", "1200.00", date(2026, 9, 2), "Mudança de endereço"),
    ("401", "Ganho de Capital", "680.00", date(2026, 8, 20), "Venda de imóvel"),
    ("502", "Certificado digital", "180.00", date(2026, 9, 25), "e-CPF A1"),
)
# a escola tem contrato e nunca pagou: três meses em aberto
ESCOLA, MESES_ESCOLA = "308", (6, 7, 8)
# cobranças já feitas, com a resposta de cada cliente
RETORNOS = (
    ("308", date(2026, 9, 25), ResultadoCobranca.SEM_RESPOSTA, None, ""),
    ("308", date(2026, 10, 1), ResultadoCobranca.PROMETEU_PAGAR, date(2026, 10, 8),
     "A diretora vai pagar junho e julho no dia 08; agosto no fim do mês"),
    ("306", date(2026, 9, 28), ResultadoCobranca.CONTESTOU, None,
     "Diz que a mudança de endereço foi cancelada; pediu o protocolo"),
    ("401", date(2026, 9, 29), ResultadoCobranca.PEDIU_RENEGOCIACAO, None,
     "Quer dividir o ganho de capital em 3x"),
)


def main() -> int:
    esquema.preparar()
    with db.transacao() as sessao:
        tipos = {t.nome: t for t in sessao.scalars(select(TipoHonorario))}
        for codigo, tipo, valor, vencimento, descricao in AVULSOS:
            cliente = clientes.por_codigo(sessao, codigo)
            servico.criar(sessao, servico.DadosHonorario(
                cliente_id=cliente.id, tipo_id=tipos[tipo].id, valor=Decimal(valor),
                vencimento=vencimento, descricao=descricao,
            ))
        escola = clientes.por_codigo(sessao, ESCOLA)
        contrato = sessao.scalar(select(Contrato).where(Contrato.cliente_id == escola.id))
        for mes in MESES_ESCOLA:
            servico.criar(sessao, servico.DadosHonorario(
                cliente_id=escola.id, tipo_id=contrato.tipo_id, valor=contrato.valor,
                vencimento=proximo_dia_util(date(2026, mes + 1, contrato.dia_vencimento)),
                competencia=Competencia(2026, mes), contrato_id=contrato.id,
            ))
        sessao.flush()
        for codigo, quando, resultado, promessa, observacao in RETORNOS:
            cliente = clientes.por_codigo(sessao, codigo)
            linhas = [linha for linha in cobrancas.linhas_em_aberto_do_cliente(
                sessao, cliente.id, quando)
                if linha.honorario.tipo.periodicidade is not Periodicidade.AVULSO
                or codigo != ESCOLA]
            cobrancas.registrar(
                sessao, cobrancas.Selecao(cliente=cliente, linhas=linhas, data_referencia=quando),
                texto="(cobrança de exemplo)", resultado=resultado, promessa_data=promessa,
                observacao=observacao, quando=datetime.combine(quando, time(10)),
            )
    print(f"{len(AVULSOS)} avulsos, {len(MESES_ESCOLA)} mensais da escola e "
          f"{len(RETORNOS)} cobranças com retorno acrescentados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
