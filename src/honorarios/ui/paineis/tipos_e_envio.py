"""Tipos de faturamento: os grupos e tipos de honorário.

As formas de envio ficam no cadastro dos clientes (tela Clientes).
"""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..comum import widgets
from ..contexto import Contexto
from .tipos import PainelTipos


class PainelTiposEEnvio(QWidget):
    titulo = "Tipos de faturamento"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addWidget(widgets.Cabecalho(
            "Tipos de faturamento", "Grupos e tipos de honorário"))
        self.tipos = PainelTipos(contexto)
        self.tipos.cabecalho.ocultar_titulo()
        layout.addWidget(self.tipos, 1)

    def recarregar(self) -> None:
        self.tipos.recarregar()
