"""Conta de e-mail: de onde vêm os e-mails do financeiro e por onde a resposta sai.

Um provedor por vez — Gmail, Microsoft 365 (Outlook) ou outro (IMAP/SMTP) —, o
seu e-mail e a pasta que a regra preenche. A senha de app e a autorização da
Microsoft vão para o cofre de senhas do sistema, não para o banco. A imagem de
assinatura, posta no fim do que se envia, fica no banco (vale em qualquer PC).
"""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...servicos import caixa_email as servico
from ..comum import cores, segundo_plano, tema, widgets
from ..contexto import Contexto

AJUDA_GMAIL = (
    "<b>No Gmail</b>: 1) ative a verificação em duas etapas e crie uma <b>senha de app</b> "
    "em <a href='https://myaccount.google.com/apppasswords'>myaccount.google.com/apppasswords"
    "</a>; 2) crie o marcador da pasta (ex.: Cobranças) e um <b>filtro</b> com o remetente "
    "do financeiro e o assunto da conversa → <i>aplicar o marcador</i>."
)
AJUDA_MICROSOFT = (
    "<b>Uma vez, quem administra o e-mail</b>, no portal Microsoft Entra: <i>Registros de "
    "aplicativo → Novo registro</i> (contas só desta organização); em <i>Autenticação</i>, "
    "<i>Permitir fluxos de cliente público</i> = Sim; em <i>Permissões de API</i>, Microsoft "
    "Graph delegadas <b>Mail.Read</b> e <b>Mail.Send</b>. Copie o <i>ID do aplicativo</i> e o "
    "<i>ID do diretório (locatário)</i> para cá.<br><b>No Outlook</b>: crie a pasta (ex.: "
    "Cobranças) e uma <b>regra</b>: de [financeiro] com o assunto da conversa → <i>mover para "
    "a pasta</i>."
)
AJUDA_IMAP = (
    "Use os dados de IMAP (leitura) e SMTP (envio) do seu provedor e uma senha de app, se ele "
    "tiver. Crie a pasta e a regra que leva os e-mails do financeiro para ela."
)


LARGURA_ROTULO = 170
LARGURA_ASSINATURA = 600   # maior que isso, a imagem é reduzida (e-mail não precisa de mais)
ALTURA_PREVIA = 90


def png_da_assinatura(caminho: str) -> bytes:
    """Abre a imagem, reduz se for larga demais e devolve em PNG."""
    imagem = QImage(caminho)
    if imagem.isNull():
        raise servico.ErroDeValidacao("Não consegui abrir essa imagem.")
    if imagem.width() > LARGURA_ASSINATURA:
        imagem = imagem.scaledToWidth(LARGURA_ASSINATURA,
                                      Qt.TransformationMode.SmoothTransformation)
    dados = QByteArray()
    buffer = QBuffer(dados)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    imagem.save(buffer, "PNG")
    return bytes(dados)


def _rotulo(texto: str) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setMinimumWidth(LARGURA_ROTULO)
    return rotulo


class DialogoEntradaMicrosoft(QDialog):
    """Mostra o código e espera a pessoa entrar em microsoft.com/devicelogin."""

    def __init__(self, caixa: servico.CaixaMicrosoft, executor, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Entrar na conta Microsoft")
        self.setMinimumWidth(460)
        self.caixa = caixa
        self.executor = executor
        self.cancelado = False
        self.conectou = False
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        self.instrucao = QLabel("Pedindo o código à Microsoft…")
        self.instrucao.setWordWrap(True)
        layout.addWidget(self.instrucao)
        self.codigo = QLabel("")
        self.codigo.setObjectName("codigoEntrada")
        self.codigo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.codigo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.codigo)
        linha = QHBoxLayout()
        self.copiar = QPushButton("Copiar código")
        self.copiar.clicked.connect(lambda: widgets.copiar(self.codigo.text()))
        self.abrir = QPushButton("Abrir a página de entrada")
        self.abrir.setObjectName("primario")
        linha.addWidget(self.copiar)
        linha.addWidget(self.abrir)
        layout.addLayout(linha)
        self.situacao = widgets.rotulo_fraco("")
        layout.addWidget(self.situacao)
        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        botoes.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)
        for botao in (self.copiar, self.abrir):
            botao.setEnabled(False)
        self.executor(self.caixa.iniciar_entrada, self._recebeu_codigo, self._falhou)

    def _recebeu_codigo(self, codigo: servico.CodigoDeEntrada) -> None:
        self.codigo.setText(codigo.codigo)
        self.instrucao.setText(
            "Abra a página da Microsoft, digite o código abaixo e entre com a sua conta. "
            "Esta janela fecha sozinha quando terminar."
        )
        self.abrir.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(codigo.endereco))
        )
        for botao in (self.copiar, self.abrir):
            botao.setEnabled(True)
        self.situacao.setText("Esperando você entrar…")
        self.executor(
            lambda: self.caixa.concluir_entrada(codigo, lambda: self.cancelado),
            self._entrou, self._falhou,
        )

    def _entrou(self, _resultado) -> None:
        self.conectou = True
        self.accept()

    def _falhou(self, falha: Exception) -> None:
        if not self.cancelado:
            self.situacao.setText(str(falha))

    def reject(self) -> None:
        self.cancelado = True
        super().reject()


class DialogoContaEmail(QDialog):
    def __init__(self, contexto: Contexto, parent=None, executor=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.executor = executor or segundo_plano.executar
        self.setWindowTitle("Conta de e-mail")
        self.setMinimumWidth(620)
        atual = servico.conta(contexto.sessao)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(widgets.rotulo_fraco(
            "O sistema lê só a pasta abaixo, e dela só os e-mails com o assunto da conversa "
            "(Configurações → E-mail de cobranças). Nada mais da caixa é baixado."
        ))

        formulario = QFormLayout()
        formulario.setHorizontalSpacing(12)
        self.provedor = QComboBox()
        for chave, nome in servico.PROVEDORES.items():
            self.provedor.addItem(nome, chave)
        indice = self.provedor.findData(atual.provedor)
        self.provedor.setCurrentIndex(max(0, indice))
        formulario.addRow(_rotulo("Provedor:"), self.provedor)
        self.endereco = QLineEdit(atual.endereco)
        self.endereco.setPlaceholderText("voce@empresa.com.br")
        formulario.addRow(_rotulo("Seu e-mail:"), self.endereco)
        self.pasta = QLineEdit(atual.pasta)
        formulario.addRow(_rotulo("Pasta (ou marcador):"), self.pasta)
        layout.addLayout(formulario)

        self.paginas = QStackedWidget()
        self.paginas.addWidget(self._pagina_gmail())
        self.paginas.addWidget(self._pagina_microsoft(atual))
        self.paginas.addWidget(self._pagina_imap(atual))
        layout.addWidget(self.paginas)
        layout.addLayout(self._assinatura())

        self.resultado = QLabel("")
        self.resultado.setWordWrap(True)
        self.resultado.setObjectName("resultadoConexao")
        layout.addWidget(self.resultado)

        botoes = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        botoes.button(QDialogButtonBox.StandardButton.Save).setText("Salvar")
        botoes.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        self.botao_testar = botoes.addButton("Testar conexão",
                                             QDialogButtonBox.ButtonRole.ActionRole)
        self.botao_testar.clicked.connect(self.testar)
        botoes.accepted.connect(self._salvar)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)
        self.provedor.currentIndexChanged.connect(self._trocar_pagina)
        self._trocar_pagina()

    # ---------------------------------------------------------- assinatura
    def _assinatura(self) -> QFormLayout:
        self.imagem_assinatura = servico.assinatura(self.contexto.sessao)
        self.previa_assinatura = QLabel()
        self.previa_assinatura.setObjectName("previaAssinatura")
        self.botao_assinatura = QPushButton("Escolher imagem…")
        self.botao_assinatura.clicked.connect(self._escolher_assinatura)
        self.botao_sem_assinatura = QPushButton("Remover")
        self.botao_sem_assinatura.clicked.connect(lambda: self._mostrar_assinatura(b""))
        linha = QHBoxLayout()
        linha.addWidget(self.previa_assinatura, 1)
        linha.addWidget(self.botao_assinatura)
        linha.addWidget(self.botao_sem_assinatura)
        formulario = QFormLayout()
        formulario.setHorizontalSpacing(12)
        formulario.addRow(_rotulo("Assinatura (imagem):"), linha)
        self._mostrar_assinatura(self.imagem_assinatura)
        return formulario

    def _mostrar_assinatura(self, imagem: bytes) -> None:
        self.imagem_assinatura = imagem
        self.botao_sem_assinatura.setEnabled(bool(imagem))
        if not imagem:
            self.previa_assinatura.setPixmap(QPixmap())
            self.previa_assinatura.setText("Sem assinatura")
            return
        figura = QPixmap()
        figura.loadFromData(imagem)
        if figura.height() > ALTURA_PREVIA:
            figura = figura.scaledToHeight(ALTURA_PREVIA,
                                           Qt.TransformationMode.SmoothTransformation)
        self.previa_assinatura.setPixmap(figura)

    def _escolher_assinatura(self) -> None:
        caminho, _ = QFileDialog.getOpenFileName(
            self, "Imagem da assinatura", "",
            "Imagens (*.png *.jpg *.jpeg *.gif *.bmp);;Todos os arquivos (*)",
        )
        if not caminho:
            return
        deu_certo, imagem = widgets.executar(self, lambda: png_da_assinatura(caminho))
        if deu_certo:
            self._mostrar_assinatura(imagem)

    # ------------------------------------------------------------ páginas
    def _ajuda(self, html: str) -> QLabel:
        cor = tema.cor("destaque", cores.tema_atual()).name()
        rotulo = QLabel(html.replace("<a href", f"<a style='color:{cor}' href"))
        rotulo.setWordWrap(True)
        rotulo.setOpenExternalLinks(True)
        rotulo.setObjectName("ajudaConta")
        return rotulo

    def _campo_senha(self) -> QLineEdit:
        campo = QLineEdit()
        campo.setEchoMode(QLineEdit.EchoMode.Password)
        guardada = servico.ler_segredo(servico.chave_senha(self.endereco.text()))
        campo.setPlaceholderText("guardada no cofre do sistema" if guardada
                                 else "senha de app")
        return campo

    def _pagina_gmail(self) -> QWidget:
        pagina = QWidget()
        formulario = QFormLayout(pagina)
        formulario.setContentsMargins(0, 0, 0, 0)
        formulario.setHorizontalSpacing(12)
        self.senha_gmail = self._campo_senha()
        formulario.addRow(_rotulo("Senha de app:"), self.senha_gmail)
        formulario.addRow(self._ajuda(AJUDA_GMAIL))
        return pagina

    def _pagina_microsoft(self, atual: servico.ContaEmail) -> QWidget:
        pagina = QWidget()
        formulario = QFormLayout(pagina)
        formulario.setContentsMargins(0, 0, 0, 0)
        formulario.setHorizontalSpacing(12)
        self.ms_cliente = QLineEdit(atual.ms_cliente)
        self.ms_cliente.setPlaceholderText("ID do aplicativo (cliente)")
        formulario.addRow(_rotulo("ID do aplicativo:"), self.ms_cliente)
        self.ms_locatario = QLineEdit(
            "" if atual.ms_locatario == "organizations" else atual.ms_locatario
        )
        self.ms_locatario.setPlaceholderText("ID do diretório (locatário)")
        formulario.addRow(_rotulo("ID do locatário:"), self.ms_locatario)
        linha = QHBoxLayout()
        self.ms_situacao = QLabel()
        linha.addWidget(self.ms_situacao, 1)
        self.botao_entrar = QPushButton("Entrar na conta Microsoft…")
        self.botao_entrar.clicked.connect(self.entrar_microsoft)
        self.botao_sair = QPushButton("Desconectar")
        self.botao_sair.clicked.connect(self._desconectar_microsoft)
        linha.addWidget(self.botao_entrar)
        linha.addWidget(self.botao_sair)
        formulario.addRow(linha)
        formulario.addRow(self._ajuda(AJUDA_MICROSOFT))
        self._mostrar_situacao_microsoft()
        return pagina

    def _pagina_imap(self, atual: servico.ContaEmail) -> QWidget:
        pagina = QWidget()
        formulario = QFormLayout(pagina)
        formulario.setContentsMargins(0, 0, 0, 0)
        formulario.setHorizontalSpacing(12)
        self.imap_host = QLineEdit(atual.imap_host if atual.provedor == servico.IMAP else "")
        self.imap_host.setPlaceholderText("imap.seuprovedor.com.br")
        self.imap_porta = QSpinBox()
        self.imap_porta.setRange(1, 65535)
        self.imap_porta.setValue(atual.imap_porta)
        self.smtp_host = QLineEdit(atual.smtp_host if atual.provedor == servico.IMAP else "")
        self.smtp_host.setPlaceholderText("smtp.seuprovedor.com.br")
        self.smtp_porta = QSpinBox()
        self.smtp_porta.setRange(1, 65535)
        self.smtp_porta.setValue(atual.smtp_porta)
        for rotulo, servidor, porta in (("IMAP (leitura):", self.imap_host, self.imap_porta),
                                        ("SMTP (envio):", self.smtp_host, self.smtp_porta)):
            linha = QHBoxLayout()
            linha.addWidget(servidor, 1)
            linha.addWidget(QLabel("porta"))
            linha.addWidget(porta)
            formulario.addRow(_rotulo(rotulo), linha)
        self.senha_imap = self._campo_senha()
        formulario.addRow(_rotulo("Senha:"), self.senha_imap)
        formulario.addRow(self._ajuda(AJUDA_IMAP))
        return pagina

    def _trocar_pagina(self) -> None:
        ordem = {servico.GMAIL: 0, servico.MICROSOFT: 1, servico.IMAP: 2}
        self.paginas.setCurrentIndex(ordem.get(self.provedor.currentData(), 0))
        self.resultado.setText("")

    # -------------------------------------------------------------- dados
    def _conta_do_formulario(self) -> servico.ContaEmail:
        provedor = self.provedor.currentData()
        dados = servico.ContaEmail(
            provedor=provedor, endereco=self.endereco.text().strip(),
            pasta=self.pasta.text().strip() or servico.PASTA_PADRAO,
            ms_cliente=self.ms_cliente.text().strip(),
            ms_locatario=self.ms_locatario.text().strip() or "organizations",
        )
        if provedor == servico.GMAIL:
            dados.imap_host, dados.imap_porta, dados.smtp_host, dados.smtp_porta = \
                servico.PADROES_GMAIL
        elif provedor == servico.IMAP:
            dados.imap_host = self.imap_host.text().strip()
            dados.imap_porta = self.imap_porta.value()
            dados.smtp_host = self.smtp_host.text().strip()
            dados.smtp_porta = self.smtp_porta.value()
        return dados

    def _senha_digitada(self) -> str:
        campo = self.senha_gmail if self.provedor.currentData() == servico.GMAIL \
            else self.senha_imap
        return campo.text().replace(" ", "") if self.provedor.currentData() == servico.GMAIL \
            else campo.text()

    def _caixa(self):
        dados = self._conta_do_formulario()
        if not dados.endereco:
            raise servico.ErroDeValidacao("Informe o seu e-mail.")
        if dados.provedor == servico.MICROSOFT:
            if not dados.ms_cliente:
                raise servico.ErroDeValidacao("Informe o ID do aplicativo da Microsoft.")
            return servico.CaixaMicrosoft(dados)
        senha = self._senha_digitada() or \
            servico.ler_segredo(servico.chave_senha(dados.endereco))
        if not senha:
            raise servico.ErroDeValidacao("Informe a senha de app.")
        if not (dados.imap_host and dados.smtp_host):
            raise servico.ErroDeValidacao("Informe os servidores IMAP e SMTP.")
        return servico.CaixaImap(dados, senha)

    def testar(self) -> None:
        deu_certo, caixa = widgets.executar(self, self._caixa)
        if not deu_certo:
            return
        self.botao_testar.setEnabled(False)
        self.resultado.setText("Testando a conexão…")

        def fim(texto):
            self.botao_testar.setEnabled(True)
            self.resultado.setProperty("ok", True)
            self.resultado.setText(f"✓ {texto}")

        def falhou(falha):
            self.botao_testar.setEnabled(True)
            self.resultado.setProperty("ok", False)
            self.resultado.setText(str(falha))

        self.executor(caixa.testar, fim, falhou)

    def _mostrar_situacao_microsoft(self) -> None:
        endereco = self.endereco.text().strip()
        conectada = bool(endereco) and bool(
            servico.ler_segredo(servico.chave_token_microsoft(endereco))
        )
        self.ms_situacao.setText("✓ Conectada" if conectada else "Não conectada")
        self.botao_sair.setEnabled(conectada)

    def entrar_microsoft(self) -> None:
        deu_certo, caixa = widgets.executar(self, self._caixa)
        if not deu_certo:
            return
        dialogo = DialogoEntradaMicrosoft(caixa, self.executor, self)
        dialogo.exec()
        self._mostrar_situacao_microsoft()
        if dialogo.conectou:
            self.resultado.setText("✓ Conta Microsoft conectada. Salve para usar.")

    def _desconectar_microsoft(self) -> None:
        servico.apagar_segredo(servico.chave_token_microsoft(self.endereco.text()))
        self._mostrar_situacao_microsoft()

    def _salvar(self) -> None:
        dados = self._conta_do_formulario()
        if not dados.endereco:
            widgets.aviso(self, "Informe o seu e-mail.")
            return

        def acao():
            servico.gravar_conta(self.contexto.sessao, dados)
            servico.gravar_assinatura(self.contexto.sessao, self.imagem_assinatura)
            senha = self._senha_digitada()
            if senha and dados.provedor in (servico.GMAIL, servico.IMAP):
                servico.guardar_segredo(servico.chave_senha(dados.endereco), senha)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if deu_certo:
            self.accept()
