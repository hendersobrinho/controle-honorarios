"""Janela principal: navegação à esquerda, tela de trabalho à direita."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from ..dominio.valores import formatar_data, hoje
from ..servicos import backup as servico_backup
from ..servicos import configuracoes as servico_configuracoes
from .comum import cores, tema, widgets
from .contexto import Contexto
from .paineis.acompanhamento import PainelAcompanhamento
from .paineis.avulsos import PainelAvulsos
from .paineis.clientes import PainelClientes
from .paineis.cobranca_geral import PainelCobrancaGeral
from .paineis.configuracoes import PainelConfiguracoes
from .paineis.contratos import PainelContratos
from .paineis.fila_dia import PainelFilaDia
from .paineis.fila_envio import PainelFilaEnvio
from .paineis.importar import PainelImportar
from .paineis.painel import PainelResumo
from .paineis.relatorios import PainelRelatorios


class JanelaPrincipal(QMainWindow):
    def __init__(self, contexto: Contexto) -> None:
        super().__init__()
        self.contexto = contexto
        self.setWindowTitle("Controle de Honorários – Métodos Serviços Contábeis")
        self.resize(1360, 820)
        self._montar()
        self._aplicar_tema()

    def _montar(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.navegacao = QListWidget()
        self.navegacao.setObjectName("navegacao")
        self.navegacao.setFixedWidth(210)
        layout.addWidget(self.navegacao)

        self.telas = QStackedWidget()
        self.telas.setContentsMargins(14, 14, 14, 14)
        layout.addWidget(self.telas, 1)
        self.setCentralWidget(central)

        # a navegação é agrupada pelo momento do trabalho: cobrar, cadastrar, gerir
        grupos = (
            ("COBRANÇA", (
                PainelCobrancaGeral,
                PainelFilaDia,
                PainelFilaEnvio,
                PainelAcompanhamento,
            )),
            ("CADASTROS", (PainelClientes, PainelContratos, PainelAvulsos)),
            ("GESTÃO", (
                PainelResumo,
                PainelRelatorios,
                PainelImportar,
                PainelConfiguracoes,
            )),
        )

        self.paineis: list[QWidget] = []
        self.linhas_de_tela: dict[int, int] = {}   # linha da lista -> índice da tela
        for titulo_grupo, classes in grupos:
            if self.navegacao.count():
                self._separador()
            self._cabecalho_grupo(titulo_grupo)
            for classe in classes:
                painel = classe(self.contexto)
                indice = self.telas.addWidget(painel)
                self.paineis.append(painel)
                item = QListWidgetItem(classe.titulo)
                self.navegacao.addItem(item)
                self.linhas_de_tela[self.navegacao.row(item)] = indice

        self.navegacao.currentRowChanged.connect(self._trocar_tela)
        self.navegacao.setCurrentRow(next(iter(self.linhas_de_tela)))

        self.statusBar().showMessage(self._mensagem_status())

        atalho_atualizar = QAction("Atualizar", self)
        atalho_atualizar.setShortcut(QKeySequence("F5"))
        atalho_atualizar.triggered.connect(self._recarregar_atual)
        self.addAction(atalho_atualizar)
        for numero, linha in enumerate(list(self.linhas_de_tela)[:9], start=1):
            acao = QAction(self)
            acao.setShortcut(QKeySequence(f"Ctrl+{numero}"))
            acao.triggered.connect(
                lambda _=False, alvo=linha: self.navegacao.setCurrentRow(alvo)
            )
            self.addAction(acao)

    def _cabecalho_grupo(self, titulo: str) -> None:
        item = QListWidgetItem(titulo)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        fonte = item.font()
        fonte.setPointSizeF(max(8.0, fonte.pointSizeF() - 2))
        fonte.setBold(True)
        item.setFont(fonte)
        item.setForeground(tema.cor("texto_fraco", cores.tema_atual()))
        self.navegacao.addItem(item)

    def _separador(self) -> None:
        espaco = QListWidgetItem()
        espaco.setFlags(Qt.ItemFlag.NoItemFlags)
        espaco.setSizeHint(QSize(0, 12))
        self.navegacao.addItem(espaco)

    def _mensagem_status(self) -> str:
        from ..config.caminhos import caminho_banco

        return (
            f"Hoje: {formatar_data(hoje())} · data de referência: "
            f"{formatar_data(self.contexto.data_referencia)} · banco: {caminho_banco()}"
        )

    def _trocar_tela(self, linha: int) -> None:
        indice = self.linhas_de_tela.get(linha)
        if indice is None:  # clicou num título de grupo
            return
        self.telas.setCurrentIndex(indice)
        self._recarregar_atual()
        self.statusBar().showMessage(self._mensagem_status())

    def _recarregar_atual(self) -> None:
        painel = self.telas.currentWidget()
        if hasattr(painel, "recarregar"):
            widgets.executar(self, painel.recarregar)

    def _aplicar_tema(self) -> None:
        """Aplica no aplicativo, não só na janela, para os diálogos herdarem."""
        from PySide6.QtWidgets import QApplication

        nome = servico_configuracoes.obter(self.contexto.sessao, "tema", "claro")
        cores.definir_tema(nome)
        folha = tema.folha_de_estilo(nome)
        aplicativo = QApplication.instance()
        if aplicativo is not None:
            aplicativo.setStyleSheet(folha)
        else:
            self.setStyleSheet(folha)

    def closeEvent(self, evento) -> None:  # noqa: N802
        """Backup automático ao fechar, se estiver ligado nas configurações."""
        sessao = self.contexto.sessao
        try:
            if servico_configuracoes.obter_bool(sessao, "backup_ao_fechar", True):
                manter = servico_configuracoes.obter_int(sessao, "backup_manter", 20)
                servico_backup.gerar("ao-fechar", manter)
        except Exception:  # noqa: BLE001
            from ..config.registro import log

            log(__name__).exception("Falha ao gerar o backup de encerramento")
        try:
            sessao.commit()
        except Exception:  # noqa: BLE001
            sessao.rollback()
        finally:
            sessao.close()
        super().closeEvent(evento)
