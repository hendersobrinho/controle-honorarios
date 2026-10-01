"""Lista de clientes: cadastro, juros e cobrança. Abas: ativos, só de Imposto de
Renda e inativos.

A dívida não aparece aqui: em aberto, atraso e totais têm as telas de cobrança.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QRadioButton,
    QTabBar,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...dominio.enums import TipoPessoa
from ...dominio.valores import formatar_documento
from ...servicos import clientes as servico
from ..comum import cores, widgets
from ..comum.campos import CampoBusca
from ..comum.tabelas import (
    Coluna,
    ModeloTabela,
    ajustar_colunas,
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
        self.so_ir: set[int] = set()
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

        self.abas = QTabBar()
        self.abas.setExpanding(False)
        self.abas.setDrawBase(False)
        self.abas.addTab("Ativos")
        self.abas.addTab("Imposto de Renda")
        self.abas.addTab("Inativos")
        self.abas.setTabToolTip(
            1, "Clientes que só têm honorário de Imposto de Renda. A cobrança deles fica "
            "na tela Imposto de Renda."
        )
        self.abas.setTabToolTip(
            2, "Clientes marcados como inativos no cadastro. Ficam fora da lista principal."
        )
        self.abas.currentChanged.connect(lambda *_: self.recarregar())
        layout.addWidget(self.abas)

        filtros = QHBoxLayout()
        self.grupo_tipo = QButtonGroup(self)
        for indice, rotulo in enumerate(("Todos", "PF", "PJ")):
            botao = QRadioButton(rotulo)
            botao.setChecked(indice == 0)
            self.grupo_tipo.addButton(botao, indice)
            filtros.addWidget(botao)
        self.grupo_tipo.idToggled.connect(lambda *_: self.recarregar())
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
        from ...servicos import honorarios as servico_honorarios

        self.so_ir = servico_honorarios.clientes_so_imposto_de_renda(self.contexto.sessao)
        indice = self.grupo_tipo.checkedId()
        tipo = {1: TipoPessoa.PF, 2: TipoPessoa.PJ}.get(indice)
        filtro = dict(
            termo=self.busca.text(),
            tipo_pessoa=tipo,
            data_referencia=self.contexto.data_referencia,
            com_totais=False,
        )
        nao_inativos = servico.listar(self.contexto.sessao, inativos=False, **filtro)
        # quem só tem IR fica na aba dele; inativo vai para Inativos, seja IR ou não
        ativos = [linha for linha in nao_inativos if linha.cliente.id not in self.so_ir]
        so_ir = [linha for linha in nao_inativos if linha.cliente.id in self.so_ir]
        inativos = servico.listar(self.contexto.sessao, inativos=True, **filtro)
        self.abas.setTabText(0, f"Ativos ({len(ativos)})")
        self.abas.setTabText(1, f"Imposto de Renda ({len(so_ir)})")
        self.abas.setTabText(2, f"Inativos ({len(inativos)})")
        aba = self.abas.currentIndex()
        linhas = (ativos, so_ir, inativos)[aba]
        self.modelo.definir_itens(linhas)
        ajustar_colunas(self.tabela, self.modelo.colunas)
        if aba == 2:
            self.resumo.setText(
                f"{len(linhas)} cliente(s) inativo(s). Para reativar, edite o cadastro e "
                "mude a situação."
            )
            return
        suspensos = sum(1 for linha in linhas if linha.cobranca_suspensa)
        partes = [
            f"{len(linhas)} cliente(s) ativo(s)" if aba == 0
            else f"{len(linhas)} cliente(s) só de Imposto de Renda — a cobrança deles fica "
            "na tela Imposto de Renda"
        ]
        if suspensos:
            partes.append(f"{suspensos} com cobrança suspensa")
        self.resumo.setText(" · ".join(partes))

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
