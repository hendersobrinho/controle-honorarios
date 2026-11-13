"""Subtipos do cliente pessoa física (Doméstica…), cadastrados pelo usuário.

O cliente guarda o nome do subtipo; vazio é "sem subtipo". Renomear um subtipo
renomeia nos clientes que o usam. Desativar tira da lista de escolha, mas não
mexe em quem já tem.
"""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..dominio.valores import normalizar_busca
from ..infra.modelos import Cliente, SubtipoCliente
from .erros import ErroDeValidacao, RegistroDuplicado

SEM_SUBTIPO = ""
# o que uma planilha pode trazer para dizer "nenhum"
VAZIOS = {"", "-", "—", "nenhum", "nenhuma", "sem"}


def listar(sessao: Session, somente_ativos: bool = True) -> list[SubtipoCliente]:
    consulta = select(SubtipoCliente)
    if somente_ativos:
        consulta = consulta.where(SubtipoCliente.ativo.is_(True))
    return list(sessao.scalars(consulta.order_by(SubtipoCliente.nome)))


def uso(sessao: Session) -> dict[str, int]:
    """Quantos clientes (não excluídos) usam cada subtipo, pelo nome."""
    consulta = (
        select(Cliente.subtipo, func.count())
        .where(Cliente.excluido_em.is_(None), Cliente.subtipo != SEM_SUBTIPO)
        .group_by(Cliente.subtipo)
    )
    return dict(sessao.execute(consulta).all())


def _achar(sessao: Session, nome: str) -> SubtipoCliente | None:
    alvo = normalizar_busca(nome)
    return next((s for s in listar(sessao, somente_ativos=False)
                 if normalizar_busca(s.nome) == alvo), None)


def _nome_valido(sessao: Session, nome: str, atual: SubtipoCliente | None = None) -> str:
    nome = " ".join((nome or "").split())
    if not nome:
        raise ErroDeValidacao("Informe o nome do subtipo.", "nome")
    if len(nome) > 40:
        raise ErroDeValidacao("O nome do subtipo pode ter até 40 letras.", "nome")
    existente = _achar(sessao, nome)
    if existente is not None and existente is not atual:
        raise RegistroDuplicado(f"Já existe o subtipo {existente.nome}.")
    return nome


def criar(sessao: Session, nome: str) -> SubtipoCliente:
    subtipo = SubtipoCliente(nome=_nome_valido(sessao, nome))
    sessao.add(subtipo)
    sessao.flush()
    return subtipo


def renomear(sessao: Session, subtipo: SubtipoCliente, nome: str) -> None:
    """Troca o nome aqui e em todos os clientes que usam o subtipo."""
    novo = _nome_valido(sessao, nome, subtipo)
    antigo = subtipo.nome
    if novo == antigo:
        return
    sessao.execute(update(Cliente).where(Cliente.subtipo == antigo).values(subtipo=novo))
    subtipo.nome = novo
    sessao.flush()
    sessao.expire_all()


def alternar(sessao: Session, subtipo: SubtipoCliente) -> None:
    subtipo.ativo = not subtipo.ativo
    sessao.flush()


def resolver(sessao: Session, texto: str | None, criar_se_faltar: bool = False) -> str:
    """O nome cadastrado do subtipo (acento e maiúscula não importam).

    Vazio, "-" ou "nenhum" é sem subtipo. Um nome que não existe é recusado, a não
    ser com ``criar_se_faltar`` (importação de planilha), que o cadastra.
    """
    texto = " ".join((texto or "").split())
    if normalizar_busca(texto) in VAZIOS:
        return SEM_SUBTIPO
    existente = _achar(sessao, texto)
    if existente is not None:
        return existente.nome
    if criar_se_faltar:
        return criar(sessao, texto).nome
    raise ErroDeValidacao(
        f"Subtipo {texto} não existe: cadastre em Subtipos… no cadastro do cliente.",
        "subtipo",
    )
