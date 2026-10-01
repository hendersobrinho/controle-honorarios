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


def salvar_grupo(
    sessao: Session,
    grupo: GrupoHonorario | None,
    nome: str,
    imposto_de_renda: bool = False,
) -> GrupoHonorario:
    """Cria ou renomeia um grupo. Só um grupo pode ser o de Imposto de Renda."""
    nome = (nome or "").strip()
    if not nome:
        raise ErroDeValidacao("Informe o nome do grupo.", "nome")
    consulta = select(GrupoHonorario).where(GrupoHonorario.nome == nome)
    if grupo is not None and grupo.id:
        consulta = consulta.where(GrupoHonorario.id != grupo.id)
    if sessao.scalar(consulta):
        raise RegistroDuplicado(f"Já existe o grupo {nome}.")
    if grupo is None:
        grupo = criar_grupo(sessao, nome)
    grupo.nome = nome
    if imposto_de_renda:
        for outro in listar_grupos(sessao):
            if outro.id != grupo.id:
                outro.imposto_de_renda = False
    grupo.imposto_de_renda = imposto_de_renda
    sessao.flush()
    return grupo


def mover_grupo(sessao: Session, grupo: GrupoHonorario, direcao: int) -> None:
    """Sobe (-1) ou desce (+1) o grupo; a ordem é a das seções nas telas."""
    grupos = listar_grupos(sessao)
    # normaliza a ordem antes de trocar, para não depender de valores repetidos
    for posicao, item in enumerate(grupos):
        item.ordem = (posicao + 1) * 10
    indice = next(i for i, item in enumerate(grupos) if item.id == grupo.id)
    alvo = indice + direcao
    if 0 <= alvo < len(grupos):
        grupos[indice].ordem, grupos[alvo].ordem = grupos[alvo].ordem, grupos[indice].ordem
    sessao.flush()


def reativar_grupo(sessao: Session, grupo: GrupoHonorario) -> None:
    grupo.ativo = True
    sessao.flush()


def grupo_do_imposto_de_renda(sessao: Session) -> GrupoHonorario | None:
    return sessao.scalar(
        select(GrupoHonorario).where(GrupoHonorario.imposto_de_renda.is_(True))
    )


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


def previa_dos_textos(
    nome_do_tipo: str,
    exige_competencia: ExigeCompetencia,
    texto_mensagem: str,
    texto_mensagem_empresa: str,
    texto_item_lista: str,
) -> tuple[str, str, str]:
    """Os três textos do tipo preenchidos com um exemplo, para a tela mostrar.

    Variável inexistente não derruba a prévia: aparece o aviso no lugar do texto.
    """
    from datetime import date
    from decimal import Decimal

    from ..dominio.mensagens import VariavelDesconhecida, renderizar
    from ..dominio.valores import Competencia, formatar_data, formatar_moeda

    if exige_competencia is ExigeCompetencia.MES:
        competencia = Competencia(2026, 8)
    elif exige_competencia is ExigeCompetencia.ANO:
        competencia = Competencia(2026)
    else:
        competencia = Competencia()
    variaveis = {
        "empresa": "EMPRESA EXEMPLO LTDA",
        "titular": "",
        "nome_do_tipo": nome_do_tipo or "Tipo",
        "competencia": competencia.rotulo(),
        "ano": str(competencia.ano or ""),
        "vencimento": formatar_data(date(2026, 9, 8)),
        "valor": formatar_moeda(Decimal("599.70")),
        "valor_original": formatar_moeda(Decimal("592.90")),
        "juros": formatar_moeda(Decimal("6.80")),
        "dias_atraso": "9",
    }
    saida = []
    for texto in (texto_mensagem, texto_mensagem_empresa, texto_item_lista):
        try:
            saida.append(renderizar(texto or "", variaveis))
        except VariavelDesconhecida as erro:
            saida.append(f"⚠ variável {{{erro.variavel}}} não existe")
    return saida[0], saida[1], saida[2]


VARIAVEIS_DO_TIPO = (
    ("competencia", "competência (08/2026)"),
    ("ano", "ano (2026)"),
    ("empresa", "nome da empresa"),
    ("nome_do_tipo", "nome deste tipo"),
    ("vencimento", "vencimento"),
    ("valor", "valor atualizado"),
    ("valor_original", "valor original"),
    ("juros", "juros"),
    ("dias_atraso", "dias de atraso"),
)


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
