"""Notificações: vence hoje, não pago na data, promessa e acordo — sem duplicar."""

from __future__ import annotations

from datetime import date, timedelta

from honorarios.dominio.valores import Competencia, agora_utc
from honorarios.servicos import acordos
from honorarios.servicos import notificacoes as servico
from testes import fabricas

HOJE = date(2026, 9, 30)


def _cliente(sessao, **extras):
    cliente = fabricas.cliente(sessao, juros_dia="1.00", **extras)
    cliente.juros[0].vigencia_inicio = date(2020, 1, 1)
    sessao.commit()
    return cliente


def test_sem_pendencia_nao_ha_notificacao(sessao):
    assert servico.gerar(sessao, HOJE) == []
    assert servico.nao_lidas(sessao) == 0


def test_vence_hoje_e_nao_pago_por_cliente(sessao):
    cliente = _cliente(sessao)
    fabricas.honorario(sessao, cliente, valor="300.00", vencimento=HOJE,
                       competencia=Competencia(2026, 8))
    for mes in (6, 7):   # dois honorários que venceram no mesmo dia: um aviso só
        fabricas.honorario(sessao, cliente, valor="100.00", vencimento=date(2026, 9, 10),
                           competencia=Competencia(2026, mes))
    # venceu há mais de 30 dias: já passou da janela do "não pago na data"
    fabricas.honorario(sessao, cliente, valor="100.00", vencimento=date(2026, 7, 1),
                       competencia=Competencia(2026, 5))
    sessao.commit()

    novas = servico.gerar(sessao, HOJE)
    por_tipo = {n.tipo: n for n in novas}
    assert set(por_tipo) == {servico.VENCE_HOJE, servico.NAO_PAGO}
    assert por_tipo[servico.VENCE_HOJE].tela == "A vencer"
    assert "R$ 300,00" in por_tipo[servico.VENCE_HOJE].texto
    nao_pago = por_tipo[servico.NAO_PAGO]
    assert "2 honorários venceram em 10/09/2026" in nao_pago.titulo
    assert nao_pago.tela == "Atrasados" and nao_pago.cliente_id == cliente.id
    assert servico.resumo(novas) == (
        "1 cliente com vencimento hoje · 1 vencimento sem pagamento"
    )

    # verificar de novo (ao abrir, a cada meia hora) não duplica nada
    sessao.commit()
    assert servico.gerar(sessao, HOJE) == []
    assert servico.nao_lidas(sessao) == 2


def test_cobranca_suspensa_nao_gera_aviso(sessao):
    cliente = _cliente(sessao)
    cliente.cobranca_suspensa = True
    fabricas.honorario(sessao, cliente, valor="300.00", vencimento=HOJE,
                       competencia=Competencia(2026, 8))
    sessao.commit()
    assert servico.gerar(sessao, HOJE) == []


def test_acordo_que_vence_hoje(sessao):
    cliente = _cliente(sessao)
    atrasado = fabricas.honorario(sessao, cliente, valor="500.00",
                                  vencimento=date(2026, 7, 10),
                                  competencia=Competencia(2026, 6))
    acordos.registrar(sessao, [atrasado], date(2026, 9, 25), HOJE)
    sessao.commit()
    [aviso] = [n for n in servico.gerar(sessao, HOJE) if n.tipo == servico.ACORDO]
    assert "vence hoje" in aviso.titulo
    assert "juros volta a correr" in aviso.texto


def test_marcar_lidas_e_limpar_antigas(sessao):
    cliente = _cliente(sessao)
    fabricas.honorario(sessao, cliente, valor="300.00", vencimento=HOJE,
                       competencia=Competencia(2026, 8))
    fabricas.honorario(sessao, cliente, valor="100.00", vencimento=date(2026, 9, 10),
                       competencia=Competencia(2026, 7))
    sessao.commit()
    primeira, segunda = servico.gerar(sessao, HOJE)
    servico.marcar_lida(sessao, primeira)
    assert servico.nao_lidas(sessao) == 1
    # as não lidas vêm antes na lista
    assert [n.lida for n in servico.listar(sessao)] == [False, True]
    assert servico.marcar_todas_lidas(sessao) == 1
    assert servico.nao_lidas(sessao) == 0

    # lidas há mais de dois meses saem da lista
    servico.limpar_antigas(sessao, agora=agora_utc() + timedelta(days=61))
    assert servico.listar(sessao) == []
