"""Renegociação: agrupa honorários em aberto num acordo com parcelas."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from ..dominio.enums import ExigeCompetencia, StatusPagamento
from ..dominio.valores import ZERO, Competencia, agora_utc, dinheiro, hoje, somar_meses
from ..infra.modelos import (
    Cliente,
    LogAlteracao,
    Renegociacao,
    RenegociacaoItem,
    TipoHonorario,
)
from . import honorarios as servico_honorarios
from .erros import ErroDeValidacao
from .honorarios import LinhaHonorario


def criar(
    sessao: Session,
    cliente: Cliente,
    linhas: Sequence[LinhaHonorario],
    valor_acordado: Decimal,
    parcelas: int,
    primeiro_vencimento: date,
    tipo_id: int,
    desconto: Decimal = ZERO,
    observacoes: str = "",
) -> Renegociacao:
    if not linhas:
        raise ErroDeValidacao("Selecione os honorários que entram no acordo.")
    if parcelas < 1:
        raise ErroDeValidacao("O acordo precisa de pelo menos uma parcela.", "parcelas")
    acordado = dinheiro(valor_acordado)
    if acordado <= 0:
        raise ErroDeValidacao("O valor acordado deve ser maior que zero.", "valor_acordado")
    for linha in linhas:
        if not linha.honorario.status.cobravel:
            raise ErroDeValidacao(
                f"{linha.honorario.tipo.nome} {linha.honorario.competencia_rotulo} está "
                f"{linha.honorario.status.rotulo.lower()} e não entra em acordo."
            )

    total_original = sum((linha.atualizacao.valor_original for linha in linhas), start=ZERO)
    juros = sum((linha.atualizacao.juros for linha in linhas), start=ZERO)

    acordo = Renegociacao(
        cliente_id=cliente.id,
        data=hoje(),
        valor_original_total=total_original,
        juros_incluidos=juros,
        desconto=dinheiro(desconto),
        valor_acordado=acordado,
        parcelas=parcelas,
        observacoes=observacoes or "",
    )
    sessao.add(acordo)
    sessao.flush()

    for linha in linhas:
        honorario = linha.honorario
        honorario.status = StatusPagamento.RENEGOCIADO
        honorario.saldo_aberto = ZERO
        honorario.renegociacao_id = acordo.id
        acordo.itens.append(
            RenegociacaoItem(
                honorario_origem_id=honorario.id, valor=linha.atualizacao.total
            )
        )

    tipo = sessao.get(TipoHonorario, tipo_id)
    if tipo is None:
        raise ErroDeValidacao("Escolha o tipo de honorário das parcelas.", "tipo")

    valor_parcela = dinheiro(acordado / parcelas)
    restante = acordado
    for numero in range(1, parcelas + 1):
        valor = valor_parcela if numero < parcelas else dinheiro(restante)
        restante -= valor
        vencimento = somar_meses(primeiro_vencimento, numero - 1)
        # a parcela só recebe competência se o tipo escolhido exigir uma
        if tipo.exige_competencia is ExigeCompetencia.MES:
            competencia = Competencia(vencimento.year, vencimento.month)
        elif tipo.exige_competencia is ExigeCompetencia.ANO:
            competencia = Competencia(vencimento.year)
        else:
            competencia = Competencia()
        dados = servico_honorarios.DadosHonorario(
            cliente_id=cliente.id,
            tipo_id=tipo_id,
            valor=valor,
            vencimento=vencimento,
            competencia=competencia,
            descricao=f"Acordo {acordo.id} – parcela {numero}/{parcelas}",
            observacoes=observacoes or "",
        )
        gerado = servico_honorarios.criar(sessao, dados)
        acordo.itens.append(RenegociacaoItem(honorario_gerado_id=gerado.id, valor=valor))

    sessao.add(
        LogAlteracao(
            entidade="renegociacao",
            entidade_id=acordo.id,
            acao="CRIAR",
            resumo=(
                f"{cliente.nome}: {len(linhas)} honorário(s) renegociado(s) em "
                f"{parcelas} parcela(s)"
            ),
        )
    )
    sessao.flush()
    return acordo


def cancelar(sessao: Session, acordo: Renegociacao, motivo: str) -> None:
    """Cancela o acordo e devolve os honorários originais para Em aberto."""
    if not (motivo or "").strip():
        raise ErroDeValidacao("Descreva o motivo do cancelamento do acordo.", "motivo")
    from ..infra.modelos import Honorario

    acordo.cancelada_em = agora_utc()
    for item in acordo.itens:
        if item.honorario_origem_id:
            honorario = sessao.get(Honorario, item.honorario_origem_id)
            if honorario is not None:
                honorario.status = StatusPagamento.EM_ABERTO
                honorario.saldo_aberto = honorario.valor_original
                honorario.renegociacao_id = None
        if item.honorario_gerado_id:
            gerado = sessao.get(Honorario, item.honorario_gerado_id)
            if gerado is not None and gerado.status is StatusPagamento.EM_ABERTO:
                servico_honorarios.cancelar(
                    sessao, gerado, f"Acordo cancelado: {motivo.strip()}"
                )
    sessao.flush()
