"""Cadastro de cliente: dados e juros ao dia, contatos e o honorário recorrente."""

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
    QTabWidget,
    QVBoxLayout,
    QWidget,
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
        self.resize(780, 660)
        self._montar()
        if cliente:
            self._carregar()
        self._ajustar_honorario()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        self.abas = QTabWidget()
        layout.addWidget(self.abas, 1)
        aba_dados = QWidget()
        dados_layout = QVBoxLayout(aba_dados)

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
            "O que a empresa paga já cobre esta pessoa: a geração da competência não "
            "cria honorário para ela. Se um dia precisar, lance um honorário à mão — "
            "e a cobrança dele pode sair junto com a da empresa."
        )
        formulario.addRow("Paga pela empresa:", self.empresa)
        self.observacoes = QPlainTextEdit()
        self.observacoes.setMaximumHeight(70)
        formulario.addRow("Observações:", self.observacoes)
        dados_layout.addWidget(grupo)

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
        dados_layout.addWidget(grupo_juros)
        dados_layout.addStretch(1)
        self.abas.addTab(aba_dados, "Dados")

        grupo_contatos = QWidget()
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
        self.abas.addTab(grupo_contatos, "Contatos")
        self.abas.addTab(self._aba_honorario(), "Honorário recorrente")
        self.empresa.mudou.connect(lambda *_: self._ajustar_honorario())

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

    # ------------------------------------------------------- honorário recorrente
    def _aba_honorario(self) -> QWidget:
        from .contrato import FormularioContrato

        pagina = QWidget()
        caixa = QVBoxLayout(pagina)
        self.aviso_honorario = QLabel()
        self.aviso_honorario.setObjectName("ajudaConta")
        self.aviso_honorario.setWordWrap(True)
        caixa.addWidget(self.aviso_honorario)
        if self.cliente is None:
            # cliente novo: o honorário recorrente nasce junto
            self.formulario_honorario = FormularioContrato(self.contexto)
            caixa.addWidget(self.formulario_honorario)
            caixa.addStretch(1)
        else:
            # já cadastrado: os honorários recorrentes dele, para cuidar daqui
            self.formulario_honorario = None
            self.tabela_contratos = QTableWidget(0, 5)
            self.tabela_contratos.setHorizontalHeaderLabels(
                ("Tipo", "Valor", "Periodicidade", "Vence dia", "Situação"))
            self.tabela_contratos.verticalHeader().setVisible(False)
            self.tabela_contratos.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            self.tabela_contratos.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
            self.tabela_contratos.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.tabela_contratos.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.ResizeMode.Stretch)
            self.tabela_contratos.doubleClicked.connect(lambda *_: self._editar_contrato())
            caixa.addWidget(self.tabela_contratos, 1)
            botoes = QHBoxLayout()
            self.botao_novo_contrato = widgets.QPushButton("Novo honorário recorrente…")
            self.botao_novo_contrato.setObjectName("primario")
            self.botao_novo_contrato.clicked.connect(self._novo_contrato)
            botoes.addWidget(self.botao_novo_contrato)
            for texto, funcao in (("Editar…", self._editar_contrato),
                                  ("Reajustar…", self._reajustar_contrato),
                                  ("Suspender / reativar", self._suspender_contrato)):
                botao = widgets.QPushButton(texto)
                botao.clicked.connect(funcao)
                botoes.addWidget(botao)
            botoes.addStretch(1)
            caixa.addLayout(botoes)
        return pagina

    def _paga_pela_empresa(self) -> bool:
        return self.empresa.valor() is not None

    def _ajustar_honorario(self) -> None:
        paga = self._paga_pela_empresa()
        if paga:
            self.aviso_honorario.setText(
                "<b>Paga pela empresa:</b> o que a empresa paga já cobre esta pessoa, então "
                "não precisa de honorário recorrente — o cadastro salva sem, e a geração "
                "da competência não cria honorário para ela. Se um dia precisar, lance "
                "um honorário à mão."
            )
        elif self.cliente is None:
            self.aviso_honorario.setText(
                "O honorário que se repete (mensal, trimestral…). Preenchido, ele já gera "
                "a partir da vigência. Cliente só de IR ou de serviços avulsos pode ficar "
                "sem — o sistema pergunta antes de salvar."
            )
        else:
            self.aviso_honorario.setText(
                "Os honorários que se repetem para este cliente. Mudança de valor é "
                "reajuste (guarda o histórico e vale daqui para frente)."
            )
        if self.formulario_honorario is not None:
            self.formulario_honorario.setEnabled(not paga)
        else:
            self.botao_novo_contrato.setEnabled(not paga)

    def _contratos(self):
        from ...servicos import contratos

        return contratos.listar(self.contexto.sessao, cliente_id=self.cliente.id)

    def _mostrar_contratos(self) -> None:
        if self.cliente is None:
            return
        self.contratos_listados = self._contratos()
        self.tabela_contratos.setRowCount(len(self.contratos_listados))
        for linha, contrato in enumerate(self.contratos_listados):
            textos = (contrato.tipo.nome, formatar_moeda(contrato.valor),
                      contrato.periodicidade.rotulo, str(contrato.dia_vencimento),
                      "Suspenso" if contrato.suspenso else "Ativo")
            for coluna, texto in enumerate(textos):
                self.tabela_contratos.setItem(linha, coluna, QTableWidgetItem(texto))

    def _contrato_selecionado(self):
        linhas = self.tabela_contratos.selectionModel().selectedRows()
        if not linhas:
            widgets.aviso(self, "Selecione um honorário recorrente.")
            return None
        return self.contratos_listados[linhas[0].row()]

    def _novo_contrato(self) -> None:
        from .contrato import DialogoContrato

        if DialogoContrato(self.contexto, parent=self, cliente_id=self.cliente.id).exec():
            self._mostrar_contratos()

    def _editar_contrato(self) -> None:
        from .contrato import DialogoContrato

        contrato = self._contrato_selecionado()
        if contrato and DialogoContrato(self.contexto, contrato, parent=self).exec():
            self._mostrar_contratos()

    def _reajustar_contrato(self) -> None:
        from .contrato import DialogoReajuste

        contrato = self._contrato_selecionado()
        if contrato and DialogoReajuste(self.contexto, contrato, parent=self).exec():
            self._mostrar_contratos()

    def _suspender_contrato(self) -> None:
        from ...servicos import contratos

        contrato = self._contrato_selecionado()
        if contrato is None:
            return

        def acao():
            contratos.suspender(self.contexto.sessao, contrato, not contrato.suspenso)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if deu_certo:
            self._mostrar_contratos()

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
        if hasattr(self, "aviso_honorario"):
            self._ajustar_honorario()

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
        self._mostrar_contratos()

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
        from ...servicos import contratos

        dados = self._dados()
        novo = self.cliente is None
        com_honorario = (novo and not self._paga_pela_empresa()
                         and self.formulario_honorario.preenchido())
        # primeiro os dados do cliente: não adianta perguntar do honorário com o CNPJ errado
        deu_certo, _ = widgets.executar(
            self, lambda: clientes.validar(self.contexto.sessao, dados,
                                           None if novo else self.cliente.id))
        if not deu_certo:
            return
        if novo and not self._paga_pela_empresa() and not com_honorario and not \
                widgets.confirmar(
                    self, "Salvar o cliente sem honorário recorrente?", "Sem honorário",
                    "Serve para quem é só de Imposto de Renda ou de serviços avulsos. Se ele "
                    "paga por outra empresa, preencha \"Paga pela empresa\" na aba Dados. "
                    "Dá para cadastrar o honorário depois, no cadastro do cliente.",
                    acao="Salvar sem honorário"):
            self.abas.setCurrentIndex(self.abas.count() - 1)
            return

        def acao():
            if self.cliente is None:
                self.cliente = clientes.criar(self.contexto.sessao, dados)
                if com_honorario:
                    contratos.criar(self.contexto.sessao,
                                    self.formulario_honorario.dados(self.cliente.id))
            else:
                clientes.atualizar(self.contexto.sessao, self.cliente, dados)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            if novo:   # nada foi gravado: continua como cliente novo
                self.cliente = None
            return
        self.accept()
