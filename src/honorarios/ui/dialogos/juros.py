"""Alteração do juros ao dia, com aviso explícito de vigência."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QPlainTextEdit,
    QTableView,
    QVBoxLayout,
)

from ...dominio.valores import formatar_data, formatar_moeda, hoje
from ...servicos import clientes
from ..comum import widgets
from ..comum.campos import CampoData, CampoTaxa
from ..comum.tabelas import (
    Coluna,
    ModeloTabela,
    ajustar_colunas,
    coluna_data,
    preparar_tabela,
)
from ..contexto import Contexto


class DialogoJuros(QDialog):
    def __init__(self, contexto: Contexto, cliente, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.cliente = cliente
        self.setWindowTitle(f"Juros ao dia – {cliente.nome}")
        self.resize(620, 520)
        self._montar()
        self._recarregar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        atual = clientes.juros_atual(self.cliente)
        layout.addWidget(
            widgets.Cabecalho(
                "Juros ao dia",
                f"Vigente hoje: {formatar_moeda(atual)} por dia de atraso",
            )
        )

        formulario = QFormLayout()
        self.valor = CampoTaxa(atual)
        formulario.addRow("Novo valor:", self.valor)
        self.vigencia = CampoData(hoje())
        self.vigencia.dateChanged.connect(self._atualizar_aviso)
        formulario.addRow("Vale a partir de:", self.vigencia)
        self.motivo = QPlainTextEdit()
        self.motivo.setMaximumHeight(70)
        self.motivo.setPlaceholderText("Ex.: reajuste do boleto, correção de digitação…")
        formulario.addRow("Motivo:", self.motivo)
        layout.addLayout(formulario)

        self.aviso = widgets.rotulo_fraco("")
        layout.addWidget(self.aviso)
        self._atualizar_aviso()

        layout.addWidget(widgets.rotulo_fraco("Histórico de vigências"))
        self.modelo = ModeloTabela(
            [
                coluna_data("Vigência", lambda item: item.vigencia_inicio),
                Coluna(
                    "Valor anterior",
                    lambda item: formatar_moeda(item.valor_anterior)
                    if item.valor_anterior is not None
                    else "—",
                ),
                Coluna("Novo valor", lambda item: formatar_moeda(item.valor_dia), negrito=True),
                Coluna("Motivo", lambda item: item.motivo or "—"),
                Coluna("Registrado em", lambda item: formatar_data(item.registrado_em)),
            ]
        )
        self.tabela = preparar_tabela(QTableView(), esticar=3)
        self.tabela.setModel(self.modelo)
        layout.addWidget(self.tabela, 1)

        acoes = QHBoxLayout()
        acoes.addStretch(1)
        cancelar = widgets.QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        salvar = widgets.QPushButton("Salvar alteração")
        salvar.setObjectName("primario")
        salvar.clicked.connect(self._salvar)
        acoes.addWidget(cancelar)
        acoes.addWidget(salvar)
        layout.addLayout(acoes)

    def _atualizar_aviso(self) -> None:
        data = self.vigencia.valor()
        self.aviso.setText(
            f"O novo valor vale a partir de {formatar_data(data)}. "
            "Os juros já corridos antes dessa data continuam com o valor antigo."
        )

    def _recarregar(self) -> None:
        self.modelo.definir_itens(
            sorted(self.cliente.juros, key=lambda item: item.vigencia_inicio, reverse=True)
        )
        ajustar_colunas(self.tabela, self.modelo.colunas)

    def _salvar(self) -> None:
        def acao():
            clientes.registrar_juros(
                self.contexto.sessao,
                self.cliente,
                self.valor.valor(),
                self.vigencia.valor(),
                self.motivo.toPlainText().strip(),
            )
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.accept()
