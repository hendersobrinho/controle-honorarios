"""Juros ao dia da empresa: um valor só, que vale para tudo o que está em aberto."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLineEdit, QVBoxLayout

from ...dominio.valores import formatar_moeda
from ...servicos import clientes
from ..comum import widgets
from ..comum.campos import CampoTaxa
from ..contexto import Contexto


class DialogoJuros(QDialog):
    def __init__(self, contexto: Contexto, cliente, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.cliente = cliente
        self.setWindowTitle(f"Juros ao dia – {cliente.nome}")
        self.resize(520, 240)
        self._montar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        atual = clientes.juros_atual(self.cliente)
        layout.addWidget(widgets.Cabecalho(
            "Juros ao dia", f"Hoje: {formatar_moeda(atual)} por dia de atraso"))
        formulario = QFormLayout()
        self.valor = CampoTaxa(atual)
        formulario.addRow("Juros por dia:", self.valor)
        self.motivo = QLineEdit()
        self.motivo.setPlaceholderText("Opcional. Ex.: reajuste, correção de digitação…")
        formulario.addRow("Motivo:", self.motivo)
        layout.addLayout(formulario)
        layout.addWidget(widgets.rotulo_fraco(
            "O novo valor vale para tudo o que está em aberto da empresa, inclusive os "
            "juros já corridos. Honorário já pago não muda. O valor anterior fica no log "
            "de alterações."
        ))
        layout.addStretch(1)

        acoes = QHBoxLayout()
        acoes.addStretch(1)
        cancelar = widgets.QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        salvar = widgets.QPushButton("Salvar")
        salvar.setObjectName("primario")
        salvar.clicked.connect(self._salvar)
        acoes.addWidget(cancelar)
        acoes.addWidget(salvar)
        layout.addLayout(acoes)

    def _salvar(self) -> None:
        def acao():
            clientes.definir_juros(self.contexto.sessao, self.cliente, self.valor.valor(),
                                   self.motivo.text().strip())
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.accept()
