"""Renegociação: agrupa honorários em aberto num acordo com parcelas."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
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


@dataclass(frozen=True)
class ParcelaPrevista:
    numero: int
    vencimento: date
    valor: Decimal


def dividir(valor: Decimal, parcelas: int, primeiro_vencimento: date) -> list[ParcelaPrevista]:
    """As parcelas iguais, um mês depois da outra; a última leva a sobra dos centavos."""
    if parcelas < 1:
        return []
    total = dinheiro(valor)
    base = dinheiro(total / parcelas)
    previstas = [ParcelaPrevista(numero, somar_meses(primeiro_vencimento, numero - 1), base)
                 for numero in range(1, parcelas)]
    previstas.append(ParcelaPrevista(parcelas, somar_meses(primeiro_vencimento, parcelas - 1),
                                     total - base * (parcelas - 1)))
    return previstas


FATOR = Decimal("0.000001")


def fator_do_juros(linhas: Sequence[LinhaHonorario]) -> Decimal:
    """Quanto do juros ao dia do cliente os honorários parcelados vinham pagando:
    1 por honorário em aberto inteiro, a fração do saldo no pago em parte."""
    total = ZERO
    for linha in linhas:
        original = linha.honorario.valor_original
        if original > 0:
            total += Decimal(linha.honorario.saldo_aberto) / Decimal(original)
    return total


def fatores_das_parcelas(fator_total: Decimal, previstas) -> list[Decimal]:
    """A parte de cada parcela no juros ao dia, na proporção do valor dela."""
    soma = sum((p.valor for p in previstas), start=ZERO)
    if soma <= 0:
        return [ZERO for _ in previstas]
    return [(fator_total * p.valor / soma).quantize(FATOR) for p in previstas]


def juros_dia_calculado(cliente: Cliente, fator: Decimal, referencia: date) -> Decimal:
    """O juros ao dia de uma parcela pela regra: a fração dela no juros do cliente."""
    from . import calculo

    return calculo.taxa_vigente_em(cliente, referencia) * fator


def juros_previstos(cliente: Cliente, previstas, fatores: Sequence[Decimal],
                    desde: date, juros_dia: Decimal | None = None) -> list[Decimal]:
    """O juros que cada parcela terá no próprio vencimento, contado desde ``desde``
    (com o juros ao dia de hoje do cliente, ou com ``juros_dia`` estipulado à mão).
    Para a prévia do parcelamento."""
    from ..dominio.juros import calcular_juros_com_parciais
    from . import calculo

    taxas = calculo.taxas_do_cliente(cliente)
    resultado = []
    for prevista, fator in zip(previstas, fatores, strict=True):
        escaladas = ((calculo.taxa_fixa(juros_dia),) if juros_dia is not None else
                     tuple(replace(t, valor_dia=t.valor_dia * fator) for t in taxas))
        resultado.append(calcular_juros_com_parciais(
            vencimento=desde, data_referencia=prevista.vencimento, taxas=escaladas,
            valor_original=prevista.valor).juros)
    return resultado


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
    juros_ate_o_vencimento: bool = True,
    juros_dia: Decimal | None = None,
) -> Renegociacao:
    """``juros_ate_o_vencimento``: cada parcela corre juros desde hoje (o dia do
    parcelamento) até o vencimento dela, e depois, se atrasar. Sem isso, só depois
    do vencimento. Nos dois casos, com a fração dela do juros ao dia — ou, com
    ``juros_dia``, com esse juros ao dia estipulado à mão para cada parcela."""
    if juros_dia is not None and juros_dia < 0:
        raise ErroDeValidacao("O juros ao dia das parcelas não pode ser negativo.")
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

    # antes de os originais irem para Renegociado (saldo zero)
    fator_total = fator_do_juros(linhas)
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

    previstas = dividir(acordado, parcelas, primeiro_vencimento)
    fatores = fatores_das_parcelas(fator_total, previstas)
    for prevista, fator in zip(previstas, fatores, strict=True):
        numero, valor, vencimento = prevista.numero, prevista.valor, prevista.vencimento
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
            descricao=f"Parcelamento {acordo.id} – parcela {numero}/{parcelas}",
            observacoes=observacoes or "",
        )
        gerado = servico_honorarios.criar(sessao, dados)
        gerado.juros_fator = fator if juros_dia is None else None
        gerado.juros_dia = juros_dia
        gerado.juros_desde = acordo.data if juros_ate_o_vencimento else None
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
    sessao.add(
        LogAlteracao(
            entidade="renegociacao",
            entidade_id=acordo.id,
            acao="CANCELAR",
            resumo=f"{acordo.cliente.nome}: acordo cancelado – {motivo.strip()}",
        )
    )
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
