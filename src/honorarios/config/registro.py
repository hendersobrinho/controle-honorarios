"""Log em arquivo, para conseguir investigar um erro depois do fato."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .caminhos import arquivo_log

_configurado = False


def configurar(nivel: int = logging.INFO) -> None:
    global _configurado
    if _configurado:
        return
    formato = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%d/%m/%Y %H:%M:%S"
    )
    arquivo = RotatingFileHandler(
        arquivo_log(), maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    arquivo.setFormatter(formato)
    console = logging.StreamHandler()
    console.setFormatter(formato)
    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    raiz.addHandler(arquivo)
    raiz.addHandler(console)
    _configurado = True


def log(nome: str) -> logging.Logger:
    return logging.getLogger(nome)
