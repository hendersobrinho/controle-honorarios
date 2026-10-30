"""Tela "Cobrar": escolher, conferir a conta, acertar as datas e mandar.

Tudo numa tela só, em passos numerados:

1. **Quais honorários** vão na cobrança.
2. **Conferência**: a conta dos juros de cada um (dias × juros por dia), com a
   opção de digitar outro valor de juros à mão.
3. **Datas**: até quando os valores são atualizados (hoje, ou outra data) e o
   vencimento — o "pagar até" da imagem e do lembrete, que não mexe nos juros.
4. **Mensagem e imagem**, já com essas datas e esses valores, para conferir
   antes de copiar.

Copiar não registra nada — o registro acontece só em "Marcar como cobrado",
porque copiar e não enviar é situação comum.
"""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QTableView,
    QTabWidget,
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
from ..comum import cores, widgets
from ..comum.campos import CampoData, CampoMoeda, ComboRegistros, ValorDestaque
from ..comum.imagem_cobranca import copiar_imagem, renderizar
from ..comum.tabelas import (
    Coluna,
    ModeloTabelaMarcavel,
    ajustar_colunas,
    coluna_data,
    coluna_inteiro,
    coluna_moeda,
    preparar_tabela,
)
from ..contexto import Contexto

ABA_MENSAGEM, ABA_IMAGEM = 0, 1


def _rotulo(linha: LinhaHonorario) -> str:
    honorario = linha.honorario
    competencia = honorario.competencia_rotulo or honorario.descricao
    if not competencia or competencia.startswith(honorario.tipo.nome):
        return competencia or honorario.tipo.nome
    return f"{honorario.tipo.nome} · {competencia}"


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
        self.setWindowTitle(f"Cobrar – {cliente.nome}")
        self.resize(1280, 860)
        self._montar()
        self._escolher_para_editar(-1)
        self._gerar()

    # ================================================================== layout
    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(widgets.Cabecalho(
            f"Cobrar {self.cliente.nome}",
            f"Código {self.cliente.codigo} · {self.cliente.tipo_pessoa.rotulo}",
        ))

        suspensao = servico_clientes.suspensao(self.cliente, self.contexto.data_referencia)
        if suspensao:
            aviso = QLabel(
                f"⚠ {suspensao}. Retome a cobrança na ficha do cliente para poder "
                "registrar esta cobrança."
            )
            aviso.setObjectName("avisoForte")
            aviso.setWordWrap(True)
            layout.addWidget(aviso)

        divisor = QSplitter(Qt.Orientation.Horizontal)
        divisor.setChildrenCollapsible(False)
        divisor.addWidget(self._coluna_esquerda())
        divisor.addWidget(self._coluna_direita())
        divisor.setSizes([760, 480])
        layout.addWidget(divisor, 1)
        layout.addLayout(self._barra_de_acoes())

    # ----------------------------------------------------------- 1, 2 e 3
    def _coluna_esquerda(self) -> QWidget:
        coluna = QWidget()
        layout = QVBoxLayout(coluna)
        layout.setContentsMargins(0, 0, 6, 0)

        # 3. datas
        datas_grupo = QGroupBox("3. Datas")
        datas = QFormLayout(datas_grupo)
        valores = QHBoxLayout()
        hoje = self.contexto.data_referencia
        self.usar_hoje = QRadioButton(f"Hoje ({formatar_data(hoje)})")
        self.usar_outra_data = QRadioButton("Outra data:")
        grupo_datas = QButtonGroup(self)
        grupo_datas.addButton(self.usar_hoje)
        grupo_datas.addButton(self.usar_outra_data)
        self.usar_hoje.setChecked(True)
        self.data_referencia = CampoData(hoje)
        self.data_referencia.setEnabled(False)
        self.usar_hoje.toggled.connect(self._trocar_data_dos_valores)
        self.data_referencia.dateChanged.connect(self._data_digitada)
        for widget in (self.usar_hoje, self.usar_outra_data, self.data_referencia):
            valores.addWidget(widget)
        valores.addStretch(1)
        datas.addRow("Valores atualizados até:", valores)
        venc = QHBoxLayout()
        self.pagar_ate = CampoData(hoje)
        self.pagar_ate.dateChanged.connect(self._vencimento_digitado)
        venc.addWidget(self.pagar_ate)
        self.botao_vencimento = widgets.QPushButton("Automático")
        self.botao_vencimento.setToolTip(
            "Volta ao padrão: a data dos valores, ou o vencimento do honorário quando "
            "ele ainda está no prazo")
        self.botao_vencimento.clicked.connect(self._vencimento_automatico)
        venc.addWidget(self.botao_vencimento)
        venc.addStretch(1)
        datas.addRow("Vencimento (pagar até):", venc)
        explicacao = widgets.rotulo_fraco(
            "Os juros vão até a data dos valores. O vencimento é o prazo para pagar que "
            "aparece na imagem (e no lembrete): não aumenta os juros."
        )
        datas.addRow(explicacao)

        # 1. honorários
        grupo = QGroupBox("1. Quais honorários vão na cobrança")
        caixa = QVBoxLayout(grupo)
        self.modelo = ModeloTabelaMarcavel(self._colunas(), self.linhas)
        # a coluna que estica é a do honorário, que muda de lugar com a do titular
        indice = next(i for i, c in enumerate(self.modelo.colunas) if c.titulo == "Honorário")
        self.tabela = preparar_tabela(QTableView(), esticar=indice)
        self.tabela.setModel(self.modelo)
        self.tabela.setSortingEnabled(False)
        self.tabela.setMinimumHeight(140)
        self.modelo.dataChanged.connect(lambda *_: self._gerar())
        self.tabela.selectionModel().currentRowChanged.connect(
            lambda atual, _anterior: self._escolher_para_editar(atual.row()))
        self.tabela.doubleClicked.connect(lambda *_: self.juros_editor.setFocus())
        ajustar_colunas(self.tabela, self.modelo.colunas)
        caixa.addWidget(self.tabela)
        linha = QHBoxLayout()
        todos = widgets.QPushButton("Marcar todos")
        todos.clicked.connect(lambda: (self.modelo.marcar_todos(True), self._gerar()))
        nenhum = widgets.QPushButton("Desmarcar todos")
        nenhum.clicked.connect(lambda: (self.modelo.marcar_todos(False), self._gerar()))
        linha.addWidget(todos)
        linha.addWidget(nenhum)
        linha.addStretch(1)
        caixa.addLayout(linha)
        self.incluir_vinculados = QCheckBox(
            f"Incluir {len(self.linhas_vinculados)} honorário(s) de "
            f"{len({linha.cliente.id for linha in self.linhas_vinculados})} pessoa(s) "
            "que pagam por esta empresa"
        )
        self.incluir_vinculados.setVisible(bool(self.linhas_vinculados))
        self.incluir_vinculados.toggled.connect(self._alternar_vinculados)
        caixa.addWidget(self.incluir_vinculados)
        layout.addWidget(grupo, 3)

        # 2. conferência
        grupo = QGroupBox("2. Conferência dos juros")
        caixa = QVBoxLayout(grupo)
        caixa.addWidget(widgets.rotulo_fraco(
            "Juros = juros por dia do cliente × dias de atraso. Confira a conta de cada "
            "honorário marcado; para cobrar outro valor de juros, clique no honorário na "
            "lista acima e digite abaixo."
        ))
        self.conferencia = QPlainTextEdit()
        self.conferencia.setReadOnly(True)
        self.conferencia.setMinimumHeight(120)
        caixa.addWidget(self.conferencia, 1)
        editar = QHBoxLayout()
        self.editado_rotulo = QLabel("Juros a cobrar do honorário selecionado:")
        editar.addWidget(self.editado_rotulo)
        self.juros_editor = CampoMoeda()
        self.juros_editor.setToolTip("Digite o juros e tecle Enter (ou saia do campo)")
        self.juros_editor.editingFinished.connect(self._aplicar_juros_digitado)
        editar.addWidget(self.juros_editor)
        self.botao_calculado = widgets.QPushButton("Usar o juros calculado")
        self.botao_calculado.clicked.connect(self._voltar_ao_calculado)
        editar.addWidget(self.botao_calculado)
        editar.addStretch(1)
        caixa.addLayout(editar)
        layout.addWidget(grupo, 3)

        layout.addWidget(datas_grupo)

        # totais
        totais = QHBoxLayout()
        self.resumo_totais = widgets.rotulo_fraco("")
        totais.addWidget(self.resumo_totais, 1)
        totais.addWidget(QLabel("Total a cobrar:"))
        self.total = ValorDestaque()
        totais.addWidget(self.total)
        layout.addLayout(totais)
        return coluna

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
            return f"{texto} ✎" if linha.atualizacao.juros_manual else texto

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
            coluna_moeda("Valor", lambda linha: linha.atualizacao.saldo),
            Coluna("Juros", juros, alinhamento=Qt.AlignmentFlag.AlignRight
                   | Qt.AlignmentFlag.AlignVCenter, dica=dica_juros),
            coluna_moeda("Total", lambda linha: linha.atualizacao.total, negrito=True),
        ]

    # --------------------------------------------------------------------- 4
    def _coluna_direita(self) -> QWidget:
        coluna = QWidget()
        layout = QVBoxLayout(coluna)
        layout.setContentsMargins(6, 0, 0, 0)
        grupo = QGroupBox("4. Mensagem e imagem")
        caixa = QVBoxLayout(grupo)
        opcoes = QFormLayout()
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

        tipos = QHBoxLayout()
        self.tipo_cobranca = QRadioButton("Cobrança (em atraso)")
        self.lembrete = QRadioButton("Lembrete (ainda no prazo)")
        grupo_tipo = QButtonGroup(self)
        grupo_tipo.addButton(self.tipo_cobranca)
        grupo_tipo.addButton(self.lembrete)
        self.tipo_cobranca.setChecked(True)
        self.lembrete.toggled.connect(self._tipo_escolhido)
        tipos.addWidget(self.tipo_cobranca)
        tipos.addWidget(self.lembrete)
        tipos.addStretch(1)
        opcoes.addRow("Tipo de mensagem:", tipos)
        self.citar_empresa = QCheckBox("Citar o nome da empresa na mensagem")
        self.citar_empresa.toggled.connect(lambda *_: self._gerar())
        opcoes.addRow("", self.citar_empresa)
        caixa.addLayout(opcoes)

        self.abas = QTabWidget()
        texto = QWidget()
        caixa_texto = QVBoxLayout(texto)
        caixa_texto.setContentsMargins(0, 6, 0, 0)
        self.texto = QPlainTextEdit()
        self.texto.setPlaceholderText(
            "A mensagem aparece aqui e pode ser editada antes de copiar.")
        caixa_texto.addWidget(self.texto, 1)
        self.abas.addTab(texto, "Mensagem de texto")

        imagem = QWidget()
        caixa_imagem = QVBoxLayout(imagem)
        caixa_imagem.setContentsMargins(0, 6, 0, 0)
        self.previa = QLabel()
        self.previa.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.previa.setWordWrap(True)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setWidget(self.previa)
        caixa_imagem.addWidget(rolagem, 1)
        self.imagem_info = widgets.rotulo_fraco("")
        caixa_imagem.addWidget(self.imagem_info)
        self.acordo = QCheckBox("Guardar como acordo: pagando até o vencimento, vale este total")
        self.acordo.setToolTip(
            "Congela os juros na data dos valores: pagando até o vencimento, a baixa "
            "sugere este total. Depois do vencimento, os juros voltam a correr desde o "
            "vencimento original. É guardado quando a imagem é copiada ou salva.")
        caixa_imagem.addWidget(self.acordo)
        self.abas.addTab(imagem, "Imagem")
        self.abas.currentChanged.connect(lambda *_: self._pedir_imagem())
        caixa.addWidget(self.abas, 1)
        layout.addWidget(grupo, 1)
        layout.addWidget(widgets.rotulo_fraco(
            "A resposta do cliente se anota depois, na tela Cobranças enviadas."))
        return coluna

    def _barra_de_acoes(self) -> QHBoxLayout:
        acoes = QHBoxLayout()
        self.aviso = widgets.rotulo_fraco("")
        acoes.addWidget(self.aviso, 1)
        botoes = (
            ("Copiar mensagem", "Ctrl+M", self._copiar, "Copia o texto (não registra)"),
            ("Abrir no WhatsApp", "Ctrl+W", self._abrir_whatsapp,
             "Abre a conversa com a mensagem escrita"),
            ("Copiar imagem", "Ctrl+I", self.copiar_imagem,
             "Copia a imagem para colar no WhatsApp (Ctrl+V)"),
            ("Copiar chave Pix", "", self.copiar_chave,
             "Para mandar como mensagem depois da imagem: o cliente toca e copia"),
            ("Salvar imagem…", "", self._salvar_imagem, "Salva a imagem em PNG"),
        )
        for texto, atalho, funcao, dica in botoes:
            botao = widgets.QPushButton(texto)
            if atalho:
                botao.setShortcut(atalho)
            botao.setToolTip(dica)
            botao.clicked.connect(lambda _=False, f=funcao: f())
            acoes.addWidget(botao)
            if texto == "Copiar chave Pix":
                self.botao_chave = botao
        registrar = widgets.QPushButton("Marcar como cobrado")
        registrar.setObjectName("primario")
        registrar.setShortcut("Ctrl+Return")
        registrar.setToolTip("Registra a cobrança dos honorários marcados")
        registrar.clicked.connect(self._registrar)
        fechar = widgets.QPushButton("Fechar")
        fechar.clicked.connect(self.reject)
        acoes.addWidget(registrar)
        acoes.addWidget(fechar)
        return acoes

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
        self.juros_editor.setEnabled(linha is not None)
        self.botao_calculado.setEnabled(linha is not None and linha.atualizacao.juros_manual)
        if linha is None:
            self.editado_rotulo.setText("Juros a cobrar do honorário selecionado:")
            return
        self.editado_rotulo.setText(f"Juros a cobrar de {_rotulo(linha)}:")
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
        algum_em_atraso = any(linha.atualizacao.dias_atraso > 0 for linha in marcados)
        self.tipo_cobranca.setEnabled(algum_em_atraso)
        self.tipo_cobranca.setToolTip("" if algum_em_atraso else
                                      "Nenhum honorário marcado está em atraso")
        if not self._tipo_a_mao or not algum_em_atraso:
            (self.tipo_cobranca if algum_em_atraso else self.lembrete).setChecked(True)

        selecao = self._selecao()
        self.total.definir(selecao.total)
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

    def _mostrar_conferencia(self, marcados: list[LinhaHonorario]) -> None:
        if not marcados:
            self.conferencia.setPlainText("Marque ao menos um honorário.")
            self.resumo_totais.setText("")
            return
        blocos = []
        for linha in marcados:
            titular = "" if linha.cliente.id == self.cliente.id else f"{linha.cliente.nome}: "
            cabeca = (f"{titular}{_rotulo(linha)} — venceu em "
                      f"{formatar_data(linha.honorario.vencimento)}")
            blocos.append("\n".join([cabeca] + [f"   {texto}" for texto in
                                                calculo.explicar(linha.atualizacao)]))
        self.conferencia.setPlainText("\n\n".join(blocos))
        valor = sum((linha.atualizacao.saldo for linha in marcados), start=ZERO)
        juros = sum((linha.atualizacao.juros for linha in marcados), start=ZERO)
        manuais = sum(1 for linha in marcados if linha.atualizacao.juros_manual)
        self.resumo_totais.setText(
            f"{len(marcados)} honorário(s) · valor {formatar_moeda(valor)} + juros "
            f"{formatar_moeda(juros)}, até {formatar_data(self._data_dos_valores())}"
            + (f" · {manuais} com juros digitado à mão" if manuais else ""))

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
        self.previa.setPixmap(QPixmap.fromImage(self.imagem).scaledToWidth(
            500, Qt.TransformationMode.SmoothTransformation))
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
