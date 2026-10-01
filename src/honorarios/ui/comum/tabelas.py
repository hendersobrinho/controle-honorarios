"""Tabelas e árvores de dados.

Listas de centenas de linhas usam ``QAbstractTableModel`` + proxy de filtro
(nunca um widget por linha), que é o que mantém a janela responsiva.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from PySide6.QtCore import (
    QAbstractItemModel,
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QObject,
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QTableView, QTreeView

from ...dominio.valores import formatar_data, formatar_moeda, normalizar_busca

PAPEL_ORDENACAO = int(Qt.ItemDataRole.UserRole) + 1
PAPEL_BUSCA = int(Qt.ItemDataRole.UserRole) + 2
PAPEL_ITEM = int(Qt.ItemDataRole.UserRole) + 3


@dataclass
class Coluna:
    """Uma coluna declarada: como mostrar, como ordenar e como colorir."""

    titulo: str
    texto: Callable[[Any], str]
    ordem: Callable[[Any], Any] | None = None
    alinhamento: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    largura: int | None = None
    cor: Callable[[Any], QColor | None] | None = None
    negrito: bool = False
    dica: Callable[[Any], str] | None = None

    def valor_ordem(self, item: Any) -> Any:
        return self.ordem(item) if self.ordem else self.texto(item)


def coluna_moeda(titulo: str, obter: Callable[[Any], Decimal], **kwargs) -> Coluna:
    return Coluna(
        titulo=titulo,
        texto=lambda item: formatar_moeda(obter(item)),
        ordem=lambda item: obter(item) or Decimal(0),
        alinhamento=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        **kwargs,
    )


def coluna_data(titulo: str, obter: Callable[[Any], date | None], **kwargs) -> Coluna:
    return Coluna(
        titulo=titulo,
        texto=lambda item: formatar_data(obter(item)),
        ordem=lambda item: obter(item) or date.min,
        alinhamento=Qt.AlignmentFlag.AlignCenter,
        **kwargs,
    )


def coluna_inteiro(titulo: str, obter: Callable[[Any], int], **kwargs) -> Coluna:
    return Coluna(
        titulo=titulo,
        texto=lambda item: str(obter(item) or 0),
        ordem=lambda item: obter(item) or 0,
        alinhamento=Qt.AlignmentFlag.AlignCenter,
        **kwargs,
    )


class ModeloTabela(QAbstractTableModel):
    def __init__(self, colunas: Sequence[Coluna], itens: Sequence[Any] = (), parent=None) -> None:
        super().__init__(parent)
        self.colunas = list(colunas)
        self._itens = list(itens)

    # ---- dados
    def definir_itens(self, itens: Sequence[Any]) -> None:
        self.beginResetModel()
        self._itens = list(itens)
        self.endResetModel()

    @property
    def itens(self) -> list[Any]:
        return self._itens

    def item(self, linha: int) -> Any | None:
        if 0 <= linha < len(self._itens):
            return self._itens[linha]
        return None

    # ---- QAbstractTableModel
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self._itens)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self.colunas)

    def headerData(self, secao, orientacao, papel=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientacao is Qt.Orientation.Horizontal and papel == Qt.ItemDataRole.DisplayRole:
            return self.colunas[secao].titulo
        return None

    def data(self, indice: QModelIndex, papel=Qt.ItemDataRole.DisplayRole):
        if not indice.isValid():
            return None
        item = self._itens[indice.row()]
        coluna = self.colunas[indice.column()]
        if papel == Qt.ItemDataRole.DisplayRole:
            return coluna.texto(item)
        if papel == Qt.ItemDataRole.TextAlignmentRole:
            return int(coluna.alinhamento)
        if papel == PAPEL_ORDENACAO:
            return coluna.valor_ordem(item)
        if papel == PAPEL_ITEM:
            return item
        if papel == PAPEL_BUSCA:
            return normalizar_busca(
                " ".join(c.texto(item) for c in self.colunas)
            )
        if papel == Qt.ItemDataRole.ForegroundRole and coluna.cor:
            cor = coluna.cor(item)
            return QBrush(cor) if cor else None
        if papel == Qt.ItemDataRole.FontRole and coluna.negrito:
            fonte = QFont()
            fonte.setBold(True)
            return fonte
        if papel == Qt.ItemDataRole.ToolTipRole and coluna.dica:
            return coluna.dica(item)
        return None


class ModeloTabelaMarcavel(ModeloTabela):
    """Tabela com caixa de seleção na primeira coluna (usada em prévias e cobrança)."""

    def __init__(self, colunas, itens=(), marcados_por_padrao: bool = True, parent=None) -> None:
        super().__init__(colunas, itens, parent)
        self._marcados: set[int] = set()
        self._padrao = marcados_por_padrao
        self._bloqueado: Callable[[Any], bool] | None = None
        self.definir_itens(itens)

    def definir_bloqueio(self, funcao: Callable[[Any], bool] | None) -> None:
        self._bloqueado = funcao

    def definir_itens(self, itens) -> None:
        super().definir_itens(itens)
        if self._padrao:
            self._marcados = {
                indice
                for indice, item in enumerate(self.itens)
                if not (self._bloqueado and self._bloqueado(item))
            }
        else:
            self._marcados = set()

    def flags(self, indice: QModelIndex):
        base = super().flags(indice)
        if indice.column() == 0:
            item = self.item(indice.row())
            if self._bloqueado and self._bloqueado(item):
                return base
            return base | Qt.ItemFlag.ItemIsUserCheckable
        return base

    def data(self, indice: QModelIndex, papel=Qt.ItemDataRole.DisplayRole):
        if (
            indice.isValid()
            and indice.column() == 0
            and papel == Qt.ItemDataRole.CheckStateRole
        ):
            marcado = indice.row() in self._marcados
            return Qt.CheckState.Checked if marcado else Qt.CheckState.Unchecked
        return super().data(indice, papel)

    def setData(self, indice: QModelIndex, valor, papel=Qt.ItemDataRole.EditRole):  # noqa: N802
        if indice.isValid() and papel == Qt.ItemDataRole.CheckStateRole and indice.column() == 0:
            if Qt.CheckState(valor) == Qt.CheckState.Checked:
                self._marcados.add(indice.row())
            else:
                self._marcados.discard(indice.row())
            self.dataChanged.emit(indice, indice, [papel])
            return True
        return False

    def marcar_todos(self, marcado: bool = True) -> None:
        if marcado:
            self._marcados = {
                indice
                for indice, item in enumerate(self.itens)
                if not (self._bloqueado and self._bloqueado(item))
            }
        else:
            self._marcados.clear()
        if self.itens:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self.itens) - 1, 0),
                [Qt.ItemDataRole.CheckStateRole],
            )

    def marcados(self) -> list[Any]:
        return [self.itens[i] for i in sorted(self._marcados) if i < len(self.itens)]


class ProxyBusca(QSortFilterProxyModel):
    """Filtro por texto livre sobre todas as colunas, sem acento nem pontuação."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSortRole(PAPEL_ORDENACAO)
        self._termo = ""

    def definir_termo(self, termo: str) -> None:
        self._termo = normalizar_busca(termo)
        self.invalidateFilter()

    def filterAcceptsRow(self, linha: int, pai: QModelIndex) -> bool:  # noqa: N802
        if not self._termo:
            return True
        modelo = self.sourceModel()
        indice = modelo.index(linha, 0, pai)
        alvo = modelo.data(indice, PAPEL_BUSCA) or ""
        return all(parte in alvo for parte in self._termo.split())


def preparar_tabela(tabela: QTableView, esticar: int | None = None) -> QTableView:
    """Ajustes padrão da tabela.

    ``esticar`` é guardado e aplicado em ``ajustar_colunas``: definir o modo de
    redimensionamento antes de existir um modelo não tem efeito nenhum, porque o
    cabeçalho ainda não tem seções.
    """
    tabela.setAlternatingRowColors(True)
    tabela.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
    tabela.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
    tabela.setSortingEnabled(True)
    tabela.setWordWrap(False)
    tabela.verticalHeader().setVisible(False)
    tabela.verticalHeader().setDefaultSectionSize(26)
    tabela.horizontalHeader().setHighlightSections(False)
    tabela.horizontalHeader().setSectionsMovable(True)
    tabela.horizontalHeader().setStretchLastSection(False)
    tabela.coluna_esticada = esticar
    if esticar is not None:
        filtro = _AoRedimensionar(tabela)
        tabela.viewport().installEventFilter(filtro)
    return tabela


def itens_selecionados(tabela: QTableView) -> list[Any]:
    modelo = tabela.model()
    vistos: list[Any] = []
    for indice in tabela.selectionModel().selectedRows() if tabela.selectionModel() else []:
        item = modelo.data(indice, PAPEL_ITEM)
        if item is not None:
            vistos.append(item)
    return vistos


def item_atual(tabela: QTableView) -> Any | None:
    if tabela.selectionModel() is None:
        return None
    indice = tabela.selectionModel().currentIndex()
    if not indice.isValid():
        return None
    return tabela.model().data(indice.siblingAtColumn(0), PAPEL_ITEM)


# ------------------------------------------------------------------------ árvore


@dataclass
class NoSecao:
    """Cabeçalho de seção: título, quantidade e subtotal."""

    titulo: str
    itens: list[Any] = field(default_factory=list)
    subtotal: Decimal = Decimal("0.00")

    @property
    def rotulo(self) -> str:
        return f"{self.titulo}  ({len(self.itens)})"


class ModeloArvoreSecoes(QAbstractItemModel):
    """Duas camadas: seções recolhíveis e, dentro delas, as linhas."""

    def __init__(self, colunas: Sequence[Coluna], secoes: Sequence[NoSecao] = (), parent=None):
        super().__init__(parent)
        self.colunas = list(colunas)
        self._secoes = list(secoes)

    def definir_secoes(self, secoes: Sequence[NoSecao]) -> None:
        self.beginResetModel()
        self._secoes = list(secoes)
        self.endResetModel()

    @property
    def secoes(self) -> list[NoSecao]:
        return self._secoes

    # ---- estrutura
    # internalId é sem sinal: 0 identifica uma seção e, nas folhas, guarda a
    # linha da seção somada a 1.
    RAIZ = 0

    def index(self, linha, coluna, pai=QModelIndex()):  # noqa: B008
        if not self.hasIndex(linha, coluna, pai):
            return QModelIndex()
        if not pai.isValid():
            return self.createIndex(linha, coluna, self.RAIZ)
        return self.createIndex(linha, coluna, pai.row() + 1)

    def parent(self, indice: QModelIndex) -> QModelIndex:
        if not indice.isValid():
            return QModelIndex()
        identificador = int(indice.internalId())
        if identificador == self.RAIZ:
            return QModelIndex()
        return self.createIndex(identificador - 1, 0, self.RAIZ)

    def rowCount(self, pai=QModelIndex()) -> int:  # noqa: N802, B008
        if not pai.isValid():
            return len(self._secoes)
        if int(pai.internalId()) == self.RAIZ and pai.column() == 0:
            return len(self._secoes[pai.row()].itens)
        return 0

    def columnCount(self, pai=QModelIndex()) -> int:  # noqa: N802, B008
        return len(self.colunas)

    def headerData(self, secao, orientacao, papel=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientacao is Qt.Orientation.Horizontal and papel == Qt.ItemDataRole.DisplayRole:
            return self.colunas[secao].titulo
        return None

    def data(self, indice: QModelIndex, papel=Qt.ItemDataRole.DisplayRole):
        if not indice.isValid():
            return None
        coluna = self.colunas[indice.column()]
        if int(indice.internalId()) == self.RAIZ:
            secao = self._secoes[indice.row()]
            if papel == Qt.ItemDataRole.DisplayRole:
                if indice.column() == 0:
                    return secao.rotulo
                if coluna.titulo.startswith("Total"):
                    return formatar_moeda(secao.subtotal)
                return ""
            if papel == Qt.ItemDataRole.FontRole:
                fonte = QFont()
                fonte.setBold(True)
                return fonte
            if papel == Qt.ItemDataRole.TextAlignmentRole:
                return int(coluna.alinhamento)
            return None

        item = self._secoes[int(indice.internalId()) - 1].itens[indice.row()]
        if papel == Qt.ItemDataRole.DisplayRole:
            return coluna.texto(item)
        if papel == Qt.ItemDataRole.TextAlignmentRole:
            return int(coluna.alinhamento)
        if papel == PAPEL_ITEM:
            return item
        if papel == Qt.ItemDataRole.ForegroundRole and coluna.cor:
            cor = coluna.cor(item)
            return QBrush(cor) if cor else None
        if papel == Qt.ItemDataRole.FontRole and coluna.negrito:
            fonte = QFont()
            fonte.setBold(True)
            return fonte
        if papel == Qt.ItemDataRole.ToolTipRole and coluna.dica:
            return coluna.dica(item)
        return None


def preparar_arvore(arvore: QTreeView, esticar: int | None = None) -> QTreeView:
    arvore.setAlternatingRowColors(True)
    arvore.coluna_esticada = esticar
    arvore.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
    arvore.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
    arvore.setUniformRowHeights(True)
    arvore.setExpandsOnDoubleClick(False)
    arvore.header().setStretchLastSection(False)
    return arvore


def ajustar_colunas(visao, colunas: Sequence[Coluna], folga: int = 18) -> None:
    """Ajusta as colunas ao conteúdo, com folga para o título não ser cortado.

    ``resizeColumnToContents`` sozinho deixa o cabeçalho elidido ("Competên…"),
    então o cálculo considera também a largura do título.
    """
    from PySide6.QtGui import QFontMetrics

    esticar = getattr(visao, "coluna_esticada", None)
    metrica = QFontMetrics(visao.font())
    for indice, coluna in enumerate(colunas):
        if coluna.largura:  # largura declarada vale como está (ex.: caixa de seleção)
            visao.setColumnWidth(indice, coluna.largura)
            continue
        visao.resizeColumnToContents(indice)
        minimo = metrica.horizontalAdvance(coluna.titulo) + folga * 2
        largura = max(visao.columnWidth(indice) + folga, minimo)
        visao.setColumnWidth(indice, min(largura, 420))
    # A sobra de espaço vai para a coluna escolhida. Usar QHeaderView.Stretch
    # aqui seria pior: quando as outras colunas somam mais que a janela, a
    # esticada encolhe até sumir, e é justamente ela a mais importante.
    if esticar is not None and esticar < len(colunas):
        visao.largura_natural_esticada = visao.columnWidth(esticar)
        distribuir_sobra(visao)
    # depois de mudar as larguras, volta ao começo: senão a tabela fica rolada e
    # a primeira coluna aparece cortada
    barra = visao.horizontalScrollBar()
    if barra is not None:
        barra.setValue(0)


def distribuir_sobra(visao) -> None:
    """Dá à coluna esticada o espaço que sobra na largura atual da tabela."""
    esticar = getattr(visao, "coluna_esticada", None)
    natural = getattr(visao, "largura_natural_esticada", None)
    modelo = visao.model()
    if esticar is None or natural is None or modelo is None:
        return
    quantidade = modelo.columnCount()
    if esticar >= quantidade:
        return
    outras = sum(visao.columnWidth(i) for i in range(quantidade) if i != esticar)
    visao.setColumnWidth(esticar, max(natural, visao.viewport().width() - outras))


class _AoRedimensionar(QObject):
    """A janela mudou de tamanho: a coluna esticada acompanha (só ela)."""

    def eventFilter(self, objeto, evento) -> bool:  # noqa: N802
        if evento.type() == QEvent.Type.Resize:
            distribuir_sobra(self.parent())
        return False


def itens_selecionados_arvore(arvore: QTreeView) -> list[Any]:
    if arvore.selectionModel() is None:
        return []
    encontrados: list[Any] = []
    for indice in arvore.selectionModel().selectedRows():
        item = arvore.model().data(indice, PAPEL_ITEM)
        if item is not None and item not in encontrados:
            encontrados.append(item)
    return encontrados
