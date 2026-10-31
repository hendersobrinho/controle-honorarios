"""Vencimentos: a vencer, atrasados, pagos e as cobranças, cada um numa aba.

Na ordem do tempo — o que ainda vai vencer, o que venceu sem pagamento e o que
já foi pago —, e por último as cobranças já feitas, para anotar o que o cliente
respondeu. Cada aba é a tela de sempre (filtros, cartões, cobrar, dar baixa); o
número ao lado do nome da aba é o que está em aberto (nas cobranças, o que
espera uma ação).
"""

from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from ...servicos import acompanhamento as servico_acompanhamento
from ...servicos import honorarios as servico_honorarios
from ..comum import widgets
from ..contexto import Contexto
from .acompanhamento import PainelAcompanhamento
from .honorarios import PainelAtrasados, PainelAVencer, PainelPagos


class PainelVencimentos(QWidget):
    titulo = "Vencimentos"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addWidget(widgets.Cabecalho(
            "Vencimentos", "O que vai vencer, o que venceu sem pagamento, o que já foi pago "
            "e as cobranças feitas"
        ))
        self.a_vencer = PainelAVencer(contexto)
        self.atrasados = PainelAtrasados(contexto)
        self.pagos = PainelPagos(contexto)
        self.cobrancas = PainelAcompanhamento(contexto)
        self.abas = QTabWidget()
        for painel in (self.a_vencer, self.atrasados, self.pagos, self.cobrancas):
            painel.cabecalho.ocultar_titulo()
            self.abas.addTab(painel, painel.titulo)
        self.abas.currentChanged.connect(lambda *_: self.recarregar())
        layout.addWidget(self.abas, 1)
        self._contar()

    def aba(self, titulo: str) -> QWidget | None:
        """Abre a aba com esse título ("A vencer", "Atrasados", "Pagos", "Cobranças")."""
        for indice in range(self.abas.count()):
            painel = self.abas.widget(indice)
            if painel.titulo == titulo:
                self.abas.setCurrentIndex(indice)
                return painel
        return None

    def _contar(self) -> None:
        sessao, referencia = self.contexto.sessao, self.contexto.data_referencia
        contagem = servico_honorarios.contar_pendentes(sessao, referencia)
        esperando = servico_acompanhamento.contar_pendentes(sessao, referencia)
        for painel, quantidade in ((self.a_vencer, contagem.a_vencer),
                                   (self.atrasados, contagem.atrasados),
                                   (self.cobrancas, esperando)):
            indice = self.abas.indexOf(painel)
            self.abas.setTabText(indice, f"{painel.titulo} ({quantidade})"
                                 if quantidade else painel.titulo)
        self.abas.setTabToolTip(
            self.abas.indexOf(self.cobrancas),
            "Cobranças já feitas e o que cada cliente respondeu"
            + (f" — {esperando} esperando uma ação" if esperando else ""),
        )

    def recarregar(self) -> None:
        self.abas.currentWidget().recarregar()
        self._contar()
