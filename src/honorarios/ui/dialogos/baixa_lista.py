"""Baixa dos que saíram da lista do financeiro: prévia, conferência e confirmação.

A janela não trava o sistema (abre ao lado), para conferir no próprio e-mail
enquanto marca. Nada é gravado antes de "Dar baixa" e da confirmação.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...dominio.enums import FormaPagamento
from ...dominio.valores import ZERO, formatar_data, formatar_moeda, hoje
from ...servicos import email_cobrancas as servico
from ..comum import widgets
from ..comum.campos import CampoData, ComboEnum
from ..contexto import Contexto

COLUNAS = ("", "Cliente", "Competência", "Vencimento", "Saldo", "Juros", "Valor da baixa")


class DialogoBaixaLista(QDialog):
    baixou = Signal(int)

    def __init__(self, contexto: Contexto, conferencia: servico.Conferencia,
                 parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.conferencia = conferencia
        self.honorarios = [linha.honorario for linha in conferencia.sairam]
        self.itens: list[servico.ItemBaixa] = []
        self.setWindowTitle("Baixa dos que saíram da lista")
        self.setModal(False)
        self.resize(900, 520)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        clientes = len({h.cliente_id for h in self.honorarios})
        cabecalho = widgets.Cabecalho(
            f"{len(self.honorarios)} honorário(s) de {clientes} cliente(s) saíram da lista",
            f"Não estão no e-mail do financeiro de {formatar_data(conferencia.data)}: "
            "provavelmente foram pagos. Confira no e-mail e desmarque o que não foi.",
        )
        layout.addWidget(cabecalho)

        opcoes = QHBoxLayout()
        opcoes.setSpacing(10)
        opcoes.addWidget(QLabel("Pago em:"))
        self.data = CampoData(min(conferencia.data, hoje()))
        self.data.setMaximumDate(self.data.date().currentDate())
        self.data.setToolTip("O dia exato nem sempre se sabe: o padrão é a data do e-mail")
        opcoes.addWidget(self.data)
        opcoes.addSpacing(12)
        self.com_juros = QRadioButton("Com juros até a data")
        self.sem_juros = QRadioButton("Só o valor original (abona os juros)")
        self.com_juros.setChecked(True)
        grupo = QButtonGroup(self)
        grupo.addButton(self.com_juros)
        grupo.addButton(self.sem_juros)
        opcoes.addWidget(self.com_juros)
        opcoes.addWidget(self.sem_juros)
        opcoes.addStretch(1)
        opcoes.addWidget(QLabel("Forma:"))
        self.forma = ComboEnum(FormaPagamento, FormaPagamento.BOLETO)
        opcoes.addWidget(self.forma)
        layout.addLayout(opcoes)

        self.tabela = QTableWidget(0, len(COLUNAS))
        self.tabela.setHorizontalHeaderLabels(COLUNAS)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.tabela.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabela.horizontalHeader().setStretchLastSection(True)
        self.tabela.itemChanged.connect(self._marcou)
        layout.addWidget(self.tabela, 1)

        rodape = QHBoxLayout()
        self.total = QLabel()
        self.total.setObjectName("totalBaixa")
        rodape.addWidget(self.total, 1)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        self.botao_baixa = QPushButton()
        self.botao_baixa.setObjectName("cartaoPagamento")
        self.botao_baixa.setMinimumWidth(170)
        self.botao_baixa.clicked.connect(self.confirmar)
        rodape.addWidget(fechar)
        rodape.addWidget(self.botao_baixa)
        layout.addLayout(rodape)

        self.data.dateChanged.connect(lambda *_: self._calcular())
        self.com_juros.toggled.connect(lambda *_: self._calcular())
        self._calcular()

    def _calcular(self) -> None:
        marcados = {item.honorario.id: item.marcado for item in self.itens}
        self.itens = servico.previa_baixa(
            self.honorarios, self.data.valor(), self.com_juros.isChecked(),
            self.conferencia.data,
        )
        for item in self.itens:
            item.marcado = marcados.get(item.honorario.id, True)
        self.tabela.blockSignals(True)
        self.tabela.setRowCount(len(self.itens))
        direita = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        for linha, item in enumerate(self.itens):
            marca = QTableWidgetItem()
            marca.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            marca.setCheckState(Qt.CheckState.Checked if item.marcado
                                else Qt.CheckState.Unchecked)
            self.tabela.setItem(linha, 0, marca)
            honorario = item.honorario
            textos = (
                servico.nome_no_email(item.cliente),
                honorario.competencia_rotulo or honorario.tipo.nome,
                formatar_data(honorario.vencimento),
                formatar_moeda(item.saldo),
                formatar_moeda(item.juros_cobrados)
                + (" (abonado)" if item.juros > item.juros_cobrados else ""),
                formatar_moeda(item.valor),
            )
            for coluna, texto in enumerate(textos, start=1):
                celula = QTableWidgetItem(texto)
                if coluna >= 4:
                    celula.setTextAlignment(direita)
                if item.justificativa:
                    celula.setToolTip(item.justificativa)
                self.tabela.setItem(linha, coluna, celula)
        self.tabela.blockSignals(False)
        self.tabela.resizeColumnsToContents()
        self._resumir()

    def _marcou(self, celula: QTableWidgetItem) -> None:
        if celula.column() == 0:
            self.itens[celula.row()].marcado = celula.checkState() == Qt.CheckState.Checked
            self._resumir()

    def _resumir(self) -> None:
        marcados = [item for item in self.itens if item.marcado]
        total = sum((item.valor for item in marcados), start=ZERO)
        self.total.setText(f"{len(marcados)} marcado(s) · total {formatar_moeda(total)}")
        self.botao_baixa.setText(f"Dar baixa em {len(marcados)}…")
        self.botao_baixa.setEnabled(bool(marcados))

    def confirmar(self) -> None:
        marcados = [item for item in self.itens if item.marcado]
        if not marcados:
            return
        total = sum((item.valor for item in marcados), start=ZERO)
        clientes = len({item.honorario.cliente_id for item in marcados})
        plural = "honorário" if len(marcados) == 1 else "honorários"
        if not widgets.confirmar(
            self,
            f"Confirmar o pagamento de {len(marcados)} {plural}?",
            "Dar baixa",
            "Cada um passa para Pagos, com a observação \"saiu da lista do financeiro\". "
            "Se algo estiver errado, dá para estornar no histórico do honorário.",
            acao=f"Dar baixa em {len(marcados)}",
            resumo=[
                ("Clientes", f"{clientes}"),
                ("Total recebido", formatar_moeda(total)),
                ("Pago em", formatar_data(self.data.valor())),
                ("Valor", "com juros até a data" if self.com_juros.isChecked()
                 else "só o valor original (juros abonados)"),
                ("Forma", self.forma.valor().rotulo),
            ],
            tipo="pagamento",
        ):
            return

        def acao():
            quantos = servico.dar_baixa(
                self.contexto.sessao, self.itens, self.data.valor(), self.forma.valor(),
                self.conferencia.data,
            )
            self.contexto.salvar()
            return quantos

        deu_certo, quantos = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.baixou.emit(quantos)
        self.accept()
