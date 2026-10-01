"""Análise de juros: o valor original contra o que de fato foi pago.

Serve para uma decisão: vale aumentar o juros? Para isso não basta saber quanto
entrou de juros — é preciso saber quanto do juros devido foi realmente cobrado
(se boa parte é abonada, aumentar a taxa não muda a receita) e quanto um aumento
renderia daqui para frente, sem mexer no que já correu (a mudança de taxa nunca
é retroativa).

Só entram pagamentos registrados no sistema: os honorários importados da
planilha antiga não têm valor pago nem data, então não dizem nada sobre juros.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..dominio.enums import StatusPagamento
from ..dominio.valores import MESES_ABREVIADOS, ZERO, dinheiro, formatar_moeda, hoje
from ..infra.modelos import Cliente, Honorario, Pagamento
from . import calculo
from . import honorarios as servico_honorarios
from .honorarios import Filtro
from .rankings import ItemRanking, Ranking


@dataclass
class HonorarioPago:
    """Um honorário quitado, com o que foi devido, cobrado e abonado."""

    honorario: Honorario
    original: Decimal
    pago: Decimal
    juros_devidos: Decimal
    juros_cobrados: Decimal
    abono: Decimal
    dias_atraso: int
    pago_em: date
    # cada mensagem enviada é uma tentativa, como no ranking "mais cobrados":
    # uma mensagem com três honorários conta uma vez para o cliente
    tentativas: frozenset = frozenset()

    @property
    def cliente(self) -> Cliente:
        return self.honorario.cliente

    @property
    def cobrancas(self) -> int:
        return len(self.tentativas)

    @property
    def com_atraso(self) -> bool:
        return self.dias_atraso > 0


@dataclass
class AtrasadoHoje:
    """Um honorário em atraso na data da análise."""

    honorario: Honorario
    dias_atraso: int
    saldo: Decimal
    juros_ate_hoje: Decimal
    juros_por_dia: Decimal     # taxa vigente × saldo/original
    total: Decimal
    cobrancas: int


@dataclass
class CarteiraHoje:
    """O que o cliente tem em atraso na data da análise."""

    quantidade: int = 0
    juros_por_dia: Decimal = ZERO
    maior_atraso: int = 0
    tentativas: set = field(default_factory=set)
    honorarios: list[AtrasadoHoje] = field(default_factory=list)

    @property
    def cobrancas(self) -> int:
        return len(self.tentativas)


def _tentativas(honorario: Honorario) -> frozenset:
    return frozenset(
        ("lote", cobranca.lote_id) if cobranca.lote_id else ("avulsa", cobranca.id)
        for cobranca in honorario.cobrancas
        if cobranca.ativa
    )


@dataclass
class Mes:
    rotulo: str
    original: Decimal = ZERO
    juros: Decimal = ZERO
    abono: Decimal = ZERO

    @property
    def percentual(self) -> Decimal:
        return (self.juros / self.original * 100) if self.original else ZERO


@dataclass
class AnaliseJuros:
    desde: date | None
    ate: date
    honorarios: list[HonorarioPago] = field(default_factory=list)
    meses: list[Mes] = field(default_factory=list)
    # juros que a carteira em aberto soma por dia hoje (base da simulação)
    juros_por_dia_hoje: Decimal = ZERO
    ranking_juros: Ranking | None = None
    ranking_acrescimo: Ranking | None = None
    ranking_trabalho: Ranking | None = None
    ranking_tempo: Ranking | None = None
    # por cliente: o que está atrasado hoje
    carteira: dict[int, CarteiraHoje] = field(default_factory=dict)
    # preenchido quando a análise é de um cliente só
    cliente: Cliente | None = None
    taxa_atual: Decimal | None = None
    geral: AnaliseJuros | None = None   # para comparar o cliente com a média

    # ------------------------------------------------------------- totais
    @property
    def atrasados(self) -> list[HonorarioPago]:
        return [item for item in self.honorarios if item.com_atraso]

    @property
    def original(self) -> Decimal:
        return sum((item.original for item in self.honorarios), start=ZERO)

    @property
    def recebido(self) -> Decimal:
        return sum((item.pago for item in self.honorarios), start=ZERO)

    @property
    def juros_cobrados(self) -> Decimal:
        return sum((item.juros_cobrados for item in self.honorarios), start=ZERO)

    @property
    def juros_devidos(self) -> Decimal:
        return sum((item.juros_devidos for item in self.honorarios), start=ZERO)

    @property
    def abono(self) -> Decimal:
        return sum((item.abono for item in self.honorarios), start=ZERO)

    @property
    def original_dos_atrasados(self) -> Decimal:
        return sum((item.original for item in self.atrasados), start=ZERO)

    @property
    def percentual_com_atraso(self) -> Decimal:
        if not self.honorarios:
            return ZERO
        return Decimal(len(self.atrasados)) / len(self.honorarios) * 100

    @property
    def atraso_medio(self) -> Decimal:
        if not self.atrasados:
            return ZERO
        return Decimal(sum(item.dias_atraso for item in self.atrasados)) / len(self.atrasados)

    @property
    def acrescimo_sobre_atrasados(self) -> Decimal:
        """De cada R$ 100 pagos com atraso, quanto veio de juros."""
        if not self.original_dos_atrasados:
            return ZERO
        return self.juros_cobrados / self.original_dos_atrasados * 100

    @property
    def percentual_abonado(self) -> Decimal:
        if not self.juros_devidos:
            return ZERO
        return self.abono / self.juros_devidos * 100

    def _base_mensal(self) -> Decimal:
        """Valor original × meses de atraso: a base sobre a qual o juros correu."""
        return sum(
            (item.original * Decimal(item.dias_atraso) / 30 for item in self.atrasados),
            start=ZERO,
        )

    @property
    def taxa_mensal_efetiva(self) -> Decimal | None:
        """Juros recebido, em % ao mês sobre o valor atrasado."""
        base = self._base_mensal()
        return (self.juros_cobrados / base * 100) if base else None

    @property
    def taxa_mensal_cadastrada(self) -> Decimal | None:
        """O que a taxa cadastrada daria, em % ao mês, se nada fosse abonado."""
        base = self._base_mensal()
        return (self.juros_devidos / base * 100) if base else None

    @property
    def quantidade_meses(self) -> int:
        return max(1, len(self.meses))

    @property
    def maior_atraso(self) -> int:
        return max((item.dias_atraso for item in self.honorarios), default=0)

    @property
    def valor_medio(self) -> Decimal:
        if not self.honorarios:
            return ZERO
        return dinheiro(self.original / len(self.honorarios))

    @property
    def acrescimo(self) -> Decimal:
        """Quanto o total pago passou do original, em %."""
        return (self.juros_cobrados / self.original * 100) if self.original else ZERO

    # ------------------------------------------------ o trabalho para receber
    @property
    def cobrancas(self) -> int:
        """Tentativas de cobrança dos honorários pagos no período."""
        tentativas: set = set()
        for item in self.honorarios:
            tentativas |= item.tentativas
        return len(tentativas)

    @property
    def dias_em_atraso(self) -> int:
        """Soma dos dias de atraso de todos os honorários pagos no período."""
        return sum(item.dias_atraso for item in self.honorarios)

    @property
    def cobrancas_por_atrasado(self) -> Decimal:
        if not self.atrasados:
            return ZERO
        return Decimal(self.cobrancas) / len(self.atrasados)

    @property
    def juros_por_cobranca(self) -> Decimal | None:
        return (self.juros_cobrados / self.cobrancas) if self.cobrancas else None

    @property
    def hoje(self) -> CarteiraHoje:
        """A carteira atrasada de hoje somada (de um cliente ou de todos)."""
        total = CarteiraHoje()
        for parte in self.carteira.values():
            total.quantidade += parte.quantidade
            total.juros_por_dia += parte.juros_por_dia
            total.maior_atraso = max(total.maior_atraso, parte.maior_atraso)
            total.tentativas |= parte.tentativas
            total.honorarios += parte.honorarios
        total.honorarios.sort(key=lambda atrasado: atrasado.dias_atraso, reverse=True)
        return total

    @property
    def trabalho(self) -> tuple:
        """Chave para ordenar por "quem deu mais trabalho"."""
        return (self.cobrancas + self.hoje.cobrancas, len(self.atrasados), self.dias_em_atraso)

    # ----------------------------------------------------------- por cliente
    def clientes(self) -> list[AnaliseJuros]:
        """Uma análise por cliente que pagou no período."""
        grupos: dict[int, list[HonorarioPago]] = defaultdict(list)
        for item in self.honorarios:
            grupos[item.cliente.id].append(item)
        return [self._recorte(itens) for itens in grupos.values()]

    def do_cliente(self, cliente_id: int) -> AnaliseJuros | None:
        itens = [item for item in self.honorarios if item.cliente.id == cliente_id]
        return self._recorte(itens) if itens else None

    def _recorte(self, itens: list[HonorarioPago]) -> AnaliseJuros:
        cliente = itens[0].cliente
        carteira = {cliente.id: self.carteira[cliente.id]} if cliente.id in self.carteira else {}
        return AnaliseJuros(
            desde=self.desde,
            ate=self.ate,
            honorarios=sorted(itens, key=lambda item: item.pago_em, reverse=True),
            meses=_por_mes(itens),
            juros_por_dia_hoje=sum((c.juros_por_dia for c in carteira.values()), start=ZERO),
            carteira=carteira,
            cliente=cliente,
            taxa_atual=calculo.taxa_vigente_em(cliente, self.ate),
            geral=self,
        )

    # ---------------------------------------------------------- simulação
    def simular(self, aumento_percentual: Decimal) -> dict[str, Decimal]:
        """Quanto um aumento de juros renderia, com o mesmo comportamento de hoje.

        * ``no_periodo``: se a taxa fosse maior no período analisado, com os
          mesmos atrasos e a mesma proporção de abono;
        * ``por_mes``: o mesmo, na média mensal;
        * ``carteira_por_mes``: quanto a carteira atrasada de hoje passaria a
          render a mais por mês — só para frente, porque a mudança de taxa não
          alcança o juros que já correu.
        """
        fator = Decimal(aumento_percentual) / 100
        no_periodo = dinheiro(self.juros_cobrados * fator)
        return {
            "no_periodo": no_periodo,
            "por_mes": dinheiro(no_periodo / self.quantidade_meses),
            "carteira_por_mes": dinheiro(self.juros_por_dia_hoje * 30 * fator),
        }

    # ------------------------------------------------------------ leituras
    def leituras(self) -> list[str]:
        """Frases curtas com o que os números mostram. Não decidem por ninguém."""
        if not self.honorarios:
            return []
        frases = []
        if self.atrasados:
            frases.append(
                f"{len(self.atrasados)} de {len(self.honorarios)} honorários "
                f"({percentual(self.percentual_com_atraso, 0)}) foram pagos com atraso, "
                f"em média {self.atraso_medio:.0f} dias depois do vencimento."
            )
            frases.append(
                f"De cada R$ 100 pagos com atraso, entraram "
                f"{formatar_moeda(self.acrescimo_sobre_atrasados)} de juros."
            )
            if self.cobrancas:
                frases.append(
                    f"Para receber esses {len(self.atrasados)} honorários atrasados foram "
                    f"feitas {self.cobrancas} cobranças "
                    f"({_decimal(self.cobrancas_por_atrasado)} por honorário), somando "
                    f"{self.dias_em_atraso} dias de atraso. Cada cobrança rendeu em média "
                    f"{formatar_moeda(self.juros_por_cobranca)} de juros."
                )
        else:
            frases.append("Todos os honorários do período foram pagos em dia.")
        efetiva, cadastrada = self.taxa_mensal_efetiva, self.taxa_mensal_cadastrada
        if efetiva is not None and cadastrada is not None:
            frases.append(
                f"O juros recebido equivale a {percentual(efetiva, 2)} ao mês sobre o valor "
                f"atrasado; a taxa cadastrada daria {percentual(cadastrada, 2)} ao mês."
            )
        if self.abono > 0:
            frase = (
                f"{formatar_moeda(self.abono)} de juros foram abonados "
                f"({percentual(self.percentual_abonado, 0)} do que era devido)."
            )
            if self.percentual_abonado >= 25:
                frase += (
                    " Antes de aumentar a taxa, vale olhar os abonos: aumentar o que "
                    "não é cobrado não muda a receita."
                )
            frases.append(frase)
        elif self.juros_devidos > 0:
            frases.append("Nenhum juros foi abonado: a taxa está sendo cobrada inteira.")
        if self.juros_cobrados > 0:
            por_cliente: dict[int, Decimal] = defaultdict(lambda: ZERO)
            for item in self.honorarios:
                por_cliente[item.cliente.id] += item.juros_cobrados
            ordenados = sorted(por_cliente.values(), reverse=True)
            acumulado, clientes = ZERO, 0
            for valor in ordenados:
                acumulado += valor
                clientes += 1
                if acumulado >= self.juros_cobrados / 2:
                    break
            frases.append(
                f"Metade dos juros recebidos veio de {clientes} cliente(s), de "
                f"{len(por_cliente)} que pagaram juros."
            )
        return frases


def percentual(valor: Decimal, casas: int = 1) -> str:
    """Percentual no formato brasileiro: 1,64%."""
    return f"{valor:.{casas}f}%".replace(".", ",")


def _dias(quantidade: int) -> str:
    return f"{quantidade} dia" if quantidade == 1 else f"{quantidade} dias"


def _decimal(valor: Decimal, casas: int = 1) -> str:
    return f"{valor:.{casas}f}".replace(".", ",")


PERIODOS = (
    ("Últimos 3 meses", 3),
    ("Últimos 6 meses", 6),
    ("Últimos 12 meses", 12),
    ("Tudo", None),
)


def _honorarios_pagos(
    sessao: Session, desde: date | None, ate: date
) -> list[HonorarioPago]:
    consulta = (
        select(Honorario)
        .join(Cliente)
        .where(
            Honorario.status == StatusPagamento.PAGO,
            Honorario.pago_em.is_not(None),
            Honorario.pago_em <= ate,
            Cliente.excluido_em.is_(None),
        )
    )
    if desde is not None:
        consulta = consulta.where(Honorario.pago_em >= desde)

    saida = []
    for honorario in sessao.scalars(consulta).unique():
        pagamentos: list[Pagamento] = [p for p in honorario.pagamentos if p.ativo]
        if not pagamentos:  # importado da planilha: sem registro do que foi pago
            continue
        saida.append(
            HonorarioPago(
                honorario=honorario,
                original=dinheiro(honorario.valor_original),
                pago=sum((dinheiro(p.valor_pago) for p in pagamentos), start=ZERO),
                juros_devidos=sum((dinheiro(p.juros_devidos) for p in pagamentos), start=ZERO),
                juros_cobrados=sum((dinheiro(p.juros_cobrados) for p in pagamentos), start=ZERO),
                abono=sum((dinheiro(p.desconto) for p in pagamentos), start=ZERO),
                dias_atraso=max(p.dias_atraso for p in pagamentos),
                pago_em=honorario.pago_em,
                tentativas=_tentativas(honorario),
            )
        )
    return saida


def _por_mes(itens: list[HonorarioPago]) -> list[Mes]:
    meses: dict[tuple[int, int], Mes] = {}
    for item in itens:
        chave = (item.pago_em.year, item.pago_em.month)
        if chave not in meses:
            meses[chave] = Mes(f"{MESES_ABREVIADOS[chave[1] - 1]}/{str(chave[0])[-2:]}")
        mes = meses[chave]
        mes.original += item.original
        mes.juros += item.juros_cobrados
        mes.abono += item.abono
    return [meses[chave] for chave in sorted(meses)]


def _carteira_atrasada(sessao: Session, referencia: date) -> dict[int, CarteiraHoje]:
    """Por cliente: o que está atrasado hoje, o juros que soma por dia e as cobranças."""
    carteira: dict[int, CarteiraHoje] = {}
    atrasados = servico_honorarios.pendentes(
        sessao, Filtro(data_referencia=referencia, atraso_minimo=1)
    )
    for linha in atrasados:
        taxa = calculo.taxa_vigente_em(linha.cliente, referencia)
        original = linha.atualizacao.valor_original
        proporcao = (linha.atualizacao.saldo / original) if original else ZERO
        tentativas = _tentativas(linha.honorario)
        parte = carteira.setdefault(linha.cliente.id, CarteiraHoje())
        parte.quantidade += 1
        parte.juros_por_dia += taxa * proporcao
        parte.maior_atraso = max(parte.maior_atraso, linha.atualizacao.dias_atraso)
        parte.tentativas |= tentativas
        parte.honorarios.append(
            AtrasadoHoje(
                honorario=linha.honorario,
                dias_atraso=linha.atualizacao.dias_atraso,
                saldo=linha.atualizacao.saldo,
                juros_ate_hoje=linha.atualizacao.juros,
                juros_por_dia=taxa * proporcao,
                total=linha.atualizacao.total,
                cobrancas=len(tentativas),
            )
        )
    return carteira


def _rankings(itens: list[HonorarioPago], limite: int) -> tuple[Ranking, Ranking]:
    juros: dict[int, list[HonorarioPago]] = defaultdict(list)
    for item in itens:
        juros[item.cliente.id].append(item)

    def soma(lista, campo):
        return sum((getattr(item, campo) for item in lista), start=ZERO)

    total_juros = sum((item.juros_cobrados for item in itens), start=ZERO)

    por_valor = sorted(
        (lista for lista in juros.values() if soma(lista, "juros_cobrados") > 0),
        key=lambda lista: soma(lista, "juros_cobrados"),
        reverse=True,
    )
    ranking_juros = Ranking(
        chave="juros_pagos",
        titulo="Quem mais pagou de juros",
        subtitulo="Juros efetivamente recebidos no período",
        itens=[
            ItemRanking(
                cliente=lista[0].cliente,
                valor=float(soma(lista, "juros_cobrados")),
                rotulo=formatar_moeda(soma(lista, "juros_cobrados")),
                detalhe=(
                    f"original {formatar_moeda(soma(lista, 'original'))} · "
                    f"{sum(1 for i in lista if i.com_atraso)} com atraso"
                ),
            )
            for lista in por_valor[:limite]
        ],
        vazio="Ninguém pagou juros no período.",
    )
    if por_valor:
        primeiro = por_valor[0]
        ranking_juros.curiosidade = (
            f"{primeiro[0].cliente.nome} sozinho pagou "
            f"{formatar_moeda(soma(primeiro, 'juros_cobrados'))} de juros — "
            f"{percentual(soma(primeiro, 'juros_cobrados') / total_juros * 100, 0)} "
            "de tudo que entrou de juros."
        )

    def acrescimo(lista):
        original = soma(lista, "original")
        return (soma(lista, "juros_cobrados") / original * 100) if original else ZERO

    por_percentual = sorted(
        (lista for lista in juros.values() if soma(lista, "juros_cobrados") > 0),
        key=acrescimo,
        reverse=True,
    )
    ranking_acrescimo = Ranking(
        chave="acrescimo",
        titulo="Maior acréscimo sobre o original",
        subtitulo="Quanto o que foi pago passou do valor original, em %",
        itens=[
            ItemRanking(
                cliente=lista[0].cliente,
                valor=float(acrescimo(lista)),
                rotulo="+" + percentual(acrescimo(lista), 2),
                detalhe=(
                    f"{formatar_moeda(soma(lista, 'original'))} → "
                    f"{formatar_moeda(soma(lista, 'pago'))}"
                ),
            )
            for lista in por_percentual[:limite]
        ],
        vazio="Ninguém pagou acima do original no período.",
    )
    if por_percentual:
        primeiro = por_percentual[0]
        extra = acrescimo(primeiro)
        ranking_acrescimo.curiosidade = (
            f"Para cada R$ 100 de honorário, {primeiro[0].cliente.nome} acabou "
            f"pagando {formatar_moeda(100 + extra)}."
        )
    return ranking_juros, ranking_acrescimo


def _rankings_de_trabalho(
    itens: list[HonorarioPago], limite: int
) -> tuple[Ranking, Ranking]:
    """Quem precisou de mais cobranças e quem ficou mais tempo em atraso para pagar."""
    por_cliente: dict[int, list[HonorarioPago]] = defaultdict(list)
    for item in itens:
        por_cliente[item.cliente.id].append(item)

    def cobrancas(lista) -> int:
        tentativas: set = set()
        for item in lista:
            tentativas |= item.tentativas
        return len(tentativas)

    def dias(lista) -> int:
        return sum(item.dias_atraso for item in lista)

    def atrasados(lista) -> int:
        return sum(1 for item in lista if item.com_atraso)

    com_cobranca = sorted(
        (lista for lista in por_cliente.values() if cobrancas(lista)),
        key=lambda lista: (cobrancas(lista), dias(lista)),
        reverse=True,
    )
    ranking_trabalho = Ranking(
        chave="trabalho",
        titulo="Mais cobranças para receber",
        subtitulo="Tentativas de cobrança até pagar, no período",
        itens=[
            ItemRanking(
                cliente=lista[0].cliente,
                valor=float(cobrancas(lista)),
                rotulo=f"{cobrancas(lista)} cobrança{'s' if cobrancas(lista) > 1 else ''}",
                detalhe=f"{atrasados(lista)} pago(s) com atraso · {dias(lista)} dias de atraso",
            )
            for lista in com_cobranca[:limite]
        ],
        vazio="Ninguém precisou ser cobrado para pagar.",
    )
    if com_cobranca:
        total = sum(cobrancas(lista) for lista in com_cobranca)
        primeiro = com_cobranca[0]
        ranking_trabalho.curiosidade = (
            f"{primeiro[0].cliente.nome} sozinho respondeu por {cobrancas(primeiro)} "
            f"das {total} cobranças feitas até o pagamento."
        )

    com_atraso = sorted(
        (lista for lista in por_cliente.values() if dias(lista)),
        key=lambda lista: (dias(lista), atrasados(lista)),
        reverse=True,
    )
    ranking_tempo = Ranking(
        chave="tempo_atraso",
        titulo="Mais tempo em atraso até pagar",
        subtitulo="Dias de atraso somados dos honorários pagos",
        itens=[
            ItemRanking(
                cliente=lista[0].cliente,
                valor=float(dias(lista)),
                rotulo=f"{dias(lista)} dias",
                detalhe=(
                    f"{atrasados(lista)} honorário(s) · o maior, "
                    f"{max(item.dias_atraso for item in lista)} dias"
                ),
            )
            for lista in com_atraso[:limite]
        ],
        vazio="Ninguém atrasou no período.",
    )
    return ranking_trabalho, ranking_tempo


def analisar(
    sessao: Session,
    desde: date | None = None,
    referencia: date | None = None,
    limite_ranking: int = 10,
) -> AnaliseJuros:
    ate = referencia or hoje()
    itens = _honorarios_pagos(sessao, desde, ate)
    ranking_juros, ranking_acrescimo = _rankings(itens, limite_ranking)
    ranking_trabalho, ranking_tempo = _rankings_de_trabalho(itens, limite_ranking)
    carteira = _carteira_atrasada(sessao, ate)
    return AnaliseJuros(
        desde=desde,
        ate=ate,
        honorarios=itens,
        meses=_por_mes(itens),
        juros_por_dia_hoje=sum((c.juros_por_dia for c in carteira.values()), start=ZERO),
        ranking_juros=ranking_juros,
        ranking_acrescimo=ranking_acrescimo,
        ranking_trabalho=ranking_trabalho,
        ranking_tempo=ranking_tempo,
        carteira=carteira,
    )


# ------------------------------------------------------------------ cenários


@dataclass
class Cenario:
    """Uma hipótese de taxa, aplicada aos mesmos atrasos do período."""

    rotulo: str
    explicacao: str
    aumento: Decimal            # em %, sobre a taxa atual
    juros_no_periodo: Decimal   # quanto teria entrado de juros
    a_mais: Decimal             # diferença para o que de fato entrou
    a_mais_por_mes: Decimal     # o que os atrasados de hoje renderiam a mais por mês
    taxa_dia: Decimal | None = None   # só na análise de um cliente
    atual: bool = False
    sem_abono: bool = False           # mesma taxa, cobrando o juros devido inteiro

    @property
    def fator(self) -> Decimal:
        return 1 + self.aumento / 100


AUMENTOS_PADRAO = (Decimal(10), Decimal(25), Decimal(50), Decimal(100))


def cenario(analise: AnaliseJuros, aumento: Decimal, rotulo: str = "") -> Cenario:
    """A taxa sobe ``aumento``% e tudo o mais fica igual: atrasos e proporção abonada."""
    aumento = Decimal(aumento)
    fator = aumento / 100
    # honorário a honorário, para a soma bater com a tabela de cada honorário
    juros = sum(
        (dinheiro(item.juros_cobrados * (1 + fator)) for item in analise.honorarios), start=ZERO
    )
    a_mais = juros - analise.juros_cobrados
    taxa = dinheiro(analise.taxa_atual * (1 + fator)) if analise.taxa_atual is not None else None
    return Cenario(
        rotulo=rotulo or f"{aumento:+.0f}%",
        explicacao=(
            f"Juros de {formatar_moeda(taxa)} ao dia" if taxa is not None
            else f"Juros de todos {aumento:+.0f}%"
        ),
        aumento=aumento,
        juros_no_periodo=juros,
        a_mais=a_mais,
        a_mais_por_mes=dinheiro(analise.juros_por_dia_hoje * 30 * fator),
        taxa_dia=taxa,
    )


def cenarios(analise: AnaliseJuros) -> list[Cenario]:
    """Como está, cobrando sem abonar e alguns aumentos, lado a lado."""
    saida = [
        Cenario(
            rotulo="Como está hoje",
            explicacao="O que de fato aconteceu no período",
            aumento=ZERO,
            juros_no_periodo=analise.juros_cobrados,
            a_mais=ZERO,
            a_mais_por_mes=ZERO,
            taxa_dia=analise.taxa_atual,
            atual=True,
        )
    ]
    if analise.abono > 0:
        saida.append(
            Cenario(
                rotulo="Mesma taxa, sem abono",
                explicacao="Cobrando o juros inteiro, sem perdoar nada",
                aumento=ZERO,
                juros_no_periodo=analise.juros_devidos,
                a_mais=analise.abono,
                a_mais_por_mes=ZERO,
                taxa_dia=analise.taxa_atual,
                sem_abono=True,
            )
        )
    for aumento in AUMENTOS_PADRAO:
        rotulo = "Dobrar" if aumento == 100 else ""
        saida.append(cenario(analise, aumento, rotulo))
    return saida


@dataclass
class HonorarioNoCenario:
    """Um honorário pago: o juros que ele pagou e o que pagaria no cenário."""

    item: HonorarioPago
    juros_cenario: Decimal

    @property
    def diferenca(self) -> Decimal:
        return self.juros_cenario - self.item.juros_cobrados

    @property
    def total_cenario(self) -> Decimal:
        return self.item.pago + self.diferenca


@dataclass
class AtrasadoNoCenario:
    """Um honorário em atraso hoje: quanto rende por dia agora e no cenário.

    O juros que já correu não muda — a taxa nova só vale da data em diante.
    """

    atrasado: AtrasadoHoje
    juros_por_dia_cenario: Decimal
    dias_projetados: int = 30

    @property
    def a_mais_por_dia(self) -> Decimal:
        return self.juros_por_dia_cenario - self.atrasado.juros_por_dia

    @property
    def total_projetado(self) -> Decimal:
        return dinheiro(self.atrasado.total + self.atrasado.juros_por_dia * self.dias_projetados)

    @property
    def total_projetado_cenario(self) -> Decimal:
        return dinheiro(
            self.atrasado.total + self.juros_por_dia_cenario * self.dias_projetados
        )


def por_honorario(analise: AnaliseJuros, cenario_: Cenario) -> list[HonorarioNoCenario]:
    """O cenário aplicado a cada honorário pago, com os mesmos atrasos."""
    saida = []
    for item in analise.honorarios:
        if cenario_.sem_abono:
            juros = item.juros_devidos
        else:
            juros = dinheiro(item.juros_cobrados * cenario_.fator)
        saida.append(HonorarioNoCenario(item=item, juros_cenario=juros))
    return saida


def atrasados_no_cenario(
    analise: AnaliseJuros, cenario_: Cenario, dias: int = 30
) -> list[AtrasadoNoCenario]:
    """Os atrasados de hoje: o que muda daqui para frente se a taxa mudar hoje."""
    fator = Decimal(1) if cenario_.sem_abono else cenario_.fator
    return [
        AtrasadoNoCenario(
            atrasado=atrasado,
            juros_por_dia_cenario=atrasado.juros_por_dia * fator,
            dias_projetados=dias,
        )
        for atrasado in analise.hoje.honorarios
    ]


# ------------------------------------------------- o trabalho para receber

INDICADORES_TRABALHO = (
    ("atraso", "Pagos com atraso", ""),
    ("tempo", "Tempo em atraso",
     "Dias de atraso somados de todos os honorários pagos no período"),
    ("cobrancas", "Cobranças feitas até pagar",
     "Cada mensagem enviada conta uma vez, mesmo com vários honorários dentro"),
    ("por_cobranca", "Juros por cobrança",
     "Quanto de juros entrou para cada cobrança feita: mostra se o trabalho de cobrar se paga"),
    ("taxa", "Juros efetivo ao mês", "Juros recebido ÷ (valor atrasado × meses de atraso)"),
    ("hoje", "Em atraso hoje", ""),
)


def indicadores_de_trabalho(
    analise: AnaliseJuros, geral: AnaliseJuros | None = None
) -> dict[str, tuple[str, str]]:
    """Valor e nota de cada indicador; a nota compara com a média dos clientes.

    A tela e o PDF usam os mesmos textos, para os dois mostrarem o mesmo número.
    """

    def media(texto: str) -> str:
        return f"média dos clientes: {texto}"

    atrasados = len(analise.atrasados)
    tem_media = geral is not None and bool(geral.atrasados)
    saida: dict[str, tuple[str, str]] = {}
    saida["atraso"] = (
        f"{atrasados} de {len(analise.honorarios)}",
        f"{percentual(analise.percentual_com_atraso, 0)} dos honorários pagos"
        + (f" · {media(percentual(geral.percentual_com_atraso, 0))}" if geral else ""),
    )
    saida["tempo"] = (
        _dias(analise.dias_em_atraso) if atrasados else "em dia",
        (
            f"média {_dias(round(analise.atraso_medio))} por honorário · o maior, "
            f"{_dias(analise.maior_atraso)}"
            if atrasados else "nenhum dia de atraso"
        )
        + (f" · {media(_dias(round(geral.atraso_medio)))}" if tem_media else ""),
    )
    saida["cobrancas"] = (
        str(analise.cobrancas) if analise.cobrancas else "nenhuma",
        (
            f"{_decimal(analise.cobrancas_por_atrasado)} por honorário atrasado"
            if atrasados else "pagou sem ser cobrado"
        )
        + (f" · {media(_decimal(geral.cobrancas_por_atrasado))}" if tem_media else ""),
    )
    por_cobranca = analise.juros_por_cobranca
    saida["por_cobranca"] = (
        formatar_moeda(por_cobranca) if por_cobranca is not None else "—",
        "juros recebido ÷ cobranças feitas"
        + (
            f" · {media(formatar_moeda(geral.juros_por_cobranca))}"
            if geral is not None and geral.juros_por_cobranca is not None else ""
        ),
    )
    efetiva, cadastrada = analise.taxa_mensal_efetiva, analise.taxa_mensal_cadastrada
    saida["taxa"] = (
        percentual(efetiva, 2) if efetiva is not None else "—",
        f"a taxa cadastrada daria {percentual(cadastrada, 2)} sem abono"
        if cadastrada is not None else "",
    )
    hoje_ = analise.hoje
    saida["hoje"] = (
        f"{hoje_.quantidade} honorário{'s' if hoje_.quantidade > 1 else ''}"
        if hoje_.quantidade else "nada",
        (
            f"o mais antigo há {_dias(hoje_.maior_atraso)} · "
            f"{formatar_moeda(hoje_.juros_por_dia)} de juros por dia · "
            f"{hoje_.cobrancas} cobrança(s) já feita(s)"
        ) if hoje_.quantidade else "",
    )
    return saida


# ----------------------------------------------------------------- explicação


def explicar_cliente(analise: AnaliseJuros) -> list[str]:
    """O caso de um cliente em frases simples: o que custou, o trabalho que deu e o
    que isso sugere. Sempre que dá, compara com a média dos clientes."""
    if not analise.honorarios or analise.cliente is None:
        return []
    geral = analise.geral
    frases = []
    quantidade = len(analise.honorarios)
    frases.append(
        f"Pagou {quantidade} honorário{'s' if quantidade > 1 else ''} no período: "
        f"{formatar_moeda(analise.original)} de valor original viraram "
        f"{formatar_moeda(analise.recebido)} pagos."
    )
    atrasados = len(analise.atrasados)
    if not atrasados:
        frases.append("Pagou tudo em dia, então não houve juros.")
    else:
        if atrasados == 1:
            frase = (
                f"Pagou {'ele' if quantidade == 1 else 'um deles'} com atraso, de "
                f"{_dias(analise.maior_atraso)}."
            )
        else:
            vezes = "todos" if atrasados == quantidade else f"{atrasados} deles"
            frase = (
                f"Pagou {vezes} com atraso: {_dias(analise.dias_em_atraso)} de atraso "
                f"somados, em média {analise.atraso_medio:.0f} por honorário (o maior, "
                f"{_dias(analise.maior_atraso)})."
            )
        if geral is not None and geral.atrasados:
            frase += f" A média dos clientes é {geral.atraso_medio:.0f} dias."
        frases.append(frase)

    # o trabalho que deu
    if analise.cobrancas:
        frase = (
            f"Foram {analise.cobrancas} cobrança{'s' if analise.cobrancas > 1 else ''} "
            f"até ele pagar"
        )
        if atrasados:
            frase += f", {_decimal(analise.cobrancas_por_atrasado)} por honorário atrasado"
            if geral is not None and geral.atrasados and geral.cobrancas:
                frase += f" (a média dos clientes é {_decimal(geral.cobrancas_por_atrasado)})"
        frases.append(frase + ".")
        if analise.juros_por_cobranca is not None:
            frase = (
                f"Cada cobrança rendeu em média {formatar_moeda(analise.juros_por_cobranca)} "
                f"de juros"
            )
            if geral is not None and geral.juros_por_cobranca is not None:
                frase += f"; a média geral é {formatar_moeda(geral.juros_por_cobranca)}"
            frases.append(frase + ".")
    elif atrasados:
        frases.append("Atrasou, mas pagou sem precisar ser cobrado.")

    if atrasados:
        frases.append(
            f"O atraso rendeu {formatar_moeda(analise.juros_cobrados)} de juros, "
            f"{percentual(analise.acrescimo_sobre_atrasados, 2)} a mais sobre o que "
            f"atrasou."
        )
    taxa = analise.taxa_atual or ZERO
    if taxa > 0 and analise.valor_medio > 0:
        ao_mes = taxa * 30 / analise.valor_medio * 100
        frases.append(
            f"O juros dele hoje é {formatar_moeda(taxa)} ao dia. Num honorário de "
            f"{formatar_moeda(analise.valor_medio)} (a média dele), um mês de atraso "
            f"custa {formatar_moeda(taxa * 30)} — {percentual(ao_mes, 1)} ao mês."
        )
    if analise.abono > 0:
        frases.append(
            f"Foram abonados {formatar_moeda(analise.abono)} de juros "
            f"({percentual(analise.percentual_abonado, 0)} do que era devido)."
        )
    hoje_ = analise.hoje
    if hoje_.quantidade:
        frases.append(
            f"Hoje tem {hoje_.quantidade} honorário{'s' if hoje_.quantidade > 1 else ''} "
            f"em atraso (o mais antigo há {_dias(hoje_.maior_atraso)}), somando "
            f"{formatar_moeda(hoje_.juros_por_dia)} de juros por dia"
            + (f" e já com {hoje_.cobrancas} cobrança(s)." if hoje_.cobrancas else ".")
        )
    else:
        frases.append("Hoje não tem nada em atraso.")

    frases.append("Leitura: " + _leitura(analise))
    return frases


def _leitura(analise: AnaliseJuros) -> str:
    """O que o comportamento sugere — observação; a decisão é de quem usa a tela."""
    atrasados = len(analise.atrasados)
    geral = analise.geral
    if not atrasados:
        return "um aumento não mudaria nada para ele enquanto continuar pagando em dia."
    if analise.percentual_abonado >= 25:
        return (
            "boa parte do juros dele é abonada; aumentar a taxa pouco muda enquanto o "
            "abono continuar."
        )
    da_trabalho = (
        geral is not None
        and geral.atrasados
        and analise.cobrancas_por_atrasado > geral.cobrancas_por_atrasado
    )
    frequente = atrasados * 2 >= len(analise.honorarios)
    if da_trabalho and frequente:
        return (
            "atrasa com frequência e precisa de mais cobranças que a média: o juros "
            "atual não está segurando os atrasos nem pagando o trabalho de cobrar. Um "
            "aumento teria efeito direto."
        )
    if da_trabalho:
        return (
            "não atrasa tanto, mas quando atrasa dá mais trabalho que a média para "
            "receber."
        )
    if frequente:
        return (
            "atrasa com frequência mesmo pagando o juros: para ele, a taxa atual parece "
            "não pesar."
        )
    return "atrasa de vez em quando e paga o juros: a taxa atual parece cumprir o papel."

__all__ = [
    "AUMENTOS_PADRAO",
    "PERIODOS",
    "AnaliseJuros",
    "AtrasadoHoje",
    "AtrasadoNoCenario",
    "CarteiraHoje",
    "HonorarioNoCenario",
    "INDICADORES_TRABALHO",
    "Cenario",
    "HonorarioPago",
    "Mes",
    "analisar",
    "atrasados_no_cenario",
    "cenario",
    "cenarios",
    "explicar_cliente",
    "indicadores_de_trabalho",
    "percentual",
    "por_honorario",
]
