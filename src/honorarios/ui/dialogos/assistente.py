"""Cobrança de várias empresas: passa uma por uma, com a mensagem pronta.

Reaproveita o diálogo "Cobrar" para não existirem duas formas de gerar a mesma
mensagem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ...dominio.valores import ZERO, formatar_moeda
from ..comum import widgets
from ..contexto import Contexto
from .cobrar import DialogoCobrar


@dataclass
class Andamento:
    cobradas: int = 0
    puladas: int = 0
    honorarios: int = 0
    total: Decimal = field(default=ZERO)

    @property
    def resumo(self) -> str:
        return (
            f"{self.cobradas} empresa(s) cobrada(s), {self.honorarios} honorário(s), "
            f"total {formatar_moeda(self.total)}. {self.puladas} pulada(s)."
        )


def executar_assistente(contexto: Contexto, grupos, parent=None) -> Andamento:
    """Abre o diálogo de cobrança para cada empresa da fila, em sequência."""
    andamento = Andamento()
    total_grupos = len(grupos)
    for indice, (cliente, linhas) in enumerate(grupos, start=1):
        dialogo = DialogoCobrar(contexto, cliente, list(linhas), parent)
        dialogo.setWindowTitle(
            f"Cobrar {indice} de {total_grupos} – {cliente.nome}"
        )
        dialogo.exec()
        if dialogo.registrou:
            marcados = dialogo.modelo.marcados()
            andamento.cobradas += 1
            andamento.honorarios += len(marcados)
            andamento.total += sum(
                (linha.atualizacao.total for linha in marcados), start=ZERO
            )
        else:
            andamento.puladas += 1
            if indice < total_grupos and not widgets.confirmar(
                parent,
                "Continuar com as próximas empresas da fila?",
                "Cobrança de várias empresas",
                f"Faltam {total_grupos - indice} empresa(s). "
                "Cancelar encerra o assistente.",
            ):
                break
    return andamento
