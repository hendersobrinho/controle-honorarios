"""Importação da planilha antiga: prévia, relatório de erros e confirmação."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...dominio.valores import ZERO, formatar_moeda
from ...servicos.importacao import executor, leitor
from ..comum import tema, widgets
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


class PainelImportar(QWidget):
    titulo = "Importar planilha"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.leitura: leitor.Leitura | None = None
        self._montar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self.cabecalho = widgets.Cabecalho(
            "Importar planilha",
            "Lê a planilha de controle, mostra a prévia e só grava depois da sua confirmação",
        )
        self.cabecalho.adicionar_botao("Escolher arquivo…", self._escolher, primario=True)
        self.cabecalho.adicionar_botao("Importar marcados", self._importar)
        layout.addWidget(self.cabecalho)

        linha = QHBoxLayout()
        self.caminho = QLineEdit()
        self.caminho.setPlaceholderText("Nenhum arquivo selecionado")
        self.caminho.setReadOnly(True)
        linha.addWidget(self.caminho, 1)
        self.criar_clientes = QCheckBox("Criar clientes que faltam")
        self.criar_clientes.setChecked(True)
        self.importar_pagos = QCheckBox("Importar honorários já pagos")
        self.importar_pagos.setChecked(True)
        self.importar_cobrancas = QCheckBox("Importar cobranças das observações")
        self.importar_cobrancas.setChecked(True)
        for caixa in (self.criar_clientes, self.importar_pagos, self.importar_cobrancas):
            linha.addWidget(caixa)
        layout.addLayout(linha)

        self.abas = QTabWidget()
        self.modelo_linhas = ModeloTabelaMarcavel(
            [
                Coluna("", lambda item: "", largura=28),
                Coluna("Aba", lambda item: item.aba),
                Coluna("Linha", lambda item: str(item.linha),
                       alinhamento=Qt.AlignmentFlag.AlignCenter),
                Coluna("Cliente", lambda item: f"{item.codigo} – {item.nome}"),
                Coluna("Tipo", lambda item: item.tipo_honorario),
                Coluna("Competência", lambda item: item.competencia.rotulo() or item.descricao,
                       alinhamento=Qt.AlignmentFlag.AlignCenter),
                coluna_data("Vencimento", lambda item: item.vencimento),
                coluna_moeda("Valor", lambda item: item.valor),
                Coluna("Status", lambda item: item.status.rotulo),
                Coluna(
                    "Juros/dia",
                    lambda item: str(item.juros_dia) if item.juros_dia is not None else "—",
                ),
                Coluna("Cobranças", lambda item: str(len(item.cobrancas)),
                       alinhamento=Qt.AlignmentFlag.AlignCenter),
                Coluna(
                    "Situação",
                    lambda item: (
                        "ERRO: " + "; ".join(p.motivo for p in item.problemas if p.bloqueia)
                        if item.bloqueada
                        else (
                            "Avisos: " + str(len(item.problemas))
                            if item.problemas
                            else "Pronta"
                        )
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
        self.abas.addTab(self.tabela_linhas, "Honorários")

        self.modelo_clientes = ModeloTabela(
            [
                Coluna("Código", lambda c: c.codigo, alinhamento=Qt.AlignmentFlag.AlignCenter),
                Coluna("Nome", lambda c: c.nome),
                Coluna("CPF/CNPJ", lambda c: c.documento or "—"),
                Coluna("Tipo", lambda c: c.tipo_pessoa.value,
                       alinhamento=Qt.AlignmentFlag.AlignCenter),
                Coluna("Juros/dia", lambda c: str(c.juros_dia) if c.juros_dia is not None else "—"),
                Coluna("Origem", lambda c: c.origem),
            ]
        )
        self.tabela_clientes = preparar_tabela(QTableView(), esticar=1)
        self.tabela_clientes.setModel(self.modelo_clientes)
        self.abas.addTab(self.tabela_clientes, "Clientes")

        self.modelo_problemas = ModeloTabela(
            [
                Coluna("Gravidade", lambda p: p.gravidade,
                       cor=lambda p: tema.cor("atrasado") if p.bloqueia else tema.cor("atencao"),
                       alinhamento=Qt.AlignmentFlag.AlignCenter),
                Coluna("Aba", lambda p: p.aba),
                Coluna("Linha", lambda p: str(p.linha or "—"),
                       alinhamento=Qt.AlignmentFlag.AlignCenter),
                Coluna("Campo", lambda p: p.campo),
                Coluna("Valor lido", lambda p: p.valor),
                Coluna("O que o sistema fez", lambda p: p.motivo),
            ]
        )
        self.tabela_problemas = preparar_tabela(QTableView(), esticar=5)
        self.tabela_problemas.setModel(self.modelo_problemas)
        self.abas.addTab(self.tabela_problemas, "Relatório de erros e ajustes")
        layout.addWidget(self.abas, 1)

        self.resumo = widgets.rotulo_fraco(
            "Escolha a planilha para ver a prévia. Nada é gravado antes de você confirmar."
        )
        layout.addWidget(self.resumo)

    # ------------------------------------------------------------------ ações
    def _escolher(self) -> None:
        caminho, _ = QFileDialog.getOpenFileName(
            self, "Escolher a planilha", str(Path.home()), "Planilha do Excel (*.xlsx *.xlsm)"
        )
        if not caminho:
            return
        self.caminho.setText(caminho)

        def acao():
            return leitor.ler(caminho)

        deu_certo, leitura = widgets.executar(self, acao)
        if not deu_certo:
            return
        self.leitura = leitura
        self.modelo_linhas.definir_itens(leitura.linhas)
        self.modelo_clientes.definir_itens(list(leitura.clientes.values()))
        self.modelo_problemas.definir_itens(leitura.todos_problemas())
        for tabela, modelo in (
            (self.tabela_linhas, self.modelo_linhas),
            (self.tabela_clientes, self.modelo_clientes),
            (self.tabela_problemas, self.modelo_problemas),
        ):
            ajustar_colunas(tabela, modelo.colunas)
        self.resumo.setText(leitura.resumo())

    def _importar(self) -> None:
        if self.leitura is None:
            widgets.aviso(self, "Escolha a planilha primeiro.")
            return
        marcadas = [linha for linha in self.modelo_linhas.marcados() if not linha.bloqueada]
        if not marcadas:
            widgets.aviso(self, "Nenhuma linha marcada para importar.")
            return
        total = sum((linha.valor for linha in marcadas), start=ZERO)
        cobrancas = sum(len(linha.cobrancas) for linha in marcadas)
        if not widgets.confirmar(
            self,
            f"Importar {len(marcadas)} honorário(s)?",
            "Confirmar importação",
            f"{len(self.leitura.clientes)} cliente(s) na planilha · "
            f"total {formatar_moeda(total)} · {cobrancas} cobrança(s). "
            "Faça um backup antes se o banco já tiver dados.",
        ):
            return

        for linha in self.leitura.linhas:
            linha.importar = linha in marcadas

        def acao():
            resultado = executor.importar(
                self.contexto.sessao,
                self.leitura,
                criar_clientes=self.criar_clientes.isChecked(),
                importar_pagos=self.importar_pagos.isChecked(),
                importar_cobrancas=self.importar_cobrancas.isChecked(),
            )
            self.contexto.salvar()
            return resultado

        deu_certo, resultado = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.resumo.setText(resultado.resumo)
        widgets.informar(self, resultado.resumo, "Importação concluída")
