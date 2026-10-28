"""Ligar o sistema ao Claude: o servidor MCP, onde registrá-lo e se está em uso.

O Claude (Desktop ou Code) é quem abre o servidor (``mcp_servidor``) quando precisa;
o sistema não fica "conectado" o tempo todo. Por isso a tela mostra três coisas:

- **o servidor funciona?** — ``testar`` abre o servidor como o Claude abriria e
  pede a lista de ferramentas;
- **o Claude Desktop sabe dele?** — ``registrado_no_desktop`` e
  ``registrar_no_desktop`` (o arquivo de configuração do Claude Desktop);
- **o Claude usou?** — ``ultimo_uso``: cada chamada de ferramenta anota a hora
  no banco.

``testar`` faz rede de processo e roda fora da tela; o resto é rápido.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from . import configuracoes
from .erros import ErroDeNegocio

NOME_SERVIDOR = "financeiro-honorarios"
EXECUTAVEL_MCP = "FinanceiroMetodosMCP.exe"
# as mesmas chaves que o servidor grava (mcp_servidor importa o SDK do MCP; aqui não)
CHAVE_ULTIMO_USO = "mcp_ultimo_uso"
CHAVE_ULTIMA_FERRAMENTA = "mcp_ultima_ferramenta"


@dataclass
class Comando:
    executavel: str
    argumentos: list[str]

    def como_json(self) -> dict:
        return {"command": self.executavel, "args": self.argumentos}

    def linha(self) -> str:
        partes = [self.executavel, *self.argumentos]
        if sys.platform == "win32":   # caminho com espaço: aspas duplas, do jeito do Windows
            return subprocess.list2cmdline(partes)
        return " ".join(shlex.quote(parte) for parte in partes)


def comando_do_servidor() -> Comando:
    """Como abrir o servidor: o .exe próprio no instalado, o Python do projeto no código."""
    if getattr(sys, "frozen", False):
        # o programa de janela não tem entrada/saída padrão: o MCP tem executável de console
        return Comando(str(Path(sys.executable).with_name(EXECUTAVEL_MCP)), [])
    return Comando(sys.executable, ["-m", "honorarios.mcp_servidor"])


def comando_claude_code() -> str:
    """Linha para colar no terminal e registrar no Claude Code (vale para todos os projetos)."""
    return f"claude mcp add --scope user {NOME_SERVIDOR} -- {comando_do_servidor().linha()}"


# ---------------------------------------------------------------- Claude Desktop
def arquivo_do_desktop() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".config"
    return base / "Claude" / "claude_desktop_config.json"


def _ler_desktop(arquivo: Path) -> dict:
    if not arquivo.is_file():
        return {}
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError) as falha:
        raise ErroDeNegocio(
            f"Não consegui ler a configuração do Claude Desktop ({arquivo}): {falha}. "
            "Corrija o arquivo ou apague-o e tente de novo."
        ) from falha
    if not isinstance(dados, dict):
        raise ErroDeNegocio(f"A configuração do Claude Desktop ({arquivo}) não é um objeto JSON.")
    return dados


def registrado_no_desktop(arquivo: Path | None = None) -> bool:
    """O Claude Desktop tem o servidor, apontando para este programa?"""
    try:
        dados = _ler_desktop(arquivo or arquivo_do_desktop())
    except ErroDeNegocio:
        return False
    atual = (dados.get("mcpServers") or {}).get(NOME_SERVIDOR)
    return atual == comando_do_servidor().como_json()


def registrar_no_desktop(arquivo: Path | None = None) -> Path:
    """Põe (ou corrige) o servidor na configuração do Claude Desktop, sem mexer nos outros.

    Guarda uma cópia ``.bak`` do arquivo antes. O Claude Desktop só lê a
    configuração ao abrir: é preciso fechá-lo e abrir de novo.
    """
    arquivo = arquivo or arquivo_do_desktop()
    dados = _ler_desktop(arquivo)
    servidores = dados.setdefault("mcpServers", {})
    if not isinstance(servidores, dict):
        raise ErroDeNegocio("Na configuração do Claude Desktop, mcpServers não é um objeto.")
    servidores[NOME_SERVIDOR] = comando_do_servidor().como_json()
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    if arquivo.is_file():
        shutil.copy2(arquivo, arquivo.with_suffix(".json.bak"))
    arquivo.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")
    return arquivo


# -------------------------------------------------------------------- uso e teste
@dataclass
class Uso:
    quando: datetime
    ferramenta: str


def ultimo_uso(sessao: Session) -> Uso | None:
    texto = configuracoes.obter(sessao, CHAVE_ULTIMO_USO)
    if not texto:
        return None
    try:
        quando = datetime.fromisoformat(texto)
    except ValueError:
        return None
    return Uso(quando, configuracoes.obter(sessao, CHAVE_ULTIMA_FERRAMENTA))


def testar(espera: float = 30) -> int:
    """Abre o servidor como o Claude abriria e devolve quantas ferramentas ele oferece.

    Roda fora da thread da tela (abre processo e espera a resposta).
    """
    import asyncio

    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as falha:
        raise ErroDeNegocio(
            "O suporte ao MCP não está instalado (pip install -e .[mcp])."
        ) from falha

    comando = comando_do_servidor()
    if getattr(sys, "frozen", False) and not Path(comando.executavel).is_file():
        raise ErroDeNegocio(
            f"Não achei {EXECUTAVEL_MCP} na pasta do programa. Reinstale o Financeiro."
        )
    parametros = StdioServerParameters(
        command=comando.executavel, args=comando.argumentos, env=dict(os.environ)
    )

    async def conversar() -> int:
        async with stdio_client(parametros) as (leitura, escrita):
            async with ClientSession(leitura, escrita) as sessao:
                await sessao.initialize()
                return len((await sessao.list_tools()).tools)

    try:
        return asyncio.run(asyncio.wait_for(conversar(), espera))
    except TimeoutError as falha:
        raise ErroDeNegocio(
            f"O servidor não respondeu em {espera:.0f} segundos. Confira a conexão com o banco."
        ) from falha
