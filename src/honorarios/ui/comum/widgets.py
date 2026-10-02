"""Peças reaproveitadas pelas telas: cartões, cabeçalhos e diálogos de aviso."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...dominio.valores import formatar_moeda

__all__ = [
    "Cabecalho",
    "Cartao",
    "QPushButton",
    "abrir_url",
    "alinhar_direita",
    "aviso",
    "confirmar",
    "copiar",
    "erro",
    "executar",
    "informar",
    "linha_separadora",
    "rotulo_fraco",
    "rotulo_valor",
]
from ...servicos.erros import ErroDeNegocio


class Cartao(QFrame):
    """Indicador do painel: rótulo em cima, valor grande embaixo."""

    def __init__(self, rotulo: str, valor: str = "—", dica: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("cartao")
        self.setFrameShape(QFrame.Shape.NoFrame)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(2)
        self._rotulo = QLabel(rotulo)
        self._rotulo.setObjectName("rotuloCartao")
        self._valor = QLabel(valor)
        self._valor.setObjectName("valorCartao")
        layout.addWidget(self._rotulo)
        layout.addWidget(self._valor)
        if dica:
            self.setToolTip(dica)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def definir(self, valor: str | Decimal) -> None:
        if isinstance(valor, Decimal):
            valor = formatar_moeda(valor)
        self._valor.setText(str(valor))


class Cabecalho(QWidget):
    """Título da tela + área de botões à direita."""

    def __init__(self, titulo: str, subtitulo: str = "", parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        textos = QVBoxLayout()
        textos.setSpacing(0)
        self._titulo = QLabel(titulo)
        self._titulo.setObjectName("titulo")
        textos.addWidget(self._titulo)
        self._subtitulo = QLabel(subtitulo)
        self._subtitulo.setObjectName("subtitulo")
        self._subtitulo.setVisible(bool(subtitulo))
        textos.addWidget(self._subtitulo)
        layout.addLayout(textos)
        layout.addStretch(1)
        self.acoes = QHBoxLayout()
        self.acoes.setSpacing(8)
        layout.addLayout(self.acoes)

    def ocultar_titulo(self) -> None:
        """Dentro de uma aba o título repetiria o nome da aba: fica só o subtítulo."""
        self._titulo.setVisible(False)

    def definir_subtitulo(self, texto: str) -> None:
        self._subtitulo.setText(texto)
        self._subtitulo.setVisible(bool(texto))

    def adicionar_botao(self, texto: str, funcao: Callable[[], None], primario: bool = False,
                        atalho: str = "") -> QPushButton:
        botao = QPushButton(texto)
        if primario:
            botao.setObjectName("primario")
        if atalho:
            botao.setShortcut(atalho)
            botao.setToolTip(f"{texto} ({atalho})")
        botao.clicked.connect(funcao)
        self.acoes.addWidget(botao)
        return botao


def linha_separadora() -> QFrame:
    linha = QFrame()
    linha.setFrameShape(QFrame.Shape.HLine)
    linha.setFrameShadow(QFrame.Shadow.Plain)
    return linha


# ------------------------------------------------------------------ mensagens


def aviso(parent, texto: str, titulo: str = "Atenção") -> None:
    QMessageBox.warning(parent, titulo, texto)


def erro(parent, texto: str, titulo: str = "Não foi possível concluir") -> None:
    QMessageBox.critical(parent, titulo, texto)


def informar(parent, texto: str, titulo: str = "Pronto") -> None:
    QMessageBox.information(parent, titulo, texto)


def confirmar(parent, texto: str, titulo: str = "Confirmar", detalhe: str = "") -> bool:
    caixa = QMessageBox(parent)
    caixa.setWindowTitle(titulo)
    caixa.setIcon(QMessageBox.Icon.Question)
    caixa.setText(texto)
    if detalhe:
        caixa.setInformativeText(detalhe)
    sim = caixa.addButton("Confirmar", QMessageBox.ButtonRole.AcceptRole)
    caixa.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
    caixa.setDefaultButton(sim)
    caixa.exec()
    return caixa.clickedButton() is sim


def executar(
    parent, funcao: Callable[[], object], ao_terminar: Callable[[], None] | None = None
) -> tuple[bool, object]:
    """Roda a ação tratando erro de negócio como mensagem, não como travamento.

    Devolve ``(deu_certo, resultado)``; erro de negócio virou aviso na tela e
    qualquer outra falha vai para o log com a mensagem genérica.
    """
    try:
        resultado = funcao()
    except ErroDeNegocio as falha:
        aviso(parent, str(falha))
        return False, None
    except Exception as falha:  # noqa: BLE001
        from ...config.registro import log

        log(__name__).exception("Falha inesperada na interface")
        erro(parent, f"Erro inesperado: {falha}\n\nO detalhe foi gravado no log.")
        return False, None
    if ao_terminar:
        ao_terminar()
    return True, resultado


def copiar(texto: str) -> None:
    QGuiApplication.clipboard().setText(texto)


def abrir_url(url: str) -> bool:
    return QDesktopServices.openUrl(QUrl(url))


def alinhar_direita(widget: QWidget) -> QWidget:
    caixa = QWidget()
    layout = QHBoxLayout(caixa)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addStretch(1)
    layout.addWidget(widget)
    return caixa


def rotulo_fraco(texto: str) -> QLabel:
    etiqueta = QLabel(texto)
    etiqueta.setObjectName("subtitulo")
    etiqueta.setWordWrap(True)
    return etiqueta


def rotulo_valor(texto: str = "—") -> QLabel:
    etiqueta = QLabel(texto)
    etiqueta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return etiqueta
