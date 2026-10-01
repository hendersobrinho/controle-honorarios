"""Cadastro de cliente: dados, contatos e juros ao dia."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...dominio.enums import SituacaoCliente, SubtipoCliente, TipoPessoa
from ...dominio.valores import formatar_moeda, formatar_telefone
from ...servicos import clientes
from ..comum import widgets
from ..comum.campos import CampoDocumento, CampoTaxa, ComboEnum
from ..comum.seletor_cliente import CampoCliente
from ..contexto import Contexto

COLUNAS_CONTATO = ("Nome", "Como chamar", "WhatsApp", "E-mail", "Principal")


class DialogoCliente(QDialog):
    def __init__(self, contexto: Contexto, cliente=None, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.cliente = cliente
        self.setWindowTitle("Editar cliente" if cliente else "Novo cliente")
        self.resize(760, 640)
        self._montar()
        if cliente:
            self._carregar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)

        grupo = QGroupBox("Dados do cliente")
        formulario = QFormLayout(grupo)
        self.codigo = QLineEdit()
        self.codigo.setPlaceholderText("Código no sistema contábil")
        formulario.addRow("Código:", self.codigo)
        self.nome = QLineEdit()
        formulario.addRow("Nome / razão social:", self.nome)
        self.documento = CampoDocumento()
        formulario.addRow("CPF/CNPJ:", self.documento)
        self.tipo = ComboEnum(TipoPessoa, TipoPessoa.PJ)
        self.tipo.currentIndexChanged.connect(self._ajustar_subtipo)
        formulario.addRow("Tipo:", self.tipo)
        self.subtipo = ComboEnum(SubtipoCliente, SubtipoCliente.NENHUM)
        formulario.addRow("Subtipo:", self.subtipo)
        self.situacao = ComboEnum(SituacaoCliente, SituacaoCliente.ATIVO)
        formulario.addRow("Situação:", self.situacao)
        self.empresa = CampoCliente(
            self.contexto.sessao,
            tipo_pessoa=TipoPessoa.PJ,
            excluir_id=self.cliente.id if self.cliente else None,
            vazio="Em branco: cobra em nome próprio",
        )
        self.empresa.setToolTip(
            "Quando a pessoa física paga os honorários por uma empresa, a cobrança "
            "pode sair junto com a da empresa."
        )
        formulario.addRow("Paga pela empresa:", self.empresa)
        self.observacoes = QPlainTextEdit()
        self.observacoes.setMaximumHeight(70)
        formulario.addRow("Observações:", self.observacoes)
        layout.addWidget(grupo)

        grupo_juros = QGroupBox("Juros ao dia")
        caixa_juros = QVBoxLayout(grupo_juros)
        linha = QHBoxLayout()
        linha.addWidget(QLabel("Valor por dia de atraso:"))
        self.juros = CampoTaxa(Decimal("0.00"))
        linha.addWidget(self.juros)
        # no cliente já cadastrado o valor muda por aqui, com vigência e histórico
        self.botao_juros = widgets.QPushButton("Alterar juros ao dia…")
        self.botao_juros.setObjectName("primario")
        self.botao_juros.clicked.connect(self._alterar_juros)
        self.botao_juros.setVisible(False)
        linha.addWidget(self.botao_juros)
        linha.addStretch(1)
        caixa_juros.addLayout(linha)
        self.nota_juros = widgets.rotulo_fraco(
            "Obrigatório. Depois do cadastro, o valor muda pelo botão \"Alterar juros "
            "ao dia\", que guarda a data de vigência e o histórico."
        )
        caixa_juros.addWidget(self.nota_juros)
        layout.addWidget(grupo_juros)

        grupo_contatos = QGroupBox("Contatos")
        caixa = QVBoxLayout(grupo_contatos)
        self.contatos = QTableWidget(0, len(COLUNAS_CONTATO))
        self.contatos.setHorizontalHeaderLabels(COLUNAS_CONTATO)
        self.contatos.verticalHeader().setVisible(False)
        cabecalho = self.contatos.horizontalHeader()
        cabecalho.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        cabecalho.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        caixa.addWidget(self.contatos)
        botoes = QHBoxLayout()
        adicionar = widgets.QPushButton("Adicionar contato")
        adicionar.clicked.connect(lambda: self._nova_linha())
        remover = widgets.QPushButton("Remover selecionado")
        remover.clicked.connect(self._remover_linha)
        botoes.addWidget(adicionar)
        botoes.addWidget(remover)
        botoes.addStretch(1)
        botoes.addWidget(
            widgets.rotulo_fraco("\"Como chamar\" é o nome usado na saudação da mensagem.")
        )
        caixa.addLayout(botoes)
        layout.addWidget(grupo_contatos, 1)

        acoes = QHBoxLayout()
        acoes.addStretch(1)
        cancelar = widgets.QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        salvar = widgets.QPushButton("Salvar")
        salvar.setObjectName("primario")
        salvar.setShortcut("Ctrl+S")
        salvar.clicked.connect(self._salvar)
        acoes.addWidget(cancelar)
        acoes.addWidget(salvar)
        layout.addLayout(acoes)

    # ------------------------------------------------------------------ apoio
    def _ajustar_subtipo(self) -> None:
        so_pf = self.tipo.valor() is TipoPessoa.PF
        self.subtipo.setEnabled(so_pf)
        if not so_pf:
            self.subtipo.definir(SubtipoCliente.NENHUM)
        # o vínculo é de pessoa física para a empresa que paga por ela
        self.empresa.setEnabled(so_pf)
        if not so_pf:
            self.empresa.definir(None)

    def _nova_linha(self, contato=None) -> None:
        linha = self.contatos.rowCount()
        self.contatos.insertRow(linha)
        valores = [
            contato.nome if contato else "",
            contato.nome_tratamento if contato else "",
            formatar_telefone(contato.telefone) if contato else "",
            contato.email if contato else "",
        ]
        for coluna, valor in enumerate(valores):
            self.contatos.setItem(linha, coluna, QTableWidgetItem(valor))
        marca = QTableWidgetItem()
        marca.setFlags(
            Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
        )
        marcado = bool(contato.principal) if contato else self.contatos.rowCount() == 1
        marca.setCheckState(Qt.CheckState.Checked if marcado else Qt.CheckState.Unchecked)
        if contato is not None:
            marca.setData(Qt.ItemDataRole.UserRole, contato.id)
        self.contatos.setItem(linha, 4, marca)

    def _remover_linha(self) -> None:
        linha = self.contatos.currentRow()
        if linha >= 0:
            self.contatos.removeRow(linha)

    def _carregar(self) -> None:
        cliente = self.cliente
        self.codigo.setText(cliente.codigo)
        self.nome.setText(cliente.nome)
        self.documento.definir(cliente.documento)
        self.tipo.definir(cliente.tipo_pessoa)
        self.subtipo.definir(cliente.subtipo)
        self.situacao.definir(cliente.situacao)
        self.empresa.definir(cliente.empresa_id)
        self.observacoes.setPlainText(cliente.observacoes)
        self._mostrar_juros()
        for contato in cliente.contatos:
            self._nova_linha(contato)
        self._ajustar_subtipo()

    def _mostrar_juros(self) -> None:
        atual = clientes.juros_atual(self.cliente)
        self.juros.definir(atual)
        self.juros.setEnabled(False)
        self.botao_juros.setVisible(True)
        historico = len(self.cliente.juros)
        self.nota_juros.setText(
            f"Vigente hoje: {formatar_moeda(atual)} por dia · "
            f"{historico} registro(s) no histórico. A mudança vale a partir da data "
            "que você escolher, nunca para trás."
        )

    def _alterar_juros(self) -> None:
        from .juros import DialogoJuros

        if DialogoJuros(self.contexto, self.cliente, self).exec():
            self._mostrar_juros()

    def _texto(self, linha: int, coluna: int) -> str:
        item = self.contatos.item(linha, coluna)
        return item.text().strip() if item else ""

    def _dados(self) -> clientes.DadosCliente:
        contatos = []
        for linha in range(self.contatos.rowCount()):
            marca = self.contatos.item(linha, 4)
            contatos.append(
                clientes.DadosContato(
                    id=marca.data(Qt.ItemDataRole.UserRole) if marca else None,
                    nome=self._texto(linha, 0),
                    nome_tratamento=self._texto(linha, 1),
                    telefone=self._texto(linha, 2),
                    email=self._texto(linha, 3),
                    principal=bool(marca and marca.checkState() == Qt.CheckState.Checked),
                )
            )
        return clientes.DadosCliente(
            codigo=self.codigo.text(),
            nome=self.nome.text(),
            documento=self.documento.valor(),
            tipo_pessoa=self.tipo.valor(),
            subtipo=self.subtipo.valor(),
            situacao=self.situacao.valor(),
            observacoes=self.observacoes.toPlainText(),
            juros_dia=self.juros.valor() if self.cliente is None else None,
            contatos=contatos,
            empresa_id=self.empresa.valor(),
        )

    def _salvar(self) -> None:
        dados = self._dados()

        def acao():
            if self.cliente is None:
                self.cliente = clientes.criar(self.contexto.sessao, dados)
            else:
                clientes.atualizar(self.contexto.sessao, self.cliente, dados)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.accept()
