"""Tarefas: o que precisa ser feito, com baixa.

**Envio do honorário trimestral.** O trimestre de cada empresa conta da competência
em que ela virou cliente do escritório (``Cliente.cliente_desde``), não do
trimestre do ano: entrou em 15/08/2026 → 08, 09 e 10/2026; depois 11/2026 a
01/2027; e assim por diante. Quando o trimestre se completa, nasce a tarefa de
enviar o honorário dele — no primeiro dia do mês seguinte (01/11/2026 no
exemplo). Vale para quem tem honorário recorrente (contrato) trimestral ativo.

As tarefas pendentes não ficam gravadas: saem destas regras a cada leitura, e
mudar a data de entrada da empresa refaz a conta. Só a baixa vira linha
(``Tarefa``); desfazer a baixa apaga a linha. Para a lista não nascer com anos de
pendências de quem é cliente há muito tempo, só entram os trimestres completados
nos últimos ``JANELA_MESES`` meses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..dominio.enums import Periodicidade
from ..dominio.valores import formatar_data, hoje, somar_meses
from ..infra.modelos import Cliente, Contrato, Tarefa
from .erros import ErroDeValidacao

JANELA_MESES = 12
PREFIXO = "trimestre"


def trimestre(inicio: date) -> tuple[date, date]:
    """(primeiro dia, último dia) do trimestre que começa no mês de ``inicio``."""
    primeiro = date(inicio.year, inicio.month, 1)
    return primeiro, somar_meses(primeiro, 3) - timedelta(days=1)


def _competencia(dia: date) -> str:
    return f"{dia.month:02d}/{dia.year}"


@dataclass
class TarefaTrimestral:
    """Enviar o honorário de um trimestre completo da empresa."""

    contrato: Contrato
    inicio: date        # primeiro dia do primeiro mês do trimestre
    fim: date           # último dia do terceiro mês
    feita: Tarefa | None = None

    @property
    def cliente(self) -> Cliente:
        return self.contrato.cliente

    @property
    def chave(self) -> str:
        return f"{PREFIXO}:{self.contrato.id}:{self.inicio:%Y-%m}"

    @property
    def prazo(self) -> date:
        """Desde quando dá para enviar: o dia seguinte ao fim do trimestre."""
        return self.fim + timedelta(days=1)

    @property
    def periodo(self) -> str:
        return f"{_competencia(self.inicio)} a {_competencia(self.fim)}"

    @property
    def descricao(self) -> str:
        return f"Enviar o honorário trimestral ({self.contrato.tipo.nome}) · {self.periodo}"

    def dias_esperando(self, referencia: date) -> int:
        return max(0, (referencia - self.prazo).days)


@dataclass
class Quadro:
    """Tudo o que a tela de tarefas mostra."""

    pendentes: list[TarefaTrimestral] = field(default_factory=list)
    proximas: list[TarefaTrimestral] = field(default_factory=list)
    feitas: list[TarefaTrimestral] = field(default_factory=list)
    # têm honorário trimestral mas falta a data de entrada: sem ela não há conta
    sem_data: list[Cliente] = field(default_factory=list)


def _contratos_trimestrais(sessao: Session) -> list[Contrato]:
    consulta = (
        select(Contrato).join(Cliente, Contrato.cliente_id == Cliente.id)
        .where(Contrato.periodicidade == Periodicidade.TRIMESTRAL,
               Contrato.excluido_em.is_(None), Contrato.suspenso.is_(False),
               Cliente.excluido_em.is_(None))
    )
    return list(sessao.scalars(consulta).unique())


def quadro(sessao: Session, referencia: date | None = None) -> Quadro:
    referencia = referencia or hoje()
    janela = somar_meses(referencia, -JANELA_MESES)
    feitas = {t.chave: t for t in sessao.scalars(
        select(Tarefa).where(Tarefa.chave.like(f"{PREFIXO}:%")))}
    resultado = Quadro()
    for contrato in _contratos_trimestrais(sessao):
        entrada = contrato.cliente.cliente_desde
        if entrada is None:
            if contrato.cliente not in resultado.sem_data:
                resultado.sem_data.append(contrato.cliente)
            continue
        inicio = date(entrada.year, entrada.month, 1)
        while True:
            primeiro, ultimo = trimestre(inicio)
            tarefa = TarefaTrimestral(contrato, primeiro, ultimo)
            inicio = somar_meses(primeiro, 3)
            if contrato.vigencia_fim and primeiro > contrato.vigencia_fim:
                break   # o contrato acabou antes deste trimestre
            if tarefa.prazo > referencia:
                resultado.proximas.append(tarefa)
                break
            if tarefa.prazo < janela or ultimo < contrato.vigencia_inicio:
                continue
            tarefa.feita = feitas.get(tarefa.chave)
            (resultado.feitas if tarefa.feita else resultado.pendentes).append(tarefa)
    resultado.pendentes.sort(key=lambda t: (t.prazo, t.cliente.nome))
    resultado.proximas.sort(key=lambda t: (t.prazo, t.cliente.nome))
    resultado.feitas.sort(key=lambda t: t.feita.concluida_em, reverse=True)
    resultado.sem_data.sort(key=lambda c: c.nome)
    return resultado


def contar_pendentes(sessao: Session, referencia: date | None = None) -> int:
    return len(quadro(sessao, referencia).pendentes)


def concluir(sessao: Session, tarefa: TarefaTrimestral, observacao: str = "") -> Tarefa:
    """Dá baixa: o honorário do trimestre foi enviado."""
    if tarefa.feita is not None:
        raise ErroDeValidacao(f"Essa tarefa já teve baixa em "
                              f"{formatar_data(tarefa.feita.concluida_em)}.")
    feita = Tarefa(
        chave=tarefa.chave, cliente_id=tarefa.cliente.id, contrato_id=tarefa.contrato.id,
        descricao=tarefa.descricao, periodo_inicio=tarefa.inicio, periodo_fim=tarefa.fim,
        observacao=(observacao or "").strip(),
    )
    sessao.add(feita)
    sessao.flush()
    tarefa.feita = feita
    return feita


def reabrir(sessao: Session, chave: str) -> None:
    """Desfaz a baixa: a tarefa volta para as pendentes."""
    feita = sessao.scalar(select(Tarefa).where(Tarefa.chave == chave))
    if feita is None:
        raise ErroDeValidacao("Essa tarefa não tem baixa para desfazer.")
    sessao.delete(feita)
    sessao.flush()
