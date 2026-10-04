"""Vencimentos: a vencer, atrasados e pagos, cada um numa aba de uma tela só.

Na ordem do tempo — o que ainda vai vencer, o que venceu sem pagamento e o que
já foi pago. Cada aba é a tela de sempre (filtros, cartões, cobrar, dar baixa);
o número ao lado do nome da aba é a quantidade em aberto.
"""

from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from ...servicos import honorarios as servico_honorarios
from ..comum import widgets
from ..contexto import Contexto
from .honorarios import PainelAtrasados, PainelAVencer, PainelPagos


class PainelVencimentos(QWidget):
    titulo = "Vencimentos"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addWidget(widgets.Cabecalho(
            "Vencimentos", "O que vai vencer, o que venceu sem pagamento e o que já foi pago"
        ))
        self.a_vencer = PainelAVencer(contexto)
        self.atrasados = PainelAtrasados(contexto)
        self.pagos = PainelPagos(contexto)
        self.abas = QTabWidget()
        for painel in (self.a_vencer, self.atrasados, self.pagos):
            painel.cabecalho.ocultar_titulo()
            self.abas.addTab(painel, painel.titulo)
        self.abas.currentChanged.connect(lambda *_: self.recarregar())
        layout.addWidget(self.abas, 1)
        self._contar()

    def aba(self, titulo: str) -> QWidget | None:
        """Abre a aba com esse título ("A vencer", "Atrasados", "Pagos")."""
        for indice in range(self.abas.count()):
            painel = self.abas.widget(indice)
            if painel.titulo == titulo:
                self.abas.setCurrentIndex(indice)
                return painel
        return None

    def _contar(self) -> None:
        contagem = servico_honorarios.contar_pendentes(
            self.contexto.sessao, self.contexto.data_referencia
        )
        for painel, quantidade in ((self.a_vencer, contagem.a_vencer),
                                   (self.atrasados, contagem.atrasados)):
            indice = self.abas.indexOf(painel)
            self.abas.setTabText(indice, f"{painel.titulo} ({quantidade})"
                                 if quantidade else painel.titulo)

    def recarregar(self) -> None:
        self.abas.currentWidget().recarregar()
        self._contar()
