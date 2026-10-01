"""Escolha de cliente por busca, no lugar de uma lista suspensa gigante.

O campo mostra o cliente escolhido; digitar nele e apertar Enter (ou clicar em
Procurar) abre a busca já filtrada. Com um único resultado — ou o código exato —
a escolha é direta, sem abrir janela.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...dominio.enums import TipoPessoa
from ...dominio.valores import formatar_documento
from ...infra.modelos import Cliente
from ...servicos import clientes as servico
from .tabelas import Coluna, ModeloTabela, ajustar_colunas, item_atual, preparar_tabela


class DialogoProcurarCliente(QDialog):
    """Busca enquanto digita: nome sem acento, código ou CPF/CNPJ."""

    def __init__(
        self,
        sessao,
        termo: str = "",
        tipo_pessoa: TipoPessoa | None = None,
        excluir_id: int | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.sessao = sessao
        self.tipo_pessoa = tipo_pessoa
        self.excluir_id = excluir_id
        self.escolhido: Cliente | None = None
        titulo = "Procurar empresa" if tipo_pessoa is TipoPessoa.PJ else "Procurar cliente"
        self.setWindowTitle(titulo)
        self.resize(860, 540)
        self._montar(termo)
        self._filtrar()

    def _montar(self, termo: str) -> None:
        layout = QVBoxLayout(self)
        self.busca = QLineEdit(termo)
        self.busca.setPlaceholderText("Digite nome, código ou CPF/CNPJ…")
        self.busca.setClearButtonEnabled(True)
        self.busca.setMinimumHeight(34)
        self.busca.textChanged.connect(lambda *_: self._filtrar())
        self.busca.returnPressed.connect(self._escolher)
        self.busca.installEventFilter(self)
        layout.addWidget(self.busca)

        self.modelo = ModeloTabela(
            [
                Coluna("Código", lambda c: c.codigo, alinhamento=Qt.AlignmentFlag.AlignCenter),
                Coluna("Nome / razão social", lambda c: c.nome),
                Coluna("CPF/CNPJ", lambda c: formatar_documento(c.documento) or "—"),
                Coluna("Tipo", lambda c: c.tipo_pessoa.value,
                       alinhamento=Qt.AlignmentFlag.AlignCenter),
                Coluna(
                    "Situação",
                    lambda c: "Cobrança suspensa" if c.suspensao_ativa() else c.situacao.rotulo,
                ),
            ]
        )
        self.tabela = preparar_tabela(QTableView(), esticar=1)
        self.tabela.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.tabela.setModel(self.modelo)
        self.tabela.doubleClicked.connect(lambda *_: self._escolher())
        layout.addWidget(self.tabela, 1)
        QShortcut(QKeySequence(Qt.Key.Key_Return), self.tabela, activated=self._escolher)

        rodape = QHBoxLayout()
        self.contagem = QLabel("")
        self.contagem.setObjectName("subtitulo")
        rodape.addWidget(self.contagem, 1)
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        escolher = QPushButton("Selecionar")
        escolher.setObjectName("primario")
        escolher.clicked.connect(self._escolher)
        rodape.addWidget(cancelar)
        rodape.addWidget(escolher)
        layout.addLayout(rodape)

    def eventFilter(self, objeto, evento):  # noqa: N802
        # seta para baixo sai da busca e entra na lista, como num buscador
        if objeto is self.busca and evento.type() == evento.Type.KeyPress:
            if evento.key() == Qt.Key.Key_Down and self.modelo.rowCount():
                self.tabela.setFocus()
                self.tabela.selectRow(0)
                return True
        return super().eventFilter(objeto, evento)

    def _filtrar(self) -> None:
        encontrados = servico.buscar(
            self.sessao, self.busca.text(), self.tipo_pessoa, self.excluir_id
        )
        self.modelo.definir_itens(encontrados)
        ajustar_colunas(self.tabela, self.modelo.colunas)
        if encontrados:
            self.tabela.selectRow(0)
        quantidade = len(encontrados)
        self.contagem.setText(
            "Nenhum cliente encontrado" if not quantidade
            else f"{quantidade} encontrado(s) · Enter seleciona · ↓ vai para a lista"
        )

    def _escolher(self) -> None:
        cliente = item_atual(self.tabela)
        if cliente is None and self.modelo.rowCount():
            cliente = self.modelo.item(0)
        if cliente is None:
            return
        self.escolhido = cliente
        self.accept()


class CampoCliente(QWidget):
    """Campo que mostra o cliente escolhido e abre a busca para trocar."""

    mudou = Signal(object)

    def __init__(
        self,
        sessao,
        tipo_pessoa: TipoPessoa | None = None,
        excluir_id: int | None = None,
        vazio: str = "Digite para procurar…",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.sessao = sessao
        self.tipo_pessoa = tipo_pessoa
        self.excluir_id = excluir_id
        self._cliente: Cliente | None = None

        linha = QHBoxLayout(self)
        linha.setContentsMargins(0, 0, 0, 0)
        linha.setSpacing(6)
        self.texto = QLineEdit()
        self.texto.setPlaceholderText(vazio)
        self.texto.setClearButtonEnabled(True)
        self.texto.returnPressed.connect(self.procurar)
        self.texto.textEdited.connect(self._editou)
        linha.addWidget(self.texto, 1)
        self.botao = QPushButton("Procurar…")
        self.botao.clicked.connect(self.procurar)
        linha.addWidget(self.botao)

    # ------------------------------------------------------------------ API
    def valor(self) -> int | None:
        return self._cliente.id if self._cliente else None

    @property
    def cliente(self) -> Cliente | None:
        return self._cliente

    def definir(self, cliente_id: int | None) -> None:
        cliente = self.sessao.get(Cliente, cliente_id) if cliente_id else None
        self._aplicar(cliente, avisar=False)

    def setEnabled(self, habilitado: bool) -> None:  # noqa: N802
        self.texto.setEnabled(habilitado)
        self.botao.setEnabled(habilitado)
        super().setEnabled(habilitado)

    # ------------------------------------------------------------- interno
    def _aplicar(self, cliente: Cliente | None, avisar: bool = True) -> None:
        self._cliente = cliente
        self.texto.setText(f"{cliente.codigo} – {cliente.nome}" if cliente else "")
        self.texto.setCursorPosition(0)
        if avisar:
            self.mudou.emit(cliente)

    def _editou(self, texto: str) -> None:
        # começou a digitar por cima: a escolha anterior deixa de valer
        if self._cliente is not None:
            self._cliente = None
            self.mudou.emit(None)
        if not texto:
            self.mudou.emit(None)

    def procurar(self) -> None:
        termo = "" if self._cliente else self.texto.text()
        # resultado único (ou código exato) dispensa a janela
        if termo.strip():
            encontrados = servico.buscar(
                self.sessao, termo, self.tipo_pessoa, self.excluir_id, limite=2
            )
            if len(encontrados) == 1 or (
                encontrados and encontrados[0].codigo == termo.strip()
            ):
                self._aplicar(encontrados[0])
                return
        dialogo = DialogoProcurarCliente(
            self.sessao, termo, self.tipo_pessoa, self.excluir_id, self
        )
        if dialogo.exec() and dialogo.escolhido is not None:
            self._aplicar(dialogo.escolhido)
