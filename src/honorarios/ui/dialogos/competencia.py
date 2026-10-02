"""Geração de competência em lote, sempre com prévia antes de confirmar."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QSpinBox,
    QTableView,
    QVBoxLayout,
)

from ...dominio.valores import MESES_ABREVIADOS, Competencia, formatar_moeda, hoje
from ...servicos import contratos as servico
from ..comum import widgets
from ..comum.tabelas import (
    Coluna,
    ModeloTabelaMarcavel,
    ajustar_colunas,
    coluna_data,
    coluna_moeda,
    preparar_tabela,
)
from ..contexto import Contexto


class DialogoGerarCompetencia(QDialog):
    def __init__(self, contexto: Contexto, parent=None, ano: int | None = None,
                 mes: int | None = None) -> None:
        """``ano``/``mes``: a competência já escolhida (ex.: a que está na tela Mês a mês)."""
        super().__init__(parent)
        self.contexto = contexto
        self.gerados = 0
        self._competencia_inicial = (ano, mes)
        self.setWindowTitle("Gerar competência")
        self.resize(900, 620)
        self._montar()
        self._carregar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(
            widgets.Cabecalho(
                "Gerar competência",
                "Cria os honorários do mês a partir dos contratos recorrentes",
            )
        )

        seletor = QHBoxLayout()
        hoje_ = hoje()
        self.mes = QComboBox()
        for indice, nome in enumerate(MESES_ABREVIADOS, start=1):
            self.mes.addItem(nome, indice)
        ano_inicial, mes_inicial = self._competencia_inicial
        self.mes.setCurrentIndex((mes_inicial or hoje_.month) - 1)
        self.mes.currentIndexChanged.connect(self._carregar)
        self.ano = QSpinBox()
        self.ano.setRange(2000, 2100)
        self.ano.setValue(ano_inicial or hoje_.year)
        self.ano.valueChanged.connect(self._carregar)
        seletor.addWidget(widgets.rotulo_fraco("Competência:"))
        seletor.addWidget(self.mes)
        seletor.addWidget(self.ano)
        seletor.addStretch(1)
        marcar = widgets.QPushButton("Marcar todos")
        marcar.clicked.connect(lambda: (self.modelo.marcar_todos(True), self._resumir()))
        desmarcar = widgets.QPushButton("Desmarcar todos")
        desmarcar.clicked.connect(lambda: (self.modelo.marcar_todos(False), self._resumir()))
        seletor.addWidget(marcar)
        seletor.addWidget(desmarcar)
        layout.addLayout(seletor)

        self.modelo = ModeloTabelaMarcavel(
            [
                Coluna("", lambda item: "", largura=28),
                Coluna("Cliente", lambda item: f"{item.cliente.codigo} – {item.cliente.nome}"),
                Coluna("Tipo", lambda item: item.contrato.tipo.nome),
                Coluna(
                    "Periodicidade",
                    lambda item: item.contrato.periodicidade.rotulo,
                    alinhamento=Qt.AlignmentFlag.AlignCenter,
                ),
                coluna_moeda("Valor", lambda item: item.valor),
                coluna_data("Vencimento", lambda item: item.vencimento),
                Coluna(
                    "Situação",
                    lambda item: item.impedimento or "Será gerado",
                    dica=lambda item: item.impedimento,
                ),
            ]
        )
        self.modelo.definir_bloqueio(lambda item: bool(item.impedimento))
        self.modelo.dataChanged.connect(lambda *_: self._resumir())
        self.tabela = preparar_tabela(QTableView(), esticar=1)
        self.tabela.setModel(self.modelo)
        self.tabela.setSortingEnabled(False)
        layout.addWidget(self.tabela, 1)

        self.resumo = widgets.rotulo_fraco("")
        layout.addWidget(self.resumo)

        acoes = QHBoxLayout()
        acoes.addStretch(1)
        fechar = widgets.QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        gerar = widgets.QPushButton("Gerar selecionados")
        gerar.setObjectName("primario")
        gerar.clicked.connect(self._gerar)
        acoes.addWidget(fechar)
        acoes.addWidget(gerar)
        layout.addLayout(acoes)

    def _competencia(self) -> Competencia:
        return Competencia(ano=self.ano.value(), mes=self.mes.currentData())

    def _carregar(self) -> None:
        def acao():
            return servico.previa_geracao(self.contexto.sessao, self._competencia())

        deu_certo, itens = widgets.executar(self, acao)
        self.modelo.definir_itens(itens or [])
        ajustar_colunas(self.tabela, self.modelo.colunas)
        self._resumir()

    def _resumir(self) -> None:
        marcados = [item for item in self.modelo.marcados() if item.gerar]
        total = sum((item.valor for item in marcados), start=Decimal("0.00"))
        bloqueados = sum(1 for item in self.modelo.itens if item.impedimento)
        self.resumo.setText(
            f"{len(marcados)} honorário(s) a gerar · total {formatar_moeda(total)} · "
            f"{bloqueados} fora (já lançados, suspensos ou fora da periodicidade)"
        )

    def _gerar(self) -> None:
        marcados = [item for item in self.modelo.marcados() if item.gerar]
        if not marcados:
            widgets.aviso(self, "Nenhum contrato marcado para gerar.")
            return
        total = sum((item.valor for item in marcados), start=Decimal("0.00"))
        competencia = self._competencia()
        if not widgets.confirmar(
            self,
            f"Gerar {len(marcados)} honorário(s) da competência {competencia.rotulo()}?",
            "Gerar competência",
            f"Total emitido: {formatar_moeda(total)}.",
        ):
            return

        def acao():
            criados = servico.gerar(self.contexto.sessao, marcados)
            self.contexto.salvar()
            return criados

        deu_certo, criados = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.gerados += len(criados or [])
        widgets.informar(
            self,
            f"{len(criados or [])} honorário(s) gerado(s) na competência "
            f"{competencia.rotulo()}.",
            "Competência gerada",
        )
        self._carregar()
