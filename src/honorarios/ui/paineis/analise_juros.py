"""Aba de análise de juros: o original contra o que entrou, cliente a cliente.

À esquerda, os clientes que pagaram no período (quem paga entra aqui). À
direita, a análise do cliente escolhido — original + juros = pago, honorário por
honorário, a explicação em frases e os cenários de taxa — ou, no primeiro item
da lista, a visão geral de todos.
"""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...dominio.valores import (
    ZERO,
    dinheiro,
    formatar_data,
    formatar_moeda,
    normalizar_busca,
    somar_meses,
)
from ...servicos import analise_juros as servico
from ...servicos.analise_juros import AnaliseJuros, percentual
from ..comum import cores, tema, widgets
from ..comum.cartoes import CartaoRegistro, DadosCartao, DataCartao
from ..comum.grafico_meses import GraficoMeses
from ..comum.grafico_ranking import GraficoRanking, fonte_ajustada
from ..contexto import Contexto

LIMITE_PAGAMENTOS = 40

ORDENS = (
    ("Mais trabalho", lambda a: tuple(-x for x in a.trabalho) + (a.cliente.nome,)),
    ("Mais juros pago", lambda a: (-a.juros_cobrados, a.cliente.nome)),
    ("Mais atrasos", lambda a: (-len(a.atrasados), -a.atraso_medio, a.cliente.nome)),
    ("Maior acréscimo (%)", lambda a: (-a.acrescimo, a.cliente.nome)),
    ("Nome", lambda a: (a.cliente.nome,)),
)


def _titulo(texto: str) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("rankingTitulo")
    return rotulo


def _rolavel(conteudo: QWidget) -> QScrollArea:
    rolagem = QScrollArea()
    rolagem.setWidgetResizable(True)
    rolagem.setFrameShape(QScrollArea.Shape.NoFrame)
    rolagem.setWidget(conteudo)
    return rolagem


def _cor(nome: str) -> QColor:
    return tema.cor(nome, cores.tema_atual())


# ------------------------------------------------------------ lista à esquerda


class _DelegadoCliente(QStyledItemDelegate):
    """Duas linhas por cliente e, à direita, o juros que ele pagou."""

    ALTURA = 50

    def sizeHint(self, _opcao, _indice) -> QSize:  # noqa: N802
        return QSize(220, self.ALTURA)

    def paint(self, pintor: QPainter, opcao, indice: QModelIndex) -> None:
        nome, detalhe, chip, cor_chip = indice.data(Qt.ItemDataRole.UserRole + 1)
        pintor.save()
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = opcao.rect.adjusted(4, 2, -4, -2)
        selecionado = bool(opcao.state & QStyle.StateFlag.State_Selected)
        if selecionado:
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(_cor("faixa"))
            pintor.drawRoundedRect(area, 6, 6)
            pintor.setBrush(_cor("destaque"))
            pintor.drawRoundedRect(QRect(area.left(), area.top() + 6, 3, area.height() - 12), 1, 1)

        fonte_chip = QFont(opcao.font)
        fonte_chip.setBold(True)
        largura_chip = pintor.fontMetrics().horizontalAdvance(chip) + 24 if chip else 0
        texto_area = area.adjusted(12, 6, -(largura_chip + 8), -6)

        fonte_nome = QFont(opcao.font)
        fonte_nome.setBold(True)
        pintor.setFont(fonte_nome)
        pintor.setPen(_cor("texto"))
        metrica = pintor.fontMetrics()
        pintor.drawText(
            texto_area.adjusted(0, 0, 0, -texto_area.height() // 2),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            metrica.elidedText(nome, Qt.TextElideMode.ElideRight, texto_area.width()),
        )
        pintor.setFont(fonte_ajustada(opcao.font, -1.5, minimo=7.5))
        pintor.setPen(_cor("texto_fraco"))
        metrica = pintor.fontMetrics()
        pintor.drawText(
            texto_area.adjusted(0, texto_area.height() // 2, 0, 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            metrica.elidedText(detalhe, Qt.TextElideMode.ElideRight, texto_area.width()),
        )

        if chip:
            pintor.setFont(fonte_chip)
            largura = pintor.fontMetrics().horizontalAdvance(chip) + 16
            caixa = QRect(area.right() - largura - 6, area.center().y() - 11, largura, 22)
            fundo = QColor(cor_chip)
            fundo.setAlphaF(0.14)
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(fundo)
            pintor.drawRoundedRect(caixa, 11, 11)
            pintor.setPen(cor_chip)
            pintor.drawText(caixa, Qt.AlignmentFlag.AlignCenter, chip)
        pintor.restore()


# ------------------------------------------------------------------- cenários


def _ajustar_altura(tabela: QTableWidget) -> None:
    """Tabela do tamanho do conteúdo: quem rola é a página, não a tabela."""
    altura = tabela.horizontalHeader().height() + 4
    altura += sum(tabela.rowHeight(linha) for linha in range(tabela.rowCount()))
    tabela.setFixedHeight(altura)


class TabelaCenarios(QWidget):
    """Os cenários de taxa lado a lado, mais uma linha para testar outro valor.

    Na análise de um cliente o valor testado é o juros ao dia (R$); na visão
    geral, um percentual sobre o juros de todos. Clicar numa linha escolhe o
    cenário que a tabela "honorário por honorário" compara.
    """

    cenario_escolhido = Signal(object)

    COLUNAS = ("Cenário", "Juros ao dia", "Juros no período", "A mais no período",
               "A mais por mês, daqui para frente")

    def __init__(self, por_cliente: bool, parent=None) -> None:
        super().__init__(parent)
        self.por_cliente = por_cliente
        self.analise: AnaliseJuros | None = None
        self.cenarios: list[servico.Cenario] = []
        self.testado: servico.Cenario | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        linha = QHBoxLayout()
        if por_cliente:
            linha.addWidget(QLabel("Testar outro juros ao dia:"))
            self.valor = QDoubleSpinBox()
            self.valor.setPrefix("R$ ")
            self.valor.setDecimals(2)
            self.valor.setRange(0.0, 100000.0)
            self.valor.setSingleStep(0.10)
        else:
            linha.addWidget(QLabel("Testar outro aumento, para todos:"))
            self.valor = QSpinBox()
            self.valor.setRange(-90, 500)
            self.valor.setSuffix(" %")
            self.valor.setValue(20)
        self.valor.valueChanged.connect(lambda *_: self._atualizar_personalizado())
        linha.addWidget(self.valor)
        linha.addStretch(1)
        layout.addLayout(linha)

        self.tabela = QTableWidget(0, len(self.COLUNAS))
        self.tabela.setHorizontalHeaderLabels(self.COLUNAS)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        if por_cliente:
            self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.tabela.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            self.tabela.itemSelectionChanged.connect(self._emitir)
            self.tabela.setToolTip("Clique num cenário para ver o efeito em cada honorário")
        else:
            self.tabela.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            self.tabela.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabela.setColumnHidden(1, not por_cliente)
        cabecalho = self.tabela.horizontalHeader()
        cabecalho.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        cabecalho.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.tabela)

        self.nota = widgets.rotulo_fraco(
            "Cada cenário repete os mesmos atrasos e a mesma proporção de abono do "
            "período, só trocando a taxa. \"Daqui para frente\" é o que os honorários "
            "atrasados hoje renderiam a mais por mês: mudança de juros nunca é "
            "retroativa, o juros que já correu não muda."
        )
        layout.addWidget(self.nota)

    def definir(self, analise: AnaliseJuros) -> None:
        linha_antes = self.tabela.currentRow()
        self.analise = analise
        self.cenarios = servico.cenarios(analise)
        self.tabela.blockSignals(True)
        self.tabela.setRowCount(len(self.cenarios) + 1)
        for linha, cenario in enumerate(self.cenarios):
            self._preencher(linha, cenario)
        if self.por_cliente:
            taxa = float(analise.taxa_atual or 0)
            self.valor.blockSignals(True)
            self.valor.setValue(round(taxa * 1.2, 2))
            self.valor.blockSignals(False)
            self.valor.setEnabled(taxa > 0)
        self._atualizar_personalizado(emitir=False)
        _ajustar_altura(self.tabela)
        if self.por_cliente:
            # mantém a linha escolhida ao trocar de cliente; na primeira vez, o testado
            ultima = self.tabela.rowCount() - 1
            self.tabela.selectRow(linha_antes if 0 <= linha_antes <= ultima else ultima)
        self.tabela.blockSignals(False)
        self._emitir()

    def escolhido(self) -> servico.Cenario | None:
        linha = self.tabela.currentRow()
        if 0 <= linha < len(self.cenarios):
            return self.cenarios[linha]
        if linha == len(self.cenarios):
            return self.testado
        return None

    def escolher(self, linha: int) -> None:
        self.tabela.selectRow(linha)

    def _emitir(self) -> None:
        if self.por_cliente and self.analise is not None:
            self.cenario_escolhido.emit(self.escolhido())

    def _aumento_testado(self) -> Decimal | None:
        if not self.por_cliente:
            return Decimal(self.valor.value())
        atual = self.analise.taxa_atual if self.analise else None
        if not atual:
            return None
        novo = Decimal(str(self.valor.value()))
        return (novo / atual - 1) * 100

    def _atualizar_personalizado(self, emitir: bool = True) -> None:
        if self.analise is None:
            return
        aumento = self._aumento_testado()
        linha = self.tabela.rowCount() - 1
        if aumento is None:
            self.testado = None
            for coluna in range(len(self.COLUNAS)):
                self.tabela.setItem(linha, coluna, QTableWidgetItem("—"))
        else:
            self.testado = servico.cenario(
                self.analise, aumento, f"Testado ({aumento:+.0f}%)"
            )
            self._preencher(linha, self.testado, testado=True)
        if emitir and self.tabela.currentRow() == linha:
            self._emitir()

    def _preencher(self, linha: int, cenario: servico.Cenario, testado: bool = False) -> None:
        valores = (
            cenario.rotulo,
            formatar_moeda(cenario.taxa_dia) if cenario.taxa_dia is not None else "",
            formatar_moeda(cenario.juros_no_periodo),
            _com_sinal(cenario.a_mais),
            _com_sinal(cenario.a_mais_por_mes),
        )
        for coluna, texto in enumerate(valores):
            item = QTableWidgetItem(texto)
            if coluna:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if coluna == 0:
                item.setToolTip(cenario.explicacao)
            if cenario.atual or testado:
                fonte = item.font()
                fonte.setBold(True)
                item.setFont(fonte)
            if coluna >= 3:
                valor = cenario.a_mais if coluna == 3 else cenario.a_mais_por_mes
                if valor > 0:
                    item.setForeground(_cor("pago"))
                elif valor < 0:
                    item.setForeground(_cor("atrasado"))
            self.tabela.setItem(linha, coluna, item)


def _com_sinal(valor: Decimal) -> str:
    if valor == 0:
        return "—"
    return ("+ " if valor > 0 else "− ") + formatar_moeda(abs(valor))


# ------------------------------------------------------------- indicadores


class Indicador(QFrame):
    """Rótulo, valor grande e, embaixo, uma nota curta (em geral a média geral)."""

    def __init__(self, rotulo: str, dica: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("cartao")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(1)
        self._rotulo = QLabel(rotulo)
        self._rotulo.setObjectName("rotuloCartao")
        self._valor = QLabel("—")
        self._valor.setObjectName("valorCartao")
        self._nota = QLabel("")
        self._nota.setObjectName("rotuloCartao")
        self._nota.setWordWrap(True)
        for widget in (self._rotulo, self._valor, self._nota):
            layout.addWidget(widget)
        layout.addStretch(1)   # valores alinhados no topo, mesmo com nota de duas linhas
        if dica:
            self.setToolTip(dica)

    def definir(self, valor: str, nota: str = "") -> None:
        self._valor.setText(valor)
        self._nota.setText(nota)
        self._nota.setVisible(bool(nota))

    def valor(self) -> str:
        return self._valor.text()


def _grade(indicadores: dict[str, Indicador], colunas: int) -> QGridLayout:
    grade = QGridLayout()
    grade.setSpacing(10)
    for posicao, indicador in enumerate(indicadores.values()):
        grade.addWidget(indicador, posicao // colunas, posicao % colunas)
    for coluna in range(colunas):
        grade.setColumnStretch(coluna, 1)
    return grade


def _dias(quantidade: int | Decimal) -> str:
    quantidade = int(round(quantidade))
    return f"{quantidade} dia" if quantidade == 1 else f"{quantidade} dias"


def _numero(valor: Decimal) -> str:
    return f"{valor:.1f}".replace(".", ",")


def _definir_trabalho(indicadores: dict[str, Indicador], analise: AnaliseJuros,
                      geral: AnaliseJuros | None) -> None:
    """Os indicadores do trabalho que deu para receber, comparados com a média."""
    for chave, (valor, nota) in servico.indicadores_de_trabalho(analise, geral).items():
        indicadores[chave].definir(valor, nota)


def _indicadores_de_trabalho() -> dict[str, Indicador]:
    return {
        chave: Indicador(rotulo, dica) for chave, rotulo, dica in servico.INDICADORES_TRABALHO
    }


# ----------------------------------------------------- original + juros = pago


class _Equacao(QWidget):
    """Original + juros = pago, em três caixas grandes."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.original = widgets.Cartao("Valor original")
        self.juros = widgets.Cartao("Juros recebido")
        self.pago = widgets.Cartao("Total pago")
        for posicao, cartao in enumerate((self.original, self.juros, self.pago)):
            if posicao:
                sinal = QLabel("+" if posicao == 1 else "=")
                sinal.setObjectName("rankingTitulo")
                layout.addWidget(sinal)
            layout.addWidget(cartao, 1)
        self.rodape = widgets.rotulo_fraco("")

    def definir(self, analise: AnaliseJuros) -> None:
        self.original.definir(analise.original)
        self.juros.definir(f"{formatar_moeda(analise.juros_cobrados)}")
        self.pago.definir(analise.recebido)
        cor = _cor("pago").name()
        self.juros._valor.setStyleSheet(f"color: {cor};")
        partes = [f"+{percentual(analise.acrescimo, 2)} sobre o original"]
        if analise.abono > 0:
            partes.append(f"{formatar_moeda(analise.abono)} de juros abonados")
        self.rodape.setText(" · ".join(partes))


# -------------------------------------------------------------- visão geral


class _VisaoGeral(QWidget):
    cliente_escolhido = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.addWidget(_titulo("Todos os clientes"))
        layout.addWidget(
            widgets.rotulo_fraco("Escolha um cliente na lista para ver a análise dele.")
        )

        self.equacao = _Equacao()
        layout.addWidget(self.equacao)
        layout.addWidget(self.equacao.rodape)

        layout.addWidget(_titulo("O trabalho para receber"))
        self.cartoes = _indicadores_de_trabalho()
        layout.addLayout(_grade(self.cartoes, 3))

        layout.addWidget(_titulo("Original × recebido por mês"))
        layout.addWidget(
            widgets.rotulo_fraco(
                "Azul claro: valor original · verde: juros recebido · em cima, quanto o "
                "recebido passou do original. Passe o mouse para ver os valores."
            )
        )
        self.grafico = GraficoMeses()
        layout.addWidget(self.grafico)

        layout.addWidget(_titulo("O que os números dizem"))
        self.leituras = QLabel()
        self.leituras.setObjectName("rankingCuriosidade")
        self.leituras.setWordWrap(True)
        layout.addWidget(self.leituras)

        layout.addWidget(_titulo("Cenários: e se o juros de todos subisse?"))
        self.cenarios = TabelaCenarios(por_cliente=False)
        layout.addWidget(self.cenarios)

        layout.addWidget(_titulo("Quem deu mais trabalho e quem mais pagou"))
        rankings = QGridLayout()
        rankings.setSpacing(14)
        self.ranking_trabalho = GraficoRanking("roxo")
        self.ranking_tempo = GraficoRanking("atrasado")
        self.ranking_juros = GraficoRanking("pago")
        self.ranking_acrescimo = GraficoRanking("atencao")
        for posicao, grafico in enumerate(
            (self.ranking_trabalho, self.ranking_tempo, self.ranking_juros,
             self.ranking_acrescimo)
        ):
            grafico.cliente_clicado.connect(self.cliente_escolhido)
            rankings.addWidget(grafico, posicao // 2, posicao % 2)
        layout.addLayout(rankings)
        layout.addWidget(
            widgets.rotulo_fraco(
                "Clique num nome dos rankings para ver a análise daquele cliente. Entram "
                "só honorários quitados com pagamento registrado no sistema: os "
                "importados da planilha como pagos não têm valor pago nem data. Antes de "
                "mudar a taxa, confira o que o contrato com cada cliente permite."
            )
        )
        layout.addStretch(1)

    def definir(self, analise: AnaliseJuros, animar: bool) -> None:
        self.equacao.definir(analise)
        _definir_trabalho(self.cartoes, analise, None)
        self.grafico.definir(analise.meses, animar=animar)
        leituras = analise.leituras()
        self.leituras.setText(
            "\n".join(f"•  {frase}" for frase in leituras)
            or "Nenhum honorário quitado com pagamento registrado neste período."
        )
        self.cenarios.definir(analise)
        self.ranking_trabalho.definir(analise.ranking_trabalho, animar=animar)
        self.ranking_tempo.definir(analise.ranking_tempo, animar=animar)
        self.ranking_juros.definir(analise.ranking_juros, animar=animar)
        self.ranking_acrescimo.definir(analise.ranking_acrescimo, animar=animar)


# ------------------------------------------------ cenário honorário a honorário


def _celula(texto: str, direita: bool = True, cor: QColor | None = None,
            negrito: bool = False, dica: str = "") -> QTableWidgetItem:
    item = QTableWidgetItem(texto)
    if direita:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if cor is not None:
        item.setForeground(cor)
    if negrito:
        fonte = item.font()
        fonte.setBold(True)
        item.setFont(fonte)
    if dica:
        item.setToolTip(dica)
    return item


def _tabela(colunas: tuple[str, ...]) -> QTableWidget:
    tabela = QTableWidget(0, len(colunas))
    tabela.setHorizontalHeaderLabels(colunas)
    tabela.verticalHeader().setVisible(False)
    tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    tabela.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    tabela.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    tabela.setAlternatingRowColors(True)
    # a página rola; a tabela ajusta o nome do honorário à largura que sobra
    tabela.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    tabela.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    cabecalho = tabela.horizontalHeader()
    cabecalho.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    cabecalho.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    return tabela


def _rotulo_curto(honorario) -> str:
    """Competência primeiro: se a coluna cortar o texto, corta o tipo, não o mês."""
    competencia = honorario.competencia_rotulo or honorario.descricao
    tipo = honorario.tipo.nome
    if not competencia:
        return tipo
    if competencia.startswith(tipo):
        return competencia
    return f"{competencia} · {tipo}"


def _diferenca(valor: Decimal) -> tuple[str, QColor | None]:
    if valor > 0:
        return "+ " + formatar_moeda(valor), _cor("pago")
    if valor < 0:
        return "− " + formatar_moeda(-valor), _cor("atrasado")
    return "—", None


class CenarioPorHonorario(QWidget):
    """O cenário escolhido aplicado a cada honorário: como foi e como ficaria."""

    COLUNAS_PAGOS = (
        "Honorário", "Venceu", "Pago em", "Atraso", "Original", "Juros pago",
        "Juros no cenário", "Diferença", "Total pago", "Total no cenário",
    )
    COLUNAS_ABERTOS = (
        "Honorário", "Venceu", "Atraso", "Total hoje", "Juros por dia",
        "Em 30 dias, como está", "Em 30 dias, no cenário",
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.analise: AnaliseJuros | None = None
        self.cenario: servico.Cenario | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.resumo = QLabel()
        self.resumo.setObjectName("previaMensagem")
        self.resumo.setWordWrap(True)
        layout.addWidget(self.resumo)

        topo = QHBoxLayout()
        self.titulo_pagos = QLabel("<b>Honorários pagos no período</b>")
        topo.addWidget(self.titulo_pagos)
        topo.addStretch(1)
        self.so_atrasados = QCheckBox("Só os pagos com atraso")
        self.so_atrasados.setChecked(True)
        self.so_atrasados.setToolTip("Quem pagou em dia não teve juros: o cenário não muda nada")
        self.so_atrasados.toggled.connect(lambda *_: self._preencher_pagos())
        topo.addWidget(self.so_atrasados)
        layout.addLayout(topo)
        self.pagos = _tabela(self.COLUNAS_PAGOS)
        layout.addWidget(self.pagos)
        self.vazio_pagos = widgets.rotulo_fraco("Nenhum honorário pago com atraso no período.")
        layout.addWidget(self.vazio_pagos)

        self.titulo_abertos = QLabel("<b>Em atraso hoje: daqui para frente</b>")
        layout.addWidget(self.titulo_abertos)
        self.abertos = _tabela(self.COLUNAS_ABERTOS)
        layout.addWidget(self.abertos)
        self.nota_abertos = widgets.rotulo_fraco(
            "O juros que já correu não muda: a taxa nova só valeria da data da mudança em "
            "diante. As duas últimas colunas mostram o total se ele pagar daqui a 30 dias."
        )
        layout.addWidget(self.nota_abertos)

    def definir(self, analise: AnaliseJuros, cenario: servico.Cenario | None) -> None:
        self.analise = analise
        self.cenario = cenario
        if cenario is None:
            self.resumo.setText("Escolha um cenário na tabela acima.")
            self.pagos.setRowCount(0)
            self.abertos.setRowCount(0)
            return
        taxa = analise.taxa_atual or ZERO
        if cenario.atual:
            texto = (
                f"Comparando com: <b>como está hoje</b> ({formatar_moeda(taxa)} ao dia). "
                "Clique noutro cenário da tabela acima para ver a diferença em cada "
                "honorário."
            )
        elif cenario.sem_abono:
            texto = (
                f"Comparando com: <b>mesma taxa, sem abono</b> — cada honorário pagaria "
                f"o juros devido inteiro, a {formatar_moeda(taxa)} ao dia."
            )
        else:
            texto = (
                f"Comparando com: <b>{cenario.rotulo}</b> — juros de "
                f"<b>{formatar_moeda(cenario.taxa_dia or ZERO)}</b> ao dia em vez de "
                f"{formatar_moeda(taxa)}, com os mesmos atrasos e o mesmo abono."
            )
        self.resumo.setText(texto)
        self._preencher_pagos()
        self._preencher_abertos()

    def _preencher_pagos(self) -> None:
        if self.analise is None or self.cenario is None:
            return
        linhas = servico.por_honorario(self.analise, self.cenario)
        if self.so_atrasados.isChecked():
            linhas = [linha for linha in linhas if linha.item.com_atraso]
        from .honorarios import _descricao

        self.pagos.setRowCount(len(linhas) + (1 if linhas else 0))
        for posicao, linha in enumerate(linhas):
            item = linha.item
            diferenca, cor = _diferenca(linha.diferenca)
            valores = (
                _celula(_rotulo_curto(item.honorario), direita=False,
                        dica=_descricao(item.honorario)),
                _celula(formatar_data(item.honorario.vencimento)),
                _celula(formatar_data(item.pago_em)),
                _celula(_dias(item.dias_atraso) if item.com_atraso else "em dia"),
                _celula(formatar_moeda(item.original)),
                _celula(formatar_moeda(item.juros_cobrados),
                        dica=f"Juros devido: {formatar_moeda(item.juros_devidos)}"),
                _celula(formatar_moeda(linha.juros_cenario), negrito=True),
                _celula(diferenca, cor=cor),
                _celula(formatar_moeda(item.pago)),
                _celula(formatar_moeda(linha.total_cenario), negrito=True),
            )
            for coluna, celula in enumerate(valores):
                self.pagos.setItem(posicao, coluna, celula)
        if linhas:
            total = len(linhas)
            juros = sum((linha.item.juros_cobrados for linha in linhas), start=ZERO)
            cenario = sum((linha.juros_cenario for linha in linhas), start=ZERO)
            pago = sum((linha.item.pago for linha in linhas), start=ZERO)
            original = sum((linha.item.original for linha in linhas), start=ZERO)
            diferenca, cor = _diferenca(cenario - juros)
            valores = (
                _celula(f"Total ({total} honorário{'s' if total > 1 else ''})",
                        direita=False, negrito=True),
                _celula(""), _celula(""),
                _celula(_dias(sum(linha.item.dias_atraso for linha in linhas)), negrito=True),
                _celula(formatar_moeda(original), negrito=True),
                _celula(formatar_moeda(juros), negrito=True),
                _celula(formatar_moeda(cenario), negrito=True),
                _celula(diferenca, cor=cor, negrito=True),
                _celula(formatar_moeda(pago), negrito=True),
                _celula(formatar_moeda(pago + cenario - juros), negrito=True),
            )
            for coluna, celula in enumerate(valores):
                self.pagos.setItem(total, coluna, celula)
        self.pagos.setVisible(bool(linhas))
        self.vazio_pagos.setVisible(not linhas)
        _ajustar_altura(self.pagos)

    def _preencher_abertos(self) -> None:
        linhas = servico.atrasados_no_cenario(self.analise, self.cenario)
        from .honorarios import _descricao

        self.abertos.setRowCount(len(linhas))
        for posicao, linha in enumerate(linhas):
            atrasado = linha.atrasado
            a_mais = linha.total_projetado_cenario - linha.total_projetado
            valores = (
                _celula(_rotulo_curto(atrasado.honorario), direita=False,
                        dica=_descricao(atrasado.honorario)),
                _celula(formatar_data(atrasado.honorario.vencimento)),
                _celula(_dias(atrasado.dias_atraso)),
                _celula(
                    formatar_moeda(atrasado.total),
                    dica=f"{formatar_moeda(atrasado.juros_ate_hoje)} de juros até hoje; "
                    f"{atrasado.cobrancas} cobrança(s) feita(s)",
                ),
                _celula(
                    f"{formatar_moeda(dinheiro(atrasado.juros_por_dia))} → "
                    f"{formatar_moeda(dinheiro(linha.juros_por_dia_cenario))}",
                    dica="Juros por dia hoje → no cenário",
                ),
                _celula(formatar_moeda(linha.total_projetado)),
                _celula(
                    formatar_moeda(linha.total_projetado_cenario), negrito=True,
                    cor=_cor("pago") if a_mais > 0 else None,
                    dica=f"{_diferenca(a_mais)[0]} em relação a como está",
                ),
            )
            for coluna, celula in enumerate(valores):
                self.abertos.setItem(posicao, coluna, celula)
        tem = bool(linhas)
        for widget in (self.titulo_abertos, self.abertos, self.nota_abertos):
            widget.setVisible(tem)
        _ajustar_altura(self.abertos)


# ---------------------------------------------------------- um cliente só


def cartao_de_pagamento(item: servico.HonorarioPago) -> DadosCartao:
    """Um honorário quitado: as datas, o original, o juros e o que foi pago."""
    from .honorarios import _descricao

    honorario = item.honorario
    atrasou = item.com_atraso
    cor = _cor("atencao" if atrasou else "pago")
    detalhes = [("Original", formatar_moeda(item.original))]
    if atrasou:
        detalhes += [
            ("Atraso", _dias(item.dias_atraso)),
            ("Cobranças", str(item.cobrancas) if item.cobrancas else "nenhuma"),
            ("Juros devido", formatar_moeda(item.juros_devidos)),
            ("Juros pago", formatar_moeda(item.juros_cobrados)),
        ]
    if item.abono > 0:
        detalhes.append(("Abonado", formatar_moeda(item.abono)))
    acrescimo = item.juros_cobrados / item.original * 100 if item.original else ZERO
    return DadosCartao(
        titulo=_descricao(honorario),
        datas=[
            DataCartao("Venceu", formatar_data(honorario.vencimento)),
            DataCartao("Pago em", formatar_data(item.pago_em), cor),
        ],
        situacao=f"Pago com {_dias(item.dias_atraso)} de atraso" if atrasou else "Pago em dia",
        cor=cor,
        detalhes=detalhes,
        valor=formatar_moeda(item.pago),
        valor_rotulo="Pago",
        complemento=f"+{percentual(acrescimo, 2)}" if item.juros_cobrados else "sem juros",
        item=item,
    )


class _DetalheCliente(QWidget):
    abrir_ficha = Signal(object)

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.analise: AnaliseJuros | None = None
        self.pdf_gerado = None
        self.pdf_com_fundo = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        topo = QHBoxLayout()
        textos = QVBoxLayout()
        textos.setSpacing(0)
        self.nome = _titulo("")
        self.subtitulo = widgets.rotulo_fraco("")
        textos.addWidget(self.nome)
        textos.addWidget(self.subtitulo)
        topo.addLayout(textos, 1)
        pdf = QPushButton("Exportar PDF…")
        pdf.setToolTip("Gera o PDF desta análise, com o cenário escolhido, para compartilhar")
        pdf.clicked.connect(lambda: self.exportar_pdf())   # clicked manda um bool
        topo.addWidget(pdf)
        ficha = QPushButton("Abrir ficha / alterar juros")
        ficha.clicked.connect(lambda: self.analise and self.abrir_ficha.emit(self.analise.cliente))
        topo.addWidget(ficha)
        layout.addLayout(topo)

        self.equacao = _Equacao()
        layout.addWidget(self.equacao)
        layout.addWidget(self.equacao.rodape)

        layout.addWidget(_titulo("O trabalho que deu para receber"))
        self.cartoes = _indicadores_de_trabalho()
        layout.addLayout(_grade(self.cartoes, 3))

        layout.addWidget(_titulo("Explicando"))
        self.explicacao = QLabel()
        self.explicacao.setObjectName("rankingCuriosidade")
        self.explicacao.setWordWrap(True)
        layout.addWidget(self.explicacao)

        layout.addWidget(_titulo("Cenários: e se o juros dele fosse outro?"))
        self.cenarios = TabelaCenarios(por_cliente=True)
        layout.addWidget(self.cenarios)

        layout.addWidget(_titulo("Cenário honorário por honorário"))
        self.por_honorario = CenarioPorHonorario()
        self.cenarios.cenario_escolhido.connect(
            lambda cenario: self.analise and self.por_honorario.definir(self.analise, cenario)
        )
        layout.addWidget(self.por_honorario)

        layout.addWidget(_titulo("Histórico dos pagamentos"))
        self.pagamentos = QVBoxLayout()
        self.pagamentos.setSpacing(8)
        layout.addLayout(self.pagamentos)
        self.mais = widgets.rotulo_fraco("")
        layout.addWidget(self.mais)
        layout.addStretch(1)

    def exportar_pdf(self, destino: str | None = None) -> None:
        """PDF da análise do cliente, com o cenário escolhido na tabela."""
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        from ...config.caminhos import pasta_exportacoes
        from ...servicos import configuracoes, relatorio_juros

        if self.analise is None:
            return
        cliente = self.analise.cliente
        if destino is None:
            sugestao = pasta_exportacoes() / f"analise-juros-{cliente.codigo}.pdf"
            destino, _ = QFileDialog.getSaveFileName(
                self, "Exportar análise de juros", str(sugestao), "PDF (*.pdf)"
            )
            if not destino:
                return
        if not destino.lower().endswith(".pdf"):
            destino += ".pdf"
        def acao():
            import tempfile

            from ...servicos import imagem_cobranca
            from ..comum.imagem_cobranca import renderizar_pagina

            sessao = self.contexto.sessao
            svg = imagem_cobranca.caminho_fundo(sessao).read_text(encoding="utf-8")
            base = imagem_cobranca.base_do_fundo(svg)
            with tempfile.TemporaryDirectory() as pasta:
                papel = None
                if base is not None:
                    # A4 a ~200 dpi: nítido na tela e na impressão, arquivo leve
                    papel = Path(pasta) / "papel.png"
                    renderizar_pagina(base, 1654, 2339).save(str(papel), "PNG")
                arquivo = relatorio_juros.analise_cliente_pdf(
                    self.analise,
                    self.cenarios.escolhido(),
                    configuracoes.recebedor(sessao),
                    Path(destino),
                    self.contexto.data_referencia,
                    fundo=papel,
                )
            self.pdf_com_fundo = base is not None
            return arquivo

        deu_certo, arquivo = widgets.executar(self, acao)
        if deu_certo:
            self.pdf_gerado = arquivo
            widgets.abrir_url(f"file://{arquivo}")

    def definir(self, analise: AnaliseJuros) -> None:
        self.analise = analise
        cliente = analise.cliente
        self.nome.setText(f"{cliente.codigo} – {cliente.nome}")
        self.subtitulo.setText(
            f"Juros hoje: {formatar_moeda(analise.taxa_atual or ZERO)} ao dia · "
            f"{len(analise.honorarios)} honorário(s) pago(s) no período"
        )
        self.equacao.definir(analise)
        _definir_trabalho(self.cartoes, analise, analise.geral)
        self.explicacao.setText(
            "\n".join(f"•  {frase}" for frase in servico.explicar_cliente(analise))
        )
        self.cenarios.definir(analise)

        while self.pagamentos.count():
            widget = self.pagamentos.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for item in analise.honorarios[:LIMITE_PAGAMENTOS]:
            self.pagamentos.addWidget(CartaoRegistro(cartao_de_pagamento(item)))
        restantes = len(analise.honorarios) - LIMITE_PAGAMENTOS
        self.mais.setText(
            f"… e mais {restantes} mais antigo(s). Reduza o período para vê-los."
            if restantes > 0 else ""
        )
        self.mais.setVisible(restantes > 0)


# ------------------------------------------------------------------- a aba


class AbaAnaliseJuros(QWidget):
    cliente_clicado = Signal(object)   # pede a ficha do cliente

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.analise: AnaliseJuros | None = None
        self.por_cliente: list[AnaliseJuros] = []
        self.limite = 10
        self._montar()

    # ------------------------------------------------------------------ tela
    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        topo = QHBoxLayout()
        topo.addWidget(_titulo("Vale aumentar o juros?"))
        topo.addStretch(1)
        topo.addWidget(QLabel("Pagos em:"))
        self.periodo = QComboBox()
        for rotulo, meses in servico.PERIODOS:
            self.periodo.addItem(rotulo, meses)
        self.periodo.setCurrentIndex(2)
        self.periodo.currentIndexChanged.connect(lambda *_: self.recarregar())
        topo.addWidget(self.periodo)
        layout.addLayout(topo)

        divisor = QSplitter(Qt.Orientation.Horizontal)
        esquerda = QFrame()
        coluna = QVBoxLayout(esquerda)
        coluna.setContentsMargins(0, 0, 4, 0)
        coluna.setSpacing(6)
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Procurar cliente…")
        self.busca.setClearButtonEnabled(True)
        self.busca.textChanged.connect(lambda *_: self._preencher_lista())
        coluna.addWidget(self.busca)
        self.ordem = QComboBox()
        for rotulo, _ in ORDENS:
            self.ordem.addItem(f"Ordenar: {rotulo}")
        self.ordem.currentIndexChanged.connect(lambda *_: self._preencher_lista())
        coluna.addWidget(self.ordem)
        self.lista = QListWidget()
        self.lista.setObjectName("listaAnalise")
        self.lista.setItemDelegate(_DelegadoCliente(self.lista))
        self.lista.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.lista.currentItemChanged.connect(lambda *_: self._mostrar_escolhido())
        coluna.addWidget(self.lista, 1)
        self.contagem = widgets.rotulo_fraco("")
        coluna.addWidget(self.contagem)
        divisor.addWidget(esquerda)

        self.paginas = QStackedWidget()
        self.visao_geral = _VisaoGeral()
        self.visao_geral.cliente_escolhido.connect(self.escolher_cliente)
        self.detalhe = _DetalheCliente(self.contexto)
        self.detalhe.abrir_ficha.connect(self.cliente_clicado)
        self.rolagem_geral = _rolavel(self.visao_geral)
        self.rolagem_cliente = _rolavel(self.detalhe)
        self.paginas.addWidget(self.rolagem_geral)
        self.paginas.addWidget(self.rolagem_cliente)
        divisor.addWidget(self.paginas)
        divisor.setStretchFactor(1, 1)
        divisor.setSizes([290, 900])
        layout.addWidget(divisor, 1)

    # ---------------------------------------------------------------- dados
    def _desde(self):
        meses = self.periodo.currentData()
        if meses is None:
            return None
        return somar_meses(self.contexto.data_referencia, -(meses - 1)).replace(day=1)

    def recarregar(self, limite: int | None = None, animar: bool = True) -> None:
        if limite is not None:
            self.limite = limite
        self.analise = servico.analisar(
            self.contexto.sessao, self._desde(), self.contexto.data_referencia, self.limite
        )
        self.por_cliente = self.analise.clientes()
        self.visao_geral.definir(self.analise, animar)
        self._preencher_lista()

    def _preencher_lista(self) -> None:
        escolhido = self.cliente_escolhido_id()
        termo = normalizar_busca(self.busca.text())
        chave = ORDENS[max(0, self.ordem.currentIndex())][1]
        visiveis = [
            analise for analise in sorted(self.por_cliente, key=chave)
            if not termo
            or termo in normalizar_busca(analise.cliente.nome)
            or termo == analise.cliente.codigo
        ]

        self.lista.blockSignals(True)
        self.lista.clear()
        geral = QListWidgetItem()
        geral.setData(Qt.ItemDataRole.UserRole, None)
        geral.setData(
            Qt.ItemDataRole.UserRole + 1,
            (
                "Visão geral",
                f"Todos os {len(self.por_cliente)} clientes que pagaram",
                "", _cor("destaque"),
            ),
        )
        self.lista.addItem(geral)
        atual = geral
        for analise in visiveis:
            item = QListWidgetItem()
            cliente = analise.cliente
            item.setData(Qt.ItemDataRole.UserRole, cliente.id)
            atrasos = len(analise.atrasados)
            detalhe = (
                f"{atrasos} atraso(s) · {_dias(analise.dias_em_atraso)} · "
                f"{analise.cobrancas} cobrança(s)"
                if atrasos else f"{len(analise.honorarios)} pago(s), tudo em dia"
            )
            if analise.juros_cobrados > 0:
                chip, cor = f"+{formatar_moeda(analise.juros_cobrados)}", _cor("pago")
            else:
                chip, cor = "em dia", _cor("texto_fraco")
            item.setData(
                Qt.ItemDataRole.UserRole + 1, (f"{cliente.codigo} – {cliente.nome}", detalhe,
                                               chip, cor)
            )
            item.setToolTip(cliente.nome)
            self.lista.addItem(item)
            if cliente.id == escolhido:
                atual = item
        self.lista.setCurrentItem(atual)
        self.lista.blockSignals(False)
        self.contagem.setText(
            f"{len(visiveis)} de {len(self.por_cliente)} cliente(s) pagaram no período"
        )
        self._mostrar_escolhido()

    def cliente_escolhido_id(self) -> int | None:
        item = self.lista.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def escolher_cliente(self, cliente) -> None:
        """Seleciona o cliente na lista (limpa a busca se ele estiver escondido)."""
        cliente_id = getattr(cliente, "id", cliente)
        for linha in range(self.lista.count()):
            if self.lista.item(linha).data(Qt.ItemDataRole.UserRole) == cliente_id:
                self.lista.setCurrentRow(linha)
                return
        if self.busca.text():
            self.busca.clear()
            self.escolher_cliente(cliente_id)

    def _mostrar_escolhido(self) -> None:
        cliente_id = self.cliente_escolhido_id()
        analise = self.analise.do_cliente(cliente_id) if (self.analise and cliente_id) else None
        if analise is None:
            self.paginas.setCurrentWidget(self.rolagem_geral)
            return
        self.detalhe.definir(analise)
        self.paginas.setCurrentWidget(self.rolagem_cliente)
        self.rolagem_cliente.verticalScrollBar().setValue(0)
