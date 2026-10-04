"""Conexão com o banco: o PostgreSQL do escritório (num computador da rede).

O programa instalado guarda servidor, porta, banco e usuário em
``configuracao.json`` (pasta de configuração do usuário); a senha vai para o
cofre de senhas do sistema (Gerenciador de Credenciais no Windows), nunca para o
arquivo.

Ordem de onde vem o banco (``url_do_banco``):

1. ``HONORARIOS_BANCO_URL`` — uma URL do SQLAlchemy (ex.: os testes contra o
   PostgreSQL);
2. ``HONORARIOS_DADOS`` — SQLite nessa pasta (cópia de trabalho, testes);
3. a conexão configurada no primeiro uso (PostgreSQL);
4. rodando do código-fonte: SQLite em ``dados/``;
5. instalado e sem configuração: o primeiro uso pede a conexão antes.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

from sqlalchemy import URL, create_engine, text
from sqlalchemy.exc import OperationalError

from . import caminhos

SERVICO_COFRE = "financeiro-metodos-banco"
BANCO_PADRAO = "financeiro_metodos"


@dataclass
class ConexaoPostgres:
    servidor: str
    porta: int = 5432
    banco: str = BANCO_PADRAO
    usuario: str = ""

    @property
    def descricao(self) -> str:
        return f"PostgreSQL · {self.usuario}@{self.servidor}:{self.porta}/{self.banco}"

    @property
    def chave_cofre(self) -> str:
        return f"{self.usuario}@{self.servidor}:{self.porta}/{self.banco}"

    def url(self, senha: str, banco: str | None = None) -> URL:
        return URL.create("postgresql+psycopg", username=self.usuario, password=senha or None,
                          host=self.servidor, port=self.porta, database=banco or self.banco)


# ------------------------------------------------------------------ cofre
def _cofre():
    import keyring

    return keyring


def ler_senha(conexao: ConexaoPostgres) -> str:
    try:
        return _cofre().get_password(SERVICO_COFRE, conexao.chave_cofre) or ""
    except Exception:  # noqa: BLE001 - sem cofre: sem senha guardada
        return ""


def guardar_senha(conexao: ConexaoPostgres, senha: str) -> None:
    _cofre().set_password(SERVICO_COFRE, conexao.chave_cofre, senha)


# ------------------------------------------------------------- arquivo
def _ler_arquivo() -> dict:
    try:
        dados = json.loads(caminhos.arquivo_configuracao().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def ler() -> ConexaoPostgres | None:
    """A conexão configurada no primeiro uso, se houver."""
    dados = _ler_arquivo().get("postgres")
    if not isinstance(dados, dict) or not dados.get("servidor"):
        return None
    return ConexaoPostgres(
        servidor=str(dados["servidor"]), porta=int(dados.get("porta") or 5432),
        banco=str(dados.get("banco") or BANCO_PADRAO), usuario=str(dados.get("usuario", "")),
    )


def gravar(conexao: ConexaoPostgres, senha: str) -> None:
    """Guarda a conexão (e a senha no cofre) para as próximas aberturas."""
    guardar_senha(conexao, senha)
    dados = _ler_arquivo()
    dados["postgres"] = asdict(conexao)
    arquivo = caminhos.arquivo_configuracao()
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- banco
def url_do_banco() -> URL | str:
    bruto = os.environ.get("HONORARIOS_BANCO_URL")
    if bruto:
        return bruto
    if not os.environ.get("HONORARIOS_DADOS"):
        conexao = ler()
        if conexao is not None:
            return conexao.url(ler_senha(conexao))
    return f"sqlite:///{caminhos.caminho_banco()}"


def usa_postgres() -> bool:
    url = url_do_banco()
    return (url.drivername if isinstance(url, URL) else str(url)).startswith("postgresql")


def descricao() -> str:
    """Para a barra de status e as Configurações."""
    if os.environ.get("HONORARIOS_BANCO_URL"):
        return "banco de teste (HONORARIOS_BANCO_URL)"
    if not os.environ.get("HONORARIOS_DADOS"):
        conexao = ler()
        if conexao is not None:
            return conexao.descricao
    return f"SQLite · {caminhos.caminho_banco()}"


def precisa_configurar() -> bool:
    """Instalado e sem conexão: o primeiro uso pede o PostgreSQL."""
    return (not os.environ.get("HONORARIOS_BANCO_URL") and not os.environ.get("HONORARIOS_DADOS")
            and ler() is None and not caminhos.rodando_do_codigo())


# -------------------------------------------------------------- testar
class FalhaDeConexao(Exception):
    """Mensagem já pronta para mostrar (sem jargão do driver)."""


def _explicar(falha: Exception, conexao: ConexaoPostgres) -> str:
    bruto = str(getattr(falha, "orig", falha)).lower()
    if "password authentication failed" in bruto or "no password supplied" in bruto:
        return "Usuário ou senha recusados pelo servidor."
    if "does not exist" in bruto and "database" in bruto:
        return f"O banco \"{conexao.banco}\" não existe nesse servidor."
    if "could not translate host name" in bruto or "name or service not known" in bruto:
        return f"Não encontrei o servidor \"{conexao.servidor}\" na rede."
    if "connection refused" in bruto or "timeout" in bruto or "timed out" in bruto:
        return (f"O servidor {conexao.servidor}:{conexao.porta} não respondeu. Confira se o "
                "computador do banco está ligado e se o PostgreSQL aceita conexões da rede.")
    return f"Não consegui conectar: {str(getattr(falha, 'orig', falha)).strip()}"


def banco_nao_existe(falha: FalhaDeConexao) -> bool:
    return "não existe nesse servidor" in str(falha)


def testar(conexao: ConexaoPostgres, senha: str) -> str:
    """Conecta e devolve o que há no banco; levanta ``FalhaDeConexao`` explicada."""
    engine = create_engine(conexao.url(senha), connect_args={"connect_timeout": 8})
    try:
        with engine.connect() as ligacao:
            versao = ligacao.execute(text("show server_version")).scalar()
            tabelas = ligacao.execute(text(
                "select count(*) from information_schema.tables where table_schema = 'public'"
            )).scalar()
    except OperationalError as falha:
        raise FalhaDeConexao(_explicar(falha, conexao)) from falha
    finally:
        engine.dispose()
    situacao = ("banco vazio: as tabelas são criadas ao continuar" if not tabelas
                else f"{tabelas} tabela(s) — o banco já tem dados")
    return f"Conectado ao PostgreSQL {versao.split()[0]} · {situacao}."


def criar_banco(conexao: ConexaoPostgres, senha: str) -> None:
    """Cria o banco (precisa de um usuário com permissão para criar bancos)."""
    engine = create_engine(conexao.url(senha, banco="postgres"),
                           isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 8})
    try:
        with engine.connect() as ligacao:
            nome = conexao.banco.replace('"', '""')
            ligacao.execute(text(f'create database "{nome}" encoding \'UTF8\''))
    except OperationalError as falha:
        raise FalhaDeConexao(_explicar(falha, conexao)) from falha
    except Exception as falha:  # noqa: BLE001 - sem permissão, nome inválido…
        raise FalhaDeConexao(
            f"Não consegui criar o banco \"{conexao.banco}\": "
            f"{str(getattr(falha, 'orig', falha)).strip()}") from falha
    finally:
        engine.dispose()
