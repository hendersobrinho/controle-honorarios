"""Tarefa em segundo plano: rede (e-mail) sem travar a tela.

A função roda numa thread do ``QThreadPool``; o resultado (ou o erro) volta para a
thread da tela por sinal, onde se pode mexer no banco e nos widgets. A função em
segundo plano nunca usa a sessão do banco.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Sinais(QObject):
    terminou = Signal(object)
    falhou = Signal(object)


class _Tarefa(QRunnable):
    def __init__(self, funcao: Callable[[], object]) -> None:
        super().__init__()
        self.funcao = funcao
        self.sinais = _Sinais()

    def run(self) -> None:  # noqa: D401 - nome da API do Qt
        try:
            resultado = self.funcao()
        except Exception as falha:  # noqa: BLE001 - o erro volta para a tela
            self.sinais.falhou.emit(falha)
        else:
            self.sinais.terminou.emit(resultado)


_vivas: set[_Tarefa] = set()   # segura a referência até o sinal chegar


def executar(funcao: Callable[[], object], ao_terminar: Callable[[object], None],
             ao_falhar: Callable[[Exception], None]) -> None:
    tarefa = _Tarefa(funcao)
    tarefa.setAutoDelete(False)
    _vivas.add(tarefa)

    def fim(resultado, tratar=ao_terminar):
        _vivas.discard(tarefa)
        tratar(resultado)

    tarefa.sinais.terminou.connect(fim)
    tarefa.sinais.falhou.connect(lambda falha: fim(falha, ao_falhar))
    QThreadPool.globalInstance().start(tarefa)


def imediato(funcao: Callable[[], object], ao_terminar: Callable[[object], None],
             ao_falhar: Callable[[Exception], None]) -> None:
    """Mesma interface, na hora e na mesma thread (para os testes)."""
    try:
        resultado = funcao()
    except Exception as falha:  # noqa: BLE001
        ao_falhar(falha)
    else:
        ao_terminar(resultado)
