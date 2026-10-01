"""Original × recebido por mês: coluna do valor original com o juros empilhado.

O juros costuma ser pequeno perto do original, então a coluna sozinha não
mostra nada; por isso o percentual de acréscimo vai escrito em cima de cada mês.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from ...dominio.valores import formatar_moeda
from ...servicos.analise_juros import Mes, percentual
from . import cores, tema
from .grafico_ranking import fonte_ajustada

ALTURA = 230


class GraficoMeses(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.meses: list[Mes] = []
        self._progresso = 1.0
        self._colunas: list[QRectF] = []
        self.setMouseTracking(True)
        self.setFixedHeight(ALTURA)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._animacao = QVariantAnimation(self)
        self._animacao.setStartValue(0.0)
        self._animacao.setEndValue(1.0)
        self._animacao.setDuration(800)
        self._animacao.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animacao.valueChanged.connect(self._avancar)

    def definir(self, meses: list[Mes], animar: bool = True) -> None:
        self.meses = list(meses)
        if animar and self.meses:
            self._progresso = 0.0
            self._animacao.stop()
            self._animacao.start()
        else:
            self._progresso = 1.0
        self.update()

    def _avancar(self, valor) -> None:
        self._progresso = float(valor)
        self.update()

    def mouseMoveEvent(self, evento) -> None:  # noqa: N802
        posicao = evento.position()
        for coluna, mes in zip(self._colunas, self.meses, strict=False):
            if coluna.left() <= posicao.x() <= coluna.right():
                QToolTip.showText(
                    evento.globalPosition().toPoint(),
                    f"<b>{mes.rotulo}</b><br>Original: {formatar_moeda(mes.original)}"
                    f"<br>Juros recebido: {formatar_moeda(mes.juros)}"
                    f"<br>Juros abonado: {formatar_moeda(mes.abono)}"
                    f"<br>Acréscimo: +{percentual(mes.percentual, 2)}",
                    self,
                )
                return
        QToolTip.hideText()

    def paintEvent(self, _evento) -> None:  # noqa: N802
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        nome_tema = cores.tema_atual()
        cor_texto = tema.cor("texto", nome_tema)
        cor_fraca = tema.cor("texto_fraco", nome_tema)
        cor_original = QColor(tema.cor("destaque", nome_tema))
        cor_original.setAlpha(110)
        cor_juros = tema.cor("pago", nome_tema)
        self._colunas = []

        if not self.meses:
            pintor.setPen(cor_fraca)
            pintor.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "Nenhum pagamento no período."
            )
            return

        topo, base = 26, self.height() - 26
        area = base - topo
        maior = max(float(m.original + m.juros) for m in self.meses) or 1.0
        largura = self.width() / len(self.meses)
        coluna_largura = min(56.0, largura * 0.6)

        fonte = fonte_ajustada(self.font(), -0.5)
        pintor.setFont(fonte)
        pintor.setPen(QColor(cor_fraca))
        pintor.drawLine(0, int(base), self.width(), int(base))

        for indice, mes in enumerate(self.meses):
            centro = largura * indice + largura / 2
            x = centro - coluna_largura / 2
            altura_original = area * float(mes.original) / maior * self._progresso
            altura_juros = area * float(mes.juros) / maior * self._progresso
            # juros visível mesmo quando é centavos perto do original
            if mes.juros > 0:
                altura_juros = max(altura_juros, 3.0 * self._progresso)
            coluna = QRectF(x, base - altura_original, coluna_largura, altura_original)
            juros = QRectF(x, coluna.top() - altura_juros, coluna_largura, altura_juros)
            self._colunas.append(QRectF(largura * indice, topo, largura, area))

            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(cor_original)
            pintor.drawRoundedRect(coluna, 3, 3)
            pintor.setBrush(cor_juros)
            pintor.drawRoundedRect(juros, 2, 2)

            pintor.setPen(cor_juros if mes.juros > 0 else cor_fraca)
            pintor.drawText(
                QRectF(largura * indice, juros.top() - 18, largura, 16),
                Qt.AlignmentFlag.AlignCenter,
                f"+{percentual(mes.percentual, 2)}" if mes.juros > 0 else "—",
            )
            pintor.setPen(cor_texto)
            pintor.drawText(
                QRectF(largura * indice, base + 4, largura, 18),
                Qt.AlignmentFlag.AlignCenter,
                mes.rotulo,
            )
