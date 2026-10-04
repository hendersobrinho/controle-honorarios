"""Tipos e formas de envio: os cadastros de apoio da cobrança, em abas."""

from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from ..comum import widgets
from ..contexto import Contexto
from .formas_envio import PainelFormasEnvio
from .tipos import PainelTipos


class PainelTiposEEnvio(QWidget):
    titulo = "Tipos e formas de envio"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addWidget(widgets.Cabecalho(
            "Tipos e formas de envio",
            "Grupos e tipos de honorário, e por onde a cobrança chega a cada cliente",
        ))
        self.tipos = PainelTipos(contexto)
        self.formas = PainelFormasEnvio(contexto)
        self.abas = QTabWidget()
        for painel, rotulo in ((self.tipos, "Grupos e tipos"), (self.formas, "Formas de envio")):
            painel.cabecalho.ocultar_titulo()
            self.abas.addTab(painel, rotulo)
        self.abas.currentChanged.connect(lambda *_: self.recarregar())
        layout.addWidget(self.abas, 1)

    def recarregar(self) -> None:
        self.abas.currentWidget().recarregar()
