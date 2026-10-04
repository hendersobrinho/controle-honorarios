"""Notificações na tela: o botão com o contador, a lista e o aviso do canto.

O botão fica no pé do menu (acima da logo). A lista abre por cima, ao lado dele;
cada aviso tem "Abrir", que leva à tela já filtrada no cliente. Quando surge algo
novo com o sistema aberto, um aviso discreto aparece no canto por alguns segundos
— e, se o sistema operacional deixar, sai também uma notificação dele.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...dominio.valores import FUSO_LOCAL, formatar_data
from . import logo

ICONE = logo.ICONE


def icone_da_marca() -> QIcon:
    """O ícone do programa (o mesmo da área de trabalho): janela, barra de tarefas e
    notificação do sistema. Vetor: desenhado em cada tamanho, sempre nítido."""
    renderizador = QSvgRenderer(str(ICONE))
    icone = QIcon()
    for lado in (16, 20, 24, 32, 40, 48, 64, 96, 128, 256):
        imagem = QPixmap(lado, lado)
        imagem.fill(QColor(0, 0, 0, 0))
        pintor = QPainter(imagem)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderizador.render(pintor, QRectF(0, 0, lado, lado))
        pintor.end()
        icone.addPixmap(imagem)
    return icone


def _quando(momento: datetime) -> str:
    local = momento.astimezone(FUSO_LOCAL) if momento.tzinfo else momento
    agora = datetime.now(FUSO_LOCAL)
    if local.date() == agora.date():
        return f"hoje, {local:%H:%M}"
    return formatar_data(local.date())


class BotaoNotificacoes(QPushButton):
    """ "Notificações" com o número de não lidas ao lado."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("botaoNotificacoes")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 10, 0)
        self.rotulo = QLabel("Notificações")
        self.rotulo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.contador = QLabel()
        self.contador.setObjectName("contadorNotificacoes")
        self.contador.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.contador.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.rotulo, 1)
        layout.addWidget(self.contador)
        self.setMinimumHeight(38)
        self.definir(0)

    def definir(self, quantidade: int) -> None:
        self.quantidade = quantidade
        self.contador.setText(str(quantidade) if quantidade < 100 else "99+")
        self.contador.setVisible(quantidade > 0)
        self.setToolTip(f"{quantidade} notificação(ões) não lida(s)" if quantidade
                        else "Nenhuma notificação nova")


class _Item(QFrame):
    abrir = Signal(object)

    def __init__(self, notificacao, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("itemNotificacao")
        self.setProperty("lida", notificacao.lida)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 8, 8)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        titulo = QLabel(notificacao.titulo)
        titulo.setObjectName("tituloNotificacao")
        titulo.setWordWrap(True)
        textos.addWidget(titulo)
        detalhe = " · ".join(parte for parte in (notificacao.texto, _quando(notificacao.criada_em))
                             if parte)
        rodape = QLabel(detalhe)
        rodape.setObjectName("detalheNotificacao")
        rodape.setWordWrap(True)
        textos.addWidget(rodape)
        layout.addLayout(textos, 1)
        botao = QPushButton("Abrir")
        botao.setObjectName("cartaoAcao")
        botao.setCursor(Qt.CursorShape.PointingHandCursor)
        botao.clicked.connect(lambda: self.abrir.emit(notificacao))
        layout.addWidget(botao, 0, Qt.AlignmentFlag.AlignVCenter)


class ListaNotificacoes(QFrame):
    """A lista, aberta por cima da janela; fecha ao clicar fora."""

    abrir = Signal(object)
    marcar_todas = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("listaNotificacoes")
        self.setFixedSize(420, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(6)
        topo = QHBoxLayout()
        topo.setContentsMargins(16, 0, 10, 0)
        titulo = QLabel("Notificações")
        titulo.setObjectName("resumoTitulo")
        topo.addWidget(titulo, 1)
        self.botao_todas = QPushButton("Marcar todas como lidas")
        self.botao_todas.setObjectName("linkFiltro")
        self.botao_todas.clicked.connect(self.marcar_todas)
        topo.addWidget(self.botao_todas)
        layout.addLayout(topo)
        self.conteudo = QWidget()
        self.itens = QVBoxLayout(self.conteudo)
        self.itens.setContentsMargins(8, 0, 8, 0)
        self.itens.setSpacing(6)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QScrollArea.Shape.NoFrame)
        rolagem.setWidget(self.conteudo)
        layout.addWidget(rolagem, 1)

    def definir(self, notificacoes) -> None:
        while self.itens.count():
            item = self.itens.takeAt(0).widget()
            if item is not None:
                item.setParent(None)
                item.deleteLater()
        if not notificacoes:
            vazio = QLabel("Nenhuma notificação por enquanto.")
            vazio.setObjectName("detalheNotificacao")
            vazio.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.itens.addWidget(vazio)
        for notificacao in notificacoes:
            item = _Item(notificacao)
            item.abrir.connect(self.abrir)
            self.itens.addWidget(item)
        self.itens.addStretch(1)
        self.botao_todas.setEnabled(any(not n.lida for n in notificacoes))

    def mostrar_perto_de(self, ancora: QWidget) -> None:
        """Ao lado do botão, subindo a partir dele."""
        canto = ancora.mapToGlobal(QPoint(ancora.width() + 8, ancora.height()))
        self.move(canto.x(), canto.y() - self.height())
        self.show()


class AvisoNovo(QFrame):
    """O aviso do canto quando surge notificação nova: some sozinho."""

    ver = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("resumoDia")
        self.setFixedWidth(360)
        sombra = QGraphicsDropShadowEffect(self)
        sombra.setBlurRadius(24)
        sombra.setOffset(0, 5)
        sombra.setColor(QColor(0, 0, 0, 55))
        self.setGraphicsEffect(sombra)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 10, 10)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        titulo = QLabel("Novas notificações")
        titulo.setObjectName("resumoTitulo")
        textos.addWidget(titulo)
        self.texto = QLabel()
        self.texto.setWordWrap(True)
        textos.addWidget(self.texto)
        layout.addLayout(textos, 1)
        ver = QPushButton("Ver")
        ver.setObjectName("cartaoAcao")
        ver.clicked.connect(lambda: (self.hide(), self.ver.emit()))
        layout.addWidget(ver, 0, Qt.AlignmentFlag.AlignVCenter)
        self._temporizador = QTimer(self)
        self._temporizador.setSingleShot(True)
        self._temporizador.timeout.connect(self.hide)
        self.hide()

    def mostrar(self, texto: str, segundos: int = 10) -> None:
        self.texto.setText(texto)
        self.adjustSize()
        self.show()
        self.raise_()
        self._temporizador.start(segundos * 1000)
