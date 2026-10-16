"""Janela principal: navegação à esquerda, tela de trabalho à direita."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QFontMetricsF, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from ..dominio.valores import formatar_data, hoje
from ..servicos import backup as servico_backup
from ..servicos import configuracoes as servico_configuracoes
from .comum import cores, logo, tema, widgets
from .comum.notificacoes import AvisoNovo, BotaoNotificacoes, ListaNotificacoes, icone_da_marca
from .contexto import Contexto
from .paineis.acompanhamento import PainelAcompanhamento
from .paineis.cadastro_honorarios import PainelHonorarios
from .paineis.clientes import PainelClientes
from .paineis.configuracoes import PainelConfiguracoes
from .paineis.email_cobrancas import PainelEmailCobrancas
from .paineis.honorarios import PainelImpostoRenda
from .paineis.importacao_personalizada import PainelImportacaoPersonalizada
from .paineis.importar import PainelImportar
from .paineis.painel import PainelResumo
from .paineis.rankings import PainelRankings
from .paineis.relatorios import PainelRelatorios
from .paineis.tipos_e_envio import PainelTiposEEnvio
from .paineis.vencimentos import PainelVencimentos


class JanelaPrincipal(QMainWindow):
    def __init__(self, contexto: Contexto, progresso=None) -> None:
        """``progresso(porcentagem, texto)``: avisa a tela de abertura a cada tela montada."""
        super().__init__()
        self.contexto = contexto
        self._progresso = progresso or (lambda *_: None)
        self.bandeja = None   # ícone na bandeja do sistema, para a notificação do sistema
        self.setWindowTitle("Financeiro Métodos")
        self.resize(1360, 820)
        self._montar()
        self._aplicar_tema()

    def _montar(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # coluna do menu: a lista de telas e, fixa embaixo, a logo
        coluna = QWidget()
        coluna.setObjectName("colunaNavegacao")
        coluna.setFixedWidth(210)
        coluna_layout = QVBoxLayout(coluna)
        coluna_layout.setContentsMargins(0, 0, 0, 16)
        coluna_layout.setSpacing(8)
        self.navegacao = QListWidget()
        self.navegacao.setObjectName("navegacao")
        self.navegacao.setItemDelegate(ContadorDoMenu(self.navegacao))
        coluna_layout.addWidget(self.navegacao, 1)
        self.botao_notificacoes = BotaoNotificacoes()
        self.botao_notificacoes.clicked.connect(self.abrir_notificacoes)
        linha_botao = QHBoxLayout()
        linha_botao.setContentsMargins(10, 0, 10, 0)
        linha_botao.addWidget(self.botao_notificacoes)
        coluna_layout.addLayout(linha_botao)
        self.logo_menu = QLabel()
        self.logo_menu.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_menu.setToolTip("Métodos Financeiro")
        coluna_layout.addWidget(self.logo_menu)
        layout.addWidget(coluna)

        self.telas = QStackedWidget()
        self.telas.setContentsMargins(14, 14, 14, 14)
        layout.addWidget(self.telas, 1)
        self.setCentralWidget(central)
        # o aviso do canto fica por cima das telas, filho da área
        # central: se fossem filhos da pilha de telas, a tela que abre os cobriria
        self.central = central
        self.lista_notificacoes = ListaNotificacoes(self)
        self.lista_notificacoes.abrir.connect(self._abrir_notificacao)
        self.lista_notificacoes.marcar_todas.connect(self._marcar_todas_lidas)
        self.aviso_novo = AvisoNovo(self.central)
        self.aviso_novo.ver.connect(self.abrir_notificacoes)
        self.verificacao = QTimer(self)
        self.verificacao.setInterval(INTERVALO_VERIFICACAO_MS)
        self.verificacao.timeout.connect(self.verificar_notificacoes)
        self.verificacao.timeout.connect(self.verificar_email)

        # a navegação é agrupada pelo momento do trabalho. Cada situação de
        # honorário tem a sua aba em Vencimentos (a vencer, atrasado e pago nunca se
        # misturam),
        # e as cobranças já feitas ficam ao lado, para anotar a resposta.
        grupos = (
            ("COBRANÇA", (
                PainelVencimentos,    # abas: A vencer, Atrasados, Pagos
                PainelImpostoRenda,
                PainelAcompanhamento,
                PainelEmailCobrancas,
            )),
            ("CADASTROS", (PainelClientes, PainelHonorarios, PainelTiposEEnvio)),
            ("GESTÃO", (
                PainelResumo,
                PainelRankings,
                PainelRelatorios,
                PainelImportar,
                PainelImportacaoPersonalizada,
                PainelConfiguracoes,
            )),
        )

        # Só as telas que trabalham desde a abertura são montadas já (a primeira
        # tela e a do e-mail, que verifica a caixa); as outras, na primeira vez em
        # que forem abertas — cada uma lê e calcula os seus dados ao ser montada.
        ja_na_abertura = (grupos[0][1][0], PainelEmailCobrancas)
        self.paineis: list[QWidget] = []
        self.linhas_de_tela: dict[int, int] = {}   # linha da lista -> índice da tela
        self.itens_de_tela: dict[str, QListWidgetItem] = {}
        self._recem_montada: QWidget | None = None
        self._lidas: dict[int, tuple] = {}   # tela -> estado dos dados quando leu
        total = sum(len(classes) for _, classes in grupos)
        montadas = 0
        for numero, (titulo_grupo, classes) in enumerate(grupos):
            if self.navegacao.count():
                self._separador()
            self._cabecalho_grupo(titulo_grupo, numero)
            for classe in classes:
                self._progresso(10 + round(85 * montadas / total), f"Carregando {classe.titulo}…")
                montadas += 1
                painel = classe(self.contexto) if classe in ja_na_abertura else TelaAdiada(classe)
                indice = self.telas.addWidget(painel)
                self.paineis.append(painel)
                item = QListWidgetItem(classe.titulo)
                item.setData(ContadorDoMenu.PAPEL_GRUPO, numero)
                self.navegacao.addItem(item)
                self.linhas_de_tela[self.navegacao.row(item)] = indice
                self.itens_de_tela[classe.titulo] = item

        self.painel_email = next(
            (p for p in self.paineis if isinstance(p, PainelEmailCobrancas)), None
        )
        if self.painel_email is not None:
            self.painel_email.chegaram.connect(self._chegaram_emails)
            self.painel_email.recarregado.connect(self._atualizar_contadores)
        self.navegacao.currentRowChanged.connect(self._trocar_tela)
        self.navegacao.setCurrentRow(next(iter(self.linhas_de_tela)))
        self._atualizar_contadores()

        self.statusBar().showMessage(self._mensagem_status())

        atalho_atualizar = QAction("Atualizar", self)
        atalho_atualizar.setShortcut(QKeySequence("F5"))
        atalho_atualizar.triggered.connect(lambda: self._recarregar_atual(forcar=True))
        self.addAction(atalho_atualizar)
        for numero, linha in enumerate(list(self.linhas_de_tela)[:9], start=1):
            acao = QAction(self)
            acao.setShortcut(QKeySequence(f"Ctrl+{numero}"))
            acao.triggered.connect(
                lambda _=False, alvo=linha: self.navegacao.setCurrentRow(alvo)
            )
            self.addAction(acao)

    def _cabecalho_grupo(self, titulo: str, numero: int) -> None:
        """O nome do grupo, na cor dele (desenhado pelo ContadorDoMenu)."""
        item = QListWidgetItem(titulo)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setData(ContadorDoMenu.PAPEL_CABECALHO, numero)
        item.setSizeHint(QSize(0, 34))
        self.navegacao.addItem(item)

    def _separador(self) -> None:
        espaco = QListWidgetItem()
        espaco.setFlags(Qt.ItemFlag.NoItemFlags)
        espaco.setData(ContadorDoMenu.PAPEL_SEPARADOR, True)
        espaco.setSizeHint(QSize(0, 18))
        self.navegacao.addItem(espaco)

    def _mensagem_status(self) -> str:
        from ..config.conexao import descricao

        return (
            f"Hoje: {formatar_data(hoje())} · data de referência: "
            f"{formatar_data(self.contexto.data_referencia)} · banco: {descricao()}"
        )

    def tela(self, indice: int) -> QWidget:
        """A tela desse índice, montada agora se ainda não foi."""
        atual = self.telas.widget(indice)
        if not isinstance(atual, TelaAdiada):
            return atual
        painel = atual.classe(self.contexto)   # já lê os dados ao ser montada
        era_a_atual = self.telas.currentIndex() == indice
        self.telas.insertWidget(indice, painel)
        self.telas.removeWidget(atual)
        atual.deleteLater()
        self.paineis[self.paineis.index(atual)] = painel
        if era_a_atual:
            self.telas.setCurrentIndex(indice)
        self._recem_montada = painel
        return painel

    def _trocar_tela(self, linha: int) -> None:
        indice = self.linhas_de_tela.get(linha)
        if indice is None:  # clicou num título de grupo
            return
        self.tela(indice)
        self.telas.setCurrentIndex(indice)
        self._recarregar_atual()  # também atualiza os contadores
        self.statusBar().showMessage(self._mensagem_status())

    def _atualizar_contadores(self) -> None:
        """Quantidade ao lado das telas de cobrança, para ver o volume sem abrir."""
        from ..servicos import caixa_email
        from ..servicos import honorarios as servico_honorarios

        try:   # contado no banco: não carrega nem calcula os honorários
            contagem = servico_honorarios.contar_pendentes(
                self.contexto.sessao, self.contexto.data_referencia
            )
            emails = caixa_email.nao_lidos(self.contexto.sessao)
        except Exception:  # noqa: BLE001 - contador nunca derruba a navegação
            return
        contagens = (
            (PainelVencimentos.titulo, contagem.atrasados),
            (PainelImpostoRenda.titulo, contagem.imposto_de_renda),
            (PainelEmailCobrancas.titulo, emails),
        )
        for titulo, quantidade in contagens:
            item = self.itens_de_tela.get(titulo)
            if item is not None:
                item.setData(ContadorDoMenu.PAPEL, quantidade or None)

    def _estado_dos_dados(self) -> tuple:
        return (self.contexto.versao, self.contexto.data_referencia, hoje())

    def _recarregar_atual(self, forcar: bool = False) -> None:
        """Relê a tela aberta — ao voltar a uma tela, só se algo mudou desde a última
        leitura (gravação no banco, dia ou data de referência). F5 sempre relê."""
        painel = self.telas.currentWidget()
        recem = painel is self._recem_montada   # acabou de ler os dados ao ser montada
        self._recem_montada = None
        estado = self._estado_dos_dados()
        em_dia = self._lidas.get(id(painel)) == estado
        if hasattr(painel, "recarregar") and (forcar or not (recem or em_dia)):
            widgets.executar(self, painel.recarregar)
        self._lidas[id(painel)] = estado
        self._atualizar_contadores()

    def _aplicar_tema(self) -> None:
        """Aplica no aplicativo, não só na janela, para os diálogos herdarem."""
        from PySide6.QtWidgets import QApplication

        nome = servico_configuracoes.obter(self.contexto.sessao, "tema", "claro")
        cores.definir_tema(nome)
        self.logo_menu.setPixmap(logo.pixmap(170, escuro=nome == "escuro"))
        folha = tema.folha_de_estilo(nome)
        aplicativo = QApplication.instance()
        if aplicativo is not None:
            aplicativo.setStyleSheet(folha)
        else:
            self.setStyleSheet(folha)

    def _posicionar_aviso(self) -> None:
        margem = 18
        area = self.telas.geometry()   # nas coordenadas da área central
        self.aviso_novo.adjustSize()
        self.aviso_novo.move(
            area.x() + area.width() - margem - self.aviso_novo.width(),
            area.y() + area.height() - margem - self.aviso_novo.height(),
        )
        self.aviso_novo.raise_()

    # ------------------------------------------------------------ notificações
    def iniciar_notificacoes(self) -> None:
        """Ao abrir: limpa as lidas antigas, verifica agora e a cada meia hora."""
        from ..servicos import notificacoes

        try:
            notificacoes.limpar_antigas(self.contexto.sessao)
            self.contexto.salvar()
        except Exception:  # noqa: BLE001 — nunca impede o sistema de abrir
            self.contexto.sessao.rollback()
        self.verificar_notificacoes(ao_abrir=True)
        self.verificar_email()
        self.verificacao.start()

    def verificar_notificacoes(self, ao_abrir: bool = False) -> list:
        """Cria os avisos novos do dia (o de hoje, não a data de referência).

        Antes, se estiver ligada, a geração automática da competência. Ao abrir, só
        o contador muda: o aviso do canto aparece para o que surge com o sistema
        aberto (e para a competência gerada automaticamente).
        """
        from ..servicos import geracao_automatica, notificacoes

        try:
            geracao = geracao_automatica.executar(self.contexto.sessao, hoje())
            novas = ([geracao] if geracao else []) + notificacoes.gerar(
                self.contexto.sessao, hoje()
            )
            self.contexto.salvar()
        except Exception:  # noqa: BLE001 — verificação nunca derruba a janela
            from ..config.registro import log

            self.contexto.sessao.rollback()
            log(__name__).exception("Falha ao verificar as notificações")
            return []
        self._atualizar_botao_notificacoes()
        if geracao:   # honorários novos: a tela aberta e os contadores mudam
            self._recarregar_atual()
        # ao abrir, só a geração automática pede o aviso; o resto fica no contador
        avisar = [geracao] if ao_abrir and geracao else ([] if ao_abrir else novas)
        if avisar:
            texto = notificacoes.resumo(avisar)
            self.aviso_novo.mostrar(texto)
            self._posicionar_aviso()
            self._notificar_sistema(texto)
        return novas

    def verificar_email(self) -> None:
        """Busca e-mails novos do financeiro, se houver conta configurada."""
        from ..servicos import caixa_email

        if self.painel_email is None:
            return
        try:
            configurada = caixa_email.conta(self.contexto.sessao).configurada
        except Exception:  # noqa: BLE001
            return
        if configurada:
            self.painel_email.verificar(silencioso=True)

    def _chegaram_emails(self, quantidade: int) -> None:
        texto = (f"{quantidade} e-mail do financeiro" if quantidade == 1
                 else f"{quantidade} e-mails do financeiro")
        self._atualizar_botao_notificacoes()
        self._atualizar_contadores()
        self.aviso_novo.mostrar(texto)
        self._posicionar_aviso()
        self._notificar_sistema(texto)

    def _atualizar_botao_notificacoes(self) -> None:
        from ..servicos import notificacoes

        self.botao_notificacoes.definir(notificacoes.nao_lidas(self.contexto.sessao))

    def _notificar_sistema(self, texto: str) -> None:
        """A notificação do próprio sistema operacional, quando ele tem bandeja."""
        from PySide6.QtWidgets import QSystemTrayIcon

        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        if self.bandeja is None:
            self.bandeja = QSystemTrayIcon(icone_da_marca(), self)
            self.bandeja.setToolTip("Financeiro Métodos")
            self.bandeja.messageClicked.connect(self._trazer_e_abrir)
            self.bandeja.show()
        self.bandeja.showMessage("Financeiro Métodos", texto, icone_da_marca(), 10000)

    def _trazer_e_abrir(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.abrir_notificacoes()

    def abrir_notificacoes(self) -> None:
        from ..servicos import notificacoes

        self.aviso_novo.hide()
        self.lista_notificacoes.definir(notificacoes.listar(self.contexto.sessao))
        self.lista_notificacoes.mostrar_perto_de(self.botao_notificacoes)

    def _abrir_notificacao(self, notificacao) -> None:
        """Marca como lida e leva à tela, já buscando o cliente."""
        from ..servicos import notificacoes

        notificacoes.marcar_lida(self.contexto.sessao, notificacao)
        self.contexto.salvar()
        self._atualizar_botao_notificacoes()
        self.lista_notificacoes.hide()
        cliente = notificacao.cliente
        # "A vencer"/"Atrasados"/"Pagos" são abas de Vencimentos
        aba = notificacao.tela if notificacao.tela in ABAS_DE_VENCIMENTOS else None
        tela = NOMES_ANTIGOS.get(notificacao.tela, notificacao.tela)
        item = self.itens_de_tela.get(PainelVencimentos.titulo if aba else tela)
        if item is None:
            return
        painel = self.tela(self.linhas_de_tela[self.navegacao.row(item)])
        if aba:
            painel = painel.aba(aba)
        busca = getattr(painel, "busca", None)
        if busca is not None and cliente is not None:
            busca.blockSignals(True)
            busca.setText(cliente.nome)
            busca.blockSignals(False)
        if self.navegacao.currentItem() is item:
            self._recarregar_atual(forcar=True)
        else:
            self.navegacao.setCurrentItem(item)

    def _marcar_todas_lidas(self) -> None:
        from ..servicos import notificacoes

        notificacoes.marcar_todas_lidas(self.contexto.sessao)
        self.contexto.salvar()
        self._atualizar_botao_notificacoes()
        self.lista_notificacoes.definir(notificacoes.listar(self.contexto.sessao))

    def resizeEvent(self, evento) -> None:  # noqa: N802
        super().resizeEvent(evento)
        self._posicionar_aviso()

    def closeEvent(self, evento) -> None:  # noqa: N802
        """Backup automático ao fechar, se estiver ligado nas configurações."""
        sessao = self.contexto.sessao
        try:
            if servico_configuracoes.obter_bool(sessao, "backup_ao_fechar", True) and \
                    not getattr(self, "sem_backup_ao_fechar", False):
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


INTERVALO_VERIFICACAO_MS = 30 * 60 * 1000   # meia hora
ABAS_DE_VENCIMENTOS = ("A vencer", "Atrasados", "Pagos")
# notificações guardadas antes de a tela mudar de nome
NOMES_ANTIGOS = {"E-mail": "Gerenciador de e-mail", "E-mail de cobranças": "Gerenciador de e-mail"}


class TelaAdiada(QWidget):
    """Lugar de uma tela que ainda não foi aberta (montada na primeira vez)."""

    def __init__(self, classe) -> None:
        super().__init__()
        self.classe = classe
        self.titulo = classe.titulo


# cor de cada grupo do menu (Cobrança, Cadastros, Gestão): as cores da logo,
# em tons que dão leitura sobre o fundo claro e sobre o escuro
CORES_DOS_GRUPOS = {
    "claro": ("#1E8A9A", "#C27A1A", "#203461"),
    "escuro": ("#6FD3E0", "#F9B259", "#A9B8E6"),
}


def cor_do_grupo(numero: int) -> QColor:
    tons = CORES_DOS_GRUPOS.get(cores.tema_atual(), CORES_DOS_GRUPOS["claro"])
    return QColor(tons[numero % len(tons)])


class ContadorDoMenu(QStyledItemDelegate):
    """O menu lateral: o nome de cada grupo na cor dele, um fio da mesma cor ao
    lado das telas do grupo, a linha entre grupos e a quantidade num selo laranja."""

    PAPEL = Qt.ItemDataRole.UserRole + 1
    PAPEL_GRUPO = Qt.ItemDataRole.UserRole + 2       # tela: a que grupo pertence
    PAPEL_CABECALHO = Qt.ItemDataRole.UserRole + 3   # nome do grupo
    PAPEL_SEPARADOR = Qt.ItemDataRole.UserRole + 4

    def paint(self, pintor: QPainter, opcao, indice) -> None:
        caixa = QRectF(opcao.rect)
        if indice.data(self.PAPEL_SEPARADOR):
            pintor.save()
            pintor.setPen(tema.cor("borda", cores.tema_atual()))
            meio = caixa.center().y()
            pintor.drawLine(QPointF(caixa.left() + 8, meio), QPointF(caixa.right() - 8, meio))
            pintor.restore()
            return
        cabecalho = indice.data(self.PAPEL_CABECALHO)
        if cabecalho is not None:
            self._cabecalho(pintor, caixa, indice.data(Qt.ItemDataRole.DisplayRole),
                            cor_do_grupo(cabecalho))
            return
        super().paint(pintor, opcao, indice)
        grupo = indice.data(self.PAPEL_GRUPO)
        if grupo is not None:   # o fio do grupo, à esquerda das telas dele
            pintor.save()
            cor = cor_do_grupo(grupo)
            cor.setAlpha(150)
            pintor.fillRect(QRectF(caixa.left() + 1, caixa.top() + 2, 2, caixa.height() - 4),
                            cor)
            pintor.restore()
        quantidade = indice.data(self.PAPEL)
        if not quantidade:
            return
        texto = str(quantidade) if quantidade < 1000 else "999+"
        fonte = QFont(opcao.font)
        fonte.setPixelSize(11)
        fonte.setBold(True)
        largura = max(22.0, QFontMetricsF(fonte).horizontalAdvance(texto) + 12)
        altura = 18.0
        caixa = QRectF(
            opcao.rect.right() - largura - 10,
            opcao.rect.center().y() - altura / 2 + 0.5,
            largura,
            altura,
        )
        nome = cores.tema_atual()
        pintor.save()
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(tema.cor("marca", nome))
        pintor.drawRoundedRect(caixa, altura / 2, altura / 2)
        pintor.setFont(fonte)
        pintor.setPen(tema.cor("texto_sobre_marca", nome))
        pintor.drawText(caixa, Qt.AlignmentFlag.AlignCenter, texto)
        pintor.restore()

    @staticmethod
    def _cabecalho(pintor: QPainter, caixa: QRectF, titulo: str, cor: QColor) -> None:
        pintor.save()
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        faixa = QRectF(caixa.left() + 1, caixa.top() + 4, caixa.width() - 2, caixa.height() - 8)
        fundo = QColor(cor)
        fundo.setAlpha(28)
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(fundo)
        pintor.drawRoundedRect(faixa, 6, 6)
        pintor.setBrush(cor)
        pintor.drawRoundedRect(QRectF(faixa.left(), faixa.top(), 4, faixa.height()), 2, 2)
        fonte = QFont(pintor.font())
        fonte.setPixelSize(11)
        fonte.setBold(True)
        fonte.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        pintor.setFont(fonte)
        pintor.setPen(cor)
        pintor.drawText(faixa.adjusted(14, 0, -6, 0),
                        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, titulo)
        pintor.restore()
