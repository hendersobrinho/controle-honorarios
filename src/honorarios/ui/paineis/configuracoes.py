"""Configurações: PIX, modelos de mensagem, formas de envio e backup."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...dominio import mensagens as dominio_mensagens
from ...dominio.enums import (
    ChaveModelo,
    FormatoLinkWhatsapp,
    OrdemSaudacao,
    TipoChavePix,
)
from ...dominio.valores import formatar_data_hora
from ...servicos import backup as servico_backup
from ...servicos import configuracoes as servico
from ...servicos import tipos as servico_tipos
from ..comum import widgets
from ..comum.campos import ComboEnum
from ..comum.tabelas import (
    Coluna,
    ModeloTabela,
    ajustar_colunas,
    item_atual,
    preparar_tabela,
)
from ..contexto import Contexto


class PainelConfiguracoes(QWidget):
    titulo = "Configurações"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self._montar()
        self.recarregar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        self.cabecalho = widgets.Cabecalho("Configurações", "")
        self.cabecalho.adicionar_botao("Salvar", self._salvar, primario=True, atalho="Ctrl+S")
        self.cabecalho.adicionar_botao("Atualizar", self.recarregar, atalho="F5")
        layout.addWidget(self.cabecalho)

        abas = QTabWidget()
        abas.addTab(self._aba_recebedor(), "Recebedor e PIX")
        abas.addTab(self._aba_modelos(), "Modelos de mensagem")
        abas.addTab(self._aba_imagem(), "Imagem da cobrança")
        abas.addTab(self._aba_backup(), "Backup")
        abas.addTab(self._aba_claude(), "Claude (MCP)")
        layout.addWidget(abas, 1)

    # ------------------------------------------------------------- recebedor
    def _aba_recebedor(self) -> QWidget:
        pagina = QWidget()
        layout = QVBoxLayout(pagina)
        grupo = QGroupBox("Dados que aparecem na mensagem de cobrança")
        formulario = QFormLayout(grupo)
        self.razao_social = QLineEdit()
        formulario.addRow("Razão social do recebedor:", self.razao_social)
        self.tipo_chave = ComboEnum(TipoChavePix, TipoChavePix.CNPJ)
        formulario.addRow("Tipo da chave PIX:", self.tipo_chave)
        self.chave = QLineEdit()
        formulario.addRow("Chave PIX:", self.chave)
        layout.addWidget(grupo)

        grupo_geral = QGroupBox("Comportamento")
        geral = QFormLayout(grupo_geral)
        self.formato_link = ComboEnum(FormatoLinkWhatsapp, FormatoLinkWhatsapp.WA_ME)
        geral.addRow("Link do WhatsApp:", self.formato_link)
        self.ordem_saudacao = ComboEnum(OrdemSaudacao, OrdemSaudacao.SAUDACAO_NOME)
        geral.addRow("Ordem da saudação:", self.ordem_saudacao)
        self.dias_vence_breve = QSpinBox()
        self.dias_vence_breve.setRange(0, 30)
        geral.addRow("Marcar \"vence em breve\" com (dias):", self.dias_vence_breve)
        self.tema = QComboBox()
        self.tema.addItem("Claro", "claro")
        self.tema.addItem("Escuro", "escuro")
        geral.addRow("Tema:", self.tema)
        layout.addWidget(grupo_geral)

        grupo_geracao = QGroupBox("Honorários mensais")
        geracao = QFormLayout(grupo_geracao)
        self.geracao_automatica = QCheckBox("Gerar a competência do mês automaticamente")
        geracao.addRow(self.geracao_automatica)
        self.geracao_dia = QSpinBox()
        self.geracao_dia.setRange(1, 28)
        self.geracao_dia.setPrefix("dia ")
        self.geracao_automatica.toggled.connect(self.geracao_dia.setEnabled)
        geracao.addRow("A partir do:", self.geracao_dia)
        explicacao = widgets.rotulo_fraco(
            "Com o sistema aberto a partir desse dia, ele gera os honorários dos "
            "contratos recorrentes, uma vez por mês, com as mesmas regras da geração "
            "manual (suspensos e fora da vigência ficam de fora), e avisa nas "
            "notificações. O que for cancelado depois não volta."
        )
        explicacao.setWordWrap(True)
        geracao.addRow(explicacao)
        layout.addWidget(grupo_geracao)

        grupo_email = QGroupBox("E-mail de cobranças")
        email = QFormLayout(grupo_email)
        self.email_nome = QLineEdit()
        self.email_nome.setPlaceholderText("Seu nome, como aparece no e-mail")
        email.addRow("Seu nome:", self.email_nome)
        self.email_remetente = QLineEdit()
        self.email_remetente.setPlaceholderText("quem cobra e responde ao financeiro")
        email.addRow("Seu e-mail:", self.email_remetente)
        self.email_para = QLineEdit()
        self.email_para.setPlaceholderText("Quem manda a lista (usado sem o .eml dele)")
        email.addRow("E-mail do financeiro:", self.email_para)
        self.email_cc = QLineEdit()
        self.email_cc.setPlaceholderText("Separe vários com ponto e vírgula")
        email.addRow("Cópia (Cc):", self.email_cc)
        self.email_assunto = QLineEdit()
        self.email_assunto.setPlaceholderText("Clientes c/Honorários vencidos")
        email.addRow("Assunto do e-mail do financeiro:", self.email_assunto)
        conta_linha = QHBoxLayout()
        self.conta_email = widgets.rotulo_fraco("")
        conta_linha.addWidget(self.conta_email, 1)
        botao_conta = QPushButton("Conta de e-mail…")
        botao_conta.setToolTip("Outlook ou Gmail: de onde vêm os e-mails e por onde sai a resposta")
        botao_conta.clicked.connect(self._configurar_conta_email)
        conta_linha.addWidget(botao_conta)
        email.addRow("Caixa:", conta_linha)
        layout.addWidget(grupo_email)
        layout.addWidget(
            widgets.rotulo_fraco(
                "O sistema não envia mensagem nem emite boleto: ele monta o texto, "
                "copia e abre a conversa."
            )
        )
        layout.addStretch(1)
        return pagina

    # ---------------------------------------------------- imagem da cobrança
    def _aba_imagem(self) -> QWidget:
        from ...servicos import imagem_cobranca

        pagina = QWidget()
        layout = QVBoxLayout(pagina)
        grupo = QGroupBox("Fundo da imagem")
        caixa = QVBoxLayout(grupo)
        self.fundo_atual = QLabel()
        self.fundo_atual.setWordWrap(True)
        caixa.addWidget(self.fundo_atual)
        self.fundo_avisos = QLabel()
        self.fundo_avisos.setObjectName("avisoForte")
        self.fundo_avisos.setWordWrap(True)
        self.fundo_avisos.setVisible(False)
        caixa.addWidget(self.fundo_avisos)
        botoes = QHBoxLayout()
        self.botoes_fundo = {}
        for texto, funcao in (
            ("Escolher fundo SVG…", self._escolher_fundo),
            ("Voltar para o meu fundo", self._voltar_ao_fundo),
            ("Usar o modelo do sistema", self._usar_modelo_fundo),
            ("Salvar uma cópia do modelo…", self._exportar_modelo_fundo),
            ("Ver prévia", self._previa_imagem),
        ):
            botao = widgets.QPushButton(texto)
            botao.clicked.connect(lambda _=False, f=funcao: f())
            botoes.addWidget(botao)
            self.botoes_fundo[texto] = botao
        self.botoes_fundo["Voltar para o meu fundo"].setToolTip(
            "Volta a usar o último fundo que você escolheu (ele fica guardado na pasta "
            "de dados, mesmo usando o modelo)"
        )
        botoes.addStretch(1)
        caixa.addLayout(botoes)
        layout.addWidget(grupo)

        grupo_qr = QGroupBox("QR code do Pix")
        caixa_qr = QVBoxLayout(grupo_qr)
        self.qrcode_atual = QLabel()
        self.qrcode_atual.setWordWrap(True)
        caixa_qr.addWidget(self.qrcode_atual)
        botoes_qr = QHBoxLayout()
        self.botoes_qr = {}
        for texto, funcao in (
            ("Escolher PNG do QR code…", self._escolher_qrcode),
            ("Usar o do escritório", self._qrcode_modelo),
            ("Sair sem QR", self._remover_qrcode),
        ):
            botao = widgets.QPushButton(texto)
            botao.clicked.connect(lambda _=False, f=funcao: f())
            botoes_qr.addWidget(botao)
            self.botoes_qr[texto] = botao
        botoes_qr.addStretch(1)
        caixa_qr.addLayout(botoes_qr)
        caixa_qr.addWidget(widgets.rotulo_fraco(
            "O QR do Pix do escritório já vem no sistema. Para trocar, gere o QR da chave "
            "no app do banco, salve como PNG e escolha aqui. Ele entra no retângulo "
            "id=\"qrcode\" do fundo, em toda imagem de cobrança. É o QR da chave, sem "
            "valor: o cliente digita o valor ao pagar."
        ))
        layout.addWidget(grupo_qr)

        campos = ", ".join("{" + nome + "}" for nome, _ in imagem_cobranca.CAMPOS)
        layout.addWidget(
            widgets.rotulo_fraco(
                "Como fazer o fundo: desenhe o SVG no tamanho final (ex.: 1080 × 1350). "
                f"Textos com {campos} são trocados pelos valores. Um retângulo com "
                'id="lista" recebe os honorários marcados na cobrança, um por linha; um '
                'retângulo com id="qrcode" recebe o QR code (270 px de lado ou mais). '
                "Deixe esses dois retângulos transparentes. Opcional: no retângulo da "
                "lista, data-fonte, data-cor, data-cor-fraca e data-cor-linha mudam a "
                "fonte e as cores dos honorários. Agrupe a camada da cobrança (textos, "
                'lista, QR) em um grupo com id="conteudo": o "Pagamento confirmado" '
                "usa o fundo sem esse grupo."
            )
        )
        layout.addStretch(1)
        return pagina

    def _mostrar_fundo(self, avisos: list[str] | None = None) -> None:
        from ...servicos import imagem_cobranca

        sessao = self.contexto.sessao
        modelo = imagem_cobranca.usa_modelo(sessao)
        guardado = imagem_cobranca.fundo_guardado()
        if hasattr(self, "botoes_fundo"):
            self.botoes_fundo["Voltar para o meu fundo"].setVisible(modelo and guardado is not None)
            self.botoes_fundo["Usar o modelo do sistema"].setEnabled(not modelo)
        if modelo:
            self.fundo_atual.setText(
                "Usando o <b>fundo modelo</b> do sistema."
                + (" O seu fundo continua guardado: <b>Voltar para o meu fundo</b>."
                   if guardado else "")
            )
        else:
            caminho = imagem_cobranca.caminho_fundo(sessao)
            self.fundo_atual.setText(f"Usando o seu fundo: <b>{caminho}</b>")
        self.fundo_avisos.setText("\n".join(avisos or []))
        self.fundo_avisos.setVisible(bool(avisos))

    def _mostrar_qrcode(self) -> None:
        from ...servicos import imagem_cobranca

        sessao = self.contexto.sessao
        caminho = imagem_cobranca.caminho_qrcode(sessao)
        modelo = imagem_cobranca.usa_qrcode_modelo(sessao)
        if modelo:
            texto = "Usando o <b>QR do Pix do escritório</b> (vem com o sistema)."
        elif caminho:
            texto = f"Usando: <b>{caminho}</b>"
        else:
            texto = "Sem QR code: a imagem sai com a chave Pix no lugar dele."
        self.qrcode_atual.setText(texto)
        self.botoes_qr["Usar o do escritório"].setEnabled(not modelo)
        self.botoes_qr["Sair sem QR"].setEnabled(caminho is not None)

    def _qrcode_modelo(self) -> None:
        from ...servicos import imagem_cobranca

        def acao():
            imagem_cobranca.usar_qrcode_modelo(self.contexto.sessao)
            self.contexto.salvar()

        if not widgets.executar(self, acao)[0]:
            self.contexto.desfazer()
        self._mostrar_qrcode()

    def _escolher_qrcode(self) -> None:
        from ...servicos import imagem_cobranca

        origem, _ = QFileDialog.getOpenFileName(
            self, "Escolher o PNG do QR code", str(Path.home()), "PNG (*.png)"
        )
        if not origem:
            return

        def acao():
            imagem_cobranca.definir_qrcode(self.contexto.sessao, Path(origem))
            self.contexto.salvar()

        if not widgets.executar(self, acao)[0]:
            self.contexto.desfazer()
        self._mostrar_qrcode()

    def _remover_qrcode(self) -> None:
        from ...servicos import imagem_cobranca

        def acao():
            imagem_cobranca.remover_qrcode(self.contexto.sessao)
            self.contexto.salvar()

        if not widgets.executar(self, acao)[0]:
            self.contexto.desfazer()
        self._mostrar_qrcode()

    def _escolher_fundo(self) -> None:
        from ...servicos import imagem_cobranca

        origem, _ = QFileDialog.getOpenFileName(
            self, "Escolher fundo da imagem", str(Path.home()), "SVG (*.svg)"
        )
        if not origem:
            return

        def acao():
            avisos = imagem_cobranca.definir_fundo(self.contexto.sessao, Path(origem))
            self.contexto.salvar()
            return avisos

        deu_certo, avisos = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self._mostrar_fundo(avisos)

    def _voltar_ao_fundo(self) -> None:
        from ...servicos import imagem_cobranca

        def acao():
            avisos = imagem_cobranca.voltar_ao_fundo_guardado(self.contexto.sessao)
            self.contexto.salvar()
            return avisos

        deu_certo, avisos = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self._mostrar_fundo(avisos)

    def _usar_modelo_fundo(self) -> None:
        from ...servicos import imagem_cobranca

        if not widgets.confirmar(
            self, "Usar o fundo modelo do sistema?", "Usar o modelo",
            "O seu fundo não é apagado: fica guardado, e o botão \"Voltar para o meu "
            "fundo\" volta a usá-lo.", acao="Usar o modelo",
        ):
            return

        def acao():
            imagem_cobranca.usar_modelo(self.contexto.sessao)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self._mostrar_fundo()

    def _exportar_modelo_fundo(self) -> None:
        """Uma cópia do modelo para servir de ponto de partida no editor de SVG."""
        from ...servicos import imagem_cobranca

        destino, _ = QFileDialog.getSaveFileName(
            self, "Salvar cópia do modelo", str(Path.home() / "fundo_cobranca.svg"),
            "SVG (*.svg)",
        )
        if not destino:
            return

        def acao():
            shutil.copyfile(imagem_cobranca.FUNDO_MODELO, destino)

        if widgets.executar(self, acao)[0]:
            widgets.informar(self, f"Modelo salvo em {destino}.", "Pronto")

    def _previa_imagem(self) -> None:
        """Prévia com dados fictícios e o recebedor do jeito que está na tela (sem salvar)."""
        from ...servicos import imagem_cobranca
        from ..dialogos.imagem_cobranca import DialogoImagemCobranca

        sessao = self.contexto.sessao

        def acao():
            # usa o que está digitado agora, mesmo sem ter clicado em Salvar
            for chave, valor in (
                ("recebedor_razao_social", self.razao_social.text().strip()),
                ("recebedor_tipo_chave", self.tipo_chave.valor().value),
                ("recebedor_chave", self.chave.text().strip()),
            ):
                servico.gravar(sessao, chave, valor)
            try:
                return imagem_cobranca.exemplo(sessao)
            finally:
                self.contexto.desfazer()

        deu_certo, dados = widgets.executar(self, acao)
        if deu_certo:
            DialogoImagemCobranca(
                self.contexto, dados, "previa_cobranca", "Prévia da imagem", self
            ).exec()

    # -------------------------------------------------------------- modelos
    def _aba_modelos(self) -> QWidget:
        pagina = QWidget()
        layout = QVBoxLayout(pagina)
        seletor = QHBoxLayout()
        self.modelo_chave = ComboEnum(ChaveModelo, ChaveModelo.UNIDADE)
        self.modelo_chave.currentIndexChanged.connect(self._carregar_modelo)
        seletor.addWidget(widgets.rotulo_fraco("Modelo:"))
        seletor.addWidget(self.modelo_chave)
        seletor.addStretch(1)
        previa = widgets.QPushButton("Pré-visualizar com dados de exemplo")
        previa.clicked.connect(self._previa_modelo)
        restaurar = widgets.QPushButton("Restaurar padrão")
        restaurar.clicked.connect(self._restaurar_modelo)
        seletor.addWidget(previa)
        seletor.addWidget(restaurar)
        layout.addLayout(seletor)

        self.modelo_corpo = QPlainTextEdit()
        self.modelo_corpo.setMinimumHeight(220)
        layout.addWidget(self.modelo_corpo, 1)

        self.modelo_aviso = widgets.rotulo_fraco("")
        layout.addWidget(self.modelo_aviso)
        layout.addWidget(
            widgets.rotulo_fraco(
                "Variáveis disponíveis: "
                + ", ".join("{" + v + "}" for v in dominio_mensagens.VARIAVEIS_DISPONIVEIS)
            )
        )
        return pagina

    # --------------------------------------------------------------- backup
    def _aba_backup(self) -> QWidget:
        pagina = QWidget()
        layout = QVBoxLayout(pagina)
        formulario = QFormLayout()
        self.backup_ao_fechar = QComboBox()
        self.backup_ao_fechar.addItem("Sim", "1")
        self.backup_ao_fechar.addItem("Não", "0")
        formulario.addRow("Gerar backup ao fechar o sistema:", self.backup_ao_fechar)
        self.backup_manter = QSpinBox()
        self.backup_manter.setRange(1, 200)
        formulario.addRow("Quantos backups manter:", self.backup_manter)
        linha_pasta = QHBoxLayout()
        self.pasta_dados = widgets.rotulo_fraco("")
        self.pasta_dados.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        linha_pasta.addWidget(self.pasta_dados, 1)
        trocar = widgets.QPushButton("Trocar conexão…")
        trocar.setToolTip("Conectar a outro servidor ou banco (o sistema fecha para trocar)")
        trocar.clicked.connect(self._trocar_pasta_dados)
        linha_pasta.addWidget(trocar)
        formulario.addRow("Banco de dados:", linha_pasta)
        layout.addLayout(formulario)

        botoes = QHBoxLayout()
        gerar = widgets.QPushButton("Gerar backup agora")
        gerar.setObjectName("primario")
        gerar.clicked.connect(self._gerar_backup)
        restaurar = widgets.QPushButton("Restaurar selecionado")
        restaurar.clicked.connect(self._restaurar_backup)
        abrir = widgets.QPushButton("Abrir pasta de backups")
        abrir.clicked.connect(self._abrir_pasta)
        for botao in (gerar, restaurar, abrir):
            botoes.addWidget(botao)
        botoes.addStretch(1)
        layout.addLayout(botoes)

        self.modelo_backups = ModeloTabela(
            [
                Coluna("Arquivo", lambda b: b.caminho.name),
                Coluna("Quando", lambda b: formatar_data_hora(b.quando),
                       ordem=lambda b: b.quando, alinhamento=Qt.AlignmentFlag.AlignCenter),
                Coluna("Tamanho", lambda b: f"{b.tamanho / 1024:.0f} KB",
                       ordem=lambda b: b.tamanho, alinhamento=Qt.AlignmentFlag.AlignRight),
            ]
        )
        self.tabela_backups = preparar_tabela(QTableView(), esticar=0)
        self.tabela_backups.setModel(self.modelo_backups)
        layout.addWidget(self.tabela_backups, 1)
        layout.addWidget(
            widgets.rotulo_fraco(
                "Restaurar substitui o banco atual — uma cópia do estado atual é "
                "guardada antes, automaticamente."
            )
        )
        return pagina

    # --------------------------------------------------------------- Claude
    def _aba_claude(self) -> QWidget:
        pagina = QWidget()
        layout = QVBoxLayout(pagina)
        explicacao = widgets.rotulo_fraco(
            "O Claude consulta e grava nos honorários pela conversa: busca clientes, vê quem "
            "está em atraso, dá baixa, lança honorário, lê os e-mails do financeiro e "
            "responde, e prepara a cobrança no WhatsApp — com as mesmas regras das telas.\n\n"
            "Não precisa configurar nada: toda vez que abre, o sistema se grava no Claude "
            "Desktop e no Claude Code deste computador. Se o Claude estava aberto, feche-o "
            "por completo (inclusive o ícone perto do relógio) e abra de novo."
        )
        layout.addWidget(explicacao)

        grupo = QGroupBox("Situação")
        situacao = QFormLayout(grupo)
        self.claude_onde = widgets.rotulo_valor("—")
        self.claude_onde.setWordWrap(True)
        situacao.addRow("Gravado em:", self.claude_onde)
        self.claude_uso = widgets.rotulo_valor("—")
        situacao.addRow("Último uso pelo Claude:", self.claude_uso)
        layout.addWidget(grupo)

        botoes = QHBoxLayout()
        gravar = widgets.QPushButton("Gravar de novo")
        gravar.setToolTip("Grava o sistema de novo em cada Claude deste computador")
        gravar.clicked.connect(self._gravar_no_claude)
        botoes.addWidget(gravar)
        botoes.addStretch(1)
        layout.addLayout(botoes)

        aviso = widgets.rotulo_fraco(
            "Atenção: o Claude tem acesso total — pode excluir, cancelar, estornar e enviar "
            "e-mail ao financeiro pela conta configurada. No WhatsApp ele deixa a mensagem "
            "escrita e a imagem copiada; quem aperta Enviar é você."
        )
        layout.addWidget(aviso)
        layout.addStretch(1)
        return pagina

    def _mostrar_situacao_claude(self) -> None:
        from ...servicos import conexao_claude

        arquivos = list(conexao_claude.arquivos_do_desktop())
        code = conexao_claude.arquivo_do_claude_code()
        if code is not None:
            arquivos.append(code)
        gravados = [str(a) for a in arquivos if conexao_claude.registrado_em(a)]
        self.claude_onde.setText("\n".join(gravados) if gravados else "em nenhum Claude ainda")
        uso = conexao_claude.ultimo_uso(self.contexto.sessao)
        self.claude_uso.setText(
            f"{formatar_data_hora(uso.quando)} · {uso.ferramenta}" if uso else "nunca usou"
        )

    def _gravar_no_claude(self) -> None:
        from ...servicos import conexao_claude

        deu_certo, registro = widgets.executar(self, conexao_claude.registrar_em_todos)
        if not deu_certo:
            return
        self._mostrar_situacao_claude()
        texto = "Gravado em:\n" + "\n".join(str(a) for a in registro.gravados)
        if registro.falhas:
            texto += "\n\nNão consegui gravar em:\n" + "\n".join(registro.falhas)
        texto += ("\n\nFeche o Claude por completo (inclusive o ícone perto do relógio) e "
                  "abra de novo para ele carregar as ferramentas.")
        widgets.informar(self, texto, "Claude")

    # ----------------------------------------------------------------- dados
    def recarregar(self) -> None:
        sessao = self.contexto.sessao
        self.contexto.atualizar()
        self._mostrar_situacao_claude()
        self.razao_social.setText(servico.obter(sessao, "recebedor_razao_social"))
        self.tipo_chave.definir(TipoChavePix(servico.obter(sessao, "recebedor_tipo_chave", "CNPJ")))
        self.chave.setText(servico.obter(sessao, "recebedor_chave"))

        self._mostrar_qrcode()
        self._mostrar_fundo()
        self.formato_link.definir(FormatoLinkWhatsapp(servico.formato_link(sessao)))
        self.ordem_saudacao.definir(servico.ordem_saudacao(sessao))
        self.dias_vence_breve.setValue(servico.obter_int(sessao, "dias_vence_em_breve", 5))
        indice = self.tema.findData(servico.obter(sessao, "tema", "claro"))
        self.tema.setCurrentIndex(max(0, indice))
        self.backup_ao_fechar.setCurrentIndex(
            0 if servico.obter_bool(sessao, "backup_ao_fechar", True) else 1
        )
        from ...servicos import geracao_automatica

        self.geracao_automatica.setChecked(geracao_automatica.ligada(sessao))
        self.geracao_dia.setValue(geracao_automatica.dia(sessao))
        self.geracao_dia.setEnabled(self.geracao_automatica.isChecked())
        from ...servicos import email_cobrancas

        dados_email = email_cobrancas.remetente(sessao)
        self.email_nome.setText(dados_email.nome)
        self.email_remetente.setText(dados_email.email)
        self.email_para.setText(dados_email.para)
        self.email_cc.setText(dados_email.cc)
        self.email_assunto.setText(dados_email.assunto)
        from ...servicos import caixa_email

        self.conta_email.setText(caixa_email.conta(sessao).descricao)
        self.backup_manter.setValue(servico.obter_int(sessao, "backup_manter", 20))
        from ...config.caminhos import pasta_backups
        from ...config.conexao import descricao

        self.pasta_dados.setText(f"{descricao()} · backups em {pasta_backups()}")
        self._carregar_modelo()
        self.modelo_backups.definir_itens(servico_backup.listar())
        for tabela, modelo in (
            (self.tabela_backups, self.modelo_backups),
        ):
            ajustar_colunas(tabela, modelo.colunas)

    def _carregar_modelo(self) -> None:
        modelo = servico.modelo(self.contexto.sessao, self.modelo_chave.valor())
        self.modelo_corpo.setPlainText(modelo.corpo)
        self.modelo_aviso.setText("")

    def _previa_modelo(self) -> None:
        from datetime import date, time
        from decimal import Decimal

        chave = self.modelo_chave.valor()
        corpo = self.modelo_corpo.toPlainText()
        invalidas = servico_tipos.validar_corpo_modelo(corpo, chave)
        if invalidas:
            self.modelo_aviso.setText(
                "Variáveis inexistentes: " + ", ".join("{" + v + "}" for v in invalidas)
            )
            return
        item = dominio_mensagens.ItemCobranca(
            tipo_nome="Honorário mensal",
            texto_mensagem=dominio_mensagens.TEXTO_MENSAL,
            texto_mensagem_empresa=dominio_mensagens.TEXTO_MENSAL_EMPRESA,
            texto_item_lista=dominio_mensagens.TEXTO_MENSAL_ITEM,
            competencia=__import__(
                "honorarios.dominio.valores", fromlist=["Competencia"]
            ).Competencia(2026, 8),
            vencimento=date(2026, 9, 8),
            valor_original=Decimal("592.90"),
            juros=Decimal("6.80"),
            valor_atualizado=Decimal("599.70"),
            dias_atraso=9,
        )
        itens = [item, item] if chave is ChaveModelo.VARIOS else [item]
        contexto = dominio_mensagens.ContextoMensagem(
            empresa="EMPRESA EXEMPLO LTDA",
            itens=itens,
            recebedor=servico.recebedor(self.contexto.sessao),
            data_referencia=date(2026, 9, 17),
            hora_referencia=time(14, 30),
            nome_tratamento="Carol",
            ordem_saudacao=self.ordem_saudacao.valor(),
            modelos={chave: corpo},
            forcar_lembrete=chave is ChaveModelo.LEMBRETE,
        )

        def acao():
            return dominio_mensagens.montar_mensagem(contexto)

        deu_certo, texto = widgets.executar(self, acao)
        if deu_certo:
            widgets.informar(self, texto, "Pré-visualização")

    def _restaurar_modelo(self) -> None:
        chave = self.modelo_chave.valor()
        self.modelo_corpo.setPlainText(dominio_mensagens.MODELOS_PADRAO[chave])

    # ----------------------------------------------------------------- ações
    def _salvar(self) -> None:
        sessao = self.contexto.sessao
        chave = self.modelo_chave.valor()
        invalidas = servico_tipos.validar_corpo_modelo(self.modelo_corpo.toPlainText(), chave)
        if invalidas:
            widgets.aviso(
                self,
                "O modelo usa variáveis que não existem: "
                + ", ".join("{" + v + "}" for v in invalidas),
            )
            return

        def acao():
            servico.gravar(sessao, "recebedor_razao_social", self.razao_social.text().strip())
            servico.gravar(sessao, "recebedor_tipo_chave", self.tipo_chave.valor().value)
            servico.gravar(sessao, "recebedor_chave", self.chave.text().strip())
            servico.gravar(sessao, "formato_link_whatsapp", self.formato_link.valor().value)
            servico.gravar(sessao, "dias_vence_em_breve", str(self.dias_vence_breve.value()))
            servico.gravar(sessao, "tema", self.tema.currentData())
            servico.gravar(sessao, "backup_ao_fechar", self.backup_ao_fechar.currentData())
            servico.gravar(sessao, "backup_manter", str(self.backup_manter.value()))
            servico.gravar(sessao, "geracao_automatica",
                           "1" if self.geracao_automatica.isChecked() else "0")
            servico.gravar(sessao, "geracao_automatica_dia", str(self.geracao_dia.value()))
            from ...servicos import email_cobrancas

            email_cobrancas.gravar_remetente(sessao, email_cobrancas.Remetente(
                nome=self.email_nome.text(), email=self.email_remetente.text(),
                para=self.email_para.text(), cc=self.email_cc.text(),
                assunto=self.email_assunto.text(),
            ))
            servico.gravar_ordem_saudacao(sessao, self.ordem_saudacao.valor())
            servico.modelo(sessao, chave).corpo = self.modelo_corpo.toPlainText()
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        widgets.informar(self, "Configurações salvas.", "Pronto")

    def _configurar_conta_email(self) -> None:
        from ..dialogos.conta_email import DialogoContaEmail

        if DialogoContaEmail(self.contexto, self).exec():
            self.recarregar()

    def _trocar_pasta_dados(self) -> None:
        """Conecta a outro banco; antes, um backup do atual. O sistema fecha para trocar
        (o banco aberto continua sendo o antigo até reabrir)."""
        from ..dialogos.primeiro_uso import DialogoPrimeiroUso

        if not widgets.confirmar(
            self, "Trocar a conexão com o banco?", "Banco de dados",
            "Antes, é feito um backup do banco atual. Depois de escolher, o sistema fecha; "
            "ao abrir de novo, ele usa a conexão nova.", acao="Configurar a conexão…",
        ):
            return
        deu_certo, _ = widgets.executar(
            self, lambda: servico_backup.gerar("antes-de-trocar-pasta",
                                               self.backup_manter.value()))
        if not deu_certo:
            return
        dialogo = DialogoPrimeiroUso(self)
        dialogo.setWindowTitle("Trocar a conexão com o banco")
        if not dialogo.exec():
            return
        widgets.informar(self, "Conexão trocada. O sistema vai fechar agora — abra de novo "
                               "para usar o banco novo.", "Banco de dados")
        janela = self.window()
        janela.sem_backup_ao_fechar = True   # o backup "ao fechar" já foi feito acima
        janela.close()

    def _gerar_backup(self) -> None:
        def acao():
            return servico_backup.gerar("manual", self.backup_manter.value())

        deu_certo, arquivo = widgets.executar(self, acao)
        if deu_certo:
            widgets.informar(self, f"Backup gerado em:\n{arquivo}", "Backup")
            self.recarregar()

    def _restaurar_backup(self) -> None:
        arquivo = item_atual(self.tabela_backups)
        if arquivo is None:
            widgets.aviso(self, "Selecione um backup da lista.")
            return
        if not widgets.confirmar(
            self,
            f"Restaurar o backup de {formatar_data_hora(arquivo.quando)}?",
            "Restaurar backup",
            "O banco atual é substituído. Uma cópia dele é guardada antes. "
            "Feche e abra o sistema depois de restaurar.",
        ):
            return

        def acao():
            return servico_backup.restaurar(arquivo.caminho)

        deu_certo, _ = widgets.executar(self, acao)
        if deu_certo:
            widgets.informar(
                self,
                "Backup restaurado. Feche e abra o sistema para recarregar os dados.",
                "Restauração concluída",
            )

    def _abrir_pasta(self) -> None:
        from ...config.caminhos import pasta_backups

        widgets.abrir_url(f"file://{pasta_backups()}")
