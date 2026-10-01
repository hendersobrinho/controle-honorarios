"""Análise de juros: o valor original contra o que de fato foi pago."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

import pytest

from honorarios.dominio.enums import StatusPagamento
from honorarios.dominio.valores import Competencia
from honorarios.servicos import analise_juros, cobrancas, pagamentos
from testes import fabricas

REFERENCIA = date(2026, 9, 30)


def _pagar(sessao, honorario, data, juros_cobrados=None, justificativa=""):
    previa = pagamentos.previa(honorario, data)
    cobrado = previa.juros_devidos if juros_cobrados is None else Decimal(juros_cobrados)
    pagamentos.registrar(
        sessao,
        honorario,
        pagamentos.DadosPagamento(
            data=data,
            valor_pago=previa.saldo + cobrado,
            juros_cobrados=cobrado,
            justificativa_desconto=justificativa,
        ),
    )
    sessao.commit()
    return previa


@pytest.fixture
def carteira(sessao):
    """Dois clientes a R$ 1,00 e R$ 0,50 ao dia; pagamentos em dia, atrasado e com abono."""
    cara = fabricas.cliente(sessao, codigo="20", nome="PAGA COM JUROS LTDA", juros_dia="1.00")
    leve = fabricas.cliente(
        sessao, codigo="21", nome="PAGA EM DIA LTDA", documento="", juros_dia="0.50"
    )
    for cliente in (cara, leve):
        cliente.juros[0].vigencia_inicio = date(2020, 1, 1)
    sessao.commit()

    # 1000 vencido em 01/08, pago em 31/08: 30 dias × R$ 1,00 = R$ 30,00 de juros
    atrasado = fabricas.honorario(
        sessao, cara, valor="1000.00", vencimento=date(2026, 8, 1),
        competencia=Competencia(2026, 7),
    )
    _pagar(sessao, atrasado, date(2026, 8, 31))
    # 500 vencido em 01/09, pago em 11/09: devia R$ 10,00, pagou R$ 4,00 (abono de 6)
    abonado = fabricas.honorario(
        sessao, cara, valor="500.00", vencimento=date(2026, 9, 1),
        competencia=Competencia(2026, 8),
    )
    _pagar(sessao, abonado, date(2026, 9, 11), "4.00", "Cliente antigo")
    # 800 pago no vencimento: sem juros
    em_dia = fabricas.honorario(
        sessao, leve, valor="800.00", vencimento=date(2026, 9, 10),
        competencia=Competencia(2026, 8),
    )
    _pagar(sessao, em_dia, date(2026, 9, 10))
    return cara, leve


def test_compara_original_com_o_recebido(sessao, carteira):
    analise = analise_juros.analisar(sessao, referencia=REFERENCIA)

    assert len(analise.honorarios) == 3
    assert len(analise.atrasados) == 2
    assert analise.original == Decimal("2300.00")
    assert analise.juros_devidos == Decimal("40.00")
    assert analise.juros_cobrados == Decimal("34.00")
    assert analise.abono == Decimal("6.00")
    assert analise.recebido == Decimal("2334.00")
    assert analise.percentual_abonado == Decimal("15")
    # 34 de juros sobre 1500 pagos com atraso
    assert round(analise.acrescimo_sobre_atrasados, 2) == Decimal("2.27")


def test_taxa_efetiva_mensal_desconta_o_abono(sessao, carteira):
    analise = analise_juros.analisar(sessao, referencia=REFERENCIA)
    # base = 1000 × 30/30 + 500 × 10/30 = 1166,67
    assert round(analise.taxa_mensal_cadastrada, 2) == Decimal("3.43")   # 40 / 1166,67
    assert round(analise.taxa_mensal_efetiva, 2) == Decimal("2.91")      # 34 / 1166,67
    assert analise.taxa_mensal_efetiva < analise.taxa_mensal_cadastrada


def test_pago_importado_sem_pagamento_fica_de_fora(sessao, carteira):
    cara, _ = carteira
    importado = fabricas.honorario(
        sessao, cara, valor="999.00", vencimento=date(2026, 6, 1),
        competencia=Competencia(2026, 5),
    )
    importado.status = StatusPagamento.PAGO
    importado.pago_em = date(2026, 6, 1)
    sessao.commit()

    analise = analise_juros.analisar(sessao, referencia=REFERENCIA)
    assert importado.id not in [item.honorario.id for item in analise.honorarios]


def test_periodo_filtra_pela_data_de_pagamento(sessao, carteira):
    analise = analise_juros.analisar(sessao, desde=date(2026, 9, 1), referencia=REFERENCIA)
    assert analise.original == Decimal("1300.00")
    assert [m.rotulo for m in analise.meses] == ["Set/26"]

    tudo = analise_juros.analisar(sessao, referencia=REFERENCIA)
    assert [m.rotulo for m in tudo.meses] == ["Ago/26", "Set/26"]
    agosto = tudo.meses[0]
    assert (agosto.original, agosto.juros) == (Decimal("1000.00"), Decimal("30.00"))
    assert agosto.percentual == Decimal("3")


def test_simulacao_so_vale_daqui_para_frente(sessao, carteira):
    cara, _ = carteira
    # um honorário ainda atrasado hoje: rende R$ 1,00 por dia
    fabricas.honorario(
        sessao, cara, valor="300.00", vencimento=date(2026, 9, 20),
        competencia=Competencia(2026, 9),
    )
    analise = analise_juros.analisar(sessao, referencia=REFERENCIA)
    assert analise.juros_por_dia_hoje == Decimal("1.00")

    resultado = analise.simular(Decimal(50))
    assert resultado["no_periodo"] == Decimal("17.00")        # 50% de 34
    assert resultado["por_mes"] == Decimal("8.50")            # dois meses no período
    assert resultado["carteira_por_mes"] == Decimal("15.00")  # 1,00 × 30 × 50%


def test_rankings_de_juros(sessao, carteira):
    cara, _ = carteira
    analise = analise_juros.analisar(sessao, referencia=REFERENCIA)

    # quem pagou em dia não aparece: não pagou juros
    assert [i.cliente.id for i in analise.ranking_juros.itens] == [cara.id]
    assert analise.ranking_juros.itens[0].rotulo == "R$ 34,00"
    assert "100%" in analise.ranking_juros.curiosidade
    assert analise.ranking_acrescimo.itens[0].rotulo == "+2,27%"
    assert "R$ 1.500,00 → R$ 1.534,00" == analise.ranking_acrescimo.itens[0].detalhe


def test_leituras_avisam_quando_o_abono_pesa(sessao, carteira):
    leituras = analise_juros.analisar(sessao, referencia=REFERENCIA).leituras()
    texto = " ".join(leituras)
    assert "2 de 3 honorários (67%) foram pagos com atraso" in texto
    assert "De cada R$ 100 pagos com atraso, entraram R$ 2,27 de juros" in texto
    assert "(15% do que era devido)" in texto
    assert "Antes de aumentar a taxa" not in texto      # abono abaixo de 25%


def test_leituras_sugerem_olhar_os_abonos_antes_de_aumentar(sessao):
    cliente = fabricas.cliente(sessao, codigo="30", nome="SEMPRE ABONADO", juros_dia="1.00")
    cliente.juros[0].vigencia_inicio = date(2020, 1, 1)
    sessao.commit()
    honorario = fabricas.honorario(
        sessao, cliente, valor="1000.00", vencimento=date(2026, 8, 1),
        competencia=Competencia(2026, 7),
    )
    _pagar(sessao, honorario, date(2026, 8, 31), "0.00", "Perdoado")

    analise = analise_juros.analisar(sessao, referencia=REFERENCIA)
    assert analise.percentual_abonado == Decimal("100")
    assert any("Antes de aumentar a taxa" in frase for frase in analise.leituras())


def test_sem_pagamentos_nao_quebra(sessao):
    analise = analise_juros.analisar(sessao, referencia=REFERENCIA)
    assert analise.honorarios == []
    assert analise.leituras() == []
    assert analise.taxa_mensal_efetiva is None
    assert analise.ranking_juros.itens == []
    assert analise.simular(Decimal(10))["no_periodo"] == Decimal("0.00")


# ----------------------------------------------------------------- por cliente


def test_analise_de_um_cliente(sessao, carteira):
    cara, leve = carteira
    geral = analise_juros.analisar(sessao, referencia=REFERENCIA)
    assert {a.cliente.id for a in geral.clientes()} == {cara.id, leve.id}

    dele = geral.do_cliente(cara.id)
    assert dele.cliente.id == cara.id
    assert dele.taxa_atual == Decimal("1.00")
    assert dele.original == Decimal("1500.00")
    assert dele.juros_cobrados == Decimal("34.00")
    assert dele.maior_atraso == 30
    # mais recente primeiro, para a lista "honorário por honorário"
    assert [item.pago_em for item in dele.honorarios] == [date(2026, 9, 11), date(2026, 8, 31)]
    assert geral.do_cliente(99999) is None


def test_cenarios_do_cliente_trazem_a_taxa_nova(sessao, carteira):
    cara, _ = carteira
    dele = analise_juros.analisar(sessao, referencia=REFERENCIA).do_cliente(cara.id)
    cenarios = analise_juros.cenarios(dele)
    rotulos = [c.rotulo for c in cenarios]
    assert rotulos == [
        "Como está hoje", "Mesma taxa, sem abono", "+10%", "+25%", "+50%", "Dobrar",
    ]
    sem_abono = cenarios[1]
    assert (sem_abono.juros_no_periodo, sem_abono.a_mais) == (Decimal("40.00"), Decimal("6.00"))
    dobrar = cenarios[-1]
    assert dobrar.taxa_dia == Decimal("2.00")
    assert dobrar.a_mais == Decimal("34.00")

    reduzir = analise_juros.cenario(dele, Decimal(-50))
    assert reduzir.rotulo == "-50%"
    assert reduzir.taxa_dia == Decimal("0.50")
    assert reduzir.a_mais == Decimal("-17.00")


def test_sem_abono_o_cenario_de_abono_nao_aparece(sessao, carteira):
    _, leve = carteira
    dele = analise_juros.analisar(sessao, referencia=REFERENCIA).do_cliente(leve.id)
    assert "Mesma taxa, sem abono" not in [c.rotulo for c in analise_juros.cenarios(dele)]


def test_explicacao_do_cliente(sessao, carteira):
    cara, leve = carteira
    geral = analise_juros.analisar(sessao, referencia=REFERENCIA)

    texto = "\n".join(analise_juros.explicar_cliente(geral.do_cliente(cara.id)))
    assert "Pagou 2 honorários no período: R$ 1.500,00 de valor original viraram" in texto
    assert (
        "Pagou todos com atraso: 40 dias de atraso somados, em média 20 por honorário "
        "(o maior, 30 dias)." in texto
    )
    assert "Atrasou, mas pagou sem precisar ser cobrado." in texto
    assert "O juros dele hoje é R$ 1,00 ao dia" in texto
    # média de 750: um mês de atraso custa 30 → 4% ao mês
    assert "um mês de atraso custa R$ 30,00 — 4,0% ao mês" in texto
    assert "Foram abonados R$ 6,00" in texto
    assert "Hoje não tem nada em atraso." in texto
    assert "Leitura: atrasa com frequência" in texto

    em_dia = "\n".join(analise_juros.explicar_cliente(geral.do_cliente(leve.id)))
    assert "Pagou tudo em dia" in em_dia
    assert "Leitura: um aumento não mudaria nada para ele" in em_dia


# ------------------------------------------------------- trabalho para receber


def _cobrar(sessao, cliente, dia, honorarios):
    ids = {h.id for h in honorarios}
    linhas = [
        linha
        for linha in cobrancas.linhas_em_aberto_do_cliente(sessao, cliente.id, dia)
        if linha.honorario.id in ids
    ]
    selecao = cobrancas.Selecao(cliente=cliente, linhas=linhas, data_referencia=dia)
    cobrancas.registrar(
        sessao, selecao, texto="cobrança", quando=datetime.combine(dia, time(10, 0))
    )
    sessao.commit()


@pytest.fixture
def trabalhoso(sessao, carteira):
    """Precisa ser cobrado: uma mensagem com dois honorários e outra só com um."""
    cliente = fabricas.cliente(
        sessao, codigo="40", nome="DA TRABALHO LTDA", documento="", juros_dia="1.00"
    )
    cliente.juros[0].vigencia_inicio = date(2020, 1, 1)
    sessao.commit()
    primeiro = fabricas.honorario(
        sessao, cliente, valor="600.00", vencimento=date(2026, 8, 1),
        competencia=Competencia(2026, 7),
    )
    segundo = fabricas.honorario(
        sessao, cliente, valor="400.00", vencimento=date(2026, 8, 1),
        tipo=fabricas.tipo_avulso(sessao), competencia=Competencia(),
        descricao="Alteração do endereço",
    )
    _cobrar(sessao, cliente, date(2026, 8, 5), [primeiro, segundo])   # 1 tentativa
    _cobrar(sessao, cliente, date(2026, 8, 15), [primeiro])           # 2ª tentativa
    _pagar(sessao, segundo, date(2026, 8, 11))                        # 10 dias
    _pagar(sessao, primeiro, date(2026, 8, 21))                       # 20 dias
    # e ainda um atrasado hoje, já cobrado uma vez
    aberto = fabricas.honorario(
        sessao, cliente, valor="600.00", vencimento=date(2026, 9, 1),
        competencia=Competencia(2026, 8),
    )
    _cobrar(sessao, cliente, date(2026, 9, 10), [aberto])
    return cliente


def test_conta_o_trabalho_para_receber(sessao, trabalhoso):
    geral = analise_juros.analisar(sessao, referencia=REFERENCIA)
    dele = geral.do_cliente(trabalhoso.id)

    # a mensagem com dois honorários conta uma vez para o cliente
    assert dele.cobrancas == 2
    assert sorted(item.cobrancas for item in dele.honorarios) == [1, 2]
    assert dele.dias_em_atraso == 30
    assert dele.cobrancas_por_atrasado == Decimal(1)
    assert dele.juros_por_cobranca == Decimal("15.00")               # 30 de juros ÷ 2

    hoje_ = dele.hoje
    assert (hoje_.quantidade, hoje_.maior_atraso, hoje_.cobrancas) == (1, 29, 1)
    assert dele.trabalho == (3, 2, 30)

    # na carteira toda, os outros clientes pagaram sem ser cobrados
    assert geral.cobrancas == 2
    assert [i.cliente.id for i in geral.ranking_trabalho.itens] == [trabalhoso.id]
    assert geral.ranking_trabalho.itens[0].rotulo == "2 cobranças"
    assert geral.ranking_tempo.itens[0].rotulo == "40 dias"          # o outro cliente


def test_explicacao_fala_do_trabalho_e_compara_com_a_media(sessao, trabalhoso):
    geral = analise_juros.analisar(sessao, referencia=REFERENCIA)
    texto = "\n".join(analise_juros.explicar_cliente(geral.do_cliente(trabalhoso.id)))
    assert "Foram 2 cobranças até ele pagar, 1,0 por honorário atrasado" in texto
    assert "(a média dos clientes é 0,5)" in texto
    assert "Cada cobrança rendeu em média R$ 15,00 de juros" in texto
    assert "Hoje tem 1 honorário em atraso (o mais antigo há 29 dias)" in texto
    assert "já com 1 cobrança(s)" in texto
    assert "Leitura: atrasa com frequência e precisa de mais cobranças que a média" in texto


# --------------------------------------------------- cenário por honorário


def test_cenario_aplicado_a_cada_honorario(sessao, carteira):
    cara, _ = carteira
    dele = analise_juros.analisar(sessao, referencia=REFERENCIA).do_cliente(cara.id)
    cenarios = {c.rotulo: c for c in analise_juros.cenarios(dele)}

    dobrar = analise_juros.por_honorario(dele, cenarios["Dobrar"])
    por_valor = {linha.item.original: linha for linha in dobrar}
    atrasado, abonado = por_valor[Decimal("1000.00")], por_valor[Decimal("500.00")]
    assert (atrasado.juros_cenario, atrasado.diferenca) == (Decimal("60.00"), Decimal("30.00"))
    assert atrasado.total_cenario == Decimal("1060.00")
    # o abono continua na mesma proporção: pagou 4 de 10, no dobro pagaria 8
    assert abonado.juros_cenario == Decimal("8.00")
    # a soma dos honorários bate com a tabela de cenários
    assert sum(linha.diferenca for linha in dobrar) == cenarios["Dobrar"].a_mais

    sem_abono = analise_juros.por_honorario(dele, cenarios["Mesma taxa, sem abono"])
    assert {linha.item.original: linha.diferenca for linha in sem_abono} == {
        Decimal("1000.00"): Decimal("0.00"),
        Decimal("500.00"): Decimal("6.00"),
    }
    como_esta = analise_juros.por_honorario(dele, cenarios["Como está hoje"])
    assert all(linha.diferenca == 0 for linha in como_esta)


def test_atrasados_de_hoje_so_mudam_daqui_para_frente(sessao, trabalhoso):
    dele = analise_juros.analisar(sessao, referencia=REFERENCIA).do_cliente(trabalhoso.id)
    [linha] = analise_juros.atrasados_no_cenario(dele, analise_juros.cenario(dele, Decimal(50)))
    atrasado = linha.atrasado

    assert atrasado.dias_atraso == 29
    assert atrasado.juros_ate_hoje == Decimal("29.00")      # o que já correu não muda
    assert atrasado.cobrancas == 1
    assert linha.juros_por_dia_cenario == Decimal("1.50")
    assert linha.total_projetado == Decimal("659.00")         # 629 + 30 × 1,00
    assert linha.total_projetado_cenario == Decimal("674.00")  # 629 + 30 × 1,50

    sem_abono = analise_juros.Cenario(
        rotulo="x", explicacao="", aumento=Decimal(0), juros_no_periodo=Decimal(0),
        a_mais=Decimal(0), a_mais_por_mes=Decimal(0), sem_abono=True,
    )
    [igual] = analise_juros.atrasados_no_cenario(dele, sem_abono)
    assert igual.total_projetado_cenario == igual.total_projetado
