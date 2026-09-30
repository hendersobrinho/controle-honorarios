"""Geração da mensagem de cobrança em todas as variantes."""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest

from honorarios.dominio import mensagens as m
from honorarios.dominio.enums import ChaveModelo, OrdemSaudacao, TipoChavePix
from honorarios.dominio.valores import Competencia

RECEBEDOR = m.Recebedor(
    "Métodos Serviços Contábeis Ltda", TipoChavePix.CNPJ, "00.000.000/0001-00"
)


def item_mensal(competencia, vencimento, valor, juros, dias):
    return m.ItemCobranca(
        tipo_nome="Honorário mensal",
        texto_mensagem=m.TEXTO_MENSAL,
        texto_mensagem_empresa=m.TEXTO_MENSAL_EMPRESA,
        texto_item_lista=m.TEXTO_MENSAL_ITEM,
        competencia=competencia,
        vencimento=vencimento,
        valor_original=Decimal(valor),
        juros=Decimal(juros),
        valor_atualizado=Decimal(valor) + Decimal(juros),
        dias_atraso=dias,
    )


def contexto(itens, **kwargs):
    base = dict(
        empresa="EMPRESA EXEMPLO LTDA",
        itens=itens,
        recebedor=RECEBEDOR,
        data_referencia=date(2026, 9, 17),
        hora_referencia=time(14, 30),
        nome_tratamento="Carol",
    )
    base.update(kwargs)
    return m.ContextoMensagem(**base)


@pytest.mark.parametrize(
    "hora,esperado",
    [
        (time(0, 0), "Bom dia"),
        (time(11, 59), "Bom dia"),
        (time(12, 0), "Boa tarde"),
        (time(17, 59), "Boa tarde"),
        (time(18, 0), "Boa noite"),
        (time(23, 59), "Boa noite"),
    ],
)
def test_saudacao_por_horario(hora, esperado):
    assert m.saudacao_por_horario(hora) == esperado


def test_saudacao_com_e_sem_nome():
    assert m.montar_saudacao(time(9, 0), "Carol") == "Bom dia, Carol!"
    assert m.montar_saudacao(time(9, 0), None) == "Bom dia!"
    assert m.montar_saudacao(time(9, 0), "  ") == "Bom dia!"


def test_saudacao_nas_duas_ordens():
    assert (
        m.montar_saudacao(time(14, 0), "Carol", OrdemSaudacao.NOME_SAUDACAO)
        == "Carol, boa tarde!"
    )


def test_um_honorario_em_atraso():
    texto = m.montar_mensagem(
        contexto([item_mensal(Competencia(2026, 8), date(2026, 9, 8), "592.90", "6.80", 9)])
    )
    assert texto.startswith("Boa tarde, Carol! Tudo bem?")
    assert "honorário referente à competência 08/2026" in texto
    assert "com vencimento em 08/09/2026" in texto
    assert "Para pagamento hoje, 17/09/2026, o valor atualizado é de R$ 599,70." in texto
    assert "PIX – Métodos Serviços Contábeis Ltda" in texto
    assert "CNPJ: 00.000.000/0001-00" in texto
    assert texto.endswith("Após o pagamento, por gentileza, nos encaminhe o comprovante.")


def test_citar_empresa():
    texto = m.montar_mensagem(
        contexto(
            [item_mensal(Competencia(2026, 8), date(2026, 9, 8), "592.90", "6.80", 9)],
            citar_empresa=True,
        )
    )
    assert "referente à empresa EMPRESA EXEMPLO LTDA, competência 08/2026" in texto


def test_sem_nome_de_tratamento():
    texto = m.montar_mensagem(
        contexto(
            [item_mensal(Competencia(2026, 8), date(2026, 9, 8), "592.90", "6.80", 9)],
            nome_tratamento=None,
        )
    )
    assert texto.startswith("Boa tarde! Tudo bem?")


def test_varios_honorarios_geram_uma_mensagem_com_total():
    itens = [
        item_mensal(Competencia(2026, 7), date(2026, 8, 8), "600.00", "10.20", 40),
        item_mensal(Competencia(2026, 8), date(2026, 9, 8), "590.00", "6.50", 9),
    ]
    texto = m.montar_mensagem(contexto(itens, hora_referencia=time(9, 0)))
    assert "Constam em aberto os seguintes honorários:" in texto
    assert "• Honorário referente à competência 07/2026, vencimento 08/08/2026 – R$ 610,20" in texto
    assert "• Honorário referente à competência 08/2026, vencimento 08/09/2026 – R$ 596,50" in texto
    assert "o valor total atualizado é de R$ 1.206,70." in texto


def test_sem_atraso_usa_lembrete_e_nao_diz_atualizado():
    texto = m.montar_mensagem(
        contexto(
            [item_mensal(Competencia(2026, 10), date(2026, 10, 10), "500.00", "0", 0)],
            data_referencia=date(2026, 10, 1),
        )
    )
    assert "Consta em aberto" not in texto
    assert "atualizado" not in texto
    assert "que vence em 10/10/2026, o valor é de R$ 500,00." in texto


def test_imposto_de_renda_usa_o_ano():
    item = m.ItemCobranca(
        tipo_nome="Imposto de Renda",
        texto_mensagem=m.TEXTO_IRPF,
        texto_mensagem_empresa=m.TEXTO_IRPF_EMPRESA,
        texto_item_lista=m.TEXTO_IRPF_ITEM,
        competencia=Competencia(2026),
        vencimento=date(2026, 8, 10),
        valor_original=Decimal("250.00"),
        juros=Decimal("6.63"),
        valor_atualizado=Decimal("256.63"),
        dias_atraso=39,
    )
    texto = m.montar_mensagem(
        contexto([item], nome_tratamento="Douglas", hora_referencia=time(9, 0),
                 data_referencia=date(2026, 9, 18))
    )
    assert "Bom dia, Douglas! Tudo bem?" in texto
    assert "honorário referente ao seu imposto de renda/2026" in texto
    assert "o valor atualizado é de R$ 256,63." in texto


def test_servico_avulso_usa_o_nome_do_tipo():
    item = m.ItemCobranca(
        tipo_nome="Alteração Contratual",
        texto_mensagem=m.TEXTO_AVULSO,
        texto_mensagem_empresa=m.TEXTO_AVULSO_EMPRESA,
        texto_item_lista=m.TEXTO_AVULSO_ITEM,
        competencia=Competencia(),
        vencimento=date(2026, 9, 10),
        valor_original=Decimal("750.00"),
        juros=Decimal("13.08"),
        valor_atualizado=Decimal("763.08"),
        dias_atraso=8,
    )
    texto = m.montar_mensagem(contexto([item], nome_tratamento=None, hora_referencia=time(9, 0),
                                       data_referencia=date(2026, 9, 18)))
    assert "boleto referente ao serviço de Alteração Contratual" in texto
    assert "o valor atualizado é de R$ 763,08." in texto


def test_modelo_editado_pelo_usuario_e_respeitado():
    texto = m.montar_mensagem(
        contexto(
            [item_mensal(Competencia(2026, 8), date(2026, 9, 8), "100.00", "1.00", 5)],
            modelos={ChaveModelo.UNIDADE: "{saudacao} Deve {valor} desde {vencimento}."},
        )
    )
    assert texto == "Boa tarde, Carol! Deve R$ 101,00 desde 08/09/2026."


def test_variavel_inexistente_avisa_com_a_lista():
    with pytest.raises(m.VariavelDesconhecida) as erro:
        m.montar_mensagem(
            contexto(
                [item_mensal(Competencia(2026, 8), date(2026, 9, 8), "100", "0", 0)],
                modelos={ChaveModelo.LEMBRETE: "{saudacao} {inexistente}"},
                forcar_lembrete=True,
            )
        )
    assert "{inexistente}" in str(erro.value)
    assert "{saudacao}" in str(erro.value)


def test_validar_modelo_lista_as_variaveis_erradas():
    assert m.validar_modelo("{saudacao} {valor}", ChaveModelo.UNIDADE) == []
    assert m.validar_modelo("{saudacao} {nao_existe}", ChaveModelo.UNIDADE) == ["nao_existe"]


def test_sem_itens_nao_gera_mensagem():
    with pytest.raises(ValueError):
        m.montar_mensagem(contexto([]))


def test_link_whatsapp_codifica_o_texto():
    link = m.montar_link_whatsapp("5527999990000", "Bom dia, Carol! Tudo bem?")
    assert link.startswith("https://wa.me/5527999990000?text=")
    assert "%20" in link and "%21" in link


def test_link_whatsapp_outros_formatos():
    assert m.montar_link_whatsapp("5527999990000", "oi", "PROTOCOLO").startswith(
        "whatsapp://send?phone="
    )
    assert m.montar_link_whatsapp("5527999990000", "oi", "API_WHATSAPP").startswith(
        "https://api.whatsapp.com/send?"
    )


def test_link_sem_telefone_avisa():
    with pytest.raises(ValueError):
        m.montar_link_whatsapp("", "oi")
