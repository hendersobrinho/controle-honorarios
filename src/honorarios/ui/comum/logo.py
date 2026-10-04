"""A logo e o ícone do sistema: no menu lateral, na abertura e nas janelas.

É vetor (SVG), desenhada no tamanho exato em que aparece. No tema escuro o azul
da marca some no fundo, então ela vira clara — as cores de destaque continuam.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

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


ICONE = ARQUIVO.parent / "icone.svg"


def icone(lado: int) -> QPixmap:
    """O ícone do programa (o da área de trabalho), nítido em tela de alta densidade."""
    tela = QGuiApplication.primaryScreen()
    densidade = tela.devicePixelRatio() if tela else 1.0
    imagem = QPixmap(round(lado * densidade), round(lado * densidade))
    imagem.setDevicePixelRatio(densidade)
    imagem.fill(QColor(0, 0, 0, 0))
    pintor = QPainter(imagem)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(str(ICONE)).render(pintor, QRectF(0, 0, lado, lado))
    pintor.end()
    return imagem


AZUL, AZUL_ESCURO, TEAL, LARANJA = "#203461", "#141F40", "#4BBDCD", "#F9B259"


class TelaAbertura(QWidget):
    """A abertura: o ícone, o nome e a barra de carregamento, num cartão azul com
    os arcos das cores da marca (o mesmo desenho do ícone)."""

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(540, 340)
        self.setStyleSheet(f"""
            QLabel {{ background: transparent; }}
            QLabel#nomeAbertura {{ color: #FFFFFF; font-size: 26px; font-weight: 800; }}
            QLabel#subtituloAbertura {{ color: #C9D3E8; font-size: 13px; }}
            QLabel#mensagemAbertura {{ color: #DCE3F2; font-size: 12px; }}
            QLabel#porcentagemAbertura {{ color: {LARANJA}; font-size: 12px; font-weight: 700; }}
            QLabel#rodapeAbertura {{ color: #8A97B5; font-size: 11px; }}
            QProgressBar {{ background: rgba(255, 255, 255, 38); border: none;
                            border-radius: 3px; }}
            QProgressBar::chunk {{ border-radius: 3px; background: qlineargradient(
                x1:0, y1:0, x2:1, y2:0, stop:0 {TEAL}, stop:1 {LARANJA}); }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 34, 48, 22)
        layout.setSpacing(6)
        self.figura = QLabel()
        self.figura.setPixmap(icone(112))
        self.figura.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.figura)
        layout.addSpacing(8)
        nome = QLabel("Financeiro Métodos")
        nome.setObjectName("nomeAbertura")
        nome.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(nome)
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
        self.barra = QProgressBar()
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(6)
        self.barra.setRange(0, 100)
        layout.addWidget(self.barra)
        layout.addSpacing(10)
        rodape = QLabel("Métodos Serviços Contábeis")
        rodape.setObjectName("rodapeAbertura")
        rodape.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(rodape)
        tela = QGuiApplication.primaryScreen()
        if tela is not None:
            centro = tela.availableGeometry().center()
            self.move(centro.x() - self.width() // 2, centro.y() - self.height() // 2)

    def paintEvent(self, _evento) -> None:  # noqa: N802
        """O cartão: azul em degradê, cantos arredondados, os arcos da marca e um brilho
        suave atrás do ícone."""
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        cartao = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        fundo = QLinearGradient(cartao.topLeft(), cartao.bottomRight())
        fundo.setColorAt(0, QColor(AZUL))
        fundo.setColorAt(1, QColor(AZUL_ESCURO))
        contorno = QPainterPath()
        contorno.addRoundedRect(cartao, 20, 20)
        pintor.fillPath(contorno, fundo)
        pintor.setClipPath(contorno)
        # arcos nas cores do ícone, saindo pelos cantos
        for cor, caixa, inicio, extensao in (
            (TEAL, QRectF(-150, -170, 340, 340), 200 * 16, 110 * 16),
            (LARANJA, QRectF(self.width() - 170, self.height() - 150, 320, 320),
             20 * 16, 110 * 16),
        ):
            caneta = QPen(QColor(cor), 18)
            caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
            cor_fraca = QColor(cor)
            cor_fraca.setAlpha(70)
            caneta.setColor(cor_fraca)
            pintor.setPen(caneta)
            pintor.drawArc(caixa, inicio, extensao)
        # brilho atrás do ícone
        centro = self.figura.geometry().center()
        brilho = QRadialGradient(QPointF(centro), 95)
        brilho.setColorAt(0, QColor(255, 255, 255, 46))
        brilho.setColorAt(1, QColor(255, 255, 255, 0))
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(brilho)
        pintor.drawEllipse(QPointF(centro), 95, 95)
        pintor.end()

    def avancar(self, porcentagem: int, texto: str = "") -> None:
        valor = max(0, min(100, porcentagem))
        self.barra.setValue(valor)
        self.porcentagem.setText(f"{valor}%")
        if texto:
            self.mensagem.setText(texto)
        QGuiApplication.processEvents()
