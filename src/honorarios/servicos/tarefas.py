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

**Envio das parcelas.** Cada parcela em aberto de um parcelamento vira a tarefa de
enviá-la ao cliente (boleto, Pix…) ``dias_lembrete_parcela`` dias antes do
vencimento escolhido no parcelamento (5 por padrão, em Configurações). Parcela paga
ou parcelamento cancelado saem da lista; a baixa fica como nas trimestrais.

**Pagamento dos acordos.** O acordo feito no Cobrar ("pague R$ X até tal data") vira
a tarefa de acompanhar o pagamento até a data combinada. Fica na lista enquanto
algum honorário do acordo estiver em aberto — passado o prazo, continua, avisando
que o juros voltou a correr. Pago tudo, sai sozinha; a baixa serve para tirar da
lista o que não precisa mais acompanhar. Um acordo novo do mesmo honorário
substitui o antigo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..dominio.enums import Periodicidade, StatusPagamento
from ..dominio.valores import ZERO, formatar_data, formatar_moeda, hoje, somar_meses
from ..infra.modelos import AcordoValor, Cliente, Contrato, Honorario, Tarefa
from .erros import ErroDeValidacao

JANELA_MESES = 12
PREFIXO = "trimestre"
PREFIXO_PARCELA = "parcela"
PREFIXO_ACORDO = "acordo"
CHAVE_DIAS_PARCELA = "dias_lembrete_parcela"
DIAS_PARCELA_PADRAO = 5


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
class TarefaParcela:
    """Enviar ao cliente uma parcela do parcelamento, antes do vencimento."""

    parcelamento: object    # servicos.parcelamentos.Parcelamento
    parcela: object         # servicos.parcelamentos.Parcela
    dias_antes: int
    feita: Tarefa | None = None

    @property
    def cliente(self) -> Cliente:
        return self.parcelamento.cliente

    @property
    def honorario(self):
        return self.parcela.honorario

    @property
    def chave(self) -> str:
        return f"{PREFIXO_PARCELA}:{self.honorario.id}"

    @property
    def vencimento(self) -> date:
        return self.honorario.vencimento

    @property
    def prazo(self) -> date:
        """Desde quando lembrar: alguns dias antes do vencimento."""
        return self.vencimento - timedelta(days=self.dias_antes)

    @property
    def periodo(self) -> str:
        return f"{self.parcela.numero}/{len(self.parcelamento.parcelas)}"

    @property
    def descricao(self) -> str:
        return (f"Enviar a parcela {self.periodo} do parcelamento "
                f"(vence {formatar_data(self.vencimento)})")

    # o período que a baixa grava (mesma tabela das trimestrais)
    @property
    def inicio(self) -> date:
        return self.vencimento

    @property
    def fim(self) -> date:
        return self.vencimento

    def dias_esperando(self, referencia: date) -> int:
        return max(0, (referencia - self.prazo).days)


@dataclass
class TarefaAcordo:
    """Acompanhar o pagamento de um acordo até a data combinada."""

    acordos: list[AcordoValor]   # um por honorário, feitos juntos no Cobrar
    feita: Tarefa | None = None

    @property
    def cliente(self) -> Cliente:
        return self.acordos[0].honorario.cliente

    @property
    def honorarios(self) -> list[Honorario]:
        return [acordo.honorario for acordo in self.acordos]

    @property
    def em_aberto(self) -> list[Honorario]:
        return [h for h in self.honorarios if h.status is StatusPagamento.EM_ABERTO]

    @property
    def chave(self) -> str:
        return f"{PREFIXO_ACORDO}:{min(acordo.id for acordo in self.acordos)}"

    @property
    def total(self) -> Decimal:
        return sum((Decimal(acordo.total) for acordo in self.acordos), start=ZERO)

    @property
    def data_base(self) -> date:
        return self.acordos[0].data_base

    @property
    def vencimento(self) -> date:
        return self.acordos[0].valido_ate

    @property
    def prazo(self) -> date:
        return self.vencimento

    @property
    def periodo(self) -> str:
        return f"até {formatar_data(self.vencimento)}"

    @property
    def descricao(self) -> str:
        return (f"Acompanhar o pagamento do acordo: {formatar_moeda(self.total)} "
                f"até {formatar_data(self.vencimento)}")

    # o período que a baixa grava (mesma tabela das trimestrais)
    @property
    def inicio(self) -> date:
        return self.data_base

    @property
    def fim(self) -> date:
        return self.vencimento

    def dias_esperando(self, referencia: date) -> int:
        return max(0, (referencia - self.vencimento).days)


@dataclass
class Quadro:
    """Tudo o que a tela de tarefas mostra."""

    pendentes: list[TarefaTrimestral] = field(default_factory=list)
    proximas: list[TarefaTrimestral] = field(default_factory=list)
    feitas: list[TarefaTrimestral] = field(default_factory=list)
    # têm honorário trimestral mas falta a data de entrada: sem ela não há conta
    sem_data: list[Cliente] = field(default_factory=list)
    # envio das parcelas dos parcelamentos
    parcelas: list[TarefaParcela] = field(default_factory=list)
    parcelas_proximas: list[TarefaParcela] = field(default_factory=list)
    parcelas_feitas: list[TarefaParcela] = field(default_factory=list)
    # pagamento dos acordos feitos no Cobrar
    acordos: list[TarefaAcordo] = field(default_factory=list)
    acordos_feitos: list[TarefaAcordo] = field(default_factory=list)

    @property
    def para_fazer(self) -> int:
        return len(self.pendentes) + len(self.parcelas) + len(self.acordos)

    @property
    def todas(self) -> list:
        return (self.pendentes + self.feitas + self.parcelas + self.parcelas_feitas
                + self.acordos + self.acordos_feitos)


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
    _parcelas(sessao, referencia, resultado)
    _acordos(sessao, referencia, resultado)
    return resultado


def dias_antes_da_parcela(sessao: Session) -> int:
    from . import configuracoes

    return configuracoes.obter_int(sessao, CHAVE_DIAS_PARCELA, DIAS_PARCELA_PADRAO)


def _parcelas(sessao: Session, referencia: date, resultado: Quadro) -> None:
    from . import parcelamentos

    dias = dias_antes_da_parcela(sessao)
    feitas = {t.chave: t for t in sessao.scalars(
        select(Tarefa).where(Tarefa.chave.like(f"{PREFIXO_PARCELA}:%")))}
    for parcelamento in parcelamentos.listar(sessao, referencia):
        proxima_vista = False
        for parcela in parcelamento.parcelas:
            tarefa = TarefaParcela(parcelamento, parcela, dias)
            tarefa.feita = feitas.get(tarefa.chave)
            if tarefa.feita is not None:
                resultado.parcelas_feitas.append(tarefa)
            elif not parcela.em_aberto:
                continue    # paga ou cancelada: não precisa mais enviar
            elif tarefa.prazo <= referencia:
                resultado.parcelas.append(tarefa)
            elif not proxima_vista:   # das futuras, só a próxima de cada parcelamento
                resultado.parcelas_proximas.append(tarefa)
                proxima_vista = True
    resultado.parcelas.sort(key=lambda t: (t.vencimento, t.cliente.nome))
    resultado.parcelas_proximas.sort(key=lambda t: (t.prazo, t.cliente.nome))
    janela = somar_meses(referencia, -JANELA_MESES)
    resultado.parcelas_feitas = sorted(
        (t for t in resultado.parcelas_feitas if t.vencimento >= janela),
        key=lambda t: t.feita.concluida_em, reverse=True)


def _acordos(sessao: Session, referencia: date, resultado: Quadro) -> None:
    janela = somar_meses(referencia, -JANELA_MESES)
    consulta = (
        select(AcordoValor).join(Honorario).join(Cliente)
        .where(AcordoValor.valido_ate >= janela, Cliente.excluido_em.is_(None))
        .order_by(AcordoValor.criado_em, AcordoValor.id)
    )
    # o acordo mais novo de cada honorário: um acordo refeito substitui o anterior
    ultimo: dict[int, AcordoValor] = {}
    for acordo in sessao.scalars(consulta):
        ultimo[acordo.honorario_id] = acordo
    # os acordos feitos juntos (mesmo cliente, mesmas datas) são uma tarefa só
    grupos: dict[tuple, list[AcordoValor]] = {}
    for acordo in ultimo.values():
        chave = (acordo.honorario.cliente_id, acordo.data_base, acordo.valido_ate)
        grupos.setdefault(chave, []).append(acordo)
    feitas = {t.chave: t for t in sessao.scalars(
        select(Tarefa).where(Tarefa.chave.like(f"{PREFIXO_ACORDO}:%")))}
    for acordos in grupos.values():
        tarefa = TarefaAcordo(sorted(acordos, key=lambda a: a.id))
        tarefa.feita = feitas.get(tarefa.chave)
        if tarefa.feita is not None:
            resultado.acordos_feitos.append(tarefa)
        elif tarefa.em_aberto:
            resultado.acordos.append(tarefa)
        # pago tudo: não há o que acompanhar
    resultado.acordos.sort(key=lambda t: (t.vencimento, t.cliente.nome))
    resultado.acordos_feitos.sort(key=lambda t: t.feita.concluida_em, reverse=True)


def contar_pendentes(sessao: Session, referencia: date | None = None) -> int:
    return quadro(sessao, referencia).para_fazer


def concluir(sessao: Session, tarefa: TarefaTrimestral | TarefaParcela | TarefaAcordo,
             observacao: str = "") -> Tarefa:
    """Dá baixa: o honorário do trimestre (ou a parcela) foi enviado; o acordo não
    precisa mais ser acompanhado."""
    if tarefa.feita is not None:
        raise ErroDeValidacao(f"Essa tarefa já teve baixa em "
                              f"{formatar_data(tarefa.feita.concluida_em)}.")
    feita = Tarefa(
        chave=tarefa.chave, cliente_id=tarefa.cliente.id,
        contrato_id=tarefa.contrato.id if isinstance(tarefa, TarefaTrimestral) else None,
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
