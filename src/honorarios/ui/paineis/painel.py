"""Painel: emitido, recebido, em aberto, juros e inadimplência.

Cada bloco diz em que eixo olha (competência ou vencimento), porque o Dashboard
da planilha misturava os dois e dava número diferente do esperado.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...servicos import relatorios
from ..comum import widgets
from ..comum.tabelas import (
    Coluna,
    ModeloTabela,
    ajustar_colunas,
    coluna_inteiro,
    coluna_moeda,
    preparar_tabela,
)
from ..contexto import Contexto


class PainelResumo(QWidget):
    titulo = "Painel"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self._montar()
        self.recarregar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self.cabecalho = widgets.Cabecalho("Painel", "")
        self.cabecalho.adicionar_botao("Exportar PDF", self._exportar)
        self.cabecalho.adicionar_botao("Atualizar", self.recarregar, atalho="F5")
        layout.addWidget(self.cabecalho)

        seletor = QHBoxLayout()
        seletor.addWidget(widgets.rotulo_fraco("Ano de análise (por competência):"))
        self.ano = QComboBox()
        for ano in relatorios.anos_disponiveis(self.contexto.sessao):
            self.ano.addItem(str(ano), ano)
        self.ano.currentIndexChanged.connect(lambda *_: self.recarregar())
        seletor.addWidget(self.ano)
        seletor.addStretch(1)
        layout.addLayout(seletor)

        cartoes = QHBoxLayout()
        self.cartao_emitido = widgets.Cartao(
            "Emitido no ano", dica="Soma dos valores originais, por competência"
        )
        self.cartao_recebido = widgets.Cartao(
            "Pago no ano",
            dica="Honorários da competência do ano que estão pagos (valor congelado na baixa)",
        )
        self.cartao_aberto = widgets.Cartao("Em aberto (principal)")
        self.cartao_juros = widgets.Cartao("Juros acumulado")
        self.cartao_total = widgets.Cartao("Total atualizado em aberto")
        self.cartao_inadimplencia = widgets.Cartao("Inadimplência")
        for cartao in (
            self.cartao_emitido,
            self.cartao_recebido,
            self.cartao_aberto,
            self.cartao_juros,
            self.cartao_total,
            self.cartao_inadimplencia,
        ):
            cartoes.addWidget(cartao)
        layout.addLayout(cartoes)

        meio = QHBoxLayout()

        grupo_mes = QGroupBox("Por mês de competência")
        caixa_mes = QVBoxLayout(grupo_mes)
        self.modelo_mes = ModeloTabela(
            [
                Coluna("Mês", lambda item: item[0], alinhamento=Qt.AlignmentFlag.AlignCenter),
                coluna_moeda("Emitido", lambda item: item[1]),
                coluna_moeda("Pago", lambda item: item[2]),
                coluna_moeda("Em aberto (atualizado)", lambda item: item[3], negrito=True),
            ]
        )
        self.tabela_mes = preparar_tabela(QTableView(), esticar=3)
        self.tabela_mes.setModel(self.modelo_mes)
        self.tabela_mes.setSortingEnabled(False)
        caixa_mes.addWidget(self.tabela_mes)
        meio.addWidget(grupo_mes, 2)

        grupo_faixas = QGroupBox("Faixas de atraso (situação atual)")
        caixa_faixas = QVBoxLayout(grupo_faixas)
        self.modelo_faixas = ModeloTabela(
            [
                Coluna(
                    "Faixa (dias)", lambda item: item[0],
                    alinhamento=Qt.AlignmentFlag.AlignCenter,
                ),
                coluna_inteiro("Honorários", lambda item: item[1]),
                coluna_moeda("Total", lambda item: item[2], negrito=True),
            ]
        )
        self.tabela_faixas = preparar_tabela(QTableView(), esticar=2)
        self.tabela_faixas.setModel(self.modelo_faixas)
        self.tabela_faixas.setSortingEnabled(False)
        caixa_faixas.addWidget(self.tabela_faixas)
        meio.addWidget(grupo_faixas, 1)
        layout.addLayout(meio, 1)

        baixo = QHBoxLayout()
        grupo_devedores = QGroupBox("Maiores devedores (total atualizado)")
        caixa_devedores = QVBoxLayout(grupo_devedores)
        self.modelo_devedores = ModeloTabela(
            [
                Coluna("Empresa", lambda item: item[0]),
                coluna_moeda("Total", lambda item: item[1], negrito=True),
                coluna_inteiro("Honorários", lambda item: item[2]),
            ]
        )
        self.tabela_devedores = preparar_tabela(QTableView(), esticar=0)
        self.tabela_devedores.setModel(self.modelo_devedores)
        caixa_devedores.addWidget(self.tabela_devedores)
        baixo.addWidget(grupo_devedores, 2)

        grupo_grupos = QGroupBox("Em aberto por grupo e por tipo de pessoa")
        caixa_grupos = QVBoxLayout(grupo_grupos)
        self.modelo_grupos = ModeloTabela(
            [
                Coluna("Recorte", lambda item: item[0]),
                coluna_inteiro("Honorários", lambda item: item[1]),
                coluna_moeda("Total", lambda item: item[2], negrito=True),
            ]
        )
        self.tabela_grupos = preparar_tabela(QTableView(), esticar=0)
        self.tabela_grupos.setModel(self.modelo_grupos)
        caixa_grupos.addWidget(self.tabela_grupos)
        baixo.addWidget(grupo_grupos, 1)
        layout.addLayout(baixo, 1)

    def recarregar(self) -> None:
        self.contexto.atualizar()
        ano = self.ano.currentData()
        dados = relatorios.indicadores(
            self.contexto.sessao, ano, self.contexto.data_referencia
        )
        self.indicadores = dados
        self.cabecalho.definir_subtitulo(
            f"Valores atualizados para {dados.referencia:%d/%m/%Y} · "
            f"{dados.quantidade_emitida} honorário(s) emitidos em {dados.ano}"
        )
        self.cartao_emitido.definir(dados.emitido)
        self.cartao_recebido.definir(dados.pago)
        self.cartao_aberto.definir(dados.em_aberto)
        self.cartao_juros.definir(dados.juros_acumulado)
        self.cartao_total.definir(dados.total_atualizado)
        self.cartao_inadimplencia.definir(f"{dados.inadimplencia}%")
        self.modelo_mes.definir_itens(dados.por_mes)
        self.modelo_faixas.definir_itens(dados.faixas_atraso)
        self.modelo_devedores.definir_itens(dados.maiores_devedores)
        self.modelo_grupos.definir_itens([*dados.por_grupo, *dados.por_tipo_pessoa])
        for tabela, modelo in (
            (self.tabela_mes, self.modelo_mes),
            (self.tabela_faixas, self.modelo_faixas),
            (self.tabela_devedores, self.modelo_devedores),
            (self.tabela_grupos, self.modelo_grupos),
        ):
            ajustar_colunas(tabela, modelo.colunas)

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
