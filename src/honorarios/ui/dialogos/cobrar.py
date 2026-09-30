"""Diálogo "Cobrar": monta a mensagem, copia, abre o WhatsApp e registra.

Copiar não registra nada — o registro acontece só em "Marcar como cobrado",
porque copiar e não enviar é situação comum.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QTableView,
    QVBoxLayout,
)

from ...dominio.enums import Canal
from ...dominio.valores import formatar_moeda, formatar_telefone
from ...servicos import clientes as servico_clientes
from ...servicos import cobrancas
from ...servicos.honorarios import LinhaHonorario
from ..comum import cores, widgets
from ..comum.campos import CampoData, ComboRegistros, ValorDestaque
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


class DialogoCobrar(QDialog):
    def __init__(self, contexto: Contexto, cliente, linhas: list[LinhaHonorario], parent=None):
        super().__init__(parent)
        self.contexto = contexto
        self.cliente = cliente
        self.linhas = list(linhas)
        self.registrou = False
        self._gerando = False
        # honorários das pessoas físicas que pagam por esta empresa
        self.linhas_vinculados = [
            linha
            for linha in cobrancas.linhas_em_aberto_do_cliente(
                contexto.sessao, cliente.id, contexto.data_referencia, incluir_vinculados=True
            )
            if linha.honorario.cliente_id != cliente.id
        ]
        self.setWindowTitle(f"Cobrar – {cliente.nome}")
        self.resize(940, 720)
        self._montar()
        self._gerar()

    # ------------------------------------------------------------------ layout
    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        cabecalho = widgets.Cabecalho(
            self.cliente.nome, f"Código {self.cliente.codigo} · {self.cliente.tipo_pessoa.rotulo}"
        )
        layout.addWidget(cabecalho)

        suspensao = servico_clientes.suspensao(self.cliente, self.contexto.data_referencia)
        if suspensao:
            aviso = QLabel(
                f"⚠ {suspensao}. Retome a cobrança na ficha do cliente para poder "
                "registrar esta cobrança."
            )
            aviso.setObjectName("avisoForte")
            aviso.setWordWrap(True)
            layout.addWidget(aviso)

        # honorários
        grupo_itens = QGroupBox("Honorários em aberto (desmarque o que não quer cobrar)")
        caixa_itens = QVBoxLayout(grupo_itens)
        self.modelo = ModeloTabelaMarcavel(self._colunas(), self.linhas)
        # a coluna que estica é sempre a do tipo, que muda de lugar quando existe
        # a coluna Titular — esticar a errada faz o Qt ignorar a largura dela
        indice_tipo = next(
            indice
            for indice, coluna in enumerate(self.modelo.colunas)
            if coluna.titulo == "Tipo"
        )
        self.tabela = preparar_tabela(QTableView(), esticar=indice_tipo)
        self.tabela.setModel(self.modelo)
        self.tabela.setSortingEnabled(False)
        self.tabela.setMinimumHeight(150)
        self.modelo.dataChanged.connect(lambda *_: self._gerar())
        ajustar_colunas(self.tabela, self.modelo.colunas)
        caixa_itens.addWidget(self.tabela)

        rodape_itens = QHBoxLayout()
        botao_todos = widgets.QPushButton("Marcar todos")
        botao_todos.clicked.connect(lambda: (self.modelo.marcar_todos(True), self._gerar()))
        botao_nenhum = widgets.QPushButton("Desmarcar todos")
        botao_nenhum.clicked.connect(lambda: (self.modelo.marcar_todos(False), self._gerar()))
        rodape_itens.addWidget(botao_todos)
        rodape_itens.addWidget(botao_nenhum)
        rodape_itens.addStretch(1)
        rodape_itens.addWidget(QLabel("Total selecionado:"))
        self.total = ValorDestaque()
        rodape_itens.addWidget(self.total)
        caixa_itens.addLayout(rodape_itens)
        layout.addWidget(grupo_itens)

        # opções
        grupo_opcoes = QGroupBox("Mensagem")
        opcoes = QFormLayout(grupo_opcoes)
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
        opcoes.addRow("Contato:", self.combo_contato)

        self.citar_empresa = QCheckBox("Citar o nome da empresa na mensagem")
        self.citar_empresa.toggled.connect(lambda *_: self._gerar())
        opcoes.addRow("", self.citar_empresa)

        self.incluir_vinculados = QCheckBox(
            f"Incluir {len(self.linhas_vinculados)} honorário(s) de "
            f"{len({linha.cliente.id for linha in self.linhas_vinculados})} pessoa(s) "
            "que pagam por esta empresa"
        )
        self.incluir_vinculados.setVisible(bool(self.linhas_vinculados))
        self.incluir_vinculados.toggled.connect(self._alternar_vinculados)
        opcoes.addRow("", self.incluir_vinculados)

        self.data_referencia = CampoData(self.contexto.data_referencia)
        self.data_referencia.dateChanged.connect(lambda *_: self._gerar())
        opcoes.addRow("Data de referência:", self.data_referencia)

        self.lembrete = QCheckBox("Usar o modelo de lembrete (antes do vencimento)")
        self.lembrete.toggled.connect(lambda *_: self._gerar())
        opcoes.addRow("", self.lembrete)
        layout.addWidget(grupo_opcoes)

        self.texto = QPlainTextEdit()
        self.texto.setPlaceholderText("A mensagem aparece aqui e pode ser editada antes de copiar.")
        self.texto.setMinimumHeight(190)
        layout.addWidget(self.texto, 1)

        layout.addWidget(
            widgets.rotulo_fraco(
                "A resposta do cliente não se anota agora: quando ela chegar, use a "
                "tela Acompanhamento."
            )
        )

        acoes = QHBoxLayout()
        self.aviso = widgets.rotulo_fraco("")
        acoes.addWidget(self.aviso, 1)
        botao_copiar = widgets.QPushButton("Copiar mensagem")
        botao_copiar.setShortcut("Ctrl+C")
        botao_copiar.clicked.connect(self._copiar)
        botao_whats = widgets.QPushButton("Abrir no WhatsApp")
        botao_whats.setShortcut("Ctrl+W")
        botao_whats.clicked.connect(self._abrir_whatsapp)
        botao_registrar = widgets.QPushButton("Marcar como cobrado")
        botao_registrar.setObjectName("primario")
        botao_registrar.setShortcut("Ctrl+Return")
        botao_registrar.clicked.connect(self._registrar)
        botao_fechar = widgets.QPushButton("Fechar")
        botao_fechar.clicked.connect(self.reject)
        for botao in (botao_copiar, botao_whats, botao_registrar, botao_fechar):
            acoes.addWidget(botao)
        layout.addLayout(acoes)

    def _colunas(self) -> list[Coluna]:
        cor = lambda linha: cores.cor_de_linha(linha)  # noqa: E731
        colunas = [Coluna("", lambda linha: "", largura=28)]
        if self.linhas_vinculados:
            # a coluna só existe quando há honorário de outra pessoa na lista
            colunas.append(
                Coluna(
                    "Titular",
                    lambda linha: (
                        "a empresa"
                        if linha.cliente.id == self.cliente.id
                        else linha.cliente.nome
                    ),
                    dica=lambda linha: linha.cliente.nome,
                    largura=180,
                )
            )
        return colunas + [
            Coluna("Tipo", lambda linha: linha.honorario.tipo.nome, cor=cor),
            Coluna(
                "Competência",
                lambda linha: linha.honorario.competencia_rotulo,
                alinhamento=Qt.AlignmentFlag.AlignCenter,
            ),
            coluna_data("Vencimento", lambda linha: linha.honorario.vencimento),
            coluna_inteiro("Atraso", lambda linha: linha.atualizacao.dias_atraso, cor=cor),
            coluna_moeda("Valor", lambda linha: linha.atualizacao.valor_original),
            coluna_moeda("Juros", lambda linha: linha.atualizacao.juros),
            coluna_moeda("Total atualizado", lambda linha: linha.atualizacao.total, negrito=True),
        ]

    # ------------------------------------------------------------------ ações
    def _alternar_vinculados(self, marcado: bool) -> None:
        """Acrescenta (ou tira) os honorários das pessoas vinculadas à lista."""
        proprios = [
            linha for linha in self.linhas if linha.honorario.cliente_id == self.cliente.id
        ]
        self.linhas = proprios + (self.linhas_vinculados if marcado else [])
        self.modelo.definir_itens(self.linhas)
        ajustar_colunas(self.tabela, self.modelo.colunas)
        self._gerar()

    def _selecao(self) -> cobrancas.Selecao:
        contato_id = self.combo_contato.valor()
        contato = next((c for c in self.cliente.contatos if c.id == contato_id), None)
        return cobrancas.Selecao(
            cliente=self.cliente,
            linhas=self.modelo.marcados(),
            contato=contato,
            citar_empresa=self.citar_empresa.isChecked(),
            data_referencia=self.data_referencia.valor(),
            forcar_lembrete=self.lembrete.isChecked(),
        )

    def _recalcular(self) -> None:
        """Recalcula os totais quando a data de referência muda (simulação)."""
        from ...servicos import calculo

        referencia = self.data_referencia.valor()
        for linha in self.linhas:
            linha.atualizacao = calculo.atualizar(linha.honorario, referencia)
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
        selecao = self._selecao()
        self.total.definir(selecao.total)
        if not selecao.linhas:
            self.texto.setPlainText("")
            self.aviso.setText("Marque ao menos um honorário para gerar a mensagem.")
            return
        try:
            self.texto.setPlainText(cobrancas.gerar_texto(self.contexto.sessao, selecao))
            self.aviso.setText("")
        except Exception as falha:  # noqa: BLE001
            self.texto.setPlainText("")
            self.aviso.setText(str(falha))

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
            f"• {linha.honorario.tipo.nome} {linha.honorario.competencia_rotulo} – "
            f"{formatar_moeda(linha.atualizacao.total)}"
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
            # nasce aguardando resposta; o retorno entra depois, no Acompanhamento
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
