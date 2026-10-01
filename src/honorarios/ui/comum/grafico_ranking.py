"""Ranking desenhado à mão: pódio com medalhas e barras que crescem ao aparecer.

Desenhado com QPainter em vez de QtCharts para ter o visual leve que a tela
pede — medalhas de ouro, prata e bronze, coroa no primeiro lugar, barras
arredondadas e o valor dentro da barra quando cabe.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QToolTip, QVBoxLayout, QWidget

from ...servicos.rankings import ItemRanking, Ranking
from . import cores, tema

ALTURA_LINHA = 52
MEDALHAS = (QColor("#F5B301"), QColor("#A7B1BC"), QColor("#CD7F32"))


def fonte_ajustada(base: QFont, diferenca: float, minimo: float = 8.0) -> QFont:
    """Cópia da fonte, maior ou menor. A folha de estilo define a fonte em pixels,
    e aí ``pointSizeF()`` devolve -1 — por isso os dois casos."""
    fonte = QFont(base)
    if fonte.pointSizeF() > 0:
        fonte.setPointSizeF(max(minimo, fonte.pointSizeF() + diferenca))
    else:
        fonte.setPixelSize(max(round(minimo * 4 / 3), round(fonte.pixelSize() + diferenca * 4 / 3)))
    return fonte


class _Barras(QWidget):
    clicado = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.itens: list[ItemRanking] = []
        self.cor = QColor("#1f6feb")
        self.vazio = ""
        self._progresso = 1.0
        self._sobre: int | None = None
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._animacao = QVariantAnimation(self)
        self._animacao.setStartValue(0.0)
        self._animacao.setEndValue(1.0)
        self._animacao.setDuration(900)
        self._animacao.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animacao.valueChanged.connect(self._avancar)

    def definir(self, itens: list[ItemRanking], cor: QColor, vazio: str, animar: bool = True):
        self.itens = list(itens)
        self.cor = cor
        self.vazio = vazio
        self.setFixedHeight(max(1, len(self.itens)) * ALTURA_LINHA + 12)
        if animar and self.itens:
            self._progresso = 0.0
            self._animacao.stop()
            self._animacao.start()
        else:
            self._progresso = 1.0
        self.update()

    def _avancar(self, valor) -> None:
        self._progresso = float(valor)
        self.update()

    # -------------------------------------------------------------- interação
    def _linha_em(self, y: float) -> int | None:
        indice = int((y - 6) // ALTURA_LINHA)
        return indice if 0 <= indice < len(self.itens) else None

    def mouseMoveEvent(self, evento) -> None:  # noqa: N802
        indice = self._linha_em(evento.position().y())
        if indice != self._sobre:
            self._sobre = indice
            self.setCursor(
                Qt.CursorShape.PointingHandCursor
                if indice is not None
                else Qt.CursorShape.ArrowCursor
            )
            self.update()
        if indice is not None:
            item = self.itens[indice]
            QToolTip.showText(
                evento.globalPosition().toPoint(),
                f"<b>{item.cliente.nome}</b><br>{item.rotulo}<br>{item.detalhe}"
                "<br><i>Clique para abrir a ficha</i>",
                self,
            )

    def leaveEvent(self, _evento) -> None:  # noqa: N802
        self._sobre = None
        self.update()

    def mousePressEvent(self, evento) -> None:  # noqa: N802
        indice = self._linha_em(evento.position().y())
        if indice is not None:
            self.clicado.emit(self.itens[indice].cliente)

    # ----------------------------------------------------------------- pintura
    def paintEvent(self, _evento) -> None:  # noqa: N802
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        nome_tema = cores.tema_atual()
        cor_texto = tema.cor("texto", nome_tema)
        cor_fraca = tema.cor("texto_fraco", nome_tema)
        cor_trilho = tema.cor("faixa", nome_tema)

        if not self.itens:
            pintor.setFont(fonte_ajustada(self.font(), 2))
            pintor.setPen(cor_fraca)
            pintor.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.vazio)
            return

        largura = self.width()
        maximo = max(item.valor for item in self.itens) or 1.0
        coluna_nome = max(150, int(largura * 0.38))
        inicio_barra = 50 + coluna_nome + 10
        fim_barra = largura - 12
        centro_v = Qt.AlignmentFlag.AlignVCenter
        direita_v = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        esquerda_v = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        espaco_barra = max(40, fim_barra - inicio_barra)

        fonte_nome = QFont(self.font())
        fonte_nome.setBold(True)
        fonte_detalhe = fonte_ajustada(self.font(), -2, minimo=7.0)
        fonte_valor = QFont(self.font())
        fonte_valor.setBold(True)
        fonte_coroa = fonte_ajustada(self.font(), 1)
        metrica_nome = QFontMetrics(fonte_nome)
        metrica_detalhe = QFontMetrics(fonte_detalhe)
        metrica_valor = QFontMetrics(fonte_valor)

        for posicao, item in enumerate(self.itens):
            topo = 6 + posicao * ALTURA_LINHA
            meio = topo + ALTURA_LINHA / 2

            if posicao == self._sobre:
                pintor.setPen(Qt.PenStyle.NoPen)
                pintor.setBrush(cor_trilho)
                fundo = QRectF(2, topo + 2, largura - 4, ALTURA_LINHA - 4)
                pintor.drawRoundedRect(fundo, 8, 8)

            # medalha: ouro, prata e bronze no pódio; número simples no resto
            circulo = QRectF(10, meio - 15, 30, 30)
            if posicao < 3:
                pintor.setPen(Qt.PenStyle.NoPen)
                pintor.setBrush(MEDALHAS[posicao])
                pintor.drawEllipse(circulo)
                pintor.setPen(QColor("#ffffff"))
            else:
                pintor.setPen(QPen(cor_fraca, 1.2))
                pintor.setBrush(Qt.BrushStyle.NoBrush)
                pintor.drawEllipse(circulo.adjusted(3, 3, -3, -3))
                pintor.setPen(cor_fraca)
            pintor.setFont(fonte_valor)
            pintor.drawText(circulo, Qt.AlignmentFlag.AlignCenter, str(posicao + 1))
            if posicao == 0:
                pintor.setFont(fonte_coroa)
                coroa = QRectF(24, meio - 30, 22, 18)
                pintor.drawText(coroa, Qt.AlignmentFlag.AlignCenter, "👑")

            # nome e detalhe
            pintor.setFont(fonte_nome)
            pintor.setPen(cor_texto)
            nome = metrica_nome.elidedText(
                item.cliente.nome, Qt.TextElideMode.ElideRight, coluna_nome
            )
            pintor.drawText(QRectF(50, meio - 17, coluna_nome, 18), centro_v, nome)
            pintor.setFont(fonte_detalhe)
            pintor.setPen(cor_fraca)
            detalhe = metrica_detalhe.elidedText(
                item.detalhe, Qt.TextElideMode.ElideRight, coluna_nome
            )
            pintor.drawText(QRectF(50, meio + 1, coluna_nome, 16), centro_v, detalhe)

            # trilho e barra
            trilho = QRectF(inicio_barra, meio - 10, espaco_barra, 20)
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(cor_trilho)
            pintor.drawRoundedRect(trilho, 10, 10)
            proporcao = (item.valor / maximo) * self._progresso
            comprimento = max(8.0, espaco_barra * proporcao)
            barra = QRectF(inicio_barra, meio - 10, comprimento, 20)
            gradiente = QLinearGradient(barra.topLeft(), barra.topRight())
            gradiente.setColorAt(0.0, self.cor.lighter(135))
            gradiente.setColorAt(1.0, self.cor)
            pintor.setBrush(gradiente)
            pintor.drawRoundedRect(barra, 10, 10)

            # valor: dentro da barra quando cabe, logo depois quando não
            pintor.setFont(fonte_valor)
            largura_texto = metrica_valor.horizontalAdvance(item.rotulo)
            if comprimento > largura_texto + 20:
                pintor.setPen(QColor("#ffffff"))
                area = QRectF(barra.left(), barra.top(), comprimento - 10, 20)
                pintor.drawText(area, direita_v, item.rotulo)
            else:
                pintor.setPen(cor_texto)
                area = QRectF(barra.right() + 8, barra.top(), largura_texto + 4, 20)
                pintor.drawText(area, esquerda_v, item.rotulo)


class GraficoRanking(QFrame):
    """Cartão com título, o ranking desenhado e uma curiosidade no rodapé."""

    cliente_clicado = Signal(object)

    def __init__(self, nome_cor: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("cartao")
        self.nome_cor = nome_cor
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(4)
        self.titulo = QLabel("")
        self.titulo.setObjectName("rankingTitulo")
        layout.addWidget(self.titulo)
        self.subtitulo = QLabel("")
        self.subtitulo.setObjectName("subtitulo")
        layout.addWidget(self.subtitulo)
        layout.addSpacing(6)
        self.barras = _Barras()
        self.barras.clicado.connect(self.cliente_clicado.emit)
        layout.addWidget(self.barras)
        layout.addStretch(1)
        self.curiosidade = QLabel("")
        self.curiosidade.setObjectName("rankingCuriosidade")
        self.curiosidade.setWordWrap(True)
        layout.addWidget(self.curiosidade)

    def definir(self, ranking: Ranking, animar: bool = True) -> None:
        self.titulo.setText(ranking.titulo)
        self.subtitulo.setText(ranking.subtitulo)
        self.barras.definir(
            ranking.itens,
            tema.cor(self.nome_cor, cores.tema_atual()),
            ranking.vazio,
            animar,
        )
        self.curiosidade.setText(ranking.curiosidade)
        self.curiosidade.setVisible(bool(ranking.curiosidade))
