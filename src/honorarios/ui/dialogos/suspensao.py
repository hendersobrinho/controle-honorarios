"""Suspender e retomar a cobrança de um cliente."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QPlainTextEdit,
    QVBoxLayout,
)

from ...dominio.valores import formatar_data, hoje, somar_meses
from ...servicos import clientes as servico
from ..comum import widgets
from ..comum.campos import CampoData
from ..contexto import Contexto


class DialogoSuspensao(QDialog):
    """Pausa a cobrança sem mexer na dívida: o juros continua correndo."""

    def __init__(self, contexto: Contexto, cliente, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.cliente = cliente
        self.setWindowTitle(f"Suspender cobrança – {cliente.nome}")
        self.resize(520, 380)
        self._montar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(
            widgets.Cabecalho(
                self.cliente.nome,
                f"Código {self.cliente.codigo} · {self.cliente.tipo_pessoa.rotulo}",
            )
        )

        formulario = QFormLayout()
        self.motivo = QPlainTextEdit()
        self.motivo.setPlaceholderText(
            "Ex.: cliente em acordo judicial, empresa baixada, negociação em curso…"
        )
        self.motivo.setMaximumHeight(90)
        formulario.addRow("Motivo:", self.motivo)

        self.com_prazo = QCheckBox("Retomar automaticamente em")
        self.com_prazo.toggled.connect(self._ajustar)
        self.ate = CampoData(somar_meses(hoje(), 1))
        self.ate.setEnabled(False)
        formulario.addRow(self.com_prazo, self.ate)
        layout.addLayout(formulario)

        layout.addWidget(
            widgets.rotulo_fraco(
                "O cartão do cliente fica cinza com a etiqueta \"Cobrança suspensa\" e "
                "o sistema recusa registrar cobrança dele. Os honorários continuam em "
                "aberto e o juros continua correndo — o que para é a cobrança, não a "
                "dívida."
            )
        )
        layout.addStretch(1)

        acoes = QHBoxLayout()
        acoes.addStretch(1)
        cancelar = widgets.QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        confirmar = widgets.QPushButton("Suspender cobrança")
        confirmar.setObjectName("primario")
        confirmar.clicked.connect(self._confirmar)
        acoes.addWidget(cancelar)
        acoes.addWidget(confirmar)
        layout.addLayout(acoes)

    def _ajustar(self) -> None:
        self.ate.setEnabled(self.com_prazo.isChecked())

    def _confirmar(self) -> None:
        ate = self.ate.valor() if self.com_prazo.isChecked() else None

        def acao():
            servico.suspender_cobranca(
                self.contexto.sessao, self.cliente, self.motivo.toPlainText(), ate
            )
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.accept()


def retomar(parent, contexto: Contexto, cliente) -> bool:
    """Confirma e retoma a cobrança do cliente."""
    detalhe = servico.suspensao(cliente) or "Cobrança suspensa"
    if cliente.suspensa_em:
        detalhe += f"\nSuspensa em {formatar_data(cliente.suspensa_em)}."
    if not widgets.confirmar(
        parent,
        f"Retomar a cobrança de {cliente.nome}?",
        "Retomar cobrança",
        f"{detalhe}\n\nEle volta a aparecer nas filas de cobrança.",
    ):
        return False

    def acao():
        servico.retomar_cobranca(contexto.sessao, cliente, "Retomada pela tela de clientes")
        contexto.salvar()

    deu_certo, _ = widgets.executar(parent, acao)
    if not deu_certo:
        contexto.desfazer()
    return deu_certo
