"""Leitura e gravação das configurações e dos modelos de mensagem."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..dominio.enums import ChaveModelo, FormatoLinkWhatsapp, OrdemSaudacao, TipoChavePix
from ..dominio.mensagens import MODELOS_PADRAO, Recebedor
from ..infra.modelos import Configuracao, ModeloMensagem


def obter(sessao: Session, chave: str, padrao: str = "") -> str:
    linha = sessao.get(Configuracao, chave)
    return linha.valor if linha else padrao


def obter_int(sessao: Session, chave: str, padrao: int = 0) -> int:
    try:
        return int(obter(sessao, chave, str(padrao)) or padrao)
    except ValueError:
        return padrao


def obter_bool(sessao: Session, chave: str, padrao: bool = False) -> bool:
    return obter(sessao, chave, "1" if padrao else "0") in ("1", "true", "True", "sim")


def gravar(sessao: Session, chave: str, valor: str) -> None:
    linha = sessao.get(Configuracao, chave)
    if linha is None:
        sessao.add(Configuracao(chave=chave, valor=valor))
    else:
        linha.valor = valor


def recebedor(sessao: Session) -> Recebedor:
    tipo = obter(sessao, "recebedor_tipo_chave", TipoChavePix.CNPJ.value)
    return Recebedor(
        razao_social=obter(sessao, "recebedor_razao_social"),
        tipo_chave=TipoChavePix(tipo),
        chave=obter(sessao, "recebedor_chave"),
    )


def formato_link(sessao: Session) -> str:
    valor = obter(sessao, "formato_link_whatsapp", FormatoLinkWhatsapp.WA_ME.value)
    try:
        return FormatoLinkWhatsapp(valor).value
    except ValueError:
        return FormatoLinkWhatsapp.WA_ME.value


def modelos(sessao: Session) -> dict[ChaveModelo, str]:
    salvos = {m.chave: m.corpo for m in sessao.scalars(select(ModeloMensagem)).all()}
    return {chave: salvos.get(chave) or corpo for chave, corpo in MODELOS_PADRAO.items()}


def modelo(sessao: Session, chave: ChaveModelo) -> ModeloMensagem:
    linha = sessao.scalar(select(ModeloMensagem).where(ModeloMensagem.chave == chave))
    if linha is None:
        linha = ModeloMensagem(chave=chave, corpo=MODELOS_PADRAO[chave])
        sessao.add(linha)
        sessao.flush()
    return linha


def ordem_saudacao(sessao: Session) -> OrdemSaudacao:
    linha = sessao.scalar(select(ModeloMensagem).limit(1))
    return linha.ordem_saudacao if linha else OrdemSaudacao.SAUDACAO_NOME


def gravar_ordem_saudacao(sessao: Session, ordem: OrdemSaudacao) -> None:
    for linha in sessao.scalars(select(ModeloMensagem)).all():
        linha.ordem_saudacao = ordem
