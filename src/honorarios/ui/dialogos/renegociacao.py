"""Renegociação: junta honorários em aberto num acordo parcelado."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QPlainTextEdit,
    QSpinBox,
    QTableView,
    QVBoxLayout,
)

from ...dominio.valores import formatar_moeda, hoje
from ...servicos import renegociacoes
from ..comum import widgets
from ..comum.campos import CampoData, CampoMoeda, ComboRegistros, Rotulo
from ..comum.tabelas import (
    Coluna,
    ModeloTabela,
    ajustar_colunas,
    coluna_data,
    coluna_moeda,
    preparar_tabela,
)
from ..contexto import Contexto


class DialogoRenegociacao(QDialog):
    def __init__(self, contexto: Contexto, cliente, linhas, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.cliente = cliente
        self.linhas = list(linhas)
        self.setWindowTitle(f"Renegociar – {cliente.nome}")
        self.resize(820, 620)
        self._montar()
        self._recalcular()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(
            widgets.Cabecalho(
                self.cliente.nome, f"{len(self.linhas)} honorário(s) em aberto no acordo"
            )
        )
        self.modelo = ModeloTabela(
            [
                Coluna("Tipo", lambda linha: linha.honorario.tipo.nome),
                Coluna("Competência", lambda linha: linha.honorario.competencia_rotulo),
                coluna_data("Vencimento", lambda linha: linha.honorario.vencimento),
                coluna_moeda("Valor", lambda linha: linha.atualizacao.valor_original),
                coluna_moeda("Juros", lambda linha: linha.atualizacao.juros),
                coluna_moeda("Total", lambda linha: linha.atualizacao.total, negrito=True),
            ]
        )
        self.modelo.definir_itens(self.linhas)
        tabela = preparar_tabela(QTableView(), esticar=0)
        tabela.setModel(self.modelo)
        ajustar_colunas(tabela, self.modelo.colunas)
        layout.addWidget(tabela, 1)

        formulario = QFormLayout()
        self.total_original = Rotulo("—")
        formulario.addRow("Total em aberto:", self.total_original)
        self.desconto = CampoMoeda(0)
        self.desconto.valueChanged.connect(self._recalcular)
        formulario.addRow("Desconto concedido:", self.desconto)
        self.valor_acordado = CampoMoeda(0)
        self.valor_acordado.valueChanged.connect(self._recalcular)
        formulario.addRow("Valor acordado:", self.valor_acordado)
        self.parcelas = QSpinBox()
        self.parcelas.setRange(1, 36)
        self.parcelas.valueChanged.connect(self._recalcular)
        formulario.addRow("Parcelas:", self.parcelas)
        self.primeiro_vencimento = CampoData(hoje())
        formulario.addRow("1º vencimento:", self.primeiro_vencimento)
        from ...servicos import tipos as servico_tipos

        self.tipo = ComboRegistros(
            servico_tipos.listar_tipos(self.contexto.sessao),
            rotulo=lambda t: t.nome,
            vazio="— selecione o tipo das parcelas —",
        )
        padrao = next(
            (
                tipo
                for tipo in servico_tipos.listar_tipos(self.contexto.sessao)
                if tipo.nome == "Parcela de acordo"
            ),
            None,
        )
        if padrao is not None:
            self.tipo.definir(padrao.id)
        formulario.addRow("Tipo das parcelas:", self.tipo)
        self.observacoes = QPlainTextEdit()
        self.observacoes.setMaximumHeight(60)
        formulario.addRow("Observações:", self.observacoes)
        layout.addLayout(formulario)

        self.resumo = widgets.rotulo_fraco("")
        layout.addWidget(self.resumo)

        acoes = QHBoxLayout()
        acoes.addStretch(1)
        cancelar = widgets.QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        confirmar = widgets.QPushButton("Fechar acordo")
        confirmar.setObjectName("primario")
        confirmar.clicked.connect(self._confirmar)
        acoes.addWidget(cancelar)
        acoes.addWidget(confirmar)
        layout.addLayout(acoes)

    def _total(self) -> Decimal:
        return sum(
            (linha.atualizacao.total for linha in self.linhas), start=Decimal("0.00")
        )

    def _recalcular(self) -> None:
        total = self._total()
        self.total_original.setText(formatar_moeda(total))
        if self.valor_acordado.valor() == 0:
            self.valor_acordado.definir(total - self.desconto.valor())
        parcela = (
            self.valor_acordado.valor() / self.parcelas.value()
            if self.parcelas.value()
            else Decimal(0)
        )
        self.resumo.setText(
            f"{self.parcelas.value()} parcela(s) de aproximadamente "
            f"{formatar_moeda(parcela)}. Os honorários originais ficam marcados como "
            "Renegociado e saem das filas de cobrança."
        )

    def _confirmar(self) -> None:
        if self.tipo.valor() is None:
            widgets.aviso(self, "Escolha o tipo de honorário das parcelas do acordo.")
            return
        if not widgets.confirmar(
            self,
            f"Fechar acordo de {formatar_moeda(self.valor_acordado.valor())} "
            f"em {self.parcelas.value()} parcela(s)?",
            "Renegociação",
            f"{len(self.linhas)} honorário(s) passam para Renegociado.",
        ):
            return

        def acao():
            renegociacoes.criar(
                self.contexto.sessao,
                cliente=self.cliente,
                linhas=self.linhas,
                valor_acordado=self.valor_acordado.valor(),
                desconto=self.desconto.valor(),
                parcelas=self.parcelas.value(),
                primeiro_vencimento=self.primeiro_vencimento.valor(),
                tipo_id=self.tipo.valor(),
                observacoes=self.observacoes.toPlainText(),
            )
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.accept()
