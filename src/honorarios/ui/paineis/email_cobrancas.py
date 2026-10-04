"""E-mail de cobranças: a caixa da conversa com o financeiro, dentro do sistema.

À esquerda, os e-mails da pasta (só os da conversa "Clientes c/Honorários
vencidos") e as respostas enviadas daqui. À direita, o e-mail aberto em três
abas, na ordem do trabalho:

- **Mensagem**: o e-mail como chegou;
- **Conferência**: quem continua na lista, quem saiu (provável pagamento,
  confirmado um a um) e o que não bate com o sistema;
- **Responder**: a resposta pronta — a lista dele com o andamento das cobranças
  —, editável, para enviar daqui (com confirmação), copiar ou salvar rascunho.

Sem conta configurada, dá para abrir o e-mail de um arquivo ou colar o texto.
A rede (verificar e enviar) roda em segundo plano.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from email.utils import getaddresses
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...dominio.valores import FUSO_LOCAL, formatar_data, formatar_data_hora, formatar_moeda
from ...servicos import caixa_email
from ...servicos import email_cobrancas as servico
from ..comum import segundo_plano, widgets
from ..contexto import Contexto
from ..dialogos.pagamento import DialogoPagamento

PAPEL_MENSAGEM = Qt.ItemDataRole.UserRole + 1
FUNDO_EMAIL = "QTextBrowser, QTextEdit { background: #ffffff; color: #1c2430; border: none; }"


def _nome(endereco: str) -> str:
    pares = getaddresses([endereco or ""])
    if not pares:
        return endereco
    nome, email = pares[0]
    return nome or email or endereco


def _quando(mensagem) -> str:
    momento = mensagem.recebido_em
    if momento.tzinfo is not None:
        momento = momento.astimezone(FUSO_LOCAL)
    return momento.strftime("%d/%m %H:%M")


# ------------------------------------------------------------------ lista
class ItemEmail(QFrame):
    """Uma linha da lista: quem, quando, o assunto e a situação."""

    def __init__(self, mensagem, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("itemEmail")
        self.setProperty("naoLido", not mensagem.lida)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)
        topo = QHBoxLayout()
        quem = "Você" if mensagem.enviada else _nome(mensagem.de)
        self.quem = QLabel(quem)
        self.quem.setObjectName("remetenteEmail")
        topo.addWidget(self.quem, 1)
        quando = QLabel(_quando(mensagem))
        quando.setObjectName("dataEmail")
        topo.addWidget(quando)
        layout.addLayout(topo)
        assunto = QLabel(mensagem.assunto or "(sem assunto)")
        assunto.setObjectName("assuntoItemEmail")
        layout.addWidget(assunto)
        etiquetas = QHBoxLayout()
        etiquetas.setSpacing(6)
        for texto, tipo in self._etiquetas(mensagem):
            etiqueta = QLabel(texto)
            etiqueta.setObjectName("etiquetaEmail")
            etiqueta.setProperty("tipo", tipo)
            etiquetas.addWidget(etiqueta)
        etiquetas.addStretch(1)
        layout.addLayout(etiquetas)

    @staticmethod
    def _etiquetas(mensagem) -> list[tuple[str, str]]:
        if mensagem.enviada:
            return [("Enviada daqui", "enviada")]
        saida = []
        if not mensagem.lida:
            saida.append(("Nova", "nova"))
        if mensagem.respondida_em:
            saida.append(("Respondida", "respondida"))
        if mensagem.conta == caixa_email.ARQUIVO:
            saida.append(("Arquivo", "arquivo"))
        return saida


# ------------------------------------------------------------ conferência
SAIU, CONTINUA, FORA, PAGO = "saiu", "continua", "fora", "pago"
PAPEL_HONORARIO = Qt.ItemDataRole.UserRole
PAPEL_GRUPO = Qt.ItemDataRole.UserRole + 1


class AbaConferencia(QWidget):
    COLUNAS = ("Cliente", "Competência", "Vencimento", "Valor", "Anotações")

    def __init__(self, painel: PainelEmailCobrancas, parent=None) -> None:
        super().__init__(parent)
        self.painel = painel
        self.contexto = painel.contexto
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)

        # o aviso de quem saiu, com a baixa a um clique
        self.faixa_saiu = QFrame()
        self.faixa_saiu.setObjectName("faixaSaiu")
        faixa = QHBoxLayout(self.faixa_saiu)
        faixa.setContentsMargins(14, 10, 10, 10)
        self.texto_saiu = QLabel()
        self.texto_saiu.setObjectName("textoSaiu")
        self.texto_saiu.setWordWrap(True)
        faixa.addWidget(self.texto_saiu, 1)
        self.botao_baixa = QPushButton("Dar baixa…")
        self.botao_baixa.setObjectName("cartaoPagamento")
        self.botao_baixa.clicked.connect(self.painel.abrir_baixa)
        faixa.addWidget(self.botao_baixa)
        layout.addWidget(self.faixa_saiu)

        self.resumo = widgets.rotulo_fraco("")
        layout.addWidget(self.resumo)
        self.arvore = QTreeWidget()
        self.arvore.setHeaderLabels(self.COLUNAS)
        self.arvore.setColumnWidth(0, 300)
        self.arvore.setAlternatingRowColors(True)
        self.arvore.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.arvore.itemDoubleClicked.connect(lambda item, _c: self._duplo_clique(item))
        self.arvore.itemSelectionChanged.connect(self._atualizar_botoes)
        layout.addWidget(self.arvore, 1)
        rodape = QHBoxLayout()
        self.dica = widgets.rotulo_fraco(
            "Selecione honorários de um cliente que continua na lista para anotar o que "
            "ele disse; o retorno entra na resposta ao financeiro."
        )
        self.dica.setWordWrap(True)
        rodape.addWidget(self.dica, 1)
        self.botao_retorno = QPushButton("Anotar retorno…")
        self.botao_retorno.setObjectName("primario")
        self.botao_retorno.clicked.connect(self.anotar_retorno)
        self.botao_pagar = QPushButton("Confirmar pagamento…")
        self.botao_pagar.setObjectName("cartaoPagamento")
        self.botao_pagar.clicked.connect(self._pagar_selecionado)
        rodape.addWidget(self.botao_retorno)
        rodape.addWidget(self.botao_pagar)
        layout.addLayout(rodape)
        self._atualizar_botoes()

    def _linha(self, pai, grupo: str, cliente: str, competencia: str, vencimento: str,
               valor: str, notas: str = "", honorario=None) -> QTreeWidgetItem:
        item = QTreeWidgetItem(pai, [cliente, competencia, vencimento, valor, notas])
        item.setTextAlignment(3, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if notas:
            item.setToolTip(4, notas)
        item.setData(0, PAPEL_HONORARIO, honorario)
        item.setData(0, PAPEL_GRUPO, grupo)
        return item

    def _grupo(self, titulo: str, quantidade: int) -> QTreeWidgetItem:
        grupo = QTreeWidgetItem(self.arvore, [f"{titulo} ({quantidade})"])
        fonte = grupo.font(0)
        fonte.setBold(True)
        grupo.setFont(0, fonte)
        grupo.setFirstColumnSpanned(True)
        grupo.setExpanded(True)
        grupo.setFlags(Qt.ItemFlag.ItemIsEnabled)
        return grupo

    def _do_sistema(self, pai, grupo: str, linha, notas: str = "") -> None:
        honorario = linha.honorario
        valor = honorario.saldo_aberto if grupo != PAGO else honorario.valor_original
        self._linha(pai, grupo, servico.nome_no_email(linha.cliente),
                    honorario.competencia_rotulo or honorario.tipo.nome,
                    formatar_data(honorario.vencimento), formatar_moeda(valor), notas,
                    honorario)

    def mostrar(self, conferencia: servico.Conferencia | None) -> None:
        self.arvore.clear()
        self.faixa_saiu.setVisible(bool(conferencia and conferencia.sairam))
        if conferencia is None:
            self.resumo.setText(
                "Não encontrei a lista de honorários neste e-mail. O sistema procura, para "
                "cada honorário, o cliente, a competência, o vencimento (dd/mm/aaaa) e o "
                "valor — numa linha ou cada coluna numa linha, como sai ao copiar do PDF. "
                "Confira o e-mail na aba Mensagem."
            )
            self.resumo.setWordWrap(True)
            self._atualizar_botoes()
            return
        if conferencia.sairam:
            clientes = len({linha.cliente.id for linha in conferencia.sairam})
            total = sum((linha.atualizacao.total for linha in conferencia.sairam),
                        start=Decimal(0))
            self.texto_saiu.setText(
                f"<b>{len(conferencia.sairam)} honorário(s) de {clientes} cliente(s) saíram "
                f"da lista</b> ({formatar_moeda(total)} com juros de hoje): provavelmente "
                "foram pagos. Confira no e-mail e dê baixa."
            )
            saiu = self._grupo("Saíram da lista — provável pagamento", len(conferencia.sairam))
            for linha in conferencia.sairam:
                self._do_sistema(saiu, SAIU, linha)
        continuam = self._grupo("Continuam em aberto", len(conferencia.continuam))
        anotados: set[int] = set()   # a anotação vai só na primeira linha do cliente
        notas = defaultdict(list)
        for casamento in conferencia.continuam:
            notas[casamento.linha.cliente.id].extend(casamento.lida.notas)
        for casamento in conferencia.continuam:
            cliente = casamento.linha.cliente
            texto = "" if cliente.id in anotados else "  ".join(notas[cliente.id])
            anotados.add(cliente.id)
            self._do_sistema(continuam, CONTINUA, casamento.linha, texto)
        if conferencia.pagos:
            pagos = self._grupo("No e-mail, mas já pagos no sistema (ficam fora da resposta)",
                                len(conferencia.pagos))
            for casamento in conferencia.pagos:
                self._do_sistema(pagos, PAGO, casamento.linha)
        if conferencia.nao_encontradas:
            fora = self._grupo("No e-mail, mas sem honorário igual no sistema",
                               len(conferencia.nao_encontradas))
            for lida in conferencia.nao_encontradas:
                self._linha(
                    fora, FORA,
                    f"{lida.codigo} – {lida.cliente}" if lida.codigo else lida.cliente,
                    lida.competencia, formatar_data(lida.vencimento),
                    formatar_moeda(lida.valor) if lida.valor is not None else "",
                    "  ".join(lida.notas),
                )
        incompletas = conferencia.leitura.incompletas
        if incompletas:
            grupo = self._grupo("No e-mail sem vencimento ou valor — confira no e-mail",
                                len(incompletas))
            for incompleta in incompletas:
                self._linha(grupo, FORA, incompleta.texto, "", "", "",
                            "  ".join(incompleta.notas))
        partes = [f"{len(conferencia.continuam)} continuam", f"{len(conferencia.sairam)} saíram"]
        if conferencia.pagos:
            partes.append(f"{len(conferencia.pagos)} já pagos")
        partes.append(f"{len(conferencia.nao_encontradas)} sem correspondência")
        self.resumo.setText(f"Lista de {formatar_data(conferencia.data)}: " + " · ".join(partes))
        self._atualizar_botoes()

    def _selecionados(self, grupo: str) -> list:
        return [item.data(0, PAPEL_HONORARIO) for item in self.arvore.selectedItems()
                if item.data(0, PAPEL_GRUPO) == grupo and item.data(0, PAPEL_HONORARIO)]

    def _atualizar_botoes(self) -> None:
        continuam = self._selecionados(CONTINUA)
        self.botao_retorno.setEnabled(
            bool(continuam) and len({h.cliente_id for h in continuam}) == 1
        )
        self.botao_pagar.setEnabled(len(self._selecionados(SAIU)) == 1
                                    and len(self.arvore.selectedItems()) == 1)

    def _duplo_clique(self, item: QTreeWidgetItem) -> None:
        grupo = item.data(0, PAPEL_GRUPO)
        if grupo == SAIU:
            self._pagar(item.data(0, PAPEL_HONORARIO))
        elif grupo == CONTINUA:
            self.arvore.clearSelection()
            item.setSelected(True)
            self.anotar_retorno()

    def _pagar_selecionado(self) -> None:
        [honorario] = self._selecionados(SAIU)
        self._pagar(honorario)

    def _pagar(self, honorario) -> None:
        if DialogoPagamento(self.contexto, honorario, self).exec():
            self.painel.reconferir()

    def anotar_retorno(self) -> None:
        from ..dialogos.retorno import DialogoRetorno

        honorarios = self._selecionados(CONTINUA)
        if not honorarios:
            return
        if len({h.cliente_id for h in honorarios}) > 1:
            widgets.aviso(self, "Selecione honorários de um cliente só.")
            return
        dialogo = DialogoRetorno(self.contexto, honorarios[0].cliente, honorarios, self)
        if dialogo.exec():
            self.painel.reconferir()
            self.painel.status_resposta(f"✓ {dialogo.feito} A resposta já inclui o retorno.")


# ------------------------------------------------------------- responder
class AbaResponder(QWidget):
    def __init__(self, painel: PainelEmailCobrancas, parent=None) -> None:
        super().__init__(parent)
        self.painel = painel
        self.email: servico.EmailCobrancas | None = None
        self.html_gerado = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        formulario = QFormLayout()
        formulario.setHorizontalSpacing(10)
        self.para = QLineEdit()
        self.cc = QLineEdit()
        self.assunto = QLineEdit()
        formulario.addRow("Para:", self.para)
        formulario.addRow("Cc:", self.cc)
        formulario.addRow("Assunto:", self.assunto)
        layout.addLayout(formulario)

        barra = QHBoxLayout()
        self.aviso = widgets.rotulo_fraco("")
        self.aviso.setWordWrap(True)
        barra.addWidget(self.aviso, 1)
        self.botao_refazer = QPushButton("Desfazer minhas edições")
        self.botao_refazer.setToolTip(
            "Volta a resposta para o texto que o sistema montou (lista do financeiro sem "
            "quem pagou + os retornos anotados), descartando o que você escreveu"
        )
        self.botao_refazer.clicked.connect(self.painel.montar_resposta)
        self.botao_copiar = QPushButton("Copiar")
        self.botao_copiar.setToolTip("Copia com a formatação, para colar no Outlook")
        self.botao_copiar.clicked.connect(self.copiar)
        self.botao_rascunho = QPushButton("Salvar rascunho…")
        self.botao_rascunho.clicked.connect(lambda: self.salvar_rascunho())
        self.botao_enviar = QPushButton("Enviar resposta")
        self.botao_enviar.setObjectName("primario")
        self.botao_enviar.clicked.connect(self.painel.enviar)
        for botao in (self.botao_refazer, self.botao_copiar, self.botao_rascunho,
                      self.botao_enviar):
            barra.addWidget(botao)
        layout.addLayout(barra)

        self.editor = QTextEdit()
        self.editor.setAcceptRichText(True)
        self.editor.setStyleSheet(FUNDO_EMAIL)
        layout.addWidget(self.editor, 1)
        layout.addWidget(widgets.rotulo_fraco(
            "Dá para escrever no texto antes de enviar. O e-mail do financeiro vai citado "
            "embaixo, como no Outlook."
        ))

    def preencher(self, email: servico.EmailCobrancas | None, pode_enviar: bool,
                  aviso: str = "") -> None:
        self.email = email
        self.html_gerado = servico.html(email) if email is not None else ""
        self.para.setText(email.para if email is not None else "")
        self.cc.setText(email.cc if email is not None else "")
        self.assunto.setText(email.assunto if email is not None else "")
        self.editor.setHtml(self.html_gerado)
        self.editor.document().setModified(False)
        for campo in (self.para, self.cc, self.assunto, self.editor, self.botao_copiar,
                      self.botao_rascunho, self.botao_refazer):
            campo.setEnabled(email is not None)
        self.botao_enviar.setEnabled(email is not None and pode_enviar)
        self.aviso.setText(aviso)

    def corpo_html(self) -> str:
        """O que foi gerado, ou o texto editado (com a formatação do editor)."""
        if not self.editor.document().isModified():
            return self.html_gerado
        return self.editor.toHtml()

    def resposta(self) -> caixa_email.Resposta:
        return caixa_email.Resposta(
            para=self.para.text().strip(), cc=self.cc.text().strip(),
            assunto=self.assunto.text().strip(), html=self.corpo_html(),
            texto=self.editor.toPlainText(),
        )

    def copiar(self) -> None:
        dados = QMimeData()
        dados.setHtml(self.corpo_html())
        dados.setText(self.editor.toPlainText())
        QGuiApplication.clipboard().setMimeData(dados)
        self.aviso.setText("Resposta copiada: em Responder a todos, cole no corpo (Ctrl+V).")

    def salvar_rascunho(self, destino: str | None = None) -> None:
        if self.email is None:
            return
        if destino is None:
            nome = f"resposta-cobrancas-{self.email.referencia:%Y-%m-%d}.eml"
            destino, _ = QFileDialog.getSaveFileName(
                self, "Salvar rascunho da resposta", nome, "E-mail (*.eml)"
            )
            if not destino:
                return
        self.email.para, self.email.cc = self.para.text(), self.cc.text()
        self.email.assunto = self.assunto.text()
        # o remetente pode ter sido configurado depois de abrir o e-mail
        self.email.remetente = servico.remetente(self.painel.contexto.sessao)

        def acao():
            Path(destino).write_bytes(servico.eml(self.email))

        deu_certo, _ = widgets.executar(self, acao)
        if deu_certo:
            self.aviso.setText(f"Rascunho salvo em {destino}")


# ------------------------------------------------------------------ tela
class PainelEmailCobrancas(QWidget):
    titulo = "E-mail"
    chegaram = Signal(int)   # e-mails novos baixados (para a janela avisar)
    recarregado = Signal()   # houve baixa: a janela atualiza os contadores

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.executor = segundo_plano.executar
        self.mensagem = None              # o e-mail aberto
        self.conferencia: servico.Conferencia | None = None
        self.verificando = False
        self.enviando = False
        self.janela_baixa = None

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        self.cabecalho = widgets.Cabecalho(
            "E-mail", "A conversa \"Clientes c/Honorários vencidos\" com o financeiro"
        )
        self.situacao = widgets.rotulo_fraco("")
        self.cabecalho.acoes.addWidget(self.situacao)
        self.botao_verificar = self.cabecalho.adicionar_botao(
            "Verificar caixa", lambda: self.verificar(), primario=True
        )
        self.menu_acoes = QToolButton()
        self.menu_acoes.setText("Ações")
        self.menu_acoes.setObjectName("menuAcoes")
        self.menu_acoes.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.menu_acoes)
        menu.addAction("Abrir e-mail salvo no computador (.eml, PDF)…",
                       lambda: self.abrir_arquivo())
        menu.addAction("Colar o texto de um e-mail…", self.colar_texto)
        menu.addAction("Gerar a lista dos vencidos sem o e-mail do financeiro",
                       self.montar_pelo_sistema)
        menu.addSeparator()
        menu.addAction("Conta de e-mail…", self.configurar_conta)
        self.menu_acoes.setMenu(menu)
        self.cabecalho.acoes.addWidget(self.menu_acoes)
        layout.addWidget(self.cabecalho)

        divisor = QSplitter(Qt.Orientation.Horizontal)
        esquerda = QWidget()
        esquerda_layout = QVBoxLayout(esquerda)
        esquerda_layout.setContentsMargins(0, 0, 0, 0)
        esquerda_layout.setSpacing(6)
        caixas = QHBoxLayout()
        caixas.setSpacing(6)
        self.botao_recebidos = QPushButton("Recebidos")
        self.botao_enviados = QPushButton("Enviados por você")
        self.grupo_caixas = QButtonGroup(self)
        for botao in (self.botao_recebidos, self.botao_enviados):
            botao.setObjectName("abaCaixa")
            botao.setCheckable(True)
            botao.setCursor(Qt.CursorShape.PointingHandCursor)
            self.grupo_caixas.addButton(botao)
            caixas.addWidget(botao, 1)
        self.botao_recebidos.setChecked(True)
        self.grupo_caixas.buttonClicked.connect(lambda *_: self._trocar_caixa())
        esquerda_layout.addLayout(caixas)
        self.lista = QListWidget()
        self.lista.setObjectName("listaEmails")
        self.lista.setSpacing(2)
        self.lista.currentItemChanged.connect(lambda atual, _anterior: self._abrir_item(atual))
        esquerda_layout.addWidget(self.lista, 1)
        self.lista_vazia = QLabel(
            "Nenhum e-mail ainda.\n\nClique em Verificar caixa, ou abra um e-mail de arquivo "
            "pelo menu Ações."
        )
        self.lista_vazia.setObjectName("vazioEmail")
        self.lista_vazia.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lista_vazia.setWordWrap(True)
        esquerda_layout.addWidget(self.lista_vazia, 1)
        divisor.addWidget(esquerda)

        self.direita = QStackedWidget()
        self.direita.addWidget(self._estado_vazio())
        self.direita.addWidget(self._leitor())
        divisor.addWidget(self.direita)
        divisor.setStretchFactor(0, 0)
        divisor.setStretchFactor(1, 1)
        divisor.setSizes([330, 820])
        layout.addWidget(divisor, 1)

    # ------------------------------------------------------------ montagem
    def _estado_vazio(self) -> QWidget:
        pagina = QWidget()
        layout = QVBoxLayout(pagina)
        layout.addStretch(1)
        self.vazio_titulo = QLabel("Escolha um e-mail na lista")
        self.vazio_titulo.setObjectName("vazioTitulo")
        self.vazio_titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.vazio_titulo)
        self.vazio_texto = widgets.rotulo_fraco("")
        self.vazio_texto.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vazio_texto.setWordWrap(True)
        layout.addWidget(self.vazio_texto)
        self.vazio_configurar = QPushButton("Configurar a conta de e-mail…")
        self.vazio_configurar.clicked.connect(self.configurar_conta)
        linha = QHBoxLayout()
        linha.addStretch(1)
        linha.addWidget(self.vazio_configurar)
        linha.addStretch(1)
        layout.addLayout(linha)
        layout.addStretch(2)
        return pagina

    def _leitor(self) -> QWidget:
        pagina = QWidget()
        layout = QVBoxLayout(pagina)
        layout.setContentsMargins(0, 0, 0, 0)
        cartao = QFrame()
        cartao.setObjectName("cabecalhoEmail")
        cartao_layout = QVBoxLayout(cartao)
        cartao_layout.setContentsMargins(16, 12, 16, 12)
        cartao_layout.setSpacing(4)
        topo = QHBoxLayout()
        self.assunto = QLabel()
        self.assunto.setObjectName("assuntoEmail")
        self.assunto.setWordWrap(True)
        topo.addWidget(self.assunto, 1)
        self.botao_responder = QPushButton("Responder")
        self.botao_responder.setObjectName("primario")
        self.botao_responder.clicked.connect(lambda: self.abas.setCurrentWidget(self.responder))
        topo.addWidget(self.botao_responder, 0, Qt.AlignmentFlag.AlignTop)
        cartao_layout.addLayout(topo)
        self.de = QLabel()
        self.de.setObjectName("deEmail")
        self.de.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cartao_layout.addWidget(self.de)
        self.destinatarios = widgets.rotulo_fraco("")
        self.destinatarios.setWordWrap(True)
        self.destinatarios.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cartao_layout.addWidget(self.destinatarios)
        layout.addWidget(cartao)

        self.abas = QTabWidget()
        self.corpo = QTextBrowser()
        self.corpo.setOpenExternalLinks(True)
        self.corpo.setStyleSheet(FUNDO_EMAIL)
        self.conferencia_aba = AbaConferencia(self)
        self.responder = AbaResponder(self)
        self.abas.addTab(self.corpo, "Mensagem")
        self.abas.addTab(self.conferencia_aba, "Conferir com o sistema")
        self.abas.addTab(self.responder, "Sua resposta")
        layout.addWidget(self.abas, 1)
        return pagina

    # --------------------------------------------------------------- dados
    def recarregar(self) -> None:
        self.contexto.atualizar()
        conta = caixa_email.conta(self.contexto.sessao)
        verificada = caixa_email.ultima_verificacao(self.contexto.sessao)
        if conta.configurada:
            quando = f" · verificada {formatar_data_hora(verificada)}" if verificada else ""
            self.situacao.setText(f"{caixa_email.PROVEDORES[conta.provedor]} · pasta "
                                  f"{conta.pasta}{quando}")
        else:
            self.situacao.setText("Sem conta de e-mail")
        self.botao_verificar.setEnabled(conta.configurada and not self.verificando)
        self.vazio_configurar.setVisible(not conta.configurada)
        self.vazio_texto.setText(
            "" if conta.configurada else
            "Configure a conta (Outlook ou Gmail) para o sistema buscar os e-mails do "
            "financeiro sozinho. Sem conta, abra o e-mail de arquivo pelo menu Ações."
        )
        self._preencher_lista()

    def _preencher_lista(self) -> None:
        aberta = self.mensagem.id if self.mensagem is not None else None
        self.lista.blockSignals(True)
        self.lista.clear()
        selecionar = None
        todas = caixa_email.listar(self.contexto.sessao)
        enviadas = sum(1 for m in todas if m.enviada)
        novas = sum(1 for m in todas if not m.lida)
        self.botao_recebidos.setText(f"Recebidos · {novas} nova(s)" if novas
                                     else f"Recebidos ({len(todas) - enviadas})")
        self.botao_enviados.setText(f"Enviados por você ({enviadas})")
        mostrar_enviadas = self.botao_enviados.isChecked()
        for mensagem in todas:
            if mensagem.enviada != mostrar_enviadas:
                continue
            item = QListWidgetItem()
            item.setData(PAPEL_MENSAGEM, mensagem.id)
            widget = ItemEmail(mensagem)
            item.setSizeHint(widget.sizeHint())
            self.lista.addItem(item)
            self.lista.setItemWidget(item, widget)
            if mensagem.id == aberta:
                selecionar = item
        if selecionar is not None:
            self.lista.setCurrentItem(selecionar)
        self.lista.blockSignals(False)
        tem = self.lista.count() > 0
        self.lista.setVisible(tem)
        self.lista_vazia.setVisible(not tem)
        self.lista_vazia.setText(
            "Nenhuma resposta enviada pelo sistema ainda." if mostrar_enviadas else
            "Nenhum e-mail recebido ainda.\n\nClique em Verificar caixa, ou abra um e-mail "
            "salvo pelo menu Ações."
        )
        if self.mensagem is None and self.conferencia is None:
            self.direita.setCurrentIndex(0)

    def _trocar_caixa(self) -> None:
        self._preencher_lista()
        if self.lista.currentItem() is None:   # o aberto é da outra caixa
            self.mensagem = None
            self.direita.setCurrentIndex(0)

    def mostrar_caixa(self, enviados: bool) -> None:
        (self.botao_enviados if enviados else self.botao_recebidos).setChecked(True)
        self._trocar_caixa()

    def _abrir_item(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        from ...infra.modelos import EmailMensagem

        mensagem = self.contexto.sessao.get(EmailMensagem, item.data(PAPEL_MENSAGEM))
        if mensagem is not None:
            self.abrir_mensagem(mensagem)

    def abrir_mensagem(self, mensagem) -> None:
        self.mensagem = mensagem
        primeira_vez = not mensagem.lida
        if primeira_vez:
            caixa_email.marcar_lido(self.contexto.sessao, mensagem)
            self.contexto.salvar()
            self._preencher_lista()   # tira o "Nova"
        self.assunto.setText(mensagem.assunto or "(sem assunto)")
        quem = "Você" if mensagem.enviada else mensagem.de
        self.de.setText(f"<b>{quem}</b> · {formatar_data_hora(mensagem.recebido_em)}")
        partes = [f"Para: {mensagem.para}"] if mensagem.para else []
        if mensagem.cc:
            partes.append(f"Cc: {mensagem.cc}")
        self.destinatarios.setText("   ".join(partes))
        if mensagem.corpo_html:
            self.corpo.setHtml(mensagem.corpo_html)
        else:
            self.corpo.setPlainText(mensagem.corpo_texto)
        self.direita.setCurrentIndex(1)
        self.reconferir()
        tem_lista = self.conferencia is not None
        # a conferência abre mesmo sem lista: lá diz o que faltou para reconhecer
        self.abas.setTabEnabled(1, not mensagem.enviada)
        self.abas.setTabEnabled(2, not mensagem.enviada and tem_lista)
        self.abas.setTabToolTip(2, "" if tem_lista else
                                "Sem a lista de honorários reconhecida não há o que responder")
        self.botao_responder.setVisible(not mensagem.enviada and tem_lista)
        if not self.abas.isTabEnabled(self.abas.currentIndex()):
            self.abas.setCurrentIndex(0)
        # e-mail novo com gente que saiu da lista: a baixa já abre, ao lado, para
        # conferir no próprio e-mail enquanto marca
        if primeira_vez and self.conferencia is not None and self.conferencia.sairam:
            self.abas.setCurrentWidget(self.conferencia_aba)
            self.abrir_baixa()

    def abrir_baixa(self) -> None:
        from ..dialogos.baixa_lista import DialogoBaixaLista

        if self.conferencia is None or not self.conferencia.sairam:
            return
        if self.janela_baixa is not None:
            self.janela_baixa.close()
        self.janela_baixa = DialogoBaixaLista(self.contexto, self.conferencia, self)
        self.janela_baixa.baixou.connect(self._baixou)
        self.janela_baixa.show()

    def _baixou(self, quantos: int) -> None:
        self.janela_baixa = None
        self.reconferir()
        self.recarregado.emit()
        self.status_resposta(f"✓ Baixa de {quantos} honorário(s). A resposta foi refeita "
                             "sem eles.")

    def status_resposta(self, texto: str) -> None:
        self.responder.aviso.setText(texto)
        self.conferencia_aba.resumo.setText(f"{texto}  ·  {self.conferencia_aba.resumo.text()}")

    def reconferir(self) -> None:
        """Confere a lista do e-mail aberto e refaz a resposta (depois de uma baixa)."""
        self.contexto.atualizar()
        self.conferencia = None
        if self.mensagem is not None and not self.mensagem.enviada:
            recebido = caixa_email.recebido_de(self.mensagem)
            leitura = servico.ler(recebido.texto)
            if leitura.linhas or leitura.incompletas:
                self.conferencia = servico.conferir(
                    self.contexto.sessao, leitura, self.contexto.data_referencia
                )
        self.conferencia_aba.mostrar(self.conferencia)
        saiu = len(self.conferencia.sairam) if self.conferencia is not None else 0
        self.abas.setTabText(1, f"Conferir com o sistema · {saiu} saíram" if saiu
                             else "Conferir com o sistema")
        self.montar_resposta()

    def montar_resposta(self) -> None:
        if self.mensagem is None or self.conferencia is None:
            self.responder.preencher(None, False)
            return
        email = servico.responder(
            self.contexto.sessao, self.conferencia, self.contexto.data_referencia,
            caixa_email.recebido_de(self.mensagem),
        )
        pode = self.mensagem.conta in (caixa_email.GMAIL, caixa_email.IMAP,
                                       caixa_email.MICROSOFT)
        aviso = "" if pode else ("Este e-mail veio de arquivo: copie a resposta ou salve o "
                                 "rascunho para enviar pelo Outlook.")
        if self.mensagem.respondida_em:
            aviso = (f"Já respondido em {formatar_data_hora(self.mensagem.respondida_em)}. "
                     + aviso).strip()
        self.responder.preencher(email, pode, aviso)

    # -------------------------------------------------------------- ações
    def verificar(self, silencioso: bool = False) -> None:
        """Busca os e-mails novos da pasta (em segundo plano)."""
        if self.verificando:
            return
        sessao = self.contexto.sessao
        try:
            caixa = caixa_email.abrir_caixa(sessao)
        except Exception as falha:  # noqa: BLE001
            if not silencioso:
                widgets.aviso(self, str(falha))
            return
        conta = caixa_email.conta(sessao)
        ja_tenho = caixa_email.ja_baixados(sessao, conta.provedor)
        assunto = servico.remetente(sessao).assunto
        self.verificando = True
        self.botao_verificar.setEnabled(False)
        self.botao_verificar.setText("Verificando…")

        def fim(resultado: caixa_email.ResultadoVerificacao):
            self._fim_da_verificacao()
            novas = caixa_email.guardar(self.contexto.sessao, resultado.conta,
                                        resultado.mensagens)
            caixa_email.registrar_verificacao(self.contexto.sessao)
            self.contexto.salvar()
            self.recarregar()
            if novas:
                self.chegaram.emit(len(novas))
            if not silencioso:
                self.situacao.setText(
                    f"{len(novas)} e-mail(s) novo(s)" if novas else "Nenhum e-mail novo"
                )

        def falhou(falha: Exception):
            self._fim_da_verificacao()
            self.situacao.setText("Não consegui verificar a caixa")
            if not silencioso:
                widgets.erro(self, str(falha))

        self.executor(lambda: caixa_email.verificar(caixa, conta.provedor, ja_tenho, assunto),
                      fim, falhou)

    def _fim_da_verificacao(self) -> None:
        self.verificando = False
        self.botao_verificar.setText("Verificar caixa")
        self.botao_verificar.setEnabled(True)

    def enviar(self) -> None:
        if self.mensagem is None or self.enviando:
            return
        resposta = self.responder.resposta()
        copia = f"\nCópia: {resposta.cc}" if resposta.cc else ""
        if not widgets.confirmar(
            self, f"Enviar a resposta para {resposta.para or '(ninguém)'}?{copia}",
            "Enviar resposta",
            "O e-mail do financeiro vai citado embaixo. Depois de enviado não dá para desfazer.",
        ):
            return
        try:
            caixa = caixa_email.abrir_caixa(self.contexto.sessao)
        except Exception as falha:  # noqa: BLE001
            widgets.aviso(self, str(falha))
            return
        original = self.mensagem
        self.enviando = True
        self.responder.botao_enviar.setEnabled(False)
        self.responder.botao_enviar.setText("Enviando…")

        def fim(enviada: caixa_email.MensagemBaixada):
            self._fim_do_envio()
            caixa_email.registrar_enviada(self.contexto.sessao, original, enviada)
            self.contexto.salvar()
            self.recarregar()
            self.montar_resposta()
            self.responder.aviso.setText("✓ Resposta enviada.")

        def falhou(falha: Exception):
            self._fim_do_envio()
            widgets.erro(self, str(falha))

        copia = caixa_email.original_de(original)   # a thread não toca no banco
        self.executor(lambda: caixa.responder(copia, resposta), fim, falhou)

    def _fim_do_envio(self) -> None:
        self.enviando = False
        self.responder.botao_enviar.setText("Enviar resposta")
        self.responder.botao_enviar.setEnabled(True)

    def abrir_arquivo(self, caminho: str | None = None) -> None:
        if caminho is None:
            caminho, _ = QFileDialog.getOpenFileName(
                self, "Abrir o e-mail do financeiro", "",
                "E-mail (*.eml *.pdf *.txt *.html *.htm);;Todos os arquivos (*)",
            )
            if not caminho:
                return
        deu_certo, recebido = widgets.executar(self, lambda: servico.abrir(Path(caminho)))
        if deu_certo:
            self._guardar_recebido(recebido)

    def colar_texto(self) -> None:
        dialogo = QDialog(self)
        dialogo.setWindowTitle("Colar o texto do e-mail")
        dialogo.resize(640, 460)
        layout = QVBoxLayout(dialogo)
        layout.addWidget(widgets.rotulo_fraco(
            "Cole o corpo do e-mail \"Clientes c/Honorários vencidos\" (Ctrl+V)."
        ))
        texto = QPlainTextEdit()
        layout.addWidget(texto, 1)
        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                  QDialogButtonBox.StandardButton.Cancel)
        botoes.accepted.connect(dialogo.accept)
        botoes.rejected.connect(dialogo.reject)
        layout.addWidget(botoes)
        if dialogo.exec() and texto.toPlainText().strip():
            self._guardar_recebido(servico.EmailRecebido(texto.toPlainText()))

    def _guardar_recebido(self, recebido: servico.EmailRecebido) -> None:
        if not servico.ler(recebido.texto).linhas:
            widgets.aviso(self, "Não encontrei linhas de honorário (cliente, competência, "
                                "vencimento e valor) nesse e-mail.")
            return
        mensagem = caixa_email.guardar_do_arquivo(self.contexto.sessao, recebido)
        self.contexto.salvar()
        self.mensagem = mensagem
        self.recarregar()
        self.abrir_mensagem(mensagem)
        self.abas.setCurrentWidget(self.conferencia_aba)

    def montar_pelo_sistema(self) -> None:
        """Sem o e-mail do financeiro: a lista dos vencidos, para copiar."""
        self.mensagem = None
        self.conferencia = None
        self.lista.clearSelection()
        self.assunto.setText("Lista montada pelo sistema")
        self.de.setText("<b>Vencidos até hoje</b>, com as anotações das cobranças")
        self.destinatarios.setText("")
        email = servico.montar(self.contexto.sessao, self.contexto.data_referencia)
        self.corpo.setHtml(servico.html(email))
        self.conferencia_aba.mostrar(None)
        self.direita.setCurrentIndex(1)
        self.responder.preencher(email, False, "Sem o e-mail do financeiro não dá para "
                                               "responder daqui: copie ou salve o rascunho.")
        self.abas.setTabEnabled(1, False)
        self.abas.setTabEnabled(2, True)
        self.botao_responder.setVisible(True)
        self.abas.setCurrentWidget(self.responder)

    def configurar_conta(self) -> None:
        from ..dialogos.conta_email import DialogoContaEmail

        if DialogoContaEmail(self.contexto, self, executor=self.executor).exec():
            self.recarregar()
