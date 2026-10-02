"""Honorários: o mês a mês, os recorrentes (contratos) e os avulsos, em abas."""

from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from ..comum import widgets
from ..contexto import Contexto
from .avulsos import PainelAvulsos
from .contratos import PainelContratos
from .mes_a_mes import PainelMesAMes


class PainelHonorarios(QWidget):
    titulo = "Honorários"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addWidget(widgets.Cabecalho(
            "Honorários", "O que foi emitido em cada mês, os contratos e os serviços avulsos"
        ))
        self.mes_a_mes = PainelMesAMes(contexto)
        self.recorrentes = PainelContratos(contexto)
        self.avulsos = PainelAvulsos(contexto)
        self.abas = QTabWidget()
        for painel, rotulo in (
            (self.mes_a_mes, "Mês a mês"),
            (self.recorrentes, "Recorrentes"),
            (self.avulsos, "Avulsos"),
        ):
            painel.cabecalho.ocultar_titulo()
            self.abas.addTab(painel, rotulo)
        self.abas.currentChanged.connect(lambda *_: self.recarregar())
        layout.addWidget(self.abas, 1)

    def recarregar(self) -> None:
        self.abas.currentWidget().recarregar()
