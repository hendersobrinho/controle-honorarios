"""Onde ficam banco, backups e logs.

Tudo dentro de ``dados/`` na raiz do projeto (ignorada pelo git), ou no caminho
apontado por ``HONORARIOS_DADOS`` — é o que permite rodar contra uma cópia sem
tocar no banco de produção.
"""

from __future__ import annotations

import os
from pathlib import Path

NOME_BANCO = "honorarios.db"


def raiz_projeto() -> Path:
    return Path(__file__).resolve().parents[3]


def pasta_dados() -> Path:
    bruto = os.environ.get("HONORARIOS_DADOS")
    pasta = Path(bruto).expanduser() if bruto else raiz_projeto() / "dados"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def caminho_banco() -> Path:
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
