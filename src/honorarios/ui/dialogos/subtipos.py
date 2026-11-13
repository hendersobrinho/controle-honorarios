"""Subtipos do cliente pessoa física (Doméstica…): o campo de escolha do cadastro
e a janelinha para criar, renomear e desativar."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...servicos import subtipos as servico
from ..comum import widgets
from ..comum.tabelas import Coluna, ModeloTabela, ajustar_colunas, item_atual, preparar_tabela
from ..contexto import Contexto

SEM_SUBTIPO_ROTULO = "—  (nenhum)"


class CampoSubtipo(QWidget):
    """A lista dos subtipos ativos e, ao lado, o botão Subtipos… para cuidar dela."""

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        linha = QHBoxLayout(self)
        linha.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox()
        linha.addWidget(self.combo, 1)
        self.botao = widgets.QPushButton("Subtipos…")
        self.botao.setToolTip("Criar, renomear ou desativar subtipos (Doméstica, …)")
        self.botao.clicked.connect(self._gerenciar)
        linha.addWidget(self.botao)
        self._preencher()

    def _preencher(self, escolhido: str | None = None) -> None:
        atual = self.valor() if escolhido is None else escolhido
        self.combo.clear()
        self.combo.addItem(SEM_SUBTIPO_ROTULO, servico.SEM_SUBTIPO)
        for subtipo in servico.listar(self.contexto.sessao):
            self.combo.addItem(subtipo.nome, subtipo.nome)
        self.definir(atual)

    def valor(self) -> str:
        return self.combo.currentData() or servico.SEM_SUBTIPO

    def definir(self, nome: str | None) -> None:
        nome = nome or servico.SEM_SUBTIPO
        indice = self.combo.findData(nome)
        if indice < 0:
            # desativado, mas é o deste cliente: continua aparecendo para ele
            self.combo.addItem(f"{nome} (inativo)", nome)
            indice = self.combo.count() - 1
        self.combo.setCurrentIndex(indice)

    def setEnabled(self, ativo: bool) -> None:  # noqa: N802 (nome do Qt)
        self.combo.setEnabled(ativo)

    def _gerenciar(self) -> None:
        dialogo = DialogoSubtipos(self.contexto, self)
        dialogo.exec()
        # o recém-criado já vem escolhido; um renomeado continua escolhido
        escolhido = dialogo.criado or dialogo.renomeados.get(self.valor(), self.valor())
        self._preencher(escolhido)


class DialogoSubtipos(QDialog):
    """Criar, renomear e ativar/desativar subtipos, com quantos clientes usam cada."""

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.uso: dict[str, int] = {}
        self.criado: str | None = None
        self.renomeados: dict[str, str] = {}
        self.setWindowTitle("Subtipos de cliente")
        self.resize(560, 420)

        layout = QVBoxLayout(self)
        self.cabecalho = widgets.Cabecalho(
            "Subtipos de cliente", "Para separar as pessoas físicas: Doméstica, …")
        self.cabecalho.adicionar_botao("Novo subtipo", self._novo, primario=True)
        self.cabecalho.adicionar_botao("Renomear", self._renomear)
        self.cabecalho.adicionar_botao("Ativar / desativar", self._alternar)
        layout.addWidget(self.cabecalho)
        self.modelo = ModeloTabela([
            Coluna("Subtipo", lambda s: s.nome),
            Coluna("Clientes", lambda s: str(self.uso.get(s.nome) or "—"),
                   alinhamento=Qt.AlignmentFlag.AlignCenter),
            Coluna("Situação", lambda s: "Ativo" if s.ativo else "Inativo",
                   alinhamento=Qt.AlignmentFlag.AlignCenter),
        ])
        self.tabela = preparar_tabela(QTableView(), esticar=0)
        self.tabela.setModel(self.modelo)
        self.tabela.doubleClicked.connect(lambda *_: self._renomear())
        layout.addWidget(self.tabela, 1)
        layout.addWidget(widgets.rotulo_fraco(
            "Renomear muda o nome em todos os clientes que usam o subtipo. Inativo some "
            "da escolha, mas quem já tem continua com ele."))
        fechar = widgets.QPushButton("Fechar")
        fechar.clicked.connect(self.accept)
        rodape = QHBoxLayout()
        rodape.addStretch(1)
        rodape.addWidget(fechar)
        layout.addLayout(rodape)
        self.recarregar()

    def recarregar(self) -> None:
        sessao = self.contexto.sessao
        self.uso = servico.uso(sessao)
        self.modelo.definir_itens(servico.listar(sessao, somente_ativos=False))
        ajustar_colunas(self.tabela, self.modelo.colunas)

    def _selecionado(self):
        subtipo = item_atual(self.tabela)
        if subtipo is None:
            widgets.aviso(self, "Selecione um subtipo na lista.")
        return subtipo

    def _gravar(self, acao) -> bool:
        def tudo():
            acao()
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, tudo)
        if not deu_certo:
            self.contexto.desfazer()
        self.recarregar()
        return deu_certo

    def _novo(self) -> None:
        nome, confirmou = QInputDialog.getText(self, "Novo subtipo", "Nome do subtipo:")
        if not confirmou or not nome.strip():
            return
        criado = []
        if self._gravar(lambda: criado.append(servico.criar(self.contexto.sessao, nome))):
            self.criado = criado[0].nome

    def _renomear(self) -> None:
        subtipo = self._selecionado()
        if subtipo is None:
            return
        nome, confirmou = QInputDialog.getText(
            self, "Renomear subtipo", "Novo nome:", text=subtipo.nome)
        if not confirmou or not nome.strip():
            return
        antigo = subtipo.nome
        if self._gravar(lambda: servico.renomear(self.contexto.sessao, subtipo, nome)):
            self.renomeados[antigo] = subtipo.nome

    def _alternar(self) -> None:
        subtipo = self._selecionado()
        if subtipo is not None:
            self._gravar(lambda: servico.alternar(self.contexto.sessao, subtipo))
