"""Caixa de e-mail: só a pasta e só a conversa; responder na mesma conversa.

Servidores de mentira (IMAP, SMTP e Microsoft Graph): nada sai para a internet.
"""

from __future__ import annotations

from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

import pytest

from honorarios.servicos import caixa_email as servico
from honorarios.servicos import email_cobrancas, notificacoes
from honorarios.servicos.erros import ErroDeNegocio, ErroDeValidacao

ASSUNTO = "Clientes c/Honorários vencidos"
LISTA = "Cobranças de 24/09/2026\n\nEMPRESA EXEMPLO LTDA\t08/2026\t08/09/2026\t399,00\n"


def _mime(message_id: str, assunto: str, corpo: str = LISTA) -> bytes:
    mensagem = EmailMessage()
    mensagem["From"] = "Financeiro <financeiro@exemplo.com.br>"
    mensagem["To"] = "cobranca@exemplo.com.br"
    mensagem["Cc"] = "Gerencia <gerencia@exemplo.com.br>"
    mensagem["Subject"] = assunto
    mensagem["Date"] = "Thu, 24 Sep 2026 09:13:00 -0300"
    mensagem["Message-ID"] = message_id
    mensagem.set_content(corpo)
    return bytes(mensagem)


def test_nome_da_pasta_no_imap():
    assert servico.pasta_imap("Cobranças") == "Cobran&AOc-as"
    assert servico.pasta_imap("A&B") == "A&-B"
    assert servico.pasta_imap("INBOX") == "INBOX"


def test_reconhece_a_conversa():
    assert servico.da_conversa("RE: ENC: Clientes c/Honorarios vencidos", ASSUNTO)
    assert not servico.da_conversa("Reunião amanhã", ASSUNTO)


class ImapDeMentira:
    """A pasta Cobranças com três e-mails: dois da conversa (um já baixado) e um de
    fora. Em "Todos os e-mails" do Gmail, a conversa 7 tem também uma resposta que
    o filtro não marcou, e a conversa 9 é outro assunto."""

    caixas = {
        b"1": _mime("<a@x>", ASSUNTO),
        b"2": _mime("<b@x>", "RE: " + ASSUNTO),
        b"3": _mime("<c@x>", "Promoção imperdível"),
    }
    todos = {
        b"11": (b"7", _mime("<a@x>", ASSUNTO)),
        b"12": (b"7", _mime("<b@x>", "RE: " + ASSUNTO)),
        b"13": (b"7", _mime("<resposta@x>", "Re: RE: " + ASSUNTO)),
        b"14": (b"9", _mime("<c@x>", "Promoção imperdível")),
    }
    conversas = {b"1": b"7", b"2": b"7", b"3": b"9"}
    instancias: list = []

    def __init__(self, host, porta, ssl_context=None, timeout=None):
        self.host, self.comandos, self.pasta = host, [], None
        ImapDeMentira.instancias.append(self)

    def login(self, usuario, senha):
        if senha != "senha-de-app":
            import imaplib

            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    def select(self, pasta, readonly=False):
        self.pasta, self.somente_leitura = pasta, readonly
        if pasta in ('"Cobran&AOc-as"', '"[Gmail]/Todos os e-mails"'):
            return "OK", [b"3"]
        return "NO", [b""]

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"',
                      b'(\\All \\HasNoChildren) "/" "[Gmail]/Todos os e-mails"']

    def _pasta(self):
        if self.pasta == '"Cobran&AOc-as"':
            return {uid: (self.conversas[uid], bruto) for uid, bruto in self.caixas.items()}
        return self.todos

    def uid(self, comando, *argumentos):
        self.comandos.append((comando, argumentos))
        pasta = self._pasta()
        if comando == "SEARCH":
            if argumentos[1] == "X-GM-THRID":
                return "OK", [b" ".join(u for u, (c, _) in pasta.items()
                                        if c == argumentos[2].encode())]
            return "OK", [b" ".join(pasta)]
        uids, pedido = argumentos
        saida = []
        for uid in uids.split(","):
            conversa, bruto = pasta[uid.encode()]
            extra = f"X-GM-THRID {conversa.decode()} " if "X-GM-THRID" in pedido else ""
            if "HEADER.FIELDS" in pedido:
                cabecalho = bruto.split(b"\n\n")[0]
                saida.append((f"{uid} ({extra}UID {uid} BODY[HEADER] {{1}}".encode(),
                              cabecalho))
            else:
                saida.append((f"{uid} (UID {uid} BODY[] {{1}}".encode(), bruto))
            saida.append(b")")
        return "OK", saida

    def logout(self):
        pass


@pytest.fixture
def conta_gmail():
    return servico.ContaEmail(
        provedor=servico.GMAIL, endereco="cobranca@exemplo.com.br", pasta="Cobranças",
        imap_host="imap.gmail.com", imap_porta=993, smtp_host="smtp.gmail.com", smtp_porta=587,
    )


def test_imap_baixa_so_a_conversa_da_pasta(monkeypatch, conta_gmail):
    monkeypatch.setattr(servico.imaplib, "IMAP4_SSL", ImapDeMentira)
    conta_gmail.provedor = servico.IMAP                        # sem o recurso do Gmail
    novas = servico.CaixaImap(conta_gmail, "senha-de-app").baixar({"<a@x>"}, ASSUNTO)
    assert [m.message_id for m in novas] == ["<b@x>"]          # o de fora e o já baixado não
    imap = ImapDeMentira.instancias[-1]
    assert imap.pasta == '"Cobran&AOc-as"' and imap.somente_leitura
    # nada é marcado como lido na caixa: só BODY.PEEK
    assert all("PEEK" in args[1] for cmd, args in imap.comandos if cmd == "FETCH")
    assert novas[0].de == "Financeiro <financeiro@exemplo.com.br>"
    assert "EMPRESA EXEMPLO" in novas[0].texto


def test_imap_explica_pasta_e_senha_erradas(monkeypatch, conta_gmail):
    monkeypatch.setattr(servico.imaplib, "IMAP4_SSL", ImapDeMentira)
    with pytest.raises(ErroDeNegocio, match="senha de app"):
        servico.CaixaImap(conta_gmail, "errada").testar()
    conta_gmail.pasta = "Outra"
    with pytest.raises(ErroDeNegocio, match="Não encontrei a pasta"):
        servico.CaixaImap(conta_gmail, "senha-de-app").testar()


def test_resposta_por_smtp_na_mesma_conversa(monkeypatch, sessao, conta_gmail):
    enviados = []

    class SmtpDeMentira:
        def __init__(self, host, porta, timeout=None):
            self.host = host

        def __enter__(self):
            return self

        def __exit__(self, *erro):
            return False

        def starttls(self, context=None):
            pass

        def login(self, usuario, senha):
            assert (usuario, senha) == ("cobranca@exemplo.com.br", "senha-de-app")

        def send_message(self, mensagem):
            enviados.append(mensagem)

    monkeypatch.setattr(servico.smtplib, "SMTP", SmtpDeMentira)
    [original] = servico.guardar(sessao, servico.GMAIL, [servico.de_mime(_mime("<a@x>", ASSUNTO))])
    resposta = servico.Resposta(
        para="Financeiro <financeiro@exemplo.com.br>", cc="gerencia@exemplo.com.br",
        assunto="RE: " + ASSUNTO, html="<p>andamento</p>", texto="andamento",
    )
    enviada = servico.CaixaImap(conta_gmail, "senha-de-app").responder(
        servico.original_de(original), resposta)
    [mensagem] = enviados
    assert mensagem["In-Reply-To"] == "<a@x>"
    assert mensagem["References"] == "<a@x>"
    assert mensagem["Cc"] == "gerencia@exemplo.com.br"
    html = mensagem.get_body(("html",)).get_content()
    assert "<p>andamento</p>" in html and "EMPRESA EXEMPLO" in html   # o original citado
    registro = servico.registrar_enviada(sessao, original, enviada)
    assert registro.enviada and original.respondida_em is not None


def test_microsoft_entra_baixa_e_responde(monkeypatch, cofre):
    chamadas = []
    respostas_token = iter([
        {"_status": 400, "error": "authorization_pending"},
        {"access_token": "acesso", "refresh_token": "renovavel", "expires_in": 3600},
    ])

    def http(metodo, url, token="", corpo=None, formulario=None, cabecalhos=None):
        chamadas.append((metodo, url, token, corpo))
        if url.endswith("/devicecode"):
            return {"user_code": "ABCD-1234", "device_code": "dc", "interval": 0,
                    "expires_in": 60, "verification_uri": "https://microsoft.com/devicelogin"}
        if url.endswith("/token"):
            return next(respostas_token)
        if "mailFolders?$filter" in url:
            return {"value": [{"id": "pasta-1"}]}
        if "/messages?" in url:
            return {"value": [
                {"id": "g1", "subject": ASSUNTO, "internetMessageId": "<a@x>",
                 "conversationId": "conv", "receivedDateTime": "2026-09-24T12:13:00Z",
                 "from": {"emailAddress": {"name": "Financeiro",
                                           "address": "financeiro@exemplo.com.br"}},
                 "toRecipients": [], "ccRecipients": [],
                 "body": {"contentType": "html", "content": "<p>Cobranças de 24/09/2026</p>"}},
                {"id": "g2", "subject": "Outro assunto", "internetMessageId": "<z@x>",
                 "receivedDateTime": "2026-09-24T12:13:00Z", "body": {}},
            ]}
        if url.endswith("/replyAll"):
            return {}
        raise AssertionError(url)

    monkeypatch.setattr(servico, "_http", http)
    monkeypatch.setattr(servico.time, "sleep", lambda _s: None)
    conta = servico.ContaEmail(provedor=servico.MICROSOFT, endereco="cobranca@exemplo.com.br",
                               pasta="Cobranças", ms_cliente="app-id")
    caixa = servico.CaixaMicrosoft(conta)
    codigo = caixa.iniciar_entrada()
    assert codigo.codigo == "ABCD-1234"
    caixa.concluir_entrada(codigo)
    # a autorização renovável fica no cofre, não no banco
    assert cofre.get_password(servico.SERVICO_COFRE,
                              servico.chave_token_microsoft("cobranca@exemplo.com.br")) == \
        "renovavel"

    [baixada] = caixa.baixar(set(), ASSUNTO)                  # o de outro assunto fica
    assert baixada.ref_provedor == "g1" and baixada.de.startswith("Financeiro")
    assert all(token == "acesso" for metodo, url, token, _ in chamadas if "graph" in url)

    original = servico.Original(
        conta=servico.MICROSOFT, message_id="<a@x>", ref_provedor="g1", conversa="",
        assunto=ASSUNTO, de=baixada.de, para="", cc="",
        recebido_em=datetime(2026, 9, 24, tzinfo=UTC), corpo_html="<p>lista</p>",
        corpo_texto="", referencias="",
    )
    caixa.responder(original, servico.Resposta(
        para="financeiro@exemplo.com.br", cc="", assunto="RE: x", html="<p>ok</p>", texto="ok"))
    metodo, url, _token, corpo = chamadas[-1]
    assert url.endswith("/me/messages/g1/replyAll")
    assert corpo["message"]["toRecipients"] == [
        {"emailAddress": {"name": "", "address": "financeiro@exemplo.com.br"}}]
    assert corpo["message"]["body"]["content"].startswith("<p>ok</p>")


def test_guardar_sem_repetir_e_avisar(sessao):
    baixadas = [servico.de_mime(_mime("<a@x>", ASSUNTO), ref_provedor="1")]
    [nova] = servico.guardar(sessao, servico.GMAIL, baixadas)
    assert not nova.lida and servico.nao_lidos(sessao) == 1
    [aviso] = notificacoes.listar(sessao)
    assert aviso.tipo == notificacoes.EMAIL and aviso.tela == "Gerenciador de e-mail"
    assert "Financeiro" in aviso.titulo
    # de novo, com outra referência no provedor: não repete, só atualiza
    baixadas[0].ref_provedor = "9"
    assert servico.guardar(sessao, servico.GMAIL, baixadas) == []
    assert nova.ref_provedor == "9"
    servico.marcar_lido(sessao, nova)
    assert servico.nao_lidos(sessao) == 0


def test_email_de_arquivo_entra_na_lista(sessao):
    recebido = email_cobrancas.EmailRecebido(LISTA)
    primeiro = servico.guardar_do_arquivo(sessao, recebido)
    assert servico.guardar_do_arquivo(sessao, recebido).id == primeiro.id
    assert primeiro.conta == servico.ARQUIVO and primeiro.lida
    assert primeiro.recebido_em.date().isoformat() == "2026-09-24"
    assert servico.recebido_de(primeiro).texto == LISTA


def test_abrir_caixa_pede_a_configuracao(sessao):
    with pytest.raises(ErroDeValidacao, match="Configure a conta"):
        servico.abrir_caixa(sessao)
    servico.gravar_conta(sessao, servico.ContaEmail(
        provedor=servico.GMAIL, endereco="cobranca@exemplo.com.br"))
    conta = servico.conta(sessao)
    assert conta.imap_host == "imap.gmail.com" and conta.configurada   # Gmail já sabe
    with pytest.raises(ErroDeValidacao, match="senha de app"):
        servico.abrir_caixa(sessao)
    servico.guardar_segredo(servico.chave_senha("cobranca@exemplo.com.br"), "senha-de-app")
    assert isinstance(servico.abrir_caixa(sessao), servico.CaixaImap)


def test_mensagem_sem_id_ganha_um_estavel():
    bruto = _mime("", ASSUNTO).replace(b"Message-ID: \n", b"")
    primeira, segunda = servico.de_mime(bruto), servico.de_mime(bruto)
    assert primeira.message_id == segunda.message_id
    assert BytesParser(policy=policy.default).parsebytes(bruto)["Message-ID"] in (None, "")


def test_gmail_pega_as_respostas_da_conversa_fora_do_marcador(monkeypatch, conta_gmail):
    monkeypatch.setattr(servico.imaplib, "IMAP4_SSL", ImapDeMentira)
    novas = servico.CaixaImap(conta_gmail, "senha-de-app").baixar({"<a@x>"}, ASSUNTO)
    # a resposta que o filtro não marcou vem; a promoção (outra conversa) não
    assert [m.message_id for m in novas] == ["<b@x>", "<resposta@x>"]
    imap = ImapDeMentira.instancias[-1]
    assert imap.pasta == '"[Gmail]/Todos os e-mails"' and imap.somente_leitura
    assert all("PEEK" in args[1] for cmd, args in imap.comandos if cmd == "FETCH")


def test_correcoes_ficam_guardadas_no_email(sessao):
    [mensagem] = servico.guardar(sessao, servico.GMAIL, [servico.de_mime(_mime("<a@x>", ASSUNTO))])
    servico.corrigir(sessao, mensagem, "linha-1", 42)
    servico.corrigir(sessao, mensagem, "linha-2", 0)
    assert servico.correcoes(mensagem) == {"linha-1": 42, "linha-2": 0}
    servico.corrigir(sessao, mensagem, "linha-1", None)              # desfazer
    assert servico.correcoes(mensagem) == {"linha-2": 0}


def test_email_novo_sem_resposta(monkeypatch, conta_gmail):
    enviados = []

    class SmtpDeMentira:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *erro):
            return False

        def starttls(self, context=None):
            pass

        def login(self, *a):
            pass

        def send_message(self, mensagem):
            enviados.append(mensagem)

    monkeypatch.setattr(servico.smtplib, "SMTP", SmtpDeMentira)
    resposta = servico.Resposta(para="financeiro@exemplo.com.br", cc="", assunto=ASSUNTO,
                                html="<p>lista</p>", texto="lista")
    servico.CaixaImap(conta_gmail, "senha-de-app").enviar_novo(resposta)
    [mensagem] = enviados
    assert mensagem["In-Reply-To"] is None and mensagem["Subject"] == ASSUNTO

    chamadas = []
    monkeypatch.setattr(servico, "_http", lambda metodo, url, **k: chamadas.append((url, k)) or {})
    caixa = servico.CaixaMicrosoft(servico.ContaEmail(
        provedor=servico.MICROSOFT, endereco="cobranca@exemplo.com.br", ms_cliente="app"))
    monkeypatch.setattr(caixa, "_acesso", lambda: "token")
    caixa.enviar_novo(resposta)
    url, argumentos = chamadas[-1]
    assert url.endswith("/me/sendMail")
    assert argumentos["corpo"]["message"]["subject"] == ASSUNTO
