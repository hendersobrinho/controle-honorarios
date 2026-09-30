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

from ..dominio.enums import StatusPagamento, TipoPessoa
from ..dominio.valores import MESES_ABREVIADOS, ZERO, dinheiro, hoje
from ..infra.modelos import Cliente, Honorario, Pagamento
from . import calculo
from . import honorarios as servico_honorarios
from .honorarios import Filtro, LinhaHonorario


@dataclass
class Indicadores:
    referencia: date
    ano: int
    emitido: Decimal = ZERO
    pago: Decimal = ZERO
    recebido_no_caixa: Decimal = ZERO
    em_aberto: Decimal = ZERO
    juros_acumulado: Decimal = ZERO
    total_atualizado: Decimal = ZERO
    quantidade_em_aberto: int = 0
    quantidade_emitida: int = 0
    inadimplencia: Decimal = ZERO
    por_grupo: list[tuple[str, int, Decimal]] = field(default_factory=list)
    por_tipo_pessoa: list[tuple[str, int, Decimal]] = field(default_factory=list)
    por_mes: list[tuple[str, Decimal, Decimal, Decimal]] = field(default_factory=list)
    faixas_atraso: list[tuple[str, int, Decimal]] = field(default_factory=list)
    maiores_devedores: list[tuple[str, Decimal, int]] = field(default_factory=list)

    @property
    def como_dicionario(self) -> dict[str, str]:
        from ..dominio.valores import formatar_moeda

        return {
            "Ano": str(self.ano),
            "Emitido (por competência)": formatar_moeda(self.emitido),
            "Recebido (competência do ano)": formatar_moeda(self.pago),
            "Baixas registradas no ano": formatar_moeda(self.recebido_no_caixa),
            "Em aberto (valor original)": formatar_moeda(self.em_aberto),
            "Juros acumulado": formatar_moeda(self.juros_acumulado),
            "Total atualizado em aberto": formatar_moeda(self.total_atualizado),
            "Inadimplência": f"{self.inadimplencia:.1f}%",
            "Honorários em aberto": str(self.quantidade_em_aberto),
        }


FAIXAS = (("1 a 30", 1, 30), ("31 a 60", 31, 60), ("61 a 90", 61, 90), ("90+", 91, None))


def _ano_de(honorario: Honorario) -> int:
    return honorario.competencia_ano or honorario.vencimento.year


def indicadores(
    sessao: Session, ano: int | None = None, referencia: date | None = None
) -> Indicadores:
    hoje_ = referencia or hoje()
    ano = ano or hoje_.year
    dados = Indicadores(referencia=hoje_, ano=ano)

    todos = list(
        sessao.scalars(
            select(Honorario).join(Cliente).where(Cliente.excluido_em.is_(None))
        )
        .unique()
        .all()
    )
    do_ano = [h for h in todos if _ano_de(h) == ano]
    atualizacoes = calculo.atualizar_varios(do_ano, hoje_)

    for honorario in do_ano:
        if honorario.status in (StatusPagamento.CANCELADO, StatusPagamento.RENEGOCIADO):
            continue
        dados.emitido += dinheiro(honorario.valor_original)
        dados.quantidade_emitida += 1

    # mesmo eixo do resto do bloco: competência, não data de pagamento. Misturar
    # os dois eixos era o que fazia o Dashboard da planilha dar número estranho.
    dados.pago = sum(
        (
            dinheiro(h.total_congelado or h.valor_original)
            for h in do_ano
            if h.status is StatusPagamento.PAGO
        ),
        start=ZERO,
    )
    dados.recebido_no_caixa = dinheiro(
        sessao.scalar(
            select(func.coalesce(func.sum(Pagamento.valor_pago), 0)).where(
                Pagamento.estornado_em.is_(None),
                func.strftime("%Y", Pagamento.data) == str(ano),
            )
        )
        or 0
    )

    abertos = [h for h in do_ano if h.status is StatusPagamento.EM_ABERTO]
    for honorario in abertos:
        atualizacao = atualizacoes[honorario.id]
        dados.em_aberto += atualizacao.saldo
        dados.juros_acumulado += atualizacao.juros
        dados.total_atualizado += atualizacao.total
    dados.quantidade_em_aberto = len(abertos)
    if dados.emitido:
        dados.inadimplencia = (dados.em_aberto / dados.emitido * 100).quantize(Decimal("0.1"))

    # por grupo e por tipo de pessoa (em aberto atualizado)
    grupos: dict[str, list[Decimal]] = {}
    pessoas: dict[str, list[Decimal]] = {}
    for honorario in abertos:
        total = atualizacoes[honorario.id].total
        grupo = honorario.tipo.grupo.nome
        grupos.setdefault(grupo, [Decimal(0), ZERO])
        grupos[grupo][0] += 1
        grupos[grupo][1] += total
        rotulo = honorario.cliente.tipo_pessoa.rotulo
        pessoas.setdefault(rotulo, [Decimal(0), ZERO])
        pessoas[rotulo][0] += 1
        pessoas[rotulo][1] += total
    dados.por_grupo = sorted(
        ((nome, int(v[0]), v[1]) for nome, v in grupos.items()), key=lambda t: -t[2]
    )
    dados.por_tipo_pessoa = sorted(
        ((nome, int(v[0]), v[1]) for nome, v in pessoas.items()), key=lambda t: -t[2]
    )

    # por mês de competência
    for mes in range(1, 13):
        do_mes = [h for h in do_ano if (h.competencia_mes or h.vencimento.month) == mes]
        emitido = sum(
            (
                dinheiro(h.valor_original)
                for h in do_mes
                if h.status not in (StatusPagamento.CANCELADO, StatusPagamento.RENEGOCIADO)
            ),
            start=ZERO,
        )
        em_aberto = sum(
            (atualizacoes[h.id].total for h in do_mes if h.status is StatusPagamento.EM_ABERTO),
            start=ZERO,
        )
        pago = sum(
            (
                dinheiro(h.total_congelado or 0)
                for h in do_mes
                if h.status is StatusPagamento.PAGO
            ),
            start=ZERO,
        )
        dados.por_mes.append((MESES_ABREVIADOS[mes - 1], emitido, pago, em_aberto))

    # faixas de atraso e maiores devedores (visão geral, não só do ano)
    pendentes = servico_honorarios.pendentes(sessao, Filtro(data_referencia=hoje_))
    for rotulo, minimo, maximo in FAIXAS:
        na_faixa = [
            linha
            for linha in pendentes
            if linha.atualizacao.dias_atraso >= minimo
            and (maximo is None or linha.atualizacao.dias_atraso <= maximo)
        ]
        dados.faixas_atraso.append(
            (rotulo, len(na_faixa), sum((item.atualizacao.total for item in na_faixa), start=ZERO))
        )

    por_cliente: dict[int, list] = {}
    for linha in pendentes:
        atual = por_cliente.setdefault(linha.cliente.id, [linha.cliente.nome, ZERO, 0])
        atual[1] += linha.atualizacao.total
        atual[2] += 1
    dados.maiores_devedores = sorted(
        ((v[0], v[1], v[2]) for v in por_cliente.values()), key=lambda t: -t[1]
    )[:10]
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


__all__ = [
    "FAIXAS",
    "Indicadores",
    "LinhaHonorario",
    "TipoPessoa",
    "anos_disponiveis",
    "indicadores",
]
