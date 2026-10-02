"""Gráficos da análise de juros de um cliente.

* ``GraficoComparacao``: ele × a média dos clientes, uma linha por medida (cada
  linha na sua própria escala — são unidades diferentes), barra para ele e um
  traço na média, com "1,6× a média" escrito ao lado;
* ``GraficoAtrasos``: cada honorário pago, em ordem de vencimento — a barra é o
  atraso em dias, os pontos são as cobranças feitas até ele pagar;
* ``GraficoCenarios``: juros do período em cada cenário — como está (azul) e o
  que entraria a mais (laranja). Clicar numa linha escolhe o cenário.

Mesmas regras e cores dos gráficos do painel (validadas para daltonismo).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QFontMetricsF, QPainter, QPen

from ...dominio.valores import formatar_data, formatar_moeda
from . import cores, tema
from .grafico_ranking import fonte_ajustada
from .graficos_painel import _barra, _Base, _escala, cor_da_serie, moeda_curta


def _cor_tema(nome: str):
    return tema.cor(nome, cores.tema_atual())


def _legenda(pintor: QPainter, x: float, y: float, itens, cor_texto, fonte) -> None:
    """Quadradinho de cor + nome (o texto fica na cor de texto, nunca na da série)."""
    pintor.setFont(fonte)
    metrica = QFontMetricsF(fonte)
    for cor, nome, ponto in itens:
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(cor)
        if ponto:
            pintor.drawEllipse(QPointF(x + 6, y + 6), 4.5, 4.5)
        else:
            pintor.drawRoundedRect(QRectF(x, y, 12, 12), 3, 3)
        pintor.setPen(cor_texto)
        largura = metrica.horizontalAdvance(nome)
        pintor.drawText(QRectF(x + 18, y - 4, largura + 4, 20), Qt.AlignmentFlag.AlignVCenter,
                        nome)
        x += 18 + largura + 22


def _rotulo_curto(honorario) -> str:
    """Rótulo do eixo: 07/26 para mês, 2026 para ano; sem competência, o vencimento."""
    if honorario.competencia_mes and honorario.competencia_ano:
        return f"{honorario.competencia_mes:02d}/{str(honorario.competencia_ano)[-2:]}"
    if honorario.competencia_ano:
        return str(honorario.competencia_ano)
    return formatar_data(honorario.vencimento)[:5]


# ------------------------------------------------------------- ele × média


@dataclass
class Medida:
    rotulo: str
    valor: float
    media: float | None
    formatar: Callable[[float], str]


class GraficoComparacao(_Base):
    ALTURA_LINHA = 46

    def definir(self, medidas: Sequence[Medida], animar: bool = True) -> None:
        self.medidas = list(medidas)
        self.setMinimumHeight(len(self.medidas) * self.ALTURA_LINHA + 34)
        self._animar(animar)

    def paintEvent(self, _evento) -> None:  # noqa: N802
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._areas = []
        medidas = getattr(self, "medidas", [])
        if not medidas:
            return
        texto, fraco, _ = self._cores()
        azul = cor_da_serie(0)
        fonte_pequena = fonte_ajustada(self.font(), -1.5, minimo=7.5)
        _legenda(pintor, 0, 6, [(azul, "Este cliente", False)], texto, fonte_pequena)
        pintor.setFont(fonte_pequena)
        largura_legenda = QFontMetricsF(fonte_pequena).horizontalAdvance("Este cliente") + 40
        pintor.setPen(QPen(texto, 2))
        pintor.drawLine(QPointF(largura_legenda, 4), QPointF(largura_legenda, 18))
        pintor.setPen(texto)
        pintor.drawText(QRectF(largura_legenda + 8, 2, 200, 20), Qt.AlignmentFlag.AlignVCenter,
                        "Média dos clientes")

        coluna_rotulo, coluna_texto = 210.0, 190.0
        espaco = max(80.0, self.width() - coluna_rotulo - coluna_texto - 12)
        y = 30.0
        for medida in medidas:
            teto = max(medida.valor, medida.media or 0.0) * 1.15 or 1.0
            meio = y + self.ALTURA_LINHA / 2
            pintor.setFont(self.font())
            pintor.setPen(texto)
            pintor.drawText(QRectF(0, y, coluna_rotulo - 10, self.ALTURA_LINHA),
                            Qt.AlignmentFlag.AlignVCenter, medida.rotulo)
            trilho = QRectF(coluna_rotulo, meio - 7, espaco, 14)
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(_cor_tema("faixa"))
            pintor.drawRoundedRect(trilho, 4, 4)
            largura = espaco * medida.valor / teto * self._progresso
            if largura > 0:
                pintor.setBrush(azul)
                pintor.drawRoundedRect(QRectF(trilho.left(), trilho.top(), max(4.0, largura),
                                              trilho.height()), 4, 4)
            comparacao = ""
            if medida.media is not None:
                x_media = trilho.left() + espaco * medida.media / teto
                pintor.setPen(QPen(texto, 2))
                pintor.drawLine(QPointF(x_media, meio - 12), QPointF(x_media, meio + 12))
                if medida.media > 0:
                    vezes = medida.valor / medida.media
                    if 0.95 <= vezes <= 1.05:
                        comparacao = "na média"
                    else:
                        comparacao = f"{vezes:.1f}× a média".replace(".", ",")
                elif medida.valor > 0:
                    comparacao = "acima da média"
            pintor.setFont(self.font())
            pintor.setPen(texto)
            valor = medida.formatar(medida.valor)
            # valor em cima, comparação embaixo — sem se encostar
            pintor.drawText(
                QRectF(trilho.right() + 12, y, coluna_texto, self.ALTURA_LINHA / 2 - 1),
                Qt.AlignmentFlag.AlignBottom, valor,
            )
            pintor.setFont(fonte_pequena)
            pintor.setPen(fraco)
            pintor.drawText(QRectF(trilho.right() + 12, meio + 1, coluna_texto, 16),
                            Qt.AlignmentFlag.AlignTop, comparacao)
            media_texto = (medida.formatar(medida.media) if medida.media is not None
                           else "sem média")
            self._areas.append((
                QRectF(0, y, self.width(), self.ALTURA_LINHA),
                f"<b>{medida.rotulo}</b><br>Este cliente: {valor}"
                f"<br>Média dos clientes: {media_texto}",
            ))
            y += self.ALTURA_LINHA


# ------------------------------------------------- atraso honorário a honorário


class GraficoAtrasos(_Base):
    """Barras: dias de atraso de cada honorário pago. Pontos: cobranças feitas."""

    MAXIMO_PONTOS = 5

    def definir(self, itens: Sequence, animar: bool = True) -> None:
        # do mais antigo para o mais recente, como uma linha do tempo
        self.itens = sorted(itens, key=lambda item: item.honorario.vencimento)
        self._animar(animar)

    def paintEvent(self, _evento) -> None:  # noqa: N802
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._areas = []
        itens = getattr(self, "itens", [])
        if not itens:
            self._vazio(pintor, "Nenhum honorário pago no período.")
            return
        texto, fraco, borda = self._cores()
        azul, laranja = cor_da_serie(0), cor_da_serie(1)
        fonte_pequena = fonte_ajustada(self.font(), -1.5, minimo=7.5)
        _legenda(pintor, 54, 6, [(azul, "Dias de atraso", False),
                                 (laranja, "Cobranças feitas", True)], texto, fonte_pequena)

        area = QRectF(54, 40, self.width() - 64, self.height() - 72)
        maximo = max(item.dias_atraso for item in itens)
        pontos_max = min(max(item.cobrancas for item in itens), self.MAXIMO_PONTOS)
        # folga em cima para os pontos das cobranças e o rótulo do maior atraso
        folga = (pontos_max * 11 + 26) / max(1.0, area.height())
        teto, linhas = _escala((float(maximo) if maximo else 1.0) * (1 + folga))
        pintor.setFont(fonte_pequena)
        for valor in linhas:
            y = area.bottom() - area.height() * valor / teto
            pintor.setPen(QPen(borda, 1))
            pintor.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            pintor.setPen(fraco)
            pintor.drawText(QRectF(0, y - 9, area.left() - 8, 18),
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                            f"{valor:.0f} d")

        largura = area.width() / len(itens)
        largura_barra = min(30.0, largura * 0.56)
        maior = max(range(len(itens)), key=lambda i: itens[i].dias_atraso)
        for indice, item in enumerate(itens):
            centro = area.left() + largura * (indice + 0.5)
            altura = area.height() * item.dias_atraso / teto * self._progresso
            barra = QRectF(centro - largura_barra / 2, area.bottom() - altura, largura_barra,
                           altura)
            if item.dias_atraso > 0:
                _barra(pintor, barra, azul)
            else:
                # em dia: um traço fino na base, para a coluna não parecer vazia
                pintor.setPen(QPen(fraco, 2))
                pintor.drawLine(QPointF(barra.left() + 4, area.bottom() - 1),
                                QPointF(barra.right() - 4, area.bottom() - 1))
            # cobranças: pontos empilhados acima da barra, com anel da cor de fundo
            pontos = min(item.cobrancas, self.MAXIMO_PONTOS)
            topo = barra.top() if item.dias_atraso > 0 else area.bottom()
            for ponto in range(pontos):
                y = topo - 9 - ponto * 11
                pintor.setPen(QPen(_cor_tema("superficie"), 2))   # anel: separa os pontos
                pintor.setBrush(laranja)
                pintor.drawEllipse(QPointF(centro, y), 4.5, 4.5)
            if item.cobrancas > self.MAXIMO_PONTOS:
                pintor.setPen(texto)
                pintor.drawText(QRectF(centro - 20, topo - 9 - pontos * 11 - 16, 40, 14),
                                Qt.AlignmentFlag.AlignCenter,
                                f"+{item.cobrancas - self.MAXIMO_PONTOS}")
            # rótulo só no maior atraso; o resto vai na dica
            if indice == maior and item.dias_atraso > 0 and self._progresso >= 1:
                pintor.setPen(texto)
                deslocamento = pontos * 11 + 4
                pintor.drawText(QRectF(centro - 40, barra.top() - deslocamento - 18, 80, 16),
                                Qt.AlignmentFlag.AlignCenter, f"{item.dias_atraso} dias")
            honorario = item.honorario
            competencia = honorario.competencia_rotulo or formatar_data(honorario.vencimento)[3:]
            pintor.setPen(fraco)
            pintor.drawText(QRectF(centro - largura / 2, area.bottom() + 4, largura, 18),
                            Qt.AlignmentFlag.AlignCenter, _rotulo_curto(honorario))
            self._areas.append((
                QRectF(centro - largura / 2, area.top(), largura, area.height() + 22),
                f"<b>{honorario.tipo.nome} · {competencia}</b>"
                f"<br>Venceu {formatar_data(honorario.vencimento)} · pago em "
                f"{formatar_data(item.pago_em)}"
                f"<br>{'Em dia' if not item.dias_atraso else f'{item.dias_atraso} dias de atraso'}"
                f" · {item.cobrancas} cobrança(s)"
                f"<br>Juros pago: {formatar_moeda(item.juros_cobrados)}",
            ))


# ------------------------------------------------------------- cenários


class GraficoCenarios(_Base):
    """Juros do período em cada cenário: como está (azul) + o que entraria a mais."""

    escolhido = Signal(int)
    ALTURA_LINHA = 34

    def definir(self, cenarios: Sequence, selecionado: int | None, animar: bool = False) -> None:
        self.cenarios = list(cenarios)
        self.selecionado = selecionado
        self.setMinimumHeight(len(self.cenarios) * self.ALTURA_LINHA + 36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._animar(animar)

    def mousePressEvent(self, evento) -> None:  # noqa: N802
        indice = int((evento.position().y() - 30) // self.ALTURA_LINHA)
        if 0 <= indice < len(getattr(self, "cenarios", [])):
            self.escolhido.emit(indice)

    def paintEvent(self, _evento) -> None:  # noqa: N802
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._areas = []
        cenarios = getattr(self, "cenarios", [])
        if not cenarios:
            return
        texto, _, _ = self._cores()
        azul, laranja = cor_da_serie(0), cor_da_serie(1)
        fonte_pequena = fonte_ajustada(self.font(), -1.5, minimo=7.5)
        _legenda(pintor, 0, 6, [(azul, "Juros como está", False),
                                (laranja, "A mais no cenário", False)], texto, fonte_pequena)

        atual = float(next((c.juros_no_periodo for c in cenarios if c.atual), 0) or 0)
        maximo = max(float(c.juros_no_periodo) for c in cenarios) or 1.0
        coluna_rotulo, coluna_texto = 180.0, 190.0
        espaco = max(80.0, self.width() - coluna_rotulo - coluna_texto - 12)
        y = 30.0
        for indice, cenario in enumerate(cenarios):
            linha = QRectF(0, y, self.width(), self.ALTURA_LINHA)
            if indice == self.selecionado:
                pintor.setPen(Qt.PenStyle.NoPen)
                pintor.setBrush(_cor_tema("faixa"))
                pintor.drawRoundedRect(linha.adjusted(-4, 1, 4, -1), 6, 6)
            fonte = QFontMetricsF(self.font())
            negrito = self.font()
            negrito.setBold(indice == self.selecionado or cenario.atual)
            pintor.setFont(negrito)
            pintor.setPen(texto)
            pintor.drawText(QRectF(4, y, coluna_rotulo - 10, self.ALTURA_LINHA),
                            Qt.AlignmentFlag.AlignVCenter,
                            fonte.elidedText(cenario.rotulo, Qt.TextElideMode.ElideRight,
                                             coluna_rotulo - 14))
            base = min(atual, float(cenario.juros_no_periodo))
            extra = max(0.0, float(cenario.juros_no_periodo) - atual)
            meio = y + self.ALTURA_LINHA / 2
            largura_base = espaco * base / maximo * self._progresso
            largura_extra = espaco * extra / maximo * self._progresso
            pintor.setPen(Qt.PenStyle.NoPen)
            if largura_base > 0:
                pintor.setBrush(azul)
                pintor.drawRoundedRect(QRectF(coluna_rotulo, meio - 8, largura_base, 16), 4, 4)
            if largura_extra > 0:
                # 2 px de folga entre o que já entra e o que entraria a mais
                pintor.setBrush(laranja)
                pintor.drawRoundedRect(QRectF(coluna_rotulo + largura_base + 2, meio - 8,
                                              max(3.0, largura_extra - 2), 16), 4, 4)
            pintor.setFont(self.font())
            pintor.setPen(texto)
            diferenca = float(cenario.a_mais)
            sufixo = ""
            if diferenca > 0:
                sufixo = f"  (+{formatar_moeda(cenario.a_mais)})"
            elif diferenca < 0:
                sufixo = f"  (−{formatar_moeda(-cenario.a_mais)})"
            total = (moeda_curta(float(cenario.juros_no_periodo)) if maximo >= 1000
                     else formatar_moeda(cenario.juros_no_periodo))
            pintor.drawText(
                QRectF(coluna_rotulo + espaco + 10, y, coluna_texto, self.ALTURA_LINHA),
                Qt.AlignmentFlag.AlignVCenter, total + sufixo,
            )
            self._areas.append((
                linha,
                f"<b>{cenario.rotulo}</b><br>{cenario.explicacao}"
                f"<br>Juros no período: {formatar_moeda(cenario.juros_no_periodo)}"
                f"<br>Clique para ver o efeito em cada honorário",
            ))
            y += self.ALTURA_LINHA


# ------------------------------------------------ antes × depois, por linha


@dataclass
class LinhaAntesDepois:
    rotulo: str
    antes: float          # como está (azul)
    depois: float         # no cenário: o que passa de "antes" vira laranja
    texto: str            # escrito à direita
    dica: str = ""


class GraficoAntesDepois(_Base):
    """Uma barra por item: como está (azul) e o que entraria a mais (laranja).

    Serve ao "cenário honorário por honorário": juros pago × juros no cenário, e
    o que os atrasados de hoje renderiam em 30 dias.
    """

    ALTURA_LINHA = 30

    def definir(self, linhas: Sequence[LinhaAntesDepois], legenda: tuple[str, str],
                animar: bool = False) -> None:
        self.linhas = list(linhas)
        self.legenda = legenda
        self.setMinimumHeight(len(self.linhas) * self.ALTURA_LINHA + 34)
        self.setMaximumHeight(self.minimumHeight())
        self._animar(animar)

    def paintEvent(self, _evento) -> None:  # noqa: N802
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._areas = []
        linhas = getattr(self, "linhas", [])
        if not linhas:
            return
        texto, _, _ = self._cores()
        azul, laranja = cor_da_serie(0), cor_da_serie(1)
        _legenda(pintor, 0, 6, [(azul, self.legenda[0], False),
                                (laranja, self.legenda[1], False)],
                 texto, fonte_ajustada(self.font(), -1.5, minimo=7.5))
        maximo = max(max(linha.antes, linha.depois) for linha in linhas) or 1.0
        coluna_rotulo, coluna_texto = 200.0, 230.0
        espaco = max(80.0, self.width() - coluna_rotulo - coluna_texto - 12)
        metrica = QFontMetricsF(self.font())
        y = 30.0
        for linha in linhas:
            meio = y + self.ALTURA_LINHA / 2
            pintor.setFont(self.font())
            pintor.setPen(texto)
            pintor.drawText(
                QRectF(0, y, coluna_rotulo - 10, self.ALTURA_LINHA), Qt.AlignmentFlag.AlignVCenter,
                metrica.elidedText(linha.rotulo, Qt.TextElideMode.ElideRight, coluna_rotulo - 14),
            )
            base = min(linha.antes, linha.depois)
            extra = max(0.0, linha.depois - linha.antes)
            largura_base = espaco * base / maximo * self._progresso
            largura_extra = espaco * extra / maximo * self._progresso
            pintor.setPen(Qt.PenStyle.NoPen)
            if largura_base > 0:
                pintor.setBrush(azul)
                pintor.drawRoundedRect(QRectF(coluna_rotulo, meio - 7, largura_base, 14), 4, 4)
            if largura_extra > 0:
                pintor.setBrush(laranja)
                pintor.drawRoundedRect(QRectF(coluna_rotulo + largura_base + 2, meio - 7,
                                              max(3.0, largura_extra - 2), 14), 4, 4)
            pintor.setPen(texto)
            pintor.drawText(QRectF(coluna_rotulo + espaco + 10, y, coluna_texto, self.ALTURA_LINHA),
                            Qt.AlignmentFlag.AlignVCenter, linha.texto)
            if linha.dica:
                self._areas.append((QRectF(0, y, self.width(), self.ALTURA_LINHA), linha.dica))
            y += self.ALTURA_LINHA


def salvar_como_imagem(grafico, caminho, largura: int, altura: int | None = None) -> None:
    """O gráfico como PNG para o PDF: tema claro (o PDF é branco), resolução dobrada."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor, QImage, QRegion
    from PySide6.QtWidgets import QWidget

    altura = altura or max(grafico.minimumHeight(), 120)
    tema_antes = cores.tema_atual()
    cores.definir_tema("claro")
    try:
        grafico.setMaximumHeight(16777215)
        grafico.resize(largura, altura)
        imagem = QImage(largura * 2, altura * 2, QImage.Format.Format_ARGB32)
        imagem.setDevicePixelRatio(2)
        imagem.fill(QColor("#ffffff"))
        # sem o fundo da janela: no tema escuro ele viria escuro
        grafico.render(imagem, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
        imagem.save(str(caminho), "PNG")
    finally:
        cores.definir_tema(tema_antes)
