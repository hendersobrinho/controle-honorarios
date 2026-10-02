"""Imagem de cobrança: dados da seleção, Pix e o fundo SVG."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from honorarios.dominio.enums import TipoPessoa
from honorarios.dominio.valores import Competencia
from honorarios.servicos import cobrancas
from honorarios.servicos import imagem_cobranca as servico
from honorarios.servicos.erros import ErroDeValidacao
from testes import fabricas

REFERENCIA = date(2026, 9, 30)


@pytest.fixture
def empresa(sessao):
    cliente = fabricas.cliente(sessao, codigo="800", nome="EMPRESA & FILHOS LTDA", juros_dia="1.00")
    cliente.juros[0].vigencia_inicio = date(2020, 1, 1)
    sessao.commit()
    fabricas.honorario(sessao, cliente, valor="1000.00", vencimento=date(2026, 9, 10),
                       competencia=Competencia(2026, 8))
    fabricas.honorario(sessao, cliente, valor="500.00", vencimento=date(2026, 10, 10),
                       competencia=Competencia(2026, 9))
    sessao.commit()
    return cliente


def png_de_qrcode(destino):
    """Um PNG pequeno no lugar do QR baixado do banco (o conteúdo não importa aqui)."""
    from PIL import Image

    imagem = Image.new("1", (29, 29), 1)
    for x in range(29):
        for y in range(29):
            if (x // 3 + y // 3) % 2:
                imagem.putpixel((x, y), 0)
    imagem.save(destino)
    return destino


def _selecao(sessao, cliente, quais=None):
    linhas = cobrancas.linhas_em_aberto_do_cliente(sessao, cliente.id, REFERENCIA)
    if quais is not None:
        linhas = [linhas[i] for i in quais]
    return cobrancas.Selecao(cliente=cliente, linhas=linhas, data_referencia=REFERENCIA)


def test_a_imagem_segue_a_selecao(sessao, empresa):
    todos = servico.montar(sessao, _selecao(sessao, empresa))
    assert len(todos.linhas) == 2
    assert todos.campos["quantidade"] == "2 honorários"
    assert todos.campos["total"] == "R$ 1.520,00"            # 1000 + 20 dias × 1,00 + 500
    assert todos.campos["total_juros"] == "R$ 20,00"

    um = servico.montar(sessao, _selecao(sessao, empresa, [0]))
    assert len(um.linhas) == 1
    assert um.campos["quantidade"] == "1 honorário"
    linha = um.linhas[0]
    assert linha.titulo == "Honorário mensal · 08/2026"
    assert linha.detalhe == "Vencimento 10/09/2026 · 20 dias de atraso"
    # só o valor final cheio, sem o juros separado
    assert (linha.valor, linha.valor_detalhe) == ("R$ 1.020,00", "")

    with pytest.raises(ErroDeValidacao, match="Marque ao menos um"):
        servico.montar(sessao, _selecao(sessao, empresa, []))


def test_qr_code_e_o_png_escolhido(sessao, empresa, pasta_dados, tmp_path):
    assert servico.montar(sessao, _selecao(sessao, empresa)).qrcode is None

    origem = png_de_qrcode(tmp_path / "qr-do-banco.png")
    servico.definir_qrcode(sessao, origem)
    origem.unlink()                       # o sistema guarda uma cópia
    dados = servico.montar(sessao, _selecao(sessao, empresa, [0]))
    assert dados.qrcode == pasta_dados / servico.NOME_QRCODE
    assert dados.qrcode.is_file()

    servico.remover_qrcode(sessao)
    assert servico.montar(sessao, _selecao(sessao, empresa)).qrcode is None


def test_qr_code_precisa_ser_png(sessao, tmp_path):
    falso = tmp_path / "qr.png"
    falso.write_text("não é imagem")
    with pytest.raises(ErroDeValidacao, match="não é uma imagem PNG"):
        servico.definir_qrcode(sessao, falso)
    assert servico.caminho_qrcode(sessao) is None


def test_honorario_de_pessoa_vinculada_diz_de_quem_e(sessao, empresa):
    pessoa = fabricas.cliente(sessao, codigo="801", nome="SOCIO EXEMPLO",
                              documento=fabricas.CPF_FICTICIO, tipo=TipoPessoa.PF)
    pessoa.empresa_id = empresa.id
    fabricas.honorario(sessao, pessoa, valor="300.00", vencimento=date(2026, 9, 20),
                       competencia=Competencia(2026, 8))
    linhas = cobrancas.linhas_em_aberto_do_cliente(
        sessao, empresa.id, REFERENCIA, incluir_vinculados=True
    )
    dados = servico.montar(
        sessao, cobrancas.Selecao(cliente=empresa, linhas=linhas, data_referencia=REFERENCIA)
    )
    assert any(linha.titulo.startswith("SOCIO EXEMPLO: ") for linha in dados.linhas)


def test_preencher_troca_os_campos_e_escapa_o_xml():
    svg = "<text>{cliente} deve {total} {desconhecido}</text>"
    resultado = servico.preencher(svg, {"cliente": "A & B", "total": "R$ 1,00"})
    assert resultado == "<text>A &amp; B deve R$ 1,00 {desconhecido}</text>"


def test_validar_svg_avisa_o_que_falta():
    completo = servico.FUNDO_MODELO.read_text(encoding="utf-8")
    assert servico.validar_svg(completo) == []

    sem_areas = (
        '<svg xmlns="http://www.w3.org/2000/svg"><!-- use {campo} -->'
        "<text>{nome}</text></svg>"
    )
    avisos = servico.validar_svg(sem_areas)
    assert any('id="lista"' in aviso for aviso in avisos)
    assert any('id="qrcode"' in aviso for aviso in avisos)
    assert any("{nome}" in aviso for aviso in avisos)
    assert not any("{campo}" in aviso for aviso in avisos)   # comentário não conta

    with pytest.raises(ErroDeValidacao, match="não é um SVG válido"):
        servico.validar_svg("isto não é svg")


def test_fundo_escolhido_e_copiado_para_a_pasta_de_dados(sessao, pasta_dados, tmp_path):
    assert servico.usa_modelo(sessao)
    origem = tmp_path / "meu_fundo.svg"
    origem.write_text(servico.FUNDO_MODELO.read_text(encoding="utf-8"), encoding="utf-8")

    assert servico.definir_fundo(sessao, origem) == []
    origem.unlink()                       # o original pode sumir: o sistema tem a cópia
    caminho = servico.caminho_fundo(sessao)
    assert caminho == pasta_dados / servico.NOME_FUNDO
    assert caminho.is_file()
    assert not servico.usa_modelo(sessao)

    servico.usar_modelo(sessao)
    assert servico.caminho_fundo(sessao) == servico.FUNDO_MODELO


def test_exemplo_para_a_previa(sessao, tmp_path):
    dados = servico.exemplo(sessao)
    assert len(dados.linhas) == 3
    assert dados.qrcode is None
    servico.definir_qrcode(sessao, png_de_qrcode(tmp_path / "qr.png"))
    assert servico.exemplo(sessao).qrcode is not None


def test_base_do_fundo_tira_so_o_grupo_conteudo():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<rect id="papel" width="10" height="10"/>'
        '<g id="conteudo"><text>{cliente}</text><rect id="lista"/></g></svg>'
    )
    base = servico.base_do_fundo(svg)
    assert 'id="papel"' in base
    assert "conteudo" not in base and "{cliente}" not in base and 'id="lista"' not in base
    assert not base.startswith("<ns0:")            # SVG continua no namespace padrão

    # sem o grupo, não há como separar o desenho da camada da cobrança
    assert servico.base_do_fundo('<svg xmlns="http://www.w3.org/2000/svg"/>') is None
    # o modelo do sistema já vem com o grupo
    assert servico.base_do_fundo(servico.FUNDO_MODELO.read_text(encoding="utf-8"))


def test_imagem_traz_o_documento_e_o_vencimento_editavel(sessao, empresa):
    selecao = _selecao(sessao, empresa, [0])
    hoje_ = servico.montar(sessao, selecao)
    assert hoje_.campos["tipo_documento"] == "CNPJ"
    assert hoje_.campos["documento"] == "11.222.333/0001-81"
    assert hoje_.campos["vencimento"] == "30/09/2026"
    assert hoje_.campos["total"] == "R$ 1.020,00"

    # "pagar até" é só o prazo: o valor continua o da data de atualização
    oferta = servico.montar(sessao, selecao, vencimento=date(2026, 10, 10))
    assert oferta.campos["vencimento"] == "10/10/2026"
    assert oferta.campos["data"] == "30/09/2026"
    assert oferta.campos["total"] == "R$ 1.020,00"

    # atualizar os valores para outra data muda o juros (10 dias a mais)
    adiante = servico.montar(sessao, selecao, date(2026, 10, 10), date(2026, 10, 10))
    assert adiante.campos["total"] == "R$ 1.030,00"
    assert adiante.linhas[0].detalhe.endswith("30 dias de atraso")

    with pytest.raises(ErroDeValidacao, match="não pode ser antes"):
        servico.montar(sessao, selecao, date(2026, 9, 25), date(2026, 9, 30))


def test_acordo_vale_ate_a_data_e_depois_o_juros_volta(sessao, empresa):
    from honorarios.servicos import acordos, pagamentos

    honorario = _selecao(sessao, empresa, [0]).linhas[0].honorario
    # vencido em 10/09 a R$ 1,00/dia: valores de 20/09 (10 dias), válidos até 25/09
    [acordo] = acordos.registrar(sessao, [honorario], date(2026, 9, 20), date(2026, 9, 25))
    sessao.commit()
    assert (acordo.juros, acordo.total) == (Decimal("10.00"), Decimal("1010.00"))

    # pagando dentro do prazo, a baixa sugere o valor do acordo
    dentro = pagamentos.previa(honorario, date(2026, 9, 24))
    assert dentro.juros_devidos == Decimal("14.00")      # o juros real continua correndo
    assert dentro.juros_acordo == Decimal("10.00")
    assert dentro.sugestao_valor == Decimal("1010.00")
    assert "acordo" in dentro.justificativa_acordo

    # passou do prazo: o acordo não vale, e o juros é o desde o vencimento original
    fora = pagamentos.previa(honorario, date(2026, 9, 26))
    assert fora.juros_acordo is None
    assert fora.sugestao_valor == Decimal("1016.00")
    assert acordos.vigente(honorario, date(2026, 9, 26)) is None

    # a baixa dentro do prazo, com o abono justificado pelo acordo
    pagamentos.registrar(sessao, honorario, pagamentos.DadosPagamento(
        data=date(2026, 9, 24), valor_pago=dentro.sugestao_valor,
        juros_cobrados=dentro.juros_acordo, justificativa_desconto=dentro.justificativa_acordo,
    ))
    sessao.commit()
    assert honorario.status.value == "PAGO"


def test_acordo_nao_vence_antes_dos_valores(sessao, empresa):
    from honorarios.servicos import acordos

    honorario = _selecao(sessao, empresa, [0]).linhas[0].honorario
    with pytest.raises(ErroDeValidacao, match="não pode vencer antes"):
        acordos.registrar(sessao, [honorario], date(2026, 9, 30), date(2026, 9, 20))


def test_sem_qrcode_tira_a_mensagem_e_move_o_pix():
    from honorarios.servicos import imagem_cobranca

    fundo = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<rect id="qrcode" width="2" height="2"/>'
        '<g id="bloco-pix" data-sem-qrcode="translate(-5 2)" transform="scale(1)">'
        '<text>Pague com Pix</text>'
        '<g id="mensagem-qrcode"><text>Aponte a câmera</text></g>'
        '</g></svg>'
    )
    sem = imagem_cobranca.sem_qrcode(fundo)
    assert "Aponte a câmera" not in sem and "Pague com Pix" in sem
    assert 'transform="translate(-5 2) scale(1)"' in sem
    assert "data-sem-qrcode" not in sem
    # fundo sem as marcações: fica como está
    assert imagem_cobranca.sem_qrcode("<svg/>") == "<svg/>"


def test_modelo_mostra_a_mensagem_do_qr_so_com_qr(tmp_path, monkeypatch):
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    from honorarios.servicos import imagem_cobranca
    from honorarios.ui.comum import imagem_cobranca as desenho

    QApplication.instance() or QApplication([])
    vistos = []
    original = desenho.preencher
    monkeypatch.setattr(desenho, "preencher",
                        lambda texto_svg, campos: vistos.append(texto_svg) or
                        original(texto_svg, campos))
    fundo = imagem_cobranca.FUNDO_MODELO.read_text(encoding="utf-8")
    dados = imagem_cobranca.DadosImagem(campos={}, linhas=[])
    desenho.renderizar(fundo, dados)                      # sem QR
    qr = tmp_path / "qr.png"
    QImage(10, 10, QImage.Format.Format_ARGB32).save(str(qr))
    dados.qrcode = qr
    desenho.renderizar(fundo, dados)                      # com QR
    assert "Aponte a câmera" not in vistos[0]
    assert "Aponte a câmera" in vistos[1]
