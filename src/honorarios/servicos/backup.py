"""Backup do arquivo SQLite, com rotação, e restauração pela interface."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from ..config.caminhos import caminho_banco, pasta_backups
from ..infra import db
from .erros import ErroDeNegocio

PREFIXO = "honorarios-"
SUFIXO = ".db"


@dataclass(frozen=True)
class ArquivoBackup:
    caminho: Path
    quando: datetime
    tamanho: int

    @property
    def rotulo(self) -> str:
        return f"{self.quando:%d/%m/%Y %H:%M} – {self.tamanho / 1024:.0f} KB"


def gerar(motivo: str = "manual", manter: int = 20) -> Path:
    """Copia o banco com o VACUUM INTO, que gera um arquivo consistente."""
    origem = caminho_banco()
    if not origem.exists():
        raise ErroDeNegocio("Não há banco de dados para copiar ainda.")
    marca = datetime.now().strftime("%Y%m%d-%H%M%S")
    destino = pasta_backups() / f"{PREFIXO}{marca}-{motivo}{SUFIXO}"
    try:
        with db.engine().connect() as conexao:
            conexao.execute(text("VACUUM INTO :destino"), {"destino": str(destino)})
    except Exception:  # noqa: BLE001 - fallback quando o VACUUM INTO não existe
        shutil.copy2(origem, destino)
    rotacionar(manter)
    return destino


def listar() -> list[ArquivoBackup]:
    arquivos = []
    for caminho in sorted(pasta_backups().glob(f"{PREFIXO}*{SUFIXO}"), reverse=True):
        info = caminho.stat()
        arquivos.append(
            ArquivoBackup(
                caminho=caminho,
                quando=datetime.fromtimestamp(info.st_mtime),
                tamanho=info.st_size,
            )
        )
    return arquivos


def rotacionar(manter: int = 20) -> int:
    apagados = 0
    for arquivo in listar()[max(1, manter) :]:
        arquivo.caminho.unlink(missing_ok=True)
        apagados += 1
    return apagados


def restaurar(backup: Path) -> Path:
    """Guarda o banco atual antes de sobrescrever — restauração não perde nada."""
    if not Path(backup).exists():
        raise ErroDeNegocio(f"Backup não encontrado: {backup}")
    atual = caminho_banco()
    if atual.exists():
        marca = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(atual, pasta_backups() / f"{PREFIXO}{marca}-antes-da-restauracao{SUFIXO}")
    db.encerrar()
    for extra in (".db-wal", ".db-shm"):
        Path(str(atual).replace(".db", extra)).unlink(missing_ok=True)
    shutil.copy2(backup, atual)
    db.configurar(atual, criar=False)
    return atual
