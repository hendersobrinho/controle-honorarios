"""Lista de clientes com alternância PF | PJ | Todos e totais em aberto."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QRadioButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...dominio.enums import SituacaoCliente, TipoPessoa
from ...dominio.valores import ZERO, formatar_documento, formatar_moeda
from ...servicos import clientes as servico
from ..comum import cores, widgets
from ..comum.campos import CampoBusca, ComboEnum
from ..comum.tabelas import (
    Coluna,
    ModeloTabela,
    ajustar_colunas,
    coluna_inteiro,
    coluna_moeda,
    item_atual,
    preparar_tabela,
)
from ..contexto import Contexto
from ..dialogos.cliente import DialogoCliente
from ..dialogos.exportar import exportar_extrato
from ..dialogos.ficha import DialogoFicha
from ..dialogos.juros import DialogoJuros


class PainelClientes(QWidget):
    titulo = "Clientes"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self._montar()
        self.recarregar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self.cabecalho = widgets.Cabecalho("Clientes", "Pessoas físicas, jurídicas e domésticas")
        self.cabecalho.adicionar_botao("Novo cliente", self._novo, primario=True, atalho="Ctrl+N")
        self.cabecalho.adicionar_botao("Editar", self._editar)
        self.cabecalho.adicionar_botao("Juros ao dia", self._juros)
        self.cabecalho.adicionar_botao("Suspender / retomar", self._alternar_suspensao)
        self.cabecalho.adicionar_botao("Ficha", self._ficha, atalho="Ctrl+F")
        self.cabecalho.adicionar_botao("Atualizar", self.recarregar, atalho="F5")
        layout.addWidget(self.cabecalho)

        filtros = QHBoxLayout()
        self.grupo_tipo = QButtonGroup(self)
        for indice, rotulo in enumerate(("Todos", "PF", "PJ")):
            botao = QRadioButton(rotulo)
            botao.setChecked(indice == 0)
            self.grupo_tipo.addButton(botao, indice)
            filtros.addWidget(botao)
        self.grupo_tipo.idToggled.connect(lambda *_: self.recarregar())
        filtros.addSpacing(16)
        self.situacao = ComboEnum(SituacaoCliente)
        self.situacao.insertItem(0, "Qualquer situação", None)
        self.situacao.setCurrentIndex(0)
        self.situacao.currentIndexChanged.connect(lambda *_: self.recarregar())
        filtros.addWidget(self.situacao)
        self.com_debito = QCheckBox("Só com débito em aberto")
        self.com_debito.toggled.connect(lambda *_: self.recarregar())
        filtros.addWidget(self.com_debito)
        filtros.addStretch(1)
        self.busca = CampoBusca("Nome, código ou CPF/CNPJ…")
        self.busca.setMinimumWidth(280)
        self.busca.buscou.connect(lambda *_: self.recarregar())
        filtros.addWidget(self.busca)
        layout.addLayout(filtros)

        self.modelo = ModeloTabela(
            [
                Coluna("Código", lambda item: item.cliente.codigo,
                       alinhamento=Qt.AlignmentFlag.AlignCenter),
                Coluna("Nome / razão social", lambda item: item.cliente.nome),
                Coluna("CPF/CNPJ", lambda item: formatar_documento(item.cliente.documento) or "—"),
                Coluna("Tipo", lambda item: item.cliente.tipo_pessoa.value,
                       alinhamento=Qt.AlignmentFlag.AlignCenter),
                Coluna("Situação", lambda item: item.cliente.situacao.rotulo,
                       alinhamento=Qt.AlignmentFlag.AlignCenter),
                Coluna(
                    "Cobrança",
                    lambda item: "Suspensa" if item.cobranca_suspensa else "Ativa",
                    alinhamento=Qt.AlignmentFlag.AlignCenter,
                    cor=lambda item: (
                        cores.tema.cor("atencao", cores.tema_atual())
                        if item.cobranca_suspensa
                        else None
                    ),
                    dica=lambda item: servico.suspensao(item.cliente),
                ),
                Coluna(
                    "Paga pela empresa",
                    lambda item: item.cliente.empresa.nome if item.cliente.empresa else "—",
                ),
                coluna_moeda("Juros/dia", lambda item: item.juros_dia),
                coluna_inteiro("Em aberto", lambda item: item.quantidade_em_aberto),
                coluna_moeda("Total atualizado", lambda item: item.total_em_aberto, negrito=True),
                coluna_inteiro(
                    "Maior atraso",
                    lambda item: item.maior_atraso,
                    cor=lambda item: cores.cor_de_atraso(item.maior_atraso),
                ),
            ]
        )
        self.tabela = preparar_tabela(QTableView(), esticar=1)
        self.tabela.setModel(self.modelo)
        self.tabela.doubleClicked.connect(lambda *_: self._ficha())
        layout.addWidget(self.tabela, 1)

        rodape = QHBoxLayout()
        self.resumo = widgets.rotulo_fraco("")
        rodape.addWidget(self.resumo, 1)
        extrato = widgets.QPushButton("Extrato de débitos em PDF")
        extrato.clicked.connect(self._extrato)
        excluir = widgets.QPushButton("Excluir cliente")
        excluir.clicked.connect(self._excluir)
        rodape.addWidget(extrato)
        rodape.addWidget(excluir)
        layout.addLayout(rodape)

    # ------------------------------------------------------------------ dados
    def recarregar(self) -> None:
        self.contexto.atualizar()
        indice = self.grupo_tipo.checkedId()
        tipo = {1: TipoPessoa.PF, 2: TipoPessoa.PJ}.get(indice)
        linhas = servico.listar(
            self.contexto.sessao,
            termo=self.busca.text(),
            tipo_pessoa=tipo,
            situacao=self.situacao.currentData(),
            somente_com_debito=self.com_debito.isChecked(),
            data_referencia=self.contexto.data_referencia,
        )
        self.modelo.definir_itens(linhas)
        ajustar_colunas(self.tabela, self.modelo.colunas)
        total = sum((linha.total_em_aberto for linha in linhas), start=ZERO)
        com_debito = sum(1 for linha in linhas if linha.quantidade_em_aberto)
        suspensos = sum(1 for linha in linhas if linha.cobranca_suspensa)
        parte = f" · {suspensos} com cobrança suspensa" if suspensos else ""
        self.resumo.setText(
            f"{len(linhas)} cliente(s) · {com_debito} com débito · "
            f"total em aberto {formatar_moeda(total)}{parte}"
        )

    def _selecionado(self):
        linha = item_atual(self.tabela)
        if linha is None:
            widgets.aviso(self, "Selecione um cliente na lista.")
            return None
        return linha.cliente

    # ------------------------------------------------------------------ ações
    def _novo(self) -> None:
        if DialogoCliente(self.contexto, parent=self).exec():
            self.recarregar()

    def _editar(self) -> None:
        cliente = self._selecionado()
        if cliente and DialogoCliente(self.contexto, cliente, parent=self).exec():
            self.recarregar()

    def _juros(self) -> None:
        cliente = self._selecionado()
        if cliente and DialogoJuros(self.contexto, cliente, parent=self).exec():
            self.recarregar()

    def _alternar_suspensao(self) -> None:
        cliente = self._selecionado()
        if cliente is None:
            return
        from ..dialogos.suspensao import DialogoSuspensao, retomar

        if cliente.suspensao_ativa(self.contexto.data_referencia):
            if retomar(self, self.contexto, cliente):
                self.recarregar()
            return
        if DialogoSuspensao(self.contexto, cliente, self).exec():
            self.recarregar()

    def _ficha(self) -> None:
        cliente = self._selecionado()
        if cliente:
            DialogoFicha(self.contexto, cliente, self).exec()
            self.recarregar()

    def _extrato(self) -> None:
        cliente = self._selecionado()
        if cliente:
            exportar_extrato(self, self.contexto, cliente)

    def _excluir(self) -> None:
        cliente = self._selecionado()
        if cliente is None:
            return
        if not widgets.confirmar(
            self,
            f"Excluir {cliente.nome}?",
            "Excluir cliente",
            "A exclusão é lógica: o histórico continua consultável, mas o cliente "
            "sai das listas.",
        ):
            return

        def acao():
            servico.excluir(self.contexto.sessao, cliente, "Excluído pela tela de clientes")
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.recarregar()
