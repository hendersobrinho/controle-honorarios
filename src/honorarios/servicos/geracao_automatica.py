"""Geração automática dos honorários mensais (opcional, desligada por padrão).

Ligada nas Configurações, a partir do dia escolhido o sistema gera a competência
do mês com as mesmas regras da geração manual: contrato suspenso, fora da
vigência, de outra periodicidade ou já lançado fica de fora.

Roda **uma vez por competência**. Assim, o que for cancelado depois no Mês a mês
não volta sozinho, e um contrato criado no meio do mês entra pela geração manual
(o Mês a mês avisa o que falta). Cada geração vira uma notificação.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..dominio.enums import StatusPagamento
from ..dominio.valores import Competencia
from ..infra.modelos import Honorario, Notificacao
from . import configuracoes, contratos
from . import notificacoes as servico_notificacoes
from .honorarios import chave_competencia

LIGADA = "geracao_automatica"
DIA = "geracao_automatica_dia"
ULTIMA = "geracao_automatica_ultima"   # a última competência já tratada (aaaa-mm)
DIA_PADRAO = 1
DIA_MAXIMO = 28   # existe em todo mês


def ligada(sessao: Session) -> bool:
    return configuracoes.obter_bool(sessao, LIGADA, False)


def dia(sessao: Session) -> int:
    return min(DIA_MAXIMO, max(1, configuracoes.obter_int(sessao, DIA, DIA_PADRAO)))


def _cancelados(sessao: Session, competencia: Competencia) -> set[int]:
    """Contratos com honorário cancelado nesta competência: não se gera de novo."""
    return set(sessao.scalars(
        select(Honorario.contrato_id).where(
            Honorario.contrato_id.is_not(None),
            Honorario.competencia_chave == chave_competencia(competencia),
            Honorario.status == StatusPagamento.CANCELADO,
        )
    ).all())


def executar(sessao: Session, referencia: date) -> Notificacao | None:
    """Gera a competência do mês se for a hora; devolve a notificação do que gerou."""
    if not ligada(sessao) or referencia.day < dia(sessao):
        return None
    chave = f"{referencia.year}-{referencia.month:02d}"
    if configuracoes.obter(sessao, ULTIMA) == chave:
        return None
    competencia = Competencia(referencia.year, referencia.month)
    cancelados = _cancelados(sessao, competencia)
    itens = [item for item in contratos.previa_geracao(sessao, competencia)
             if item.contrato.id not in cancelados]
    criados = contratos.gerar(sessao, itens)
    configuracoes.gravar(sessao, ULTIMA, chave)
    if not criados:
        return None
    quantos = len(criados)
    notificacao = Notificacao(
        chave=f"geracao:{chave}",
        tipo=servico_notificacoes.GERACAO,
        titulo=f"Competência {competencia.rotulo()} gerada automaticamente: "
               f"{quantos} honorário{'s' if quantos > 1 else ''}",
        texto="Confira no Mês a mês; o que não deveria sair pode ser cancelado lá",
        tela=servico_notificacoes.TELAS[servico_notificacoes.GERACAO],
    )
    sessao.add(notificacao)
    sessao.flush()
    return notificacao
