"""Cor com significado: vermelho = atrasado, âmbar = atenção, verde = pago."""

from __future__ import annotations

from PySide6.QtGui import QColor

from ...dominio.enums import StatusPagamento
from . import tema

_tema_atual = "claro"


def definir_tema(nome: str) -> None:
    global _tema_atual
    _tema_atual = nome


def tema_atual() -> str:
    return _tema_atual


def cor_de_atraso(dias: int, vence_em_breve: bool = False) -> QColor | None:
    if dias > 0:
        return tema.cor("atrasado", _tema_atual)
    if vence_em_breve:
        return tema.cor("atencao", _tema_atual)
    return None


def cor_de_status(status: StatusPagamento) -> QColor | None:
    if status is StatusPagamento.PAGO:
        return tema.cor("pago", _tema_atual)
    if status in (StatusPagamento.CANCELADO, StatusPagamento.RENEGOCIADO):
        return tema.cor("texto_fraco", _tema_atual)
    return None


def cor_de_linha(linha, dias_vence_em_breve: int = 5) -> QColor | None:
    """Regra única de cor usada nas tabelas de honorários."""

    atualizacao = linha.atualizacao
    suspensa = getattr(linha, "cobranca_suspensa", False)
    if suspensa and atualizacao.status is StatusPagamento.EM_ABERTO:
        return tema.cor("texto_fraco", _tema_atual)
    if atualizacao.status is StatusPagamento.PAGO:
        return tema.cor("pago", _tema_atual)
    if atualizacao.status in (StatusPagamento.CANCELADO, StatusPagamento.RENEGOCIADO):
        return tema.cor("texto_fraco", _tema_atual)
    if atualizacao.dias_atraso > 0:
        return tema.cor("atrasado", _tema_atual)
    falta = (linha.honorario.vencimento - atualizacao.data_referencia).days
    if 0 <= falta <= dias_vence_em_breve:
        return tema.cor("atencao", _tema_atual)
    if linha.promessa is not None:
        return tema.cor("atencao", _tema_atual)
    return None
