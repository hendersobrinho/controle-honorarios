"""Exportação a partir das telas: escolhe o arquivo e avisa onde salvou."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog

from ...config.caminhos import pasta_exportacoes
from ...servicos import configuracoes, exportacao
from ...servicos import ficha as servico_ficha
from ..comum import widgets
from ..contexto import Contexto


def exportar_linhas(parent, contexto: Contexto, linhas, titulo: str = "Honorários") -> None:
    if not linhas:
        widgets.aviso(parent, "Não há nada na lista para exportar.")
        return
    sugestao = str(pasta_exportacoes() / "honorarios.xlsx")
    caminho, _ = QFileDialog.getSaveFileName(
        parent, "Exportar para Excel", sugestao, "Planilha do Excel (*.xlsx)"
    )
    if not caminho:
        return

    def acao():
        return exportacao.para_excel(linhas, Path(caminho), titulo)

    deu_certo, arquivo = widgets.executar(parent, acao)
    if deu_certo:
        widgets.informar(parent, f"Planilha salva em:\n{arquivo}", "Exportação concluída")


def exportar_extrato(parent, contexto: Contexto, cliente) -> None:
    dados = servico_ficha.extrato(contexto.sessao, cliente, contexto.data_referencia)
    if not dados["linhas"]:
        widgets.aviso(parent, f"{cliente.nome} não tem débito em aberto.")
        return
    sugestao = str(pasta_exportacoes() / f"extrato-{cliente.codigo}.pdf")
    caminho, _ = QFileDialog.getSaveFileName(
        parent, "Extrato de débitos em PDF", sugestao, "PDF (*.pdf)"
    )
    if not caminho:
        return

    def acao():
        return exportacao.extrato_pdf(
            cliente,
            dados["linhas"],
            configuracoes.recebedor(contexto.sessao),
            Path(caminho),
            contexto.data_referencia,
        )

    deu_certo, arquivo = widgets.executar(parent, acao)
    if deu_certo:
        widgets.informar(parent, f"Extrato salvo em:\n{arquivo}", "Extrato gerado")
        widgets.abrir_url(f"file://{arquivo}")
