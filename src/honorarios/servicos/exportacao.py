"""Exportações: planilha Excel da lista filtrada e PDF do extrato de débitos."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from ..config.caminhos import pasta_exportacoes
from ..dominio.valores import ZERO, formatar_data, formatar_moeda, hoje
from .honorarios import LinhaHonorario

FORMATO_MOEDA = 'R$ #,##0.00'
CABECALHO = (
    "Cliente",
    "Código",
    "CPF/CNPJ",
    "Tipo",
    "Grupo",
    "Competência",
    "Vencimento",
    "Dias em atraso",
    "Valor original",
    "Juros",
    "Total atualizado",
    "Status",
    "Cobranças",
    "Última cobrança",
    "Promessa",
)


def _nome_arquivo(prefixo: str, extensao: str) -> Path:
    marca = hoje().strftime("%Y%m%d")
    destino = pasta_exportacoes() / f"{prefixo}-{marca}.{extensao}"
    contador = 2
    while destino.exists():
        destino = pasta_exportacoes() / f"{prefixo}-{marca}-{contador}.{extensao}"
        contador += 1
    return destino


def para_excel(
    linhas: Sequence[LinhaHonorario],
    destino: Path | None = None,
    titulo: str = "Honorários",
) -> Path:
    """Planilha da lista já filtrada, com os valores atualizados e um total."""
    arquivo = Path(destino) if destino else _nome_arquivo("honorarios", "xlsx")
    livro = Workbook()
    aba = livro.active
    aba.title = titulo[:31]

    aba["A1"] = titulo
    aba["A1"].font = Font(bold=True, size=14)
    aba["A2"] = f"Gerado em {formatar_data(hoje())} · {len(linhas)} lançamento(s)"
    aba["A2"].font = Font(italic=True, color="666666")

    for coluna, nome in enumerate(CABECALHO, start=1):
        celula = aba.cell(row=4, column=coluna, value=nome)
        celula.font = Font(bold=True)
        celula.fill = PatternFill("solid", fgColor="EEF1F5")
        celula.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for indice, linha in enumerate(linhas, start=5):
        honorario = linha.honorario
        valores = (
            linha.cliente.nome,
            linha.cliente.codigo,
            linha.cliente.documento,
            honorario.tipo.nome,
            linha.grupo.nome,
            honorario.competencia_rotulo,
            honorario.vencimento,
            linha.atualizacao.dias_atraso,
            float(linha.atualizacao.valor_original),
            float(linha.atualizacao.juros),
            float(linha.atualizacao.total),
            honorario.status.rotulo,
            linha.cobrancas,
            linha.ultima_cobranca,
            linha.promessa,
        )
        for coluna, valor in enumerate(valores, start=1):
            celula = aba.cell(row=indice, column=coluna, value=valor)
            if coluna in (9, 10, 11):
                celula.number_format = FORMATO_MOEDA
            if coluna in (7, 14, 15):
                celula.number_format = "DD/MM/YYYY"

    ultima = 4 + len(linhas) + 1
    aba.cell(row=ultima, column=8, value="Total").font = Font(bold=True)
    for coluna in (9, 10, 11):
        letra = get_column_letter(coluna)
        celula = aba.cell(row=ultima, column=coluna)
        celula.value = f"=SUM({letra}5:{letra}{4 + len(linhas)})" if linhas else 0
        celula.number_format = FORMATO_MOEDA
        celula.font = Font(bold=True)

    larguras = (34, 8, 20, 22, 20, 13, 12, 8, 14, 12, 16, 14, 10, 14, 12)
    for coluna, largura in enumerate(larguras, start=1):
        aba.column_dimensions[get_column_letter(coluna)].width = largura
    aba.freeze_panes = "A5"

    livro.save(arquivo)
    return arquivo


def extrato_pdf(
    cliente,
    linhas: Sequence[LinhaHonorario],
    recebedor,
    destino: Path | None = None,
    data_referencia: date | None = None,
) -> Path:
    """Extrato de débitos da empresa, para enviar ao cliente."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    referencia = data_referencia or hoje()
    arquivo = Path(destino) if destino else _nome_arquivo(
        f"extrato-{cliente.codigo}", "pdf"
    )
    estilos = getSampleStyleSheet()
    estilo_titulo = ParagraphStyle(
        "TituloExtrato", parent=estilos["Title"], fontSize=15, spaceAfter=4
    )
    estilo_normal = estilos["Normal"]

    documento = SimpleDocTemplate(
        str(arquivo),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Extrato de débitos – {cliente.nome}",
    )

    total = sum((linha.atualizacao.total for linha in linhas), start=ZERO)
    corpo = [
        Paragraph("Extrato de débitos em aberto", estilo_titulo),
        Paragraph(recebedor.razao_social, estilo_normal),
        Spacer(1, 8),
        Paragraph(f"<b>Cliente:</b> {cliente.nome} (código {cliente.codigo})", estilo_normal),
        Paragraph(f"<b>Valores atualizados para:</b> {formatar_data(referencia)}", estilo_normal),
        Spacer(1, 10),
    ]

    dados = [["Honorário", "Competência", "Vencimento", "Atraso", "Valor", "Juros", "Total"]]
    for linha in linhas:
        dados.append(
            [
                linha.honorario.tipo.nome,
                linha.honorario.competencia_rotulo,
                formatar_data(linha.honorario.vencimento),
                f"{linha.atualizacao.dias_atraso} d",
                formatar_moeda(linha.atualizacao.valor_original),
                formatar_moeda(linha.atualizacao.juros),
                formatar_moeda(linha.atualizacao.total),
            ]
        )
    dados.append(["", "", "", "", "", "Total", formatar_moeda(total)])

    tabela = Table(dados, hAlign="LEFT", colWidths=[46 * mm, 22 * mm, 22 * mm, 14 * mm,
                                                   24 * mm, 20 * mm, 26 * mm])
    tabela.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (-2, -1), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -2), 0.4, colors.HexColor("#c9d1da")),
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor("#6b7684")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    corpo.append(tabela)
    corpo.append(Spacer(1, 12))
    corpo.append(
        Paragraph(
            f"Pagamento por PIX – {recebedor.razao_social}<br/>"
            f"{recebedor.rotulo_chave}: {recebedor.chave}",
            estilo_normal,
        )
    )
    corpo.append(Spacer(1, 6))
    corpo.append(
        Paragraph(
            "Juros de mora calculados por dia de atraso, conforme contrato. "
            "Após o pagamento, por gentileza, encaminhe o comprovante.",
            ParagraphStyle("Rodape", parent=estilo_normal, fontSize=8, textColor=colors.gray),
        )
    )
    documento.build(corpo)
    return arquivo
