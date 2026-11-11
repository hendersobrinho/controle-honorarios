"""Painel do cliente: numa tela só, para ver e editar — dados e juros ao dia,
contatos e os honorários recorrentes (com a forma de envio de cada um)."""

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
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...dominio.enums import SituacaoCliente, SubtipoCliente, TipoPessoa
from ...dominio.valores import formatar_moeda, formatar_telefone
from ...servicos import clientes
from ..comum import widgets
from ..comum.campos import CampoDataOpcional, CampoDocumento, CampoTaxa, ComboEnum
from ..comum.seletor_cliente import CampoCliente
from ..contexto import Contexto

COLUNAS_CONTATO = ("Nome", "Como chamar", "WhatsApp", "E-mail", "Principal")
COLUNAS_CONTRATO = ("Tipo", "Valor", "Periodicidade", "Vence dia", "Forma de envio",
                    "Situação")


class DialogoCliente(QDialog):
    def __init__(self, contexto: Contexto, cliente=None, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.cliente = cliente
        self.setWindowTitle(f"Cliente – {cliente.nome}" if cliente else "Novo cliente")
        widgets.tamanho_na_tela(self, 1240, 800)
        self._montar()
        if cliente:
            self._carregar()
        self._ajustar_honorario()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        self.cabecalho = widgets.Cabecalho(
            self.cliente.nome if self.cliente else "Novo cliente",
            "Tudo do cliente numa tela: veja, edite e salve no fim",
        )
        if self.cliente is not None:
            self.cabecalho.adicionar_botao("Débitos e histórico (ficha)…", self._ficha)
        layout.addWidget(self.cabecalho)

        # duas colunas: à esquerda quem é o cliente; à direita com quem falar e o
        # que ele paga. Rola quando a tela é pequena.
        self.rolagem = QScrollArea()
        self.rolagem.setWidgetResizable(True)
        self.rolagem.setFrameShape(QScrollArea.Shape.NoFrame)
        corpo = QWidget()
        colunas = QHBoxLayout(corpo)
        colunas.setContentsMargins(0, 0, 0, 0)
        colunas.setSpacing(14)
        dados_layout = QVBoxLayout()
        direita = QVBoxLayout()
        colunas.addLayout(dados_layout, 5)
        colunas.addLayout(direita, 6)
        self.rolagem.setWidget(corpo)
        layout.addWidget(self.rolagem, 1)

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
        self.cliente_desde = CampoDataOpcional()
        self.cliente_desde.setToolTip(
            "Opcional. Quando a empresa virou cliente do escritório: o trimestre do "
            "honorário trimestral conta da competência desta data (tela Tarefas)."
        )
        formulario.addRow("Cliente do escritório desde:", self.cliente_desde)
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
        linha.addStretch(1)
        caixa_juros.addLayout(linha)
        self.nota_juros = widgets.rotulo_fraco(
            "Obrigatório. É o juros da empresa: vale para tudo o que está em aberto dela, "
            "e mudar aqui muda o de todos. Honorário já pago não muda."
        )
        caixa_juros.addWidget(self.nota_juros)
        dados_layout.addWidget(grupo_juros)
        dados_layout.addStretch(1)

        grupo_contatos = QGroupBox("Contatos")
        caixa = QVBoxLayout(grupo_contatos)
        self.contatos = QTableWidget(0, len(COLUNAS_CONTATO))
        self.contatos.setMinimumHeight(110)
        self.contatos.setMaximumHeight(170)
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
        caixa.addLayout(botoes)
        caixa.addWidget(
            widgets.rotulo_fraco("\"Como chamar\" é o nome usado na saudação da mensagem.")
        )
        direita.addWidget(grupo_contatos)
        self.grupo_honorario = self._grupo_honorario()
        direita.addWidget(self.grupo_honorario, 1)
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
    def _grupo_honorario(self) -> QGroupBox:
        from .contrato import FormularioContrato

        pagina = QGroupBox("Honorários recorrentes e forma de envio")
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
            self.tabela_contratos = QTableWidget(0, len(COLUNAS_CONTRATO))
            self.tabela_contratos.setMinimumHeight(140)
            self.tabela_contratos.setHorizontalHeaderLabels(COLUNAS_CONTRATO)
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
        formas = QHBoxLayout()
        dica = widgets.rotulo_fraco(
            "A forma de envio (e-mail, WhatsApp…) é escolhida em cada honorário recorrente.")
        dica.setWordWrap(True)
        formas.addWidget(dica, 1)
        botao_formas = widgets.QPushButton("Formas de envio…")
        botao_formas.setToolTip("Cria, renomeia ou desativa as formas de envio da lista")
        botao_formas.clicked.connect(self._formas_envio)
        formas.addWidget(botao_formas)
        caixa.addLayout(formas)
        return pagina

    def _formas_envio(self) -> None:
        from ..paineis.formas_envio import DialogoFormasEnvio

        DialogoFormasEnvio(self.contexto, self).exec()
        if self.formulario_honorario is not None:
            self.formulario_honorario.recarregar_formas()
        else:
            self._mostrar_contratos()

    def _ficha(self) -> None:
        from .ficha import DialogoFicha

        DialogoFicha(self.contexto, self.cliente, self, com_cadastro=False).exec()
        self._mostrar_contratos()

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
                      contrato.forma_envio.nome if contrato.forma_envio else "—",
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
        self.cliente_desde.definir(cliente.cliente_desde)
        self.observacoes.setPlainText(cliente.observacoes)
        self.juros.definir(clientes.juros_atual(cliente))
        for contato in cliente.contatos:
            self._nova_linha(contato)
        self._ajustar_subtipo()
        self._mostrar_contratos()

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
            juros_dia=self.juros.valor(),
            contatos=contatos,
            empresa_id=self.empresa.valor(),
            cliente_desde=self.cliente_desde.valor(),
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
                    "paga por outra empresa, preencha \"Paga pela empresa\" nos dados. "
                    "Dá para cadastrar o honorário depois, no cadastro do cliente.",
                    acao="Salvar sem honorário"):
            self.rolagem.ensureWidgetVisible(self.grupo_honorario)
            self.formulario_honorario.setFocus()
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
