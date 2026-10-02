"""Notificações: o que vence hoje, o que não foi pago na data, promessas e acordos.

``gerar`` olha a carteira numa data e cria os avisos que ainda não existem — a
``chave`` de cada um identifica o fato, então rodar de novo (ao abrir, a cada meia
hora) nunca duplica nada. Os avisos são por cliente, para a lista não virar uma
fila de honorários. Cliente com cobrança suspensa não gera aviso.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..dominio.valores import ZERO, agora_utc, formatar_data, formatar_moeda
from ..infra.modelos import Notificacao
from . import acordos
from . import honorarios as servico_honorarios
from .honorarios import Filtro

VENCE_HOJE = "vence_hoje"
NAO_PAGO = "nao_pago"
PROMESSA = "promessa"
ACORDO = "acordo"
GERACAO = "geracao"   # competência gerada automaticamente
EMAIL = "email"       # chegou e-mail do financeiro na pasta da conversa

# telas para onde cada aviso leva
TELAS = {VENCE_HOJE: "A vencer", NAO_PAGO: "Atrasados", PROMESSA: "Atrasados",
         ACORDO: "Atrasados", GERACAO: "Honorários",
         EMAIL: "E-mail de cobranças"}

# "não foi pago na data" avisa o que venceu nestes últimos dias: abrindo o sistema
# depois de um feriado, aparece o que venceu enquanto ele estava fechado
JANELA_NAO_PAGO = 30
MANTER_LIDAS_DIAS = 60


def _plural(quantidade: int, singular: str, plural: str) -> str:
    return f"{quantidade} {singular if quantidade == 1 else plural}"


def _total(linhas) -> str:
    return formatar_moeda(sum((linha.atualizacao.total for linha in linhas), start=ZERO))


def candidatas(sessao: Session, referencia: date) -> list[Notificacao]:
    """Os avisos que valem nesta data (ainda sem olhar se já existem)."""
    pendentes = servico_honorarios.pendentes(
        sessao, Filtro(data_referencia=referencia, incluir_cobranca_suspensa=False)
    )
    saida: list[Notificacao] = []

    # vence hoje, por cliente
    hoje_por_cliente = defaultdict(list)
    for linha in pendentes:
        if linha.honorario.vencimento == referencia:
            hoje_por_cliente[linha.cliente].append(linha)
    for cliente, linhas in hoje_por_cliente.items():
        saida.append(Notificacao(
            chave=f"vence:{cliente.id}:{referencia.isoformat()}",
            tipo=VENCE_HOJE,
            titulo=f"{cliente.nome}: "
                   f"{_plural(len(linhas), 'honorário vence', 'honorários vencem')} hoje",
            texto=_total(linhas),
            tela=TELAS[VENCE_HOJE],
            cliente_id=cliente.id,
        ))

    # não foi pago na data: por cliente e por dia de vencimento
    limite = referencia - timedelta(days=JANELA_NAO_PAGO)
    nao_pagos = defaultdict(list)
    for linha in pendentes:
        vencimento = linha.honorario.vencimento
        if limite <= vencimento < referencia:
            nao_pagos[(linha.cliente, vencimento)].append(linha)
    for (cliente, vencimento), linhas in nao_pagos.items():
        quantos = _plural(len(linhas), "honorário venceu", "honorários venceram")
        saida.append(Notificacao(
            chave=f"nao_pago:{cliente.id}:{vencimento.isoformat()}",
            tipo=NAO_PAGO,
            titulo=f"{cliente.nome}: {quantos} em {formatar_data(vencimento)} sem pagamento",
            texto=f"{_total(linhas)} com juros até hoje",
            tela=TELAS[NAO_PAGO],
            cliente_id=cliente.id,
        ))

    # promessa de pagamento que passou
    promessas = {}
    for linha in pendentes:
        if linha.promessa and linha.promessa < referencia:
            promessas[(linha.cliente, linha.promessa)] = True
    for cliente, promessa in promessas:
        saida.append(Notificacao(
            chave=f"promessa:{cliente.id}:{promessa.isoformat()}",
            tipo=PROMESSA,
            titulo=f"{cliente.nome}: prometeu pagar até {formatar_data(promessa)} e não pagou",
            texto="",
            tela=TELAS[PROMESSA],
            cliente_id=cliente.id,
        ))

    # acordo que vence hoje: depois de hoje o juros volta a correr
    for linha in pendentes:
        acordo = acordos.vigente(linha.honorario, referencia)
        if acordo is not None and acordo.valido_ate == referencia:
            saida.append(Notificacao(
                chave=f"acordo:{acordo.id}",
                tipo=ACORDO,
                titulo=f"{linha.cliente.nome}: o acordo de {formatar_moeda(acordo.total)} "
                       "vence hoje",
                texto="Sem pagamento, o juros volta a correr desde o vencimento original",
                tela=TELAS[ACORDO],
                cliente_id=linha.cliente.id,
            ))
    return saida


def gerar(sessao: Session, referencia: date) -> list[Notificacao]:
    """Cria os avisos novos desta data e devolve só os que acabaram de nascer."""
    possiveis = candidatas(sessao, referencia)
    if not possiveis:
        return []
    existentes = set(sessao.scalars(
        select(Notificacao.chave).where(Notificacao.chave.in_([n.chave for n in possiveis]))
    ).all())
    novas = []
    for notificacao in possiveis:
        if notificacao.chave not in existentes:
            existentes.add(notificacao.chave)
            sessao.add(notificacao)
            novas.append(notificacao)
    sessao.flush()
    return novas


def listar(sessao: Session, limite: int = 80) -> list[Notificacao]:
    """As mais recentes primeiro; as não lidas antes das lidas."""
    return list(sessao.scalars(
        select(Notificacao)
        .order_by(Notificacao.lida_em.is_not(None), Notificacao.criada_em.desc(),
                  Notificacao.id.desc())
        .limit(limite)
    ).all())


def nao_lidas(sessao: Session) -> int:
    return sessao.scalar(
        select(func.count(Notificacao.id)).where(Notificacao.lida_em.is_(None))
    ) or 0


def marcar_lida(sessao: Session, notificacao: Notificacao) -> None:
    if notificacao.lida_em is None:
        notificacao.lida_em = agora_utc()
        sessao.flush()


def marcar_todas_lidas(sessao: Session) -> int:
    pendentes = sessao.scalars(select(Notificacao).where(Notificacao.lida_em.is_(None))).all()
    agora = agora_utc()
    for notificacao in pendentes:
        notificacao.lida_em = agora
    sessao.flush()
    return len(pendentes)


def limpar_antigas(sessao: Session, agora: datetime | None = None) -> None:
    """Lidas há mais de dois meses saem — o histórico de verdade está nas cobranças."""
    limite = (agora or agora_utc()) - timedelta(days=MANTER_LIDAS_DIAS)
    sessao.execute(
        delete(Notificacao).where(Notificacao.lida_em.is_not(None),
                                  Notificacao.lida_em < limite)
    )
    sessao.flush()


def resumo(novas: list[Notificacao]) -> str:
    """Uma linha para o aviso do canto e para a notificação do sistema."""
    contagem = defaultdict(int)
    for notificacao in novas:
        contagem[notificacao.tipo] += 1
    partes = []
    if contagem[VENCE_HOJE]:
        partes.append(_plural(contagem[VENCE_HOJE], "cliente com vencimento hoje",
                              "clientes com vencimento hoje"))
    if contagem[NAO_PAGO]:
        partes.append(_plural(contagem[NAO_PAGO], "vencimento sem pagamento",
                              "vencimentos sem pagamento"))
    if contagem[PROMESSA]:
        partes.append(_plural(contagem[PROMESSA], "promessa não cumprida",
                              "promessas não cumpridas"))
    if contagem[EMAIL]:
        partes.append(_plural(contagem[EMAIL], "e-mail do financeiro", "e-mails do financeiro"))
    if contagem[GERACAO]:
        partes.append("competência do mês gerada automaticamente")
    if contagem[ACORDO]:
        partes.append(_plural(contagem[ACORDO], "acordo vence hoje", "acordos vencem hoje"))
    return " · ".join(partes)
