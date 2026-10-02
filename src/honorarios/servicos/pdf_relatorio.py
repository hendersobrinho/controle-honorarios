"""Molde dos relatórios em PDF (análise de juros, painel): o mesmo visual em todos.

Com o fundo da cobrança como papel, o título vai sobre o fundo e o conteúdo num
cartão branco entre o logo do topo e o do rodapé. Sem fundo, sai o visual simples
(título no topo e a faixa de três cores na lateral).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from ..dominio.valores import formatar_data

AZUL = "#203461"
TEAL = "#4BBDCD"
LARANJA = "#F9B259"
FRACO = "#5B6577"
BORDA = "#D5DAE1"
FAIXA = "#EEF1F5"
VERDE = "#1F7A45"
VERMELHO = "#B03A2E"

# Com o fundo da cobrança como papel: o conteúdo vai num cartão branco entre o
# logo do topo e o do rodapé (medidas em pontos, página A4 de 595 × 842).
CARTAO_TOPO = 120        # distância do topo da página até o cartão
CARTAO_BASE = 84         # distância do pé da página até o fim do cartão
CARTAO_LADO = 28
RESPIRO = 18             # do cartão até o texto


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
        fundo: Path | None = None,
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
        self.fundo = fundo
        self.rodape = rodape
        self.cor = colors.HexColor
        self.pagina_a4 = A4
        if fundo is not None:
            self.margem_lado = CARTAO_LADO + RESPIRO
            self.margem_topo = CARTAO_TOPO + RESPIRO
            self.margem_base = CARTAO_BASE + RESPIRO + 14   # + a linha do rodapé
        else:
            self.margem_lado, self.margem_topo, self.margem_base = 18 * mm, 15 * mm, 16 * mm
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

    def topo(self):
        """Título no topo da página — só quando não há fundo (com fundo, ele vai no papel)."""
        from reportlab.platypus import Table, TableStyle

        topo = Table(
            [[
                [self.p(texto(self.titulo), "titulo"), self.p(texto(self.subtitulo), "subtitulo")],
                [self.p(texto(self.recebedor.razao_social), "fraco"),
                 self.p(f"Gerado em {formatar_data(self.gerado_em)}", "fraco")],
            ]],
            colWidths=[self.largura_util * 0.66, self.largura_util * 0.34],
        )
        topo.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("LINEBELOW", (0, 0), (-1, 0), 2, self.cor(TEAL)),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (0, 0), 0),
        ]))
        return topo

    def inicio(self) -> list:
        """O começo do corpo: o título (se não houver fundo) e um respiro."""
        from reportlab.platypus import Spacer

        return [] if self.fundo is not None else [self.topo(), Spacer(1, 6)]

    # ------------------------------------------------------------ página
    def _pagina_com_fundo(self, canvas, documento) -> None:
        largura, altura = self.pagina_a4
        canvas.saveState()
        canvas.drawImage(str(self.fundo), 0, 0, largura, altura)
        canvas.setFillColor(self.cor("#FFFFFF"))
        canvas.roundRect(
            CARTAO_LADO, CARTAO_BASE, largura - 2 * CARTAO_LADO,
            altura - CARTAO_TOPO - CARTAO_BASE, 14, stroke=0, fill=1,
        )
        # título no fundo, como na imagem de cobrança (à esquerda do logo do topo)
        canvas.setFillColor(self.cor(AZUL))
        canvas.setFont("Helvetica-Bold", 22)
        canvas.drawString(CARTAO_LADO + 14, altura - 58, self.titulo)
        canvas.setFont("Helvetica-Bold", 11)
        subtitulo = self.subtitulo
        # 360 pt: o resto da linha é da logo, no canto direito
        while canvas.stringWidth(subtitulo, "Helvetica-Bold", 11) > 360 and len(subtitulo) > 10:
            subtitulo = subtitulo[:-2].rstrip() + "…"
        canvas.drawString(CARTAO_LADO + 14, altura - 78, subtitulo)
        canvas.setFillColor(self.cor(TEAL))
        canvas.roundRect(CARTAO_LADO + 14, altura - 92, 40, 3.5, 1.7, stroke=0, fill=1)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(self.cor(FRACO))
        canvas.drawString(
            self.margem_lado, CARTAO_BASE + 12,
            f"{self.rodape} · {self.recebedor.razao_social[:50]} · gerado em "
            f"{formatar_data(self.gerado_em)}",
        )
        canvas.drawRightString(largura - self.margem_lado, CARTAO_BASE + 12,
                               f"Página {documento.page}")
        canvas.restoreState()

    def _pagina_simples(self, canvas, documento) -> None:
        from reportlab.lib.units import mm

        largura, altura = self.pagina_a4
        canvas.saveState()
        for indice, cor in enumerate((LARANJA, TEAL, AZUL)):
            canvas.setFillColor(self.cor(cor))
            canvas.rect(0, indice * altura / 3, 4 * mm, altura / 3, stroke=0, fill=1)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(self.cor(FRACO))
        canvas.drawString(
            18 * mm, 9 * mm,
            f"{self.rodape} · {self.subtitulo[:60]} · gerado em {formatar_data(self.gerado_em)}",
        )
        canvas.drawRightString(largura - 18 * mm, 9 * mm, f"Página {documento.page}")
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
        pagina = self._pagina_com_fundo if self.fundo is not None else self._pagina_simples
        documento.build(corpo, onFirstPage=pagina, onLaterPages=pagina)
        return destino
