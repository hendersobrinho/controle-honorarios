"""Peças reaproveitadas pelas telas: cartões, cabeçalhos e diálogos de aviso."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
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

    def definir_titulo(self, texto: str) -> None:
        self._titulo.setText(texto)

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


class DialogoConfirmacao(QDialog):
    """Confirmação no visual do sistema: a pergunta em destaque, um resumo do que
    vai acontecer, o detalhe e o botão com o nome da ação (não um "OK")."""

    def __init__(self, parent, texto: str, titulo: str, detalhe: str = "",
                 acao: str = "Confirmar", resumo=None, tipo: str = "primario") -> None:
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.setObjectName("dialogoConfirmacao")
        self.setMinimumWidth(460)
        self.setMaximumWidth(620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(14)
        pergunta = QLabel(texto)
        pergunta.setObjectName("perguntaConfirmacao")
        pergunta.setWordWrap(True)
        layout.addWidget(pergunta)
        if resumo:
            cartao = QFrame()
            cartao.setObjectName("resumoConfirmacao")
            grade = QGridLayout(cartao)
            grade.setContentsMargins(14, 10, 14, 10)
            grade.setHorizontalSpacing(18)
            grade.setVerticalSpacing(6)
            for linha, (rotulo, valor) in enumerate(resumo):
                nome = QLabel(rotulo)
                nome.setObjectName("rotuloResumoConfirmacao")
                dado = QLabel(valor)
                dado.setObjectName("valorResumoConfirmacao")
                dado.setWordWrap(True)
                grade.addWidget(nome, linha, 0, Qt.AlignmentFlag.AlignTop)
                grade.addWidget(dado, linha, 1)
            grade.setColumnStretch(1, 1)
            layout.addWidget(cartao)
        if detalhe:
            explicacao = QLabel(detalhe)
            explicacao.setObjectName("detalheConfirmacao")
            explicacao.setWordWrap(True)
            layout.addWidget(explicacao)
        botoes = QHBoxLayout()
        botoes.addStretch(1)
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        self.botao_acao = QPushButton(acao)
        # "pagamento" (verde), "perigo" (vermelho) ou "primario" (azul)
        self.botao_acao.setObjectName(
            {"pagamento": "cartaoPagamento", "perigo": "botaoPerigo"}.get(tipo, "primario")
        )
        self.botao_acao.setMinimumWidth(120)
        self.botao_acao.clicked.connect(self.accept)
        self.botao_acao.setDefault(True)
        botoes.addWidget(cancelar)
        botoes.addWidget(self.botao_acao)
        layout.addLayout(botoes)


def confirmar(parent, texto: str, titulo: str = "Confirmar", detalhe: str = "",
              acao: str = "Confirmar", resumo=None, tipo: str = "primario") -> bool:
    """Pergunta antes de uma ação; ``resumo`` é uma lista de (rótulo, valor)."""
    return bool(DialogoConfirmacao(parent, texto, titulo, detalhe, acao, resumo, tipo).exec())


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
