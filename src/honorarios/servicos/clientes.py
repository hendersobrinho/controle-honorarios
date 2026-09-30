"""Cadastro de clientes, contatos e histórico de juros ao dia."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..dominio.enums import SituacaoCliente, StatusPagamento, SubtipoCliente, TipoPessoa
from ..dominio.valores import (
    ZERO,
    agora_utc,
    formatar_documento,
    hoje,
    normalizar_busca,
    normalizar_telefone,
    so_digitos,
    validar_documento,
)
from ..infra.modelos import Cliente, ClienteContato, ClienteJuros, Honorario, LogAlteracao
from . import calculo
from .erros import ErroDeValidacao, RegistroDuplicado


@dataclass
class DadosContato:
    id: int | None = None
    nome: str = ""
    nome_tratamento: str = ""
    telefone: str = ""
    email: str = ""
    principal: bool = False
    ativo: bool = True
    observacoes: str = ""


@dataclass
class DadosCliente:
    codigo: str
    nome: str
    documento: str = ""
    tipo_pessoa: TipoPessoa = TipoPessoa.PJ
    subtipo: SubtipoCliente = SubtipoCliente.NENHUM
    situacao: SituacaoCliente = SituacaoCliente.ATIVO
    observacoes: str = ""
    juros_dia: Decimal | None = None
    contatos: list[DadosContato] | None = None
    empresa_id: int | None = None


@dataclass
class LinhaCliente:
    """Uma linha da lista de clientes, com os totais já calculados."""

    cliente: Cliente
    total_em_aberto: Decimal
    quantidade_em_aberto: int
    maior_atraso: int
    juros_dia: Decimal

    @property
    def cobranca_suspensa(self) -> bool:
        return self.cliente.suspensao_ativa()


def _validar(sessao: Session, dados: DadosCliente, cliente_id: int | None = None) -> str:
    if not (dados.codigo or "").strip():
        raise ErroDeValidacao("Informe o código do cliente.", "codigo")
    if not (dados.nome or "").strip():
        raise ErroDeValidacao("Informe o nome ou a razão social.", "nome")

    documento = so_digitos(dados.documento)
    if documento and not validar_documento(documento):
        raise ErroDeValidacao(
            f"CPF/CNPJ inválido: {formatar_documento(documento)}.", "documento"
        )
    if documento:
        esperado = 11 if dados.tipo_pessoa is TipoPessoa.PF else 14
        if len(documento) != esperado:
            faltando = "CPF" if dados.tipo_pessoa is TipoPessoa.PF else "CNPJ"
            raise ErroDeValidacao(
                f"Cliente marcado como {dados.tipo_pessoa.rotulo} precisa de {faltando}.",
                "documento",
            )

    consulta = select(Cliente).where(
        Cliente.codigo == dados.codigo.strip(), Cliente.excluido_em.is_(None)
    )
    if cliente_id:
        consulta = consulta.where(Cliente.id != cliente_id)
    if sessao.scalar(consulta):
        raise RegistroDuplicado(f"Já existe cliente com o código {dados.codigo}.")

    if documento:
        consulta = select(Cliente).where(
            Cliente.documento == documento, Cliente.excluido_em.is_(None)
        )
        if cliente_id:
            consulta = consulta.where(Cliente.id != cliente_id)
        existente = sessao.scalar(consulta)
        if existente:
            raise RegistroDuplicado(
                f"O CPF/CNPJ {formatar_documento(documento)} já está no cliente "
                f"{existente.codigo} – {existente.nome}."
            )

    _validar_vinculo(sessao, dados, cliente_id)
    return documento


def _validar_vinculo(
    sessao: Session, dados: DadosCliente, cliente_id: int | None = None
) -> None:
    """O vínculo é de pessoa física para a empresa que paga por ela."""
    if dados.empresa_id is None:
        return
    if cliente_id and dados.empresa_id == cliente_id:
        raise ErroDeValidacao("O cliente não pode estar vinculado a ele mesmo.", "empresa")
    empresa = sessao.get(Cliente, dados.empresa_id)
    if empresa is None or empresa.excluido_em is not None:
        raise ErroDeValidacao("A empresa escolhida para o vínculo não existe.", "empresa")
    if dados.tipo_pessoa is not TipoPessoa.PF:
        raise ErroDeValidacao(
            "Só pessoa física é vinculada a uma empresa.", "empresa"
        )
    if empresa.tipo_pessoa is not TipoPessoa.PJ:
        raise ErroDeValidacao(
            f"{empresa.nome} não é pessoa jurídica: o vínculo aponta para a empresa "
            "que paga os honorários.",
            "empresa",
        )
    if empresa.empresa_id is not None:
        raise ErroDeValidacao(
            f"{empresa.nome} já está vinculada a outra empresa. O vínculo tem um "
            "nível só.",
            "empresa",
        )


def _aplicar_contatos(
    sessao: Session, cliente: Cliente, contatos: Sequence[DadosContato]
) -> None:
    existentes = {c.id: c for c in cliente.contatos}
    vistos: set[int] = set()
    for dados in contatos:
        telefone = normalizar_telefone(dados.telefone)
        if not (dados.nome or "").strip() and not telefone:
            continue
        alvo = existentes.get(dados.id) if dados.id else None
        if alvo is None:
            alvo = ClienteContato(cliente_id=cliente.id)
            cliente.contatos.append(alvo)
        alvo.nome = (dados.nome or "").strip()
        alvo.nome_tratamento = (dados.nome_tratamento or "").strip()
        alvo.telefone = telefone
        alvo.email = (dados.email or "").strip()
        alvo.principal = bool(dados.principal)
        alvo.ativo = bool(dados.ativo)
        alvo.observacoes = dados.observacoes or ""
        if alvo.id:
            vistos.add(alvo.id)
    for contato in list(cliente.contatos):
        if contato.id and contato.id not in vistos and contato.id in existentes:
            cliente.contatos.remove(contato)
    principais = [c for c in cliente.contatos if c.principal and c.ativo]
    if not principais:
        ativos = [c for c in cliente.contatos if c.ativo]
        if ativos:
            ativos[0].principal = True
    elif len(principais) > 1:
        for contato in principais[1:]:
            contato.principal = False


def criar(sessao: Session, dados: DadosCliente) -> Cliente:
    documento = _validar(sessao, dados)
    if dados.juros_dia is None:
        raise ErroDeValidacao("Informe o juros por dia (R$) do cliente.", "juros_dia")

    cliente = Cliente(
        codigo=dados.codigo.strip(),
        nome=dados.nome.strip(),
        nome_busca=normalizar_busca(dados.nome),
        documento=documento,
        tipo_pessoa=dados.tipo_pessoa,
        subtipo=dados.subtipo,
        situacao=dados.situacao,
        observacoes=dados.observacoes or "",
        empresa_id=dados.empresa_id,
    )
    sessao.add(cliente)
    sessao.flush()
    _aplicar_contatos(sessao, cliente, dados.contatos or [])
    registrar_juros(sessao, cliente, dados.juros_dia, hoje(), "Cadastro inicial")
    sessao.add(
        LogAlteracao(
            entidade="cliente",
            entidade_id=cliente.id,
            acao="CRIAR",
            resumo=f"{cliente.codigo} – {cliente.nome}",
        )
    )
    sessao.flush()
    return cliente


def atualizar(sessao: Session, cliente: Cliente, dados: DadosCliente) -> Cliente:
    documento = _validar(sessao, dados, cliente.id)
    antes = f"{cliente.codigo} – {cliente.nome}"
    cliente.codigo = dados.codigo.strip()
    cliente.nome = dados.nome.strip()
    cliente.nome_busca = normalizar_busca(dados.nome)
    cliente.documento = documento
    cliente.tipo_pessoa = dados.tipo_pessoa
    cliente.subtipo = dados.subtipo
    cliente.situacao = dados.situacao
    cliente.observacoes = dados.observacoes or ""
    cliente.empresa_id = dados.empresa_id
    _aplicar_contatos(sessao, cliente, dados.contatos or [])
    sessao.add(
        LogAlteracao(
            entidade="cliente",
            entidade_id=cliente.id,
            acao="EDITAR",
            antes=antes,
            depois=f"{cliente.codigo} – {cliente.nome}",
        )
    )
    sessao.flush()
    return cliente


def excluir(sessao: Session, cliente: Cliente, motivo: str = "") -> None:
    """Exclusão lógica: o histórico continua consultável."""
    abertos = sessao.scalar(
        select(func.count(Honorario.id)).where(
            Honorario.cliente_id == cliente.id,
            Honorario.status == StatusPagamento.EM_ABERTO,
        )
    )
    if abertos:
        raise ErroDeValidacao(
            f"{cliente.nome} tem {abertos} honorário(s) em aberto. "
            "Baixe, cancele ou renegocie antes de excluir."
        )
    cliente.excluido_em = agora_utc()
    cliente.situacao = SituacaoCliente.INATIVO
    sessao.add(
        LogAlteracao(
            entidade="cliente", entidade_id=cliente.id, acao="EXCLUIR", resumo=motivo
        )
    )


# ------------------------------------------------------- suspensão da cobrança


def suspender_cobranca(
    sessao: Session,
    cliente: Cliente,
    motivo: str,
    ate: date | None = None,
) -> None:
    """Tira o cliente das filas de cobrança sem mexer na dívida.

    Os honorários continuam em aberto e o juros continua correndo: o que para é
    a cobrança. Sem data de fim, a suspensão vale até ser retomada na mão.
    """
    if not (motivo or "").strip():
        raise ErroDeValidacao("Descreva por que a cobrança está sendo suspensa.", "motivo")
    if ate is not None and ate < hoje():
        raise ErroDeValidacao("A data de retomada já passou.", "ate")
    cliente.cobranca_suspensa = True
    cliente.suspensa_em = agora_utc()
    cliente.suspensa_ate = ate
    cliente.motivo_suspensao = motivo.strip()
    sessao.add(
        LogAlteracao(
            entidade="cliente",
            entidade_id=cliente.id,
            acao="SUSPENDER_COBRANCA",
            resumo=(
                f"{cliente.nome}: {motivo.strip()}"
                + (f" (até {ate:%d/%m/%Y})" if ate else "")
            ),
        )
    )
    sessao.flush()


def retomar_cobranca(sessao: Session, cliente: Cliente, motivo: str = "") -> None:
    if not cliente.cobranca_suspensa:
        raise ErroDeValidacao(f"A cobrança de {cliente.nome} não está suspensa.")
    cliente.cobranca_suspensa = False
    cliente.suspensa_em = None
    cliente.suspensa_ate = None
    cliente.motivo_suspensao = ""
    sessao.add(
        LogAlteracao(
            entidade="cliente",
            entidade_id=cliente.id,
            acao="RETOMAR_COBRANCA",
            resumo=f"{cliente.nome}: {motivo.strip()}" if motivo else cliente.nome,
        )
    )
    sessao.flush()


def suspensao(cliente: Cliente, referencia: date | None = None) -> str:
    """Frase curta explicando a suspensão (vazia quando não há)."""
    if not cliente.suspensao_ativa(referencia):
        return ""
    texto = "Cobrança suspensa"
    if cliente.suspensa_ate:
        texto += f" até {cliente.suspensa_ate:%d/%m/%Y}"
    if cliente.motivo_suspensao:
        texto += f" · {cliente.motivo_suspensao}"
    return texto


# ------------------------------------------------------------ vínculo com empresa


def vinculados(sessao: Session, cliente: Cliente) -> list[Cliente]:
    """Pessoas físicas que pagam os honorários por esta empresa."""
    return list(
        sessao.scalars(
            select(Cliente)
            .where(Cliente.empresa_id == cliente.id, Cliente.excluido_em.is_(None))
            .order_by(Cliente.nome)
        ).unique()
    )


def empresas_para_vinculo(sessao: Session, excluir_id: int | None = None) -> list[Cliente]:
    consulta = select(Cliente).where(
        Cliente.tipo_pessoa == TipoPessoa.PJ,
        Cliente.excluido_em.is_(None),
        Cliente.empresa_id.is_(None),
    )
    if excluir_id:
        consulta = consulta.where(Cliente.id != excluir_id)
    return list(sessao.scalars(consulta.order_by(Cliente.nome)).unique())


# ------------------------------------------------------------------------- juros


def registrar_juros(
    sessao: Session,
    cliente: Cliente,
    valor_dia: Decimal | str,
    vigencia_inicio: date | None = None,
    motivo: str = "",
) -> ClienteJuros:
    """Grava uma alteração de juros/dia. Vale a partir da vigência, nunca antes."""
    try:
        valor = Decimal(str(valor_dia).replace(",", "."))
    except (InvalidOperation, ValueError) as erro:
        raise ErroDeValidacao(f"Juros por dia inválido: {valor_dia!r}", "juros_dia") from erro
    if valor < 0:
        raise ErroDeValidacao("O juros por dia não pode ser negativo.", "juros_dia")

    inicio = vigencia_inicio or hoje()
    anterior = calculo.taxa_vigente_em(cliente, inicio) if cliente.juros else None

    existente = next(
        (linha for linha in cliente.juros if linha.vigencia_inicio == inicio), None
    )
    if existente is not None:
        existente.valor_dia = valor
        existente.motivo = motivo or existente.motivo
        existente.valor_anterior = anterior
        sessao.flush()
        return existente

    linha = ClienteJuros(
        cliente_id=cliente.id,
        valor_dia=valor,
        valor_anterior=anterior,
        vigencia_inicio=inicio,
        motivo=motivo,
    )
    cliente.juros.append(linha)
    sessao.add(
        LogAlteracao(
            entidade="cliente_juros",
            entidade_id=cliente.id,
            acao="JUROS",
            antes=str(anterior or ""),
            depois=str(valor),
            resumo=f"Vigência {inicio:%d/%m/%Y}: {motivo}",
        )
    )
    sessao.flush()
    return linha


def juros_atual(cliente: Cliente, referencia: date | None = None) -> Decimal:
    return calculo.taxa_vigente_em(cliente, referencia or hoje())


# ----------------------------------------------------------------------- consulta


def obter(sessao: Session, cliente_id: int) -> Cliente | None:
    return sessao.get(Cliente, cliente_id)


def por_codigo(sessao: Session, codigo: str) -> Cliente | None:
    return sessao.scalar(
        select(Cliente).where(
            Cliente.codigo == str(codigo).strip(), Cliente.excluido_em.is_(None)
        )
    )


def por_documento(sessao: Session, documento: str) -> Cliente | None:
    digitos = so_digitos(documento)
    if not digitos:
        return None
    return sessao.scalar(
        select(Cliente).where(Cliente.documento == digitos, Cliente.excluido_em.is_(None))
    )


def listar(
    sessao: Session,
    termo: str = "",
    tipo_pessoa: TipoPessoa | None = None,
    situacao: SituacaoCliente | None = None,
    somente_com_debito: bool = False,
    data_referencia: date | None = None,
) -> list[LinhaCliente]:
    """Lista com os totais em aberto já atualizados na data de referência."""
    consulta = select(Cliente).where(Cliente.excluido_em.is_(None))
    if tipo_pessoa is not None:
        consulta = consulta.where(Cliente.tipo_pessoa == tipo_pessoa)
    if situacao is not None:
        consulta = consulta.where(Cliente.situacao == situacao)
    alvo = normalizar_busca(termo)
    if alvo:
        digitos = so_digitos(termo)
        condicoes = [Cliente.nome_busca.contains(alvo), Cliente.codigo.contains(termo.strip())]
        if digitos:
            condicoes.append(Cliente.documento.contains(digitos))
        consulta = consulta.where(or_(*condicoes))

    referencia = data_referencia or hoje()
    linhas: list[LinhaCliente] = []
    for cliente in sessao.scalars(consulta.order_by(Cliente.nome)).all():
        abertos = [
            h for h in cliente.honorarios if h.status is StatusPagamento.EM_ABERTO
        ]
        atualizacoes = calculo.atualizar_varios(abertos, referencia)
        total = sum((a.total for a in atualizacoes.values()), start=ZERO)
        maior = max((a.dias_atraso for a in atualizacoes.values()), default=0)
        if somente_com_debito and not abertos:
            continue
        linhas.append(
            LinhaCliente(
                cliente=cliente,
                total_em_aberto=total,
                quantidade_em_aberto=len(abertos),
                maior_atraso=maior,
                juros_dia=juros_atual(cliente, referencia),
            )
        )
    return linhas
