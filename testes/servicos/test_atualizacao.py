"""Atualização pelo GitHub: versão, release, download conferido. Sem internet."""

from __future__ import annotations

import hashlib
import http.server
import threading
from pathlib import Path

import pytest

from honorarios.servicos import atualizacao
from honorarios.servicos.erros import ErroDeNegocio

CONTEUDO = b"instalador de mentira " * 5000


def _release(versao="1.6.0", conteudo=CONTEUDO, url="http://x/i.exe", digest=None):
    return {
        "tag_name": f"v{versao}", "body": "## Novidades\n- coisa nova",
        "published_at": "2026-10-30T12:00:00Z", "html_url": "https://github.com/x",
        "assets": [
            {"name": "outra_coisa.zip", "browser_download_url": "http://x/z", "size": 1},
            {"name": f"Instalador_Financeiro_Metodos_{versao}.exe",
             "browser_download_url": url, "size": len(conteudo),
             "digest": digest or "sha256:" + hashlib.sha256(conteudo).hexdigest()},
        ],
    }


def test_versoes_comparam_como_numero():
    assert atualizacao.numeros("v1.10.0") > atualizacao.numeros("1.9.9")
    assert atualizacao.numeros("1.5") == (1, 5, 0)
    lancamento = atualizacao.de_json(_release("1.5.1"))
    assert atualizacao.mais_nova(lancamento, "1.5.0")
    assert not atualizacao.mais_nova(lancamento, "1.5.1")
    assert not atualizacao.mais_nova(lancamento, "2.0.0")


def test_le_o_release_e_acha_o_instalador():
    lancamento = atualizacao.de_json(_release())
    assert lancamento.versao == "1.6.0"
    assert lancamento.instalador_nome == "Instalador_Financeiro_Metodos_1.6.0.exe"
    assert lancamento.sha256 == hashlib.sha256(CONTEUDO).hexdigest()
    assert lancamento.publicado_em.year == 2026
    assert "coisa nova" in lancamento.notas


def test_release_sem_instalador_explica():
    dados = _release()
    dados["assets"] = dados["assets"][:1]
    with pytest.raises(ErroDeNegocio, match="ainda não tem instalador"):
        atualizacao.de_json(dados)


def test_sem_internet_vira_mensagem(monkeypatch):
    import urllib.error

    def sem_rede(*_a, **_k):
        raise urllib.error.URLError("sem rede")

    monkeypatch.setattr(atualizacao, "_pedir", sem_rede)
    with pytest.raises(ErroDeNegocio, match="Não consegui falar com o GitHub"):
        atualizacao.ultima()


@pytest.fixture
def servidor():
    """Um servidor HTTP local servindo o instalador de mentira."""

    class Servir(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Length", str(len(CONTEUDO)))
            self.end_headers()
            self.wfile.write(CONTEUDO)

        def log_message(self, *_args):
            pass

    http_server = http.server.HTTPServer(("127.0.0.1", 0), Servir)
    threading.Thread(target=http_server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{http_server.server_port}/i.exe"
    http_server.shutdown()


def test_baixa_e_confere_o_sha256(servidor, tmp_path):
    lancamento = atualizacao.de_json(_release(url=servidor))
    andamento = []

    arquivo = atualizacao.baixar(lancamento, tmp_path, lambda f, t: andamento.append((f, t)))

    assert arquivo.read_bytes() == CONTEUDO
    assert andamento[-1] == (len(CONTEUDO), len(CONTEUDO))
    assert not list(tmp_path.glob("*.parcial"))


def test_arquivo_que_nao_confere_e_apagado(servidor, tmp_path):
    lancamento = atualizacao.de_json(_release(url=servidor, digest="sha256:" + "0" * 64))
    with pytest.raises(ErroDeNegocio, match="não confere"):
        atualizacao.baixar(lancamento, tmp_path)
    assert list(Path(tmp_path).iterdir()) == []


def test_aviso_de_versao_nova_sai_uma_vez(sessao):
    from honorarios.servicos import notificacoes

    primeiro = notificacoes.atualizacao_disponivel(sessao, "1.6.0")
    assert primeiro is not None and primeiro.tela == "Configurações"
    assert notificacoes.atualizacao_disponivel(sessao, "1.6.0") is None
