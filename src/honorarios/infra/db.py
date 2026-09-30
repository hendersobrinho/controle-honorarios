"""Engine, sessão e criação do banco."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from ..config.caminhos import caminho_banco
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


def criar_engine(caminho: Path | str | None = None, echo: bool = False) -> Engine:
    destino = str(caminho or caminho_banco())
    url = destino if destino.startswith("sqlite") else f"sqlite:///{destino}"
    engine = create_engine(url, echo=echo, future=True)
    _ligar_pragmas(engine)
    return engine


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
