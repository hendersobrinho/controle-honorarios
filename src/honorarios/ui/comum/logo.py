"""A logo do sistema (Métodos Financeiro): no menu lateral e na tela de abertura.

É vetor (SVG), desenhada no tamanho exato em que aparece. No tema escuro o azul
da marca some no fundo, então ela vira clara — as cores de destaque continuam.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

ARQUIVO = Path(__file__).resolve().parent.parent.parent / "recursos" / "logo.svg"
AZUL_DA_MARCA = "#203461"


def pixmap(largura: int, escuro: bool = False) -> QPixmap:
    """A logo na largura pedida, nítida em tela de alta densidade."""
    texto = ARQUIVO.read_text(encoding="utf-8")
    if escuro:
        texto = texto.replace(AZUL_DA_MARCA, "#E6EAEF")
    renderizador = QSvgRenderer(QByteArray(texto.encode("utf-8")))
    caixa = renderizador.viewBoxF()
    altura = round(largura * caixa.height() / caixa.width())
    densidade = QGuiApplication.primaryScreen().devicePixelRatio() if \
        QGuiApplication.primaryScreen() else 1.0
    imagem = QPixmap(round(largura * densidade), round(altura * densidade))
    imagem.setDevicePixelRatio(densidade)
    imagem.fill(QColor(0, 0, 0, 0))
    pintor = QPainter(imagem)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderizador.render(pintor, QRectF(0, 0, largura, altura))
    pintor.end()
    return imagem


class TelaAbertura(QWidget):
    """A logo no centro e a barra de carregamento embaixo, enquanto o sistema abre."""

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("telaAbertura")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget#telaAbertura { background: #ffffff; border: 1px solid #dfe3e8;"
            " border-radius: 14px; }"
            "QLabel#mensagemAbertura { color: #6b7684; font-size: 12px; }"
            "QProgressBar { background: #eef1f5; border: none; border-radius: 3px; }"
            "QProgressBar::chunk { background: #4BBDCD; border-radius: 3px; }"
        )
        self.setFixedSize(460, 250)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 44, 40, 30)
        layout.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(pixmap(360))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo, 1)
        self.barra = QProgressBar()
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(6)
        self.barra.setRange(0, 100)
        layout.addWidget(self.barra)
        self.mensagem = QLabel("Abrindo…")
        self.mensagem.setObjectName("mensagemAbertura")
        self.mensagem.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.mensagem)
        tela = QGuiApplication.primaryScreen()
        if tela is not None:
            centro = tela.availableGeometry().center()
            self.move(centro.x() - self.width() // 2, centro.y() - self.height() // 2)

    def avancar(self, porcentagem: int, texto: str = "") -> None:
        self.barra.setValue(max(0, min(100, porcentagem)))
        if texto:
            self.mensagem.setText(texto)
        QGuiApplication.processEvents()
