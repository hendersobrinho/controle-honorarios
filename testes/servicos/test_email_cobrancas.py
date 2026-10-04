"""E-mail "Clientes c/Honorários vencidos": conferir a lista do financeiro e responder.

Tudo com dados fictícios — o e-mail real tem dados de clientes e não entra aqui.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

import pytest

from honorarios.dominio.enums import ResultadoCobranca
from honorarios.dominio.valores import Competencia
from honorarios.servicos import cobrancas
from honorarios.servicos import email_cobrancas as servico
from honorarios.servicos.erros import ErroDeValidacao
from testes import fabricas

HOJE = date(2026, 9, 24)


@pytest.fixture
def carteira(sessao):
    """Duas empresas devendo; uma com dois honorários e uma cobrança anotada."""
    alfa = fabricas.cliente(sessao, codigo="301", nome="ALFA MOVEIS LTDA", documento="")
    ipe = fabricas.cliente(sessao, codigo="302", nome="IPE INDUSTRIA E COMERCIO LTDA",
                           documento="")
    for mes, vencimento in ((7, date(2026, 8, 5)), (8, date(2026, 9, 8))):
        fabricas.honorario(sessao, alfa, valor="1507.80", vencimento=vencimento,
                           competencia=Competencia(2026, mes))
    fabricas.honorario(sessao, ipe, valor="399.00", vencimento=date(2026, 9, 8),
                       competencia=Competencia(2026, 8))
    # vence depois da data do e-mail: não entra
    fabricas.honorario(sessao, ipe, valor="399.00", vencimento=date(2026, 10, 8),
                       competencia=Competencia(2026, 9))
    sessao.commit()
    linhas = cobrancas.linhas_em_aberto_do_cliente(sessao, alfa.id, date(2026, 9, 17))
    cobrancas.registrar(
        sessao, cobrancas.Selecao(cliente=alfa, linhas=linhas, data_referencia=date(2026, 9, 17)),
        texto="oi", resultado=ResultadoCobranca.PROMETEU_PAGAR,
        promessa_data=date(2026, 9, 30), observacao="vai acertar no fim do mês",
        quando=datetime.combine(date(2026, 9, 17), time(9)),
    )
    sessao.commit()
    return alfa, ipe


# o e-mail do financeiro, escrito à mão: nomes abreviados, colunas desalinhadas,
# anotação que continua na linha de baixo, total no meio e um valor digitado errado
EMAIL_DO_FINANCEIRO = """\
Cobranças de 24/09/2026

Cliente                 Competência             Vencimento            Valor

Alfa Móveis Ltda.        07/2026             05/08/2026        1.507,80
Ipê Ind.Com.      08/2026             08/09/2026        399,00
Total do Débito: 1.906,80
18/09: Feito cobrança - Disse que está sem caixa agora. Vai tentar pagar uma parte
até o fim do mês.
Empresa Fantasma Ltda   08/2026   08/09/2026   2,500,00
22/09: Pagou hoje.
"""


def test_le_o_padrao_escrito_a_mao():
    leitura = servico.ler(EMAIL_DO_FINANCEIRO)
    assert leitura.data == HOJE
    assert [(x.cliente, x.competencia, x.vencimento) for x in leitura.linhas] == [
        ("Alfa Móveis Ltda.", "07/2026", date(2026, 8, 5)),
        ("Ipê Ind.Com.", "08/2026", date(2026, 9, 8)),
        ("Empresa Fantasma Ltda", "08/2026", date(2026, 9, 8)),
    ]
    assert leitura.linhas[2].valor == Decimal("2500.00")    # "2,500,00"
    assert leitura.linhas[1].notas == [
        "18/09: Feito cobrança - Disse que está sem caixa agora. Vai tentar pagar uma parte "
        "até o fim do mês."
    ]


def test_quem_sai_da_lista_vira_provavel_pagamento(sessao, carteira):
    alfa, _ = carteira
    conferencia = servico.conferir(sessao, servico.ler(EMAIL_DO_FINANCEIRO), HOJE)
    # casou pelo vencimento e pelo nome abreviado
    assert {c.linha.cliente.codigo for c in conferencia.continuam} == {"301", "302"}
    # o honorário de 08/2026 da Alfa não está no e-mail: saiu da lista
    [saiu] = conferencia.sairam
    assert saiu.cliente.id == alfa.id and saiu.honorario.vencimento == date(2026, 9, 8)
    assert list(conferencia.sairam_por_cliente()) == [alfa]
    # a linha que não existe no sistema fica à parte, para olhar
    [fora] = conferencia.nao_encontradas
    assert fora.cliente == "Empresa Fantasma Ltda"


def test_resposta_mantem_a_lista_e_junta_o_andamento(sessao, carteira):
    conferencia = servico.conferir(sessao, servico.ler(EMAIL_DO_FINANCEIRO), HOJE)
    resposta = servico.responder(sessao, conferencia, date(2026, 9, 25))
    corpo = servico.texto(resposta)
    assert corpo.startswith("Cobranças de 25/09/2026")
    # a lista do financeiro, com o nome do sistema e o código na frente
    assert "301 – ALFA MOVEIS LTDA\t07/2026\t05/08/2026\t1.507,80" in corpo
    # quem saiu da lista (a Alfa de 08/2026) não volta na resposta
    assert "08/09/2026\t1.507,80" not in corpo
    # o que o sistema sabe da Alfa entra; o que já veio no e-mail não se repete
    assert "17/09: Feito cobrança, prometeu pagar em 30/09 - vai acertar no fim do mês." in corpo
    assert corpo.count("18/09: Feito cobrança - Disse que está") == 1
    # linha que o sistema não reconhece vai como veio
    assert "Empresa Fantasma Ltda\t08/2026\t08/09/2026\t2.500,00" in corpo
    assert "22/09: Pagou hoje." in corpo
    assert resposta.assunto == "RE: Clientes c/Honorários vencidos"


def test_anotacoes_sem_repetir_e_em_ordem():
    juntas = servico.juntar_notas(
        ["22/09: Feito cobrança sem retorno", "17/09: Feito cobrança sem retorno."],
        ["17/09: Feito cobrança sem retorno.", "20/12: do ano passado"],
        date(2026, 9, 25),
    )
    assert juntas == ["20/12: do ano passado", "17/09: Feito cobrança sem retorno.",
                      "22/09: Feito cobrança sem retorno"]


def test_rascunho_responde_na_mesma_conversa(sessao, carteira, tmp_path):
    original = EmailMessage()
    original["From"] = "Financeiro <financeiro@exemplo.com.br>"
    original["To"] = "Cobranca <cobranca@exemplo.com.br>"
    original["Cc"] = "Gerencia <gerencia@exemplo.com.br>"
    original["Subject"] = "Clientes c/Honorários vencidos"
    original["Message-ID"] = "<lista-123@exemplo.com.br>"
    original.set_content(EMAIL_DO_FINANCEIRO)
    arquivo = tmp_path / "lista.eml"
    arquivo.write_bytes(bytes(original))

    recebido = servico.abrir(arquivo)
    assert recebido.de == "Financeiro <financeiro@exemplo.com.br>"
    conferencia = servico.conferir(sessao, servico.ler(recebido.texto), HOJE)
    resposta = servico.responder(sessao, conferencia, HOJE, recebido)
    with pytest.raises(ErroDeValidacao):
        servico.eml(resposta)                               # falta configurar o seu e-mail

    servico.gravar_remetente(sessao, servico.Remetente(
        nome="Cobranca", email="cobranca@exemplo.com.br"))
    resposta = servico.responder(sessao, conferencia, HOJE, recebido)
    mensagem = BytesParser(policy=policy.default).parsebytes(servico.eml(resposta))
    assert mensagem["To"] == "Financeiro <financeiro@exemplo.com.br>"
    assert mensagem["Cc"] == "Gerencia <gerencia@exemplo.com.br>"   # sem o próprio e-mail
    assert mensagem["Subject"] == "RE: Clientes c/Honorários vencidos"
    assert mensagem["In-Reply-To"] == "<lista-123@exemplo.com.br>"
    assert mensagem["X-Unsent"] == "1"
    assert "ALFA MOVEIS" in mensagem.get_body(("html",)).get_content()


def test_sem_o_email_monta_pelo_sistema(sessao, carteira):
    email = servico.montar(sessao, HOJE)
    assert [bloco.nome for bloco in email.blocos] == [
        "301 – ALFA MOVEIS LTDA", "302 – IPE INDUSTRIA E COMERCIO LTDA",
    ]
    corpo = servico.texto(email)
    assert "Total do Débito: 3.015,60" in corpo          # só quem tem mais de um
    assert "10/2026" not in corpo and "08/10/2026" not in corpo
    # e o que o sistema monta volta igual na conferência (texto ou HTML)
    for conteudo in (corpo, servico.texto_do_html(servico.html(email))):
        conferencia = servico.conferir(sessao, servico.ler(conteudo), HOJE)
        assert len(conferencia.continuam) == 3
        assert conferencia.sairam == [] and conferencia.nao_encontradas == []


def test_codigo_vale_mais_que_o_nome(sessao, carteira):
    texto = "Cobranças de 24/09/2026\n302 – Nome Qualquer\t08/2026\t08/09/2026\t399,00\n"
    conferencia = servico.conferir(sessao, servico.ler(texto), HOJE)
    [casou] = conferencia.continuam
    assert casou.linha.cliente.codigo == "302"


def test_semelhanca_de_nome_abreviado():
    assert servico.semelhanca("Ipê Ind.Com.", "IPE INDUSTRIA E COMERCIO LTDA") == 1
    assert servico.semelhanca("Clínica Exemplo Vit.", "OUTRA EMPRESA LTDA") == 0


def test_competencia_com_espacos_nao_gruda_no_nome():
    texto = ("Cobranças de 24/09/2026\n"
             "CARLOS EDUARDO MARTINS\tImposto de Renda 2026\t25/06/2026\t256,63\n"
             "Maria R.Souza Lima   Trimestral   06/07/2026   660,00\n"
             "Beta Representações 02/2026 16/03/2026 158,00\n")
    assert [(x.cliente, x.competencia) for x in servico.ler(texto).linhas] == [
        ("CARLOS EDUARDO MARTINS", "Imposto de Renda 2026"),
        ("Maria R.Souza Lima", "Trimestral"),
        ("Beta Representações", "02/2026"),
    ]


def test_endereco_com_acento_fica_legivel():
    assert servico.endereco_legivel("Gerência", "g@exemplo.com.br") == "Gerência <g@exemplo.com.br>"
    assert servico.endereco_legivel("Silva, Ana", "a@x") == '"Silva, Ana" <a@x>'
    assert servico.endereco_legivel("", "a@x") == "a@x"


def test_baixa_dos_que_sairam_com_previa(sessao, carteira):
    from honorarios.dominio.enums import FormaPagamento, StatusPagamento

    conferencia = servico.conferir(sessao, servico.ler(EMAIL_DO_FINANCEIRO), HOJE)
    [saiu] = conferencia.sairam
    honorarios = [linha.honorario for linha in conferencia.sairam]
    # com juros até a data do pagamento (o juros do cliente é 1,01/dia na fábrica)
    [com] = servico.previa_baixa(honorarios, date(2026, 9, 20), True, HOJE)
    assert com.juros > 0 and com.valor == com.saldo + com.juros and not com.justificativa
    # sem juros: só o saldo, e o abono vai justificado pela lista
    [sem] = servico.previa_baixa(honorarios, date(2026, 9, 20), False, HOJE)
    assert sem.valor == sem.saldo and "lista do financeiro de 24/09/2026" in sem.justificativa
    assert saiu.honorario.status is StatusPagamento.EM_ABERTO      # a prévia não grava

    sem.marcado = False
    with pytest.raises(ErroDeValidacao):
        servico.dar_baixa(sessao, [sem], date(2026, 9, 20), FormaPagamento.BOLETO, HOJE)
    sem.marcado = True
    assert servico.dar_baixa(sessao, [sem], date(2026, 9, 20), FormaPagamento.BOLETO,
                             HOJE) == 1
    honorario = saiu.honorario
    assert honorario.status is StatusPagamento.PAGO and honorario.pago_em == date(2026, 9, 20)
    [pagamento] = honorario.pagamentos
    assert pagamento.juros_cobrados == 0 and pagamento.desconto == sem.juros
    assert "lista do financeiro" in pagamento.observacoes


def test_pago_depois_do_email_nao_volta_na_resposta(sessao, carteira):
    from honorarios.servicos import pagamentos

    alfa, _ = carteira
    leitura = servico.ler(EMAIL_DO_FINANCEIRO)
    conferencia = servico.conferir(sessao, leitura, HOJE)
    julho = next(c.linha.honorario for c in conferencia.continuam
                 if c.linha.cliente.id == alfa.id)
    previa = pagamentos.previa(julho, HOJE)
    pagamentos.registrar(sessao, julho, pagamentos.DadosPagamento(
        data=HOJE, valor_pago=previa.total_devido))
    conferencia = servico.conferir(sessao, leitura, HOJE)
    [pago] = conferencia.pagos
    assert pago.linha.honorario.id == julho.id
    assert all(lida.cliente != "Alfa Móveis Ltda." for lida in conferencia.nao_encontradas)
    corpo = servico.texto(servico.responder(sessao, conferencia, HOJE))
    assert "05/08/2026" not in corpo                               # já pago: fica de fora


def test_anotacao_diz_de_qual_honorario(sessao, carteira):
    alfa, _ = carteira
    linhas = cobrancas.linhas_em_aberto_do_cliente(sessao, alfa.id, HOJE)
    julho = [linha for linha in linhas if linha.honorario.competencia_rotulo == "07/2026"]
    cobrancas.registrar(
        sessao, cobrancas.Selecao(cliente=alfa, linhas=julho, data_referencia=HOJE),
        resultado=ResultadoCobranca.PROMETEU_PAGAR, promessa_data=date(2026, 9, 28),
        observacao="vai pagar o boleto de julho", quando=datetime.combine(HOJE, time(10)),
    )
    notas = servico.notas_do_sistema([linha.honorario for linha in linhas])
    assert notas[-1] == ("24/09: Feito cobrança, prometeu pagar em 28/09 - vai pagar o boleto "
                         "de julho (07/2026).")
    # a cobrança de 17/09 foi dos dois: sem dizer de quais
    assert notas[0].startswith("17/09:") and "(07/2026" not in notas[0]


def test_anotar_retorno_na_cobranca_que_espera_ou_contato_novo(sessao, carteira):
    from honorarios.servicos import acompanhamento

    _, ipe = carteira
    [linha] = [x for x in cobrancas.linhas_em_aberto_do_cliente(sessao, ipe.id, HOJE)
               if x.honorario.vencimento < HOJE]
    # sem cobrança esperando resposta: vira um contato com o retorno
    feito = acompanhamento.anotar_retorno(
        sessao, ipe, [linha.honorario], ResultadoCobranca.PEDIU_RENEGOCIACAO,
        observacao="quer parcelar em 3x", data_referencia=HOJE)
    assert feito == "Contato registrado com o retorno."
    [cobranca] = linha.honorario.cobrancas
    assert cobranca.resultado is ResultadoCobranca.PEDIU_RENEGOCIACAO

    # com uma cobrança aguardando: o retorno vai nela, sem criar outra
    cobrancas.registrar(sessao, cobrancas.Selecao(cliente=ipe, linhas=[linha],
                                                  data_referencia=HOJE), texto="oi")
    feito = acompanhamento.anotar_retorno(
        sessao, ipe, [linha.honorario], ResultadoCobranca.SEM_RESPOSTA, data_referencia=HOJE)
    assert feito.startswith("Retorno anotado na cobrança de")
    assert len(linha.honorario.cobrancas) == 2
    assert linha.honorario.cobrancas[-1].resultado is ResultadoCobranca.SEM_RESPOSTA
    with pytest.raises(ErroDeValidacao):
        acompanhamento.anotar_retorno(sessao, ipe, [linha.honorario],
                                      ResultadoCobranca.AGUARDANDO)


# a lista copiada de um PDF: cada coluna numa linha, um bloco em colunas e
# clientes que perderam vencimento e valor na cópia
COPIADO_DO_PDF = """\
Cobranças de 24/09/2026
Cliente
Competência
Vencimento
Valor
Alfa Móveis Ltda.
07/2026
05/08/2026
1.507,80
Beta Representações 02/2026
Beta Representações 03/2026
16/03/2026
16/04/2026
158,00
344,00
17/09: Feito cobrança - disse que está sem caixa. Vai precisar
de um tempo para pagar.
Gama Serviços
22/09: Pagou hoje.
Delta Consult.
08/2026
17/09: Feito cobrança sem retorno
"""


def test_le_colunas_em_linhas_separadas():
    leitura = servico.ler(COPIADO_DO_PDF)
    assert [(x.cliente, x.competencia, x.vencimento, x.valor) for x in leitura.linhas] == [
        ("Alfa Móveis Ltda.", "07/2026", date(2026, 8, 5), Decimal("1507.80")),
        ("Beta Representações", "02/2026", date(2026, 3, 16), Decimal("158.00")),
        ("Beta Representações", "03/2026", date(2026, 4, 16), Decimal("344.00")),
    ]
    assert leitura.linhas[-1].notas == [
        "17/09: Feito cobrança - disse que está sem caixa. Vai precisar de um tempo para pagar."
    ]
    # sem vencimento e valor: à parte, com as anotações delas (não grudam na Beta)
    assert [(i.texto, i.notas) for i in leitura.incompletas] == [
        ("Gama Serviços", ["22/09: Pagou hoje."]),
        ("Delta Consult. 08/2026", ["17/09: Feito cobrança sem retorno"]),
    ]


def test_incompletas_voltam_na_resposta(sessao, carteira):
    conferencia = servico.conferir(sessao, servico.ler(COPIADO_DO_PDF), HOJE)
    corpo = servico.texto(servico.responder(sessao, conferencia, HOJE))
    assert "Gama Serviços" in corpo and "22/09: Pagou hoje." in corpo


def test_resposta_ignora_o_email_citado_embaixo():
    texto = (EMAIL_DO_FINANCEIRO
             + "\nOn Sun, Oct 4, 2026 at 12:51 AM Fulano <a@\nexemplo.com> wrote:\n"
             "> Alfa Móveis Ltda.        07/2026   05/08/2026   1.507,80\n> 17/09: velho\n")
    leitura = servico.ler(texto)
    assert len(leitura.linhas) == 3                      # a lista citada não volta
    assert not any("wrote" in nota for linha in leitura.linhas for nota in linha.notas)
    assert len(servico.ler(EMAIL_DO_FINANCEIRO + "\n-----Mensagem original-----\n"
                           "Ipê Ind.Com. 08/2026 08/09/2026 399,00\n").linhas) == 3


def test_mesma_competencia_com_vencimento_diferente(sessao, carteira):
    # no e-mail o honorário de julho da Alfa vence 06/08, no sistema 05/08
    texto = "Cobranças de 24/09/2026\nAlfa Móveis Ltda.  07/2026  06/08/2026  1.507,80\n"
    conferencia = servico.conferir(sessao, servico.ler(texto), HOJE)
    [casou] = conferencia.continuam
    assert casou.linha.honorario.vencimento == date(2026, 8, 5)
    assert conferencia.nao_encontradas == []


def test_correcao_a_mao_associa_ou_ignora(sessao, carteira):
    alfa, ipe = carteira
    texto = ("Cobranças de 24/09/2026\n"
             "Fornecedor Qualquer  08/2026  08/09/2026  399,00\n"
             "Cliente Novo Ltda  08/2026  10/09/2026  50,00\n")
    leitura = servico.ler(texto)
    conferencia = servico.conferir(sessao, leitura, HOJE)
    assert len(conferencia.nao_encontradas) == 2
    honorario_ipe = next(linha.honorario for linha in conferencia.sairam
                         if linha.cliente.id == ipe.id)
    correcoes = {
        servico.chave_da_linha(leitura.linhas[0]): honorario_ipe.id,   # era a Ipê
        servico.chave_da_linha(leitura.linhas[1]): 0,                  # ignorar
    }
    conferencia = servico.conferir(sessao, leitura, HOJE, correcoes)
    [casou] = conferencia.continuam
    assert casou.linha.honorario.id == honorario_ipe.id
    assert id(casou.lida) in conferencia.corrigidas
    assert [x.cliente for x in conferencia.ignoradas] == ["Cliente Novo Ltda"]
    assert conferencia.nao_encontradas == []
    # quem não está mais na lista (os dois da Alfa) sai para a baixa
    assert {linha.cliente.id for linha in conferencia.sairam} == {alfa.id}
