"""Honorários avulsos: IRPF, alteração contratual, atas e afins."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QTableView, QVBoxLayout, QWidget

from ...dominio.enums import Periodicidade, StatusPagamento
from ...dominio.valores import formatar_moeda
from ...servicos import honorarios as servico
from ...servicos import tipos as servico_tipos
from ...servicos.honorarios import Filtro
from ..comum import widgets
from ..comum.campos import CampoBusca, ComboEnum, ComboRegistros
from ..comum.tabelas import ModeloTabela, ajustar_colunas, item_atual, preparar_tabela
from ..contexto import Contexto
from ..dialogos.cobrar import DialogoCobrar
from ..dialogos.ficha import colunas_honorario
from ..dialogos.honorario import DialogoHonorario
from ..dialogos.pagamento import DialogoPagamento


class PainelAvulsos(QWidget):
    titulo = "Honorários avulsos"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self._montar()
        self.recarregar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self.cabecalho = widgets.Cabecalho(
            "Honorários avulsos", "Lançamentos que não vêm de contrato recorrente"
        )
        self.cabecalho.adicionar_botao(
            "Novo lançamento", self._novo, primario=True, atalho="Ctrl+N"
        )
        self.cabecalho.adicionar_botao("Editar", self._editar)
        self.cabecalho.adicionar_botao("Registrar pagamento", self._pagar, atalho="Ctrl+P")
        self.cabecalho.adicionar_botao("Cobrar", self._cobrar, atalho="Ctrl+B")
        self.cabecalho.adicionar_botao("Atualizar", self.recarregar, atalho="F5")
        layout.addWidget(self.cabecalho)

        filtros = QHBoxLayout()
        self.tipo = ComboRegistros(
            [
                tipo
                for tipo in servico_tipos.listar_tipos(self.contexto.sessao)
                if tipo.periodicidade is Periodicidade.AVULSO
                or tipo.grupo.nome == "Imposto de Renda"
            ],
            rotulo=lambda t: t.nome,
            vazio="Todos os tipos avulsos",
        )
        self.tipo.currentIndexChanged.connect(lambda *_: self.recarregar())
        filtros.addWidget(widgets.rotulo_fraco("Tipo:"))
        filtros.addWidget(self.tipo)
        self.status = ComboEnum(StatusPagamento, StatusPagamento.EM_ABERTO)
        self.status.insertItem(0, "Todos os status", None)
        self.status.setCurrentIndex(1)
        self.status.currentIndexChanged.connect(lambda *_: self.recarregar())
        filtros.addWidget(widgets.rotulo_fraco("Status:"))
        filtros.addWidget(self.status)
        filtros.addStretch(1)
        self.busca = CampoBusca("Buscar cliente…")
        self.busca.setMinimumWidth(240)
        self.busca.buscou.connect(lambda *_: self.recarregar())
        filtros.addWidget(self.busca)
        layout.addLayout(filtros)

        self.modelo = ModeloTabela(
            [
                widgets_coluna_cliente(),
                *colunas_honorario(),
            ]
        )
        self.tabela = preparar_tabela(QTableView(), esticar=0)
        self.tabela.setModel(self.modelo)
        self.tabela.doubleClicked.connect(lambda *_: self._editar())
        layout.addWidget(self.tabela, 1)

        self.resumo = widgets.rotulo_fraco("")
        layout.addWidget(self.resumo)

    def recarregar(self) -> None:
        self.contexto.atualizar()
        avulsos = [
            tipo.id
            for tipo in servico_tipos.listar_tipos(self.contexto.sessao, somente_ativos=False)
            if tipo.periodicidade is Periodicidade.AVULSO or tipo.grupo.nome == "Imposto de Renda"
        ]
        filtro = Filtro(
            termo=self.busca.text(),
            status=self.status.currentData(),
            tipo_id=self.tipo.valor(),
            data_referencia=self.contexto.data_referencia,
        )
        linhas = [
            linha
            for linha in servico.consultar(self.contexto.sessao, filtro)
            if linha.honorario.tipo_id in avulsos
        ]
        self.modelo.definir_itens(linhas)
        ajustar_colunas(self.tabela, self.modelo.colunas)
        self.resumo.setText(
            f"{len(linhas)} lançamento(s) · total {formatar_moeda(servico.total_de(linhas))}"
        )

    def _selecionada(self):
        linha = item_atual(self.tabela)
        if linha is None:
            widgets.aviso(self, "Selecione um lançamento.")
        return linha

    def _novo(self) -> None:
        if DialogoHonorario(self.contexto, parent=self).exec():
            self.recarregar()

    def _editar(self) -> None:
        linha = self._selecionada()
        if linha and DialogoHonorario(
            self.contexto, honorario=linha.honorario, parent=self
        ).exec():
            self.recarregar()

    def _pagar(self) -> None:
        linha = self._selecionada()
        if linha and DialogoPagamento(self.contexto, linha.honorario, self).exec():
            self.recarregar()

    def _cobrar(self) -> None:
        linha = self._selecionada()
        if linha is None:
            return
        if not linha.honorario.status.cobravel:
            widgets.aviso(self, f"{linha.honorario.status.rotulo} não entra em cobrança.")
            return
        dialogo = DialogoCobrar(self.contexto, linha.cliente, [linha], self)
        dialogo.exec()
        if dialogo.registrou:
            self.recarregar()


def widgets_coluna_cliente():
    from ..comum.tabelas import Coluna

    return Coluna("Cliente", lambda linha: f"{linha.cliente.codigo} – {linha.cliente.nome}")
