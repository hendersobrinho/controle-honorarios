"""Pastas locais: log, exportações, backups (e o SQLite, quando é ele o banco).

O banco do escritório é o PostgreSQL (ver ``conexao``). Esta pasta guarda o que é
de cada computador:

1. ``HONORARIOS_DADOS`` (variável de ambiente) — e aí o banco é um SQLite nela
   (cópia de trabalho, testes);
2. rodando do código-fonte (desenvolvimento): ``dados/`` na raiz do projeto;
3. instalado: ``%LOCALAPPDATA%\\Financeiro Métodos\\dados`` (no Linux,
   ``~/.local/share/financeiro-metodos/dados``).

A pasta do programa instalado nunca guarda nada: ela não é gravável e some ao
desinstalar.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

NOME_BANCO = "honorarios.db"
NOME_APLICATIVO = "Financeiro Métodos"


def raiz_projeto() -> Path:
    return Path(__file__).resolve().parents[3]


def rodando_do_codigo() -> bool:
    """Do código-fonte (não instalado): tem o pyproject.toml ao lado do src/."""
    return not getattr(sys, "frozen", False) and (raiz_projeto() / "pyproject.toml").is_file()


def _pasta_do_sistema(variavel: str, padrao_linux: str) -> Path:
    if sys.platform == "win32":
        base = os.environ.get(variavel) or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / NOME_APLICATIVO
    return Path.home() / padrao_linux / "financeiro-metodos"


def pasta_configuracao() -> Path:
    return _pasta_do_sistema("APPDATA", ".config")


def arquivo_configuracao() -> Path:
    return pasta_configuracao() / "configuracao.json"


def pasta_dados_padrao() -> Path:
    """A pasta local do programa instalado (não sincroniza na rede)."""
    return _pasta_do_sistema("LOCALAPPDATA", ".local/share") / "dados"


def precisa_configurar() -> bool:
    """Instalado e sem conexão com o banco: mostrar o primeiro uso."""
    from . import conexao

    return conexao.precisa_configurar()


def pasta_dados() -> Path:
    bruto = os.environ.get("HONORARIOS_DADOS")
    if bruto:
        pasta = Path(bruto).expanduser()
    elif rodando_do_codigo():
        pasta = raiz_projeto() / "dados"
    else:
        pasta = pasta_dados_padrao()
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def caminho_banco() -> Path:
    """O arquivo do SQLite (quando o banco é SQLite: código-fonte, cópia, testes)."""
    return pasta_dados() / NOME_BANCO


def pasta_backups() -> Path:
    pasta = pasta_dados() / "backups"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def pasta_exportacoes() -> Path:
    pasta = pasta_dados() / "exportacoes"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def arquivo_log() -> Path:
    return pasta_dados() / "honorarios.log"
