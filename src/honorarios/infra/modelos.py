"""Mapeamento ORM (SQLAlchemy 2.0).

Dinheiro é gravado como texto em coluna NUMERIC e lido de volta como
``Decimal``: SQLite não tem tipo decimal e, se deixarmos o driver converter,
perdemos centavo. Nada é apagado de verdade — as entidades têm ``excluido_em``
ou ``estornado_em``.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, validates
from sqlalchemy.types import TypeDecorator

from ..dominio.enums import (
    Canal,
    ChaveModelo,
    ExigeCompetencia,
    FormaPagamento,
    MeioCobranca,
    OrdemSaudacao,
    Periodicidade,
    ResultadoCobranca,
    SituacaoCliente,
    SituacaoEnvio,
    StatusPagamento,
    SubtipoCliente,
    TipoPessoa,
)
from ..dominio.valores import ZERO, agora_utc


class Dinheiro(TypeDecorator):
    """Decimal preservado como texto, sem passar por float."""

    impl = Numeric(14, 2)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001
        if value is None:
            return None
        return str(Decimal(str(value)))

    def process_result_value(self, value, dialect):  # noqa: ANN001
        if value is None:
            return None
        return Decimal(str(value))


class Taxa(TypeDecorator):
    """Juros ao dia: 4 casas para não perder precisão na proporção do saldo."""

    impl = Numeric(12, 4)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001
        return None if value is None else str(Decimal(str(value)))

    def process_result_value(self, value, dialect):  # noqa: ANN001
        return None if value is None else Decimal(str(value))


class EnumTexto(TypeDecorator):
    """Enum gravado como texto e devolvido como enum, não como str.

    Sem isso o ORM entrega ``str`` na leitura e as comparações com ``is`` do
    domínio passam a falhar silenciosamente.
    """

    impl = String
    cache_ok = True

    def __init__(self, enumeracao, tamanho: int = 20) -> None:
        self.enumeracao = enumeracao
        super().__init__(length=tamanho)

    def process_bind_param(self, value, dialect):  # noqa: ANN001
        if value is None:
            return None
        return value.value if isinstance(value, self.enumeracao) else str(value)

    def process_result_value(self, value, dialect):  # noqa: ANN001
        if value is None:
            return None
        return self.enumeracao(value)


class Base(DeclarativeBase):
    pass


def _criado_em() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=agora_utc, nullable=False)


# --------------------------------------------------------------- configuração


class Configuracao(Base):
    __tablename__ = "configuracao"

    chave: Mapped[str] = mapped_column(String(60), primary_key=True)
    valor: Mapped[str] = mapped_column(Text, default="", nullable=False)
    descricao: Mapped[str] = mapped_column(Text, default="", nullable=False)


class ModeloMensagem(Base):
    __tablename__ = "modelo_mensagem"

    id: Mapped[int] = mapped_column(primary_key=True)
    chave: Mapped[ChaveModelo] = mapped_column(
        EnumTexto(ChaveModelo, 20), unique=True, nullable=False
    )
    corpo: Mapped[str] = mapped_column(Text, nullable=False)
    ordem_saudacao: Mapped[OrdemSaudacao] = mapped_column(
        EnumTexto(OrdemSaudacao, 20),
        default=OrdemSaudacao.SAUDACAO_NOME, nullable=False
    )
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=agora_utc, onupdate=agora_utc, nullable=False
    )


class FormaEnvio(Base):
    __tablename__ = "forma_envio"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    ordem: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


# -------------------------------------------------------------------- cliente


class Cliente(Base):
    __tablename__ = "cliente"
    __table_args__ = (
        UniqueConstraint("codigo", name="uq_cliente_codigo"),
        Index(
            "ix_cliente_documento",
            "documento",
            unique=True,
            sqlite_where=text("documento <> ''"),
            postgresql_where=text("documento <> ''"),
        ),
        Index("ix_cliente_busca", "nome_busca"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    nome: Mapped[str] = mapped_column(String(160), nullable=False)
    nome_busca: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    documento: Mapped[str] = mapped_column(String(14), default="", nullable=False)
    tipo_pessoa: Mapped[TipoPessoa] = mapped_column(EnumTexto(TipoPessoa, 2), nullable=False)
    subtipo: Mapped[SubtipoCliente] = mapped_column(
        EnumTexto(SubtipoCliente, 20),
        default=SubtipoCliente.NENHUM, nullable=False
    )
    situacao: Mapped[SituacaoCliente] = mapped_column(
        EnumTexto(SituacaoCliente, 20),
        default=SituacaoCliente.ATIVO, nullable=False
    )
    observacoes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # pessoa física que paga os honorários por uma empresa (aponta para o cliente PJ)
    empresa_id: Mapped[int | None] = mapped_column(ForeignKey("cliente.id"), index=True)
    # cobrança suspensa: o cliente sai das filas, mas a dívida e o juros continuam
    cobranca_suspensa: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    suspensa_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspensa_ate: Mapped[date | None] = mapped_column(Date)
    motivo_suspensao: Mapped[str] = mapped_column(Text, default="", nullable=False)
    criado_em: Mapped[datetime] = _criado_em()
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=agora_utc, onupdate=agora_utc, nullable=False
    )
    excluido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    empresa: Mapped[Cliente | None] = relationship(
        back_populates="vinculados",
        remote_side="Cliente.id",
        lazy="joined",
        join_depth=1,
    )
    vinculados: Mapped[list[Cliente]] = relationship(
        back_populates="empresa", lazy="selectin"
    )
    contatos: Mapped[list[ClienteContato]] = relationship(
        back_populates="cliente", cascade="all, delete-orphan", lazy="selectin"
    )
    juros: Mapped[list[ClienteJuros]] = relationship(
        back_populates="cliente",
        cascade="all, delete-orphan",
        order_by="ClienteJuros.vigencia_inicio",
        lazy="selectin",
    )
    honorarios: Mapped[list[Honorario]] = relationship(back_populates="cliente")
    contratos: Mapped[list[Contrato]] = relationship(back_populates="cliente")

    def suspensao_ativa(self, referencia: date | None = None) -> bool:
        """A cobrança está suspensa hoje (ou na data pedida)?"""
        if not self.cobranca_suspensa:
            return False
        if self.suspensa_ate is None:
            return True
        from ..dominio.valores import hoje as _hoje

        return self.suspensa_ate >= (referencia or _hoje())

    @property
    def rotulo(self) -> str:
        return f"{self.codigo} – {self.nome}"

    @property
    def contato_principal(self) -> ClienteContato | None:
        ativos = [c for c in self.contatos if c.ativo]
        for contato in ativos:
            if contato.principal:
                return contato
        return ativos[0] if ativos else None


class ClienteContato(Base):
    __tablename__ = "cliente_contato"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("cliente.id"), index=True)
    nome: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    nome_tratamento: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    telefone: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    principal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    observacoes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    cliente: Mapped[Cliente] = relationship(back_populates="contatos")

    @property
    def tratamento_ou_nome(self) -> str:
        return (self.nome_tratamento or self.nome or "").strip()


class ClienteJuros(Base):
    """Histórico de vigência do juros ao dia. Nunca é editado, só acrescentado."""

    __tablename__ = "cliente_juros"
    __table_args__ = (
        UniqueConstraint("cliente_id", "vigencia_inicio", name="uq_juros_vigencia"),
        CheckConstraint("valor_dia >= 0", name="ck_juros_positivo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("cliente.id"), index=True)
    valor_dia: Mapped[Decimal] = mapped_column(Taxa, nullable=False)
    valor_anterior: Mapped[Decimal | None] = mapped_column(Taxa)
    vigencia_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    motivo: Mapped[str] = mapped_column(Text, default="", nullable=False)
    registrado_em: Mapped[datetime] = _criado_em()

    cliente: Mapped[Cliente] = relationship(back_populates="juros")


# ------------------------------------------------------- tipos e agrupamentos


class GrupoHonorario(Base):
    __tablename__ = "grupo_honorario"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    ordem: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # o grupo de Imposto de Renda: quem só tem honorário dele vai para a tela própria
    imposto_de_renda: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    tipos: Mapped[list[TipoHonorario]] = relationship(back_populates="grupo")


class TipoHonorario(Base):
    __tablename__ = "tipo_honorario"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    grupo_id: Mapped[int] = mapped_column(ForeignKey("grupo_honorario.id"), index=True)
    periodicidade: Mapped[Periodicidade] = mapped_column(
        EnumTexto(Periodicidade, 20), nullable=False
    )
    exige_competencia: Mapped[ExigeCompetencia] = mapped_column(
        EnumTexto(ExigeCompetencia, 10), nullable=False
    )
    texto_mensagem: Mapped[str] = mapped_column(Text, default="", nullable=False)
    texto_mensagem_empresa: Mapped[str] = mapped_column(Text, default="", nullable=False)
    texto_item_lista: Mapped[str] = mapped_column(Text, default="", nullable=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    grupo: Mapped[GrupoHonorario] = relationship(back_populates="tipos", lazy="joined")


# ------------------------------------------------------------------- contratos


class Contrato(Base):
    """Honorário recorrente: o que gera os lançamentos de cada competência."""

    __tablename__ = "contrato"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("cliente.id"), index=True)
    tipo_id: Mapped[int] = mapped_column(ForeignKey("tipo_honorario.id"))
    valor: Mapped[Decimal] = mapped_column(Dinheiro, nullable=False)
    periodicidade: Mapped[Periodicidade] = mapped_column(
        EnumTexto(Periodicidade, 20), nullable=False
    )
    dia_vencimento: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    meses_vencimento: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    meses_referencia: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    forma_envio_id: Mapped[int | None] = mapped_column(ForeignKey("forma_envio.id"))
    meio: Mapped[MeioCobranca] = mapped_column(
        EnumTexto(MeioCobranca, 10), default=MeioCobranca.BOLETO
    )
    vigencia_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    vigencia_fim: Mapped[date | None] = mapped_column(Date)
    suspenso: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    observacoes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    criado_em: Mapped[datetime] = _criado_em()
    excluido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    cliente: Mapped[Cliente] = relationship(back_populates="contratos", lazy="joined")
    tipo: Mapped[TipoHonorario] = relationship(lazy="joined")
    forma_envio: Mapped[FormaEnvio | None] = relationship(lazy="joined")
    historico: Mapped[list[ContratoHistorico]] = relationship(
        back_populates="contrato", cascade="all, delete-orphan"
    )


class ContratoHistorico(Base):
    __tablename__ = "contrato_historico"

    id: Mapped[int] = mapped_column(primary_key=True)
    contrato_id: Mapped[int] = mapped_column(ForeignKey("contrato.id"), index=True)
    campo: Mapped[str] = mapped_column(String(40), nullable=False)
    valor_anterior: Mapped[str] = mapped_column(Text, default="", nullable=False)
    valor_novo: Mapped[str] = mapped_column(Text, default="", nullable=False)
    vigencia_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    motivo: Mapped[str] = mapped_column(Text, default="", nullable=False)
    registrado_em: Mapped[datetime] = _criado_em()

    contrato: Mapped[Contrato] = relationship(back_populates="historico")


# ------------------------------------------------------------------ honorários


class Honorario(Base):
    __tablename__ = "honorario"
    __table_args__ = (
        Index(
            "ix_honorario_unico",
            "cliente_id",
            "tipo_id",
            "competencia_chave",
            unique=True,
            sqlite_where=text("status <> 'CANCELADO' AND competencia_chave <> ''"),
            postgresql_where=text("status <> 'CANCELADO' AND competencia_chave <> ''"),
        ),
        Index("ix_honorario_status", "status", "vencimento"),
        Index("ix_honorario_cliente", "cliente_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("cliente.id"), index=True)
    tipo_id: Mapped[int] = mapped_column(ForeignKey("tipo_honorario.id"))
    contrato_id: Mapped[int | None] = mapped_column(ForeignKey("contrato.id"))
    competencia_ano: Mapped[int | None] = mapped_column(Integer)
    competencia_mes: Mapped[int | None] = mapped_column(Integer)
    competencia_chave: Mapped[str] = mapped_column(String(10), default="", nullable=False)
    descricao: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    valor_original: Mapped[Decimal] = mapped_column(Dinheiro, nullable=False)
    saldo_aberto: Mapped[Decimal] = mapped_column(Dinheiro, nullable=False)
    vencimento: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    juros_dia_snapshot: Mapped[Decimal | None] = mapped_column(Taxa)
    meio: Mapped[MeioCobranca] = mapped_column(
        EnumTexto(MeioCobranca, 10), default=MeioCobranca.BOLETO
    )
    forma_envio_id: Mapped[int | None] = mapped_column(ForeignKey("forma_envio.id"))
    status: Mapped[StatusPagamento] = mapped_column(
        EnumTexto(StatusPagamento, 20),
        default=StatusPagamento.EM_ABERTO, nullable=False
    )
    situacao_envio: Mapped[SituacaoEnvio] = mapped_column(
        EnumTexto(SituacaoEnvio, 20),
        default=SituacaoEnvio.NAO_ENVIADO, nullable=False
    )
    enviado_em: Mapped[date | None] = mapped_column(Date)
    numero_boleto: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    observacoes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    pago_em: Mapped[date | None] = mapped_column(Date)
    total_congelado: Mapped[Decimal | None] = mapped_column(Dinheiro)
    cancelado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    motivo_cancelamento: Mapped[str] = mapped_column(Text, default="", nullable=False)
    renegociacao_id: Mapped[int | None] = mapped_column(ForeignKey("renegociacao.id"))
    origem_importacao_id: Mapped[int | None] = mapped_column(ForeignKey("importacao.id"))
    criado_em: Mapped[datetime] = _criado_em()

    cliente: Mapped[Cliente] = relationship(back_populates="honorarios", lazy="joined")
    tipo: Mapped[TipoHonorario] = relationship(lazy="joined")
    forma_envio: Mapped[FormaEnvio | None] = relationship(lazy="joined")
    contrato: Mapped[Contrato | None] = relationship()
    pagamentos: Mapped[list[Pagamento]] = relationship(
        back_populates="honorario",
        cascade="all, delete-orphan",
        order_by="Pagamento.data",
        lazy="selectin",
    )
    cobrancas: Mapped[list[Cobranca]] = relationship(
        back_populates="honorario",
        cascade="all, delete-orphan",
        order_by="Cobranca.data_hora",
        lazy="selectin",
    )
    acordos: Mapped[list[AcordoValor]] = relationship(
        back_populates="honorario",
        cascade="all, delete-orphan",
        order_by="AcordoValor.criado_em",
        lazy="selectin",
    )

    @property
    def competencia_rotulo(self) -> str:
        if self.competencia_ano and self.competencia_mes:
            return f"{self.competencia_mes:02d}/{self.competencia_ano}"
        if self.competencia_ano:
            return f"{self.descricao or self.tipo.nome} {self.competencia_ano}".strip()
        return self.descricao


class Notificacao(Base):
    """Aviso do sistema (vence hoje, não foi pago na data…), lido ou não.

    ``chave`` identifica o fato (ex.: ``vence:12:2026-10-02``): o mesmo fato nunca
    vira duas notificações.
    """

    __tablename__ = "notificacao"

    id: Mapped[int] = mapped_column(primary_key=True)
    chave: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    texto: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tela: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("cliente.id"), index=True)
    criada_em: Mapped[datetime] = _criado_em()
    lida_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    cliente: Mapped[Cliente | None] = relationship()

    @property
    def lida(self) -> bool:
        return self.lida_em is not None

    @validates("titulo", "chave", "tela", "tipo")
    def _caber(self, campo: str, valor: str) -> str:
        """O PostgreSQL recusa texto maior que a coluna (o SQLite aceitava calado)."""
        limite = self.__table__.c[campo].type.length
        return valor if not valor or len(valor) <= limite else valor[: limite - 1] + "…"


class EmailMensagem(Base):
    """E-mail da conversa "Clientes c/Honorários vencidos", guardado no sistema.

    Só entram os e-mails da pasta configurada (a regra do Outlook/Gmail põe lá
    apenas os do financeiro) com o assunto da conversa, e as respostas enviadas
    daqui (``enviada``). ``conta`` diz de onde veio (``gmail``, ``microsoft``,
    ``imap`` ou ``arquivo``); ``message_id`` é o identificador do e-mail e não se
    repete na mesma conta. ``ref_provedor`` é o id do e-mail no provedor (o que a
    Microsoft pede para responder).
    """

    __tablename__ = "email_mensagem"
    __table_args__ = (
        UniqueConstraint("conta", "message_id", name="uq_email_mensagem_conta_message_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conta: Mapped[str] = mapped_column(String(20), nullable=False)
    message_id: Mapped[str] = mapped_column(String(400), nullable=False)
    ref_provedor: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    conversa: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    assunto: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    de: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    para: Mapped[str] = mapped_column(Text, default="", nullable=False)
    cc: Mapped[str] = mapped_column(Text, default="", nullable=False)
    recebido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  index=True)
    corpo_html: Mapped[str] = mapped_column(Text, default="", nullable=False)
    corpo_texto: Mapped[str] = mapped_column(Text, default="", nullable=False)
    in_reply_to: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    referencias: Mapped[str] = mapped_column(Text, default="", nullable=False)
    enviada: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    lida_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    respondida_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # correções da conferência feitas à mão: {chave da linha: id do honorário, 0 = ignorar}
    correcoes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    criada_em: Mapped[datetime] = _criado_em()

    @property
    def lida(self) -> bool:
        return self.enviada or self.lida_em is not None

    @validates("message_id", "ref_provedor", "conversa", "assunto", "de", "in_reply_to")
    def _caber(self, campo: str, valor: str) -> str:
        """O PostgreSQL recusa texto maior que a coluna (o SQLite aceitava calado)."""
        limite = self.__table__.c[campo].type.length
        return valor if not valor or len(valor) <= limite else valor[:limite]


class AcordoValor(Base):
    """Valor oferecido ao cliente, congelado numa data e válido até um vencimento.

    Pagando até ``valido_ate``, vale o juros calculado em ``data_base``. Passado o
    prazo sem pagamento, o acordo simplesmente deixa de valer: o juros volta a
    correr desde o vencimento original, como se a oferta não tivesse existido.
    """

    __tablename__ = "acordo_valor"

    id: Mapped[int] = mapped_column(primary_key=True)
    honorario_id: Mapped[int] = mapped_column(ForeignKey("honorario.id"), index=True)
    data_base: Mapped[date] = mapped_column(Date, nullable=False)
    valido_ate: Mapped[date] = mapped_column(Date, nullable=False)
    saldo: Mapped[Decimal] = mapped_column(Dinheiro, nullable=False)
    juros: Mapped[Decimal] = mapped_column(Dinheiro, nullable=False)
    total: Mapped[Decimal] = mapped_column(Dinheiro, nullable=False)
    criado_em: Mapped[datetime] = _criado_em()

    honorario: Mapped[Honorario] = relationship(back_populates="acordos")


class Pagamento(Base):
    """Baixa. Os valores aqui estão congelados: mudança de juros não os altera."""

    __tablename__ = "pagamento"

    id: Mapped[int] = mapped_column(primary_key=True)
    honorario_id: Mapped[int] = mapped_column(ForeignKey("honorario.id"), index=True)
    data: Mapped[date] = mapped_column(Date, nullable=False)
    valor_pago: Mapped[Decimal] = mapped_column(Dinheiro, nullable=False)
    principal_abatido: Mapped[Decimal] = mapped_column(Dinheiro, default=ZERO, nullable=False)
    dias_atraso: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    juros_devidos: Mapped[Decimal] = mapped_column(Dinheiro, default=ZERO, nullable=False)
    juros_cobrados: Mapped[Decimal] = mapped_column(Dinheiro, default=ZERO, nullable=False)
    desconto: Mapped[Decimal] = mapped_column(Dinheiro, default=ZERO, nullable=False)
    justificativa_desconto: Mapped[str] = mapped_column(Text, default="", nullable=False)
    total: Mapped[Decimal] = mapped_column(Dinheiro, default=ZERO, nullable=False)
    forma_pagamento: Mapped[FormaPagamento] = mapped_column(
        EnumTexto(FormaPagamento, 20),
        default=FormaPagamento.PIX, nullable=False
    )
    parcial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    observacoes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    registrado_em: Mapped[datetime] = _criado_em()
    estornado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    motivo_estorno: Mapped[str] = mapped_column(Text, default="", nullable=False)

    honorario: Mapped[Honorario] = relationship(back_populates="pagamentos")

    @property
    def ativo(self) -> bool:
        return self.estornado_em is None


# ------------------------------------------------------------------- cobranças


class CobrancaLote(Base):
    """Uma mensagem enviada, que pode cobrir vários honorários do cliente."""

    __tablename__ = "cobranca_lote"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("cliente.id"), index=True)
    contato_id: Mapped[int | None] = mapped_column(ForeignKey("cliente_contato.id"))
    canal: Mapped[Canal] = mapped_column(
        EnumTexto(Canal, 20), default=Canal.WHATSAPP, nullable=False
    )
    data_hora: Mapped[datetime] = _criado_em()
    texto_enviado: Mapped[str] = mapped_column(Text, default="", nullable=False)
    total_no_momento: Mapped[Decimal] = mapped_column(Dinheiro, default=ZERO, nullable=False)

    cliente: Mapped[Cliente] = relationship(lazy="joined")
    contato: Mapped[ClienteContato | None] = relationship(lazy="joined")
    cobrancas: Mapped[list[Cobranca]] = relationship(back_populates="lote")


class Cobranca(Base):
    __tablename__ = "cobranca"

    id: Mapped[int] = mapped_column(primary_key=True)
    honorario_id: Mapped[int] = mapped_column(ForeignKey("honorario.id"), index=True)
    lote_id: Mapped[int | None] = mapped_column(ForeignKey("cobranca_lote.id"), index=True)
    data_hora: Mapped[datetime] = _criado_em()
    canal: Mapped[Canal] = mapped_column(
        EnumTexto(Canal, 20), default=Canal.WHATSAPP, nullable=False
    )
    resultado: Mapped[ResultadoCobranca] = mapped_column(
        EnumTexto(ResultadoCobranca, 30),
        default=ResultadoCobranca.SEM_RESPOSTA, nullable=False
    )
    promessa_data: Mapped[date | None] = mapped_column(Date)
    observacao: Mapped[str] = mapped_column(Text, default="", nullable=False)
    valor_atualizado_no_momento: Mapped[Decimal] = mapped_column(
        Dinheiro, default=ZERO, nullable=False
    )
    texto_enviado: Mapped[str] = mapped_column(Text, default="", nullable=False)
    origem_texto_planilha: Mapped[str] = mapped_column(Text, default="", nullable=False)
    estornada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    honorario: Mapped[Honorario] = relationship(back_populates="cobrancas")
    lote: Mapped[CobrancaLote | None] = relationship(back_populates="cobrancas")

    @property
    def ativa(self) -> bool:
        return self.estornada_em is None

    @property
    def texto(self) -> str:
        if self.texto_enviado:
            return self.texto_enviado
        if self.lote is not None:
            return self.lote.texto_enviado
        return self.origem_texto_planilha


# --------------------------------------------------------------- renegociação


class Renegociacao(Base):
    __tablename__ = "renegociacao"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("cliente.id"), index=True)
    data: Mapped[date] = mapped_column(Date, nullable=False)
    valor_original_total: Mapped[Decimal] = mapped_column(Dinheiro, nullable=False)
    juros_incluidos: Mapped[Decimal] = mapped_column(Dinheiro, default=ZERO, nullable=False)
    desconto: Mapped[Decimal] = mapped_column(Dinheiro, default=ZERO, nullable=False)
    valor_acordado: Mapped[Decimal] = mapped_column(Dinheiro, nullable=False)
    parcelas: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    observacoes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    criado_em: Mapped[datetime] = _criado_em()
    cancelada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    cliente: Mapped[Cliente] = relationship(lazy="joined")
    itens: Mapped[list[RenegociacaoItem]] = relationship(
        back_populates="renegociacao", cascade="all, delete-orphan"
    )


class RenegociacaoItem(Base):
    __tablename__ = "renegociacao_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    renegociacao_id: Mapped[int] = mapped_column(ForeignKey("renegociacao.id"), index=True)
    honorario_origem_id: Mapped[int | None] = mapped_column(ForeignKey("honorario.id"))
    honorario_gerado_id: Mapped[int | None] = mapped_column(ForeignKey("honorario.id"))
    valor: Mapped[Decimal] = mapped_column(Dinheiro, default=ZERO, nullable=False)

    renegociacao: Mapped[Renegociacao] = relationship(back_populates="itens")


# ------------------------------------------------------- importação e auditoria


class Importacao(Base):
    __tablename__ = "importacao"

    id: Mapped[int] = mapped_column(primary_key=True)
    arquivo: Mapped[str] = mapped_column(Text, nullable=False)
    aba: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    executada_em: Mapped[datetime] = _criado_em()
    clientes_criados: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    honorarios_criados: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cobrancas_criadas: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    linhas_ignoradas: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    observacoes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    erros: Mapped[list[ImportacaoErro]] = relationship(
        back_populates="importacao", cascade="all, delete-orphan"
    )


class ImportacaoErro(Base):
    __tablename__ = "importacao_erro"

    id: Mapped[int] = mapped_column(primary_key=True)
    importacao_id: Mapped[int] = mapped_column(ForeignKey("importacao.id"), index=True)
    linha: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    aba: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    campo: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    valor: Mapped[str] = mapped_column(Text, default="", nullable=False)
    gravidade: Mapped[str] = mapped_column(String(10), default="AVISO", nullable=False)
    motivo: Mapped[str] = mapped_column(Text, default="", nullable=False)

    importacao: Mapped[Importacao] = relationship(back_populates="erros")


class LogAlteracao(Base):
    __tablename__ = "log_alteracao"

    id: Mapped[int] = mapped_column(primary_key=True)
    entidade: Mapped[str] = mapped_column(String(40), nullable=False)
    entidade_id: Mapped[int | None] = mapped_column(Integer)
    acao: Mapped[str] = mapped_column(String(20), nullable=False)
    resumo: Mapped[str] = mapped_column(Text, default="", nullable=False)
    antes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    depois: Mapped[str] = mapped_column(Text, default="", nullable=False)
    registrado_em: Mapped[datetime] = _criado_em()
