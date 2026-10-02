"""PDF do Painel, no mesmo visual do PDF da análise de juros.

Traz os indicadores do ano, as leituras, os três gráficos da tela (desenhados
pela interface e passados como imagem) e a tabela por mês, que é o mesmo dado
do primeiro gráfico para quem quiser conferir número a número.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ..dominio.valores import ZERO, formatar_data, formatar_moeda, hoje
from .pdf_relatorio import RelatorioPdf, texto
from .relatorios import Indicadores

GRAFICOS = (
    ("quitacao", "Emitido por mês: quanto já foi quitado",
     "Pela competência: a parte azul já foi quitada, a laranja segue em aberto."),
    ("caixa", "Entrou no caixa por mês",
     "Pela data da baixa, com juros, de qualquer competência."),
    ("origem", "De onde vem o faturamento",
     "Emitido no ano, por grupo e por tipo de cliente."),
)


def _pct(valor) -> str:
    return f"{valor:.0f}%"


def painel_pdf(
    dados: Indicadores,
    recebedor,
    destino: Path,
    graficos: dict[str, Path] | None = None,
    fundo: Path | None = None,
    gerado_em: date | None = None,
) -> Path:
    """Gera o PDF do painel do ano e devolve o caminho."""
    from reportlab.platypus import KeepTogether, Paragraph, Spacer

    graficos = graficos or {}
    r = RelatorioPdf(
        f"Painel {dados.ano}",
        f"Honorários com competência em {dados.ano}",
        recebedor,
        gerado_em or hoje(),
        fundo,
    )
    corpo = [
        *r.inicio(),
        r.p(
            f"Competência de {dados.ano} · valores atualizados para "
            f"{formatar_data(dados.referencia)} · atraso e devedores ficam no Ranking dos "
            "atrasados",
            "fraco",
        ),
        Spacer(1, 10),
        r.grade([
            ("Emitido no ano", formatar_moeda(dados.emitido),
             f"{dados.quantidade_emitida} honorário(s), pela competência"),
            ("Quitado", formatar_moeda(dados.quitado),
             f"{_pct(dados.percentual_quitado)} do emitido (valor original)"),
            ("Em aberto", formatar_moeda(dados.em_aberto),
             f"{dados.quantidade_em_aberto} honorário(s) · valor original, sem juros"),
            ("Entrou no caixa", formatar_moeda(dados.recebido_no_caixa),
             "baixas do ano, de qualquer competência, com juros"),
            ("Clientes faturados", str(dados.clientes_faturados), "com honorário no ano"),
            ("Valor médio por honorário", formatar_moeda(dados.ticket_medio), ""),
        ]),
        r.p("O que os números dizem", "secao"),
    ]
    for frase in dados.leituras():
        corpo.append(Paragraph(f"•&nbsp;&nbsp;{texto(frase)}", r.estilo["normal"]))

    for chave, titulo, nota in GRAFICOS:
        if chave not in graficos:
            continue
        corpo.append(KeepTogether([
            r.p(titulo, "secao"),
            r.p(nota, "fraco"),
            Spacer(1, 4),
            r.imagem(graficos[chave]),
        ]))

    # a tabela é o mesmo dado do primeiro gráfico, número a número
    linhas = [["Mês", "Emitido", "Quitado", "Em aberto", "% quitado", "Entrou no caixa"]]
    for mes in dados.meses:
        linhas.append([
            mes.rotulo,
            formatar_moeda(mes.emitido) if mes.emitido else "—",
            formatar_moeda(mes.quitado) if mes.quitado else "—",
            formatar_moeda(mes.em_aberto) if mes.em_aberto else "—",
            _pct(mes.percentual_quitado) if mes.emitido else "—",
            formatar_moeda(mes.recebido) if mes.recebido else "—",
        ])
    linhas.append([
        "Total", formatar_moeda(dados.emitido), formatar_moeda(dados.quitado),
        formatar_moeda(dados.em_aberto),
        _pct(dados.percentual_quitado) if dados.emitido > ZERO else "—",
        formatar_moeda(dados.recebido_no_caixa),
    ])
    corpo.append(KeepTogether([
        r.p("Mês a mês", "secao"),
        r.tabela(linhas, r.larguras((0.16, 0.18, 0.17, 0.17, 0.12, 0.2)), total=True),
    ]))
    return r.salvar(corpo, destino, f"Painel {dados.ano}")
