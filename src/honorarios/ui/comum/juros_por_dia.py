"""Juros por dia: a conta "R$ por dia × dias de atraso" e o aviso de quando o valor
digitado no juros (que é o juros inteiro) parece ser só o de um dia."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QVBoxLayout

from ...dominio.valores import ZERO, dinheiro, formatar_moeda
from . import widgets
from .campos import CampoMoeda, Rotulo


def total_por_dia(valor_dia: Decimal, dias: int) -> Decimal:
    return dinheiro(Decimal(valor_dia) * max(dias, 0))


def conta_por_dia(valor_dia: Decimal, dias: int) -> str:
    return (f"{formatar_moeda(valor_dia)} por dia × {dias} dia(s) de atraso = "
            f"{formatar_moeda(total_por_dia(valor_dia, dias))}")


def parece_do_dia(juros: Decimal, dias: int, taxa_dia: Decimal) -> bool:
    """O juros digitado é do tamanho do juros de um dia, num honorário com vários
    dias de atraso (ex.: R$ 1,67 com 95 dias, quando o certo seria R$ 158,65)."""
    if dias < 3 or juros <= 0:
        return False
    if taxa_dia > 0:
        return juros <= taxa_dia * 2
    return False


def aviso_do_dia(juros: Decimal, dias: int, taxa_dia: Decimal,
                 como: str = "use \"Por dia…\"") -> str:
    if not parece_do_dia(juros, dias, taxa_dia):
        return ""
    return (f"⚠ {formatar_moeda(juros)} parece o juros de UM dia. Este campo é o juros "
            f"inteiro. Se é por dia, {como}: {conta_por_dia(juros, dias)}.")


class DialogoJurosPorDia(QDialog):
    """Digita quanto é o juros por dia; o total (× dias de atraso) vai para o campo."""

    def __init__(self, dias: int, sugestao: Decimal = ZERO, parent=None) -> None:
        super().__init__(parent)
        self.dias = dias
        self.total: Decimal | None = None
        self.setWindowTitle("Juros por dia")
        layout = QVBoxLayout(self)
        layout.addWidget(widgets.Cabecalho(
            "Juros por dia",
            "Digite quanto o juros é por dia. O sistema multiplica pelos dias de atraso "
            "e põe o total no juros."))
        formulario = QFormLayout()
        formulario.addRow("Dias de atraso:", Rotulo(str(dias)))
        self.valor_dia = CampoMoeda(sugestao)
        self.valor_dia.valueChanged.connect(lambda *_: self._mostrar())
        formulario.addRow("Juros por dia:", self.valor_dia)
        self.conta = Rotulo("", "valorDestaque")
        formulario.addRow("Juros total:", self.conta)
        layout.addLayout(formulario)
        botoes = QHBoxLayout()
        botoes.addStretch(1)
        cancelar = widgets.QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        usar = widgets.QPushButton("Usar este total")
        usar.setObjectName("primario")
        usar.setDefault(True)
        usar.clicked.connect(self._usar)
        botoes.addWidget(cancelar)
        botoes.addWidget(usar)
        layout.addLayout(botoes)
        self._mostrar()

    def _mostrar(self) -> None:
        self.conta.setText(conta_por_dia(self.valor_dia.valor(), self.dias))

    def _usar(self) -> None:
        self.total = total_por_dia(self.valor_dia.valor(), self.dias)
        self.accept()
