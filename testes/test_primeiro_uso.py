"""Programa instalado: a conexão com o PostgreSQL é pedida no primeiro uso e lembrada."""

from __future__ import annotations

import os

import pytest

from honorarios.config import caminhos, conexao


class _Cofre:
    def __init__(self):
        self.dados = {}

    def set_password(self, servico, nome, valor):
        self.dados[(servico, nome)] = valor

    def get_password(self, servico, nome):
        return self.dados.get((servico, nome))


@pytest.fixture
def instalado(tmp_path, monkeypatch):
    """Como se estivesse instalado: sem as variáveis de teste, fora do código-fonte."""
    monkeypatch.delenv("HONORARIOS_DADOS", raising=False)
    monkeypatch.delenv("HONORARIOS_BANCO_URL", raising=False)
    monkeypatch.setattr(caminhos, "rodando_do_codigo", lambda: False)
    monkeypatch.setattr(caminhos, "pasta_configuracao", lambda: tmp_path / "config")
    monkeypatch.setattr(caminhos, "pasta_dados_padrao", lambda: tmp_path / "local")
    cofre = _Cofre()
    monkeypatch.setattr(conexao, "_cofre", lambda: cofre)
    return cofre


def test_instalado_pede_a_conexao_e_depois_lembra(instalado):
    assert caminhos.precisa_configurar()
    dados = conexao.ConexaoPostgres(servidor="192.168.0.10", usuario="escritorio")
    conexao.gravar(dados, "s3nh@")
    assert not caminhos.precisa_configurar()
    assert conexao.ler() == dados
    url = conexao.url_do_banco()
    assert url.host == "192.168.0.10" and url.database == "financeiro_metodos"
    assert url.password == "s3nh@"                               # do cofre…
    assert "s3nh@" not in caminhos.arquivo_configuracao().read_text()   # …nunca no arquivo
    assert conexao.usa_postgres()
    assert conexao.descricao() == "PostgreSQL · escritorio@192.168.0.10:5432/financeiro_metodos"


def test_variaveis_de_ambiente_valem_primeiro(instalado, monkeypatch):
    conexao.gravar(conexao.ConexaoPostgres(servidor="srv", usuario="u"), "x")
    monkeypatch.setenv("HONORARIOS_DADOS", "/tmp/copia")
    assert not conexao.usa_postgres()                            # cópia local em SQLite
    monkeypatch.setenv("HONORARIOS_BANCO_URL", "sqlite:///teste.db")
    assert conexao.url_do_banco() == "sqlite:///teste.db"


def test_mensagens_de_erro_sem_jargao():
    dados = conexao.ConexaoPostgres(servidor="srv", banco="fin", usuario="u")
    assert conexao._explicar(Exception('password authentication failed for user "u"'),
                             dados) == "Usuário ou senha recusados pelo servidor."
    falha = conexao.FalhaDeConexao(conexao._explicar(
        Exception('database "fin" does not exist'), dados))
    assert conexao.banco_nao_existe(falha)
    assert "não respondeu" in conexao._explicar(Exception("Connection refused"), dados)


def test_tela_de_conexao(qtbot, instalado, monkeypatch):
    from honorarios.ui.comum import segundo_plano
    from honorarios.ui.dialogos.primeiro_uso import DialogoPrimeiroUso

    dialogo = DialogoPrimeiroUso(executor=segundo_plano.imediato)
    qtbot.addWidget(dialogo)
    dialogo.confirmar()                                          # sem servidor: avisa
    assert dialogo.result() == 0 and "servidor" in dialogo.resultado.text()

    dialogo.servidor.setText("192.168.0.10")
    dialogo.usuario.setText("escritorio")
    dialogo.senha.setText("s3nh@")
    # banco inexistente: oferece criar
    def nao_existe(dados, senha):
        raise conexao.FalhaDeConexao(f'O banco "{dados.banco}" não existe nesse servidor.')

    monkeypatch.setattr(conexao, "testar", nao_existe)
    dialogo.testar()
    assert dialogo.botao_criar.isVisibleTo(dialogo)
    criados = []
    monkeypatch.setattr(conexao, "criar_banco", lambda dados, senha: criados.append(dados.banco))
    monkeypatch.setattr(conexao, "testar", lambda dados, senha: "Conectado ao PostgreSQL 16")
    dialogo.criar_banco()
    assert criados == ["financeiro_metodos"] and "Banco criado" in dialogo.resultado.text()
    assert not dialogo.botao_criar.isVisibleTo(dialogo)

    dialogo.confirmar()
    assert dialogo.result() == 1
    assert conexao.ler().servidor == "192.168.0.10"
    assert conexao.ler_senha(conexao.ler()) == "s3nh@"


def test_demonstracao_nao_grava_nada(qtbot, instalado, monkeypatch):
    from honorarios.ui.comum import segundo_plano
    from honorarios.ui.dialogos.primeiro_uso import DialogoPrimeiroUso

    monkeypatch.setattr(conexao, "testar", lambda dados, senha: "ok")
    dialogo = DialogoPrimeiroUso(demonstracao=True, executor=segundo_plano.imediato)
    qtbot.addWidget(dialogo)
    dialogo.servidor.setText("srv")
    dialogo.usuario.setText("u")
    dialogo.confirmar()
    assert dialogo.result() == 1
    assert conexao.ler() is None                                 # nada guardado


@pytest.mark.skipif(not os.environ.get("HONORARIOS_TESTE_PG"),
                    reason="só com um PostgreSQL de teste")
def test_conecta_de_verdade_no_postgres():
    from sqlalchemy.engine import make_url

    url = make_url(os.environ["HONORARIOS_TESTE_PG"])
    dados = conexao.ConexaoPostgres(servidor=url.host or url.query.get("host", ""),
                                    porta=url.port or 5432, banco=url.database,
                                    usuario=url.username)
    assert conexao.testar(dados, url.password or "").startswith("Conectado ao PostgreSQL")
    outro = conexao.ConexaoPostgres(servidor=dados.servidor, porta=dados.porta,
                                    banco="nao_existe_financeiro", usuario=dados.usuario)
    with pytest.raises(conexao.FalhaDeConexao) as erro:
        conexao.testar(outro, url.password or "")
    assert conexao.banco_nao_existe(erro.value)


def test_trocar_conexao_nas_configuracoes(qtbot, contexto, monkeypatch):
    from honorarios.servicos import backup
    from honorarios.ui.comum import widgets
    from honorarios.ui.dialogos import primeiro_uso
    from honorarios.ui.paineis.configuracoes import PainelConfiguracoes

    painel = PainelConfiguracoes(contexto)
    qtbot.addWidget(painel)
    assert "backups em" in painel.pasta_dados.text()           # o banco e onde ficam os backups
    feitos = []
    monkeypatch.setattr(backup, "gerar", lambda motivo, manter: feitos.append(motivo))
    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: True)
    monkeypatch.setattr(widgets, "informar", lambda *a, **k: None)
    monkeypatch.setattr(primeiro_uso.DialogoPrimeiroUso, "exec", lambda self: 1)
    painel._trocar_pasta_dados()
    assert feitos == ["antes-de-trocar-pasta"]
    assert painel.window().sem_backup_ao_fechar
