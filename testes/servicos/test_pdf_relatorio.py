"""O papel dos PDFs (o canhoto) e a marca desenhada em vetor."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from honorarios.servicos import svg_pdf
from honorarios.servicos.pdf_relatorio import MARCA, RelatorioPdf


def test_marca_vira_caminhos_do_pdf(tmp_path):
    from reportlab.pdfgen.canvas import Canvas

    assert round(svg_pdf.proporcao(MARCA), 2) == round(293.16 / 96, 2)
    canvas = Canvas(str(tmp_path / "marca.pdf"))
    largura = svg_pdf.desenhar(canvas, MARCA, 10, 10, 40)
    canvas.save()
    assert round(largura, 1) == round(40 * 293.16 / 96, 1)


def test_arco_de_um_quarto_termina_no_ponto_certo():
    # canto arredondado do canhoto: de (160,64) a (128,96) com raio 32
    curvas = svg_pdf._arco(160, 64, 32, 32, 0, 0, 0, 128, 96)
    assert len(curvas) == 1
    assert curvas[-1][4:] == pytest.approx((128, 96))


def test_relatorio_quebra_pagina_e_repete_o_papel(tmp_path, monkeypatch):
    from reportlab import rl_config

    monkeypatch.setattr(rl_config, "pageCompression", 0)
    recebedor = SimpleNamespace(razao_social="Escritório de Teste")
    r = RelatorioPdf("Relatório", "Um subtítulo bem comprido " * 6, recebedor,
                     date(2026, 10, 27))
    corpo = [r.p(f"Linha {numero}") for numero in range(200)]
    arquivo = r.salvar(corpo, tmp_path / "longo.pdf", "Relatório")
    conteudo = arquivo.read_bytes()
    assert b"gina 2" in conteudo                 # o rodapé em todas as páginas
    assert conteudo.count(b"/Shading") >= 1
