"""Molde dos PDFs (análise de juros, painel, extrato): o mesmo visual em todos.

A página é um canhoto, como a abertura do programa: no topo, a faixa navy com o
título e a marca do Financeiro; o picote com os furos nas laterais; e no pé o
canhoto ciano com o rodapé. Tudo em vetor (a marca também), arquivo leve.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from ..dominio.valores import formatar_data
from . import svg_pdf

AZUL = "#203461"
AZUL_ESCURO = "#16254A"
PICOTE = "#8C9BC0"
TEAL = "#4BBDCD"
LARANJA = "#F9B259"
FRACO = "#5B6577"
BORDA = "#D5DAE1"
FAIXA = "#EEF1F5"
VERDE = "#1F7A45"
VERMELHO = "#B03A2E"

MARCA = Path(__file__).resolve().parent.parent / "recursos" / "marca_negativo.svg"

# o canhoto da página, em pontos (A4 tem 595 × 842)
FAIXA_TOPO = 92          # altura da faixa navy do topo
CANHOTO = 30             # altura do canhoto ciano do pé
FURO = 9                 # raio dos furos do picote
LADO = 40                # margem lateral do texto


def texto(valor) -> str:
    """Helvetica (a fonte padrão do PDF) não tem seta nem sinal de menos tipográfico."""
    return escape(str(valor)).replace("→", "->").replace("−", "-")


class RelatorioPdf:
    """Estilos, peças e a página do relatório. Uso: monte ``corpo`` e chame ``salvar``."""

    def __init__(
        self,
        titulo: str,
        subtitulo: str,
        recebedor,
        gerado_em: date,
        rodape: str = "Documento interno",
    ) -> None:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm

        self.titulo = titulo
        self.subtitulo = subtitulo
        self.recebedor = recebedor
        self.gerado_em = gerado_em
        self.rodape = rodape
        self.cor = colors.HexColor
        self.pagina_a4 = A4
        self.margem_lado = LADO
        self.margem_topo = FAIXA_TOPO + 8 * mm
        self.margem_base = CANHOTO + 8 * mm
        self.largura_util = A4[0] - 2 * self.margem_lado

        cor = self.cor
        base = getSampleStyleSheet()["Normal"]
        self.estilo = {
            "titulo": ParagraphStyle("t", parent=base, fontName="Helvetica-Bold", fontSize=18,
                                     leading=22, textColor=cor(AZUL)),
            "subtitulo": ParagraphStyle("c", parent=base, fontName="Helvetica-Bold",
                                        fontSize=12.5, leading=16, textColor=cor(AZUL)),
            "fraco": ParagraphStyle("f", parent=base, fontSize=8.5, leading=11,
                                    textColor=cor(FRACO)),
            "secao": ParagraphStyle("s", parent=base, fontName="Helvetica-Bold", fontSize=11.5,
                                    leading=14, textColor=cor(AZUL), spaceBefore=12,
                                    spaceAfter=6),
            "normal": ParagraphStyle("n", parent=base, fontSize=9, leading=12.5),
            "rotulo": ParagraphStyle("r", parent=base, fontSize=7.5, leading=9,
                                     textColor=cor(FRACO)),
            "valor": ParagraphStyle("v", parent=base, fontName="Helvetica-Bold", fontSize=13,
                                    leading=16, textColor=cor(AZUL)),
            "nota": ParagraphStyle("o", parent=base, fontSize=7.2, leading=9,
                                   textColor=cor(FRACO)),
            "celula": ParagraphStyle("e", parent=base, fontSize=8, leading=10),
            "cabecalho": ParagraphStyle("h", parent=base, fontName="Helvetica-Bold",
                                        fontSize=7.3, leading=8.6, textColor=cor(FRACO),
                                        alignment=2),
            "cabecalho_esq": ParagraphStyle("he", parent=base, fontName="Helvetica-Bold",
                                            fontSize=7.3, leading=8.6, textColor=cor(FRACO)),
        }

    # -------------------------------------------------------------- peças
    def p(self, conteudo: str, nome: str = "normal"):
        from reportlab.platypus import Paragraph

        return Paragraph(conteudo, self.estilo[nome])

    def larguras(self, fracoes: Sequence[float]) -> list[float]:
        return [self.largura_util * fracao for fracao in fracoes]

    def tabela(self, linhas, larguras, total: bool = False, destaque: int | None = None):
        """Tabela no padrão do relatório: cabeçalho cinza, números à direita.

        O cabeçalho vira parágrafo para quebrar linha: título longo não invade a
        coluna vizinha.
        """
        from reportlab.platypus import Paragraph, Table, TableStyle

        cor = self.cor
        linhas = [[
            Paragraph(titulo, self.estilo["cabecalho_esq" if coluna == 0 else "cabecalho"])
            for coluna, titulo in enumerate(linhas[0])
        ]] + list(linhas[1:])
        t = Table(linhas, colWidths=larguras, hAlign="LEFT", repeatRows=1)
        regras = [
            ("BACKGROUND", (0, 0), (-1, 0), cor(FAIXA)),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, 0), (-1, 0), cor(FRACO)),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, cor(BORDA)),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ]
        if total:
            regras += [
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, cor(FRACO)),
            ]
        if destaque is not None:
            regras += [
                ("BACKGROUND", (0, destaque), (-1, destaque), cor("#E6F6F8")),
                ("FONTNAME", (0, destaque), (-1, destaque), "Helvetica-Bold"),
            ]
        t.setStyle(TableStyle(regras))
        return t

    def grade(self, indicadores: Sequence[tuple[str, str, str]], colunas: int = 3):
        """Indicadores em grade: rótulo pequeno, valor grande e uma nota embaixo."""
        from reportlab.platypus import Table, TableStyle

        celulas = [
            [self.p(texto(rotulo), "rotulo"), self.p(texto(valor), "valor"),
             self.p(texto(nota), "nota")]
            for rotulo, valor, nota in indicadores
        ]
        while len(celulas) % colunas:
            celulas.append("")
        linhas = [celulas[i:i + colunas] for i in range(0, len(celulas), colunas)]
        grade = Table(linhas, colWidths=[self.largura_util / colunas] * colunas)
        grade.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.6, self.cor(BORDA)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ]))
        return grade

    def imagem(self, caminho: Path, largura: float | None = None):
        """Imagem na largura útil (ou na pedida), sem deformar."""
        from reportlab.lib.utils import ImageReader
        from reportlab.platypus import Image

        largura = largura or self.largura_util
        largura_px, altura_px = ImageReader(str(caminho)).getSize()
        return Image(str(caminho), width=largura, height=largura * altura_px / largura_px)

    def inicio(self) -> list:
        """O começo do corpo (o título vai na faixa do topo, no papel)."""
        return []

    # ------------------------------------------------------------ página
    def _furos(self, canvas, y: float) -> None:
        """Os furos do picote: meios círculos brancos nas duas laterais."""
        largura = self.pagina_a4[0]
        canvas.setFillColor(self.cor("#FFFFFF"))
        for x in (0, largura):
            canvas.circle(x, y, FURO, stroke=0, fill=1)

    def _tracejado(self, canvas, y: float) -> None:
        largura = self.pagina_a4[0]
        canvas.setFillColor(self.cor(PICOTE))
        canvas.setFillAlpha(0.6)
        x = 26.0
        while x + 7 <= largura - 26:
            canvas.roundRect(x, y - 1, 7, 2, 1, stroke=0, fill=1)
            x += 14
        canvas.setFillAlpha(1)

    def _pagina(self, canvas, documento) -> None:
        largura, altura = self.pagina_a4
        canvas.saveState()
        # faixa navy do topo, em degradê como a abertura
        base_faixa = altura - FAIXA_TOPO
        canvas.saveState()
        recorte = canvas.beginPath()
        recorte.rect(0, base_faixa, largura, FAIXA_TOPO)
        canvas.clipPath(recorte, stroke=0, fill=0)
        canvas.linearGradient(0, altura, largura, base_faixa,
                              (self.cor(AZUL), self.cor(AZUL_ESCURO)))
        canvas.restoreState()
        self._furos(canvas, base_faixa)
        self._tracejado(canvas, base_faixa - 8)
        # a marca à direita; o título e o subtítulo à esquerda
        altura_marca = 38
        largura_marca = altura_marca * svg_pdf.proporcao(MARCA)
        svg_pdf.desenhar(canvas, MARCA, largura - LADO - largura_marca,
                         base_faixa + (FAIXA_TOPO - altura_marca) / 2, altura_marca)
        espaco = largura - 2 * LADO - largura_marca - 24
        canvas.setFillColor(self.cor("#FFFFFF"))
        canvas.setFont("Helvetica-Bold", 20)
        canvas.drawString(LADO, altura - 44, _caber(canvas, self.titulo, "Helvetica-Bold",
                                                    20, espaco))
        canvas.setFillColor(self.cor(TEAL))
        canvas.setFont("Helvetica-Bold", 10.5)
        canvas.drawString(LADO, altura - 64, _caber(canvas, self.subtitulo, "Helvetica-Bold",
                                                    10.5, espaco))
        # o canhoto ciano no pé, com o rodapé em navy
        canvas.setFillColor(self.cor(TEAL))
        canvas.rect(0, 0, largura, CANHOTO, stroke=0, fill=1)
        self._furos(canvas, CANHOTO)
        self._tracejado(canvas, CANHOTO + 8)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(self.cor(AZUL))
        canvas.drawString(
            LADO, CANHOTO / 2 - 2.5,
            _caber(canvas, f"{self.rodape} · {self.recebedor.razao_social} · gerado em "
                           f"{formatar_data(self.gerado_em)}", "Helvetica", 7.5,
                   largura - 2 * LADO - 60),
        )
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.drawRightString(largura - LADO, CANHOTO / 2 - 2.5, f"Página {documento.page}")
        canvas.restoreState()

    def salvar(self, corpo: list, destino: Path, titulo_documento: str) -> Path:
        from reportlab.platypus import SimpleDocTemplate

        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        documento = SimpleDocTemplate(
            str(destino),
            pagesize=self.pagina_a4,
            leftMargin=self.margem_lado,
            rightMargin=self.margem_lado,
            topMargin=self.margem_topo,
            bottomMargin=self.margem_base,
            title=titulo_documento,
            author=self.recebedor.razao_social,
        )
        documento.build(corpo, onFirstPage=self._pagina, onLaterPages=self._pagina)
        return destino


def _caber(canvas, conteudo: str, fonte: str, tamanho: float, largura: float) -> str:
    """Corta com reticências o que não cabe na largura."""
    while canvas.stringWidth(conteudo, fonte, tamanho) > largura and len(conteudo) > 10:
        conteudo = conteudo[:-2].rstrip() + "…"
    return conteudo
