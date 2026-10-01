"""Rankings de clientes: quem mais deve, há mais tempo, com mais boletos e mais cobrado.

Tudo sai de uma leitura só dos honorários em aberto (mais a contagem de
cobranças), e cada ranking traz uma curiosidade para a tela ficar leve.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..dominio.valores import ZERO, formatar_data, formatar_moeda, hoje
from ..infra.modelos import Cliente, CobrancaLote
from . import honorarios as servico_honorarios
from .honorarios import Filtro, LinhaHonorario


@dataclass
class ItemRanking:
    cliente: Cliente
    valor: float                 # tamanho da barra
    rotulo: str                  # o número que aparece na barra
    detalhe: str = ""            # linha pequena embaixo do nome


@dataclass
class Ranking:
    chave: str
    titulo: str
    subtitulo: str
    itens: list[ItemRanking] = field(default_factory=list)
    curiosidade: str = ""
    vazio: str = "Ninguém por aqui. 🎉"


def _plural(quantidade: int, singular: str, plural: str) -> str:
    return f"{quantidade} {singular if quantidade == 1 else plural}"


def _tempo_por_extenso(dias: int) -> str:
    if dias < 31:
        return _plural(dias, "dia", "dias")
    meses = dias // 30
    if meses < 12:
        return "≈ " + _plural(meses, "mês", "meses")
    anos, resto = divmod(meses, 12)
    texto = "≈ " + _plural(anos, "ano", "anos")
    return texto + (" e " + _plural(resto, "mês", "meses") if resto else "")


def _por_cliente(linhas: list[LinhaHonorario]) -> dict[int, list[LinhaHonorario]]:
    grupos: dict[int, list[LinhaHonorario]] = defaultdict(list)
    for linha in linhas:
        grupos[linha.cliente.id].append(linha)
    return grupos


def maiores_devedores(grupos, limite: int) -> Ranking:
    totais = sorted(
        (
            (itens[0].cliente, servico_honorarios.total_de(itens), itens)
            for itens in grupos.values()
        ),
        key=lambda par: par[1],
        reverse=True,
    )
    itens = [
        ItemRanking(
            cliente=cliente,
            valor=float(total),
            rotulo=formatar_moeda(total),
            detalhe=(
                f"{_plural(len(linhas), 'honorário', 'honorários')} · juros "
                f"{formatar_moeda(sum((linha.atualizacao.juros for linha in linhas), start=ZERO))}"
            ),
        )
        for cliente, total, linhas in totais[:limite]
    ]
    curiosidade = ""
    if len(totais) >= 2:
        geral = sum((total for _, total, _ in totais), start=ZERO)
        primeiro = totais[0][1]
        seguintes = sum((total for _, total, _ in totais[1:4]), start=ZERO)
        if primeiro > seguintes and len(totais) >= 4:
            curiosidade = (
                f"🏆 O primeiro lugar deve mais que o 2º, o 3º e o 4º juntos "
                f"({formatar_moeda(primeiro)} × {formatar_moeda(seguintes)})."
            )
        elif geral:
            fatia = sum((total for _, total, _ in totais[:3]), start=ZERO) / geral * 100
            curiosidade = (
                f"🍕 Os 3 primeiros ficam com {fatia:.0f}% de todo o valor em aberto "
                f"({formatar_moeda(geral)})."
            )
    return Ranking(
        chave="devedores",
        titulo="💸 Quem mais deve",
        subtitulo="Total em aberto com juros até hoje",
        itens=itens,
        curiosidade=curiosidade,
        vazio="Ninguém devendo. Dia de festa! 🎉",
    )


def devendo_ha_mais_tempo(grupos, limite: int, referencia: date) -> Ranking:
    maiores = sorted(
        (
            (
                itens[0].cliente,
                max(linha.atualizacao.dias_atraso for linha in itens),
                min(linha.honorario.vencimento for linha in itens),
            )
            for itens in grupos.values()
        ),
        key=lambda par: par[1],
        reverse=True,
    )
    maiores = [par for par in maiores if par[1] > 0]
    itens = [
        ItemRanking(
            cliente=cliente,
            valor=float(dias),
            rotulo=f"{dias} dias",
            detalhe=f"desde {formatar_data(vencimento)} · {_tempo_por_extenso(dias)}",
        )
        for cliente, dias, vencimento in maiores[:limite]
    ]
    curiosidade = ""
    if maiores:
        cliente, dias, vencimento = maiores[0]
        horas = f"{dias * 24:,}".replace(",", ".")
        curiosidade = (
            f"⏳ O boleto mais antigo venceu em {formatar_data(vencimento)} — "
            f"{_tempo_por_extenso(dias)} esperando, {horas} horas no relógio."
        )
    return Ranking(
        chave="tempo",
        titulo="⏳ Devendo há mais tempo",
        subtitulo="Dias desde o vencimento mais antigo em aberto",
        itens=itens,
        curiosidade=curiosidade,
        vazio="Nenhum atraso. O tempo está do nosso lado! ⏰",
    )


def mais_honorarios_em_aberto(grupos, limite: int) -> Ranking:
    contagem = sorted(
        (
            (itens[0].cliente, len(itens), servico_honorarios.total_de(itens))
            for itens in grupos.values()
        ),
        key=lambda par: (par[1], par[2]),
        reverse=True,
    )
    itens = [
        ItemRanking(
            cliente=cliente,
            valor=float(quantidade),
            rotulo=_plural(quantidade, "boleto", "boletos"),
            detalhe=f"somando {formatar_moeda(total)}",
        )
        for cliente, quantidade, total in contagem[:limite]
    ]
    curiosidade = ""
    if contagem:
        top3 = sum(quantidade for _, quantidade, _ in contagem[:3])
        geral = sum(quantidade for _, quantidade, _ in contagem)
        curiosidade = (
            f"📚 Os 3 maiores colecionadores juntam {top3} dos {geral} boletos em aberto."
        )
    return Ranking(
        chave="honorarios",
        titulo="📚 Colecionadores de boletos",
        subtitulo="Mais honorários em aberto ao mesmo tempo",
        itens=itens,
        curiosidade=curiosidade,
        vazio="Nenhum boleto acumulado. Coleção vazia! 🗂️",
    )


def mais_cobrados(sessao: Session, limite: int) -> Ranking:
    """Cada mensagem enviada conta uma tentativa (não cada honorário dentro dela)."""
    tentativas: dict[int, list[CobrancaLote]] = defaultdict(list)
    lotes = sessao.scalars(
        select(CobrancaLote).join(Cliente).where(Cliente.excluido_em.is_(None))
    ).unique()
    for lote in lotes:
        if any(cobranca.ativa for cobranca in lote.cobrancas):
            tentativas[lote.cliente_id].append(lote)
    ordenados = sorted(tentativas.values(), key=len, reverse=True)
    itens = []
    for lista in ordenados[:limite]:
        ultima = max(lote.data_hora for lote in lista)
        itens.append(
            ItemRanking(
                cliente=lista[0].cliente,
                valor=float(len(lista)),
                rotulo=_plural(len(lista), "tentativa", "tentativas"),
                detalhe=f"última em {formatar_data(ultima)}",
            )
        )
    curiosidade = ""
    if ordenados:
        total = sum(len(lista) for lista in ordenados)
        media = total / len(ordenados)
        media_texto = f"{media:.1f}".replace(".", ",")
        curiosidade = (
            f"📞 {_plural(total, 'tentativa registrada', 'tentativas registradas')} "
            f"no total — média de "
            f"{media_texto} por cliente cobrado."
        )
    return Ranking(
        chave="cobrados",
        titulo="📞 Os mais procurados",
        subtitulo="Mais tentativas de cobrança registradas",
        itens=itens,
        curiosidade=curiosidade,
        vazio="Ninguém cobrado ainda. Telefone em silêncio. 🤫",
    )


def calcular(
    sessao: Session, referencia: date | None = None, limite: int = 10
) -> dict[str, Ranking]:
    dia = referencia or hoje()
    pendentes = servico_honorarios.pendentes(sessao, Filtro(data_referencia=dia))
    grupos = _por_cliente(pendentes)
    return {
        "devedores": maiores_devedores(grupos, limite),
        "tempo": devendo_ha_mais_tempo(grupos, limite, dia),
        "honorarios": mais_honorarios_em_aberto(grupos, limite),
        "cobrados": mais_cobrados(sessao, limite),
    }


__all__ = ["ItemRanking", "Ranking", "Decimal", "calcular"]
