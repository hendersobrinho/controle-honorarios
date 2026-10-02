"""Painel: o ano em números (emitido, quitado, caixa, origem) e as leituras."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from honorarios.dominio.enums import TipoPessoa
from honorarios.dominio.valores import Competencia
from honorarios.servicos import pagamentos, relatorios
from testes import fabricas

REFERENCIA = date(2026, 9, 30)


def _pagar(sessao, honorario, data, valor=None):
    previa = pagamentos.previa(honorario, data)
    pagamentos.registrar(
        sessao, honorario,
        pagamentos.DadosPagamento(
            data=data,
            valor_pago=valor if valor is not None else previa.total_devido,
            juros_cobrados=previa.juros_devidos,
        ),
    )
    sessao.commit()


@pytest.fixture
def ano(sessao):
    empresa = fabricas.cliente(sessao, codigo="10", nome="EMPRESA LTDA", juros_dia="0.00")
    pessoa = fabricas.cliente(sessao, codigo="11", nome="PESSOA", documento=fabricas.CPF_FICTICIO,
                              tipo=TipoPessoa.PF, juros_dia="0.00")
    # janeiro: 1000 pago em dia; fevereiro: 1000 pago pela metade; março: 500 em aberto
    jan = fabricas.honorario(sessao, empresa, valor="1000.00", vencimento=date(2026, 2, 5),
                             competencia=Competencia(2026, 1))
    fev = fabricas.honorario(sessao, empresa, valor="1000.00", vencimento=date(2026, 3, 5),
                             competencia=Competencia(2026, 2))
    fabricas.honorario(sessao, pessoa, valor="500.00", vencimento=date(2026, 4, 5),
                       competencia=Competencia(2026, 3), tipo=fabricas.tipo_irpf(sessao))
    _pagar(sessao, jan, date(2026, 2, 5))
    _pagar(sessao, fev, date(2026, 3, 5), Decimal("400.00"))
    return empresa, pessoa


def test_emitido_quitado_e_em_aberto_por_competencia(sessao, ano):
    dados = relatorios.indicadores(sessao, 2026, REFERENCIA)
    assert dados.emitido == Decimal("2500.00")
    assert dados.quitado == Decimal("1400.00")       # 1000 + 400 do parcial
    assert dados.em_aberto == Decimal("1100.00")     # 600 do parcial + 500
    assert dados.quantidade_emitida == 3
    assert dados.quantidade_em_aberto == 2
    assert dados.clientes_faturados == 2
    assert dados.ticket_medio == Decimal("833.33")
    assert round(dados.percentual_quitado) == 56

    jan, fev, mar = dados.meses[:3]
    assert (jan.quitado, jan.em_aberto) == (Decimal("1000.00"), Decimal("0.00"))
    assert (fev.quitado, fev.em_aberto) == (Decimal("400.00"), Decimal("600.00"))
    assert (mar.quitado, mar.em_aberto) == (Decimal("0.00"), Decimal("500.00"))
    assert dados.emitido == sum((mes.emitido for mes in dados.meses), start=Decimal(0))


def test_caixa_pela_data_da_baixa(sessao, ano):
    dados = relatorios.indicadores(sessao, 2026, REFERENCIA)
    assert dados.meses[1].recebido == Decimal("1000.00")   # baixa em fevereiro
    assert dados.meses[2].recebido == Decimal("400.00")    # parcial em março
    assert dados.recebido_no_caixa == Decimal("1400.00")


def test_origem_do_faturamento(sessao, ano):
    dados = relatorios.indicadores(sessao, 2026, REFERENCIA)
    assert dados.por_grupo == [("Mensais", Decimal("2000.00")),
                               ("Imposto de Renda", Decimal("500.00"))]
    assert dados.por_tipo_pessoa == [("Pessoa jurídica", Decimal("2000.00")),
                                     ("Pessoa física", Decimal("500.00"))]


def test_leituras_sem_atraso_e_sem_comparacao_sem_base(sessao, ano):
    leituras = relatorios.indicadores(sessao, 2026, REFERENCIA).leituras()
    texto = " ".join(leituras)
    assert "foram emitidos R$ 2.500,00 em 3 honorários, para 2 cliente(s)" in texto
    assert "56% do que foi emitido já está quitado" in texto
    assert "O grupo Mensais responde por 80% do faturamento" in texto
    assert "Ainda não há dados suficientes de 2025" in texto
    assert "atraso" not in texto.lower()


def test_compara_com_o_ano_anterior_so_com_base(sessao, ano):
    empresa, _ = ano
    # um honorário solto em 2025 não basta para comparar
    fabricas.honorario(sessao, empresa, valor="100.00", vencimento=date(2025, 2, 5),
                       competencia=Competencia(2025, 1))
    assert relatorios.indicadores(sessao, 2026, REFERENCIA).emitido_anterior is None
    # com dado em pelo menos metade dos meses do período (até setembro: 4 meses)
    for mes in (2, 3, 4):
        fabricas.honorario(sessao, empresa, valor="100.00", vencimento=date(2025, mes + 1, 5),
                           competencia=Competencia(2025, mes))
    dados = relatorios.indicadores(sessao, 2026, REFERENCIA)
    assert dados.emitido_anterior == Decimal("400.00")
    assert any("a mais que no mesmo período de 2025" in frase for frase in dados.leituras())


def test_pdf_do_painel(sessao, ano, tmp_path, monkeypatch):
    from PIL import Image
    from reportlab import rl_config

    from honorarios.servicos import configuracoes, relatorio_painel

    monkeypatch.setattr(rl_config, "pageCompression", 0)
    graficos = {}
    # cores diferentes: imagens iguais o reportlab guarda uma vez só
    for chave, cor in (("quitacao", "#2a78d6"), ("caixa", "#eb6834"), ("origem", "#1baf7a")):
        graficos[chave] = tmp_path / f"{chave}.png"
        Image.new("RGB", (900, 300), cor).save(graficos[chave])

    dados = relatorios.indicadores(sessao, 2026, REFERENCIA)
    arquivo = relatorio_painel.painel_pdf(
        dados, configuracoes.recebedor(sessao), tmp_path / "painel.pdf", graficos=graficos,
        gerado_em=REFERENCIA,
    )
    conteudo = arquivo.read_bytes()
    assert conteudo.startswith(b"%PDF")
    assert conteudo.count(b"/Subtype /Image") == 3          # os três gráficos
    for trecho in (b"Painel 2026", b"O que os n", b"Entrou no caixa por m", b"Total"):
        assert trecho in conteudo, trecho
    assert b"atraso h" not in conteudo                       # nada de atraso no painel


def test_honorarios_do_mes_pela_competencia_ou_vencimento(sessao, ano):
    from honorarios.servicos import honorarios as servico_honorarios

    empresa, pessoa = ano
    # IR tem competência só de ano: conta no mês do vencimento (abril)
    fabricas.honorario(sessao, pessoa, valor="300.00", vencimento=date(2026, 4, 30),
                       competencia=Competencia(2026), tipo=fabricas.tipo_irpf(sessao))
    janeiro = servico_honorarios.do_mes(sessao, 2026, 1, REFERENCIA)
    assert [linha.honorario.valor_original for linha in janeiro] == [Decimal("1000.00")]
    # a competência 02/2026 vence em março, mas conta em fevereiro
    assert len(servico_honorarios.do_mes(sessao, 2026, 2, REFERENCIA)) == 1
    abril = servico_honorarios.do_mes(sessao, 2026, 4, REFERENCIA)
    assert [linha.honorario.valor_original for linha in abril] == [Decimal("300.00")]
    meses = servico_honorarios.meses_com_lancamento(sessao)
    assert meses[0] == (2026, 4) and (2026, 1) in meses
