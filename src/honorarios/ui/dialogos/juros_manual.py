"""Juros de um honorário conferido e acertado à mão: outro valor, sem juros ou o
calculado de volta. Usado no parcelamento (antes de parcelar e nas parcelas)."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QVBoxLayout

from ...dominio.valores import ZERO, formatar_data, formatar_moeda
from ...servicos.calculo import Atualizacao
from ..comum import widgets
from ..comum.campos import CampoMoeda, Rotulo


class DialogoJurosManual(QDialog):
    """Depois do ``exec``: ``juros`` é o valor escolhido, ou None para o calculado."""

    def __init__(self, titulo: str, honorario, atualizacao: Atualizacao,
                 aviso: str = "", parent=None) -> None:
        super().__init__(parent)
        self.atualizacao = atualizacao
        self.juros: Decimal | None = atualizacao.juros if atualizacao.juros_manual else None
        self.setWindowTitle(f"Juros – {titulo}")
        self.resize(480, 300)

        layout = QVBoxLayout(self)
        layout.addWidget(widgets.Cabecalho("Juros", titulo))
        formulario = QFormLayout()
        formulario.addRow("Vencimento:", Rotulo(formatar_data(honorario.vencimento)))
        formulario.addRow("Dias de atraso:", Rotulo(str(atualizacao.dias_atraso)))
        formulario.addRow("Valor:", Rotulo(formatar_moeda(atualizacao.saldo)))
        formulario.addRow("Juros calculado:", Rotulo(formatar_moeda(self.calculado)))
        self.campo = CampoMoeda(atualizacao.juros)
        self.campo.valueChanged.connect(lambda *_: self._mostrar_total())
        formulario.addRow("Juros:", self.campo)
        self.total = Rotulo("", "valorDestaque")
        formulario.addRow("Total:", self.total)
        layout.addLayout(formulario)
        if aviso:
            texto = widgets.rotulo_fraco(aviso)
            texto.setWordWrap(True)
            layout.addWidget(texto)
        layout.addStretch(1)

        botoes = QHBoxLayout()
        self.botao_sem_juros = widgets.QPushButton("Sem juros")
        self.botao_sem_juros.setToolTip("Tira o juros: fica só o valor")
        self.botao_sem_juros.clicked.connect(self._sem_juros)
        self.botao_calculado = widgets.QPushButton("Voltar ao calculado")
        self.botao_calculado.clicked.connect(self._calculado)
        self.botao_calculado.setEnabled(atualizacao.juros_manual)
        cancelar = widgets.QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        aplicar = widgets.QPushButton("Aplicar")
        aplicar.setObjectName("primario")
        aplicar.setDefault(True)
        aplicar.clicked.connect(self._aplicar)
        for botao in (self.botao_sem_juros, self.botao_calculado):
            botoes.addWidget(botao)
        botoes.addStretch(1)
        botoes.addWidget(cancelar)
        botoes.addWidget(aplicar)
        layout.addLayout(botoes)
        self._mostrar_total()

    @property
    def calculado(self) -> Decimal:
        a = self.atualizacao
        return a.juros_calculado if a.juros_manual else a.juros

    def _mostrar_total(self) -> None:
        self.total.setText(formatar_moeda(self.atualizacao.saldo + self.campo.valor()))

    def _sem_juros(self) -> None:
        self.juros = ZERO
        self.accept()

    def _calculado(self) -> None:
        self.juros = None
        self.accept()

    def _aplicar(self) -> None:
        valor = self.campo.valor()
        # digitar o próprio calculado é o mesmo que não acertar nada
        self.juros = None if valor == self.calculado else valor
        self.accept()
