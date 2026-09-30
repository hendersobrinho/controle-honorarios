"""Estado compartilhado pelas telas: a sessão do banco e a data de trabalho."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from ..dominio.valores import hoje
from ..servicos import configuracoes


@dataclass
class Contexto:
    sessao: Session
    data_referencia: date = field(default_factory=hoje)

    def atualizar(self) -> None:
        """Descarta o que está em memória para reler do banco."""
        self.sessao.expire_all()

    def salvar(self) -> None:
        self.sessao.commit()

    def desfazer(self) -> None:
        self.sessao.rollback()

    def config(self, chave: str, padrao: str = "") -> str:
        return configuracoes.obter(self.sessao, chave, padrao)

    def config_int(self, chave: str, padrao: int = 0) -> int:
        return configuracoes.obter_int(self.sessao, chave, padrao)
