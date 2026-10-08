"""Ponto de entrada do aplicativo."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__
from .config import registro
from .config.caminhos import caminho_banco
from .dominio.valores import hoje
from .infra import carga_inicial, db, esquema
from .ui.contexto import Contexto
from .ui.janela_principal import JanelaPrincipal


def preparar_banco() -> None:
    esquema.preparar()
    with db.transacao() as sessao:
        carga_inicial.aplicar(sessao)


def primeiro_uso() -> bool:
    """Instalado e sem pasta de dados escolhida: pergunta onde fica o banco.

    Devolve False se a pessoa fechou sem escolher (o programa não abre)."""
    from .config import caminhos

    # --primeiro-uso: mostra a tela para conferir, sem gravar nada (desenvolvimento)
    demonstracao = "--primeiro-uso" in sys.argv
    if not caminhos.precisa_configurar() and not demonstracao:
        return True
    from .ui.comum import cores, tema
    from .ui.dialogos.primeiro_uso import DialogoPrimeiroUso

    cores.definir_tema("claro")
    QApplication.instance().setStyleSheet(tema.folha_de_estilo("claro"))
    return bool(DialogoPrimeiroUso(demonstracao=demonstracao).exec())


def _falha_no_banco(falha: Exception) -> str:
    """O banco não abriu (servidor desligado, rede, senha): tentar, reconfigurar ou sair."""
    from .config import conexao

    caixa = QMessageBox()
    caixa.setIcon(QMessageBox.Icon.Warning)
    caixa.setWindowTitle("Não foi possível abrir o banco de dados")
    if conexao.usa_postgres():
        caixa.setText(f"Não consegui conectar ao banco ({conexao.descricao()}).")
        caixa.setInformativeText(
            "Confira se o computador do banco está ligado e na rede.\n\n"
            f"Detalhe: {str(getattr(falha, 'orig', falha)).strip()[:300]}")
    else:
        caixa.setText("Não consegui abrir o banco de dados.")
        caixa.setInformativeText(f"{falha}\n\nVerifique {caminho_banco()} ou restaure um backup.")
    tentar = caixa.addButton("Tentar de novo", QMessageBox.ButtonRole.AcceptRole)
    configurar = caixa.addButton("Configurar conexão…", QMessageBox.ButtonRole.ActionRole)
    caixa.addButton("Sair", QMessageBox.ButtonRole.RejectRole)
    caixa.setDefaultButton(tentar)
    caixa.exec()
    if caixa.clickedButton() is tentar:
        return "tentar"
    if caixa.clickedButton() is configurar:
        return "configurar"
    return "sair"


def main(argumentos: list[str] | None = None) -> int:
    aplicativo = QApplication(argumentos if argumentos is not None else sys.argv)
    aplicativo.setApplicationName("Financeiro Métodos")
    aplicativo.setOrganizationName("Métodos Serviços Contábeis")
    aplicativo.setApplicationVersion(__version__)
    from .ui.comum.notificacoes import icone_da_marca

    aplicativo.setWindowIcon(icone_da_marca())
    if not primeiro_uso():   # antes do log: o log vai para a pasta escolhida
        return 0
    registro.configurar()
    log = registro.log(__name__)

    from .ui.comum.logo import TelaAbertura

    abertura = TelaAbertura()
    abertura.show()
    while True:
        abertura.avancar(3, "Conectando ao banco de dados…")
        try:
            preparar_banco()
            break
        except Exception as falha:  # noqa: BLE001
            log.exception("Falha ao preparar o banco de dados")
            abertura.hide()
            escolha = _falha_no_banco(falha)
            if escolha == "sair":
                return 1
            if escolha == "configurar":
                from .ui.dialogos.primeiro_uso import DialogoPrimeiroUso

                if not DialogoPrimeiroUso().exec():
                    return 1
            db.encerrar()
            abertura.show()

    contexto = Contexto(sessao=db.sessao(), data_referencia=hoje())
    janela = JanelaPrincipal(contexto, progresso=abertura.avancar)
    abertura.avancar(100, "Pronto")
    janela.show()
    abertura.close()
    janela.iniciar_notificacoes()
    log.info("Aplicativo iniciado")
    return aplicativo.exec()


if __name__ == "__main__":
    raise SystemExit(main())
