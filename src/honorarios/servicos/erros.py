"""Erros de regra de negócio, com mensagem pronta para a tela."""

from __future__ import annotations


class ErroDeNegocio(Exception):
    """Algo que o usuário precisa corrigir. A mensagem é exibida como está."""


class ErroDeValidacao(ErroDeNegocio):
    def __init__(self, mensagem: str, campo: str = "") -> None:
        self.campo = campo
        super().__init__(mensagem)


class RegistroDuplicado(ErroDeNegocio):
    pass
