"""Rankings: quem mais deve, há mais tempo, com mais boletos e o mais cobrado.

Dois gráficos por aba, lado a lado. Clicar num nome abre a ficha do cliente.
A última aba é a análise de juros: original × recebido, para decidir a taxa.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...servicos import rankings as servico
from ..comum import widgets
from ..comum.grafico_ranking import GraficoRanking
from ..contexto import Contexto
from .analise_juros import AbaAnaliseJuros

# (aba, [(chave do ranking, cor da barra), ...])
ABAS = (
    ("💰  Dinheiro e tempo", (("devedores", "atrasado"), ("tempo", "atencao"))),
    ("📚  Boletos e cobranças", (("honorarios", "destaque"), ("cobrados", "roxo"))),
)


class PainelRankings(QWidget):
    titulo = "Rankings"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.graficos: dict[str, GraficoRanking] = {}
        self._montar()
        self.recarregar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self.cabecalho = widgets.Cabecalho(
            "Rankings",
            "Quem mais deve, quem deve há mais tempo, quem junta mais boletos, quem "
            "mais foi cobrado — e quanto o juros rende de verdade",
        )
        self.tamanho = QComboBox()
        self.tamanho.addItem("Top 5", 5)
        self.tamanho.addItem("Top 10", 10)
        self.tamanho.setCurrentIndex(1)
        self.tamanho.currentIndexChanged.connect(lambda *_: self.recarregar())
        self.cabecalho.acoes.addWidget(self.tamanho)
        self.cabecalho.adicionar_botao("Atualizar", self.recarregar, atalho="F5")
        layout.addWidget(self.cabecalho)

        self.abas = QTabWidget()
        self.abas.currentChanged.connect(lambda *_: self._animar_aba_atual())
        for rotulo, graficos in ABAS:
            pagina = QWidget()
            linha = QHBoxLayout(pagina)
            linha.setContentsMargins(12, 12, 12, 12)
            linha.setSpacing(14)
            for chave, cor in graficos:
                grafico = GraficoRanking(cor)
                grafico.cliente_clicado.connect(self._abrir_ficha)
                self.graficos[chave] = grafico
                linha.addWidget(grafico, 1)
            rolagem = QScrollArea()
            rolagem.setWidgetResizable(True)
            rolagem.setFrameShape(QScrollArea.Shape.NoFrame)
            rolagem.setWidget(pagina)
            self.abas.addTab(rolagem, rotulo)

        self.analise = AbaAnaliseJuros(self.contexto)
        self.analise.cliente_clicado.connect(self._abrir_ficha)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QScrollArea.Shape.NoFrame)
        rolagem.setWidget(self.analise)
        self.indice_analise = self.abas.addTab(rolagem, "📈  Análise de juros")
        layout.addWidget(self.abas, 1)

        layout.addWidget(
            widgets.rotulo_fraco(
                "Clique num nome para abrir a ficha do cliente. Valores com juros até "
                "hoje; cada mensagem enviada conta como uma tentativa de cobrança."
            )
        )

    def recarregar(self) -> None:
        self.contexto.atualizar()
        self.rankings = servico.calcular(
            self.contexto.sessao, self.contexto.data_referencia, self.tamanho.currentData()
        )
        for chave, grafico in self.graficos.items():
            grafico.definir(self.rankings[chave], animar=False)
        self.analise.recarregar(self.tamanho.currentData(), animar=False)
        self._animar_aba_atual()

    def _animar_aba_atual(self) -> None:
        """As barras crescem de novo sempre que a aba aparece."""
        indice = self.abas.currentIndex()
        if not hasattr(self, "rankings") or indice < 0:
            return
        if indice == self.indice_analise:
            self.analise.recarregar(self.tamanho.currentData())
            return
        for chave, _ in ABAS[indice][1]:
            self.graficos[chave].definir(self.rankings[chave], animar=True)

    def _abrir_ficha(self, cliente) -> None:
        from ..dialogos.ficha import DialogoFicha

        DialogoFicha(self.contexto, cliente, self).exec()
        self.recarregar()
