"""Ligar o sistema ao Claude: onde gravar o servidor MCP e se o Claude está usando.

O Claude (Desktop ou Code) é quem abre o servidor (``mcp_servidor``) quando precisa,
lendo o comando do arquivo de configuração dele. ``registrar_em_todos`` grava o
servidor em cada Claude do computador (Desktop comum, Desktop da Microsoft Store e
Claude Code); o programa instalado faz isso sozinho toda vez que abre.
``ultimo_uso`` diz quando o Claude chamou uma ferramenta pela última vez.
"""

from __future__ import annotations

import json
import os
import shutil
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


def comando_do_servidor() -> Comando:
    """Como abrir o servidor: o .exe próprio no instalado, o Python do projeto no código."""
    if getattr(sys, "frozen", False):
        # o programa de janela não tem entrada/saída padrão: o MCP tem executável de console
        return Comando(str(Path(sys.executable).with_name(EXECUTAVEL_MCP)), [])
    return Comando(sys.executable, ["-m", "honorarios.mcp_servidor"])


# ---------------------------------------------------------- onde o Claude procura
def _appdata() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")


def _localappdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


def arquivo_do_desktop() -> Path:
    """O arquivo do Claude Desktop instalado pelo instalador comum."""
    if sys.platform == "win32":
        base = _appdata()
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".config"
    return base / "Claude" / "claude_desktop_config.json"


def arquivos_do_desktop() -> list[Path]:
    """Todos os arquivos que um Claude Desktop deste computador pode estar lendo.

    O Claude Desktop da Microsoft Store (pacote MSIX) não enxerga o ``%APPDATA%``
    de verdade: o Windows desvia a pasta para dentro do pacote
    (``%LOCALAPPDATA%\\Packages\\Claude_…\\LocalCache\\Roaming\\Claude``). Gravar só no
    ``%APPDATA%\\Claude`` deixa esse Claude sem o servidor. Por isso vale cada
    instalação encontrada; sem nenhuma, o lugar do instalador comum.
    """
    comum = arquivo_do_desktop()
    achados = [comum] if comum.parent.is_dir() else []
    if sys.platform == "win32":
        pacotes = _localappdata() / "Packages"
        if pacotes.is_dir():
            for pacote in sorted(pacotes.glob("Claude_*")):
                achados.append(pacote / "LocalCache" / "Roaming" / "Claude" /
                               "claude_desktop_config.json")
    return achados or [comum]


def arquivo_do_claude_code() -> Path | None:
    """O ``.claude.json`` do Claude Code (servidores do usuário), se ele estiver instalado."""
    pasta = os.environ.get("CLAUDE_CONFIG_DIR")
    arquivo = Path(pasta) / ".claude.json" if pasta else Path.home() / ".claude.json"
    return arquivo if arquivo.is_file() else None


# ------------------------------------------------------------------ gravar
def _ler_json(arquivo: Path) -> dict:
    if not arquivo.is_file():
        return {}
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8-sig") or "{}")
    except (OSError, ValueError) as falha:
        raise ErroDeNegocio(
            f"Não consegui ler a configuração do Claude ({arquivo}): {falha}. "
            "Corrija o arquivo ou apague-o e tente de novo."
        ) from falha
    if not isinstance(dados, dict):
        raise ErroDeNegocio(f"A configuração do Claude ({arquivo}) não é um objeto JSON.")
    return dados


def _gravar_json(arquivo: Path, dados: dict) -> None:
    """Grava por cima de uma vez (arquivo temporário + troca), sem deixar meio escrito."""
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    if arquivo.is_file():
        shutil.copy2(arquivo, arquivo.with_name(arquivo.name + ".bak"))
    temporario = arquivo.with_name(arquivo.name + ".tmp")
    temporario.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporario, arquivo)


def _servidores(dados: dict, arquivo: Path) -> dict:
    servidores = dados.setdefault("mcpServers", {})
    if not isinstance(servidores, dict):
        raise ErroDeNegocio(f"Em {arquivo}, mcpServers não é um objeto.")
    return servidores


def _aponta_para_nos(entrada) -> bool:
    esperado = comando_do_servidor()
    return isinstance(entrada, dict) and entrada.get("command") == esperado.executavel \
        and list(entrada.get("args") or []) == esperado.argumentos


def registrado_em(arquivo: Path) -> bool:
    """O arquivo tem o servidor, apontando para este programa?"""
    try:
        dados = _ler_json(arquivo)
    except ErroDeNegocio:
        return False
    return _aponta_para_nos((dados.get("mcpServers") or {}).get(NOME_SERVIDOR))


def registrado_no_desktop(arquivo: Path | None = None) -> bool:
    arquivos = [arquivo] if arquivo else arquivos_do_desktop()
    return any(registrado_em(a) for a in arquivos)


def registrar_no_desktop(arquivo: Path | None = None) -> Path:
    """Põe (ou corrige) o servidor na configuração do Claude Desktop, sem mexer nos outros.

    Guarda uma cópia ``.bak`` antes. O Claude Desktop só lê a configuração ao abrir.
    """
    arquivo = arquivo or arquivo_do_desktop()
    dados = _ler_json(arquivo)
    entrada = comando_do_servidor().como_json()
    if _servidores(dados, arquivo).get(NOME_SERVIDOR) != entrada:
        dados["mcpServers"][NOME_SERVIDOR] = entrada
        _gravar_json(arquivo, dados)
    return arquivo


def registrar_no_claude_code(arquivo: Path) -> Path:
    """Servidor do usuário no Claude Code (vale em qualquer pasta), como o ``claude mcp add``."""
    dados = _ler_json(arquivo)
    entrada = {"type": "stdio", **comando_do_servidor().como_json(), "env": {}}
    if not _aponta_para_nos(_servidores(dados, arquivo).get(NOME_SERVIDOR)):
        dados["mcpServers"][NOME_SERVIDOR] = entrada
        _gravar_json(arquivo, dados)
    return arquivo


@dataclass
class Registro:
    gravados: list[Path]
    falhas: list[str]


def registrar_em_todos() -> Registro:
    """Grava o servidor em todo Claude deste computador: Desktop (comum e da Store) e Code.

    O programa instalado chama ao abrir, então a conexão se mantém sozinha (até depois
    de reinstalar em outra pasta). Uma configuração quebrada não impede as outras.
    """
    alvos = [(registrar_no_desktop, a) for a in arquivos_do_desktop()]
    code = arquivo_do_claude_code()
    if code is not None:
        alvos.append((registrar_no_claude_code, code))
    resultado = Registro([], [])
    for registrar, arquivo in alvos:
        try:
            resultado.gravados.append(registrar(arquivo))
        except (ErroDeNegocio, OSError) as falha:
            resultado.falhas.append(f"{arquivo}: {falha}")
    if not resultado.gravados and resultado.falhas:
        raise ErroDeNegocio("Não consegui gravar o servidor no Claude.\n" +
                            "\n".join(resultado.falhas))
    return resultado


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
