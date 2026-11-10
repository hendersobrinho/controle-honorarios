"""Parcelar honorários numa tela só, direta: o cliente, os honorários, o juros (o da
empresa, ou um total personalizado) e as parcelas, com a prévia na hora. A
explicação da conta fica no botão ⓘ, para não poluir a tela."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QTableView,
    QVBoxLayout,
)

from ...dominio.valores import ZERO, dinheiro, formatar_data, formatar_moeda, hoje, somar_meses
from ...servicos import calculo, parcelamentos, renegociacoes
from ...servicos import clientes as servico_clientes
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


def distribuir(total: Decimal, pesos: list[Decimal]) -> list[Decimal]:
    """Reparte ``total`` na proporção dos pesos (a sobra dos centavos vai no último)."""
    if not pesos:
        return []
    soma = sum(pesos, start=ZERO)
    if soma <= 0:
        pesos, soma = [Decimal(1)] * len(pesos), Decimal(len(pesos))
    partes = [dinheiro(total * peso / soma) for peso in pesos[:-1]]
    return partes + [dinheiro(total - sum(partes, start=ZERO))]


class DialogoJurosDaEmpresa(QDialog):
    """Troca rápida do juros por dia no cadastro da empresa."""

    def __init__(self, contexto: Contexto, cliente, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.cliente = cliente
        self.setWindowTitle("Juros da empresa")
        layout = QVBoxLayout(self)
        layout.addWidget(Rotulo(f"<b>{cliente.nome}</b>"))
        formulario = QFormLayout()
        self.valor_dia = CampoMoeda(servico_clientes.juros_atual(cliente))
        formulario.addRow("Juros por dia de atraso:", self.valor_dia)
        layout.addLayout(formulario)
        aviso = widgets.rotulo_fraco("Muda no cadastro da empresa e vale para todos os "
                                     "honorários dela em aberto.")
        aviso.setWordWrap(True)
        layout.addWidget(aviso)
        botoes = QHBoxLayout()
        botoes.addStretch(1)
        cancelar = widgets.QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        salvar = widgets.QPushButton("Salvar")
        salvar.setObjectName("primario")
        salvar.setDefault(True)
        salvar.clicked.connect(self._salvar)
        botoes.addWidget(cancelar)
        botoes.addWidget(salvar)
        layout.addLayout(botoes)

    def _salvar(self) -> None:
        def acao():
            servico_clientes.definir_juros(self.contexto.sessao, self.cliente,
                                           self.valor_dia.valor(), "Alterado ao parcelar")
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.accept()


class AssistenteParcelamento(QDialog):
    """Depois do ``exec``: ``acordo`` é o parcelamento criado (ou None)."""

    def __init__(self, contexto: Contexto, cliente=None, linhas=(), juros=None,
                 parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.cliente = cliente
        self._escolhidos = {linha.honorario.id for linha in linhas}
        # juros que veio de outra tela (o Cobrar), por honorário: vira o personalizado
        self._juros_de_fora: dict[int, Decimal] = dict(juros or {})
        self._juros_previsto: dict[int, Decimal] = {}
        self._personalizados: dict[int, Decimal] = {}
        self._pronto = False
        self.acordo = None
        self.usar_tela_antiga = False
        self.setWindowTitle("Parcelar honorários")
        widgets.tamanho_na_tela(self, 1040, 760)
        self._montar()
        self._pronto = True
        self._carregar_cliente(cliente)
        if self._juros_de_fora:
            self._usar_juros_de_fora()

    # ================================================================== tela
    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        topo = QHBoxLayout()
        topo.addWidget(widgets.Cabecalho("Parcelar honorários"), 1)
        self.botao_info = widgets.QPushButton("ⓘ  Como funciona")
        self.botao_info.setToolTip("Como o juros e as parcelas são calculados")
        self.botao_info.clicked.connect(self._como_funciona)
        topo.addWidget(self.botao_info, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(topo)

        cliente = QFormLayout()
        self.campo_cliente = CampoCliente(self.contexto.sessao)
        self.campo_cliente.mudou.connect(self._carregar_cliente)
        cliente.addRow("Cliente:", self.campo_cliente)
        layout.addLayout(cliente)

        # ---- os honorários
        self.modelo = ModeloTabelaMarcavel(
            [
                Coluna("Honorário", lambda linha: f"{linha.honorario.tipo.nome} "
                       f"{linha.honorario.competencia_rotulo}".strip()),
                coluna_data("Venceu em", lambda linha: linha.honorario.vencimento),
                Coluna("Dias", lambda linha: str(linha.atualizacao.dias_atraso),
                       alinhamento=Qt.AlignmentFlag.AlignCenter),
                coluna_moeda("Valor", lambda linha: linha.atualizacao.saldo),
                coluna_moeda("Juros", lambda linha: self.atualizacao(linha).juros),
                coluna_moeda("Total", lambda linha: self.atualizacao(linha).total, negrito=True),
            ],
            marcados_por_padrao=False,
        )
        self.modelo.dataChanged.connect(self._marcou)
        self.tabela = preparar_tabela(QTableView(), esticar=0)
        self.tabela.setModel(self.modelo)
        ajustar_colunas(self.tabela, self.modelo.colunas)
        self.tabela.setMinimumHeight(110)
        layout.addWidget(self.tabela, 2)

        # ---- o juros
        caixa = QFrame()
        caixa.setObjectName("editorJuros")
        juros = QGridLayout(caixa)
        juros.setContentsMargins(12, 8, 12, 8)
        juros.setHorizontalSpacing(10)
        juros.addWidget(Rotulo("<b>Juros</b>"), 0, 0)
        self.juros_empresa = QLabel("")
        juros.addWidget(self.juros_empresa, 0, 1)
        self.botao_alterar_juros = widgets.QPushButton("Alterar")
        self.botao_alterar_juros.setObjectName("linkFiltro")
        self.botao_alterar_juros.setToolTip("Muda o juros por dia no cadastro da empresa")
        self.botao_alterar_juros.clicked.connect(self._alterar_juros_da_empresa)
        juros.addWidget(self.botao_alterar_juros, 0, 2, Qt.AlignmentFlag.AlignLeft)
        self.personalizado = QCheckBox("Juros total personalizado:")
        self.personalizado.setToolTip("Um valor cheio de juros para os honorários marcados, "
                                      "no lugar do calculado")
        self.personalizado.toggled.connect(self._trocar_personalizado)
        juros.addWidget(self.personalizado, 1, 1)
        self.juros_total = CampoMoeda(0)
        self.juros_total.setMaximumWidth(160)
        self.juros_total.setEnabled(False)
        self.juros_total.valueChanged.connect(lambda *_: self._recalcular())
        juros.addWidget(self.juros_total, 1, 2)
        self.juros_calculado = widgets.rotulo_fraco("")
        self.juros_calculado.setWordWrap(False)
        juros.addWidget(self.juros_calculado, 1, 3)
        juros.setColumnStretch(4, 1)
        layout.addWidget(caixa)

        # ---- as parcelas
        campos = QHBoxLayout()
        campos.setSpacing(8)
        self.desconto = CampoMoeda(0)
        self.desconto.setMaximumWidth(130)
        self.desconto.valueChanged.connect(lambda *_: self._recalcular())
        self.parcelas = QSpinBox()
        self.parcelas.setRange(1, 60)
        self.parcelas.setSuffix(" x")
        self.parcelas.setMaximumWidth(90)
        self.parcelas.valueChanged.connect(lambda *_: self._recalcular())
        self.primeiro_vencimento = CampoData(somar_meses(hoje(), 1))
        self.primeiro_vencimento.setMaximumWidth(150)
        self.primeiro_vencimento.dateChanged.connect(lambda *_: self._recalcular())
        from ...servicos import tipos as servico_tipos

        tipos = servico_tipos.listar_tipos(self.contexto.sessao)
        self.tipo = ComboRegistros(tipos, rotulo=lambda t: t.nome,
                                   vazio="— tipo das parcelas —")
        padrao = next((tipo for tipo in tipos if tipo.nome == TIPO_PADRAO), None)
        if padrao is not None:
            self.tipo.definir(padrao.id)
        for rotulo, campo in (("Desconto:", self.desconto), ("Parcelas:", self.parcelas),
                              ("1ª vence em:", self.primeiro_vencimento),
                              ("Tipo:", self.tipo)):
            campos.addWidget(QLabel(rotulo))
            campos.addWidget(campo)
            campos.addSpacing(6)
        campos.addStretch(1)
        layout.addLayout(campos)
        self.juros_correndo = QCheckBox("Juros continua correndo nas parcelas até o pagamento")
        self.juros_correndo.setChecked(True)
        self.juros_correndo.setToolTip("Desmarcado: a parcela só soma juros se atrasar")
        self.juros_correndo.toggled.connect(lambda *_: self._recalcular())
        layout.addWidget(self.juros_correndo)

        self.modelo_parcelas = ModeloTabela(
            [
                Coluna("Parcela", lambda p: f"{p.numero}/{self.parcelas.value()}", largura=72),
                coluna_data("Vence em", lambda p: p.vencimento, largura=100),
                coluna_moeda("Valor", lambda p: p.valor, largura=110),
                coluna_moeda("Juros até vencer", lambda p: self._juros_previsto.get(
                    p.numero, ZERO), largura=130),
                coluna_moeda("No vencimento", lambda p: p.valor + self._juros_previsto.get(
                    p.numero, ZERO), negrito=True),
            ]
        )
        self.tabela_parcelas = preparar_tabela(QTableView(), esticar=4)
        self.tabela_parcelas.setModel(self.modelo_parcelas)
        ajustar_colunas(self.tabela_parcelas, self.modelo_parcelas.colunas)
        self.tabela_parcelas.setMinimumHeight(120)
        layout.addWidget(self.tabela_parcelas, 3)

        rodape = QHBoxLayout()
        self.total_parcelar = Rotulo("", "valorDestaque")
        rodape.addWidget(self.total_parcelar, 1)
        self.botao_antiga = widgets.QPushButton("tela antiga")
        self.botao_antiga.setObjectName("linkFiltro")
        self.botao_antiga.clicked.connect(self._tela_antiga)
        rodape.addWidget(self.botao_antiga)
        cancelar = widgets.QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        self.botao_parcelar = widgets.QPushButton("Parcelar")
        self.botao_parcelar.setObjectName("primario")
        self.botao_parcelar.setDefault(True)
        self.botao_parcelar.clicked.connect(self._confirmar)
        rodape.addWidget(cancelar)
        rodape.addWidget(self.botao_parcelar)
        layout.addLayout(rodape)

    # ================================================================ dados
    def _carregar_cliente(self, cliente) -> None:
        marcados = {linha.honorario.id for linha in self.escolhidos()}
        mesmo = cliente is not None and self.cliente is not None and cliente.id == self.cliente.id
        self.cliente = cliente
        if cliente is not None and self.campo_cliente.valor() != cliente.id:
            self.campo_cliente.definir(cliente.id)
        linhas = []
        if cliente is not None:
            # parcela de outro parcelamento não entra: ela já é acompanhada lá
            linhas = servico_honorarios.pendentes(self.contexto.sessao, servico_honorarios.Filtro(
                cliente_id=cliente.id, data_referencia=self.contexto.data_referencia,
                incluir_parcelas=False))
        manter = marcados if mesmo and marcados else self._escolhidos
        self.modelo.definir_itens(linhas)
        for indice, linha in enumerate(linhas):
            if linha.honorario.id in manter or len(linhas) == 1:
                self.modelo.setData(self.modelo.index(indice, 0), Qt.CheckState.Checked,
                                    Qt.ItemDataRole.CheckStateRole)
        self._recalcular()

    def escolhidos(self) -> list:
        return self.modelo.marcados()

    def taxa_do_cliente(self) -> Decimal:
        return calculo.taxa_vigente_em(self.cliente, hoje()) if self.cliente else ZERO

    def juros_calculado_total(self) -> Decimal:
        return sum((linha.atualizacao.juros for linha in self.escolhidos()), start=ZERO)

    def _juros_personalizados(self) -> dict[int, Decimal]:
        """O juros total personalizado repartido entre os marcados, na proporção do
        juros calculado de cada um (sem juros calculado: na proporção do valor)."""
        if not self.personalizado.isChecked():
            return {}
        marcados = self.escolhidos()
        pesos = [linha.atualizacao.juros for linha in marcados]
        if sum(pesos, start=ZERO) <= 0:
            pesos = [linha.atualizacao.saldo for linha in marcados]
        partes = distribuir(self.juros_total.valor(), pesos)
        return {linha.honorario.id: parte for linha, parte in zip(marcados, partes, strict=True)}

    def atualizacao(self, linha) -> calculo.Atualizacao:
        juros = self._personalizados.get(linha.honorario.id)
        if juros is None:
            return linha.atualizacao
        return calculo.com_juros_manual(linha.atualizacao, juros)

    def _total(self) -> Decimal:
        return sum((self.atualizacao(linha).total for linha in self.escolhidos()), start=ZERO)

    def valor_a_parcelar(self) -> Decimal:
        return max(ZERO, self._total() - self.desconto.valor())

    def previstas(self) -> list[parcelamentos.ParcelaPrevista]:
        valor = self.valor_a_parcelar()
        if valor <= 0:
            return []
        return parcelamentos.dividir(valor, self.parcelas.value(),
                                     self.primeiro_vencimento.valor())

    def _fatores(self, previstas) -> list[Decimal]:
        return renegociacoes.fatores_das_parcelas(
            renegociacoes.fator_do_juros(self.escolhidos()), previstas)

    def juros_dia_da_parcela(self, previstas=None) -> Decimal:
        previstas = self.previstas() if previstas is None else previstas
        if not previstas or self.cliente is None:
            return ZERO
        return renegociacoes.juros_dia_calculado(self.cliente, self._fatores(previstas)[0],
                                                 hoje())

    # ============================================================== ações
    def _marcou(self, *_args) -> None:
        if not self._repintando:
            self._recalcular()

    _repintando = False

    def _trocar_personalizado(self, marcado: bool) -> None:
        self.juros_total.setEnabled(marcado)
        if marcado:
            self.juros_total.blockSignals(True)
            self.juros_total.definir(self.juros_calculado_total())
            self.juros_total.blockSignals(False)
            self.juros_total.setFocus()
        self._recalcular()

    def _usar_juros_de_fora(self) -> None:
        """O juros mudado no Cobrar: entra como o total personalizado."""
        total = sum((self._juros_de_fora.get(linha.honorario.id, linha.atualizacao.juros)
                     for linha in self.escolhidos()), start=ZERO)
        if total == self.juros_calculado_total():
            return
        self.personalizado.setChecked(True)
        self.juros_total.definir(total)

    def _alterar_juros_da_empresa(self) -> None:
        if self.cliente is None:
            return
        if DialogoJurosDaEmpresa(self.contexto, self.cliente, self).exec():
            self._carregar_cliente(self.cliente)   # os juros mudaram: recalcula tudo

    def _como_funciona(self) -> None:
        taxa = self.taxa_do_cliente()
        previstas = self.previstas()
        dia = formatar_moeda(self.juros_dia_da_parcela(previstas))
        quantos = len(self.escolhidos())
        widgets.informar(self, (
            "<b>Juros dos honorários</b><br>"
            f"Juros por dia da empresa × dias de atraso. Ex.: 10 dias × "
            f"{formatar_moeda(taxa)} = {formatar_moeda(taxa * 10)}.<br>"
            "Em <i>Juros total personalizado</i>, o valor digitado é o juros inteiro de "
            "todos os marcados (não é por dia).<br><br>"
            "<b>Valor a parcelar</b><br>"
            "Valor dos honorários + juros − desconto, dividido em parcelas iguais (a última "
            "acerta os centavos). As outras parcelas vencem no mesmo dia dos meses "
            "seguintes.<br><br>"
            "<b>Juros das parcelas</b><br>"
            "Cada parcela soma juros por dia desde hoje até ser paga (desmarcando a opção, "
            "só se atrasar). O juros por dia da empresa é dividido entre as parcelas: "
            f"{quantos} honorário(s) × {formatar_moeda(taxa)} ÷ {len(previstas) or 1} "
            f"parcela(s) ≈ <b>{dia} por dia</b> em cada uma. Assim o cliente paga por dia "
            "o mesmo de antes.<br><br>"
            "<b>Depois de parcelar</b><br>"
            "Os honorários saem de Vencimentos (ficam como Renegociado) e as parcelas "
            "aparecem em Parcelamentos e no lembrete de Tarefas."), "Como funciona")

    def _tela_antiga(self) -> None:
        self.usar_tela_antiga = True
        self.reject()

    # ============================================================ recalcular
    def _recalcular(self) -> None:
        if not self._pronto:
            return   # ainda montando a tela
        self._personalizados = self._juros_personalizados()
        if self.modelo.itens:   # repinta o juros e o total da lista
            self._repintando = True
            self.modelo.dataChanged.emit(
                self.modelo.index(0, 0),
                self.modelo.index(len(self.modelo.itens) - 1, len(self.modelo.colunas) - 1))
            self._repintando = False
        tem_cliente = self.cliente is not None
        self.botao_alterar_juros.setVisible(tem_cliente)
        self.juros_empresa.setText(
            f"da empresa: {formatar_moeda(self.taxa_do_cliente())} por dia de atraso"
            if tem_cliente else "escolha o cliente")
        self.juros_calculado.setText(
            f"calculado: {formatar_moeda(self.juros_calculado_total())}")

        previstas = self.previstas()
        self._juros_previsto = {}
        if previstas and tem_cliente and self.juros_correndo.isChecked():
            juros = renegociacoes.juros_previstos(self.cliente, previstas,
                                                  self._fatores(previstas), hoje())
            self._juros_previsto = {p.numero: v for p, v in zip(previstas, juros, strict=True)}
        self.modelo_parcelas.definir_itens(previstas)

        if previstas:
            texto = (f"A parcelar: {formatar_moeda(self.valor_a_parcelar())}  →  "
                     f"{len(previstas)} × {formatar_moeda(previstas[0].valor)}")
            if self.juros_correndo.isChecked():
                texto += f"  + {formatar_moeda(self.juros_dia_da_parcela(previstas))}/dia"
        else:
            texto = "Marque os honorários" if tem_cliente else "Escolha o cliente"
        self.total_parcelar.setText(texto)
        self.botao_parcelar.setEnabled(bool(previstas))

    # ============================================================ confirmar
    def problema(self) -> str:
        if self.cliente is None:
            return "Escolha o cliente."
        if not self.escolhidos():
            return "Marque ao menos um honorário."
        if self.valor_a_parcelar() <= 0:
            return "O valor a parcelar precisa ser maior que zero."
        if self.tipo.valor() is None:
            return "Escolha o tipo das parcelas."
        return ""

    def _confirmar(self) -> None:
        falta = self.problema()
        if falta:
            widgets.aviso(self, falta)
            return
        linhas = [replace(linha, atualizacao=self.atualizacao(linha))
                  for linha in self.escolhidos()]
        previstas = self.previstas()
        if not widgets.confirmar(
            self,
            f"Parcelar {formatar_moeda(self.valor_a_parcelar())} em {len(previstas)} "
            "parcela(s)?",
            "Parcelamento",
            f"1ª parcela em {formatar_data(previstas[0].vencimento)}. Os honorários marcados "
            "vão para Parcelamentos.",
            acao="Parcelar",
        ):
            return

        def acao():
            self.acordo = parcelamentos.criar(
                self.contexto.sessao,
                cliente=self.cliente,
                linhas=linhas,
                valor_acordado=self.valor_a_parcelar(),
                desconto=self.desconto.valor(),
                parcelas=self.parcelas.value(),
                primeiro_vencimento=self.primeiro_vencimento.valor(),
                tipo_id=self.tipo.valor(),
                juros_ate_o_vencimento=self.juros_correndo.isChecked(),
            )
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.accept()


def parcelar(contexto: Contexto, cliente=None, linhas=(), juros=None, parent=None):
    """Abre a tela de parcelar (ou a antiga, se a pessoa preferir). Devolve o
    parcelamento criado, ou None."""
    tela = AssistenteParcelamento(contexto, cliente, linhas, juros, parent)
    if tela.exec():
        return tela.acordo
    if not tela.usar_tela_antiga:
        return None
    from .renegociacao import DialogoRenegociacao

    # o que já foi escolhido vai junto
    antiga = DialogoRenegociacao(contexto, tela.cliente, tela.escolhidos(), parent)
    return antiga.acordo if antiga.exec() else None
