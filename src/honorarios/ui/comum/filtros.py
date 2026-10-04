"""Filtros compactos ("chips"): cada um mostra o valor atual e abre um menu.

Mesma interface dos combos que substituem (``addItem``, ``currentData``,
``setCurrentIndex``, ``currentIndexChanged``…), para as telas não mudarem por
dentro. Fora do padrão, o chip fica destacado, e "Limpar filtros" aparece.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from PySide6.QtCore import QDate, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QCalendarWidget,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QToolButton,
    QWidget,
    QWidgetAction,
)

from ...dominio.valores import formatar_data, hoje


class _Chip(QToolButton):
    alterou = Signal()   # qualquer mudança: a barra decide se mostra "Limpar"

    def __init__(self, rotulo: str, parent=None) -> None:
        super().__init__(parent)
        self.rotulo = rotulo
        self.setObjectName("chipFiltro")
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setAutoRaise(False)

    def ativo(self) -> bool:
        return False

    def limpar(self) -> None:
        """Volta ao padrão."""

    def _marcar(self) -> None:
        self.setProperty("ativo", self.ativo())
        self.style().unpolish(self)
        self.style().polish(self)
        self.alterou.emit()


class FiltroOpcoes(_Chip):
    """Escolha única num menu. "Rótulo: valor ▾"."""

    currentIndexChanged = Signal(int)   # noqa: N815 (mesma assinatura do QComboBox)

    def __init__(self, rotulo: str, opcoes: list[tuple[str, Any]] | None = None,
                 padrao: int = 0, parent=None) -> None:
        super().__init__(rotulo, parent)
        self._itens: list[tuple[str, Any]] = []
        self._indice = -1
        self.padrao = padrao
        self._menu = QMenu(self)
        self._grupo = QActionGroup(self)
        self._grupo.setExclusive(True)
        self.setMenu(self._menu)
        for texto, dado in opcoes or []:
            self.addItem(texto, dado)

    # --- interface de QComboBox -------------------------------------------
    def addItem(self, texto: str, dado: Any = None) -> None:  # noqa: N802
        self.insertItem(len(self._itens), texto, dado)

    def insertItem(self, posicao: int, texto: str, dado: Any = None) -> None:  # noqa: N802
        self._itens.insert(posicao, (texto, dado))
        self._refazer_menu()
        if self._indice < 0:
            self.setCurrentIndex(0)
        elif posicao <= self._indice:
            self._indice += 1
            self._atualizar_texto()

    def count(self) -> int:
        return len(self._itens)

    def currentIndex(self) -> int:  # noqa: N802
        return self._indice

    def currentData(self) -> Any:  # noqa: N802
        return self._itens[self._indice][1] if 0 <= self._indice < len(self._itens) else None

    def currentText(self) -> str:  # noqa: N802
        return self._itens[self._indice][0] if 0 <= self._indice < len(self._itens) else ""

    def findData(self, dado: Any) -> int:  # noqa: N802
        return next((i for i, (_, valor) in enumerate(self._itens) if valor == dado), -1)

    def itemText(self, indice: int) -> str:  # noqa: N802
        return self._itens[indice][0]

    def setCurrentIndex(self, indice: int) -> None:  # noqa: N802
        if not 0 <= indice < len(self._itens) or indice == self._indice:
            return
        self._indice = indice
        for numero, acao in enumerate(self._grupo.actions()):
            acao.setChecked(numero == indice)
        self._atualizar_texto()
        self._marcar()
        self.currentIndexChanged.emit(indice)

    def valor(self) -> Any:
        """Como o ComboRegistros: o dado escolhido."""
        return self.currentData()

    # --- chip -------------------------------------------------------------
    def ativo(self) -> bool:
        return self._indice != self.padrao

    def limpar(self) -> None:
        self.setCurrentIndex(self.padrao)

    def _refazer_menu(self) -> None:
        self._menu.clear()
        for acao in self._grupo.actions():
            self._grupo.removeAction(acao)
        for numero, (texto, _) in enumerate(self._itens):
            acao = QAction(texto, self._menu)
            acao.setCheckable(True)
            acao.setChecked(numero == self._indice)
            acao.triggered.connect(lambda _=False, n=numero: self.setCurrentIndex(n))
            self._grupo.addAction(acao)
            self._menu.addAction(acao)

    def _atualizar_texto(self) -> None:
        self.setText(f"{self.rotulo}: {self.currentText()}  ▾" if self.rotulo
                     else f"{self.currentText()}  ▾")


class FiltroLiga(_Chip):
    """Liga/desliga. Mesma interface do QCheckBox (``isChecked``, ``toggled``)."""

    def __init__(self, rotulo: str, parent=None) -> None:
        super().__init__(rotulo, parent)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)
        self.setCheckable(True)
        self.setText(rotulo)
        self.toggled.connect(lambda *_: self._marcar())

    def ativo(self) -> bool:
        return self.isChecked()

    def limpar(self) -> None:
        self.setChecked(False)


class FiltroData(_Chip):
    """Uma data, num calendário. Mesma interface do CampoData (``valor``, ``dateChanged``)."""

    dateChanged = Signal()   # noqa: N815

    def __init__(self, rotulo: str, valor: date | None = None, parent=None) -> None:
        super().__init__(rotulo, parent)
        self._valor = valor or hoje()
        self._padrao = self._valor
        menu = QMenu(self)
        self.calendario = QCalendarWidget()
        self.calendario.setGridVisible(False)
        self.calendario.clicked.connect(self._escolheu)
        acao = QWidgetAction(menu)
        acao.setDefaultWidget(self.calendario)
        menu.addAction(acao)
        voltar = menu.addAction("Voltar para hoje")
        voltar.triggered.connect(self.limpar)
        self.setMenu(menu)
        self._atualizar()

    def valor(self) -> date:
        return self._valor

    def definir(self, valor: date) -> None:
        if valor == self._valor:
            return
        self._valor = valor
        self._atualizar()
        self._marcar()
        self.dateChanged.emit()

    def ativo(self) -> bool:
        return self._valor != self._padrao

    def limpar(self) -> None:
        self.definir(self._padrao)

    def _escolheu(self, data: QDate) -> None:
        self.menu().close()
        self.definir(date(data.year(), data.month(), data.day()))

    def _atualizar(self) -> None:
        texto = "hoje" if self._valor == self._padrao else formatar_data(self._valor)
        self.setText(f"{self.rotulo}: {texto}  ▾")
        self.calendario.setSelectedDate(QDate(self._valor.year, self._valor.month,
                                              self._valor.day))


class BarraDeFiltros(QWidget):
    """Os chips em linha e, quando algum sai do padrão, "Limpar filtros"."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.chips: list[_Chip] = []
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self.limpar = QPushButton("Limpar filtros")
        self.limpar.setObjectName("linkFiltro")
        self.limpar.clicked.connect(self.limpar_todos)
        self.limpar.setVisible(False)
        self._layout.addWidget(self.limpar)
        self._layout.addStretch(1)

    def adicionar(self, chip: _Chip) -> _Chip:
        self._layout.insertWidget(len(self.chips), chip)
        self.chips.append(chip)
        chip.alterou.connect(self._conferir)
        return chip

    def adicionar_controle(self, widget: QWidget) -> QWidget:
        """Um controle que não é chip (ex.: ◀ mês ▶): entra antes dos chips."""
        self._layout.insertWidget(0, widget)
        return widget

    def limpar_todos(self) -> None:
        for chip in self.chips:
            if not chip.isHidden():
                chip.limpar()

    def _conferir(self) -> None:
        self.limpar.setVisible(any(chip.ativo() and not chip.isHidden() for chip in self.chips))
