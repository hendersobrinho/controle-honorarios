from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from honorarios.dominio.enums import Periodicidade
from honorarios.dominio.valores import Competencia
from honorarios.servicos import contratos
from honorarios.servicos.erros import ErroDeValidacao, RegistroDuplicado
from testes import fabricas


def test_gerar_competencia_cria_honorario_com_vencimento_no_mes_seguinte(sessao):
    cliente = fabricas.cliente(sessao)
    fabricas.contrato(sessao, cliente, valor="1507.80", dia=8)
    previa = contratos.previa_geracao(sessao, Competencia(2026, 8))
    assert len(previa) == 1
    assert previa[0].vencimento == date(2026, 9, 8)
    criados = contratos.gerar(sessao, previa)
    sessao.commit()
    assert len(criados) == 1
    assert criados[0].valor_original == Decimal("1507.80")
    assert criados[0].competencia_chave == "2026-08"


def test_gerar_duas_vezes_nao_duplica(sessao):
    cliente = fabricas.cliente(sessao)
    fabricas.contrato(sessao, cliente)
    contratos.gerar(sessao, contratos.previa_geracao(sessao, Competencia(2026, 8)))
    sessao.commit()
    previa = contratos.previa_geracao(sessao, Competencia(2026, 8))
    assert previa[0].impedimento == "Já lançado nesta competência"
    assert contratos.gerar(sessao, previa) == []


def test_contrato_suspenso_nao_gera(sessao):
    cliente = fabricas.cliente(sessao)
    contrato = fabricas.contrato(sessao, cliente)
    contratos.suspender(sessao, contrato)
    previa = contratos.previa_geracao(sessao, Competencia(2026, 8))
    assert "suspenso" in previa[0].impedimento.lower()
    assert contratos.gerar(sessao, previa) == []
    contratos.suspender(sessao, contrato, False)
    assert contratos.gerar(sessao, contratos.previa_geracao(sessao, Competencia(2026, 8)))


def test_vigencia_futura_nao_gera(sessao):
    cliente = fabricas.cliente(sessao)
    contrato = fabricas.contrato(sessao, cliente)
    contrato.vigencia_inicio = date(2026, 10, 1)
    sessao.commit()
    previa = contratos.previa_geracao(sessao, Competencia(2026, 8))
    assert "Vigência começa" in previa[0].impedimento


def test_vigencia_encerrada_nao_gera(sessao):
    cliente = fabricas.cliente(sessao)
    contrato = fabricas.contrato(sessao, cliente)
    contrato.vigencia_fim = date(2026, 7, 31)
    sessao.commit()
    previa = contratos.previa_geracao(sessao, Competencia(2026, 8))
    assert "Vigência encerrada" in previa[0].impedimento


def test_trimestral_gera_a_cada_tres_meses(sessao):
    cliente = fabricas.cliente(sessao)
    tipo = sessao.scalars(
        __import__("sqlalchemy").select(
            __import__("honorarios.infra.modelos", fromlist=["TipoHonorario"]).TipoHonorario
        )
    ).first()
    contrato = fabricas.contrato(
        sessao, cliente, periodicidade=Periodicidade.TRIMESTRAL, tipo=tipo
    )
    contrato.vigencia_inicio = date(2026, 1, 1)
    sessao.commit()
    assert contratos.previa_geracao(sessao, Competencia(2026, 4))[0].impedimento == ""
    assert "não gera" in contratos.previa_geracao(sessao, Competencia(2026, 5))[0].impedimento


def test_meses_de_referencia_explicitos(sessao):
    cliente = fabricas.cliente(sessao)
    contrato = fabricas.contrato(sessao, cliente, periodicidade=Periodicidade.ANUAL)
    contrato.meses_referencia = "6"
    sessao.commit()
    assert contratos.previa_geracao(sessao, Competencia(2026, 6))[0].impedimento == ""
    assert "não gera" in contratos.previa_geracao(sessao, Competencia(2026, 7))[0].impedimento


def test_dia_31_em_mes_curto(sessao):
    cliente = fabricas.cliente(sessao)
    fabricas.contrato(sessao, cliente, dia=31)
    previa = contratos.previa_geracao(sessao, Competencia(2026, 1))
    assert previa[0].vencimento == date(2026, 2, 28)


def test_item_desmarcado_nao_e_gerado(sessao):
    cliente = fabricas.cliente(sessao)
    fabricas.contrato(sessao, cliente)
    previa = contratos.previa_geracao(sessao, Competencia(2026, 8))
    previa[0].selecionado = False
    assert contratos.gerar(sessao, previa) == []


def test_reajuste_gera_historico_e_vale_para_frente(sessao):
    cliente = fabricas.cliente(sessao)
    contrato = fabricas.contrato(sessao, cliente, valor="1000.00")
    contratos.gerar(sessao, contratos.previa_geracao(sessao, Competencia(2026, 7)))
    sessao.commit()
    contratos.reajustar(sessao, contrato, Decimal("1100.00"), date(2026, 8, 1), "Anual")
    sessao.commit()
    gerados = contratos.gerar(sessao, contratos.previa_geracao(sessao, Competencia(2026, 8)))
    sessao.commit()
    antigo = [h for h in cliente.honorarios if h.competencia_mes == 7][0]
    assert antigo.valor_original == Decimal("1000.00")   # o que passou não muda
    assert gerados[0].valor_original == Decimal("1100.00")
    assert contrato.historico[0].valor_anterior == "1000.00"
    assert contrato.historico[0].vigencia_inicio == date(2026, 8, 1)


def test_editar_valor_direto_e_bloqueado(sessao):
    cliente = fabricas.cliente(sessao)
    contrato = fabricas.contrato(sessao, cliente, valor="1000.00")
    dados = contratos.DadosContrato(
        cliente_id=cliente.id, tipo_id=contrato.tipo_id, valor=Decimal("1200.00")
    )
    with pytest.raises(ErroDeValidacao, match="Reajustar"):
        contratos.atualizar(sessao, contrato, dados)


def test_previa_de_reajuste_em_massa(sessao):
    cliente = fabricas.cliente(sessao)
    contrato = fabricas.contrato(sessao, cliente, valor="1000.00")
    itens = contratos.previa_reajuste([contrato], percentual=Decimal("7.5"))
    assert itens[0].valor_novo == Decimal("1075.00")
    assert contratos.aplicar_reajuste(sessao, itens, date(2027, 1, 1)) == 1
    sessao.commit()
    assert contrato.valor == Decimal("1075.00")


def test_reajuste_exige_percentual_ou_valor(sessao):
    cliente = fabricas.cliente(sessao)
    contrato = fabricas.contrato(sessao, cliente)
    with pytest.raises(ErroDeValidacao):
        contratos.previa_reajuste([contrato])


def test_contrato_duplicado_do_mesmo_tipo(sessao):
    cliente = fabricas.cliente(sessao)
    fabricas.contrato(sessao, cliente)
    with pytest.raises(RegistroDuplicado):
        fabricas.contrato(sessao, cliente)


def test_competencia_sem_mes_e_recusada(sessao):
    with pytest.raises(ErroDeValidacao, match="mm/aaaa"):
        contratos.previa_geracao(sessao, Competencia(2026))
