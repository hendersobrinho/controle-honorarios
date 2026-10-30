"""Tela "Cobrar": escolher, conferir a conta, acertar as datas e mandar.

Tudo numa tela só, em passos numerados:

1. **Quais honorários** vão na cobrança.
2. **Conferência**: a conta dos juros de cada um (dias × juros por dia), com a
   opção de digitar outro valor de juros à mão.
3. **Datas**: até quando os valores são atualizados (hoje, ou outra data) e o
   vencimento — o "pagar até" da imagem e do lembrete, que não mexe nos juros.
4. **Para o cliente**: a mensagem e a imagem, já com essas datas e esses
   valores, para conferir antes de copiar.

Copiar não registra nada — o registro acontece só em "Marcar como cobrado",
porque copiar e não enviar é situação comum.
"""

from __future__ import annotations

from decimal import Decimal
from html import escape

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableView,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ...config.caminhos import pasta_exportacoes
from ...dominio.enums import Canal
from ...dominio.valores import ZERO, formatar_data, formatar_moeda, formatar_telefone
from ...servicos import calculo, cobrancas, imagem_cobranca
from ...servicos import clientes as servico_clientes
from ...servicos.erros import ErroDeNegocio
from ...servicos.honorarios import LinhaHonorario
from ..comum import cores, tema, widgets
from ..comum.campos import CampoData, CampoMoeda, ComboRegistros, ValorDestaque
from ..comum.imagem_cobranca import copiar_imagem, renderizar
from ..comum.tabelas import (
    Coluna,
    ModeloTabelaMarcavel,
    ajustar_colunas,
    coluna_data,
    coluna_inteiro,
    coluna_moeda,
    distribuir_sobra,
    preparar_tabela,
)
from ..contexto import Contexto

ABA_MENSAGEM, ABA_IMAGEM = 0, 1
ALTURA_COMPACTA = 760   # abaixo disso (notebook), as dicas dos passos somem
LARGURA_MINIMA_HONORARIO = 110   # o nome inteiro fica na dica e na conferência
LINHAS_MINIMAS = 4   # a lista mostra pelo menos isto; com mais espaço, mais


def _rotulo(linha: LinhaHonorario) -> str:
    honorario = linha.honorario
    competencia = honorario.competencia_rotulo or honorario.descricao
    if not competencia or competencia.startswith(honorario.tipo.nome):
        return competencia or honorario.tipo.nome
    return f"{honorario.tipo.nome} · {competencia}"


def _etapa(numero: int, titulo: str, dica: str = "") -> tuple[QFrame, QVBoxLayout, QHBoxLayout]:
    """Cartão de um passo: número no círculo, título e a dica embaixo.

    Devolve o cartão, o layout do corpo e a linha do topo (para links à direita).
    """
    cartao = QFrame()
    cartao.setObjectName("etapa")
    corpo = QVBoxLayout(cartao)
    corpo.setContentsMargins(16, 14, 16, 14)
    corpo.setSpacing(10)
    topo = QHBoxLayout()
    topo.setSpacing(10)
    circulo = QLabel(str(numero))
    circulo.setObjectName("etapaNumero")
    circulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
    topo.addWidget(circulo, 0, Qt.AlignmentFlag.AlignTop)
    textos = QVBoxLayout()
    textos.setSpacing(1)
    rotulo = QLabel(titulo)
    rotulo.setObjectName("etapaTitulo")
    rotulo.setToolTip(dica)   # na tela baixa a dica some; no título ela continua
    textos.addWidget(rotulo)
    if dica:
        explicacao = QLabel(dica)
        explicacao.setObjectName("etapaDica")
        explicacao.setWordWrap(True)
        textos.addWidget(explicacao)
    topo.addLayout(textos, 1)
    corpo.addLayout(topo)
    return cartao, corpo, topo


def _segmentos(dono, *textos: str) -> tuple[list[QPushButton], QHBoxLayout]:
    """Botões que se acendem, um de cada vez (escolha entre poucas opções)."""
    grupo = QButtonGroup(dono)
    linha = QHBoxLayout()
    linha.setSpacing(6)
    botoes = []
    for texto in textos:
        botao = QPushButton(texto)
        botao.setObjectName("segmento")
        botao.setCheckable(True)
        botao.setCursor(Qt.CursorShape.PointingHandCursor)
        grupo.addButton(botao)
        linha.addWidget(botao)
        botoes.append(botao)
    botoes[0].setChecked(True)
    return botoes, linha


def _link(texto: str, funcao) -> QPushButton:
    botao = QPushButton(texto)
    botao.setObjectName("linkFiltro")
    botao.setCursor(Qt.CursorShape.PointingHandCursor)
    botao.clicked.connect(lambda _=False: funcao())
    return botao


class DialogoCobrar(QDialog):
    def __init__(self, contexto: Contexto, cliente, linhas: list[LinhaHonorario], parent=None):
        super().__init__(parent)
        self.contexto = contexto
        self.cliente = cliente
        self.linhas = list(linhas)
        self.registrou = False
        # id do honorário → juros digitado à mão (vale até fechar a tela)
        self.juros_manuais: dict[int, Decimal] = {}
        self._gerando = False
        self._pagar_ate_a_mao = False     # a pessoa escolheu o vencimento
        self._tipo_a_mao = False          # a pessoa escolheu cobrança ou lembrete
        self._editada: LinhaHonorario | None = None
        self._acordo_registrado: tuple | None = None
        self.imagem: QImage | None = None
        self.dados_imagem: imagem_cobranca.DadosImagem | None = None
        self._imagem_em_dia = False
        # honorários das pessoas físicas que pagam por esta empresa
        self.linhas_vinculados = [
            linha
            for linha in cobrancas.linhas_em_aberto_do_cliente(
                contexto.sessao, cliente.id, contexto.data_referencia, incluir_vinculados=True
            )
            if linha.honorario.cliente_id != cliente.id
        ]
        # a prévia da imagem é refeita um instante depois da última mudança
        self._espera_imagem = QTimer(self)
        self._espera_imagem.setSingleShot(True)
        self._espera_imagem.setInterval(250)
        self._espera_imagem.timeout.connect(self._atualizar_imagem)
        self.setObjectName("dialogoCobrar")
        self.setWindowTitle(f"Cobrar – {cliente.nome}")
        self._tamanho_inicial()
        self._montar()
        self._escolher_para_editar(-1)
        self._gerar()

    # ================================================================== layout
    def resizeEvent(self, evento) -> None:  # noqa: N802 - nome da API do Qt
        super().resizeEvent(evento)
        compacta = self.height() < ALTURA_COMPACTA
        for dica in self.findChildren(QLabel, "etapaDica"):
            dica.setVisible(not compacta)
        # a largura da tabela só se acerta depois do layout: confere logo em seguida
        QTimer.singleShot(0, self._encaixar_colunas)

    def _encaixar_colunas(self) -> None:
        """Lista estreita: some o "Venceu em" (está na conferência) e o total fica à vista."""
        if not hasattr(self, "tabela"):
            return
        indice = next(i for i, c in enumerate(self.modelo.colunas) if c.titulo == "Venceu em")
        esticada = self.tabela.coluna_esticada
        outras = sum(self.tabela.columnWidth(i) for i in range(len(self.modelo.colunas))
                     if i not in (indice, esticada))
        cabe = outras + self._largura_vencimento + LARGURA_MINIMA_HONORARIO \
            <= self.tabela.viewport().width()
        if self.tabela.isColumnHidden(indice) == cabe:
            self.tabela.setColumnHidden(indice, not cabe)
            if cabe:
                self.tabela.setColumnWidth(indice, self._largura_vencimento)
        distribuir_sobra(self.tabela)

    def showEvent(self, evento) -> None:  # noqa: N802 - nome da API do Qt
        """Ao aparecer, já no tamanho final: 58% da largura para a lista, 42% para o resto."""
        super().showEvent(evento)
        if not self._proporcao_feita:
            self._proporcao_feita = True
            largura = self.divisor.width() - self.divisor.handleWidth()
            esquerda = int(largura * 0.58)
            self.divisor.setSizes([esquerda, largura - esquerda])

    def _tamanho_inicial(self) -> None:
        """1320×900, ou o que couber na tela (notebook de 1366×768, por exemplo)."""
        tela = self.screen().availableGeometry() if self.screen() else None
        largura, altura = 1320, 900
        if tela is not None and not tela.isEmpty():
            largura = min(largura, int(tela.width() * 0.96))
            altura = min(altura, int(tela.height() * 0.94))
        self.resize(largura, altura)

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)
        layout.addLayout(self._topo())

        suspensao = servico_clientes.suspensao(self.cliente, self.contexto.data_referencia)
        if suspensao:
            aviso = QLabel(
                f"⚠ {suspensao}. Retome a cobrança na ficha do cliente para poder "
                "registrar esta cobrança."
            )
            aviso.setObjectName("avisoForte")
            aviso.setWordWrap(True)
            layout.addWidget(aviso)

        self.divisor = QSplitter(Qt.Orientation.Horizontal)
        self.divisor.setChildrenCollapsible(False)
        self.divisor.setHandleWidth(14)
        self.divisor.addWidget(self._coluna_esquerda())
        self.divisor.addWidget(self._coluna_direita())
        self.divisor.setStretchFactor(0, 58)
        self.divisor.setStretchFactor(1, 42)
        self._proporcao_feita = False
        layout.addWidget(self.divisor, 1)

        rodape = QHBoxLayout()
        self.aviso = QLabel("")
        self.aviso.setObjectName("statusCobranca")
        self.aviso.setWordWrap(True)
        rodape.addWidget(self.aviso, 1)
        fechar = widgets.QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        registrar = widgets.QPushButton("Marcar como cobrado")
        registrar.setObjectName("primario")
        registrar.setShortcut("Ctrl+Return")
        registrar.setToolTip("Registra a cobrança dos honorários marcados (Ctrl+Enter)")
        registrar.clicked.connect(self._registrar)
        rodape.addWidget(fechar)
        rodape.addWidget(registrar)
        layout.addLayout(rodape)

    def _topo(self) -> QHBoxLayout:
        """Quem está sendo cobrado e, à direita, a soma: valor + juros = total."""
        topo = QHBoxLayout()
        topo.setSpacing(16)
        cabecalho = widgets.Cabecalho(
            f"Cobrar {self.cliente.nome}",
            f"Código {self.cliente.codigo} · {self.cliente.tipo_pessoa.rotulo}",
        )
        topo.addWidget(cabecalho, 1)

        resumo = QFrame()
        resumo.setObjectName("resumoCobranca")
        caixa = QVBoxLayout(resumo)
        caixa.setContentsMargins(16, 10, 18, 10)
        caixa.setSpacing(2)
        soma = QHBoxLayout()
        soma.setSpacing(14)

        def coluna(rotulo: str, valor: QLabel) -> QVBoxLayout:
            bloco = QVBoxLayout()
            bloco.setSpacing(0)
            titulo = QLabel(rotulo)
            titulo.setObjectName("resumoRotulo")
            bloco.addWidget(titulo)
            bloco.addWidget(valor)
            return bloco

        def sinal(texto: str) -> QLabel:
            rotulo = QLabel(texto)
            rotulo.setObjectName("resumoSinal")
            return rotulo

        self.resumo_valor = QLabel("—")
        self.resumo_valor.setObjectName("resumoValor")
        self.resumo_juros = QLabel("—")
        self.resumo_juros.setObjectName("resumoValor")
        self.total = ValorDestaque()
        soma.addLayout(coluna("Valor", self.resumo_valor))
        soma.addWidget(sinal("+"), 0, Qt.AlignmentFlag.AlignBottom)
        soma.addLayout(coluna("Juros", self.resumo_juros))
        soma.addWidget(sinal("="), 0, Qt.AlignmentFlag.AlignBottom)
        soma.addLayout(coluna("Total a cobrar", self.total))
        caixa.addLayout(soma)
        self.resumo_totais = QLabel("")
        self.resumo_totais.setObjectName("resumoRotulo")
        caixa.addWidget(self.resumo_totais)
        topo.addWidget(resumo, 0, Qt.AlignmentFlag.AlignTop)
        return topo

    # ------------------------------------------------- esquerda: o que se cobra
    def _coluna_esquerda(self) -> QWidget:
        coluna = QWidget()
        layout = QVBoxLayout(coluna)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        # as datas (que ficam à direita) nascem antes da lista: a conta depende delas
        self._cartao_datas = self._etapa_datas()
        layout.addWidget(self._etapa_honorarios(), 3)
        layout.addWidget(self._etapa_conferencia(), 2)
        return coluna

    def _etapa_honorarios(self) -> QFrame:
        cartao, corpo, topo = _etapa(
            1, "Quais honorários vão na cobrança",
            "Marque os que entram. Clique num honorário para conferir ou mudar os juros.")
        topo.addWidget(_link("Marcar todos", lambda: (self.modelo.marcar_todos(True),
                                                      self._gerar())),
                       0, Qt.AlignmentFlag.AlignTop)
        topo.addWidget(_link("Desmarcar todos", lambda: (self.modelo.marcar_todos(False),
                                                         self._gerar())),
                       0, Qt.AlignmentFlag.AlignTop)
        self.modelo = ModeloTabelaMarcavel(self._colunas(), self.linhas)
        # a coluna que estica é a do honorário, que muda de lugar com a do titular
        indice = next(i for i, c in enumerate(self.modelo.colunas) if c.titulo == "Honorário")
        self.tabela = preparar_tabela(QTableView(), esticar=indice)
        # sem espaço, o nome do honorário encolhe (com "…") e o total continua à vista
        self.tabela.largura_minima_esticada = LARGURA_MINIMA_HONORARIO
        self.tabela.setModel(self.modelo)
        self.tabela.setSortingEnabled(False)
        self.tabela.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.tabela.verticalHeader().setDefaultSectionSize(30)
        self.modelo.dataChanged.connect(lambda *_: self._gerar())
        self.tabela.selectionModel().currentRowChanged.connect(
            lambda atual, _anterior: self._escolher_para_editar(atual.row()))
        self.tabela.doubleClicked.connect(lambda *_: self.juros_editor.setFocus())
        ajustar_colunas(self.tabela, self.modelo.colunas)
        self._largura_vencimento = self.tabela.columnWidth(
            next(i for i, c in enumerate(self.modelo.colunas) if c.titulo == "Venceu em"))
        corpo.addWidget(self.tabela, 1)
        self.incluir_vinculados = QCheckBox(
            f"Incluir {len(self.linhas_vinculados)} honorário(s) de "
            f"{len({linha.cliente.id for linha in self.linhas_vinculados})} pessoa(s) "
            "que pagam por esta empresa"
        )
        self.incluir_vinculados.setVisible(bool(self.linhas_vinculados))
        self.incluir_vinculados.toggled.connect(self._alternar_vinculados)
        corpo.addWidget(self.incluir_vinculados)
        self._ajustar_altura_da_lista()
        return cartao

    def _ajustar_altura_da_lista(self) -> None:
        """A lista nunca fica menor que algumas linhas; o resto do espaço é dela também.

        Altura travada não serve: com a letra maior do Windows (125%, 150%) a conta
        não bate e a lista ficava curta demais até para rolar.
        """
        linhas = max(1, min(self.modelo.rowCount(), LINHAS_MINIMAS))
        altura = (self.tabela.horizontalHeader().sizeHint().height()
                  + self.tabela.verticalHeader().defaultSectionSize() * linhas
                  + 2 * self.tabela.frameWidth() + 4)
        self.tabela.setMinimumHeight(altura)

    def _etapa_conferencia(self) -> QFrame:
        cartao, corpo, _ = _etapa(
            2, "Conferência dos juros",
            "Juros = juros por dia do cliente × dias de atraso. Confira a conta de cada "
            "honorário marcado.")
        self.conferencia = QTextBrowser()
        self.conferencia.setObjectName("conferencia")
        self.conferencia.setOpenLinks(False)
        self.conferencia.setMinimumHeight(100)
        corpo.addWidget(self.conferencia, 1)

        editor = QFrame()
        editor.setObjectName("editorJuros")
        linha = QHBoxLayout(editor)
        linha.setContentsMargins(12, 8, 12, 8)
        linha.setSpacing(10)
        self.editado_rotulo = QLabel("")
        self.editado_rotulo.setTextFormat(Qt.TextFormat.RichText)
        self.editado_rotulo.setWordWrap(True)
        linha.addWidget(self.editado_rotulo, 1)
        self.juros_editor = CampoMoeda()
        self.juros_editor.setMinimumWidth(130)
        self.juros_editor.setToolTip("Digite os juros e tecle Enter (ou saia do campo)")
        self.juros_editor.editingFinished.connect(self._aplicar_juros_digitado)
        linha.addWidget(self.juros_editor)
        self.botao_calculado = widgets.QPushButton("Usar o calculado")
        self.botao_calculado.setToolTip("Desfaz os juros digitados e volta à conta do sistema")
        self.botao_calculado.clicked.connect(self._voltar_ao_calculado)
        linha.addWidget(self.botao_calculado)
        corpo.addWidget(editor)
        return cartao

    def _etapa_datas(self) -> QFrame:
        cartao, corpo, _ = _etapa(
            3, "Datas",
            "Os juros vão até a data dos valores. O vencimento é só o prazo para pagar "
            "(na imagem e no lembrete): não aumenta os juros.")
        formulario = QFormLayout()
        # tela estreita (notebook): o rótulo sobe para cima do campo em vez de espremer
        formulario.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        formulario.setHorizontalSpacing(14)
        formulario.setVerticalSpacing(10)
        hoje = self.contexto.data_referencia
        (self.usar_hoje, self.usar_outra_data), valores = _segmentos(
            self, f"Hoje ({formatar_data(hoje)})", "Outra data")
        self.data_referencia = CampoData(hoje)
        self.data_referencia.setEnabled(False)
        self.usar_hoje.toggled.connect(self._trocar_data_dos_valores)
        self.data_referencia.dateChanged.connect(self._data_digitada)
        valores.addWidget(self.data_referencia)
        valores.addStretch(1)
        formulario.addRow("Valores atualizados até:", valores)
        venc = QHBoxLayout()
        venc.setSpacing(6)
        self.pagar_ate = CampoData(hoje)
        self.pagar_ate.dateChanged.connect(self._vencimento_digitado)
        venc.addWidget(self.pagar_ate)
        self.botao_vencimento = _link("Voltar ao automático", self._vencimento_automatico)
        self.botao_vencimento.setToolTip(
            "A data dos valores ou, quando nada marcado está atrasado, o vencimento do "
            "próprio honorário")
        venc.addWidget(self.botao_vencimento)
        venc.addStretch(1)
        formulario.addRow("Vencimento (pagar até):", venc)
        corpo.addLayout(formulario)
        return cartao

    def _colunas(self) -> list[Coluna]:
        cor = lambda linha: cores.cor_de_linha(linha)  # noqa: E731
        colunas = [Coluna("", lambda linha: "", largura=28)]
        if self.linhas_vinculados:
            # a coluna só existe quando há honorário de outra pessoa na lista
            colunas.append(Coluna(
                "Titular",
                lambda linha: ("a empresa" if linha.cliente.id == self.cliente.id
                               else linha.cliente.nome),
                dica=lambda linha: linha.cliente.nome,
                largura=160,
            ))

        def juros(linha):
            texto = formatar_moeda(linha.atualizacao.juros)
            return f"✎ {texto}" if linha.atualizacao.juros_manual else texto

        def dica_juros(linha):
            if linha.atualizacao.juros_manual:
                return (f"Digitado à mão. O cálculo dava "
                        f"{formatar_moeda(linha.atualizacao.juros_calculado)}.")
            return "\n".join(calculo.explicar(linha.atualizacao))

        return colunas + [
            Coluna("Honorário", _rotulo, cor=cor),
            coluna_data("Venceu em", lambda linha: linha.honorario.vencimento),
            coluna_inteiro("Atraso", lambda linha: linha.atualizacao.dias_atraso, cor=cor,
                           dica=lambda linha: f"{linha.atualizacao.dias_atraso} dia(s) de "
                                              "atraso"),
            Coluna("Juros", juros, alinhamento=Qt.AlignmentFlag.AlignRight
                   | Qt.AlignmentFlag.AlignVCenter, dica=dica_juros),
            coluna_moeda("Total", lambda linha: linha.atualizacao.total, negrito=True),
        ]

    # ---------------------------------------------- direita: como vai para o cliente
    def _coluna_direita(self) -> QWidget:
        coluna = QWidget()
        layout = QVBoxLayout(coluna)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._cartao_datas)
        layout.addWidget(self._etapa_cliente(), 1)
        return coluna

    def _etapa_cliente(self) -> QFrame:
        cartao, corpo, _ = _etapa(
            4, "Para o cliente",
            "Confira a mensagem e a imagem antes de copiar: elas já usam as datas acima "
            "e os valores ao lado.")
        opcoes = QFormLayout()
        opcoes.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        opcoes.setHorizontalSpacing(14)
        opcoes.setVerticalSpacing(10)
        contatos = [c for c in self.cliente.contatos if c.ativo]
        self.combo_contato = ComboRegistros(
            contatos,
            rotulo=lambda c: (
                f"{c.tratamento_ou_nome or c.nome or 'sem nome'} · "
                f"{formatar_telefone(c.telefone) or 'sem telefone'}"
            ),
            vazio="— sem contato —",
        )
        principal = self.cliente.contato_principal
        if principal:
            self.combo_contato.definir(principal.id)
        self.combo_contato.currentIndexChanged.connect(lambda *_: self._gerar())
        opcoes.addRow("Enviar para:", self.combo_contato)
        (self.tipo_cobranca, self.lembrete), tipos = _segmentos(
            self, "Cobrança (em atraso)", "Lembrete (no prazo)")
        self.lembrete.toggled.connect(self._tipo_escolhido)
        tipos.addStretch(1)
        opcoes.addRow("Tipo de mensagem:", tipos)
        self.citar_empresa = QCheckBox("Citar o nome da empresa na mensagem")
        self.citar_empresa.toggled.connect(lambda *_: self._gerar())
        opcoes.addRow("", self.citar_empresa)
        corpo.addLayout(opcoes)

        self.abas = QTabWidget()
        self.abas.addTab(self._aba_mensagem(), "Mensagem de texto")
        self.abas.addTab(self._aba_imagem(), "Imagem")
        self.abas.currentChanged.connect(lambda *_: self._pedir_imagem())
        corpo.addWidget(self.abas, 1)
        dica = widgets.rotulo_fraco(
            "A resposta do cliente se anota depois, na tela Cobranças enviadas.")
        corpo.addWidget(dica)
        return cartao

    def _aba_mensagem(self) -> QWidget:
        pagina = QWidget()
        caixa = QVBoxLayout(pagina)
        caixa.setContentsMargins(10, 10, 10, 10)
        self.texto = QPlainTextEdit()
        self.texto.setPlaceholderText(
            "A mensagem aparece aqui e pode ser editada antes de copiar.")
        caixa.addWidget(self.texto, 1)
        botoes = QHBoxLayout()
        botoes.addStretch(1)
        copiar = widgets.QPushButton("Copiar mensagem")
        copiar.setShortcut("Ctrl+M")
        copiar.setToolTip("Copia o texto (Ctrl+M). Copiar não registra a cobrança.")
        copiar.clicked.connect(self._copiar)
        whatsapp = widgets.QPushButton("Abrir no WhatsApp")
        whatsapp.setShortcut("Ctrl+W")
        whatsapp.setToolTip("Abre a conversa com a mensagem já escrita (Ctrl+W)")
        whatsapp.clicked.connect(self._abrir_whatsapp)
        botoes.addWidget(copiar)
        botoes.addWidget(whatsapp)
        caixa.addLayout(botoes)
        return pagina

    def _aba_imagem(self) -> QWidget:
        pagina = QWidget()
        caixa = QVBoxLayout(pagina)
        caixa.setContentsMargins(10, 10, 10, 10)
        self.previa = QLabel()
        self.previa.setObjectName("previaImagem")
        self.previa.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.previa.setWordWrap(True)
        self.rolagem_imagem = QScrollArea()
        self.rolagem_imagem.setWidgetResizable(True)
        self.rolagem_imagem.setFrameShape(QFrame.Shape.NoFrame)
        self.rolagem_imagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rolagem_imagem.setWidget(self.previa)
        caixa.addWidget(self.rolagem_imagem, 1)
        self.imagem_info = widgets.rotulo_fraco("")
        caixa.addWidget(self.imagem_info)
        self.acordo = QCheckBox("Guardar como acordo: pagando até o vencimento, vale este total")
        self.acordo.setToolTip(
            "Congela os juros na data dos valores: pagando até o vencimento, a baixa "
            "sugere este total. Depois do vencimento, os juros voltam a correr desde o "
            "vencimento original. É guardado quando a imagem é copiada ou salva.")
        caixa.addWidget(self.acordo)
        botoes = QHBoxLayout()
        botoes.addStretch(1)
        salvar = widgets.QPushButton("Salvar imagem…")
        salvar.clicked.connect(self._salvar_imagem)
        self.botao_chave = widgets.QPushButton("Copiar chave Pix")
        self.botao_chave.setToolTip(
            "Para mandar como mensagem depois da imagem: o cliente toca e copia")
        self.botao_chave.clicked.connect(lambda _=False: self.copiar_chave())
        copiar = widgets.QPushButton("Copiar imagem")
        copiar.setShortcut("Ctrl+I")
        copiar.setToolTip("Copia a imagem para colar no WhatsApp com Ctrl+V (Ctrl+I)")
        copiar.clicked.connect(lambda _=False: self.copiar_imagem())
        for botao in (salvar, self.botao_chave, copiar):
            botoes.addWidget(botao)
        caixa.addLayout(botoes)
        return pagina

    # ================================================================== estado
    def _data_dos_valores(self):
        if self.usar_outra_data.isChecked():
            return self.data_referencia.valor()
        return self.contexto.data_referencia

    def _selecao(self) -> cobrancas.Selecao:
        contato_id = self.combo_contato.valor()
        contato = next((c for c in self.cliente.contatos if c.id == contato_id), None)
        return cobrancas.Selecao(
            cliente=self.cliente,
            linhas=self.modelo.marcados(),
            contato=contato,
            citar_empresa=self.citar_empresa.isChecked(),
            data_referencia=self._data_dos_valores(),
            forcar_lembrete=self.lembrete.isChecked(),
            vencimento_lembrete=self.pagar_ate.valor() if self._pagar_ate_a_mao else None,
        )

    # ------------------------------------------------------------------ datas
    def _trocar_data_dos_valores(self, *_args) -> None:
        self.data_referencia.setEnabled(self.usar_outra_data.isChecked())
        self._gerar()

    def _data_digitada(self, *_args) -> None:
        """Mexeu na data: é porque quer outra data, não hoje."""
        if not self.usar_outra_data.isChecked():
            self.usar_outra_data.setChecked(True)   # chama _trocar_data_dos_valores
            return
        self._gerar()

    def _vencimento_digitado(self, *_args) -> None:
        if self._gerando:
            return
        self._pagar_ate_a_mao = True
        self._gerar()

    def _vencimento_automatico(self) -> None:
        self._pagar_ate_a_mao = False
        self._gerar()

    def _vencimento_padrao(self, marcados: list[LinhaHonorario]):
        """A data dos valores; ou, se nada marcado está em atraso, o primeiro vencimento."""
        data = self._data_dos_valores()
        if not marcados or any(linha.atualizacao.dias_atraso > 0 for linha in marcados):
            return data
        return max(data, min(linha.honorario.vencimento for linha in marcados))

    def _tipo_escolhido(self, *_args) -> None:
        if self._gerando:
            return
        self._tipo_a_mao = True
        self._gerar()

    # ------------------------------------------------------------------ juros
    def _escolher_para_editar(self, indice: int) -> None:
        linha = self.modelo.item(indice) if indice >= 0 else None
        self._editada = linha
        self.juros_editor.setVisible(linha is not None)
        self.botao_calculado.setVisible(linha is not None)
        if linha is None:
            self.editado_rotulo.setText(
                "✎ Para cobrar outro valor de juros, clique no honorário na lista acima.")
            return
        self.botao_calculado.setEnabled(linha.atualizacao.juros_manual)
        self.editado_rotulo.setText(f"✎ Juros a cobrar de <b>{escape(_rotulo(linha))}</b>:")
        self.juros_editor.blockSignals(True)
        self.juros_editor.definir(linha.atualizacao.juros)
        self.juros_editor.blockSignals(False)

    def _aplicar_juros_digitado(self) -> None:
        linha = self._editada
        if linha is None:
            return
        valor = self.juros_editor.valor()
        atual = linha.atualizacao
        calculado = atual.juros_calculado if atual.juros_manual else atual.juros
        if valor == calculado:
            self.juros_manuais.pop(linha.honorario.id, None)
        elif valor != atual.juros:
            self.juros_manuais[linha.honorario.id] = valor
        else:
            return
        self._gerar()
        self.botao_calculado.setEnabled(linha.honorario.id in self.juros_manuais)

    def _voltar_ao_calculado(self) -> None:
        if self._editada is None:
            return
        self.juros_manuais.pop(self._editada.honorario.id, None)
        self._gerar()
        self._escolher_para_editar(self.tabela.currentIndex().row())

    def definir_juros(self, linha: LinhaHonorario, juros: Decimal | None) -> None:
        """Juros à mão para um honorário (None volta ao calculado)."""
        if juros is None:
            self.juros_manuais.pop(linha.honorario.id, None)
        else:
            self.juros_manuais[linha.honorario.id] = Decimal(juros)
        self._gerar()

    # ------------------------------------------------------------------ geral
    def _alternar_vinculados(self, marcado: bool) -> None:
        """Acrescenta (ou tira) os honorários das pessoas vinculadas à lista."""
        proprios = [
            linha for linha in self.linhas if linha.honorario.cliente_id == self.cliente.id
        ]
        self.linhas = proprios + (self.linhas_vinculados if marcado else [])
        self.modelo.definir_itens(self.linhas)
        ajustar_colunas(self.tabela, self.modelo.colunas)
        self._ajustar_altura_da_lista()
        self._encaixar_colunas()
        self._gerar()

    def _recalcular(self) -> None:
        """Valores na data escolhida, com os juros digitados à mão por cima."""
        referencia = self._data_dos_valores()
        for linha in self.linhas:
            atual = calculo.atualizar(linha.honorario, referencia)
            manual = self.juros_manuais.get(linha.honorario.id)
            linha.atualizacao = calculo.com_juros_manual(atual, manual) \
                if manual is not None else atual
        if self.linhas:
            self.modelo.dataChanged.emit(
                self.modelo.index(0, 0),
                self.modelo.index(len(self.linhas) - 1, len(self.modelo.colunas) - 1),
            )

    def _gerar(self) -> None:
        if self._gerando:  # _recalcular emite dataChanged, que reentra aqui
            return
        self._gerando = True
        try:
            self._gerar_agora()
        finally:
            self._gerando = False

    def _gerar_agora(self) -> None:
        self._recalcular()
        marcados = self.modelo.marcados()
        if not self._pagar_ate_a_mao:
            self.pagar_ate.definir(self._vencimento_padrao(marcados))
        self.botao_vencimento.setVisible(self._pagar_ate_a_mao)
        algum_em_atraso = any(linha.atualizacao.dias_atraso > 0 for linha in marcados)
        self.tipo_cobranca.setEnabled(algum_em_atraso)
        self.tipo_cobranca.setToolTip("" if algum_em_atraso else
                                      "Nenhum honorário marcado está em atraso")
        if not self._tipo_a_mao or not algum_em_atraso:
            (self.tipo_cobranca if algum_em_atraso else self.lembrete).setChecked(True)

        selecao = self._selecao()
        self._mostrar_resumo(marcados)
        self._mostrar_conferencia(marcados)
        self._imagem_em_dia = False
        self._pedir_imagem()
        if not marcados:
            self.texto.setPlainText("")
            self.aviso.setText("Marque ao menos um honorário para gerar a mensagem.")
            return
        try:
            self.texto.setPlainText(cobrancas.gerar_texto(self.contexto.sessao, selecao))
            self.aviso.setText("")
        except Exception as falha:  # noqa: BLE001
            self.texto.setPlainText("")
            self.aviso.setText(str(falha))

    def _mostrar_resumo(self, marcados: list[LinhaHonorario]) -> None:
        valor = sum((linha.atualizacao.saldo for linha in marcados), start=ZERO)
        juros = sum((linha.atualizacao.juros for linha in marcados), start=ZERO)
        self.resumo_valor.setText(formatar_moeda(valor))
        self.resumo_juros.setText(formatar_moeda(juros))
        self.total.definir(valor + juros)
        manuais = sum(1 for linha in marcados if linha.atualizacao.juros_manual)
        self.resumo_totais.setText(
            f"{len(marcados)} honorário(s) · valores até "
            f"{formatar_data(self._data_dos_valores())}"
            + (f" · {manuais} com juros à mão" if manuais else ""))

    def _mostrar_conferencia(self, marcados: list[LinhaHonorario]) -> None:
        if not marcados:
            self.conferencia.setHtml("<p>Marque ao menos um honorário.</p>")
            return
        paleta = tema.CORES.get(cores.tema_atual(), tema.CORES["claro"])
        fraco, destaque = paleta["texto_fraco"], paleta["destaque_texto"]
        blocos = []
        for linha in marcados:
            atual = linha.atualizacao
            conta = calculo.conta_dos_juros(atual)
            titular = "" if linha.cliente.id == self.cliente.id else f"{linha.cliente.nome}: "
            situacao = f"venceu em {formatar_data(linha.honorario.vencimento)}"
            if atual.dias_atraso:
                situacao += f" · {atual.dias_atraso} dias de atraso"
            partes = [f"<b>{escape(titular + _rotulo(linha))}</b>"
                      f"<span style='color:{fraco}'> &nbsp;· {situacao}</span>"]
            if conta.no_prazo:
                partes.append(f"<span style='color:{paleta['pago']}'>"
                              "Ainda no prazo: sem juros.</span>")
            for faixa in conta.faixas:
                partes.append(f"{faixa.conta} = <b style='color:{destaque}'>"
                              f"{formatar_moeda(faixa.juros)}</b>"
                              f"<span style='color:{fraco}'> &nbsp;({faixa.periodo})</span>")
            if conta.ja_cobrado > 0:
                partes.append(f"<span style='color:{fraco}'>− "
                              f"{formatar_moeda(conta.ja_cobrado)} de juros já cobrados ou "
                              "abonados em pagamentos parciais</span>")
            if conta.mostra_soma:
                partes.append(f"Juros calculados: <b>{formatar_moeda(conta.calculado)}</b>")
            if atual.juros_manual:
                partes.append(
                    f"<span style='background:{paleta['marca']};"
                    f"color:{paleta['texto_sobre_marca']}'>&nbsp;✎ Juros digitados à mão: "
                    f"{formatar_moeda(atual.juros)}&nbsp;</span>"
                    f"<span style='color:{fraco}'> (o cálculo dava "
                    f"{formatar_moeda(conta.calculado)})</span>")
            partes.append(f"<span style='color:{fraco}'>{formatar_moeda(atual.saldo)} + "
                          f"{formatar_moeda(atual.juros)} de juros = </span>"
                          f"<b>{formatar_moeda(atual.total)}</b>")
            blocos.append(
                f"<table width='100%' cellspacing='0' cellpadding='9' "
                f"style='margin-bottom:6px'><tr><td bgcolor='{paleta['superficie']}'>"
                + "<br>".join(partes) + "</td></tr></table>")
        rolagem = self.conferencia.verticalScrollBar().value()
        self.conferencia.setHtml("".join(blocos))
        self.conferencia.verticalScrollBar().setValue(rolagem)

    # ------------------------------------------------------------------ imagem
    def _pedir_imagem(self) -> None:
        """Refaz a prévia logo depois (só quando a aba da imagem está à vista)."""
        if self.abas.currentIndex() == ABA_IMAGEM and not self._imagem_em_dia:
            self._espera_imagem.start()

    def _atualizar_imagem(self) -> bool:
        """Gera a imagem com os valores e as datas da tela. False se não deu."""
        selecao = self._selecao()
        self.imagem = self.dados_imagem = None
        if not selecao.linhas:
            self.previa.setPixmap(QPixmap())
            self.previa.setText("Marque ao menos um honorário para gerar a imagem.")
            self.imagem_info.setText("")
            return False
        try:
            dados = imagem_cobranca.montar(self.contexto.sessao, selecao,
                                           vencimento=self.pagar_ate.valor())
            fundo = imagem_cobranca.caminho_fundo(self.contexto.sessao)
            self.imagem = renderizar(fundo.read_text(encoding="utf-8"), dados)
        except ErroDeNegocio as falha:
            self.previa.setPixmap(QPixmap())
            self.previa.setText(str(falha))
            self.imagem_info.setText("")
            return False
        self.dados_imagem = dados
        self._imagem_em_dia = True
        # na largura da aba (menos a margem e a barra de rolagem vertical)
        largura = max(260, self.rolagem_imagem.viewport().width() - 40)
        self.previa.setPixmap(QPixmap.fromImage(self.imagem).scaledToWidth(
            largura, Qt.TransformationMode.SmoothTransformation))
        info = (f"Valores atualizados até {dados.campos['data']} · vencimento "
                f"{dados.campos['vencimento']} · total {dados.campos['total']}.")
        if dados.qrcode is None:
            info += " Sem QR code: Configurações → Imagem da cobrança → Usar o do escritório."
        self.imagem_info.setText(info)
        return True

    def _imagem_pronta(self) -> bool:
        if self._imagem_em_dia and self.imagem is not None:
            return True
        if self._atualizar_imagem():
            return True
        widgets.aviso(self, self.previa.text() or "Não consegui gerar a imagem.")
        return False

    def _guardar_acordo(self) -> None:
        """Registra o acordo uma vez por combinação de valores e datas."""
        if not self.acordo.isChecked():
            return
        selecao = self._selecao()
        datas = (selecao.data_referencia, self.pagar_ate.valor(),
                 tuple(sorted((linha.honorario.id, linha.atualizacao.total)
                              for linha in selecao.linhas)))
        if self._acordo_registrado == datas:
            return
        from ...servicos import acordos

        def acao():
            try:
                acordos.registrar(
                    self.contexto.sessao, [linha.honorario for linha in selecao.linhas],
                    selecao.data_referencia, self.pagar_ate.valor(),
                    {linha.honorario.id: linha.atualizacao.juros for linha in selecao.linhas
                     if linha.atualizacao.juros_manual},
                )
                self.contexto.salvar()
            except Exception:
                self.contexto.desfazer()
                raise

        if widgets.executar(self, acao)[0]:
            self._acordo_registrado = datas

    def _chave(self) -> str:
        from ...servicos import configuracoes

        return configuracoes.recebedor(self.contexto.sessao).chave

    def copiar_imagem(self) -> None:
        if not self._imagem_pronta():
            return
        copiar_imagem(self.imagem, self._chave())
        self._guardar_acordo()
        self.aviso.setText(
            "1/2 · Imagem copiada: cole na conversa (Ctrl+V)."
            + (" Depois clique em Copiar chave Pix e cole como mensagem." if self._chave()
               else "") + (" Acordo guardado." if self._acordo_registrado else ""))
        if self._chave():   # o segundo passo, em destaque
            self.botao_chave.setObjectName("primario")
            self.botao_chave.setText("2/2 · Copiar chave Pix")
            self.botao_chave.style().unpolish(self.botao_chave)
            self.botao_chave.style().polish(self.botao_chave)

    def copiar_chave(self) -> None:
        chave = self._chave()
        if not chave:
            widgets.aviso(self, "Cadastre a chave Pix em Configurações → Recebedor e PIX.")
            return
        widgets.copiar(chave)
        self.aviso.setText("2/2 · Chave Pix copiada: cole como mensagem logo depois da imagem.")

    def _salvar_imagem(self) -> None:
        if not self._imagem_pronta():
            return
        nome = f"cobranca_{self.cliente.codigo}_{self._data_dos_valores():%Y-%m-%d}.png"
        destino, _ = QFileDialog.getSaveFileName(
            self, "Salvar imagem", str(pasta_exportacoes() / nome), "PNG (*.png)")
        if not destino:
            return
        if not destino.lower().endswith(".png"):
            destino += ".png"
        if self.imagem.save(destino, "PNG"):
            self._guardar_acordo()
            self.aviso.setText(f"Imagem salva em {destino}."
                               + (" Acordo guardado." if self._acordo_registrado else ""))
        else:
            widgets.erro(self, f"Não foi possível salvar em {destino}.")

    # --------------------------------------------------------------- mensagem
    def _copiar(self) -> None:
        texto = self.texto.toPlainText().strip()
        if not texto:
            widgets.aviso(self, "Não há mensagem para copiar.")
            return
        widgets.copiar(texto)
        self.aviso.setText("Mensagem copiada. Copiar não registra a cobrança.")

    def _abrir_whatsapp(self) -> None:
        texto = self.texto.toPlainText().strip()
        if not texto:
            widgets.aviso(self, "Gere a mensagem antes de abrir o WhatsApp.")
            return
        selecao = self._selecao()
        contato = selecao.contato or self.cliente.contato_principal

        def acao():
            link = cobrancas.link_whatsapp(self.contexto.sessao, contato, texto)
            widgets.copiar(texto)
            if not widgets.abrir_url(link):
                raise RuntimeError(
                    "Não foi possível abrir o navegador. A mensagem ficou copiada."
                )
            return link

        deu_certo, _ = widgets.executar(self, acao)
        if deu_certo:
            self.aviso.setText(
                "WhatsApp aberto e mensagem copiada. Registre a cobrança se enviou."
            )

    def _registrar(self) -> None:
        selecao = self._selecao()
        if not selecao.linhas:
            widgets.aviso(self, "Marque os honorários que você cobrou.")
            return
        detalhe = "\n".join(
            f"• {_rotulo(linha)} – {formatar_moeda(linha.atualizacao.total)}"
            + (" (juros digitado à mão)" if linha.atualizacao.juros_manual else "")
            for linha in selecao.linhas
        )
        if not widgets.confirmar(
            self,
            f"Registrar cobrança de {len(selecao.linhas)} honorário(s), "
            f"total {formatar_moeda(selecao.total)}?",
            "Marcar como cobrado",
            detalhe,
        ):
            return

        def acao():
            # nasce aguardando resposta; o retorno entra depois, em Cobranças enviadas
            cobrancas.registrar(
                self.contexto.sessao,
                selecao,
                texto=self.texto.toPlainText().strip(),
                canal=Canal.WHATSAPP,
            )
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.registrou = True
        self.accept()


def cobrar_honorarios(parent, contexto: Contexto, honorarios) -> bool:
    """Abre o "Cobrar" com estes honorários (de um cliente só); True se registrou.

    Serve às telas que lançam ou listam honorários soltos — o avulso recém-lançado,
    por exemplo — sem precisar ir até Atrasados ou A vencer para cobrar.
    """
    honorarios = [h for h in honorarios if h.status.cobravel]
    if not honorarios:
        widgets.aviso(parent, "Só dá para cobrar honorário em aberto.")
        return False
    cliente = honorarios[0].cliente
    ids = {h.id for h in honorarios}
    linhas = [
        linha
        for linha in cobrancas.linhas_em_aberto_do_cliente(
            contexto.sessao, cliente.id, contexto.data_referencia
        )
        if linha.honorario.id in ids
    ]
    if not linhas:
        widgets.aviso(parent, "Só dá para cobrar honorário em aberto.")
        return False
    dialogo = DialogoCobrar(contexto, cliente, linhas, parent)
    dialogo.exec()
    return dialogo.registrou
