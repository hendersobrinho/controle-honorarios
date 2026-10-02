"""Indicadores do painel.

Diferente do Dashboard da planilha, cada número diz explicitamente se olha
competência ou vencimento — a planilha antiga misturava os dois.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..dominio.enums import StatusPagamento
from ..dominio.valores import MESES_ABREVIADOS, ZERO, dinheiro, hoje
from ..infra.modelos import Cliente, Honorario, Pagamento


@dataclass
class MesPainel:
    """Um mês do ano no painel."""

    rotulo: str
    quitado: Decimal = ZERO      # do que foi emitido nesta competência, já quitado
    em_aberto: Decimal = ZERO    # do que foi emitido nesta competência, ainda em aberto
    recebido: Decimal = ZERO     # baixas registradas neste mês (caixa), de qualquer competência

    @property
    def emitido(self) -> Decimal:
        return self.quitado + self.em_aberto

    @property
    def percentual_quitado(self) -> Decimal:
        return (self.quitado / self.emitido * 100) if self.emitido else ZERO


@dataclass
class Indicadores:
    """O ano em números: o que foi emitido, o que entrou e de onde vem.

    Atraso e devedores ficam de fora: para isso existe o Ranking dos atrasados.
    """

    referencia: date
    ano: int
    emitido: Decimal = ZERO
    quitado: Decimal = ZERO            # valor original já quitado (competência do ano)
    em_aberto: Decimal = ZERO          # valor original ainda em aberto (competência do ano)
    recebido_no_caixa: Decimal = ZERO  # baixas registradas no ano
    quantidade_emitida: int = 0
    quantidade_em_aberto: int = 0
    clientes_faturados: int = 0
    meses: list[MesPainel] = field(default_factory=list)
    por_grupo: list[tuple[str, Decimal]] = field(default_factory=list)
    por_tipo_pessoa: list[tuple[str, Decimal]] = field(default_factory=list)
    # o ano anterior até o mesmo mês, para comparar
    emitido_anterior: Decimal | None = None
    recebido_anterior: Decimal | None = None
    ate_mes: int = 12

    @property
    def percentual_quitado(self) -> Decimal:
        return (self.quitado / self.emitido * 100) if self.emitido else ZERO

    @property
    def ticket_medio(self) -> Decimal:
        return dinheiro(self.emitido / self.quantidade_emitida) if self.quantidade_emitida else ZERO

    @property
    def emitido_ate_mes(self) -> Decimal:
        return sum((mes.emitido for mes in self.meses[: self.ate_mes]), start=ZERO)

    @property
    def recebido_ate_mes(self) -> Decimal:
        return sum((mes.recebido for mes in self.meses[: self.ate_mes]), start=ZERO)

    def leituras(self) -> list[str]:
        """O que os números do ano dizem, em frases curtas."""
        from ..dominio.valores import formatar_moeda

        if not self.quantidade_emitida and not self.recebido_no_caixa:
            return [f"Nenhum honorário com competência em {self.ano}."]
        frases = [
            f"Em {self.ano} foram emitidos {formatar_moeda(self.emitido)} em "
            f"{self.quantidade_emitida} honorários, para {self.clientes_faturados} "
            f"cliente(s): em média {formatar_moeda(self.ticket_medio)} por honorário.",
            f"{_pct(self.percentual_quitado)} do que foi emitido já está quitado; "
            f"{formatar_moeda(self.em_aberto)} seguem em aberto.",
        ]
        com_emissao = [mes for mes in self.meses if mes.emitido > 0]
        com_caixa = [mes for mes in self.meses if mes.recebido > 0]
        if com_caixa:
            melhor = max(com_caixa, key=lambda mes: mes.recebido)
            frases.append(
                f"O mês que mais entrou dinheiro foi {melhor.rotulo}: "
                f"{formatar_moeda(melhor.recebido)} em baixas."
            )
        # o mês corrente ainda está acontecendo: não entra na comparação de quitação
        fechados = [mes for indice, mes in enumerate(self.meses, start=1)
                    if mes.emitido > 0 and indice < self.ate_mes]
        if len(fechados) >= 2:
            pior = min(fechados, key=lambda mes: mes.percentual_quitado)
            if pior.percentual_quitado < 100:
                frases.append(
                    f"Das competências já fechadas, {pior.rotulo} é a menos quitada: "
                    f"{_pct(pior.percentual_quitado)} do emitido."
                )
        if self.por_grupo and self.emitido:
            nome, valor = self.por_grupo[0]
            frases.append(
                f"O grupo {nome} responde por {_pct(valor / self.emitido * 100)} do "
                "faturamento do ano."
            )
        if self.emitido_anterior is None and self.recebido_anterior is None and self.ano > 2000:
            frases.append(
                f"Ainda não há dados suficientes de {self.ano - 1} para comparar com o ano "
                "anterior."
            )
        if self.emitido_anterior:
            variacao = (self.emitido_ate_mes / self.emitido_anterior - 1) * 100
            sentido = "a mais" if variacao >= 0 else "a menos"
            frases.append(
                f"Até {MESES_ABREVIADOS[self.ate_mes - 1]}, foram emitidos "
                f"{_pct(abs(variacao))} {sentido} que no mesmo período de {self.ano - 1}."
            )
        if self.recebido_anterior:
            variacao = (self.recebido_ate_mes / self.recebido_anterior - 1) * 100
            sentido = "a mais" if variacao >= 0 else "a menos"
            frases.append(
                f"No caixa, entraram {_pct(abs(variacao))} {sentido} que no mesmo período "
                f"de {self.ano - 1}."
            )
        if len(com_emissao) == 0:
            frases.append("Ainda não há honorários emitidos para este ano.")
        return frases


def _pct(valor: Decimal) -> str:
    return f"{valor:.0f}%"


def _ano_de(honorario: Honorario) -> int:
    return honorario.competencia_ano or honorario.vencimento.year


def _mes_de(honorario: Honorario) -> int:
    return honorario.competencia_mes or honorario.vencimento.month


def _valido(honorario: Honorario) -> bool:
    return honorario.status not in (StatusPagamento.CANCELADO, StatusPagamento.RENEGOCIADO)


def _quitado_e_aberto(honorario: Honorario) -> tuple[Decimal, Decimal]:
    """Quanto do valor original já foi quitado e quanto ainda falta."""
    original = dinheiro(honorario.valor_original)
    if honorario.status is StatusPagamento.PAGO:
        return original, ZERO
    saldo = dinheiro(honorario.saldo_aberto if honorario.saldo_aberto is not None else original)
    return original - saldo, saldo


def _caixa_por_mes(sessao: Session, ano: int) -> dict[int, Decimal]:
    linhas = sessao.execute(
        select(func.strftime("%m", Pagamento.data), func.sum(Pagamento.valor_pago))
        .where(
            Pagamento.estornado_em.is_(None),
            func.strftime("%Y", Pagamento.data) == str(ano),
        )
        .group_by(func.strftime("%m", Pagamento.data))
    ).all()
    return {int(mes): dinheiro(Decimal(str(total or 0))) for mes, total in linhas}


def indicadores(
    sessao: Session, ano: int | None = None, referencia: date | None = None
) -> Indicadores:
    hoje_ = referencia or hoje()
    ano = ano or hoje_.year
    # no ano corrente, compara até o mês de hoje; nos anteriores, o ano todo
    ate_mes = hoje_.month if ano == hoje_.year else 12
    dados = Indicadores(referencia=hoje_, ano=ano, ate_mes=ate_mes)

    todos = list(
        sessao.scalars(
            select(Honorario).join(Cliente).where(Cliente.excluido_em.is_(None))
        )
        .unique()
        .all()
    )
    do_ano = [h for h in todos if _ano_de(h) == ano and _valido(h)]
    dados.meses = [MesPainel(rotulo) for rotulo in MESES_ABREVIADOS]

    grupos: dict[str, Decimal] = {}
    pessoas: dict[str, Decimal] = {}
    clientes: set[int] = set()
    for honorario in do_ano:
        original = dinheiro(honorario.valor_original)
        quitado, aberto = _quitado_e_aberto(honorario)
        mes = dados.meses[_mes_de(honorario) - 1]
        mes.quitado += quitado
        mes.em_aberto += aberto
        dados.emitido += original
        dados.quitado += quitado
        dados.em_aberto += aberto
        dados.quantidade_emitida += 1
        if aberto > 0:
            dados.quantidade_em_aberto += 1
        clientes.add(honorario.cliente_id)
        grupo = honorario.tipo.grupo.nome
        grupos[grupo] = grupos.get(grupo, ZERO) + original
        pessoa = honorario.cliente.tipo_pessoa.rotulo
        pessoas[pessoa] = pessoas.get(pessoa, ZERO) + original
    dados.clientes_faturados = len(clientes)
    dados.por_grupo = sorted(grupos.items(), key=lambda par: -par[1])
    dados.por_tipo_pessoa = sorted(pessoas.items(), key=lambda par: -par[1])

    caixa = _caixa_por_mes(sessao, ano)
    for numero, total in caixa.items():
        dados.meses[numero - 1].recebido = total
    dados.recebido_no_caixa = sum(caixa.values(), start=ZERO)

    # o mesmo período do ano anterior — só com dado em pelo menos metade dos meses:
    # um honorário solto no ano anterior daria "19000% a mais", que não diz nada
    minimo_de_meses = max(1, ate_mes // 2)
    anterior = [
        h for h in todos
        if _ano_de(h) == ano - 1 and _valido(h) and _mes_de(h) <= ate_mes
    ]
    if len({_mes_de(h) for h in anterior}) >= minimo_de_meses:
        dados.emitido_anterior = sum(
            (dinheiro(h.valor_original) for h in anterior), start=ZERO
        )
    caixa_anterior = {
        mes: total for mes, total in _caixa_por_mes(sessao, ano - 1).items() if mes <= ate_mes
    }
    if len(caixa_anterior) >= minimo_de_meses:
        dados.recebido_anterior = sum(caixa_anterior.values(), start=ZERO) or None
    return dados


def anos_disponiveis(sessao: Session) -> list[int]:
    anos = set(
        sessao.scalars(
            select(Honorario.competencia_ano).where(Honorario.competencia_ano.is_not(None))
        ).all()
    )
    anos.update(
        data.year
        for data in sessao.scalars(select(Honorario.vencimento)).all()
        if data is not None
    )
    anos.add(hoje().year)
    return sorted(anos, reverse=True)


__all__ = ["Indicadores", "MesPainel", "anos_disponiveis", "indicadores"]
