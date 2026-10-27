"""A logo, a marca do produto e o ícone do sistema: no menu lateral, na abertura e
nas janelas.

É vetor (SVG), desenhada no tamanho exato em que aparece. No tema escuro o azul
da marca some no fundo, então ela vira clara — as cores de destaque continuam.
A ``logo.svg`` é a da Métodos (vai nas imagens para o cliente); a ``marca.svg`` é
a do Financeiro (fica dentro do programa).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

ARQUIVO = Path(__file__).resolve().parent.parent.parent / "recursos" / "logo.svg"
MARCA = ARQUIVO.parent / "marca.svg"
MARCA_NEGATIVO = ARQUIVO.parent / "marca_negativo.svg"
ICONE = ARQUIVO.parent / "icone.svg"
ICONE_PEQUENO = ARQUIVO.parent / "icone_pequeno.svg"
AZUL_DA_MARCA = "#203461"


def _densidade() -> float:
    tela = QGuiApplication.primaryScreen()
    return tela.devicePixelRatio() if tela else 1.0


def pixmap(largura: int, escuro: bool = False, arquivo: Path = ARQUIVO) -> QPixmap:
    """A logo (ou outro SVG da marca) na largura pedida, nítida em tela de alta densidade."""
    texto = arquivo.read_text(encoding="utf-8")
    if escuro:
        texto = texto.replace(AZUL_DA_MARCA, "#E6EAEF")
    renderizador = QSvgRenderer(QByteArray(texto.encode("utf-8")))
    caixa = renderizador.viewBoxF()
    altura = round(largura * caixa.height() / caixa.width())
    densidade = _densidade()
    imagem = QPixmap(round(largura * densidade), round(altura * densidade))
    imagem.setDevicePixelRatio(densidade)
    imagem.fill(QColor(0, 0, 0, 0))
    pintor = QPainter(imagem)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderizador.render(pintor, QRectF(0, 0, largura, altura))
    pintor.end()
    return imagem


def icone(lado: int) -> QPixmap:
    """O ícone do programa (o da área de trabalho), nítido em tela de alta densidade.
    Até 24 px usa a versão pequena, de F mais grosso."""
    densidade = _densidade()
    imagem = QPixmap(round(lado * densidade), round(lado * densidade))
    imagem.setDevicePixelRatio(densidade)
    imagem.fill(QColor(0, 0, 0, 0))
    pintor = QPainter(imagem)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    arquivo = ICONE_PEQUENO if lado <= 24 else ICONE
    QSvgRenderer(str(arquivo)).render(pintor, QRectF(0, 0, lado, lado))
    pintor.end()
    return imagem


AZUL, AZUL_ESCURO, CIANO, PICOTE = "#203461", "#16254A", "#4BBDCD", "#8C9BC0"
LARGURA, ALTURA = 540, 340
CORPO, CANHOTO = 252, 264   # onde o corpo termina e o canhoto começa (a fresta fica entre)
RAIO, FURO = 20, 14


class TelaAbertura(QWidget):
    """A abertura num canhoto: o corpo navy com a marca, o picote e o canhoto ciano
    onde a barra carrega (o mesmo desenho do ícone)."""

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(LARGURA, ALTURA)
        self.setStyleSheet(f"""
            QLabel {{ background: transparent; }}
            QLabel#subtituloAbertura {{ color: {PICOTE}; font-size: 13px; }}
            QLabel#mensagemAbertura {{ color: {AZUL}; font-size: 12px; font-weight: 600; }}
            QLabel#porcentagemAbertura {{ color: {AZUL}; font-size: 13px; font-weight: 700; }}
            QProgressBar {{ background: rgba(32, 52, 97, 46); border: none;
                            border-radius: 3px; }}
            QProgressBar::chunk {{ border-radius: 3px; background: {AZUL}; }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 56, 28, 22)
        layout.setSpacing(0)
        self.figura = QLabel()
        self.figura.setPixmap(_altura(MARCA_NEGATIVO, 96))
        self.figura.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.figura.setFixedHeight(96)
        layout.addWidget(self.figura)
        layout.addSpacing(18)
        subtitulo = QLabel("Controle de honorários e cobrança")
        subtitulo.setObjectName("subtituloAbertura")
        subtitulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitulo)
        layout.addStretch(1)
        linha = QHBoxLayout()
        self.mensagem = QLabel("Abrindo…")
        self.mensagem.setObjectName("mensagemAbertura")
        self.porcentagem = QLabel("0%")
        self.porcentagem.setObjectName("porcentagemAbertura")
        linha.addWidget(self.mensagem, 1)
        linha.addWidget(self.porcentagem)
        layout.addLayout(linha)
        layout.addSpacing(10)
        self.barra = QProgressBar()
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(6)
        self.barra.setRange(0, 100)
        layout.addWidget(self.barra)
        tela = QGuiApplication.primaryScreen()
        if tela is not None:
            centro = tela.availableGeometry().center()
            self.move(centro.x() - self.width() // 2, centro.y() - self.height() // 2)

    @staticmethod
    def _recortado(topo: float, base: float, picote_embaixo: bool) -> QPainterPath:
        """Um retângulo arredondado cujos cantos do lado do picote são recortados por
        quartos de círculo com centro na borda lateral: os furos do picote."""
        caminho = QPainterPath()
        caminho.addRoundedRect(QRectF(0, topo, LARGURA, base - topo), RAIO, RAIO)
        picote = base if picote_embaixo else topo
        reto = QPainterPath()   # do lado do picote o canto fica reto antes do recorte
        reto.addRect(QRectF(0, base - RAIO if picote_embaixo else topo, LARGURA, RAIO))
        furos = QPainterPath()
        for x in (0, LARGURA):
            furos.addEllipse(QRectF(x - FURO, picote - FURO, 2 * FURO, 2 * FURO))
        return caminho.united(reto).subtracted(furos)

    def paintEvent(self, _evento) -> None:  # noqa: N802
        """O canhoto: corpo em degradê, a fresta com o picote e o canhoto ciano."""
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        pintor.setPen(Qt.PenStyle.NoPen)
        fundo = QLinearGradient(0, 0, LARGURA, CORPO)
        fundo.setColorAt(0, QColor(AZUL))
        fundo.setColorAt(1, QColor(AZUL_ESCURO))
        pintor.fillPath(self._recortado(0, CORPO, True), fundo)
        pintor.fillPath(self._recortado(CANHOTO, ALTURA, False), QColor(CIANO))
        tracinho = QColor(PICOTE)
        tracinho.setAlphaF(0.5)
        pintor.setBrush(tracinho)
        meio = (CORPO + CANHOTO) / 2
        for x in range(30, 510, 22):
            pintor.drawRoundedRect(QRectF(x, meio - 1.5, 11, 3), 1.5, 1.5)
        pintor.end()

    def avancar(self, porcentagem: int, texto: str = "") -> None:
        valor = max(0, min(100, porcentagem))
        self.barra.setValue(valor)
        self.porcentagem.setText(f"{valor}%")
        if texto:
            self.mensagem.setText(texto)
        QGuiApplication.processEvents()


def _altura(arquivo: Path, altura: int) -> QPixmap:
    """Um SVG da marca na altura pedida."""
    caixa = QSvgRenderer(str(arquivo)).viewBoxF()
    return pixmap(round(altura * caixa.width() / caixa.height()), arquivo=arquivo)
