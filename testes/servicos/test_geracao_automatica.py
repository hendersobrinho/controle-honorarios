"""Geração automática da competência: opcional, no dia escolhido, uma vez por mês."""

from __future__ import annotations

from datetime import date

from honorarios.dominio.valores import Competencia
from honorarios.servicos import configuracoes, contratos, geracao_automatica, notificacoes
from honorarios.servicos import honorarios as servico_honorarios
from testes import fabricas


def _ligar(sessao, dia=5):
    configuracoes.gravar(sessao, geracao_automatica.LIGADA, "1")
    configuracoes.gravar(sessao, geracao_automatica.DIA, str(dia))
    sessao.commit()


def _lancados(sessao, competencia):
    return [
        item for item in contratos.previa_geracao(sessao, competencia)
        if item.impedimento == "Já lançado nesta competência"
    ]


def test_desligada_por_padrao(sessao):
    fabricas.contrato(sessao, fabricas.cliente(sessao))
    assert not geracao_automatica.ligada(sessao)
    assert geracao_automatica.executar(sessao, date(2026, 10, 20)) is None
    assert _lancados(sessao, Competencia(2026, 10)) == []


def test_gera_a_partir_do_dia_uma_vez_e_avisa(sessao):
    cliente = fabricas.cliente(sessao)
    fabricas.contrato(sessao, cliente)
    outra = fabricas.cliente(sessao, nome="SUSPENSA LTDA", codigo="901", documento="")
    suspenso = fabricas.contrato(sessao, outra)
    contratos.suspender(sessao, suspenso)
    _ligar(sessao, dia=5)
    outubro = Competencia(2026, 10)

    assert geracao_automatica.executar(sessao, date(2026, 10, 4)) is None   # antes do dia
    aviso = geracao_automatica.executar(sessao, date(2026, 10, 5))
    sessao.commit()
    assert aviso.tipo == notificacoes.GERACAO and aviso.tela == "Honorários"
    assert "1 honorário" in aviso.titulo                  # o suspenso ficou de fora
    [lancado] = _lancados(sessao, outubro)
    assert lancado.cliente.id == cliente.id

    # cancelado depois, não volta: a geração do mês já foi feita
    honorario = servico_honorarios.existente(
        sessao, cliente.id, lancado.contrato.tipo_id, outubro
    )
    servico_honorarios.cancelar(sessao, honorario, "não deveria sair")
    sessao.commit()
    assert geracao_automatica.executar(sessao, date(2026, 10, 6)) is None
    assert _lancados(sessao, outubro) == []


def test_ligada_no_meio_do_mes_nao_refaz_cancelado(sessao):
    cliente = fabricas.cliente(sessao)
    contrato = fabricas.contrato(sessao, cliente)
    outubro = Competencia(2026, 10)
    contratos.gerar(sessao, contratos.previa_geracao(sessao, outubro))   # gerado à mão
    honorario = servico_honorarios.existente(sessao, cliente.id, contrato.tipo_id, outubro)
    servico_honorarios.cancelar(sessao, honorario, "cliente saiu")
    sessao.commit()

    _ligar(sessao, dia=1)
    assert geracao_automatica.executar(sessao, date(2026, 10, 15)) is None
    assert _lancados(sessao, outubro) == []
