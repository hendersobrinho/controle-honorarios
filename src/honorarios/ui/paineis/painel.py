"""Painel: o ano em números e em gráficos — o que foi emitido, o que entrou e de
onde vem o faturamento.

Atraso e devedores não aparecem aqui: para isso existe o Ranking dos atrasados.
Cada bloco diz em que eixo olha (competência ou data da baixa), porque o
Dashboard da planilha misturava os dois.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...dominio.valores import formatar_moeda
from ...servicos import relatorios
from ..comum import widgets
from ..comum.graficos_painel import (
    GraficoBarrasHorizontais,
    GraficoColunas,
    GraficoQuitacao,
)
from ..comum.tabelas import Coluna, ModeloTabela, ajustar_colunas, coluna_moeda, preparar_tabela
from ..contexto import Contexto


def _titulo(texto: str, subtitulo: str = "") -> QWidget:
    caixa = QWidget()
    layout = QVBoxLayout(caixa)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    rotulo = QLabel(texto)
    rotulo.setObjectName("rankingTitulo")
    layout.addWidget(rotulo)
    if subtitulo:
        layout.addWidget(widgets.rotulo_fraco(subtitulo))
    return caixa


class PainelResumo(QWidget):
    titulo = "Painel"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self._montar()
        self.recarregar(animar=False)

    def _montar(self) -> None:
        externo = QVBoxLayout(self)
        externo.setSpacing(10)
        self.cabecalho = widgets.Cabecalho("Painel", "")
        self.ano = QComboBox()
        for ano in relatorios.anos_disponiveis(self.contexto.sessao):
            self.ano.addItem(str(ano), ano)
        indice = self.ano.findData(self.contexto.data_referencia.year)
        self.ano.setCurrentIndex(max(0, indice))
        self.ano.currentIndexChanged.connect(lambda *_: self.recarregar())
        self.cabecalho.acoes.addWidget(QLabel("Ano (competência):"))
        self.cabecalho.acoes.addWidget(self.ano)
        self.cabecalho.adicionar_botao("Exportar PDF", self._exportar)
        self.cabecalho.adicionar_botao("Atualizar", self.recarregar, atalho="F5")
        externo.addWidget(self.cabecalho)

        conteudo = QWidget()
        layout = QVBoxLayout(conteudo)
        layout.setContentsMargins(0, 0, 8, 8)
        layout.setSpacing(14)

        self.cartoes = {
            "emitido": widgets.Cartao("Emitido no ano", dica="Soma dos valores originais, "
                                      "pela competência"),
            "quitado": widgets.Cartao("Quitado", dica="Do que foi emitido no ano, quanto já "
                                      "foi quitado (valor original)"),
            "aberto": widgets.Cartao("Em aberto", dica="Do que foi emitido no ano, quanto "
                                     "falta (valor original, sem juros)"),
            "caixa": widgets.Cartao("Entrou no caixa", dica="Baixas registradas no ano, de "
                                    "qualquer competência, com juros"),
            "clientes": widgets.Cartao("Clientes faturados"),
            "ticket": widgets.Cartao("Valor médio por honorário"),
        }
        linha = QHBoxLayout()
        linha.setSpacing(10)
        for cartao in self.cartoes.values():
            linha.addWidget(cartao)
        layout.addLayout(linha)

        grade = QGridLayout()
        grade.setHorizontalSpacing(16)
        grade.setVerticalSpacing(16)

        # emitido x quitado, com a alternativa em tabela (acessível e conferível)
        topo_quitacao = QHBoxLayout()
        topo_quitacao.addWidget(_titulo(
            "Emitido por mês: quanto já foi quitado",
            "Pela competência. Passe o mouse numa barra para ver os valores.",
        ), 1)
        self.alternar = QPushButton("Ver em tabela")
        self.alternar.clicked.connect(lambda: self._alternar_tabela())
        topo_quitacao.addWidget(self.alternar, 0, Qt.AlignmentFlag.AlignTop)
        bloco_quitacao = QVBoxLayout()
        bloco_quitacao.addLayout(topo_quitacao)
        self.quitacao = GraficoQuitacao()
        self.modelo_mes = ModeloTabela([
            Coluna("Mês", lambda mes: mes.rotulo, alinhamento=Qt.AlignmentFlag.AlignCenter),
            coluna_moeda("Emitido", lambda mes: mes.emitido),
            coluna_moeda("Quitado", lambda mes: mes.quitado),
            coluna_moeda("Em aberto", lambda mes: mes.em_aberto),
            Coluna("% quitado", lambda mes: f"{mes.percentual_quitado:.0f}%" if mes.emitido else
                   "—", alinhamento=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            coluna_moeda("Entrou no caixa", lambda mes: mes.recebido),
        ])
        self.tabela_mes = preparar_tabela(QTableView(), esticar=0)
        self.tabela_mes.setModel(self.modelo_mes)
        self.tabela_mes.setSortingEnabled(False)
        self.pilha_quitacao = QStackedWidget()
        self.pilha_quitacao.addWidget(self.quitacao)
        self.pilha_quitacao.addWidget(self.tabela_mes)
        self.pilha_quitacao.setMinimumHeight(290)
        bloco_quitacao.addWidget(self.pilha_quitacao, 1)
        grade.addLayout(bloco_quitacao, 0, 0)

        bloco_leituras = QVBoxLayout()
        bloco_leituras.addWidget(_titulo("O que os números dizem"))
        self.leituras = QLabel()
        self.leituras.setObjectName("rankingCuriosidade")
        self.leituras.setWordWrap(True)
        self.leituras.setAlignment(Qt.AlignmentFlag.AlignTop)
        bloco_leituras.addWidget(self.leituras, 1)
        grade.addLayout(bloco_leituras, 0, 1)

        bloco_caixa = QVBoxLayout()
        bloco_caixa.addWidget(_titulo(
            "Entrou no caixa por mês",
            "Pela data da baixa, com juros, de qualquer competência.",
        ))
        self.caixa = GraficoColunas()
        bloco_caixa.addWidget(self.caixa, 1)
        grade.addLayout(bloco_caixa, 1, 0)

        bloco_origem = QVBoxLayout()
        bloco_origem.addWidget(_titulo(
            "De onde vem o faturamento", "Emitido no ano, por grupo e por tipo de cliente."
        ))
        self.origem = GraficoBarrasHorizontais()
        bloco_origem.addWidget(self.origem, 1)
        grade.addLayout(bloco_origem, 1, 1)

        grade.setColumnStretch(0, 3)
        grade.setColumnStretch(1, 2)
        layout.addLayout(grade)
        layout.addWidget(widgets.rotulo_fraco(
            "Atraso, juros e quem mais deve estão no Ranking dos atrasados."
        ))
        layout.addStretch(1)

        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QScrollArea.Shape.NoFrame)
        rolagem.setWidget(conteudo)
        externo.addWidget(rolagem, 1)

    def _alternar_tabela(self) -> None:
        tabela = self.pilha_quitacao.currentWidget() is self.quitacao
        self.pilha_quitacao.setCurrentWidget(self.tabela_mes if tabela else self.quitacao)
        self.alternar.setText("Ver em gráfico" if tabela else "Ver em tabela")
        if tabela:
            ajustar_colunas(self.tabela_mes, self.modelo_mes.colunas)

    def recarregar(self, animar: bool = True) -> None:
        self.contexto.atualizar()
        dados = relatorios.indicadores(
            self.contexto.sessao, self.ano.currentData(), self.contexto.data_referencia
        )
        self.indicadores = dados
        self.cabecalho.definir_subtitulo(
            f"{dados.ano} · valores atualizados para {dados.referencia:%d/%m/%Y}"
        )
        self.cartoes["emitido"].definir(dados.emitido)
        self.cartoes["quitado"].definir(
            f"{formatar_moeda(dados.quitado)}  ({dados.percentual_quitado:.0f}%)"
        )
        self.cartoes["aberto"].definir(dados.em_aberto)
        self.cartoes["caixa"].definir(dados.recebido_no_caixa)
        self.cartoes["clientes"].definir(str(dados.clientes_faturados))
        self.cartoes["ticket"].definir(dados.ticket_medio)

        self.quitacao.definir(dados.meses, animar=animar)
        self.modelo_mes.definir_itens(dados.meses)
        ajustar_colunas(self.tabela_mes, self.modelo_mes.colunas)
        self.caixa.definir(
            [mes.rotulo for mes in dados.meses],
            [mes.recebido for mes in dados.meses],
            "Entrou no caixa",
            animar=animar,
        )
        self.origem.definir(
            [("Por grupo", dados.por_grupo), ("Por tipo de cliente", dados.por_tipo_pessoa)],
            animar=animar,
        )
        self.leituras.setText("\n\n".join(f"•  {frase}" for frase in dados.leituras()))

    def _exportar(self) -> None:
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        from ...config.caminhos import pasta_exportacoes
        from ...servicos import exportacao

        sugestao = str(pasta_exportacoes() / f"painel-{self.indicadores.ano}.pdf")
        caminho, _ = QFileDialog.getSaveFileName(self, "Exportar painel", sugestao, "PDF (*.pdf)")
        if not caminho:
            return

        def acao():
            return exportacao.painel_pdf(self.indicadores.como_dicionario, Path(caminho))

        deu_certo, arquivo = widgets.executar(self, acao)
        if deu_certo:
            widgets.informar(self, f"Painel salvo em:\n{arquivo}", "Exportado")
