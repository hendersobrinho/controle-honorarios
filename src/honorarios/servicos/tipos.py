"""Tabelas editáveis em Configurações: grupos, tipos e formas de envio."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..dominio.enums import ChaveModelo, ExigeCompetencia, Periodicidade
from ..dominio.mensagens import validar_modelo
from ..infra.modelos import Contrato, FormaEnvio, GrupoHonorario, Honorario, TipoHonorario
from .erros import ErroDeValidacao, RegistroDuplicado

# ------------------------------------------------------------------------ grupos


def listar_grupos(sessao: Session, somente_ativos: bool = False) -> list[GrupoHonorario]:
    consulta = select(GrupoHonorario)
    if somente_ativos:
        consulta = consulta.where(GrupoHonorario.ativo.is_(True))
    return list(sessao.scalars(consulta.order_by(GrupoHonorario.ordem, GrupoHonorario.nome)).all())


def criar_grupo(sessao: Session, nome: str, ordem: int | None = None) -> GrupoHonorario:
    nome = (nome or "").strip()
    if not nome:
        raise ErroDeValidacao("Informe o nome do grupo.", "nome")
    if sessao.scalar(select(GrupoHonorario).where(GrupoHonorario.nome == nome)):
        raise RegistroDuplicado(f"Já existe o grupo {nome}.")
    if ordem is None:
        maior = sessao.scalar(select(func.max(GrupoHonorario.ordem))) or 0
        ordem = maior + 10
    grupo = GrupoHonorario(nome=nome, ordem=ordem)
    sessao.add(grupo)
    sessao.flush()
    return grupo


def desativar_grupo(sessao: Session, grupo: GrupoHonorario) -> None:
    em_uso = sessao.scalar(
        select(func.count(TipoHonorario.id)).where(
            TipoHonorario.grupo_id == grupo.id, TipoHonorario.ativo.is_(True)
        )
    )
    if em_uso:
        raise ErroDeValidacao(
            f"O grupo {grupo.nome} tem {em_uso} tipo(s) ativo(s). Desative os tipos antes."
        )
    grupo.ativo = False
    sessao.flush()


# ------------------------------------------------------------------------- tipos


def listar_tipos(
    sessao: Session, somente_ativos: bool = True, grupo_id: int | None = None
) -> list[TipoHonorario]:
    consulta = select(TipoHonorario)
    if somente_ativos:
        consulta = consulta.where(TipoHonorario.ativo.is_(True))
    if grupo_id:
        consulta = consulta.where(TipoHonorario.grupo_id == grupo_id)
    return list(sessao.scalars(consulta.order_by(TipoHonorario.nome)).unique().all())


def salvar_tipo(
    sessao: Session,
    tipo: TipoHonorario | None,
    nome: str,
    grupo_id: int,
    periodicidade: Periodicidade,
    exige_competencia: ExigeCompetencia,
    texto_mensagem: str,
    texto_mensagem_empresa: str,
    texto_item_lista: str,
    ativo: bool = True,
) -> TipoHonorario:
    nome = (nome or "").strip()
    if not nome:
        raise ErroDeValidacao("Informe o nome do tipo de honorário.", "nome")
    consulta = select(TipoHonorario).where(TipoHonorario.nome == nome)
    if tipo is not None and tipo.id:
        consulta = consulta.where(TipoHonorario.id != tipo.id)
    if sessao.scalar(consulta):
        raise RegistroDuplicado(f"Já existe o tipo {nome}.")

    for campo, texto in (
        ("texto_mensagem", texto_mensagem),
        ("texto_mensagem_empresa", texto_mensagem_empresa),
        ("texto_item_lista", texto_item_lista),
    ):
        invalidas = _variaveis_invalidas(texto)
        if invalidas:
            raise ErroDeValidacao(
                "Variável inexistente no texto da mensagem: "
                + ", ".join("{" + v + "}" for v in invalidas),
                campo,
            )

    if tipo is None:
        tipo = TipoHonorario(nome=nome)
        sessao.add(tipo)
    tipo.nome = nome
    tipo.grupo_id = grupo_id
    tipo.periodicidade = periodicidade
    tipo.exige_competencia = exige_competencia
    tipo.texto_mensagem = texto_mensagem
    tipo.texto_mensagem_empresa = texto_mensagem_empresa
    tipo.texto_item_lista = texto_item_lista
    tipo.ativo = ativo
    sessao.flush()
    return tipo


def _variaveis_invalidas(texto: str) -> list[str]:
    permitidas = {
        "empresa",
        "titular",
        "nome_do_tipo",
        "competencia",
        "ano",
        "vencimento",
        "valor",
        "valor_original",
        "juros",
        "dias_atraso",
    }
    from ..dominio.mensagens import variaveis_de

    return sorted(variaveis_de(texto) - permitidas)


def desativar_tipo(sessao: Session, tipo: TipoHonorario) -> None:
    """Desativar não apaga: honorários antigos continuam apontando para o tipo."""
    tipo.ativo = False
    sessao.flush()


def tipo_em_uso(sessao: Session, tipo: TipoHonorario) -> tuple[int, int]:
    honorarios = sessao.scalar(
        select(func.count(Honorario.id)).where(Honorario.tipo_id == tipo.id)
    ) or 0
    contratos = sessao.scalar(
        select(func.count(Contrato.id)).where(
            Contrato.tipo_id == tipo.id, Contrato.excluido_em.is_(None)
        )
    ) or 0
    return honorarios, contratos


# ---------------------------------------------------------------- formas de envio


def listar_formas(sessao: Session, somente_ativas: bool = True) -> list[FormaEnvio]:
    consulta = select(FormaEnvio)
    if somente_ativas:
        consulta = consulta.where(FormaEnvio.ativo.is_(True))
    return list(sessao.scalars(consulta.order_by(FormaEnvio.ordem, FormaEnvio.nome)).all())


def criar_forma(sessao: Session, nome: str) -> FormaEnvio:
    nome = (nome or "").strip()
    if not nome:
        raise ErroDeValidacao("Informe o nome da forma de envio.", "nome")
    if sessao.scalar(select(FormaEnvio).where(FormaEnvio.nome == nome)):
        raise RegistroDuplicado(f"Já existe a forma de envio {nome}.")
    maior = sessao.scalar(select(func.max(FormaEnvio.ordem))) or 0
    forma = FormaEnvio(nome=nome, ordem=maior + 10)
    sessao.add(forma)
    sessao.flush()
    return forma


def desativar_forma(sessao: Session, forma: FormaEnvio) -> None:
    forma.ativo = False
    sessao.flush()


# ------------------------------------------------------------ modelos de mensagem


def validar_corpo_modelo(corpo: str, chave: ChaveModelo) -> list[str]:
    return validar_modelo(corpo, chave)
