"""Engine, sessão e criação do banco."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .modelos import Base

_engine: Engine | None = None
_Sessao: sessionmaker[Session] | None = None


def _ligar_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _ao_conectar(conexao, _registro):  # noqa: ANN001
        cursor = conexao.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def _url(destino: Path | str | URL | None) -> URL | str:
    """Caminho de arquivo vira SQLite; URL vale como está; nada = a configuração."""
    if destino is None:
        from ..config.conexao import url_do_banco

        return url_do_banco()
    if isinstance(destino, URL) or "://" in str(destino):
        return destino
    return f"sqlite:///{destino}"


def criar_engine(caminho: Path | str | URL | None = None, echo: bool = False) -> Engine:
    url = _url(caminho)
    if (url.drivername if isinstance(url, URL) else str(url)).startswith("sqlite"):
        engine = create_engine(url, echo=echo, future=True)
        _ligar_pragmas(engine)
        return engine
    # PostgreSQL na rede: confere a conexão antes de usar (o servidor pode ter caído)
    return create_engine(url, echo=echo, future=True, pool_pre_ping=True,
                         connect_args={"connect_timeout": 10})


def configurar(caminho: Path | str | None = None, criar: bool = True) -> Engine:
    """Prepara o engine global. ``criar`` monta o esquema se o banco é novo."""
    global _engine, _Sessao
    _engine = criar_engine(caminho)
    _Sessao = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    if criar:
        Base.metadata.create_all(_engine)
    return _engine


def engine() -> Engine:
    if _engine is None:
        configurar()
    assert _engine is not None
    return _engine


def sessao() -> Session:
    if _Sessao is None:
        configurar()
    assert _Sessao is not None
    return _Sessao()


@contextmanager
def transacao() -> Iterator[Session]:
    """Sessão com commit no sucesso e rollback no erro."""
    sessao_atual = sessao()
    try:
        yield sessao_atual
        sessao_atual.commit()
    except Exception:
        sessao_atual.rollback()
        raise
    finally:
        sessao_atual.close()


def encerrar() -> None:
    global _engine, _Sessao
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Sessao = None
