"""E-mail "Clientes c/Honorários vencidos": conferir a lista do financeiro e responder.

**O fluxo.** O financeiro manda o e-mail com a lista de quem está em aberto,
sempre com o mesmo assunto. Quem cobra (quem usa este sistema) responde esse
e-mail com o andamento: o que cada cliente disse sobre o atraso, renegociação,
promessa…

**Conferir.** O e-mail do financeiro (``.eml``, PDF impresso do Outlook, ``.txt``
ou texto colado) é comparado com os honorários vencidos do sistema:

- quem **continua** na lista segue em aberto;
- quem **saiu** da lista provavelmente pagou: vira uma lista para confirmar o
  pagamento, um a um, pela tela de pagamento de sempre (nada é baixado sozinho);
- linha do e-mail que **não bate** com nenhum honorário em aberto aparece à parte.

A linha é casada pelo código do cliente, quando vem ("302 – …"), ou pelo
vencimento e pelo nome (abreviação conta como começo das palavras do nome
cadastrado: "Ipê Ind.Com." casa com "IPE INDUSTRIA E COMERCIO").

**Responder.** A resposta mantém a lista do financeiro — quem saiu não volta —
no mesmo padrão ("Cobranças de dd/mm/aaaa", Cliente · Competência · Vencimento ·
Valor, "Total do Débito") e junta, por cliente, as anotações que já vieram no
e-mail com as cobranças e respostas registradas no sistema
("24/09: Feito cobrança, prometeu pagar em 05/10 - …"), sem repetir. O sistema
não envia: copia a resposta com a formatação ou salva um rascunho ``.eml`` já
ligado à conversa (``In-Reply-To``), que o Outlook abre pronto para enviar.

Sem o e-mail do financeiro em mãos, ``montar`` faz a mesma lista a partir do
sistema.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses
from html import escape
from html.parser import HTMLParser
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..dominio.enums import FormaPagamento, ResultadoCobranca, StatusPagamento
from ..dominio.valores import (
    ZERO,
    formatar_data,
    formatar_moeda,
    normalizar_busca,
    remover_acentos,
)
from ..infra.modelos import Cliente, Cobranca, Honorario
from . import configuracoes
from . import honorarios as servico_honorarios
from .erros import ErroDeValidacao
from .honorarios import Filtro

ASSUNTO_PADRAO = "Clientes c/Honorários vencidos"

# chaves das Configurações
REMETENTE_NOME = "email_remetente_nome"
REMETENTE = "email_remetente"
PARA = "email_para"
CC = "email_cc"
ASSUNTO = "email_assunto"


# --------------------------------------------------------- configuração
@dataclass
class Remetente:
    """Quem responde (o e-mail desta pessoa), o financeiro e o assunto da conversa."""

    nome: str = ""
    email: str = ""
    para: str = ""       # o e-mail do financeiro, quando não se tem o e-mail recebido
    cc: str = ""
    assunto: str = ASSUNTO_PADRAO

    @property
    def configurado(self) -> bool:
        return bool(self.email.strip())


def remetente(sessao: Session) -> Remetente:
    return Remetente(
        nome=configuracoes.obter(sessao, REMETENTE_NOME),
        email=configuracoes.obter(sessao, REMETENTE),
        para=configuracoes.obter(sessao, PARA),
        cc=configuracoes.obter(sessao, CC),
        assunto=configuracoes.obter(sessao, ASSUNTO) or ASSUNTO_PADRAO,
    )


def gravar_remetente(sessao: Session, dados: Remetente) -> None:
    configuracoes.gravar(sessao, REMETENTE_NOME, dados.nome.strip())
    configuracoes.gravar(sessao, REMETENTE, dados.email.strip())
    configuracoes.gravar(sessao, PARA, dados.para.strip())
    configuracoes.gravar(sessao, CC, dados.cc.strip())
    configuracoes.gravar(sessao, ASSUNTO, dados.assunto.strip() or ASSUNTO_PADRAO)


# --------------------------------------------------------------- o e-mail
@dataclass
class LinhaEmail:
    competencia: str
    vencimento: date
    valor: Decimal | None

    @property
    def vencimento_texto(self) -> str:
        return formatar_data(self.vencimento)

    @property
    def valor_texto(self) -> str:
        return formatar_moeda(self.valor, com_simbolo=False) if self.valor is not None else ""


@dataclass
class BlocoCliente:
    nome: str
    linhas: list[LinhaEmail] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)
    cliente: Cliente | None = None   # None: linha do e-mail que o sistema não reconheceu

    @property
    def total(self) -> Decimal:
        return sum((linha.valor for linha in self.linhas if linha.valor is not None),
                   start=ZERO)


@dataclass
class EmailCobrancas:
    referencia: date
    remetente: Remetente
    blocos: list[BlocoCliente]
    assunto: str = ""
    para: str = ""
    cc: str = ""
    em_resposta_a: str = ""   # Message-ID do e-mail do financeiro
    referencias: str = ""

    @property
    def total(self) -> Decimal:
        return sum((bloco.total for bloco in self.blocos), start=ZERO)

    @property
    def quantidade(self) -> int:
        return sum(len(bloco.linhas) for bloco in self.blocos)


def endereco_legivel(nome: str, endereco: str) -> str:
    """ "Gerência <g@x>" como se lê (o ``formataddr`` codificaria o acento: é para o
    cabeçalho; o ``EmailMessage`` já codifica sozinho ao enviar)."""
    nome = (nome or "").strip()
    if not nome:
        return endereco
    if re.search(r'[,;:<>@"]', nome):
        nome = '"' + nome.replace('"', "'") + '"'
    return f"{nome} <{endereco}>"


def nome_no_email(cliente: Cliente) -> str:
    return f"{cliente.codigo} – {cliente.nome}"


def assunto_de_resposta(assunto: str) -> str:
    assunto = (assunto or ASSUNTO_PADRAO).strip()
    return assunto if re.match(r"^(re|res)\s*:", assunto, re.IGNORECASE) else f"RE: {assunto}"


# ------------------------------------------------------------ anotações
_RESULTADOS = {
    ResultadoCobranca.AGUARDANDO: "Feito cobrança, aguardando retorno",
    ResultadoCobranca.SEM_RESPOSTA: "Feito cobrança sem retorno",
    ResultadoCobranca.PEDIU_RENEGOCIACAO: "Feito cobrança, pediu renegociação",
    ResultadoCobranca.CONTESTOU: "Feito cobrança, contestou o valor",
    ResultadoCobranca.PAGOU: "Feito cobrança, disse que pagou",
    ResultadoCobranca.OUTRO: "Feito cobrança",
}


def _nota(cobranca: Cobranca, competencias: list[str] | None = None) -> str:
    """ "17/09: Feito cobrança sem retorno." — com a resposta anotada, se houver.

    ``competencias``: quando a cobrança foi só de parte dos honorários do cliente,
    a anotação diz de quais ("(07/2026)").
    """
    quando = cobranca.data_hora.date()
    if cobranca.resultado is ResultadoCobranca.PROMETEU_PAGAR:
        base = "Feito cobrança, prometeu pagar"
        if cobranca.promessa_data:
            base += f" em {cobranca.promessa_data:%d/%m}"
    else:
        base = _RESULTADOS.get(cobranca.resultado, "Feito cobrança")
    observacao = (cobranca.observacao or "").strip()
    texto_nota = f"{base} - {observacao}" if observacao else base
    de_quais = f" ({', '.join(competencias)})" if competencias else ""
    return f"{quando:%d/%m}: {texto_nota.rstrip('.')}{de_quais}."


def notas_do_sistema(honorarios) -> list[str]:
    """Uma anotação por mensagem enviada (o lote), na ordem em que aconteceram.

    Se a mensagem tratou só de parte destes honorários, a anotação diz de quais.
    """
    honorarios = list(honorarios)
    vistas: dict[object, Cobranca] = {}
    de_quais: dict[object, list[Honorario]] = defaultdict(list)
    for honorario in honorarios:
        for cobranca in honorario.cobrancas:
            if not cobranca.ativa:
                continue
            chave = ("lote", cobranca.lote_id) if cobranca.lote_id else ("cobranca", cobranca.id)
            vistas.setdefault(chave, cobranca)
            if honorario not in de_quais[chave]:
                de_quais[chave].append(honorario)
    notas = []
    for chave, cobranca in sorted(vistas.items(), key=lambda par: par[1].data_hora):
        parte = de_quais[chave]
        competencias = None
        if len(honorarios) > 1 and len(parte) < len(honorarios):
            competencias = [h.competencia_rotulo or h.tipo.nome
                            for h in sorted(parte, key=lambda h: h.vencimento)]
        notas.append(_nota(cobranca, competencias))
    return notas


def _nota_comparavel(nota: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", remover_acentos(nota).lower())


def _quando_da_nota(nota: str, referencia: date) -> tuple[int, int, int]:
    """A data "dd/mm" da anotação; o ano é o da referência ou o anterior."""
    achou = re.match(r"\s*(\d{2})/(\d{2})", nota)
    if not achou:
        return (9999, 12, 31)   # sem data: vai para o fim
    dia, mes = int(achou[1]), int(achou[2])
    ano = referencia.year if (mes, dia) <= (referencia.month, referencia.day) else \
        referencia.year - 1
    return (ano, mes, dia)


def juntar_notas(do_email: list[str], do_sistema: list[str], referencia: date) -> list[str]:
    """As anotações do e-mail e as do sistema, sem repetir, em ordem de data."""
    juntas: list[str] = []
    vistas: set[str] = set()
    for nota in [*do_email, *do_sistema]:
        chave = _nota_comparavel(nota)
        if chave and chave not in vistas:
            vistas.add(chave)
            juntas.append(nota)
    return sorted(juntas, key=lambda nota: _quando_da_nota(nota, referencia))


def _nota_de_suspensao(cliente: Cliente) -> list[str]:
    if not cliente.suspensao_ativa():
        return []
    ate = f" até {cliente.suspensa_ate:%d/%m}" if cliente.suspensa_ate else ""
    motivo = f": {cliente.motivo_suspensao}" if cliente.motivo_suspensao else ""
    return [f"Cobrança suspensa{ate}{motivo}"]


# ------------------------------------------------------- montar e responder
def _vencidos(sessao: Session, data: date, ate_o_dia: bool = False) -> list:
    pendentes = servico_honorarios.pendentes(sessao, Filtro(data_referencia=data))
    if ate_o_dia:
        return [linha for linha in pendentes if linha.honorario.vencimento <= data]
    return [linha for linha in pendentes if linha.honorario.vencimento < data]


def _linha_do_sistema(honorario: Honorario) -> LinhaEmail:
    return LinhaEmail(
        honorario.competencia_rotulo or honorario.tipo.nome,
        honorario.vencimento,
        honorario.saldo_aberto,
    )


def _email(sessao: Session, referencia: date, blocos, recebido=None) -> EmailCobrancas:
    """O cabeçalho da resposta: responde a quem mandou, com cópia para os demais."""
    config = remetente(sessao)
    proprio = config.email.strip().lower()
    if recebido is not None and recebido.de:
        para = recebido.de
        copia = [
            endereco_legivel(nome, endereco)
            for nome, endereco in getaddresses([recebido.para, recebido.cc])
            if endereco and endereco.lower() != proprio
            and endereco.lower() not in recebido.de.lower()
        ]
        cc = "; ".join(copia)
    else:
        para, cc = config.para, config.cc
    assunto = recebido.assunto if recebido is not None and recebido.assunto else config.assunto
    return EmailCobrancas(
        referencia=referencia, remetente=config, blocos=blocos,
        assunto=assunto_de_resposta(assunto), para=para, cc=cc,
        em_resposta_a=recebido.message_id if recebido is not None else "",
        referencias=recebido.referencias if recebido is not None else "",
    )


def montar(sessao: Session, referencia: date) -> EmailCobrancas:
    """Sem o e-mail do financeiro: a lista dos vencidos a partir do sistema."""
    por_cliente: dict[int, list] = defaultdict(list)
    for linha in _vencidos(sessao, referencia):
        por_cliente[linha.cliente.id].append(linha)
    blocos = []
    for linhas in por_cliente.values():
        linhas.sort(key=lambda linha: linha.honorario.vencimento)
        cliente = linhas[0].cliente
        honorarios = [linha.honorario for linha in linhas]
        blocos.append(BlocoCliente(
            nome=nome_no_email(cliente),
            linhas=[_linha_do_sistema(h) for h in honorarios],
            notas=notas_do_sistema(honorarios) + _nota_de_suspensao(cliente),
            cliente=cliente,
        ))
    blocos.sort(key=lambda bloco: normalizar_busca(bloco.cliente.nome))
    return _email(sessao, referencia, blocos)


def responder(sessao: Session, conferencia: Conferencia, referencia: date,
              recebido: EmailRecebido | None = None) -> EmailCobrancas:
    """A resposta ao financeiro: a lista dele, sem quem saiu, com o andamento."""
    grupos: dict[tuple, BlocoCliente] = {}
    honorarios_do_grupo: dict[tuple, list[Honorario]] = defaultdict(list)
    pagos = {id(casamento.lida) for casamento in conferencia.pagos}
    for lida in conferencia.leitura.linhas:
        if id(lida) in pagos:   # pago depois do e-mail: não volta na resposta
            continue
        linha = conferencia.casadas.get(id(lida))
        if linha is not None:
            chave = ("cliente", linha.cliente.id)
            bloco = grupos.setdefault(chave, BlocoCliente(
                nome=nome_no_email(linha.cliente), cliente=linha.cliente,
            ))
            bloco.linhas.append(_linha_do_sistema(linha.honorario))
            honorarios_do_grupo[chave].append(linha.honorario)
        else:
            nome = f"{lida.codigo} – {lida.cliente}" if lida.codigo else lida.cliente
            chave = ("texto", normalizar_busca(nome))
            bloco = grupos.setdefault(chave, BlocoCliente(nome=nome))
            bloco.linhas.append(LinhaEmail(lida.competencia, lida.vencimento, lida.valor))
        bloco.notas.extend(lida.notas)
    for incompleta in conferencia.leitura.incompletas:
        chave = ("texto", normalizar_busca(incompleta.texto))
        bloco = grupos.setdefault(chave, BlocoCliente(nome=incompleta.texto))
        bloco.notas.extend(incompleta.notas)
    for chave, bloco in grupos.items():
        do_sistema = notas_do_sistema(honorarios_do_grupo.get(chave, []))
        if bloco.cliente is not None:
            do_sistema += _nota_de_suspensao(bloco.cliente)
        bloco.notas = juntar_notas(bloco.notas, do_sistema, referencia)
    return _email(sessao, referencia, list(grupos.values()), recebido)


# ---------------------------------------------------------------- saídas
def texto(email: EmailCobrancas) -> str:
    """O corpo em texto puro (colunas separadas por tabulação)."""
    partes = [f"Cobranças de {formatar_data(email.referencia)}", "",
              "Cliente\tCompetência\tVencimento\tValor", ""]
    for bloco in email.blocos:
        if not bloco.linhas:   # cliente que veio sem vencimento e valor
            partes.append(bloco.nome)
        for linha in bloco.linhas:
            partes.append(f"{bloco.nome}\t{linha.competencia}\t{linha.vencimento_texto}\t"
                          f"{linha.valor_texto}")
        if len(bloco.linhas) > 1:
            partes.append(f"Total do Débito: {formatar_moeda(bloco.total, com_simbolo=False)}")
        partes.extend(bloco.notas)
        partes.append("")
    return "\n".join(partes).rstrip() + "\n"


_AZUL = "#1F3B73"


def html(email: EmailCobrancas) -> str:
    """O corpo formatado: uma tabela só, no visual do e-mail de hoje."""
    celula = f"padding:1px 18px 1px 0;color:{_AZUL};white-space:nowrap"
    linhas_html = []
    for bloco in email.blocos:
        if not bloco.linhas:   # cliente que veio sem vencimento e valor
            linhas_html.append(
                f"<tr><td colspan='4' style='{celula}'>{escape(bloco.nome)}</td></tr>"
            )
        for linha in bloco.linhas:
            linhas_html.append(
                f"<tr><td style='{celula}'>{escape(bloco.nome)}</td>"
                f"<td style='{celula}'>{escape(linha.competencia)}</td>"
                f"<td style='{celula}'>{linha.vencimento_texto}</td>"
                f"<td style='{celula};text-align:right'>{linha.valor_texto}</td></tr>"
            )
        if len(bloco.linhas) > 1:
            linhas_html.append(
                f"<tr><td colspan='4' style='color:{_AZUL};font-weight:bold'>Total do Débito: "
                f"{formatar_moeda(bloco.total, com_simbolo=False)}</td></tr>"
            )
        for nota in bloco.notas:
            linhas_html.append(
                f"<tr><td colspan='4' style='color:{_AZUL}'>{escape(nota)}</td></tr>"
            )
        linhas_html.append("<tr><td colspan='4' style='height:14px'></td></tr>")
    cabecalho = "".join(
        f"<th style='text-align:{lado};padding:0 18px 6px 0;color:{_AZUL}'>{nome}</th>"
        for nome, lado in (("Cliente", "left"), ("Competência", "left"),
                           ("Vencimento", "left"), ("Valor", "right"))
    )
    return (
        "<div style=\"font-family:'Segoe UI',Calibri,Arial,sans-serif;font-size:11pt\">"
        f"<p style='color:{_AZUL}'>Cobranças de {formatar_data(email.referencia)}</p>"
        "<table style='border-collapse:collapse;font-size:11pt' cellspacing='0'>"
        f"<tr>{cabecalho}</tr>{''.join(linhas_html)}</table></div>"
    )


def _enderecos(texto_enderecos: str) -> str:
    pares = getaddresses([texto_enderecos.replace(";", ",")])
    return ", ".join(endereco_legivel(*par) for par in pares if par[1])


def eml(email: EmailCobrancas) -> bytes:
    """Rascunho ``.eml``: abre no Outlook/Thunderbird pronto para revisar e enviar."""
    if not email.remetente.configurado:
        raise ErroDeValidacao("Configure o seu e-mail em Configurações → E-mail de cobranças.")
    if not _enderecos(email.para):
        raise ErroDeValidacao(
            "Falta para quem responder: abra o e-mail do financeiro ou configure o e-mail "
            "dele em Configurações → E-mail de cobranças."
        )
    mensagem = EmailMessage()
    mensagem["From"] = endereco_legivel(email.remetente.nome, email.remetente.email.strip())
    mensagem["To"] = _enderecos(email.para)
    if _enderecos(email.cc):
        mensagem["Cc"] = _enderecos(email.cc)
    mensagem["Subject"] = email.assunto
    if email.em_resposta_a:   # fica na mesma conversa do e-mail do financeiro
        mensagem["In-Reply-To"] = email.em_resposta_a
        mensagem["References"] = f"{email.referencias} {email.em_resposta_a}".strip()
    mensagem["X-Unsent"] = "1"   # o Outlook abre como rascunho, não como recebido
    mensagem.set_content(texto(email))
    mensagem.add_alternative(html(email), subtype="html")
    return bytes(mensagem)


# ----------------------------------------------------------------- ler
@dataclass
class EmailRecebido:
    """O e-mail do financeiro: o texto e, quando vem de ``.eml``, o cabeçalho."""

    texto: str
    de: str = ""
    para: str = ""
    cc: str = ""
    assunto: str = ""
    message_id: str = ""
    referencias: str = ""


@dataclass
class LinhaLida:
    cliente: str
    competencia: str
    vencimento: date
    valor: Decimal | None
    codigo: str = ""
    notas: list[str] = field(default_factory=list)


@dataclass
class Incompleta:
    """Cliente na lista sem vencimento ou valor (linha cortada ao copiar)."""

    texto: str
    notas: list[str] = field(default_factory=list)


@dataclass
class Leitura:
    data: date | None
    linhas: list[LinhaLida]
    incompletas: list[Incompleta] = field(default_factory=list)


_LINHA = re.compile(
    r"^\s*(?P<cliente>.+?)\s+(?P<competencia>\d{1,2}/\d{4}|\S+)\s+"
    r"(?P<vencimento>\d{2}/\d{2}/\d{4})\s+(?P<valor>\d{1,3}(?:[.,]?\d{3})*(?:[.,]\d{2}))\s*$"
)
_NOTA = re.compile(r"^\s*(?P<dia>\d{2}/\d{2})(?:/\d{2,4})?\s*[:\-–]\s*(?P<texto>.+)$")
_DATA = re.compile(r"Cobran[çc]as de (\d{2}/\d{2}/\d{4})", re.IGNORECASE)
_CODIGO = re.compile(r"^(?P<codigo>\d+)\s*[–-]\s*(?P<nome>.+)$")
_IGNORAR = re.compile(r"^\s*(total|cliente\s+compet)", re.IGNORECASE)


def _valor(texto_valor: str) -> Decimal | None:
    """Tolera "2,500,00" e "1.507,80": os dois últimos dígitos são os centavos."""
    digitos = re.sub(r"\D", "", texto_valor)
    if len(digitos) < 3:
        return None
    try:
        return Decimal(f"{digitos[:-2]}.{digitos[-2:]}")
    except InvalidOperation:
        return None


def _data(texto_data: str) -> date | None:
    try:
        dia, mes, ano = (int(p) for p in texto_data.split("/"))
        return date(ano, mes, dia)
    except ValueError:
        return None


def _colunas(linha: str) -> dict[str, str] | None:
    """Linha com as colunas separadas (tabulação ou 2+ espaços): a competência
    pode ter espaços ("Imposto de Renda 2026") sem grudar no nome do cliente."""
    partes = [p.strip() for p in re.split(r"\t+|\s{2,}", linha.strip()) if p.strip()]
    if len(partes) != 4 or not re.fullmatch(r"\d{2}/\d{2}/\d{4}", partes[2]):
        return None
    if not re.fullmatch(r"\d{1,3}(?:[.,]?\d{3})*(?:[.,]\d{2})", partes[3]):
        return None
    return dict(zip(("cliente", "competencia", "vencimento", "valor"), partes, strict=True))


_SO_DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_SO_VALOR = re.compile(r"^\d{1,3}(?:[.,]?\d{3})*[.,]\d{2}$")
_SO_COMPETENCIA_NUMERO = re.compile(r"^\d{1,2}/\d{4}$")
_CABECALHOS = {"cliente", "competência", "competencia", "vencimento", "valor"}
_SO_COMPETENCIA = re.compile(r"^(\d{1,2}/\d{4}|[A-Za-zÀ-ú]+)$")
_TERMINA_EM_DATA = re.compile(r"\S\s+\d{2}/\d{2}/\d{4}$")


def _cabeca(linha: str) -> bool:
    """Pedaço de linha de honorário (nome, competência) que não é data nem valor."""
    return bool(linha) and not (
        _SO_DATA.match(linha) or _SO_VALOR.match(linha) or _NOTA.match(linha)
        or _IGNORAR.match(linha) or _DATA.search(linha)
        or _colunas(linha) or _LINHA.match(linha)
    )


def _reagrupar(linhas: list[str]) -> list[str]:
    """Junta as colunas que vieram em linhas separadas (lista copiada de PDF ou de
    uma tabela): "nome / competência / vencimento / valor", uma por linha, ou
    blocos de N nomes seguidos de N vencimentos e N valores."""
    saida, i, n = [], 0, len(linhas)
    while i < n:
        atual = linhas[i]
        # nome, competência, vencimento e valor, um em cada linha
        if (i + 3 < n and _cabeca(atual) and _SO_COMPETENCIA.match(linhas[i + 1])
                and _SO_DATA.match(linhas[i + 2]) and _SO_VALOR.match(linhas[i + 3])):
            saida.append("\t".join(linhas[i:i + 4]))
            i += 4
            continue
        # a linha quebrada pelo e-mail: cliente, competência e vencimento numa linha
        # e o valor sozinho na de baixo
        if (i + 1 < n and _TERMINA_EM_DATA.search(atual) and _SO_VALOR.match(linhas[i + 1])
                and not _colunas(atual)):
            saida.append(f"{atual}\t{linhas[i + 1]}")
            i += 2
            continue
        # N linhas "nome competência", depois N vencimentos e N valores
        k = 0
        while i + k < n and _cabeca(linhas[i + k]):
            k += 1
        if k and i + 3 * k <= n and all(_SO_DATA.match(x) for x in linhas[i + k:i + 2 * k]) \
                and all(_SO_VALOR.match(x) for x in linhas[i + 2 * k:i + 3 * k]):
            for j in range(k):
                saida.append(f"{linhas[i + j]}\t{linhas[i + k + j]}\t{linhas[i + 2 * k + j]}")
            i += 3 * k
            continue
        saida.append(atual)
        i += 1
    return saida


_CITACAO_GMAIL = re.compile(r"^(On|Em)\s.+", re.IGNORECASE)
_CITACAO_FIM = re.compile(r"(wrote|escreveu)\s*:\s*$", re.IGNORECASE)
_CITACAO_OUTLOOK = re.compile(
    r"^\s*(-{2,}\s*(original message|mensagem original)\s*-{2,}|_{5,})\s*$", re.IGNORECASE
)
_CABECALHO_OUTLOOK = re.compile(r"^\s*(De|From)\s*:", re.IGNORECASE)
_ENVIADO = re.compile(r"^\s*(Enviado|Enviada|Sent|Data|Date)\s*:", re.IGNORECASE)


def sem_citacao(texto_email: str) -> str:
    """Só a mensagem nova de uma resposta: corta o e-mail anterior citado embaixo
    ("On … wrote:", "Em … escreveu:", "-----Mensagem original-----", o bloco
    "De:/Enviado:" do Outlook) e as linhas citadas com ">"."""
    linhas = texto_email.splitlines()
    for indice, linha in enumerate(linhas):
        # "On Sun, Oct 4, 2026 at 12:51 AM <x@y> wrote:" (às vezes em duas linhas)
        junto = " ".join(x.strip() for x in linhas[indice:indice + 3])
        if _CITACAO_GMAIL.match(linha.strip()) and _CITACAO_FIM.search(
                junto[:junto.lower().find("wrote:") + 6] if "wrote:" in junto.lower()
                else junto[:junto.lower().find("escreveu:") + 9]):
            linhas = linhas[:indice]
            break
        if _CITACAO_OUTLOOK.match(linha):
            linhas = linhas[:indice]
            break
        if _CABECALHO_OUTLOOK.match(linha) and any(
                _ENVIADO.match(x) for x in linhas[indice + 1:indice + 4]):
            linhas = linhas[:indice]
            break
    return "\n".join(x for x in linhas if not x.lstrip().startswith(">"))


def ler(texto_email: str) -> Leitura:
    """As linhas de honorário e as anotações de cada cliente.

    Aceita uma linha por honorário (colunas separadas por espaços ou tabulação)
    e também as colunas em linhas separadas, como sai ao copiar de um PDF. De
    uma resposta, só a mensagem nova conta (o e-mail citado embaixo é ignorado).
    """
    texto_email = sem_citacao(texto_email)
    encontrada = _DATA.search(texto_email)
    data_email = _data(encontrada.group(1)) if encontrada else None
    linhas: list[LinhaLida] = []
    incompletas: list[Incompleta] = []
    alvo: list[str] | None = None          # as anotações do último cliente lido
    incompleta: Incompleta | None = None
    ultima_nota: list[str] | None = None
    limpas = [bruta.replace("\u00a0", " ").strip() for bruta in texto_email.splitlines()]
    agrupadas = _reagrupar([linha for linha in limpas if linha])
    for indice, linha in enumerate(agrupadas):
        if _IGNORAR.match(linha) or linha.lower() in _CABECALHOS:
            continue
        casou = _colunas(linha) or _LINHA.match(linha)
        if casou:
            vencimento = _data(casou["vencimento"])
            if vencimento is None:
                continue
            nome = casou["cliente"].strip()
            codigo = ""
            com_codigo = _CODIGO.match(nome)
            if com_codigo:
                codigo, nome = com_codigo["codigo"], com_codigo["nome"].strip()
            linhas.append(LinhaLida(nome, casou["competencia"], vencimento,
                                    _valor(casou["valor"]), codigo))
            alvo, incompleta, ultima_nota = linhas[-1].notas, None, None
            continue
        nota = _NOTA.match(linha)
        if nota and alvo is not None:
            alvo.append(f"{nota['dia']}: {nota['texto'].strip()}")
            ultima_nota = alvo
            continue
        # a anotação continua na linha de baixo (frase sem ponto final)
        if ultima_nota and not ultima_nota[-1].rstrip().endswith((".", "!", "?")) \
                and not _DATA.search(linha):
            ultima_nota[-1] += " " + linha
            continue
        if incompleta is not None and _SO_COMPETENCIA_NUMERO.match(linha):
            incompleta.texto += f" {linha}"
            continue
        # nome de cliente sem vencimento nem valor, seguido de anotação ou competência
        proxima = agrupadas[indice + 1] if indice + 1 < len(agrupadas) else ""
        if _cabeca(linha) and (_NOTA.match(proxima) or _SO_COMPETENCIA_NUMERO.match(proxima)):
            incompleta = Incompleta(linha)
            incompletas.append(incompleta)
            alvo, ultima_nota = incompleta.notas, None
            continue
        ultima_nota = None
    return Leitura(data_email, linhas, incompletas)


class _TextoDoHtml(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.partes: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        if tag in ("tr", "p", "div", "br", "li"):
            self.partes.append("\n")
        elif tag in ("td", "th"):
            self.partes.append("\t")

    def handle_data(self, data) -> None:
        self.partes.append(data)


def texto_do_html(conteudo: str) -> str:
    leitor = _TextoDoHtml()
    leitor.feed(conteudo)
    return re.sub(r"[ \t]*\n[ \t]*", "\n", "".join(leitor.partes))


def abrir(caminho: Path) -> EmailRecebido:
    """O e-mail salvo: ``.eml`` (com remetente e assunto), ``.txt``/``.html`` ou PDF."""
    sufixo = caminho.suffix.lower()
    if sufixo == ".eml":
        with caminho.open("rb") as arquivo:
            mensagem = BytesParser(policy=policy.default).parse(arquivo)
        corpo = mensagem.get_body(preferencelist=("plain", "html"))
        if corpo is None:
            raise ErroDeValidacao("O e-mail não tem texto para ler.")
        conteudo = corpo.get_content()
        if corpo.get_content_subtype() == "html":
            conteudo = texto_do_html(conteudo)
        return EmailRecebido(
            texto=conteudo,
            de=str(mensagem.get("From", "")),
            para=str(mensagem.get("To", "")),
            cc=str(mensagem.get("Cc", "")),
            assunto=str(mensagem.get("Subject", "")),
            message_id=str(mensagem.get("Message-ID", "")),
            referencias=str(mensagem.get("References", "")),
        )
    if sufixo in (".html", ".htm"):
        return EmailRecebido(texto_do_html(caminho.read_text(encoding="utf-8",
                                                             errors="replace")))
    if sufixo == ".pdf":
        programa = shutil.which("pdftotext")
        if programa is None:
            raise ErroDeValidacao(
                "Para ler PDF falta o programa pdftotext (poppler). "
                "Salve o e-mail como .eml ou copie e cole o texto."
            )
        saida = subprocess.run(
            [programa, "-layout", str(caminho), "-"], capture_output=True, check=True
        )
        return EmailRecebido(saida.stdout.decode("utf-8", errors="replace"))
    return EmailRecebido(caminho.read_text(encoding="utf-8", errors="replace"))


# --------------------------------------------------------------- conferir
@dataclass
class Casamento:
    lida: LinhaLida
    linha: object   # LinhaHonorario do sistema


@dataclass
class _Pago:
    """Honorário já pago no sistema que ainda veio no e-mail."""

    honorario: Honorario

    @property
    def cliente(self) -> Cliente:
        return self.honorario.cliente


@dataclass
class Conferencia:
    data: date
    leitura: Leitura
    continuam: list[Casamento] = field(default_factory=list)
    sairam: list = field(default_factory=list)            # LinhaHonorario
    nao_encontradas: list[LinhaLida] = field(default_factory=list)
    # vieram no e-mail mas já estão pagos no sistema (baixa feita depois do e-mail)
    pagos: list[Casamento] = field(default_factory=list)
    casadas: dict[int, object] = field(default_factory=dict)   # id(lida) -> LinhaHonorario
    ignoradas: list[LinhaLida] = field(default_factory=list)   # marcadas à mão
    corrigidas: set[int] = field(default_factory=set)          # id(lida) associadas à mão

    def sairam_por_cliente(self) -> dict[Cliente, list]:
        grupos: dict[int, list] = defaultdict(list)
        clientes: dict[int, Cliente] = {}
        for linha in self.sairam:
            grupos[linha.cliente.id].append(linha)
            clientes[linha.cliente.id] = linha.cliente
        return {clientes[i]: grupos[i] for i in grupos}


def _palavras(texto_nome: str) -> list[str]:
    """Sem acento, minúsculas; a pontuação separa ("Ind.Com." vira "ind", "com")."""
    return [p for p in re.split(r"[^a-z0-9]+", remover_acentos(texto_nome).lower()) if p]


def semelhanca(lido: str, cadastrado: str) -> float:
    """Quanto do nome lido bate com o cadastrado: abreviação conta como começo."""
    lidas, nomes = _palavras(lido), _palavras(cadastrado)
    if not lidas or not nomes:
        return 0.0
    acertos = sum(1 for p in lidas if any(n.startswith(p) for n in nomes))
    return acertos / len(lidas)


MINIMO_SEMELHANCA = 0.6
TOLERANCIA_DIAS = 31   # mesma competência, vencimento diferente no e-mail


def chave_da_linha(lida: LinhaLida) -> str:
    """Identifica a linha do e-mail para guardar a correção feita à mão."""
    return f"{lida.cliente}|{lida.competencia}|{lida.vencimento.isoformat()}|{lida.valor}"


def _casar(lida: LinhaLida, candidatos: list, por_competencia: bool = False):
    """O honorário da linha do e-mail: pelo código, ou pelo vencimento e o nome.

    ``por_competencia``: segunda tentativa, para quando o vencimento do e-mail
    difere do sistema (outro dia útil, digitado diferente): mesma competência e
    vencimento a até ``TOLERANCIA_DIAS``.
    """
    if por_competencia:
        do_dia = [
            linha for linha in candidatos
            if linha.honorario.competencia_rotulo == lida.competencia
            and abs((linha.honorario.vencimento - lida.vencimento).days) <= TOLERANCIA_DIAS
        ]
    else:
        do_dia = [linha for linha in candidatos
                  if linha.honorario.vencimento == lida.vencimento]
    if lida.codigo:
        pontos = [(1.0, linha) for linha in do_dia if linha.cliente.codigo == lida.codigo]
    else:
        pontos = [(semelhanca(lida.cliente, linha.cliente.nome), linha) for linha in do_dia]
        pontos = [(nota, linha) for nota, linha in pontos if nota >= MINIMO_SEMELHANCA]
    if not pontos:
        return None
    # empate: o mesmo valor desempata (dois honorários do cliente no mesmo dia)
    return max(pontos, key=lambda par: (
        par[0], lida.valor is not None and lida.valor in (
            par[1].honorario.saldo_aberto, par[1].honorario.valor_original)
    ))[1]


def conferir(sessao: Session, leitura: Leitura, referencia: date,
             correcoes: dict[str, int] | None = None) -> Conferencia:
    """Compara o e-mail com os honorários vencidos do sistema na data dele.

    Casa com o que vence até o dia do e-mail; "saiu da lista" só vale para o que
    já tinha vencido antes dele. ``correcoes`` são as associações feitas à mão
    (chave da linha → id do honorário; 0 = ignorar a linha) e valem primeiro.
    """
    from . import calculo

    data = leitura.data or referencia
    livres = list(_vencidos(sessao, data, ate_o_dia=True))
    resultado = Conferencia(data=data, leitura=leitura)
    correcoes = correcoes or {}
    automaticas = []
    for lida in leitura.linhas:
        escolhido = correcoes.get(chave_da_linha(lida))
        if escolhido is None:
            automaticas.append(lida)
            continue
        if escolhido == 0:
            resultado.ignoradas.append(lida)
            continue
        linha = next((x for x in livres if x.honorario.id == escolhido), None)
        if linha is not None:
            livres.remove(linha)
        else:
            honorario = sessao.get(Honorario, escolhido)
            if honorario is None:   # apagado depois da correção: volta ao automático
                automaticas.append(lida)
                continue
            if honorario.status is StatusPagamento.PAGO:
                resultado.pagos.append(Casamento(lida, _Pago(honorario)))
                resultado.corrigidas.add(id(lida))
                continue
            linha = servico_honorarios.montar_linha(
                honorario, calculo.atualizar(honorario, data), data)
        resultado.continuam.append(Casamento(lida, linha))
        resultado.casadas[id(lida)] = linha
        resultado.corrigidas.add(id(lida))
    sem_par = []
    for por_competencia in (False, True):
        restantes = automaticas if not por_competencia else sem_par
        sem_par = []
        for lida in restantes:
            melhor = _casar(lida, livres, por_competencia)
            if melhor is None:
                sem_par.append(lida)
                continue
            livres.remove(melhor)
            resultado.continuam.append(Casamento(lida, melhor))
            resultado.casadas[id(lida)] = melhor
    # o que veio no e-mail mas já foi baixado no sistema (pago depois do e-mail)
    if sem_par:
        menor = min(lida.vencimento for lida in sem_par) - timedelta(days=TOLERANCIA_DIAS)
        maior = max(lida.vencimento for lida in sem_par) + timedelta(days=TOLERANCIA_DIAS)
        pagos = [_Pago(h) for h in sessao.scalars(select(Honorario).where(
            Honorario.status == StatusPagamento.PAGO, Honorario.vencimento.between(menor, maior)
        ))]
    else:
        pagos = []
    for lida in sem_par:
        pago = _casar(lida, pagos) or _casar(lida, pagos, por_competencia=True)
        if pago is None:
            resultado.nao_encontradas.append(lida)
        else:
            pagos.remove(pago)
            resultado.pagos.append(Casamento(lida, pago))
    resultado.continuam.sort(key=lambda c: leitura.linhas.index(c.lida))
    resultado.sairam = sorted(
        (linha for linha in livres if linha.honorario.vencimento < data),
        key=lambda linha: (normalizar_busca(linha.cliente.nome), linha.honorario.vencimento),
    )
    return resultado


# ------------------------------------------------- baixa dos que saíram
@dataclass
class ItemBaixa:
    """Um honorário que saiu da lista, com o que a baixa vai registrar."""

    honorario: Honorario
    saldo: Decimal
    juros: Decimal          # juros devidos até a data do pagamento
    juros_cobrados: Decimal
    valor: Decimal          # o que entra como pago
    justificativa: str = ""   # do abono, quando há juros não cobrado
    marcado: bool = True

    @property
    def cliente(self) -> Cliente:
        return self.honorario.cliente


def previa_baixa(honorarios, data_pagamento: date, com_juros: bool,
                 data_do_email: date) -> list[ItemBaixa]:
    """O que cada baixa registraria — nada é gravado aqui.

    Com juros: o valor atualizado até a data do pagamento (com acordo vigente,
    vale o valor do acordo). Sem juros: só o saldo, e os juros viram abono
    justificado pela lista do financeiro.
    """
    from . import pagamentos

    itens = []
    for honorario in honorarios:
        previa = pagamentos.previa(honorario, data_pagamento)
        if com_juros:
            cobrados = previa.juros_acordo if previa.juros_acordo is not None \
                else previa.juros_devidos
            justificativa = previa.justificativa_acordo
        else:
            cobrados = ZERO
            justificativa = (f"Saiu da lista do financeiro de {formatar_data(data_do_email)}: "
                             "baixa pelo valor original, sem juros")
        itens.append(ItemBaixa(
            honorario=honorario, saldo=previa.saldo, juros=previa.juros_devidos,
            juros_cobrados=cobrados, valor=previa.saldo + cobrados,
            justificativa=justificativa if previa.juros_devidos > cobrados else "",
        ))
    return itens


def dar_baixa(sessao: Session, itens: list[ItemBaixa], data_pagamento: date,
              forma: FormaPagamento, data_do_email: date) -> int:
    """Registra o pagamento dos itens marcados; tudo ou nada (a tela desfaz se falhar)."""
    from . import pagamentos

    marcados = [item for item in itens if item.marcado]
    if not marcados:
        raise ErroDeValidacao("Marque os honorários que foram pagos.")
    for item in marcados:
        pagamentos.registrar(sessao, item.honorario, pagamentos.DadosPagamento(
            data=data_pagamento, valor_pago=item.valor, juros_cobrados=item.juros_cobrados,
            justificativa_desconto=item.justificativa, forma_pagamento=forma,
            observacoes=f"Saiu da lista do financeiro de {formatar_data(data_do_email)}",
        ))
    return len(marcados)


__all__ = [
    "ASSUNTO_PADRAO",
    "ItemBaixa",
    "dar_baixa",
    "previa_baixa",
    "BlocoCliente",
    "Conferencia",
    "EmailCobrancas",
    "EmailRecebido",
    "Leitura",
    "LinhaLida",
    "Remetente",
    "abrir",
    "conferir",
    "eml",
    "html",
    "juntar_notas",
    "ler",
    "montar",
    "remetente",
    "responder",
    "texto",
]
