"""Honorários recorrentes: contratos, reajuste e geração de competência."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..dominio.enums import MeioCobranca, Periodicidade, StatusPagamento
from ..dominio.feriados import proximo_dia_util
from ..dominio.valores import ZERO, Competencia, agora_utc, dia_do_mes, dinheiro, hoje
from ..infra.modelos import Cliente, Contrato, ContratoHistorico, TipoHonorario
from . import honorarios as servico_honorarios
from .erros import ErroDeValidacao, RegistroDuplicado


@dataclass
class DadosContrato:
    cliente_id: int
    tipo_id: int
    valor: Decimal
    periodicidade: Periodicidade = Periodicidade.MENSAL
    dia_vencimento: int = 10
    meses_vencimento: int = 1
    meses_referencia: str = ""
    forma_envio_id: int | None = None
    meio: MeioCobranca = MeioCobranca.BOLETO
    vigencia_inicio: date | None = None
    vigencia_fim: date | None = None
    suspenso: bool = False
    observacoes: str = ""


def _validar(sessao: Session, dados: DadosContrato, contrato_id: int | None = None) -> None:
    if sessao.get(Cliente, dados.cliente_id) is None:
        raise ErroDeValidacao("Selecione o cliente.", "cliente")
    if sessao.get(TipoHonorario, dados.tipo_id) is None:
        raise ErroDeValidacao("Selecione o tipo de honorário.", "tipo")
    if dinheiro(dados.valor) <= 0:
        raise ErroDeValidacao("O valor do contrato deve ser maior que zero.", "valor")
    if not 1 <= dados.dia_vencimento <= 31:
        raise ErroDeValidacao("Dia de vencimento deve estar entre 1 e 31.", "dia_vencimento")
    if dados.periodicidade is Periodicidade.AVULSO:
        raise ErroDeValidacao(
            "Honorário avulso não tem contrato: use a tela de honorários avulsos.",
            "periodicidade",
        )
    consulta = select(Contrato).where(
        Contrato.cliente_id == dados.cliente_id,
        Contrato.tipo_id == dados.tipo_id,
        Contrato.excluido_em.is_(None),
    )
    if contrato_id:
        consulta = consulta.where(Contrato.id != contrato_id)
    if sessao.scalar(consulta):
        raise RegistroDuplicado("Este cliente já tem contrato desse tipo de honorário.")


def criar(sessao: Session, dados: DadosContrato) -> Contrato:
    _validar(sessao, dados)
    contrato = Contrato(
        cliente_id=dados.cliente_id,
        tipo_id=dados.tipo_id,
        valor=dinheiro(dados.valor),
        periodicidade=dados.periodicidade,
        dia_vencimento=dados.dia_vencimento,
        meses_vencimento=dados.meses_vencimento,
        meses_referencia=dados.meses_referencia or "",
        forma_envio_id=dados.forma_envio_id,
        meio=dados.meio,
        vigencia_inicio=dados.vigencia_inicio or hoje(),
        vigencia_fim=dados.vigencia_fim,
        suspenso=dados.suspenso,
        observacoes=dados.observacoes or "",
    )
    sessao.add(contrato)
    sessao.flush()
    return contrato


def atualizar(sessao: Session, contrato: Contrato, dados: DadosContrato) -> Contrato:
    _validar(sessao, dados, contrato.id)
    if dinheiro(dados.valor) != dinheiro(contrato.valor):
        raise ErroDeValidacao(
            "Mudança de valor é reajuste: use o botão Reajustar para guardar o histórico.",
            "valor",
        )
    contrato.periodicidade = dados.periodicidade
    contrato.dia_vencimento = dados.dia_vencimento
    contrato.meses_vencimento = dados.meses_vencimento
    contrato.meses_referencia = dados.meses_referencia or ""
    contrato.forma_envio_id = dados.forma_envio_id
    contrato.meio = dados.meio
    contrato.vigencia_inicio = dados.vigencia_inicio or contrato.vigencia_inicio
    contrato.vigencia_fim = dados.vigencia_fim
    contrato.suspenso = dados.suspenso
    contrato.observacoes = dados.observacoes or ""
    sessao.flush()
    return contrato


def excluir(sessao: Session, contrato: Contrato) -> None:
    contrato.excluido_em = agora_utc()
    sessao.flush()


def suspender(sessao: Session, contrato: Contrato, suspenso: bool = True) -> None:
    """Pausa a geração sem apagar o contrato."""
    contrato.suspenso = suspenso
    sessao.flush()


def reajustar(
    sessao: Session,
    contrato: Contrato,
    novo_valor: Decimal,
    vigencia_inicio: date | None = None,
    motivo: str = "",
) -> ContratoHistorico:
    """Reajuste vale só daqui para frente: o que já foi gerado não muda."""
    novo = dinheiro(novo_valor)
    if novo <= 0:
        raise ErroDeValidacao("O novo valor deve ser maior que zero.", "valor")
    anterior = dinheiro(contrato.valor)
    if novo == anterior:
        raise ErroDeValidacao("O novo valor é igual ao atual.", "valor")
    registro = ContratoHistorico(
        contrato_id=contrato.id,
        campo="valor",
        valor_anterior=str(anterior),
        valor_novo=str(novo),
        vigencia_inicio=vigencia_inicio or hoje(),
        motivo=motivo or "",
    )
    contrato.valor = novo
    contrato.historico.append(registro)
    sessao.flush()
    return registro


@dataclass
class ItemReajuste:
    contrato: Contrato
    valor_atual: Decimal
    valor_novo: Decimal


def previa_reajuste(
    contratos: Sequence[Contrato],
    percentual: Decimal | None = None,
    valor_fixo: Decimal | None = None,
) -> list[ItemReajuste]:
    if (percentual is None) == (valor_fixo is None):
        raise ErroDeValidacao("Informe um percentual OU um valor fixo de reajuste.")
    itens = []
    for contrato in contratos:
        atual = dinheiro(contrato.valor)
        if percentual is not None:
            novo = dinheiro(atual * (Decimal(1) + Decimal(str(percentual)) / 100))
        else:
            novo = dinheiro(atual + dinheiro(valor_fixo))
        itens.append(ItemReajuste(contrato=contrato, valor_atual=atual, valor_novo=novo))
    return itens


def aplicar_reajuste(
    sessao: Session,
    itens: Iterable[ItemReajuste],
    vigencia_inicio: date | None = None,
    motivo: str = "Reajuste anual",
) -> int:
    total = 0
    for item in itens:
        if item.valor_novo == dinheiro(item.contrato.valor):
            continue
        reajustar(sessao, item.contrato, item.valor_novo, vigencia_inicio, motivo)
        total += 1
    return total


# ------------------------------------------------------------ geração de competência


@dataclass
class ItemPrevia:
    contrato: Contrato
    competencia: Competencia
    valor: Decimal
    vencimento: date
    selecionado: bool = True
    impedimento: str = ""

    @property
    def cliente(self) -> Cliente:
        return self.contrato.cliente

    @property
    def gerar(self) -> bool:
        return self.selecionado and not self.impedimento


def _gera_nesta_competencia(contrato: Contrato, competencia: Competencia) -> bool:
    if contrato.periodicidade is Periodicidade.MENSAL:
        return True
    meses = [
        int(m)
        for m in (contrato.meses_referencia or "").replace(";", ",").split(",")
        if m.strip().isdigit()
    ]
    if meses:
        return competencia.mes in meses
    passo = contrato.periodicidade.meses or 1
    base = contrato.vigencia_inicio.month
    return competencia.mes is not None and (competencia.mes - base) % passo == 0


def previa_geracao(
    sessao: Session, competencia: Competencia, cliente_id: int | None = None
) -> list[ItemPrevia]:
    """Lista o que seria gerado, com o motivo de cada exclusão."""
    if not (competencia.ano and competencia.mes):
        raise ErroDeValidacao("Informe a competência no formato mm/aaaa.", "competencia")

    consulta = select(Contrato).where(Contrato.excluido_em.is_(None))
    if cliente_id:
        consulta = consulta.where(Contrato.cliente_id == cliente_id)

    primeiro_dia = date(competencia.ano, competencia.mes, 1)
    itens: list[ItemPrevia] = []
    for contrato in sessao.scalars(consulta).unique().all():
        # sábado, domingo ou feriado: vai para o próximo dia útil
        vencimento = proximo_dia_util(dia_do_mes(
            *_mes_vencimento(competencia, contrato.meses_vencimento),
            contrato.dia_vencimento,
        ))
        item = ItemPrevia(
            contrato=contrato,
            competencia=competencia,
            valor=dinheiro(contrato.valor),
            vencimento=vencimento,
        )
        empresa_id = contrato.cliente.empresa_id
        empresa = sessao.get(Cliente, empresa_id) if empresa_id else None
        if empresa is not None and empresa.excluido_em is None:
            # o que a empresa paga já cobre esta pessoa: não se gera honorário dela
            # (lançar um à mão continua possível, se um dia for preciso)
            item.impedimento = f"Paga pela empresa {empresa.codigo} – {empresa.nome}"
        elif contrato.suspenso:
            item.impedimento = "Contrato suspenso temporariamente"
        elif contrato.vigencia_inicio > _ultimo_dia(competencia):
            item.impedimento = (
                f"Vigência começa em {contrato.vigencia_inicio:%d/%m/%Y}"
            )
        elif contrato.vigencia_fim and contrato.vigencia_fim < primeiro_dia:
            item.impedimento = f"Vigência encerrada em {contrato.vigencia_fim:%d/%m/%Y}"
        elif not _gera_nesta_competencia(contrato, competencia):
            item.impedimento = (
                f"{contrato.periodicidade.rotulo}: não gera nesta competência"
            )
        elif servico_honorarios.existente(
            sessao, contrato.cliente_id, contrato.tipo_id, competencia
        ):
            item.impedimento = "Já lançado nesta competência"
        if item.impedimento:
            item.selecionado = False
        itens.append(item)
    itens.sort(key=lambda item: (bool(item.impedimento), item.cliente.nome))
    return itens


def _mes_vencimento(competencia: Competencia, deslocamento: int) -> tuple[int, int]:
    total = (competencia.ano * 12 + (competencia.mes or 1) - 1) + max(0, deslocamento)
    return total // 12, total % 12 + 1


def _ultimo_dia(competencia: Competencia) -> date:
    import calendar

    ano, mes = competencia.ano, competencia.mes or 12
    return date(ano, mes, calendar.monthrange(ano, mes)[1])


def gerar(sessao: Session, itens: Sequence[ItemPrevia]) -> list:
    """Cria os honorários dos itens marcados. Nada é gerado duas vezes."""
    criados = []
    for item in itens:
        if not item.gerar:
            continue
        dados = servico_honorarios.DadosHonorario(
            cliente_id=item.contrato.cliente_id,
            tipo_id=item.contrato.tipo_id,
            valor=item.valor,
            vencimento=item.vencimento,
            competencia=item.competencia,
            meio=item.contrato.meio,
            forma_envio_id=item.contrato.forma_envio_id,
            contrato_id=item.contrato.id,
        )
        criados.append(servico_honorarios.criar(sessao, dados))
    sessao.flush()
    return criados


def listar(sessao: Session, cliente_id: int | None = None, incluir_suspensos: bool = True):
    consulta = select(Contrato).where(Contrato.excluido_em.is_(None))
    if cliente_id:
        consulta = consulta.where(Contrato.cliente_id == cliente_id)
    if not incluir_suspensos:
        consulta = consulta.where(Contrato.suspenso.is_(False))
    return list(sessao.scalars(consulta.join(Cliente).order_by(Cliente.nome)).unique().all())


def total_mensal(sessao: Session) -> Decimal:
    contratos = listar(sessao, incluir_suspensos=False)
    return sum(
        (dinheiro(c.valor) for c in contratos if c.periodicidade is Periodicidade.MENSAL),
        start=ZERO,
    )


__all__ = [
    "DadosContrato",
    "ItemPrevia",
    "ItemReajuste",
    "aplicar_reajuste",
    "atualizar",
    "criar",
    "excluir",
    "gerar",
    "listar",
    "previa_geracao",
    "previa_reajuste",
    "reajustar",
    "suspender",
    "total_mensal",
    "StatusPagamento",
]
