"""Caixa de e-mail da conversa "Clientes c/Honorários vencidos": baixar e responder.

**Só esses e-mails.** Uma regra no Outlook (ou um filtro no Gmail) põe os e-mails
do financeiro numa pasta própria — "Cobranças", por padrão. O sistema abre só
essa pasta, e dela só guarda o que tem o assunto da conversa. Nada mais da caixa
é lido ou guardado.

**Provedores.**

- **Gmail** e **outro provedor** (IMAP/SMTP): e-mail + senha de app. No Gmail a
  pasta é o marcador.
- **Microsoft 365 (Outlook)**: pelo Microsoft Graph, com o aplicativo que o
  administrador cadastra no portal da Microsoft (permissões ``Mail.Read`` e
  ``Mail.Send``). Entra-se uma vez com um código (``microsoft.com/devicelogin``)
  e o sistema guarda a autorização renovável.

Senha de app e autorização da Microsoft ficam no cofre de senhas do sistema
operacional (``keyring``: Gerenciador de Credenciais no Windows), nunca no banco.

A rede roda fora da tela (em segundo plano): ``baixar`` e ``responder`` não
mexem no banco; ``guardar`` e ``registrar_enviada`` gravam, na tela.
"""

from __future__ import annotations

import base64
import imaplib
import json
import re
import smtplib
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, make_msgid, parsedate_to_datetime
from hashlib import sha1
from html import escape

from sqlalchemy import func, select
from sqlalchemy.orm import Session, defer

from ..dominio.valores import agora_utc, formatar_data_hora, remover_acentos
from ..infra.modelos import EmailMensagem, Notificacao
from . import configuracoes
from . import email_cobrancas as servico_email
from . import notificacoes as servico_notificacoes
from .erros import ErroDeNegocio, ErroDeValidacao

GMAIL = "gmail"
MICROSOFT = "microsoft"
IMAP = "imap"
ARQUIVO = "arquivo"   # e-mail aberto de um arquivo ou colado, sem conta

PROVEDORES = {
    GMAIL: "Gmail",
    MICROSOFT: "Microsoft 365 (Outlook)",
    IMAP: "Outro provedor (IMAP/SMTP)",
}

PASTA_PADRAO = "Cobranças"
DIAS_PARA_TRAS = 120   # quanto o IMAP olha para trás a cada verificação

# chaves das Configurações
PROVEDOR = "email_provedor"
PASTA = "email_pasta"
IMAP_HOST = "email_imap_host"
IMAP_PORTA = "email_imap_porta"
SMTP_HOST = "email_smtp_host"
SMTP_PORTA = "email_smtp_porta"
MS_CLIENTE = "email_ms_cliente"
MS_LOCATARIO = "email_ms_locatario"
ULTIMA_VERIFICACAO = "email_ultima_verificacao"

SERVICO_COFRE = "honorarios-email"


# ------------------------------------------------------------------ conta
@dataclass
class ContaEmail:
    provedor: str = ""
    endereco: str = ""        # o "Seu e-mail" das Configurações do e-mail de cobranças
    pasta: str = PASTA_PADRAO
    imap_host: str = ""
    imap_porta: int = 993
    smtp_host: str = ""
    smtp_porta: int = 587
    ms_cliente: str = ""      # ID do aplicativo (cliente) cadastrado no portal da Microsoft
    ms_locatario: str = "organizations"

    @property
    def configurada(self) -> bool:
        if self.provedor not in PROVEDORES or not self.endereco or not self.pasta:
            return False
        if self.provedor == MICROSOFT:
            return bool(self.ms_cliente)
        return bool(self.imap_host and self.smtp_host)

    @property
    def descricao(self) -> str:
        if self.provedor not in PROVEDORES:
            return "Nenhuma conta configurada"
        return f"{PROVEDORES[self.provedor]} · {self.endereco} · pasta {self.pasta}"


PADROES_GMAIL = ("imap.gmail.com", 993, "smtp.gmail.com", 587)


def conta(sessao: Session) -> ContaEmail:
    provedor = configuracoes.obter(sessao, PROVEDOR)
    dados = ContaEmail(
        provedor=provedor,
        endereco=configuracoes.obter(sessao, servico_email.REMETENTE),
        pasta=configuracoes.obter(sessao, PASTA) or PASTA_PADRAO,
        imap_host=configuracoes.obter(sessao, IMAP_HOST),
        imap_porta=configuracoes.obter_int(sessao, IMAP_PORTA, 993),
        smtp_host=configuracoes.obter(sessao, SMTP_HOST),
        smtp_porta=configuracoes.obter_int(sessao, SMTP_PORTA, 587),
        ms_cliente=configuracoes.obter(sessao, MS_CLIENTE),
        ms_locatario=configuracoes.obter(sessao, MS_LOCATARIO) or "organizations",
    )
    if provedor == GMAIL:   # o Gmail tem endereço fixo: não precisa digitar
        dados.imap_host, dados.imap_porta, dados.smtp_host, dados.smtp_porta = PADROES_GMAIL
    return dados


def gravar_conta(sessao: Session, dados: ContaEmail) -> None:
    configuracoes.gravar(sessao, PROVEDOR, dados.provedor)
    configuracoes.gravar(sessao, servico_email.REMETENTE, dados.endereco.strip())
    configuracoes.gravar(sessao, PASTA, dados.pasta.strip() or PASTA_PADRAO)
    configuracoes.gravar(sessao, IMAP_HOST, dados.imap_host.strip())
    configuracoes.gravar(sessao, IMAP_PORTA, str(dados.imap_porta))
    configuracoes.gravar(sessao, SMTP_HOST, dados.smtp_host.strip())
    configuracoes.gravar(sessao, SMTP_PORTA, str(dados.smtp_porta))
    configuracoes.gravar(sessao, MS_CLIENTE, dados.ms_cliente.strip())
    configuracoes.gravar(sessao, MS_LOCATARIO, dados.ms_locatario.strip() or "organizations")


# ------------------------------------------------------------- o cofre
def _cofre():
    try:
        import keyring
    except ImportError as falha:   # pragma: no cover - dependência do projeto
        raise ErroDeNegocio("Falta o pacote keyring para guardar a senha com segurança.") \
            from falha
    return keyring


def guardar_segredo(nome: str, valor: str) -> None:
    try:
        _cofre().set_password(SERVICO_COFRE, nome, valor)
    except Exception as falha:  # noqa: BLE001 - qualquer falha do cofre vira mensagem
        raise ErroDeNegocio(f"Não consegui guardar no cofre de senhas do sistema: {falha}") \
            from falha


def ler_segredo(nome: str) -> str:
    try:
        return _cofre().get_password(SERVICO_COFRE, nome) or ""
    except Exception:  # noqa: BLE001
        return ""


def apagar_segredo(nome: str) -> None:
    try:
        _cofre().delete_password(SERVICO_COFRE, nome)
    except Exception:  # noqa: BLE001 - não existia: nada a apagar
        pass


def chave_senha(endereco: str) -> str:
    return f"senha:{endereco.strip().lower()}"


def chave_token_microsoft(endereco: str) -> str:
    return f"microsoft:{endereco.strip().lower()}"


# ------------------------------------------------------------ mensagens
@dataclass
class MensagemBaixada:
    message_id: str
    assunto: str
    de: str
    para: str
    cc: str
    data: datetime
    html: str = ""
    texto: str = ""
    in_reply_to: str = ""
    referencias: str = ""
    conversa: str = ""
    ref_provedor: str = ""


_PREFIXOS = re.compile(r"^\s*((re|res|enc|fw|fwd|tr)\s*:\s*)+", re.IGNORECASE)


def assunto_base(assunto: str) -> str:
    """Sem "RE:"/"ENC:" e sem acento: para reconhecer a mesma conversa."""
    sem_prefixo = _PREFIXOS.sub("", assunto or "")
    return re.sub(r"\s+", " ", remover_acentos(sem_prefixo).lower()).strip()


def da_conversa(assunto: str, assunto_da_conversa: str) -> bool:
    base = assunto_base(assunto_da_conversa)
    return bool(base) and base in assunto_base(assunto)


def _texto_de_html(conteudo: str) -> str:
    return servico_email.texto_do_html(conteudo)


def de_mime(bruto: bytes, ref_provedor: str = "") -> MensagemBaixada:
    """Um e-mail no formato da internet (o que o IMAP entrega e o ``.eml`` guarda)."""
    mensagem = BytesParser(policy=policy.default).parsebytes(bruto)
    html_parte = mensagem.get_body(preferencelist=("html",))
    texto_parte = mensagem.get_body(preferencelist=("plain",))
    html = html_parte.get_content() if html_parte is not None else ""
    texto = texto_parte.get_content() if texto_parte is not None else _texto_de_html(html)
    try:
        data = parsedate_to_datetime(str(mensagem.get("Date", "")))
    except (TypeError, ValueError):
        data = agora_utc()
    if data.tzinfo is None:
        data = data.replace(tzinfo=UTC)
    message_id = str(mensagem.get("Message-ID", "")).strip()
    if not message_id:   # sem identificador: um estável a partir do conteúdo
        message_id = f"<sem-id-{sha1(bruto).hexdigest()}@honorarios>"
    referencias = str(mensagem.get("References", "")).strip()
    return MensagemBaixada(
        message_id=message_id,
        assunto=str(mensagem.get("Subject", "")),
        de=str(mensagem.get("From", "")),
        para=str(mensagem.get("To", "")),
        cc=str(mensagem.get("Cc", "")),
        data=data,
        html=html,
        texto=texto,
        in_reply_to=str(mensagem.get("In-Reply-To", "")).strip(),
        referencias=referencias,
        conversa=(referencias.split() or [message_id])[0],
        ref_provedor=ref_provedor,
    )


def _citacao_html(original: Original) -> str:
    """O e-mail original embaixo da resposta, como o Outlook faz."""
    corpo = original.corpo_html or f"<pre>{escape(original.corpo_texto)}</pre>"
    return (
        "<br><hr style='border:none;border-top:1px solid #b5c4df'>"
        "<div style=\"font-family:'Segoe UI',Calibri,Arial,sans-serif;font-size:10pt\">"
        f"<b>De:</b> {escape(original.de)}<br>"
        f"<b>Enviado:</b> {formatar_data_hora(original.recebido_em)}<br>"
        f"<b>Para:</b> {escape(original.para)}<br>"
        + (f"<b>Cc:</b> {escape(original.cc)}<br>" if original.cc else "")
        + f"<b>Assunto:</b> {escape(original.assunto)}</div><br>{corpo}"
    )


def _citacao_texto(original: Original) -> str:
    linhas = (original.corpo_texto or _texto_de_html(original.corpo_html)).splitlines()
    return (f"\n\n-----Mensagem original-----\nDe: {original.de}\n"
            f"Enviado: {formatar_data_hora(original.recebido_em)}\n"
            f"Assunto: {original.assunto}\n\n" + "\n".join(f"> {linha}" for linha in linhas))


@dataclass(frozen=True)
class Original:
    """Cópia solta do e-mail a responder: vai para a thread de envio sem levar a
    sessão do banco junto (o objeto do banco pode ser recarregado no meio)."""

    conta: str
    message_id: str
    ref_provedor: str
    conversa: str
    assunto: str
    de: str
    para: str
    cc: str
    recebido_em: datetime
    corpo_html: str
    corpo_texto: str
    referencias: str


def original_de(mensagem: EmailMensagem) -> Original:
    return Original(
        conta=mensagem.conta, message_id=mensagem.message_id,
        ref_provedor=mensagem.ref_provedor, conversa=mensagem.conversa,
        assunto=mensagem.assunto, de=mensagem.de, para=mensagem.para, cc=mensagem.cc,
        recebido_em=mensagem.recebido_em, corpo_html=mensagem.corpo_html,
        corpo_texto=mensagem.corpo_texto, referencias=mensagem.referencias,
    )


@dataclass
class Resposta:
    """O que vai ser enviado: destinatários, assunto e corpo (sem a citação)."""

    para: str
    cc: str
    assunto: str
    html: str
    texto: str


def _lista_de_enderecos(texto_enderecos: str) -> list[tuple[str, str]]:
    return [(nome, endereco) for nome, endereco in
            getaddresses([(texto_enderecos or "").replace(";", ",")]) if endereco]


# ---------------------------------------------------------- IMAP e SMTP
def pasta_imap(nome: str) -> str:
    """O nome da pasta no "UTF-7 modificado" do IMAP ("Cobranças" → "Cobran&AOc-as")."""
    saida, pendente = [], []

    def descarregar():
        if pendente:
            bruto = "".join(pendente).encode("utf-16-be")
            codigo = base64.b64encode(bruto).decode("ascii").rstrip("=").replace("/", ",")
            saida.append(f"&{codigo}-")
            pendente.clear()

    for letra in nome:
        if 0x20 <= ord(letra) <= 0x7E:
            descarregar()
            saida.append("&-" if letra == "&" else letra)
        else:
            pendente.append(letra)
    descarregar()
    return "".join(saida)


class CaixaImap:
    """Gmail e outros provedores: lê a pasta por IMAP e responde por SMTP."""

    def __init__(self, conta_email: ContaEmail, senha: str) -> None:
        self.conta = conta_email
        self.senha = senha

    def _entrar(self) -> imaplib.IMAP4_SSL:
        try:
            imap = imaplib.IMAP4_SSL(self.conta.imap_host, self.conta.imap_porta,
                                     ssl_context=ssl.create_default_context(), timeout=30)
        except OSError as falha:
            raise ErroDeNegocio(f"Não consegui conectar em {self.conta.imap_host}: {falha}") \
                from falha
        try:
            imap.login(self.conta.endereco, self.senha)
        except imaplib.IMAP4.error as falha:
            raise ErroDeNegocio(
                "O provedor recusou o e-mail e a senha. No Gmail, use uma senha de app "
                "(myaccount.google.com/apppasswords), não a senha normal."
            ) from falha
        estado, _ = imap.select(f'"{pasta_imap(self.conta.pasta)}"', readonly=True)
        if estado != "OK":
            imap.logout()
            raise ErroDeNegocio(
                f"Não encontrei a pasta \"{self.conta.pasta}\" na caixa. Crie a pasta (no Gmail, "
                "o marcador) e a regra que leva os e-mails do financeiro para ela."
            )
        return imap

    def testar(self) -> str:
        imap = self._entrar()
        try:
            _, dados = imap.uid("SEARCH", None, "ALL")
            quantos = len((dados[0] or b"").split())
        finally:
            imap.logout()
        return f"Conectado: {quantos} e-mail(s) na pasta \"{self.conta.pasta}\"."

    def baixar(self, ja_tenho: set[str], assunto_da_conversa: str) -> list[MensagemBaixada]:
        """Os e-mails novos da pasta com o assunto da conversa (sem marcar como lidos)."""
        desde = (date.today() - timedelta(days=DIAS_PARA_TRAS)).strftime("%d-%b-%Y")
        imap = self._entrar()
        novas: list[MensagemBaixada] = []
        try:
            _, dados = imap.uid("SEARCH", None, "SINCE", desde)
            uids = (dados[0] or b"").split()
            if not uids:
                return []
            gmail = self.conta.provedor == GMAIL
            conversas: set[bytes] = set()
            querer = self._da_conversa(imap, uids, ja_tenho, assunto_da_conversa,
                                       conversas if gmail else None)
            novas.extend(self._baixar_uids(imap, querer))
            vistos = ja_tenho | {m.message_id for m in novas}
            if gmail and conversas:
                novas.extend(self._resto_das_conversas(imap, conversas, vistos,
                                                       assunto_da_conversa))
        finally:
            imap.logout()
        return novas

    @staticmethod
    def _da_conversa(imap, uids: list[bytes], ja_tenho: set[str], assunto_da_conversa: str,
                     conversas: set[bytes] | None) -> list[bytes]:
        """Os uids com o assunto da conversa que ainda não foram baixados.

        No Gmail, guarda também o id da conversa (``X-GM-THRID``) de cada um.
        """
        campos = "BODY.PEEK[HEADER.FIELDS (MESSAGE-ID SUBJECT)]"
        if conversas is not None:
            campos = f"X-GM-THRID {campos}"
        _, cabecalhos = imap.uid("FETCH", b",".join(uids).decode(), f"({campos})")
        querer = []
        for parte in cabecalhos:
            if not isinstance(parte, tuple):
                continue
            uid = re.search(rb"UID (\d+)", parte[0])
            cabecalho = BytesParser(policy=policy.default).parsebytes(parte[1])
            if not uid or not da_conversa(str(cabecalho.get("Subject", "")),
                                          assunto_da_conversa):
                continue
            conversa = re.search(rb"X-GM-THRID (\d+)", parte[0])
            if conversas is not None and conversa:
                conversas.add(conversa.group(1))
            if str(cabecalho.get("Message-ID", "")).strip() not in ja_tenho:
                querer.append(uid.group(1))
        return querer

    @staticmethod
    def _baixar_uids(imap, uids: list[bytes], prefixo: str = "") -> list[MensagemBaixada]:
        baixadas = []
        for uid in uids:
            _, partes = imap.uid("FETCH", uid.decode(), "(BODY.PEEK[])")
            for parte in partes:
                if isinstance(parte, tuple):
                    baixadas.append(de_mime(parte[1], ref_provedor=prefixo + uid.decode()))
        return baixadas

    def _resto_das_conversas(self, imap, conversas: set[bytes], vistos: set[str],
                             assunto_da_conversa: str) -> list[MensagemBaixada]:
        """Gmail: as respostas das mesmas conversas que o filtro não marcou.

        As respostas (as suas enviadas pelo Gmail e as que chegam depois) nem sempre
        recebem o marcador. Elas são buscadas em "Todos os e-mails", mas só as das
        conversas que já estão na pasta e com o assunto da conversa.
        """
        todos = self._pasta_todos(imap)
        if todos is None:
            return []
        estado, _ = imap.select(todos, readonly=True)
        if estado != "OK":
            return []
        uids: list[bytes] = []
        for conversa in conversas:
            _, dados = imap.uid("SEARCH", None, "X-GM-THRID", conversa.decode())
            uids.extend((dados[0] or b"").split())
        if not uids:
            return []
        querer = self._da_conversa(imap, uids, vistos, assunto_da_conversa, None)
        return self._baixar_uids(imap, querer, prefixo="todos:")

    @staticmethod
    def _pasta_todos(imap) -> str | None:
        """A pasta "Todos os e-mails" do Gmail (o nome muda com o idioma: vale a marca \\All)."""
        estado, linhas = imap.list()
        if estado != "OK":
            return None
        for linha in linhas or []:
            texto = linha.decode("utf-8", "replace") if isinstance(linha, bytes) else str(linha)
            if "\\All" in texto:
                nome = re.search(r'"([^"]+)"\s*$', texto) or re.search(r"(\S+)\s*$", texto)
                if nome:
                    return f'"{nome.group(1)}"'
        return None

    def responder(self, original: Original, resposta: Resposta) -> MensagemBaixada:
        mensagem = EmailMessage()
        dominio = self.conta.endereco.split("@")[-1] or "honorarios"
        mensagem["Message-ID"] = make_msgid(domain=dominio)
        mensagem["From"] = self.conta.endereco
        mensagem["To"] = ", ".join(servico_email.endereco_legivel(*par)
                                   for par in _lista_de_enderecos(resposta.para))
        if _lista_de_enderecos(resposta.cc):
            mensagem["Cc"] = ", ".join(servico_email.endereco_legivel(*par)
                                       for par in _lista_de_enderecos(resposta.cc))
        mensagem["Subject"] = resposta.assunto
        mensagem["In-Reply-To"] = original.message_id
        mensagem["References"] = f"{original.referencias} {original.message_id}".strip()
        mensagem.set_content(resposta.texto + _citacao_texto(original))
        mensagem.add_alternative(resposta.html + _citacao_html(original), subtype="html")
        if not _lista_de_enderecos(resposta.para):
            raise ErroDeValidacao("Informe para quem vai a resposta.")
        try:
            with smtplib.SMTP(self.conta.smtp_host, self.conta.smtp_porta, timeout=30) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(self.conta.endereco, self.senha)
                smtp.send_message(mensagem)
        except smtplib.SMTPAuthenticationError as falha:
            raise ErroDeNegocio("O provedor recusou a senha ao enviar. Confira a senha de app.") \
                from falha
        except (OSError, smtplib.SMTPException) as falha:
            raise ErroDeNegocio(f"Não consegui enviar a resposta: {falha}") from falha
        return de_mime(bytes(mensagem))


# ------------------------------------------------------- Microsoft Graph
GRAPH = "https://graph.microsoft.com/v1.0"
ESCOPOS = ("offline_access https://graph.microsoft.com/Mail.Read "
           "https://graph.microsoft.com/Mail.Send")


def _http(metodo: str, url: str, token: str = "", corpo: dict | None = None,
          formulario: dict | None = None, cabecalhos: dict | None = None) -> dict:
    """Uma chamada HTTP com resposta JSON (função solta para os testes trocarem)."""
    pedido_cabecalhos = dict(cabecalhos or {})
    dados = None
    if formulario is not None:
        dados = urllib.parse.urlencode(formulario).encode()
        pedido_cabecalhos["Content-Type"] = "application/x-www-form-urlencoded"
    elif corpo is not None:
        dados = json.dumps(corpo).encode()
        pedido_cabecalhos["Content-Type"] = "application/json"
    if token:
        pedido_cabecalhos["Authorization"] = f"Bearer {token}"
    pedido = urllib.request.Request(url, data=dados, method=metodo, headers=pedido_cabecalhos)
    try:
        with urllib.request.urlopen(pedido, timeout=30) as resposta:
            conteudo = resposta.read()
    except urllib.error.HTTPError as falha:
        conteudo = falha.read()
        try:
            erro = json.loads(conteudo or b"{}")
        except ValueError:
            erro = {}
        if isinstance(erro, dict) and "error" in erro:
            return {"_status": falha.code, **erro}
        raise ErroDeNegocio(f"A Microsoft respondeu {falha.code}.") from falha
    except OSError as falha:
        raise ErroDeNegocio(f"Sem conexão com a Microsoft: {falha}") from falha
    return json.loads(conteudo) if conteudo else {}


@dataclass
class CodigoDeEntrada:
    """O que mostrar para a pessoa entrar: o código e o endereço."""

    codigo: str
    endereco: str
    device_code: str
    intervalo: int
    expira_em: float


class CaixaMicrosoft:
    """Microsoft 365: lê a pasta e responde pelo Microsoft Graph."""

    def __init__(self, conta_email: ContaEmail) -> None:
        self.conta = conta_email
        self._token = ""
        self._token_vale_ate = 0.0

    @property
    def _login(self) -> str:
        return f"https://login.microsoftonline.com/{self.conta.ms_locatario}/oauth2/v2.0"

    # -- entrada (uma vez): código em microsoft.com/devicelogin
    def iniciar_entrada(self) -> CodigoDeEntrada:
        resposta = _http("POST", f"{self._login}/devicecode", formulario={
            "client_id": self.conta.ms_cliente, "scope": ESCOPOS,
        })
        if "error" in resposta:
            raise ErroDeNegocio(
                "A Microsoft recusou o aplicativo: confira o ID do aplicativo e do locatário "
                f"({resposta.get('error_description', resposta['error'])})."
            )
        return CodigoDeEntrada(
            codigo=resposta["user_code"],
            endereco=resposta.get("verification_uri", "https://microsoft.com/devicelogin"),
            device_code=resposta["device_code"],
            intervalo=int(resposta.get("interval", 5)),
            expira_em=time.monotonic() + int(resposta.get("expires_in", 900)),
        )

    def concluir_entrada(self, codigo: CodigoDeEntrada, cancelado=lambda: False) -> None:
        """Espera a pessoa entrar (em segundo plano) e guarda a autorização no cofre."""
        intervalo = codigo.intervalo
        while time.monotonic() < codigo.expira_em:
            if cancelado():
                raise ErroDeNegocio("Entrada cancelada.")
            resposta = _http("POST", f"{self._login}/token", formulario={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": self.conta.ms_cliente, "device_code": codigo.device_code,
            })
            erro = resposta.get("error")
            if erro == "authorization_pending":
                time.sleep(intervalo)
                continue
            if erro == "slow_down":
                intervalo += 5
                time.sleep(intervalo)
                continue
            if erro:
                raise ErroDeNegocio(
                    f"A entrada não foi concluída: {resposta.get('error_description', erro)}"
                )
            self._guardar_tokens(resposta)
            return
        raise ErroDeNegocio("O código expirou. Clique em Entrar de novo.")

    def _guardar_tokens(self, resposta: dict) -> None:
        if resposta.get("refresh_token"):
            guardar_segredo(chave_token_microsoft(self.conta.endereco), resposta["refresh_token"])
        self._token = resposta.get("access_token", "")
        self._token_vale_ate = time.monotonic() + int(resposta.get("expires_in", 3600)) - 120

    def conectada(self) -> bool:
        return bool(ler_segredo(chave_token_microsoft(self.conta.endereco)))

    def _acesso(self) -> str:
        if self._token and time.monotonic() < self._token_vale_ate:
            return self._token
        renovavel = ler_segredo(chave_token_microsoft(self.conta.endereco))
        if not renovavel:
            raise ErroDeNegocio("Entre na conta Microsoft em Configurações → Conta de e-mail.")
        resposta = _http("POST", f"{self._login}/token", formulario={
            "grant_type": "refresh_token", "client_id": self.conta.ms_cliente,
            "refresh_token": renovavel, "scope": ESCOPOS,
        })
        if "error" in resposta:
            raise ErroDeNegocio(
                "A autorização da Microsoft venceu: entre de novo em Configurações → "
                "Conta de e-mail."
            )
        self._guardar_tokens(resposta)
        return self._token

    def _get(self, caminho: str) -> dict:
        resposta = _http("GET", f"{GRAPH}{caminho}", token=self._acesso(),
                         cabecalhos={"Prefer": 'outlook.body-content-type="html"'})
        if "error" in resposta:
            detalhe = resposta["error"]
            mensagem = detalhe.get("message", "") if isinstance(detalhe, dict) else detalhe
            raise ErroDeNegocio(f"A Microsoft recusou a leitura: {mensagem}")
        return resposta

    def _id_da_pasta(self) -> str:
        nome = self.conta.pasta.replace("'", "''")
        filtro = urllib.parse.quote(f"displayName eq '{nome}'")
        for onde in ("/me/mailFolders", "/me/mailFolders/inbox/childFolders"):
            achadas = self._get(f"{onde}?$filter={filtro}&$top=1").get("value", [])
            if achadas:
                return achadas[0]["id"]
        raise ErroDeNegocio(
            f"Não encontrei a pasta \"{self.conta.pasta}\" no Outlook. Crie a pasta e a regra "
            "que leva os e-mails do financeiro para ela."
        )

    def testar(self) -> str:
        pasta = self._get(f"/me/mailFolders/{self._id_da_pasta()}")
        return f"Conectado: {pasta.get('totalItemCount', 0)} e-mail(s) na pasta " \
               f"\"{self.conta.pasta}\"."

    def baixar(self, ja_tenho: set[str], assunto_da_conversa: str) -> list[MensagemBaixada]:
        campos = ("id,subject,from,toRecipients,ccRecipients,receivedDateTime,body,"
                  "internetMessageId,conversationId")
        caminho = (f"/me/mailFolders/{self._id_da_pasta()}/messages?$top=50"
                   f"&$orderby=receivedDateTime%20desc&$select={campos}")
        mensagens = []
        for item in self._get(caminho).get("value", []):
            if not da_conversa(item.get("subject", ""), assunto_da_conversa):
                continue
            mensagens.append(_de_graph(item))
        # as respostas das mesmas conversas que a regra não moveu para a pasta
        vistos = {m.message_id for m in mensagens}
        for conversa in {m.conversa for m in mensagens if m.conversa}:
            filtro = urllib.parse.quote(f"conversationId eq '{conversa}'")
            for item in self._get(f"/me/messages?$filter={filtro}&$top=50"
                                  f"&$select={campos}").get("value", []):
                if not da_conversa(item.get("subject", ""), assunto_da_conversa):
                    continue
                mensagem = _de_graph(item)
                if mensagem.message_id not in vistos:
                    vistos.add(mensagem.message_id)
                    mensagens.append(mensagem)
        # o id do Graph muda se o e-mail mudar de pasta: os já guardados vêm também,
        # para atualizar a referência de resposta
        return [m for m in mensagens if m.message_id not in ja_tenho] + \
            [m for m in mensagens if m.message_id in ja_tenho]

    def responder(self, original: Original, resposta: Resposta) -> MensagemBaixada:
        if not original.ref_provedor:
            raise ErroDeNegocio("Este e-mail não veio da conta Microsoft: copie a resposta.")
        if not _lista_de_enderecos(resposta.para):
            raise ErroDeValidacao("Informe para quem vai a resposta.")
        html = resposta.html + _citacao_html(original)
        retorno = _http(
            "POST", f"{GRAPH}/me/messages/{original.ref_provedor}/replyAll",
            token=self._acesso(),
            corpo={"message": {
                "toRecipients": _destinatarios_graph(resposta.para),
                "ccRecipients": _destinatarios_graph(resposta.cc),
                "body": {"contentType": "HTML", "content": html},
            }},
        )
        if "error" in retorno:
            detalhe = retorno["error"]
            mensagem = detalhe.get("message", "") if isinstance(detalhe, dict) else detalhe
            raise ErroDeNegocio(f"A Microsoft não enviou a resposta: {mensagem}")
        dominio = self.conta.endereco.split("@")[-1] or "honorarios"
        return MensagemBaixada(
            message_id=make_msgid(domain=dominio), assunto=resposta.assunto,
            de=self.conta.endereco, para=resposta.para, cc=resposta.cc, data=agora_utc(),
            html=html, texto=resposta.texto, in_reply_to=original.message_id,
            conversa=original.conversa,
        )


def _de_graph(item: dict) -> MensagemBaixada:
    message_id = item.get("internetMessageId") or f"<{item['id']}@graph>"
    corpo = item.get("body", {})
    html = corpo.get("content", "") if corpo.get("contentType") == "html" else ""
    texto = _texto_de_html(html) if html else corpo.get("content", "")
    return MensagemBaixada(
        message_id=message_id,
        assunto=item.get("subject", ""),
        de=_endereco_graph(item.get("from")),
        para=", ".join(_endereco_graph(d) for d in item.get("toRecipients", [])),
        cc=", ".join(_endereco_graph(d) for d in item.get("ccRecipients", [])),
        data=datetime.fromisoformat(item["receivedDateTime"].replace("Z", "+00:00")),
        html=html, texto=texto,
        conversa=item.get("conversationId", ""),
        ref_provedor=item["id"],
    )


def _endereco_graph(destinatario: dict | None) -> str:
    dados = (destinatario or {}).get("emailAddress", {})
    return servico_email.endereco_legivel(dados.get("name", ""), dados.get("address", ""))


def _destinatarios_graph(texto_enderecos: str) -> list[dict]:
    return [{"emailAddress": {"name": nome, "address": endereco}}
            for nome, endereco in _lista_de_enderecos(texto_enderecos)]


def abrir_caixa(sessao: Session):
    """A caixa da conta configurada (Gmail/IMAP com a senha do cofre, ou Microsoft)."""
    dados = conta(sessao)
    if not dados.configurada:
        raise ErroDeValidacao("Configure a conta de e-mail em Configurações → Conta de e-mail.")
    if dados.provedor == MICROSOFT:
        return CaixaMicrosoft(dados)
    senha = ler_segredo(chave_senha(dados.endereco))
    if not senha:
        raise ErroDeValidacao("Falta a senha de app da conta de e-mail (Configurações).")
    return CaixaImap(dados, senha)


# ------------------------------------------------------------- no banco
def ja_baixados(sessao: Session, conta_chave: str) -> set[str]:
    return set(sessao.scalars(
        select(EmailMensagem.message_id).where(EmailMensagem.conta == conta_chave)
    ).all())


def guardar(sessao: Session, conta_chave: str,
            mensagens: list[MensagemBaixada]) -> list[EmailMensagem]:
    """Guarda os e-mails novos (e atualiza a referência dos que já existiam)."""
    existentes = {
        m.message_id: m for m in sessao.scalars(
            select(EmailMensagem).where(EmailMensagem.conta == conta_chave)
        )
    }
    novas = []
    for baixada in mensagens:
        ja = existentes.get(baixada.message_id)
        if ja is not None:
            if baixada.ref_provedor and ja.ref_provedor != baixada.ref_provedor:
                ja.ref_provedor = baixada.ref_provedor
            continue
        registro = _registro(conta_chave, baixada)
        sessao.add(registro)
        existentes[baixada.message_id] = registro
        novas.append(registro)
    sessao.flush()
    for registro in novas:
        _notificar(sessao, registro)
    return novas


def _registro(conta_chave: str, baixada: MensagemBaixada, enviada: bool = False):
    return EmailMensagem(
        conta=conta_chave, message_id=baixada.message_id, ref_provedor=baixada.ref_provedor,
        conversa=baixada.conversa, assunto=baixada.assunto, de=baixada.de,
        para=baixada.para, cc=baixada.cc, recebido_em=baixada.data,
        corpo_html=baixada.html, corpo_texto=baixada.texto,
        in_reply_to=baixada.in_reply_to, referencias=baixada.referencias, enviada=enviada,
    )


def _notificar(sessao: Session, registro: EmailMensagem) -> None:
    chave = f"email:{registro.id}"
    if sessao.scalar(select(Notificacao.id).where(Notificacao.chave == chave)):
        return
    nome = (getaddresses([registro.de])[0][0] if registro.de else "") or registro.de
    sessao.add(Notificacao(
        chave=chave, tipo=servico_notificacoes.EMAIL,
        titulo=f"Chegou e-mail de {nome}: {registro.assunto}",
        texto="Confira a lista e responda pela tela E-mail",
        tela=servico_notificacoes.TELAS[servico_notificacoes.EMAIL],
    ))
    sessao.flush()


def guardar_do_arquivo(sessao: Session, recebido) -> EmailMensagem:
    """E-mail aberto de arquivo ou colado: entra na lista como os outros."""
    texto = recebido.texto
    message_id = recebido.message_id or \
        f"<arquivo-{sha1(texto.encode('utf-8')).hexdigest()}@honorarios>"
    existente = sessao.scalar(select(EmailMensagem).where(
        EmailMensagem.conta == ARQUIVO, EmailMensagem.message_id == message_id))
    if existente is not None:
        return existente
    leitura = servico_email.ler(texto)
    quando = datetime.combine(leitura.data, datetime.min.time(), tzinfo=UTC) \
        if leitura.data else agora_utc()
    registro = _registro(ARQUIVO, MensagemBaixada(
        message_id=message_id,
        assunto=recebido.assunto or servico_email.ASSUNTO_PADRAO,
        de=recebido.de or "(e-mail aberto de arquivo)",
        para=recebido.para, cc=recebido.cc, data=quando, texto=texto,
        referencias=recebido.referencias,
    ))
    registro.lida_em = agora_utc()
    sessao.add(registro)
    sessao.flush()
    return registro


def listar(sessao: Session, limite: int = 200) -> list[EmailMensagem]:
    """Para a lista: sem o corpo dos e-mails (só é lido quando um é aberto)."""
    return list(sessao.scalars(
        select(EmailMensagem)
        .options(defer(EmailMensagem.corpo_html), defer(EmailMensagem.corpo_texto))
        .order_by(EmailMensagem.recebido_em.desc(), EmailMensagem.id.desc())
        .limit(limite)
    ).all())


def nao_lidos(sessao: Session) -> int:
    return sessao.scalar(
        select(func.count(EmailMensagem.id)).where(
            EmailMensagem.lida_em.is_(None), EmailMensagem.enviada.is_(False)
        )
    ) or 0


def marcar_lido(sessao: Session, mensagem: EmailMensagem) -> None:
    if mensagem.lida_em is None and not mensagem.enviada:
        mensagem.lida_em = agora_utc()
        sessao.flush()


def registrar_enviada(sessao: Session, original: EmailMensagem,
                      enviada: MensagemBaixada) -> EmailMensagem:
    """A resposta enviada entra na conversa, e o original fica como respondido."""
    registro = _registro(original.conta, enviada, enviada=True)
    registro.conversa = registro.conversa or original.conversa
    sessao.add(registro)
    original.respondida_em = agora_utc()
    sessao.flush()
    return registro


def recebido_de(mensagem: EmailMensagem) -> servico_email.EmailRecebido:
    """O e-mail guardado no formato que a conferência e a resposta usam."""
    texto = mensagem.corpo_texto or _texto_de_html(mensagem.corpo_html)
    return servico_email.EmailRecebido(
        texto=texto, de=mensagem.de, para=mensagem.para, cc=mensagem.cc,
        assunto=mensagem.assunto, message_id=mensagem.message_id,
        referencias=mensagem.referencias,
    )


def registrar_verificacao(sessao: Session) -> None:
    configuracoes.gravar(sessao, ULTIMA_VERIFICACAO, agora_utc().isoformat())


def ultima_verificacao(sessao: Session) -> datetime | None:
    valor = configuracoes.obter(sessao, ULTIMA_VERIFICACAO)
    try:
        return datetime.fromisoformat(valor) if valor else None
    except ValueError:
        return None


@dataclass
class ResultadoVerificacao:
    conta: str
    mensagens: list[MensagemBaixada] = field(default_factory=list)


def verificar(caixa, conta_chave: str, ja_tenho: set[str],
              assunto_da_conversa: str) -> ResultadoVerificacao:
    """A parte de rede da verificação: roda em segundo plano, sem tocar no banco."""
    return ResultadoVerificacao(conta_chave, caixa.baixar(ja_tenho, assunto_da_conversa))
