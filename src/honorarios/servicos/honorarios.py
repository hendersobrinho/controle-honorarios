"""Honorários: criação, edição, cancelamento e as consultas das telas."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..dominio.enums import (
    ExigeCompetencia,
    MeioCobranca,
    ResultadoCobranca,
    SituacaoEnvio,
    StatusPagamento,
    TipoPessoa,
)
from ..dominio.valores import (
    ZERO,
    Competencia,
    agora_utc,
    dinheiro,
    hoje,
    normalizar_busca,
    somar_meses,
)
from ..infra.modelos import (
    Cliente,
    Cobranca,
    GrupoHonorario,
    Honorario,
    LogAlteracao,
    TipoHonorario,
)
from . import calculo
from .erros import ErroDeValidacao, RegistroDuplicado


def chave_competencia(competencia: Competencia) -> str:
    if competencia.ano and competencia.mes:
        return f"{competencia.ano:04d}-{competencia.mes:02d}"
    if competencia.ano:
        return f"{competencia.ano:04d}"
    return ""


@dataclass
class DadosHonorario:
    cliente_id: int
    tipo_id: int
    valor: Decimal
    vencimento: date
    competencia: Competencia = field(default_factory=Competencia)
    descricao: str = ""
    meio: MeioCobranca = MeioCobranca.BOLETO
    forma_envio_id: int | None = None
    observacoes: str = ""
    numero_boleto: str = ""
    contrato_id: int | None = None
    situacao_envio: SituacaoEnvio = SituacaoEnvio.NAO_ENVIADO
    enviado_em: date | None = None


@dataclass
class LinhaHonorario:
    """Honorário pronto para a tabela, com cálculo e histórico de cobrança."""

    honorario: Honorario
    atualizacao: calculo.Atualizacao
    cobrancas: int = 0
    ultima_cobranca: date | None = None
    promessa: date | None = None

    @property
    def cliente(self) -> Cliente:
        return self.honorario.cliente

    @property
    def grupo(self) -> GrupoHonorario:
        return self.honorario.tipo.grupo

    @property
    def nunca_cobrado(self) -> bool:
        return self.cobrancas == 0

    @property
    def promessa_vencida(self) -> bool:
        return self.promessa is not None and self.promessa < hoje()

    @property
    def cobranca_suspensa(self) -> bool:
        return self.cliente.suspensao_ativa()


@dataclass
class Filtro:
    termo: str = ""
    cliente_id: int | None = None
    tipo_pessoa: TipoPessoa | None = None
    grupo_id: int | None = None
    tipo_id: int | None = None
    status: StatusPagamento | None = StatusPagamento.EM_ABERTO
    vencimento_de: date | None = None
    vencimento_ate: date | None = None
    pago_de: date | None = None
    pago_ate: date | None = None
    competencia_ano: int | None = None
    # um mês de competência (ano, mês); sem mês na competência, vale o do vencimento
    competencia_mes: tuple[int, int] | None = None
    atraso_minimo: int | None = None
    atraso_maximo: int | None = None
    nunca_cobrado: bool = False
    sem_cobranca_dias: int | None = None
    somente_promessa_vencida: bool = False
    # cliente com cobrança suspensa continua aparecendo na cobrança geral (a
    # dívida existe), mas sai das filas de trabalho
    incluir_cobranca_suspensa: bool = True
    incluir_vinculados_de: int | None = None
    # None = todos; True = só clientes de Imposto de Renda; False = sem eles
    clientes_so_ir: bool | None = None
    data_referencia: date | None = None


def clientes_so_imposto_de_renda(sessao: Session) -> set[int]:
    """Clientes cujo único assunto com o escritório é o Imposto de Renda.

    É cliente só de IR quem tem honorário (não cancelado) e todos eles são de
    tipos do grupo marcado como Imposto de Renda — e não tem contrato recorrente
    ativo de outro tipo. Quem tem mensal e IR continua sendo cliente mensal.
    """
    from ..infra.modelos import Contrato, GrupoHonorario

    tipos_ir = set(
        sessao.scalars(
            select(TipoHonorario.id)
            .join(GrupoHonorario)
            .where(GrupoHonorario.imposto_de_renda.is_(True))
        )
    )
    if not tipos_ir:
        return set()

    tipos_por_cliente: dict[int, set[int]] = {}
    for cliente_id, tipo_id in sessao.execute(
        select(Honorario.cliente_id, Honorario.tipo_id).where(
            Honorario.status != StatusPagamento.CANCELADO
        )
    ):
        tipos_por_cliente.setdefault(cliente_id, set()).add(tipo_id)

    com_contrato_de_outro_tipo = {
        cliente_id
        for cliente_id, tipo_id in sessao.execute(
            select(Contrato.cliente_id, Contrato.tipo_id).where(
                Contrato.excluido_em.is_(None), Contrato.suspenso.is_(False)
            )
        )
        if tipo_id not in tipos_ir
    }
    return {
        cliente_id
        for cliente_id, tipos in tipos_por_cliente.items()
        if tipos <= tipos_ir and cliente_id not in com_contrato_de_outro_tipo
    }


def _validar_competencia(tipo: TipoHonorario, competencia: Competencia, descricao: str) -> None:
    if tipo.exige_competencia is ExigeCompetencia.MES and not (
        competencia.ano and competencia.mes
    ):
        raise ErroDeValidacao(
            f"O tipo {tipo.nome} exige competência no formato mm/aaaa.", "competencia"
        )
    if tipo.exige_competencia is ExigeCompetencia.ANO and not competencia.ano:
        raise ErroDeValidacao(f"O tipo {tipo.nome} exige o ano de competência.", "competencia")
    if tipo.exige_competencia is ExigeCompetencia.NENHUMA and not (descricao or "").strip():
        raise ErroDeValidacao(
            f"O tipo {tipo.nome} não usa competência: descreva o serviço.", "descricao"
        )


def existente(
    sessao: Session, cliente_id: int, tipo_id: int, competencia: Competencia
) -> Honorario | None:
    chave = chave_competencia(competencia)
    if not chave:
        return None
    return sessao.scalar(
        select(Honorario).where(
            Honorario.cliente_id == cliente_id,
            Honorario.tipo_id == tipo_id,
            Honorario.competencia_chave == chave,
            Honorario.status != StatusPagamento.CANCELADO,
        )
    )


def criar(sessao: Session, dados: DadosHonorario) -> Honorario:
    cliente = sessao.get(Cliente, dados.cliente_id)
    if cliente is None:
        raise ErroDeValidacao("Selecione o cliente.", "cliente")
    tipo = sessao.get(TipoHonorario, dados.tipo_id)
    if tipo is None:
        raise ErroDeValidacao("Selecione o tipo de honorário.", "tipo")
    valor = dinheiro(dados.valor)
    if valor <= 0:
        raise ErroDeValidacao("O valor do honorário deve ser maior que zero.", "valor")
    if dados.vencimento is None:
        raise ErroDeValidacao("Informe o vencimento.", "vencimento")
    _validar_competencia(tipo, dados.competencia, dados.descricao)

    duplicado = existente(sessao, dados.cliente_id, dados.tipo_id, dados.competencia)
    if duplicado is not None:
        raise RegistroDuplicado(
            f"{cliente.nome} já tem {tipo.nome} da competência "
            f"{dados.competencia.rotulo()} lançado (vencimento "
            f"{duplicado.vencimento:%d/%m/%Y})."
        )

    honorario = Honorario(
        cliente_id=cliente.id,
        tipo_id=tipo.id,
        contrato_id=dados.contrato_id,
        competencia_ano=dados.competencia.ano,
        competencia_mes=dados.competencia.mes,
        competencia_chave=chave_competencia(dados.competencia),
        descricao=(dados.descricao or "").strip(),
        valor_original=valor,
        saldo_aberto=valor,
        vencimento=dados.vencimento,
        juros_dia_snapshot=calculo.taxa_vigente_em(cliente, dados.vencimento),
        meio=dados.meio,
        forma_envio_id=dados.forma_envio_id,
        observacoes=dados.observacoes or "",
        numero_boleto=dados.numero_boleto or "",
        situacao_envio=dados.situacao_envio,
        enviado_em=dados.enviado_em,
        status=StatusPagamento.EM_ABERTO,
    )
    cliente.honorarios.append(honorario)
    sessao.flush()
    return honorario


def atualizar(sessao: Session, honorario: Honorario, dados: DadosHonorario) -> Honorario:
    if honorario.status is StatusPagamento.PAGO:
        raise ErroDeValidacao(
            "Honorário pago não pode ser editado. Estorne o pagamento antes."
        )
    tipo = sessao.get(TipoHonorario, dados.tipo_id)
    if tipo is None:
        raise ErroDeValidacao("Selecione o tipo de honorário.", "tipo")
    _validar_competencia(tipo, dados.competencia, dados.descricao)
    valor = dinheiro(dados.valor)
    if valor <= 0:
        raise ErroDeValidacao("O valor do honorário deve ser maior que zero.", "valor")

    duplicado = existente(sessao, dados.cliente_id, dados.tipo_id, dados.competencia)
    if duplicado is not None and duplicado.id != honorario.id:
        raise RegistroDuplicado(
            f"Já existe {tipo.nome} da competência {dados.competencia.rotulo()} "
            "para este cliente."
        )

    pago = honorario.valor_original - honorario.saldo_aberto
    honorario.tipo_id = tipo.id
    honorario.competencia_ano = dados.competencia.ano
    honorario.competencia_mes = dados.competencia.mes
    honorario.competencia_chave = chave_competencia(dados.competencia)
    honorario.descricao = (dados.descricao or "").strip()
    honorario.valor_original = valor
    honorario.saldo_aberto = max(ZERO, valor - pago)
    honorario.vencimento = dados.vencimento
    honorario.meio = dados.meio
    honorario.forma_envio_id = dados.forma_envio_id
    honorario.observacoes = dados.observacoes or ""
    honorario.numero_boleto = dados.numero_boleto or ""
    honorario.situacao_envio = dados.situacao_envio
    honorario.enviado_em = dados.enviado_em
    sessao.flush()
    return honorario


def cancelar(sessao: Session, honorario: Honorario, motivo: str) -> None:
    if honorario.status is StatusPagamento.PAGO:
        raise ErroDeValidacao("Honorário pago não pode ser cancelado; estorne primeiro.")
    if not (motivo or "").strip():
        raise ErroDeValidacao("Descreva o motivo do cancelamento.", "motivo")
    honorario.status = StatusPagamento.CANCELADO
    honorario.cancelado_em = agora_utc()
    honorario.motivo_cancelamento = motivo.strip()
    honorario.saldo_aberto = ZERO
    sessao.add(
        LogAlteracao(
            entidade="honorario",
            entidade_id=honorario.id,
            acao="CANCELAR",
            resumo=motivo.strip(),
        )
    )
    sessao.flush()


def marcar_enviado(
    sessao: Session, honorarios: Iterable[Honorario], quando: date | None = None
) -> int:
    data = quando or hoje()
    total = 0
    for honorario in honorarios:
        honorario.situacao_envio = SituacaoEnvio.ENVIADO
        honorario.enviado_em = data
        total += 1
    sessao.flush()
    return total


# ----------------------------------------------------------------------- consultas


def _resumo_cobrancas(honorario: Honorario) -> tuple[int, date | None, date | None]:
    ativas = [c for c in honorario.cobrancas if c.ativa]
    if not ativas:
        return 0, None, None
    ultima = max(c.data_hora for c in ativas)
    promessas = [
        c.promessa_data
        for c in ativas
        if c.resultado is ResultadoCobranca.PROMETEU_PAGAR and c.promessa_data
    ]
    return len(ativas), ultima.date(), max(promessas) if promessas else None


def montar_linha(
    honorario: Honorario, atualizacao: calculo.Atualizacao | None = None,
    data_referencia: date | None = None,
) -> LinhaHonorario:
    quantidade, ultima, promessa = _resumo_cobrancas(honorario)
    return LinhaHonorario(
        honorario=honorario,
        atualizacao=atualizacao or calculo.atualizar(honorario, data_referencia),
        cobrancas=quantidade,
        ultima_cobranca=ultima,
        promessa=promessa,
    )


def consultar(sessao: Session, filtro: Filtro) -> list[LinhaHonorario]:
    consulta = select(Honorario).join(Cliente).join(TipoHonorario)
    if filtro.status is not None:
        consulta = consulta.where(Honorario.status == filtro.status)
    if filtro.cliente_id:
        alvos = [filtro.cliente_id]
        if filtro.incluir_vinculados_de == filtro.cliente_id:
            # a empresa cobra também pelas pessoas físicas vinculadas a ela
            alvos += [
                identificador
                for (identificador,) in sessao.execute(
                    select(Cliente.id).where(
                        Cliente.empresa_id == filtro.cliente_id,
                        Cliente.excluido_em.is_(None),
                    )
                )
            ]
        consulta = consulta.where(Honorario.cliente_id.in_(alvos))
    if filtro.tipo_pessoa is not None:
        consulta = consulta.where(Cliente.tipo_pessoa == filtro.tipo_pessoa)
    if filtro.grupo_id:
        consulta = consulta.where(TipoHonorario.grupo_id == filtro.grupo_id)
    if filtro.tipo_id:
        consulta = consulta.where(Honorario.tipo_id == filtro.tipo_id)
    if filtro.vencimento_de:
        consulta = consulta.where(Honorario.vencimento >= filtro.vencimento_de)
    if filtro.vencimento_ate:
        consulta = consulta.where(Honorario.vencimento <= filtro.vencimento_ate)
    # O recorte de período dos pagos entra na consulta, não na tela: o que está
    # fora do período nem chega a ser lido nem calculado. Honorário importado da
    # planilha antiga não tem data de pagamento (ela não existia lá), então nesse
    # caso o vencimento serve de referência — senão o histórico sumiria.
    if filtro.pago_de:
        consulta = consulta.where(
            or_(
                Honorario.pago_em >= filtro.pago_de,
                and_(Honorario.pago_em.is_(None), Honorario.vencimento >= filtro.pago_de),
            )
        )
    if filtro.pago_ate:
        consulta = consulta.where(
            or_(
                Honorario.pago_em <= filtro.pago_ate,
                and_(Honorario.pago_em.is_(None), Honorario.vencimento <= filtro.pago_ate),
            )
        )
    if filtro.competencia_ano:
        consulta = consulta.where(Honorario.competencia_ano == filtro.competencia_ano)
    if filtro.competencia_mes:
        ano, mes = filtro.competencia_mes
        inicio = date(ano, mes, 1)
        fim = somar_meses(inicio, 1) - timedelta(days=1)
        consulta = consulta.where(or_(
            and_(Honorario.competencia_ano == ano, Honorario.competencia_mes == mes),
            and_(Honorario.competencia_mes.is_(None), Honorario.vencimento.between(inicio, fim)),
        ))
    if filtro.termo:
        from ..dominio.valores import normalizar_busca

        alvo = normalizar_busca(filtro.termo)
        if alvo:
            consulta = consulta.where(Cliente.nome_busca.contains(alvo))
    consulta = consulta.where(Cliente.excluido_em.is_(None))
    if filtro.clientes_so_ir is not None:
        so_ir = clientes_so_imposto_de_renda(sessao)
        if filtro.clientes_so_ir:
            consulta = consulta.where(Honorario.cliente_id.in_(so_ir))
        elif so_ir:
            consulta = consulta.where(Honorario.cliente_id.not_in(so_ir))

    encontrados = sessao.scalars(consulta.order_by(Honorario.vencimento)).unique().all()
    referencia = filtro.data_referencia or hoje()
    atualizacoes = calculo.atualizar_varios(encontrados, referencia)

    linhas: list[LinhaHonorario] = []
    for honorario in encontrados:
        linha = montar_linha(honorario, atualizacoes[honorario.id], referencia)
        atraso = linha.atualizacao.dias_atraso
        if filtro.atraso_minimo is not None and atraso < filtro.atraso_minimo:
            continue
        if filtro.atraso_maximo is not None and atraso > filtro.atraso_maximo:
            continue
        if filtro.nunca_cobrado and linha.cobrancas:
            continue
        if filtro.sem_cobranca_dias is not None:
            limite = filtro.sem_cobranca_dias
            if linha.ultima_cobranca and (referencia - linha.ultima_cobranca).days < limite:
                continue
        if filtro.somente_promessa_vencida and not linha.promessa_vencida:
            continue
        if not filtro.incluir_cobranca_suspensa and linha.cliente.suspensao_ativa(referencia):
            continue
        linhas.append(linha)
    return linhas


@dataclass
class Contagem:
    atrasados: int = 0
    a_vencer: int = 0
    imposto_de_renda: int = 0


def contar_pendentes(sessao: Session, referencia: date) -> Contagem:
    """Os números do menu, contados no banco (sem carregar nem calcular nada).

    Mesma regra das telas: em aberto, cliente não excluído; atrasado é o que
    venceu antes da referência; quem só tem IR conta à parte.
    """
    so_ir = clientes_so_imposto_de_renda(sessao)
    consulta = (
        select(Honorario.cliente_id, Honorario.vencimento < referencia, func.count())
        .join(Cliente)
        .where(Honorario.status == StatusPagamento.EM_ABERTO, Cliente.excluido_em.is_(None))
        .group_by(Honorario.cliente_id, Honorario.vencimento < referencia)
    )
    contagem = Contagem()
    for cliente_id, vencido, quantidade in sessao.execute(consulta):
        if cliente_id in so_ir:
            contagem.imposto_de_renda += quantidade
        elif vencido:
            contagem.atrasados += quantidade
        else:
            contagem.a_vencer += quantidade
    return contagem


def pendentes(sessao: Session, filtro: Filtro | None = None) -> list[LinhaHonorario]:
    filtro = filtro or Filtro()
    filtro.status = StatusPagamento.EM_ABERTO
    return consultar(sessao, filtro)


def pagos(sessao: Session, filtro: Filtro | None = None) -> list[LinhaHonorario]:
    filtro = filtro or Filtro()
    filtro.status = StatusPagamento.PAGO
    return consultar(sessao, filtro)


def agrupar_por_grupo(
    linhas: Sequence[LinhaHonorario],
) -> list[tuple[str, list[LinhaHonorario]]]:
    grupos: dict[tuple[int, str], list[LinhaHonorario]] = {}
    for linha in linhas:
        grupo = linha.grupo
        chave = (grupo.ordem, grupo.nome)
        grupos.setdefault(chave, []).append(linha)
    saida = []
    for (_, nome), itens in sorted(grupos.items()):
        itens.sort(key=lambda linha: linha.atualizacao.dias_atraso, reverse=True)
        saida.append((nome, itens))
    return saida


def _ordem_do_codigo(codigo: str) -> tuple:
    """Pelo número: "99" antes de "302" (comparar como texto poria "1000" antes de "302")."""
    codigo = (codigo or "").strip()
    return (0, int(codigo), "") if codigo.isdigit() else (1, 0, codigo)


def agrupar_por_empresa(
    linhas: Sequence[LinhaHonorario],
) -> list[tuple[str, list[LinhaHonorario], bool]]:
    """Pelo número da empresa, do menor para o maior. Quem tem mais de um honorário
    vira uma seção com título ("302 – NOME"); quem tem um só entra direto, sem
    título. Dentro da empresa, do vencimento mais antigo para o mais novo."""
    grupos: dict[int, list[LinhaHonorario]] = {}
    for linha in linhas:
        grupos.setdefault(linha.cliente.id, []).append(linha)
    ordem = sorted(grupos.values(), key=lambda itens: (
        _ordem_do_codigo(itens[0].cliente.codigo), normalizar_busca(itens[0].cliente.nome)))
    saida = []
    for itens in ordem:
        itens.sort(key=lambda linha: linha.honorario.vencimento)
        cliente = itens[0].cliente
        saida.append((f"{cliente.codigo} – {cliente.nome}", itens, len(itens) > 1))
    return saida


def agrupar_por_cliente(
    linhas: Sequence[LinhaHonorario],
) -> list[tuple[str, list[LinhaHonorario]]]:
    """Uma seção por empresa ("302 – NOME"), em ordem alfabética do nome; dentro
    dela, do vencimento mais antigo para o mais novo."""
    from ..dominio.valores import normalizar_busca

    grupos: dict[int, list[LinhaHonorario]] = {}
    for linha in linhas:
        grupos.setdefault(linha.cliente.id, []).append(linha)
    ordem = sorted(grupos.values(), key=lambda itens: (
        normalizar_busca(itens[0].cliente.nome), itens[0].cliente.codigo))
    saida = []
    for itens in ordem:
        itens.sort(key=lambda linha: linha.honorario.vencimento)
        cliente = itens[0].cliente
        saida.append((f"{cliente.codigo} – {cliente.nome}", itens))
    return saida


FAIXAS_ATRASO = (
    ("Mais de 90 dias", 91, None),
    ("61 a 90 dias", 61, 90),
    ("31 a 60 dias", 31, 60),
    ("1 a 30 dias", 1, 30),
)


def agrupar_por_faixa_de_atraso(
    linhas: Sequence[LinhaHonorario],
) -> list[tuple[str, list[LinhaHonorario]]]:
    """Seções da tela de atrasados, da dívida mais antiga para a mais recente."""
    saida = []
    for rotulo, minimo, maximo in FAIXAS_ATRASO:
        itens = [
            linha
            for linha in linhas
            if linha.atualizacao.dias_atraso >= minimo
            and (maximo is None or linha.atualizacao.dias_atraso <= maximo)
        ]
        if itens:
            itens.sort(key=lambda linha: linha.atualizacao.dias_atraso, reverse=True)
            saida.append((rotulo, itens))
    return saida


def agrupar_por_proximidade(
    linhas: Sequence[LinhaHonorario],
    referencia: date | None = None,
    dias_em_breve: int = 5,
) -> list[tuple[str, list[LinhaHonorario]]]:
    """Seções da tela de honorários no prazo: o que vence primeiro vem primeiro."""
    hoje_ = referencia or hoje()
    grupos: dict[str, list[LinhaHonorario]] = {
        "Vence hoje": [],
        f"Vence nos próximos {dias_em_breve} dias": [],
        "Vence mais adiante": [],
    }
    chaves = list(grupos)
    for linha in linhas:
        falta = (linha.honorario.vencimento - hoje_).days
        if falta <= 0:
            grupos[chaves[0]].append(linha)
        elif falta <= dias_em_breve:
            grupos[chaves[1]].append(linha)
        else:
            grupos[chaves[2]].append(linha)
    saida = []
    for rotulo, itens in grupos.items():
        if itens:
            itens.sort(key=lambda linha: linha.honorario.vencimento)
            saida.append((rotulo, itens))
    return saida


def agrupar_por_mes_pagamento(
    linhas: Sequence[LinhaHonorario],
) -> list[tuple[str, list[LinhaHonorario]]]:
    from ..dominio.valores import MESES_ABREVIADOS

    grupos: dict[tuple[int, int, bool], list[LinhaHonorario]] = {}
    for linha in linhas:
        pago_em = linha.honorario.pago_em
        # sem data de pagamento (veio da planilha antiga), o vencimento é a
        # referência, e o rótulo avisa que a data é estimada
        referencia = pago_em or linha.honorario.vencimento
        grupos.setdefault(
            (referencia.year, referencia.month, pago_em is None), []
        ).append(linha)
    saida = []
    for ano, mes, sem_data in sorted(grupos, reverse=True):
        rotulo = f"{MESES_ABREVIADOS[mes - 1]}/{ano}"
        if sem_data:
            rotulo += " (sem data de pagamento, pelo vencimento)"
        saida.append((rotulo, grupos[(ano, mes, sem_data)]))
    return saida


def total_de(linhas: Iterable[LinhaHonorario]) -> Decimal:
    return sum((linha.atualizacao.total for linha in linhas), start=ZERO)


def contar_cobrancas_no_dia(sessao: Session, dia: date) -> int:
    from sqlalchemy import func

    return sessao.scalar(
        select(func.count(Cobranca.id)).where(
            func.date(Cobranca.data_hora) == dia.isoformat(),
            Cobranca.estornada_em.is_(None),
        )
    ) or 0


# ------------------------------------------------------------- mês a mês


def mes_do_honorario(honorario: Honorario) -> tuple[int, int]:
    """Em que mês o honorário conta: o da competência; sem mês nela, o do vencimento."""
    if honorario.competencia_mes and honorario.competencia_ano:
        return honorario.competencia_ano, honorario.competencia_mes
    return honorario.vencimento.year, honorario.vencimento.month


def do_mes(
    sessao: Session, ano: int, mes: int, referencia: date | None = None
) -> list[LinhaHonorario]:
    """Tudo o que foi emitido no mês — recorrente ou avulso, pago, em aberto ou cancelado."""
    # o mês pode vir da competência ou do vencimento: busca uma janela folgada e filtra
    inicio = date(ano, mes, 1)
    consulta = (
        select(Honorario)
        .join(Cliente)
        .where(
            Cliente.excluido_em.is_(None),
            or_(
                (Honorario.competencia_ano == ano) & (Honorario.competencia_mes == mes),
                (Honorario.vencimento >= inicio)
                & (Honorario.vencimento < somar_meses(inicio, 1)),
            ),
        )
    )
    honorarios = [
        honorario for honorario in sessao.scalars(consulta).unique().all()
        if mes_do_honorario(honorario) == (ano, mes)
    ]
    atualizacoes = calculo.atualizar_varios(honorarios, referencia or hoje())
    linhas = [
        LinhaHonorario(honorario=honorario, atualizacao=atualizacoes[honorario.id])
        for honorario in honorarios
    ]
    linhas.sort(key=lambda linha: (linha.cliente.nome, linha.honorario.vencimento))
    return linhas


def meses_com_pagos(sessao: Session) -> list[tuple[int, int]]:
    """Os meses de competência com honorário pago, do mais recente ao mais antigo."""
    meses = set()
    for ano, mes, vencimento in sessao.execute(
        select(Honorario.competencia_ano, Honorario.competencia_mes, Honorario.vencimento)
        .where(Honorario.status == StatusPagamento.PAGO)
    ):
        meses.add((ano, mes) if ano and mes else (vencimento.year, vencimento.month))
    return sorted(meses, reverse=True)


def meses_com_lancamento(sessao: Session) -> list[tuple[int, int]]:
    """Os meses que têm algum honorário, do mais recente para o mais antigo."""
    meses = {
        mes_do_honorario(honorario)
        for honorario in sessao.scalars(select(Honorario)).unique().all()
    }
    return sorted(meses, reverse=True)
