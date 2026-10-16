"""Importação personalizada: a coluna do Excel de cada informação, prévia e gravação."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from ...config.caminhos import pasta_exportacoes
from ...dominio.enums import (
    MeioCobranca,
    Periodicidade,
    SituacaoCliente,
    SituacaoEnvio,
    StatusPagamento,
    SubtipoCliente,
    TipoPessoa,
)
from ...infra.modelos import FormaEnvio, TipoHonorario
from ...servicos.importacao import personalizada
from ..comum import tema, widgets
from ..comum.tabelas import (
    Coluna,
    ModeloTabela,
    ModeloTabelaMarcavel,
    ajustar_colunas,
    preparar_tabela,
)
from ..contexto import Contexto

NOVO_LAYOUT = "(novo layout)"
OPCOES_ENUM = {
    "pessoa": TipoPessoa,
    "subtipo": SubtipoCliente,
    "situacao": SituacaoCliente,
    "periodicidade": Periodicidade,
    "meio": MeioCobranca,
    "status": StatusPagamento,
    "envio": SituacaoEnvio,
}


class PainelImportacaoPersonalizada(QWidget):
    titulo = "Importação personalizada"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.previa: personalizada.Previa | None = None
        self.colunas: dict[str, QLineEdit] = {}
        self.padroes: dict[str, QComboBox | QLineEdit] = {}
        self._montar()
        self._carregar_layouts()

    # ---------------------------------------------------------------- montagem
    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self.cabecalho = widgets.Cabecalho(
            "Importação personalizada",
            "Diga em que coluna do Excel está cada informação. O sistema confere o que "
            "já está cadastrado e só acrescenta o que falta",
        )
        self.cabecalho.adicionar_botao("Exportar modelo…", self._exportar_modelo)
        self.cabecalho.adicionar_botao("Escolher planilha…", self._escolher, primario=True)
        self.cabecalho.adicionar_botao("Importar marcados", self._importar)
        layout.addWidget(self.cabecalho)

        barra = QHBoxLayout()
        barra.addWidget(QLabel("Layout:"))
        self.escolha_layout = QComboBox()
        self.escolha_layout.setMinimumWidth(200)
        self.escolha_layout.currentTextChanged.connect(self._layout_escolhido)
        barra.addWidget(self.escolha_layout)
        self.nome_layout = QLineEdit()
        self.nome_layout.setPlaceholderText("Nome para salvar")
        self.nome_layout.setMaximumWidth(220)
        barra.addWidget(self.nome_layout)
        for texto, funcao in (
            ("Salvar layout", self._salvar_layout),
            ("Excluir layout", self._excluir_layout),
            ("Abrir de um modelo…", self._abrir_modelo),
        ):
            botao = QPushButton(texto)
            botao.clicked.connect(funcao)
            barra.addWidget(botao)
        barra.addSpacing(16)
        barra.addWidget(QLabel("Aba:"))
        self.aba = QLineEdit()
        self.aba.setPlaceholderText("a primeira")
        self.aba.setMaximumWidth(160)
        barra.addWidget(self.aba)
        barra.addWidget(QLabel("Dados a partir da linha:"))
        self.linha_inicial = QSpinBox()
        self.linha_inicial.setRange(1, 1_000_000)
        self.linha_inicial.setValue(2)
        barra.addWidget(self.linha_inicial)
        barra.addStretch(1)
        layout.addLayout(barra)

        self.abas = QTabWidget()
        self.abas.addTab(self._montar_colunas(), "Colunas do layout")

        self.modelo_linhas = ModeloTabelaMarcavel(
            [
                Coluna("", lambda item: "", largura=28),
                Coluna("Linha", lambda item: str(item.linha),
                       ordem=lambda item: item.linha,
                       alinhamento=Qt.AlignmentFlag.AlignCenter),
                Coluna("Cliente", lambda item: item.rotulo_cliente),
                Coluna("Cadastro do cliente", lambda item: item.acao_cliente or "—",
                       dica=lambda item: item.acao_cliente),
                Coluna("Contrato", lambda item: item.acao_contrato or "—",
                       dica=lambda item: item.acao_contrato),
                Coluna("Honorário", lambda item: item.acao_honorario or "—",
                       dica=lambda item: item.acao_honorario),
                Coluna(
                    "Situação",
                    lambda item: (
                        "ERRO: " + "; ".join(p.motivo for p in item.problemas if p.bloqueia)
                        if item.bloqueada
                        else (f"Avisos: {len(item.problemas)}" if item.problemas else "Pronta")
                    ),
                    cor=lambda item: tema.cor("atrasado") if item.bloqueada else None,
                    dica=lambda item: "\n".join(
                        f"[{p.gravidade}] {p.campo}: {p.motivo}" for p in item.problemas
                    ),
                ),
            ]
        )
        self.modelo_linhas.definir_bloqueio(lambda item: item.bloqueada)
        self.tabela_linhas = preparar_tabela(QTableView(), esticar=3)
        self.tabela_linhas.setModel(self.modelo_linhas)
        self.tabela_linhas.setSortingEnabled(False)
        self.abas.addTab(self.tabela_linhas, "Prévia")

        self.modelo_problemas = ModeloTabela(
            [
                Coluna("Gravidade", lambda p: p.gravidade,
                       cor=lambda p: tema.cor("atrasado") if p.bloqueia else tema.cor("atencao"),
                       alinhamento=Qt.AlignmentFlag.AlignCenter),
                Coluna("Linha", lambda p: str(p.linha or "—"),
                       alinhamento=Qt.AlignmentFlag.AlignCenter),
                Coluna("Campo", lambda p: p.campo),
                Coluna("Valor lido", lambda p: p.valor),
                Coluna("O que o sistema fez", lambda p: p.motivo),
            ]
        )
        self.tabela_problemas = preparar_tabela(QTableView(), esticar=4)
        self.tabela_problemas.setModel(self.modelo_problemas)
        self.abas.addTab(self.tabela_problemas, "Relatório de erros e ajustes")
        layout.addWidget(self.abas, 1)

        rodape = QHBoxLayout()
        self.resumo = widgets.rotulo_fraco(
            "Preencha as colunas, escolha a planilha e confira a prévia. Nada é gravado "
            "antes de você confirmar."
        )
        rodape.addWidget(self.resumo, 1)
        self.atualizar_existentes = QCheckBox("Atualizar dados de clientes já cadastrados")
        self.atualizar_existentes.setChecked(True)
        self.atualizar_existentes.setToolTip(
            "Desmarcado, cliente já cadastrado fica como está: só entram clientes "
            "novos, contratos novos e honorários"
        )
        self.atualizar_existentes.toggled.connect(self._reconferir)
        rodape.addWidget(self.atualizar_existentes)
        layout.addLayout(rodape)

    def _montar_colunas(self) -> QWidget:
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        conteudo = QWidget()
        coluna = QVBoxLayout(conteudo)
        coluna.setSpacing(12)
        explicacao = widgets.rotulo_fraco(
            "Coluna: a letra do Excel onde está a informação (A, B… AA). Valor fixo: usado "
            "quando a célula vem vazia ou quando a informação não está na planilha — por "
            "exemplo, o tipo de honorário igual para todas as linhas. Deixe os dois em "
            "branco no que não for importar. O cliente é reconhecido pelo CPF/CNPJ, pelo "
            "código ou pelo nome: quem já está cadastrado não é cadastrado de novo."
        )
        coluna.addWidget(explicacao)
        letras = QRegularExpressionValidator(QRegularExpression("[A-Za-z]{0,3}"))
        for grupo in personalizada.GRUPOS:
            caixa = QGroupBox(grupo)
            grade = QGridLayout(caixa)
            grade.setHorizontalSpacing(12)
            for posicao, titulo in enumerate(("Informação", "Coluna", "Valor fixo", "")):
                rotulo = QLabel(titulo)
                rotulo.setObjectName("subtitulo")
                grade.addWidget(rotulo, 0, posicao)
            for linha, campo in enumerate(personalizada.campos_do_grupo(grupo), start=1):
                grade.addWidget(QLabel(campo.rotulo), linha, 0)
                letra = QLineEdit()
                letra.setValidator(letras)
                letra.setMaxLength(3)
                letra.setFixedWidth(60)
                letra.setAlignment(Qt.AlignmentFlag.AlignCenter)
                letra.textEdited.connect(
                    lambda texto, alvo=letra: alvo.setText(texto.upper())
                )
                grade.addWidget(letra, linha, 1)
                padrao = self._campo_padrao(campo)
                grade.addWidget(padrao, linha, 2)
                dica = QLabel(campo.dica)
                dica.setObjectName("subtitulo")
                dica.setWordWrap(True)
                grade.addWidget(dica, linha, 3)
                self.colunas[campo.chave] = letra
                self.padroes[campo.chave] = padrao
            grade.setColumnStretch(3, 1)
            grade.setColumnMinimumWidth(0, 230)   # mesma largura em todos os grupos
            grade.setColumnMinimumWidth(2, 200)
            coluna.addWidget(caixa)
        coluna.addStretch(1)
        rolagem.setWidget(conteudo)
        return rolagem

    def _campo_padrao(self, campo: personalizada.Campo) -> QWidget:
        if campo.tipo in OPCOES_ENUM or campo.tipo in ("tipo_honorario", "forma_envio",
                                                         "sim_nao"):
            combo = QComboBox()
            combo.setEditable(False)
            combo.setMinimumWidth(200)
            self._preencher_opcoes(combo, campo)
            return combo
        texto = QLineEdit()
        texto.setMinimumWidth(200)
        return texto

    def _preencher_opcoes(self, combo: QComboBox, campo: personalizada.Campo) -> None:
        atual = combo.currentText()
        combo.clear()
        combo.addItem("")
        if campo.tipo in OPCOES_ENUM:
            opcoes = [item.rotulo for item in OPCOES_ENUM[campo.tipo]
                      if item is not SubtipoCliente.NENHUM]
        elif campo.tipo == "sim_nao":
            opcoes = ["Sim", "Não"]
        elif campo.tipo == "tipo_honorario":
            opcoes = list(self.contexto.sessao.scalars(
                select(TipoHonorario.nome).order_by(TipoHonorario.nome)
            ))
        else:
            opcoes = list(self.contexto.sessao.scalars(
                select(FormaEnvio.nome).order_by(FormaEnvio.ordem, FormaEnvio.nome)
            ))
        combo.addItems(opcoes)
        indice = combo.findText(atual)
        combo.setCurrentIndex(max(0, indice))

    def recarregar(self) -> None:
        """Tipos de honorário e formas de envio podem ter mudado no cadastro."""
        for chave, padrao in self.padroes.items():
            if isinstance(padrao, QComboBox):
                self._preencher_opcoes(padrao, personalizada.POR_CHAVE[chave])

    # ------------------------------------------------------------------ layout
    def layout_da_tela(self) -> personalizada.Layout:
        campos = {}
        for chave, letra in self.colunas.items():
            padrao = self.padroes[chave]
            texto = padrao.currentText() if isinstance(padrao, QComboBox) else padrao.text()
            mapa = personalizada.Mapeamento(letra.text().strip().upper(), texto.strip())
            if not mapa.vazio:
                campos[chave] = mapa
        return personalizada.Layout(
            nome=self.nome_layout.text().strip(),
            aba=self.aba.text().strip(),
            linha_inicial=self.linha_inicial.value(),
            campos=campos,
        )

    def mostrar_layout(self, layout: personalizada.Layout) -> None:
        self.nome_layout.setText(layout.nome)
        self.aba.setText(layout.aba)
        self.linha_inicial.setValue(layout.linha_inicial)
        for chave, letra in self.colunas.items():
            mapa = layout.campos.get(chave) or personalizada.Mapeamento()
            letra.setText(mapa.coluna)
            padrao = self.padroes[chave]
            if isinstance(padrao, QComboBox):
                indice = padrao.findText(mapa.padrao)
                if indice < 0 and mapa.padrao:
                    padrao.addItem(mapa.padrao)   # valor que não está mais no cadastro
                    indice = padrao.count() - 1
                padrao.setCurrentIndex(max(0, indice))
            else:
                padrao.setText(mapa.padrao)

    def _carregar_layouts(self, selecionar: str = "") -> None:
        self.layouts = personalizada.listar_layouts(self.contexto.sessao)
        self.escolha_layout.blockSignals(True)
        self.escolha_layout.clear()
        self.escolha_layout.addItem(NOVO_LAYOUT)
        self.escolha_layout.addItems(list(self.layouts))
        self.escolha_layout.blockSignals(False)
        indice = self.escolha_layout.findText(selecionar) if selecionar else -1
        if indice < 0 and not selecionar and self.layouts:
            indice = 1   # abre no primeiro layout salvo
        self.escolha_layout.setCurrentIndex(max(0, indice))
        self._layout_escolhido(self.escolha_layout.currentText())

    def _layout_escolhido(self, nome: str) -> None:
        layout = self.layouts.get(nome)
        self.mostrar_layout(layout or personalizada.Layout())

    def _salvar_layout(self) -> None:
        layout = self.layout_da_tela()
        sobrescreve = layout.nome in self.layouts
        if sobrescreve and layout.nome != self.escolha_layout.currentText() and not (
            widgets.confirmar(self, f"Já existe o layout {layout.nome!r}. Substituir?",
                              "Salvar layout", acao="Substituir")
        ):
            return

        def acao():
            personalizada.salvar_layout(self.contexto.sessao, layout)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self._carregar_layouts(layout.nome)
        self.resumo.setText(f"Layout {layout.nome!r} salvo.")

    def _excluir_layout(self) -> None:
        nome = self.escolha_layout.currentText()
        if nome not in self.layouts:
            widgets.aviso(self, "Escolha um layout salvo para excluir.")
            return
        if not widgets.confirmar(self, f"Excluir o layout {nome!r}?", "Excluir layout",
                                 "As planilhas já importadas não mudam.", acao="Excluir",
                                 tipo="perigo"):
            return

        def acao():
            personalizada.excluir_layout(self.contexto.sessao, nome)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self._carregar_layouts(NOVO_LAYOUT)

    def _abrir_modelo(self) -> None:
        caminho, _ = QFileDialog.getOpenFileName(
            self, "Abrir o layout de uma planilha-modelo", str(pasta_exportacoes()),
            "Planilha do Excel (*.xlsx *.xlsm)",
        )
        if not caminho:
            return
        deu_certo, layout = widgets.executar(
            self, lambda: personalizada.ler_layout_do_modelo(caminho)
        )
        if not deu_certo:
            return
        self.escolha_layout.blockSignals(True)
        self.escolha_layout.setCurrentIndex(0)
        self.escolha_layout.blockSignals(False)
        self.mostrar_layout(layout)
        self.resumo.setText(
            f"Layout {layout.nome or ''} aberto do modelo. Salve-o para usar de novo."
        )

    def _exportar_modelo(self) -> None:
        layout = self.layout_da_tela()
        deu_certo, _ = widgets.executar(self, lambda: personalizada.validar_layout(layout))
        if not deu_certo:
            return
        nome = (layout.nome or "importacao").replace("/", "-")
        sugestao = str(pasta_exportacoes() / f"modelo-{nome}.xlsx")
        caminho, _ = QFileDialog.getSaveFileName(
            self, "Salvar planilha-modelo", sugestao, "Planilha do Excel (*.xlsx)"
        )
        if not caminho:
            return
        if not caminho.lower().endswith(".xlsx"):
            caminho += ".xlsx"
        deu_certo, arquivo = widgets.executar(
            self, lambda: personalizada.exportar_modelo(layout, caminho)
        )
        if deu_certo:
            widgets.informar(
                self,
                f"Modelo salvo em {arquivo}.\n\nO cabeçalho de cada informação está na "
                "coluna do layout e a aba Instruções explica o que cada uma aceita.",
                "Modelo exportado",
            )

    # ------------------------------------------------------------------ ações
    def _escolher(self) -> None:
        layout = self.layout_da_tela()
        deu_certo, _ = widgets.executar(self, lambda: personalizada.validar_layout(layout))
        if not deu_certo:
            return
        caminho, _ = QFileDialog.getOpenFileName(
            self, "Escolher a planilha", str(Path.home()), "Planilha do Excel (*.xlsx *.xlsm)"
        )
        if not caminho:
            return

        def acao():
            return personalizada.ler(
                self.contexto.sessao, caminho, layout, self.atualizar_existentes.isChecked()
            )

        deu_certo, previa = widgets.executar(self, acao)
        if not deu_certo:
            return
        self.previa = previa
        self._mostrar_previa()
        self.abas.setCurrentWidget(self.tabela_linhas)

    def _reconferir(self) -> None:
        if self.previa is None:
            return
        deu_certo, _ = widgets.executar(
            self,
            lambda: personalizada.conferir(
                self.contexto.sessao, self.previa, self.atualizar_existentes.isChecked()
            ),
        )
        if deu_certo:
            self._mostrar_previa()

    def _mostrar_previa(self) -> None:
        previa = self.previa
        self.modelo_linhas.definir_itens(previa.linhas)
        self.modelo_problemas.definir_itens(previa.todos_problemas())
        for tabela, modelo in (
            (self.tabela_linhas, self.modelo_linhas),
            (self.tabela_problemas, self.modelo_problemas),
        ):
            ajustar_colunas(tabela, modelo.colunas)
        self.resumo.setText(f"{Path(previa.arquivo).name} (aba {previa.aba}): {previa.resumo()}")

    def _importar(self) -> None:
        if self.previa is None:
            widgets.aviso(self, "Escolha a planilha primeiro.")
            return
        marcadas = [linha for linha in self.modelo_linhas.marcados() if not linha.bloqueada]
        if not marcadas:
            widgets.aviso(self, "Nenhuma linha marcada para importar.")
            return
        atualizar = self.atualizar_existentes.isChecked()
        clientes_novos = len({
            linha.chave_cliente for linha in marcadas if linha.acao_cliente == "Novo cliente"
        })
        a_atualizar = len({
            linha.chave_cliente for linha in marcadas
            if linha.acao_cliente.startswith("Atualizar")
        })
        honorarios = sum(1 for linha in marcadas if linha.acao_honorario.startswith("Novo"))
        contratos = sum(
            1 for linha in marcadas
            if linha.acao_contrato.startswith(("Novo", "Atualizar", "Reajuste"))
        )
        if not widgets.confirmar(
            self,
            f"Importar {len(marcadas)} linha(s)?",
            "Confirmar importação",
            "Faça um backup antes se o banco já tiver dados.",
            acao="Importar",
            resumo=[
                ("Clientes novos", str(clientes_novos)),
                ("Clientes a atualizar", str(a_atualizar) if atualizar else "nenhum"),
                ("Contratos", str(contratos)),
                ("Honorários", str(honorarios)),
            ],
        ):
            return

        escolhidas = {id(linha) for linha in marcadas}
        for linha in self.previa.linhas:
            linha.importar = id(linha) in escolhidas

        def acao():
            resultado = personalizada.importar(self.contexto.sessao, self.previa, atualizar)
            self.contexto.salvar()
            return resultado

        deu_certo, resultado = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.previa = None
        self.modelo_linhas.definir_itens([])
        self.modelo_problemas.definir_itens(resultado.falhas)
        if resultado.falhas:
            self.abas.setCurrentWidget(self.tabela_problemas)
        self.resumo.setText(resultado.resumo)
        widgets.informar(self, resultado.resumo, "Importação concluída")
