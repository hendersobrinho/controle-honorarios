"""Campos de entrada em português: moeda, data, documento, telefone e combos."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
)

from ...dominio.valores import (
    formatar_documento,
    formatar_moeda,
    formatar_telefone,
    so_digitos,
)


def para_qdate(valor: date | None) -> QDate:
    if valor is None:
        return QDate.currentDate()
    return QDate(valor.year, valor.month, valor.day)


def de_qdate(valor: QDate) -> date:
    return date(valor.year(), valor.month(), valor.day())


class CampoData(QDateEdit):
    def __init__(self, valor: date | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setDisplayFormat("dd/MM/yyyy")
        self.setCalendarPopup(True)
        self.setDate(para_qdate(valor))

    def valor(self) -> date:
        return de_qdate(self.date())

    def definir(self, valor: date | None) -> None:
        self.setDate(para_qdate(valor))


class CampoDataOpcional(CampoData):
    """Data que pode ficar em branco (vigência sem fim, por exemplo)."""

    def __init__(self, valor: date | None = None, parent=None) -> None:
        super().__init__(valor, parent)
        self.setSpecialValueText("—")
        self.setMinimumDate(QDate(1900, 1, 1))
        if valor is None:
            self.setDate(self.minimumDate())

    def valor(self) -> date | None:  # type: ignore[override]
        if self.date() == self.minimumDate():
            return None
        return de_qdate(self.date())

    def definir(self, valor: date | None) -> None:
        self.setDate(self.minimumDate() if valor is None else para_qdate(valor))


class CampoMoeda(QDoubleSpinBox):
    def __init__(self, valor: Decimal | float = 0, parent=None) -> None:
        super().__init__(parent)
        self.setPrefix("R$ ")
        self.setDecimals(2)
        self.setMaximum(99_999_999.99)
        self.setGroupSeparatorShown(True)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.setValue(float(valor or 0))

    def valor(self) -> Decimal:
        return Decimal(f"{self.value():.2f}")

    def definir(self, valor: Decimal | float | None) -> None:
        self.setValue(float(valor or 0))


class CampoTaxa(QDoubleSpinBox):
    """Juros ao dia em reais, com 2 casas (a planilha usa 2)."""

    def __init__(self, valor: Decimal | float = 0, parent=None) -> None:
        super().__init__(parent)
        self.setPrefix("R$ ")
        self.setSuffix(" / dia")
        self.setDecimals(2)
        self.setSingleStep(0.01)
        self.setMaximum(9_999.99)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.setValue(float(valor or 0))

    def valor(self) -> Decimal:
        return Decimal(f"{self.value():.2f}")

    def definir(self, valor: Decimal | float | None) -> None:
        self.setValue(float(valor or 0))


class CampoDocumento(QLineEdit):
    """CPF/CNPJ com máscara aplicada ao sair do campo."""

    def __init__(self, valor: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("000.000.000-00 ou 00.000.000/0000-00")
        self.definir(valor)
        self.editingFinished.connect(self._formatar)

    def _formatar(self) -> None:
        digitos = so_digitos(self.text())
        if len(digitos) in (11, 14):
            self.setText(formatar_documento(digitos))

    def valor(self) -> str:
        return so_digitos(self.text())

    def definir(self, valor: str) -> None:
        self.setText(formatar_documento(valor) if valor else "")


class CampoTelefone(QLineEdit):
    def __init__(self, valor: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("(27) 99999-0000")
        self.definir(valor)
        self.editingFinished.connect(self._formatar)

    def _formatar(self) -> None:
        self.setText(formatar_telefone(self.text()))

    def valor(self) -> str:
        return self.text()

    def definir(self, valor: str) -> None:
        self.setText(formatar_telefone(valor) if valor else "")


class ComboEnum(QComboBox):
    """Combo alimentado por um enum do domínio, mostrando o rótulo em português.

    O dado guardado no combo volta do Qt como texto simples; por isso tudo é
    convertido de novo para o membro do enum. Sem isso, comparações ``is`` no
    domínio (``resultado is ResultadoCobranca.PROMETEU_PAGAR``) falham calado.
    """

    def __init__(self, enumeracao, atual=None, excluir=(), parent=None) -> None:
        super().__init__(parent)
        self.enumeracao = enumeracao
        for item in enumeracao:
            if item in excluir:
                continue
            self.addItem(item.rotulo, item.value)
        if atual is not None:
            self.definir(atual)

    def _converter(self, dado):
        if dado is None or isinstance(dado, self.enumeracao):
            return dado
        try:
            return self.enumeracao(dado)
        except ValueError:
            return None

    def currentData(self, papel=int(Qt.ItemDataRole.UserRole)):  # noqa: N802
        return self._converter(super().currentData(papel))

    def valor(self):
        return self.currentData()

    def definir(self, item) -> None:
        alvo = item.value if isinstance(item, self.enumeracao) else item
        indice = self.findData(alvo)
        if indice >= 0:
            self.setCurrentIndex(indice)


class ComboRegistros(QComboBox):
    """Combo de registros do banco: guarda o id e mostra um rótulo."""

    def __init__(
        self, registros=(), rotulo=lambda registro: str(registro), vazio: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._rotulo = rotulo
        self.recarregar(registros, vazio)

    def recarregar(self, registros, vazio: str | None = None) -> None:
        atual = self.valor()
        self.clear()
        if vazio is not None:
            self.addItem(vazio, None)
        for registro in registros:
            self.addItem(self._rotulo(registro), registro.id)
        if atual is not None:
            self.definir(atual)

    def valor(self) -> int | None:
        return self.currentData()

    def definir(self, identificador: int | None) -> None:
        indice = self.findData(identificador)
        self.setCurrentIndex(max(0, indice))


class Rotulo(QLabel):
    def __init__(self, texto: str = "", papel: str = "", parent=None) -> None:
        super().__init__(texto, parent)
        if papel:
            self.setObjectName(papel)


class ValorDestaque(QLabel):
    """Total atualizado, sempre em evidência."""

    def __init__(self, valor: Decimal | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("valorDestaque")
        fonte = QFont()
        fonte.setPointSize(16)
        fonte.setBold(True)
        self.setFont(fonte)
        self.definir(valor)

    def definir(self, valor: Decimal | None) -> None:
        self.setText(formatar_moeda(valor))


class CampoBusca(QLineEdit):
    buscou = Signal(str)

    def __init__(self, dica: str = "Buscar…", parent=None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(dica)
        self.setClearButtonEnabled(True)
        self.textChanged.connect(self.buscou.emit)
