"""Dados iniciais: listas da aba Configurações, tipos, grupos e modelos.

Roda sempre que o app abre e é idempotente — só cria o que falta, nunca
sobrescreve o que o usuário editou.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..dominio import mensagens as msg
from ..dominio.enums import (
    ChaveModelo,
    ExigeCompetencia,
    OrdemSaudacao,
    Periodicidade,
    TipoChavePix,
)
from .modelos import (
    Configuracao,
    FormaEnvio,
    GrupoHonorario,
    ModeloMensagem,
    TipoHonorario,
)

FORMAS_ENVIO = (
    "DP que envia para o cliente",
    "E-mail",
    "E-mail de terceiros",
    "E-mail e Malote",
    "E-mail e WhatsApp",
    "Malote",
    "Onvio",
    "WhatsApp de terceiros",
    "WhatsApp do cliente",
    "WhatsApp do Ricardo",
    "WhatsApp Grupo",
)

GRUPOS = (
    ("Mensais", 10),
    ("Trimestrais/Anuais", 20),
    ("Imposto de Renda", 30),
    ("Serviços avulsos", 40),
)

# nome, grupo, periodicidade, exige competência, textos
TIPOS = (
    (
        "Honorário mensal",
        "Mensais",
        Periodicidade.MENSAL,
        ExigeCompetencia.MES,
        (msg.TEXTO_MENSAL, msg.TEXTO_MENSAL_EMPRESA, msg.TEXTO_MENSAL_ITEM),
    ),
    (
        "Honorário trimestral",
        "Trimestrais/Anuais",
        Periodicidade.TRIMESTRAL,
        ExigeCompetencia.MES,
        (msg.TEXTO_MENSAL, msg.TEXTO_MENSAL_EMPRESA, msg.TEXTO_MENSAL_ITEM),
    ),
    (
        "Honorário anual",
        "Trimestrais/Anuais",
        Periodicidade.ANUAL,
        ExigeCompetencia.MES,
        (msg.TEXTO_MENSAL, msg.TEXTO_MENSAL_EMPRESA, msg.TEXTO_MENSAL_ITEM),
    ),
    (
        "Imposto de Renda",
        "Imposto de Renda",
        Periodicidade.ANUAL,
        ExigeCompetencia.ANO,
        (msg.TEXTO_IRPF, msg.TEXTO_IRPF_EMPRESA, msg.TEXTO_IRPF_ITEM),
    ),
    (
        "Alteração contratual",
        "Serviços avulsos",
        Periodicidade.AVULSO,
        ExigeCompetencia.NENHUMA,
        (msg.TEXTO_AVULSO, msg.TEXTO_AVULSO_EMPRESA, msg.TEXTO_AVULSO_ITEM),
    ),
    (
        "Ata de Sócios",
        "Serviços avulsos",
        Periodicidade.AVULSO,
        ExigeCompetencia.NENHUMA,
        (msg.TEXTO_AVULSO, msg.TEXTO_AVULSO_EMPRESA, msg.TEXTO_AVULSO_ITEM),
    ),
    (
        "Ganho de Capital",
        "Serviços avulsos",
        Periodicidade.AVULSO,
        ExigeCompetencia.NENHUMA,
        (msg.TEXTO_AVULSO, msg.TEXTO_AVULSO_EMPRESA, msg.TEXTO_AVULSO_ITEM),
    ),
    (
        "Abertura de empresa",
        "Serviços avulsos",
        Periodicidade.AVULSO,
        ExigeCompetencia.NENHUMA,
        (msg.TEXTO_AVULSO, msg.TEXTO_AVULSO_EMPRESA, msg.TEXTO_AVULSO_ITEM),
    ),
    (
        "Parcela de acordo",
        "Serviços avulsos",
        Periodicidade.AVULSO,
        ExigeCompetencia.NENHUMA,
        (
            "parcelamento dos honorários em aberto",
            "parcelamento dos honorários em aberto da empresa {empresa}",
            "{nome_do_tipo}, vencimento {vencimento} – {valor}",
        ),
    ),
    (
        "Certificado digital",
        "Serviços avulsos",
        Periodicidade.AVULSO,
        ExigeCompetencia.NENHUMA,
        (msg.TEXTO_AVULSO, msg.TEXTO_AVULSO_EMPRESA, msg.TEXTO_AVULSO_ITEM),
    ),
)

CONFIGURACOES = (
    ("recebedor_razao_social", "Métodos Serviços Contábeis Ltda", "Nome que aparece no PIX"),
    ("recebedor_tipo_chave", TipoChavePix.CNPJ.value, "Tipo da chave PIX"),
    ("recebedor_chave", "02.294.442/0001-13", "Chave PIX da empresa"),
    ("imagem_fundo", "", "Fundo SVG da imagem de cobrança (vazio = modelo do sistema)"),
    ("imagem_qrcode_png", "", "PNG do QR code do Pix (gerado no banco) da imagem de cobrança"),
    ("formato_link_whatsapp", "WA_ME", "wa.me, api.whatsapp.com ou whatsapp://"),
    ("dias_vence_em_breve", "5", "Quantos dias antes do vencimento pintar de âmbar"),
    ("backup_ao_fechar", "1", "Gera backup automático ao fechar o app"),
    ("backup_manter", "20", "Quantos backups manter na rotação"),
    ("tema", "claro", "claro ou escuro"),
)


def aplicar(sessao: Session) -> None:
    for nome, ordem in GRUPOS:
        if not sessao.scalar(select(GrupoHonorario).where(GrupoHonorario.nome == nome)):
            sessao.add(
                GrupoHonorario(
                    nome=nome, ordem=ordem, imposto_de_renda=(nome == "Imposto de Renda")
                )
            )
    sessao.flush()

    grupos = {g.nome: g for g in sessao.scalars(select(GrupoHonorario)).all()}
    for nome, grupo, periodicidade, exige, textos in TIPOS:
        if sessao.scalar(select(TipoHonorario).where(TipoHonorario.nome == nome)):
            continue
        sessao.add(
            TipoHonorario(
                nome=nome,
                grupo_id=grupos[grupo].id,
                periodicidade=periodicidade,
                exige_competencia=exige,
                texto_mensagem=textos[0],
                texto_mensagem_empresa=textos[1],
                texto_item_lista=textos[2],
            )
        )

    for ordem, nome in enumerate(FORMAS_ENVIO, start=1):
        if not sessao.scalar(select(FormaEnvio).where(FormaEnvio.nome == nome)):
            sessao.add(FormaEnvio(nome=nome, ordem=ordem * 10))

    for chave, corpo in msg.MODELOS_PADRAO.items():
        if not sessao.scalar(select(ModeloMensagem).where(ModeloMensagem.chave == chave)):
            sessao.add(
                ModeloMensagem(
                    chave=chave, corpo=corpo, ordem_saudacao=OrdemSaudacao.SAUDACAO_NOME
                )
            )

    for chave, valor, descricao in CONFIGURACOES:
        if not sessao.get(Configuracao, chave):
            sessao.add(Configuracao(chave=chave, valor=valor, descricao=descricao))

    sessao.flush()


def garantir(sessao: Session) -> None:
    """Idem ``aplicar``, com commit."""
    aplicar(sessao)
    sessao.commit()


__all__ = ["aplicar", "garantir", "ChaveModelo"]
