"""Primeiro uso do programa instalado: a conexão com o banco do escritório.

O banco é um PostgreSQL num computador da rede. À esquerda, a marca (o ícone do
programa) e os passos; à direita, servidor, porta, banco, usuário e senha, com
**Testar conexão**. Se o banco ainda não existe, dá para criá-lo daqui (com um
usuário que tenha permissão). Na primeira conexão, as tabelas são criadas; num
banco que já tem dados, ele é atualizado para a versão do programa.

Servidor, porta, banco e usuário ficam em ``configuracao.json``; a senha, no
cofre de senhas do sistema. Tem estilo próprio, nas cores da marca: aparece
antes de o tema do sistema ser lido do banco.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...config import conexao as servico
from ..comum import logo, segundo_plano

AZUL, AZUL_ESCURO, TEAL, LARANJA = "#203461", "#16244A", "#4BBDCD", "#F9B259"
ESTILO = f"""
QDialog#primeiroUso {{ background: #F4F6F9; }}
QFrame#ladoMarca {{
    background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 {AZUL}, stop:1 {AZUL_ESCURO});
    border: none;
}}
QLabel#nomeMarca {{ color: #FFFFFF; font-size: 24px; font-weight: 800; }}
QLabel#textoMarca {{ color: #C9D3E8; font-size: 13px; }}
QLabel#passoMarca {{ color: #FFFFFF; font-size: 13px; }}
QLabel#numeroPasso {{
    color: {AZUL}; background: {LARANJA}; border-radius: 11px; font-weight: 800;
    min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px;
}}
QLabel#tituloPrimeiroUso {{ color: {AZUL}; font-size: 20px; font-weight: 800; }}
QLabel#textoPrimeiroUso {{ color: #5B6577; font-size: 13px; }}
QFrame#cartaoOpcao {{
    background: #FFFFFF; border: 1px solid #DCE2EA; border-radius: 12px;
}}
QFrame#cartaoOpcao:hover {{ border-color: {TEAL}; }}
QFrame#cartaoOpcao[marcado="true"] {{
    border: 2px solid {TEAL}; background: #F2FBFC;
}}
QLabel#tituloOpcao {{ color: {AZUL}; font-size: 14px; font-weight: 700; background: transparent; }}
QLabel#textoOpcao {{ color: #5B6577; font-size: 12px; background: transparent; }}
QRadioButton {{ background: transparent; }}
QRadioButton::indicator {{
    width: 16px; height: 16px; border-radius: 10px; border: 2px solid #AEB8C6;
    background: #FFFFFF;
}}
QRadioButton::indicator:checked {{
    width: 10px; height: 10px; border-radius: 10px; border: 5px solid {TEAL};
    background: #FFFFFF;
}}
QLabel#rotuloCampo {{ color: {AZUL}; font-weight: 700; }}
QLineEdit {{
    background: #FFFFFF; border: 1px solid #DCE2EA; border-radius: 8px; padding: 7px 10px;
    color: #1c2430;
}}
QLineEdit:focus {{ border-color: {TEAL}; }}
QPushButton {{
    background: #FFFFFF; border: 1px solid #DCE2EA; border-radius: 8px; padding: 7px 14px;
    color: {AZUL}; font-weight: 600;
}}
QPushButton:hover {{ border-color: {TEAL}; }}
QPushButton#continuar {{
    background: {AZUL}; color: #FFFFFF; border: 1px solid {AZUL}; padding: 9px 22px;
}}
QPushButton#continuar:hover {{ background: {AZUL_ESCURO}; }}
QLabel#avisoPrimeiroUso {{ color: #5B6577; font-size: 12px; }}
QLabel#rotuloCampo {{ color: {AZUL}; font-weight: 700; }}
QLabel#okPrimeiroUso {{
    color: #0E6B5C; background: #EAF8F5; border: 1px solid #B5E3D8; border-radius: 8px;
    padding: 8px 10px;
}}
QSpinBox {{
    background: #FFFFFF; border: 1px solid #DCE2EA; border-radius: 8px; padding: 6px 8px;
    color: #1c2430;
}}
QLabel#erroPrimeiroUso {{
    color: #B42318; background: #FEF0EE; border: 1px solid #F5C2BC; border-radius: 8px;
    padding: 8px 10px;
}}
"""


class DialogoPrimeiroUso(QDialog):
    def __init__(self, parent=None, demonstracao: bool = False, executor=None) -> None:
        """``demonstracao``: testa a conexão mas não grava nada (para ver a tela rodando
        do código-fonte: ``python -m honorarios.app --primeiro-uso``)."""
        super().__init__(parent)
        self.demonstracao = demonstracao
        self.executor = executor or segundo_plano.executar
        self.conectando = False
        self.setObjectName("primeiroUso")
        self.setWindowTitle("Financeiro Métodos – configuração")
        self.setStyleSheet(ESTILO)
        self.setMinimumSize(880, 560)
        principal = QHBoxLayout(self)
        principal.setContentsMargins(0, 0, 0, 0)
        principal.setSpacing(0)
        principal.addWidget(self._lado_da_marca())
        principal.addWidget(self._formulario(), 1)
        atual = servico.ler()
        if atual is not None:   # trocando a conexão: começa da que já existe
            self.servidor.setText(atual.servidor)
            self.porta.setValue(atual.porta)
            self.banco.setText(atual.banco)
            self.usuario.setText(atual.usuario)

    # ------------------------------------------------------------- layout
    def _lado_da_marca(self) -> QWidget:
        lado = QFrame()
        lado.setObjectName("ladoMarca")
        lado.setFixedWidth(300)
        caixa = QVBoxLayout(lado)
        caixa.setContentsMargins(32, 40, 28, 28)
        caixa.setSpacing(10)
        icone = QLabel()
        icone.setPixmap(logo.icone(150))
        caixa.addWidget(icone, 0, Qt.AlignmentFlag.AlignHCenter)
        caixa.addSpacing(10)
        nome = QLabel("Financeiro Métodos")
        nome.setObjectName("nomeMarca")
        nome.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        caixa.addWidget(nome)
        texto = QLabel("Controle de honorários e cobrança")
        texto.setObjectName("textoMarca")
        texto.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        caixa.addWidget(texto)
        caixa.addSpacing(24)
        for numero, passo in ((1, "Conecte ao banco do escritório"),
                              (2, "O sistema prepara as tabelas"),
                              (3, "Pronto para usar")):
            linha = QHBoxLayout()
            linha.setSpacing(10)
            bola = QLabel(str(numero))
            bola.setObjectName("numeroPasso")
            bola.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rotulo = QLabel(passo)
            rotulo.setObjectName("passoMarca")
            linha.addWidget(bola)
            linha.addWidget(rotulo, 1)
            caixa.addLayout(linha)
        caixa.addStretch(1)
        rodape = QLabel("A senha fica guardada no cofre de senhas do Windows, nunca em arquivo.")
        rodape.setObjectName("textoMarca")
        rodape.setWordWrap(True)
        caixa.addWidget(rodape)
        return lado

    def _formulario(self) -> QWidget:
        corpo = QWidget()
        caixa = QVBoxLayout(corpo)
        caixa.setContentsMargins(32, 32, 32, 24)
        caixa.setSpacing(12)
        titulo = QLabel("Conectar ao banco de dados")
        titulo.setObjectName("tituloPrimeiroUso")
        caixa.addWidget(titulo)
        explicacao = QLabel(
            "Os dados do escritório ficam num PostgreSQL, no computador que serve de "
            "banco. Informe onde ele está — quem instalou o banco tem esses dados."
        )
        explicacao.setObjectName("textoPrimeiroUso")
        explicacao.setWordWrap(True)
        caixa.addWidget(explicacao)
        caixa.addSpacing(4)

        formulario = QFormLayout()
        formulario.setHorizontalSpacing(14)
        formulario.setVerticalSpacing(10)
        self.servidor = QLineEdit()
        self.servidor.setPlaceholderText("IP ou nome do computador — ex.: 192.168.0.10")
        linha_servidor = QHBoxLayout()
        linha_servidor.setSpacing(10)
        linha_servidor.addWidget(self.servidor, 1)
        linha_servidor.addWidget(QLabel("porta"))
        self.porta = QSpinBox()
        self.porta.setRange(1, 65535)
        self.porta.setValue(5432)
        linha_servidor.addWidget(self.porta)
        formulario.addRow(self._rotulo("Servidor"), linha_servidor)
        self.banco = QLineEdit(servico.BANCO_PADRAO)
        formulario.addRow(self._rotulo("Banco"), self.banco)
        self.usuario = QLineEdit()
        self.usuario.setPlaceholderText("usuário do PostgreSQL")
        formulario.addRow(self._rotulo("Usuário"), self.usuario)
        self.senha = QLineEdit()
        self.senha.setEchoMode(QLineEdit.EchoMode.Password)
        formulario.addRow(self._rotulo("Senha"), self.senha)
        caixa.addLayout(formulario)

        linha_teste = QHBoxLayout()
        self.botao_testar = QPushButton("Testar conexão")
        self.botao_testar.clicked.connect(self.testar)
        self.botao_criar = QPushButton("Criar o banco agora")
        self.botao_criar.setToolTip("Cria o banco no servidor (o usuário precisa ter permissão)")
        self.botao_criar.clicked.connect(self.criar_banco)
        self.botao_criar.setVisible(False)
        linha_teste.addWidget(self.botao_testar)
        linha_teste.addWidget(self.botao_criar)
        linha_teste.addStretch(1)
        caixa.addLayout(linha_teste)

        self.resultado = QLabel("")
        self.resultado.setWordWrap(True)
        self.resultado.setVisible(False)
        caixa.addWidget(self.resultado)
        aviso = QLabel(
            "Todos os computadores do escritório usam o mesmo banco: o que um faz, os outros "
            "veem. Os backups automáticos ficam neste computador."
        )
        aviso.setObjectName("avisoPrimeiroUso")
        aviso.setWordWrap(True)
        caixa.addWidget(aviso)
        caixa.addStretch(1)

        botoes = QHBoxLayout()
        botoes.addStretch(1)
        sair = QPushButton("Sair")
        sair.clicked.connect(self.reject)
        self.continuar = QPushButton("Conectar e continuar")
        self.continuar.setObjectName("continuar")
        self.continuar.setDefault(True)
        self.continuar.clicked.connect(self.confirmar)
        botoes.addWidget(sair)
        botoes.addWidget(self.continuar)
        caixa.addLayout(botoes)
        return corpo

    @staticmethod
    def _rotulo(texto: str) -> QLabel:
        rotulo = QLabel(texto)
        rotulo.setObjectName("rotuloCampo")
        rotulo.setMinimumWidth(70)
        return rotulo

    # ------------------------------------------------------------ apoio
    def conexao(self) -> servico.ConexaoPostgres:
        return servico.ConexaoPostgres(
            servidor=self.servidor.text().strip(), porta=self.porta.value(),
            banco=self.banco.text().strip() or servico.BANCO_PADRAO,
            usuario=self.usuario.text().strip(),
        )

    def _mostrar(self, texto: str, ok: bool) -> None:
        self.resultado.setObjectName("okPrimeiroUso" if ok else "erroPrimeiroUso")
        self.resultado.setText(texto)
        self.resultado.setVisible(bool(texto))
        self.resultado.style().unpolish(self.resultado)
        self.resultado.style().polish(self.resultado)

    def _faltando(self) -> str:
        if not self.servidor.text().strip():
            return "Informe o servidor (IP ou nome do computador do banco)."
        if not self.usuario.text().strip():
            return "Informe o usuário do PostgreSQL."
        return ""

    def _ocupado(self, sim: bool, texto: str = "") -> None:
        self.conectando = sim
        for botao in (self.botao_testar, self.botao_criar, self.continuar):
            botao.setEnabled(not sim)
        if sim:
            self._mostrar(texto, True)

    def _rodar(self, funcao, ao_terminar) -> None:
        """Rede fora da tela (o servidor pode demorar a responder)."""
        def falhou(falha: Exception):
            self._ocupado(False)
            self._mostrar(str(falha), False)
            self.botao_criar.setVisible(isinstance(falha, servico.FalhaDeConexao)
                                        and servico.banco_nao_existe(falha))

        def terminou(resultado):
            self._ocupado(False)
            ao_terminar(resultado)

        self.executor(funcao, terminou, falhou)

    # ------------------------------------------------------------- ações
    def testar(self) -> None:
        if (faltando := self._faltando()):
            self._mostrar(faltando, False)
            return
        conexao, senha = self.conexao(), self.senha.text()
        self._ocupado(True, "Conectando…")
        self._rodar(lambda: servico.testar(conexao, senha),
                    lambda texto: (self._mostrar(f"✓ {texto}", True),
                                   self.botao_criar.setVisible(False)))

    def criar_banco(self) -> None:
        conexao, senha = self.conexao(), self.senha.text()
        self._ocupado(True, f"Criando o banco \"{conexao.banco}\"…")

        def criar():
            servico.criar_banco(conexao, senha)
            return servico.testar(conexao, senha)

        self._rodar(criar, lambda texto: (self._mostrar(f"✓ Banco criado. {texto}", True),
                                         self.botao_criar.setVisible(False)))

    def confirmar(self) -> None:
        if (faltando := self._faltando()):
            self._mostrar(faltando, False)
            return
        conexao, senha = self.conexao(), self.senha.text()
        self._ocupado(True, "Conectando…")

        def guardar(_texto):
            if not self.demonstracao:   # na demonstração só testa: nada é guardado
                try:
                    servico.gravar(conexao, senha)
                except Exception as falha:  # noqa: BLE001 - cofre indisponível…
                    self._mostrar(f"Conectou, mas não consegui guardar a senha: {falha}", False)
                    return
            self.accept()

        self._rodar(lambda: servico.testar(conexao, senha), guardar)
