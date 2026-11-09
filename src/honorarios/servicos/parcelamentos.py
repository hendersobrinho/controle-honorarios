"""Parcelamentos: o controle dos acordos que dividem honorários em parcelas.

O acordo em si é a ``Renegociacao`` (``servicos/renegociacoes.py``): os honorários
escolhidos — um ou vários — ficam como Renegociado e as parcelas nascem como
honorários novos. Daí em diante as parcelas são acompanhadas aqui, na tela
Parcelamentos, e saem das abas A vencer e Atrasados de Vencimentos (os pagos
continuam em Pagos, que é o que entrou no mês). Relatórios, ficha da empresa e o
e-mail do financeiro continuam vendo as parcelas como qualquer honorário.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..dominio.enums import StatusPagamento
from ..dominio.valores import ZERO, normalizar_busca
from ..infra.modelos import Cliente, Honorario, Renegociacao
from . import calculo, renegociacoes
from . import honorarios as servico_honorarios
from .erros import ErroDeValidacao
from .honorarios import LinhaHonorario
from .renegociacoes import ParcelaPrevista, dividir  # noqa: F401 - usados pela tela


@dataclass
class Parcela:
    numero: int
    linha: LinhaHonorario

    @property
    def honorario(self) -> Honorario:
        return self.linha.honorario

    @property
    def paga(self) -> bool:
        return self.honorario.status is StatusPagamento.PAGO

    @property
    def em_aberto(self) -> bool:
        return self.honorario.status is StatusPagamento.EM_ABERTO

    @property
    def atrasada(self) -> bool:
        return self.em_aberto and self.linha.atualizacao.dias_atraso > 0


@dataclass
class Parcelamento:
    acordo: Renegociacao
    parcelas: list[Parcela] = field(default_factory=list)
    originais: list[Honorario] = field(default_factory=list)

    @property
    def cliente(self) -> Cliente:
        return self.acordo.cliente

    @property
    def cancelado(self) -> bool:
        return self.acordo.cancelada_em is not None

    @property
    def validas(self) -> list[Parcela]:
        return [p for p in self.parcelas
                if p.honorario.status is not StatusPagamento.CANCELADO]

    @property
    def pagas(self) -> list[Parcela]:
        return [p for p in self.validas if p.paga]

    @property
    def abertas(self) -> list[Parcela]:
        return [p for p in self.validas if p.em_aberto]

    @property
    def atrasadas(self) -> list[Parcela]:
        return [p for p in self.abertas if p.atrasada]

    @property
    def quitado(self) -> bool:
        return not self.cancelado and bool(self.validas) and not self.abertas

    @property
    def proxima(self) -> Parcela | None:
        return self.abertas[0] if self.abertas else None

    @property
    def pago(self) -> Decimal:
        """O principal já pago das parcelas (inclui pagamento parcial)."""
        return sum((p.honorario.valor_original - p.honorario.saldo_aberto
                    for p in self.validas), start=ZERO)

    @property
    def falta(self) -> Decimal:
        """O que falta pagar hoje, com o juros das parcelas atrasadas."""
        return sum((p.linha.atualizacao.total for p in self.abertas), start=ZERO)


def _montar(acordos: Sequence[Renegociacao], sessao: Session,
            referencia: date) -> list[Parcelamento]:
    ids = {item.honorario_gerado_id or item.honorario_origem_id
           for acordo in acordos for item in acordo.itens}
    honorarios = {
        h.id: h for h in sessao.scalars(select(Honorario).where(Honorario.id.in_(ids)))
    } if ids else {}
    gerados = [honorarios[item.honorario_gerado_id] for acordo in acordos
               for item in acordo.itens if item.honorario_gerado_id in honorarios]
    atualizacoes = calculo.atualizar_varios(gerados, referencia)
    resultado = []
    for acordo in acordos:
        parcelamento = Parcelamento(acordo)
        for item in acordo.itens:
            if item.honorario_origem_id in honorarios:
                parcelamento.originais.append(honorarios[item.honorario_origem_id])
            honorario = honorarios.get(item.honorario_gerado_id)
            if honorario is not None:
                linha = servico_honorarios.montar_linha(
                    honorario, atualizacoes[honorario.id], referencia)
                parcelamento.parcelas.append(Parcela(0, linha))
        parcelamento.parcelas.sort(key=lambda p: (p.honorario.vencimento, p.honorario.id))
        for numero, parcela in enumerate(parcelamento.parcelas, start=1):
            parcela.numero = numero
        resultado.append(parcelamento)
    return resultado


def listar(sessao: Session, referencia: date, termo: str = "",
           incluir_cancelados: bool = False) -> list[Parcelamento]:
    """Os parcelamentos, do mais recente para o mais antigo."""
    consulta = (
        select(Renegociacao).join(Cliente)
        .where(Cliente.excluido_em.is_(None))
        .options(selectinload(Renegociacao.itens))
        .order_by(Renegociacao.data.desc(), Renegociacao.id.desc())
    )
    if not incluir_cancelados:
        consulta = consulta.where(Renegociacao.cancelada_em.is_(None))
    alvo = normalizar_busca(termo) if termo else ""
    if alvo:
        consulta = consulta.where(Cliente.nome_busca.contains(alvo))
    return _montar(sessao.scalars(consulta).unique().all(), sessao, referencia)


def obter(sessao: Session, acordo_id: int, referencia: date) -> Parcelamento | None:
    acordo = sessao.get(Renegociacao, acordo_id)
    return _montar([acordo], sessao, referencia)[0] if acordo is not None else None


def contar_atrasados(sessao: Session, referencia: date) -> int:
    """Parcelas vencidas e em aberto — o número ao lado da tela, contado no banco."""
    return sessao.scalar(
        select(func.count()).select_from(Honorario).join(Cliente)
        .where(Honorario.id.in_(servico_honorarios.ids_das_parcelas()),
               Honorario.status == StatusPagamento.EM_ABERTO,
               Honorario.vencimento < referencia,
               Cliente.excluido_em.is_(None))
    ) or 0


def criar(sessao: Session, cliente: Cliente, linhas: Sequence[LinhaHonorario],
          valor_acordado: Decimal, parcelas: int, primeiro_vencimento: date,
          tipo_id: int, desconto: Decimal = ZERO, observacoes: str = "",
          juros_ate_o_vencimento: bool = True) -> Renegociacao:
    for linha in linhas:
        if linha.honorario.cliente_id != cliente.id:
            raise ErroDeValidacao("Os honorários do parcelamento precisam ser do mesmo cliente.")
    return renegociacoes.criar(
        sessao, cliente=cliente, linhas=linhas, valor_acordado=valor_acordado,
        parcelas=parcelas, primeiro_vencimento=primeiro_vencimento, tipo_id=tipo_id,
        desconto=desconto, observacoes=observacoes,
        juros_ate_o_vencimento=juros_ate_o_vencimento,
    )


def cancelar(sessao: Session, parcelamento: Parcelamento, motivo: str) -> None:
    """Desfaz o parcelamento: os originais voltam para Em aberto e as parcelas são
    canceladas. Com parcela já paga não dá: o dinheiro precisa ser estornado antes."""
    if parcelamento.cancelado:
        raise ErroDeValidacao("Este parcelamento já foi cancelado.")
    if parcelamento.pagas or any(p.honorario.saldo_aberto != p.honorario.valor_original
                                 for p in parcelamento.abertas):
        raise ErroDeValidacao(
            "Este parcelamento já tem parcela paga. Estorne o pagamento da parcela antes "
            "de cancelar, para o dinheiro recebido não sumir das contas."
        )
    renegociacoes.cancelar(sessao, parcelamento.acordo, motivo)
