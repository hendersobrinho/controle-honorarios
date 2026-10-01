"""Gráficos do painel, desenhados com QPainter (como os rankings).

Regras seguidas: uma escala só por gráfico, grade discreta, marcas finas com
canto arredondado só na ponta, 2 px de folga entre segmentos, legenda sempre que
há mais de uma série, dica ao passar o mouse e número escrito só onde ajuda. As
cores das séries foram validadas para daltonismo, no tema claro e no escuro.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from ...dominio.valores import formatar_moeda
from . import cores, tema
from .grafico_ranking import fonte_ajustada

# séries categóricas, em ordem fixa (validadas: ΔE daltonismo 24,7 claro / 26,8 escuro)
SERIES = {
    "claro": ("#2a78d6", "#eb6834", "#1baf7a"),
    "escuro": ("#3987e5", "#d95926", "#199e70"),
}


def cor_da_serie(indice: int) -> QColor:
    return QColor(SERIES.get(cores.tema_atual(), SERIES["claro"])[indice])


def moeda_curta(valor: float) -> str:
    """Rótulo de eixo: R$ 12 mil, R$ 1,5 mi."""
    if abs(valor) >= 1_000_000:
        return f"R$ {valor / 1_000_000:.1f} mi".replace(".", ",")
    if abs(valor) >= 1_000:
        return f"R$ {valor / 1_000:.0f} mil"
    return f"R$ {valor:.0f}"


def _escala(maximo: float) -> tuple[float, list[float]]:
    """Teto 'redondo' do eixo e as linhas da grade (3 ou 4 divisões)."""
    if maximo <= 0:
        return 1.0, [0.0]
    passo_bruto = maximo / 4
    potencia = 10 ** math.floor(math.log10(passo_bruto))
    for fator in (1, 2, 2.5, 5, 10):
        passo = fator * potencia
        if passo * 4 >= maximo:
            break
    teto = passo * math.ceil(maximo / passo)
    return teto, [passo * i for i in range(int(round(teto / passo)) + 1)]


def _barra(pintor: QPainter, retangulo: QRectF, cor: QColor, raio: float = 4.0,
           arredondar_topo: bool = True) -> None:
    """Barra com canto arredondado só na ponta (a base fica reta, presa ao eixo)."""
    if retangulo.height() <= 0 or retangulo.width() <= 0:
        return
    raio = min(raio, retangulo.width() / 2, retangulo.height())
    caminho = QPainterPath()
    if arredondar_topo:
        caminho.moveTo(retangulo.bottomLeft())
        caminho.lineTo(retangulo.left(), retangulo.top() + raio)
        caminho.quadTo(retangulo.topLeft(), QPointF(retangulo.left() + raio, retangulo.top()))
        caminho.lineTo(retangulo.right() - raio, retangulo.top())
        caminho.quadTo(retangulo.topRight(), QPointF(retangulo.right(), retangulo.top() + raio))
        caminho.lineTo(retangulo.bottomRight())
        caminho.closeSubpath()
    else:
        caminho.addRect(retangulo)
    pintor.fillPath(caminho, cor)


class _Base(QWidget):
    """Animação de entrada, dica ao passar o mouse e as cores do tema."""

    ALTURA = 260

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._progresso = 1.0
        self._areas: list[tuple[QRectF, str]] = []   # região → texto da dica
        self.setMouseTracking(True)
        self.setMinimumHeight(self.ALTURA)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._animacao = QVariantAnimation(self)
        self._animacao.setStartValue(0.0)
        self._animacao.setEndValue(1.0)
        self._animacao.setDuration(700)
        self._animacao.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animacao.valueChanged.connect(self._avancar)

    def _animar(self, animar: bool) -> None:
        if animar:
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
        for area, texto in self._areas:
            if area.contains(posicao):
                QToolTip.showText(evento.globalPosition().toPoint(), texto, self)
                return
        QToolTip.hideText()

    def _cores(self) -> tuple[QColor, QColor, QColor]:
        nome = cores.tema_atual()
        return tema.cor("texto", nome), tema.cor("texto_fraco", nome), tema.cor("borda", nome)

    def _vazio(self, pintor: QPainter, texto: str) -> None:
        pintor.setPen(self._cores()[1])
        pintor.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, texto)

    def _grade(self, pintor: QPainter, area: QRectF, teto: float, linhas: list[float]) -> None:
        """Grade horizontal discreta, com o valor à esquerda."""
        _, fraco, borda = self._cores()
        pintor.setFont(fonte_ajustada(self.font(), -1.5, minimo=7.5))
        for valor in linhas:
            y = area.bottom() - area.height() * valor / teto
            pintor.setPen(QPen(borda, 1))
            pintor.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            pintor.setPen(fraco)
            pintor.drawText(
                QRectF(0, y - 9, area.left() - 8, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                moeda_curta(valor),
            )


class GraficoQuitacao(_Base):
    """Emitido por mês de competência: quitado + em aberto, empilhados."""

    def definir(self, meses: Sequence, animar: bool = True) -> None:
        self.meses = list(meses)
        self._animar(animar)

    def paintEvent(self, _evento) -> None:  # noqa: N802
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._areas = []
        meses = getattr(self, "meses", [])
        if not any(mes.emitido > 0 for mes in meses):
            self._vazio(pintor, "Nenhum honorário emitido neste ano.")
            return
        texto, fraco, _ = self._cores()
        quitado_cor, aberto_cor = cor_da_serie(0), cor_da_serie(1)

        # legenda no topo: duas séries, cor + nome em texto normal
        pintor.setFont(fonte_ajustada(self.font(), -0.5, minimo=8))
        x = 64.0
        for cor, nome in ((quitado_cor, "Quitado"), (aberto_cor, "Em aberto")):
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(cor)
            pintor.drawRoundedRect(QRectF(x, 8, 12, 12), 3, 3)
            pintor.setPen(texto)
            largura = QFontMetricsF(pintor.font()).horizontalAdvance(nome)
            pintor.drawText(QRectF(x + 18, 4, largura + 4, 20), Qt.AlignmentFlag.AlignVCenter,
                            nome)
            x += 18 + largura + 22

        area = QRectF(64, 36, self.width() - 76, self.height() - 64)
        maximo = max(float(mes.emitido) for mes in meses)
        teto, linhas = _escala(maximo)
        self._grade(pintor, area, teto, linhas)

        largura_mes = area.width() / len(meses)
        largura_barra = min(34.0, largura_mes * 0.58)
        pintor.setFont(fonte_ajustada(self.font(), -1, minimo=8))
        for indice, mes in enumerate(meses):
            centro = area.left() + largura_mes * (indice + 0.5)
            esquerda = centro - largura_barra / 2
            altura_quitado = area.height() * float(mes.quitado) / teto * self._progresso
            altura_aberto = area.height() * float(mes.em_aberto) / teto * self._progresso
            # quitado na base; em aberto por cima, com 2 px de folga entre os dois
            folga = 2.0 if altura_quitado > 0 and altura_aberto > 0 else 0.0
            _barra(pintor, QRectF(esquerda, area.bottom() - altura_quitado, largura_barra,
                                  altura_quitado), quitado_cor,
                   arredondar_topo=altura_aberto <= 0)
            _barra(pintor, QRectF(esquerda, area.bottom() - altura_quitado - folga - altura_aberto,
                                  largura_barra, altura_aberto), aberto_cor)
            pintor.setPen(fraco)
            pintor.drawText(QRectF(centro - largura_mes / 2, area.bottom() + 4, largura_mes, 18),
                            Qt.AlignmentFlag.AlignCenter, mes.rotulo)
            if mes.emitido > 0:
                self._areas.append((
                    QRectF(centro - largura_mes / 2, area.top(), largura_mes, area.height() + 22),
                    f"<b>{mes.rotulo}</b><br>Emitido: {formatar_moeda(mes.emitido)}"
                    f"<br>Quitado: {formatar_moeda(mes.quitado)} "
                    f"({mes.percentual_quitado:.0f}%)"
                    f"<br>Em aberto: {formatar_moeda(mes.em_aberto)}",
                ))


class GraficoColunas(_Base):
    """Uma série por mês (ex.: o que entrou no caixa). Sem legenda: o título nomeia."""

    def definir(self, rotulos: Sequence[str], valores: Sequence[Decimal], nome: str,
                animar: bool = True) -> None:
        self.rotulos = list(rotulos)
        self.valores = [float(valor) for valor in valores]
        self.nome = nome
        self._animar(animar)

    def paintEvent(self, _evento) -> None:  # noqa: N802
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._areas = []
        valores = getattr(self, "valores", [])
        if not any(valores):
            self._vazio(pintor, "Nenhuma baixa registrada neste ano.")
            return
        texto, fraco, _ = self._cores()
        cor = cor_da_serie(0)
        area = QRectF(64, 26, self.width() - 76, self.height() - 54)
        teto, linhas = _escala(max(valores))
        self._grade(pintor, area, teto, linhas)
        largura_mes = area.width() / len(valores)
        largura_barra = min(34.0, largura_mes * 0.58)
        maior = valores.index(max(valores))
        pintor.setFont(fonte_ajustada(self.font(), -1, minimo=8))
        for indice, (rotulo, valor) in enumerate(zip(self.rotulos, valores, strict=False)):
            centro = area.left() + largura_mes * (indice + 0.5)
            altura = area.height() * valor / teto * self._progresso
            barra = QRectF(
                centro - largura_barra / 2, area.bottom() - altura, largura_barra, altura
            )
            _barra(pintor, barra, cor)
            pintor.setPen(fraco)
            pintor.drawText(QRectF(centro - largura_mes / 2, area.bottom() + 4, largura_mes, 18),
                            Qt.AlignmentFlag.AlignCenter, rotulo)
            if indice == maior and self._progresso >= 1:   # rótulo só no maior
                pintor.setPen(texto)
                pintor.drawText(QRectF(centro - 60, barra.top() - 20, 120, 18),
                                Qt.AlignmentFlag.AlignCenter, moeda_curta(valor))
            if valor:
                self._areas.append((
                    QRectF(centro - largura_mes / 2, area.top(), largura_mes, area.height() + 22),
                    f"<b>{rotulo}</b><br>{self.nome}: {formatar_moeda(Decimal(str(valor)))}",
                ))


class GraficoBarrasHorizontais(_Base):
    """Composição: uma barra por categoria, com o valor e o % escritos ao lado."""

    ALTURA_LINHA = 34

    def definir(self, secoes: Sequence[tuple[str, Sequence[tuple[str, Decimal]]]],
                animar: bool = True) -> None:
        """``secoes``: [(título da seção, [(nome, valor), ...]), ...]."""
        self.secoes = [(titulo, list(itens)) for titulo, itens in secoes]
        linhas = sum(len(itens) + 1 for _, itens in self.secoes)
        self.setMinimumHeight(max(self.ALTURA, linhas * self.ALTURA_LINHA + 10))
        self._animar(animar)

    def paintEvent(self, _evento) -> None:  # noqa: N802
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._areas = []
        secoes = getattr(self, "secoes", [])
        if not any(itens for _, itens in secoes):
            self._vazio(pintor, "Nenhum honorário emitido neste ano.")
            return
        texto, fraco, _ = self._cores()
        cor = cor_da_serie(2)
        coluna_nome = 150.0
        coluna_valor = 150.0
        y = 4.0
        for titulo, itens in secoes:
            pintor.setFont(fonte_ajustada(self.font(), -1, minimo=8))
            pintor.setPen(fraco)
            pintor.drawText(QRectF(0, y, self.width(), 22), Qt.AlignmentFlag.AlignVCenter,
                            titulo.upper())
            y += self.ALTURA_LINHA - 8
            total = sum(float(valor) for _, valor in itens) or 1.0
            maximo = max((float(valor) for _, valor in itens), default=1.0) or 1.0
            espaco = self.width() - coluna_nome - coluna_valor - 12
            for nome, valor in itens:
                fracao = float(valor) / maximo
                metrica = QFontMetricsF(self.font())
                pintor.setFont(self.font())
                pintor.setPen(texto)
                pintor.drawText(
                    QRectF(0, y, coluna_nome - 8, self.ALTURA_LINHA - 8),
                    Qt.AlignmentFlag.AlignVCenter,
                    metrica.elidedText(nome, Qt.TextElideMode.ElideRight, coluna_nome - 8),
                )
                trilho = QRectF(coluna_nome, y + 6, espaco, self.ALTURA_LINHA - 20)
                pintor.setPen(Qt.PenStyle.NoPen)
                pintor.setBrush(tema.cor("faixa", cores.tema_atual()))
                pintor.drawRoundedRect(trilho, 4, 4)
                barra = QRectF(trilho.left(), trilho.top(),
                               max(3.0, espaco * fracao * self._progresso), trilho.height())
                pintor.setBrush(cor)
                pintor.drawRoundedRect(barra, 4, 4)
                percentual = float(valor) / total * 100
                pintor.setPen(texto)
                pintor.drawText(
                    QRectF(trilho.right() + 10, y, coluna_valor, self.ALTURA_LINHA - 8),
                    Qt.AlignmentFlag.AlignVCenter,
                    f"{moeda_curta(float(valor))} · {percentual:.0f}%",
                )
                self._areas.append((
                    QRectF(0, y, self.width(), self.ALTURA_LINHA - 4),
                    f"<b>{nome}</b><br>{formatar_moeda(Decimal(str(valor)))} "
                    f"({percentual:.1f}% de {titulo.lower()})",
                ))
                y += self.ALTURA_LINHA - 4
            y += 10
