"""Parcelamento: junta um ou mais honorários em aberto num acordo parcelado.

Abre pela tela Parcelamentos (escolhendo o cliente) ou pelos honorários
selecionados em Atrasados. Mostra todos os honorários em aberto do cliente, com os
escolhidos marcados, e as parcelas que vão nascer antes de confirmar.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSpinBox,
    QTableView,
    QVBoxLayout,
)

from ...dominio.valores import ZERO, formatar_data, formatar_moeda, hoje, somar_meses
from ...servicos import calculo, parcelamentos
from ...servicos import honorarios as servico_honorarios
from ..comum import widgets
from ..comum.campos import CampoData, CampoMoeda, ComboRegistros, Rotulo
from ..comum.seletor_cliente import CampoCliente
from ..comum.tabelas import (
    Coluna,
    ModeloTabela,
    ModeloTabelaMarcavel,
    ajustar_colunas,
    coluna_data,
    coluna_moeda,
    preparar_tabela,
)
from ..contexto import Contexto

TIPO_PADRAO = "Parcela de acordo"


class DialogoRenegociacao(QDialog):
    def __init__(self, contexto: Contexto, cliente=None, linhas=(), parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.cliente = cliente
        self._escolhidos = {linha.honorario.id for linha in linhas}
        self._valor_mexido = False
        # juros acertado aqui, por honorário (None = o calculado); só vale no parcelamento
        self._juros: dict[int, Decimal | None] = {}
        self.acordo = None
        from ...servicos import tarefas

        self._dias_lembrete = tarefas.dias_antes_da_parcela(contexto.sessao)
        self.setWindowTitle(f"Parcelar – {cliente.nome}" if cliente else "Novo parcelamento")
        self.resize(900, 720)
        self._montar()
        self._carregar_cliente(cliente)

    # ------------------------------------------------------------------ tela
    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        self.cabecalho = widgets.Cabecalho(
            "Novo parcelamento",
            "Marque os honorários que entram: um ou vários. Eles saem de Vencimentos e "
            "as parcelas passam a ser acompanhadas em Parcelamentos.",
        )
        layout.addWidget(self.cabecalho)

        escolha = QFormLayout()
        self.campo_cliente = CampoCliente(self.contexto.sessao)
        self.campo_cliente.mudou.connect(self._carregar_cliente)
        escolha.addRow("Cliente:", self.campo_cliente)
        layout.addLayout(escolha)

        layout.addWidget(QLabel("<b>Honorários em aberto</b>"))
        self.modelo = ModeloTabelaMarcavel(
            [
                Coluna("Tipo", lambda linha: linha.honorario.tipo.nome),
                Coluna("Competência", lambda linha: linha.honorario.competencia_rotulo),
                coluna_data("Vencimento", lambda linha: linha.honorario.vencimento),
                coluna_moeda("Valor", lambda linha: linha.atualizacao.valor_original),
                coluna_moeda("Juros", lambda linha: self.atualizacao(linha).juros),
                Coluna("", lambda linha: "✎ à mão" if self.atualizacao(linha).juros_manual
                       else "", dica=lambda linha: self._dica_juros(linha)),
                coluna_moeda("Total", lambda linha: self.atualizacao(linha).total, negrito=True),
            ],
            marcados_por_padrao=False,
        )
        self.modelo.dataChanged.connect(lambda *_: self._recalcular())
        self.tabela = preparar_tabela(QTableView(), esticar=0)
        self.tabela.setModel(self.modelo)
        ajustar_colunas(self.tabela, self.modelo.colunas)
        self.tabela.doubleClicked.connect(lambda *_: self._alterar_juros())
        layout.addWidget(self.tabela, 2)

        juros = QHBoxLayout()
        self.botao_juros = widgets.QPushButton("Alterar juros…")
        self.botao_juros.setToolTip("Conferir e acertar à mão o juros do honorário escolhido "
                                    "(também com dois cliques)")
        self.botao_juros.clicked.connect(self._alterar_juros)
        self.botao_sem_juros = widgets.QPushButton("Tirar o juros dos marcados")
        self.botao_sem_juros.clicked.connect(self._tirar_juros)
        self.botao_calculado = widgets.QPushButton("Voltar ao calculado")
        self.botao_calculado.clicked.connect(self._voltar_ao_calculado)
        for botao in (self.botao_juros, self.botao_sem_juros, self.botao_calculado):
            juros.addWidget(botao)
        juros.addStretch(1)
        self.juros_resumo = widgets.rotulo_fraco("")
        self.juros_resumo.setWordWrap(False)
        juros.addWidget(self.juros_resumo)
        layout.addLayout(juros)

        meio = QHBoxLayout()
        formulario = QFormLayout()
        self.total_original = Rotulo("—")
        formulario.addRow("Total escolhido:", self.total_original)
        self.desconto = CampoMoeda(0)
        self.desconto.valueChanged.connect(self._recalcular)
        formulario.addRow("Desconto:", self.desconto)
        self.valor_acordado = CampoMoeda(0)
        self.valor_acordado.valueChanged.connect(self._digitou_valor)
        formulario.addRow("Valor parcelado:", self.valor_acordado)
        self.parcelas = QSpinBox()
        self.parcelas.setRange(1, 60)
        self.parcelas.setSuffix(" parcela(s)")
        self.parcelas.valueChanged.connect(self._recalcular)
        formulario.addRow("Parcelas:", self.parcelas)
        self.primeiro_vencimento = CampoData(somar_meses(hoje(), 1))
        self.primeiro_vencimento.dateChanged.connect(lambda *_: self._recalcular())
        formulario.addRow("1º vencimento:", self.primeiro_vencimento)
        from ...servicos import tipos as servico_tipos

        tipos = servico_tipos.listar_tipos(self.contexto.sessao)
        self.tipo = ComboRegistros(tipos, rotulo=lambda t: t.nome,
                                   vazio="— selecione o tipo das parcelas —")
        padrao = next((tipo for tipo in tipos if tipo.nome == TIPO_PADRAO), None)
        if padrao is not None:
            self.tipo.definir(padrao.id)
        formulario.addRow("Tipo das parcelas:", self.tipo)
        self.observacoes = QPlainTextEdit()
        self.observacoes.setMaximumHeight(60)
        formulario.addRow("Observações:", self.observacoes)
        coluna = QVBoxLayout()
        coluna.addLayout(formulario)
        coluna.addStretch(1)
        meio.addLayout(coluna, 1)

        previa = QVBoxLayout()
        previa.addWidget(QLabel("<b>As parcelas</b>"))
        self.modelo_parcelas = ModeloTabela(
            [
                Coluna("Parcela", lambda p: f"{p.numero}/{self.parcelas.value()}"),
                coluna_data("Vencimento", lambda p: p.vencimento),
                coluna_moeda("Valor", lambda p: p.valor, negrito=True),
            ]
        )
        self.tabela_parcelas = preparar_tabela(QTableView(), esticar=1)
        self.tabela_parcelas.setModel(self.modelo_parcelas)
        previa.addWidget(self.tabela_parcelas, 1)
        meio.addLayout(previa, 1)
        layout.addLayout(meio, 3)

        self.resumo = widgets.rotulo_fraco("")
        self.resumo.setWordWrap(True)
        layout.addWidget(self.resumo)

        acoes = QHBoxLayout()
        acoes.addStretch(1)
        cancelar = widgets.QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        self.botao_confirmar = widgets.QPushButton("Parcelar")
        self.botao_confirmar.setObjectName("primario")
        self.botao_confirmar.clicked.connect(self._confirmar)
        acoes.addWidget(cancelar)
        acoes.addWidget(self.botao_confirmar)
        layout.addLayout(acoes)

    # ----------------------------------------------------------------- dados
    def _carregar_cliente(self, cliente) -> None:
        self.cliente = cliente
        if cliente is not None and self.campo_cliente.valor() != cliente.id:
            self.campo_cliente.definir(cliente.id)
        linhas = []
        if cliente is not None:
            # parcela de outro parcelamento não entra: ela já é acompanhada lá
            linhas = servico_honorarios.pendentes(self.contexto.sessao, servico_honorarios.Filtro(
                cliente_id=cliente.id, data_referencia=self.contexto.data_referencia,
                incluir_parcelas=False))
        self._juros.clear()
        self.modelo.definir_itens(linhas)
        for indice, linha in enumerate(linhas):
            if linha.honorario.id in self._escolhidos or len(linhas) == 1:
                self.modelo.setData(self.modelo.index(indice, 0), Qt.CheckState.Checked,
                                    Qt.ItemDataRole.CheckStateRole)
        self.cabecalho.definir_subtitulo(
            f"{len(linhas)} honorário(s) em aberto. Marque os que entram no parcelamento: "
            "eles saem de Vencimentos e as parcelas passam a ser acompanhadas em "
            "Parcelamentos." if cliente is not None else
            "Escolha o cliente e marque os honorários que entram no parcelamento."
        )
        self._valor_mexido = False
        self._recalcular()

    def escolhidos(self) -> list:
        return self.modelo.marcados()

    def atualizacao(self, linha) -> calculo.Atualizacao:
        """O cálculo do honorário com o juros acertado aqui, se houver."""
        if linha.honorario.id in self._juros:
            return calculo.com_juros_manual(linha.atualizacao, self._juros[linha.honorario.id])
        return linha.atualizacao

    def _calculado(self, linha) -> Decimal:
        atual = linha.atualizacao
        return atual.juros_calculado if atual.juros_manual else atual.juros

    def _dica_juros(self, linha) -> str:
        atual = self.atualizacao(linha)
        if not atual.juros_manual:
            return f"Juros calculado: {atual.dias_atraso} dia(s) de atraso"
        return f"Acertado à mão. O calculado é {formatar_moeda(self._calculado(linha))}"

    def _total(self) -> Decimal:
        return sum((self.atualizacao(linha).total for linha in self.escolhidos()), start=ZERO)

    def _juros_mudou(self) -> None:
        if self.modelo.itens:   # repinta a tabela sem perder as marcações
            self.modelo.dataChanged.emit(
                self.modelo.index(0, 0),
                self.modelo.index(len(self.modelo.itens) - 1, len(self.modelo.colunas) - 1))
        self._recalcular()

    def _alterar_juros(self) -> None:
        from ..comum.tabelas import item_atual
        from .juros_manual import DialogoJurosManual

        linha = item_atual(self.tabela)
        if linha is None:
            widgets.aviso(self, "Escolha na lista o honorário para conferir o juros.")
            return
        dialogo = DialogoJurosManual(
            f"{linha.honorario.tipo.nome} {linha.honorario.competencia_rotulo}".strip(),
            linha.honorario, self.atualizacao(linha),
            aviso="Vale só para este parcelamento: entra no total a parcelar.", parent=self)
        if dialogo.exec():
            self._juros[linha.honorario.id] = dialogo.juros
            self._juros_mudou()

    def _tirar_juros(self) -> None:
        marcados = self.escolhidos()
        if not marcados:
            widgets.aviso(self, "Marque os honorários para tirar o juros.")
            return
        for linha in marcados:
            self._juros[linha.honorario.id] = ZERO
        self._juros_mudou()

    def _voltar_ao_calculado(self) -> None:
        for linha in self.modelo.itens:
            self._juros[linha.honorario.id] = None
        self._juros_mudou()

    def _digitou_valor(self, *_args) -> None:
        self._valor_mexido = True
        self._recalcular()

    def previstas(self) -> list[parcelamentos.ParcelaPrevista]:
        return parcelamentos.dividir(self.valor_acordado.valor(), self.parcelas.value(),
                                     self.primeiro_vencimento.valor())

    def _recalcular(self) -> None:
        total = self._total()
        self.total_original.setText(formatar_moeda(total))
        if not self._valor_mexido:
            # o valor acompanha a escolha e o desconto até ser digitado à mão
            self.valor_acordado.blockSignals(True)
            self.valor_acordado.definir(max(ZERO, total - self.desconto.valor()))
            self.valor_acordado.blockSignals(False)
        valor = self.valor_acordado.valor()
        previstas = self.previstas() if valor > 0 else []
        self.modelo_parcelas.definir_itens(previstas)
        quantidade = len(self.escolhidos())
        juros = sum((self.atualizacao(linha).juros for linha in self.escolhidos()), start=ZERO)
        calculado = sum((self._calculado(linha) for linha in self.escolhidos()), start=ZERO)
        self.juros_resumo.setText(
            f"Juros incluídos: {formatar_moeda(juros)}"
            + (f" (calculado {formatar_moeda(calculado)})" if juros != calculado else ""))
        self.botao_calculado.setEnabled(any(self.atualizacao(linha).juros_manual
                                            for linha in self.modelo.itens))
        self.botao_sem_juros.setEnabled(juros > 0)
        self.botao_juros.setEnabled(bool(self.modelo.itens))
        self.botao_confirmar.setEnabled(quantidade > 0 and valor > 0)
        if not quantidade:
            self.resumo.setText("Marque ao menos um honorário.")
            return
        ultima = previstas[-1].vencimento if previstas else None
        self.resumo.setText(
            f"{quantidade} honorário(s) de {formatar_moeda(total)} viram "
            f"{self.parcelas.value()} parcela(s), somando {formatar_moeda(valor)}"
            + (f", até {formatar_data(ultima)}" if ultima else "")
            + ". Os honorários escolhidos ficam como Renegociado; em Tarefas aparece o "
            f"lembrete de enviar cada parcela {self._dias_lembrete} dia(s) antes do vencimento."
        )

    def _confirmar(self) -> None:
        linhas = [replace(linha, atualizacao=self.atualizacao(linha))
                  for linha in self.escolhidos()]
        if self.cliente is None or not linhas:
            widgets.aviso(self, "Escolha o cliente e marque os honorários do parcelamento.")
            return
        if self.tipo.valor() is None:
            widgets.aviso(self, "Escolha o tipo de honorário das parcelas.")
            return
        valor = self.valor_acordado.valor()
        if not widgets.confirmar(
            self,
            f"Parcelar {formatar_moeda(valor)} em {self.parcelas.value()} parcela(s)?",
            "Parcelamento",
            f"{len(linhas)} honorário(s) passam para Renegociado e as parcelas vão para "
            "a tela Parcelamentos.",
            acao="Parcelar",
        ):
            return

        def acao():
            self.acordo = parcelamentos.criar(
                self.contexto.sessao,
                cliente=self.cliente,
                linhas=linhas,
                valor_acordado=valor,
                desconto=self.desconto.valor(),
                parcelas=self.parcelas.value(),
                primeiro_vencimento=self.primeiro_vencimento.valor(),
                tipo_id=self.tipo.valor(),
                observacoes=self.observacoes.toPlainText(),
            )
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.accept()
