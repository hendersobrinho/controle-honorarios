"""Juros de um honorário conferido e acertado à mão: o juros inteiro ou um valor por
dia (× dias de atraso), sem juros ou o calculado de volta. Usado no parcelamento
(antes de parcelar e nas parcelas)."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QRadioButton, QVBoxLayout

from ...dominio.valores import ZERO, formatar_data, formatar_moeda, hoje
from ...servicos import calculo
from ...servicos.calculo import Atualizacao
from ..comum import widgets
from ..comum.campos import CampoMoeda, Rotulo
from ..comum.juros_por_dia import aviso_do_dia, conta_por_dia, total_por_dia


class DialogoJurosManual(QDialog):
    """Depois do ``exec``: ``juros`` é o juros inteiro escolhido, ou None para o
    calculado; ``valor_dia`` é o valor por dia, quando foi escolhido assim."""

    def __init__(self, titulo: str, honorario, atualizacao: Atualizacao,
                 aviso: str = "", parent=None) -> None:
        super().__init__(parent)
        self.atualizacao = atualizacao
        self.dias = atualizacao.dias_atraso
        self.taxa_dia = calculo.taxa_vigente_em(honorario.cliente, hoje())
        self.juros: Decimal | None = atualizacao.juros if atualizacao.juros_manual else None
        self.valor_dia: Decimal | None = None
        self.setWindowTitle(f"Juros – {titulo}")
        self.resize(560, 380)

        layout = QVBoxLayout(self)
        layout.addWidget(widgets.Cabecalho("Juros", titulo))
        formulario = QFormLayout()
        formulario.addRow("Vencimento:", Rotulo(formatar_data(honorario.vencimento)))
        formulario.addRow("Dias de atraso:", Rotulo(str(self.dias)))
        formulario.addRow("Valor:", Rotulo(formatar_moeda(atualizacao.saldo)))
        formulario.addRow("Juros calculado:", Rotulo(
            f"{formatar_moeda(self.calculado)}  ({conta_por_dia(self.taxa_dia, self.dias)})"
            if self.dias else formatar_moeda(self.calculado)))
        layout.addLayout(formulario)

        layout.addWidget(Rotulo("<b>Como você quer informar o juros?</b>"))
        self.modo_total = QRadioButton("O juros inteiro (o total, já somando todos os dias)")
        self.modo_dia = QRadioButton("Um valor por dia (o sistema multiplica pelos dias de "
                                     "atraso)")
        self.modo_total.setChecked(True)
        self.modo_dia.setEnabled(self.dias > 0)
        for botao in (self.modo_total, self.modo_dia):
            botao.toggled.connect(lambda *_: self._trocar_modo())
            layout.addWidget(botao)

        campo = QFormLayout()
        self.campo = CampoMoeda(atualizacao.juros)
        self.campo.valueChanged.connect(lambda *_: self._mostrar_total())
        self.rotulo_campo = Rotulo("Juros total:")
        campo.addRow(self.rotulo_campo, self.campo)
        self.conta = widgets.rotulo_fraco("")
        self.conta.setWordWrap(True)
        campo.addRow("", self.conta)
        self.total = Rotulo("", "valorDestaque")
        campo.addRow("Total do honorário:", self.total)
        layout.addLayout(campo)
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

    def por_dia(self) -> bool:
        return self.modo_dia.isChecked()

    def juros_escolhido(self) -> Decimal:
        """O juros inteiro, do jeito que foi digitado (total ou por dia × dias)."""
        if self.por_dia():
            return total_por_dia(self.campo.valor(), self.dias)
        return self.campo.valor()

    def _trocar_modo(self) -> None:
        self.campo.blockSignals(True)
        if self.por_dia():
            self.rotulo_campo.setText("Juros por dia:")
            self.campo.definir(self.taxa_dia)
        else:
            self.rotulo_campo.setText("Juros total:")
            self.campo.definir(self.atualizacao.juros)
        self.campo.blockSignals(False)
        self._mostrar_total()

    def _mostrar_total(self) -> None:
        juros = self.juros_escolhido()
        if self.por_dia():
            self.conta.setText(conta_por_dia(self.campo.valor(), self.dias))
        else:
            self.conta.setText(aviso_do_dia(juros, self.dias, self.taxa_dia,
                                            "marque \"Um valor por dia\" acima")
                               or "É o juros inteiro do honorário, não o de um dia.")
        self.total.setText(formatar_moeda(self.atualizacao.saldo + juros))

    def _sem_juros(self) -> None:
        self.juros = ZERO
        self.accept()

    def _calculado(self) -> None:
        self.juros = None
        self.accept()

    def _aplicar(self) -> None:
        valor = self.juros_escolhido()
        self.valor_dia = self.campo.valor() if self.por_dia() else None
        # digitar o próprio calculado é o mesmo que não acertar nada
        self.juros = None if valor == self.calculado else valor
        self.accept()
