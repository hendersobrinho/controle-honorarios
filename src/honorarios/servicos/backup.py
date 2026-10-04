"""Backup com rotação, e restauração pela interface.

- **SQLite** (código-fonte, cópia de trabalho): cópia do arquivo (``VACUUM INTO``).
- **PostgreSQL** (o banco do escritório): o banco inteiro é copiado, tabela por
  tabela, para um arquivo SQLite local na pasta de backups deste computador —
  o mesmo formato, então listar, rotacionar e restaurar funcionam igual. A
  restauração devolve tudo ao PostgreSQL numa transação só (tudo ou nada) e só
  aceita backup da mesma versão do banco.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine, Table, inspect, select, text

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


def _postgres() -> bool:
    return db.engine().dialect.name == "postgresql"


def _versao(conexao) -> str | None:
    if "alembic_version" not in inspect(conexao).get_table_names():
        return None
    return conexao.execute(text("select version_num from alembic_version")).scalar()


def _tabelas() -> list[Table]:
    from ..infra.modelos import Base

    return list(Base.metadata.sorted_tables)


def _auto_referencias(tabela: Table) -> list[str]:
    """Colunas que apontam para a própria tabela (ex.: cliente.empresa_id)."""
    return [chave.parent.name for chave in tabela.foreign_keys
            if chave.column.table is tabela]


def _copiar(origem: Engine, destino: Engine, limpar: bool) -> None:
    """Todas as tabelas, na ordem das chaves estrangeiras, numa transação só."""
    with origem.connect() as ler, destino.begin() as gravar:
        tabelas = _tabelas()
        if limpar:
            for tabela in reversed(tabelas):
                gravar.execute(tabela.delete())
        for tabela in tabelas:
            linhas = [dict(linha._mapping) for linha in ler.execute(select(tabela))]
            if not linhas:
                continue
            proprias = _auto_referencias(tabela)
            # referência à própria tabela: entra vazia e é preenchida depois
            primeiro = [{**linha, **dict.fromkeys(proprias)} for linha in linhas]
            gravar.execute(tabela.insert(), primeiro)
            for coluna in proprias:
                for linha in linhas:
                    if linha[coluna] is not None:
                        gravar.execute(tabela.update().where(tabela.c.id == linha["id"])
                                       .values({coluna: linha[coluna]}))
        if destino.dialect.name == "postgresql":   # os contadores de id continuam do máximo
            for tabela in tabelas:
                if "id" in tabela.c:
                    gravar.execute(text(
                        f"select setval(pg_get_serial_sequence('{tabela.name}', 'id'), "
                        f"coalesce((select max(id) from {tabela.name}), 1), "
                        f"(select max(id) from {tabela.name}) is not null)"))


def _gerar_do_postgres(destino: Path) -> None:
    from ..infra.modelos import Base

    local = db.criar_engine(destino)
    try:
        Base.metadata.create_all(local)
        _copiar(db.engine(), local, limpar=False)
        with db.engine().connect() as servidor, local.begin() as copia:
            versao = _versao(servidor)
            copia.execute(text("create table alembic_version (version_num varchar(32) "
                               "not null primary key)"))
            if versao:
                copia.execute(text("insert into alembic_version values (:v)"), {"v": versao})
    finally:
        local.dispose()


def gerar(motivo: str = "manual", manter: int = 20) -> Path:
    """SQLite: VACUUM INTO (arquivo consistente). PostgreSQL: cópia para um SQLite local."""
    if _postgres():
        marca = datetime.now().strftime("%Y%m%d-%H%M%S")
        destino = pasta_backups() / f"{PREFIXO}{marca}-{motivo}{SUFIXO}"
        try:
            _gerar_do_postgres(destino)
        except Exception:
            destino.unlink(missing_ok=True)
            raise
        rotacionar(manter)
        return destino
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


def _restaurar_no_postgres(backup: Path) -> None:
    local = db.criar_engine(backup)
    try:
        with local.connect() as copia, db.engine().connect() as servidor:
            de_la, daqui = _versao(copia), _versao(servidor)
        if de_la != daqui:
            raise ErroDeNegocio(
                "Este backup é de outra versão do banco e não pode ser restaurado nesta. "
                f"(backup: {de_la or 'sem versão'}; banco: {daqui or 'sem versão'})")
        gerar("antes-da-restauracao", manter=1000)   # nada se perde
        _copiar(local, db.engine(), limpar=True)
    finally:
        local.dispose()


def restaurar(backup: Path) -> Path | str:
    """Guarda o banco atual antes de sobrescrever — restauração não perde nada."""
    if not Path(backup).exists():
        raise ErroDeNegocio(f"Backup não encontrado: {backup}")
    if _postgres():
        _restaurar_no_postgres(Path(backup))
        return "PostgreSQL"
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
