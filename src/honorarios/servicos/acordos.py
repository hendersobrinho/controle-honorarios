"""Acordo de valor: "pague R$ X até tal data".

O valor é o do honorário atualizado numa data (``data_base``) e vale até o
vencimento do acordo. Pagando dentro do prazo, a baixa sugere esse valor (o juros
congelado). Passado o prazo, o acordo não vale mais e o juros volta a correr
desde o vencimento original — nada precisa ser desfeito.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlalchemy.orm import Session

from ..dominio.enums import StatusPagamento
from ..dominio.valores import dinheiro, formatar_data, formatar_moeda
from ..infra.modelos import AcordoValor, Honorario
from . import calculo
from .erros import ErroDeValidacao


def registrar(
    sessao: Session, honorarios: Sequence[Honorario], data_base: date, valido_ate: date
) -> list[AcordoValor]:
    """Um acordo por honorário, com o valor de ``data_base`` válido até ``valido_ate``."""
    if valido_ate < data_base:
        raise ErroDeValidacao("O acordo não pode vencer antes da data dos valores.")
    criados = []
    for honorario in honorarios:
        if honorario.status is not StatusPagamento.EM_ABERTO:
            raise ErroDeValidacao(
                f"{honorario.tipo.nome} {honorario.competencia_rotulo} não está em aberto."
            )
        atual = calculo.atualizar(honorario, data_base)
        acordo = AcordoValor(
            data_base=data_base,
            valido_ate=valido_ate,
            saldo=atual.saldo,
            juros=atual.juros,
            total=atual.total,
        )
        honorario.acordos.append(acordo)
        criados.append(acordo)
    sessao.flush()
    return criados


def vigente(honorario: Honorario, data: date) -> AcordoValor | None:
    """O acordo que vale para pagar nesta data — o mais recente, se houver mais de um.

    Só vale enquanto o saldo for o mesmo de quando o acordo foi feito: um pagamento
    parcial no meio do caminho muda a conta, e aí o acordo deixa de se aplicar.
    """
    saldo = dinheiro(honorario.saldo_aberto)
    validos = [
        acordo for acordo in honorario.acordos
        if acordo.data_base <= data <= acordo.valido_ate and dinheiro(acordo.saldo) == saldo
    ]
    return max(validos, key=lambda acordo: acordo.criado_em, default=None)


def descricao(acordo: AcordoValor) -> str:
    return (
        f"Pago dentro do acordo: {formatar_moeda(acordo.total)} (valores de "
        f"{formatar_data(acordo.data_base)}) válido até {formatar_data(acordo.valido_ate)}."
    )
