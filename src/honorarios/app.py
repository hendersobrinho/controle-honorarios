"""Ponto de entrada do aplicativo."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from .config import registro
from .dominio.valores import hoje
from .infra import carga_inicial, db, esquema
from .ui.contexto import Contexto
from .ui.janela_principal import JanelaPrincipal


def preparar_banco() -> None:
    esquema.preparar()
    with db.transacao() as sessao:
        carga_inicial.aplicar(sessao)


def main(argumentos: list[str] | None = None) -> int:
    registro.configurar()
    log = registro.log(__name__)
    aplicativo = QApplication(argumentos if argumentos is not None else sys.argv)
    aplicativo.setApplicationName("Controle de Honorários")
    aplicativo.setOrganizationName("Métodos Serviços Contábeis")

    try:
        preparar_banco()
    except Exception as falha:  # noqa: BLE001
        log.exception("Falha ao preparar o banco de dados")
        QMessageBox.critical(
            None,
            "Não foi possível abrir o banco de dados",
            f"{falha}\n\nVerifique a pasta dados/ ou restaure um backup.",
        )
        return 1

    contexto = Contexto(sessao=db.sessao(), data_referencia=hoje())
    janela = JanelaPrincipal(contexto)
    janela.show()
    log.info("Aplicativo iniciado")
    return aplicativo.exec()


if __name__ == "__main__":
    raise SystemExit(main())
