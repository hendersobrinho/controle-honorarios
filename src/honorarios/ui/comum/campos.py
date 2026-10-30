"""Campos de entrada em português: moeda, data, documento, telefone e combos."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCalendarWidget,
    QComboBox,
    QLabel,
    QLineEdit,
    QMenu,
    QWidgetAction,
)

from ...dominio.valores import (
    formatar_data,
    formatar_documento,
    formatar_moeda,
    formatar_telefone,
    ler_data_livre,
    ler_numero_livre,
    so_digitos,
)


def para_qdate(valor: date | None) -> QDate:
    if valor is None:
        return QDate.currentDate()
    return QDate(valor.year, valor.month, valor.day)


def de_qdate(valor: QDate) -> date:
    return date(valor.year(), valor.month(), valor.day())


def _icone_calendario() -> QIcon:
    """Um calendarinho desenhado (o Qt não tem um ícone de calendário pronto)."""
    imagem = QPixmap(32, 32)
    imagem.fill(Qt.GlobalColor.transparent)
    pintor = QPainter(imagem)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    cor = QColor("#6b7684")
    pintor.setPen(QPen(cor, 2.4))
    pintor.drawRoundedRect(QRectF(5, 7, 22, 20), 3, 3)
    pintor.drawLine(5, 13, 27, 13)
    pintor.drawLine(11, 4, 11, 9)
    pintor.drawLine(21, 4, 21, 9)
    pintor.setPen(Qt.PenStyle.NoPen)
    pintor.setBrush(cor)
    for x in (10, 16, 22):
        for y in (17, 22):
            pintor.drawEllipse(QRectF(x - 1.5, y - 1.5, 3, 3))
    pintor.end()
    return QIcon(imagem)


class _CampoLivre(QLineEdit):
    """Campo de texto livre que avisa (borda vermelha e dica) em vez de travar."""

    dica_padrao = ""

    def _avisar(self, motivo: str = "") -> None:
        if bool(self.property("invalido")) != bool(motivo):
            self.setProperty("invalido", bool(motivo))
            self.style().unpolish(self)
            self.style().polish(self)
        self.setToolTip(motivo or self.dica_padrao)


class CampoData(_CampoLivre):
    """Data digitada livre — 30/10/2026, 30102026, 30/10/26, 30-10, "hoje" — com as
    barras entrando sozinhas e o calendário num botão, para quem preferir.

    Mesma interface de antes (``valor``, ``definir``, ``dateChanged``, ``date``,
    ``setDate``, limites): as telas não precisaram mudar.
    """

    dateChanged = Signal(QDate)
    opcional = False
    dica_padrao = "Digite a data (30/10/2026, 30102026, 30/10/26…) ou use o calendário"

    def __init__(self, valor: date | None = None, parent=None) -> None:
        super().__init__(parent)
        self._valor: date | None = None
        self._minimo: date | None = None
        self._maximo: date | None = None
        self._anterior = ""
        self.setPlaceholderText("dd/mm/aaaa" + (" (opcional)" if self.opcional else ""))
        self.setToolTip(self.dica_padrao)
        self.setMinimumWidth(140)
        calendario = self.addAction(_icone_calendario(),
                                    QLineEdit.ActionPosition.TrailingPosition)
        calendario.setToolTip("Escolher no calendário")
        calendario.triggered.connect(self._abrir_calendario)
        self.textEdited.connect(self._digitando)
        self.editingFinished.connect(self._terminou)
        self.definir(valor if valor is not None or self.opcional else date.today())

    # ---- interface de sempre
    def valor(self) -> date | None:
        return self._valor

    def definir(self, valor: date | None) -> None:
        if valor is None and not self.opcional:
            valor = date.today()
        self._aplicar(valor)

    def date(self) -> QDate:   # noqa: A003 - nome da API do QDateEdit
        return para_qdate(self._valor) if self._valor else QDate()

    def setDate(self, valor: QDate) -> None:  # noqa: N802
        self.definir(de_qdate(valor) if valor.isValid() else None)

    def setMinimumDate(self, valor: QDate) -> None:  # noqa: N802
        self._minimo = de_qdate(valor)

    def setMaximumDate(self, valor: QDate) -> None:  # noqa: N802
        self._maximo = de_qdate(valor)

    # ---- digitação
    def _aplicar(self, valor: date | None, formatar: bool = True) -> None:
        mudou = valor != self._valor
        self._valor = valor
        if formatar:
            self.setText(formatar_data(valor) if valor else "")
            self._anterior = self.text()
        self._avisar()
        if mudou:
            self.dateChanged.emit(self.date())

    def _fora_dos_limites(self, valor: date) -> str:
        if self._minimo and valor < self._minimo:
            return f"A data não pode ser antes de {formatar_data(self._minimo)}."
        if self._maximo and valor > self._maximo:
            return f"A data não pode passar de {formatar_data(self._maximo)}."
        return ""

    def _digitando(self, texto: str) -> None:
        novo = texto.replace("//", "/")
        crescendo = len(novo) > len(self._anterior)
        # as barras entram sozinhas: 30 → 30/, 30/10 → 30/10/
        if crescendo and re.fullmatch(r"\d{2}|\d{2}/\d{2}", novo):
            novo += "/"
        if novo != texto:
            self.setText(novo)
        self._anterior = novo
        self._avisar()
        if re.fullmatch(r"\d{2}/\d{2}/\d{4}", novo):   # completa: já vale
            try:
                valor = ler_data_livre(novo)
            except ValueError as falha:
                self._avisar(str(falha))
                return
            if not self._fora_dos_limites(valor):
                self._aplicar(valor, formatar=False)

    def _terminou(self) -> None:
        texto = self.text()
        try:
            valor = ler_data_livre(texto)
        except ValueError as falha:
            self._avisar(str(falha))   # o texto fica, para corrigir; o valor não muda
            return
        if valor is None:
            if self.opcional:
                self._aplicar(None)
            else:   # data obrigatória: volta a que estava
                self._aplicar(self._valor)
            return
        motivo = self._fora_dos_limites(valor)
        if motivo:
            self._avisar(motivo)
            return
        self._aplicar(valor)

    def _abrir_calendario(self) -> None:
        menu = QMenu(self)
        calendario = QCalendarWidget()
        calendario.setGridVisible(False)
        calendario.setSelectedDate(para_qdate(self._valor or date.today()))
        if self._minimo:
            calendario.setMinimumDate(para_qdate(self._minimo))
        if self._maximo:
            calendario.setMaximumDate(para_qdate(self._maximo))

        def escolheu(dia: QDate) -> None:
            self._aplicar(de_qdate(dia))
            menu.close()

        calendario.clicked.connect(escolheu)
        acao = QWidgetAction(menu)
        acao.setDefaultWidget(calendario)
        menu.addAction(acao)
        menu.exec(self.mapToGlobal(QPoint(0, self.height())))


class CampoDataOpcional(CampoData):
    """Data que pode ficar em branco (vigência sem fim, por exemplo): apague e pronto."""

    opcional = True


class CampoNumero(_CampoLivre):
    """Número digitado livre — 1.234,56, 1234,56, 1234.56, 2 — formatado ao sair do campo.

    Enquanto se digita, o campo mostra só o número (sem "R$" no meio do caminho);
    o valor já vale a cada tecla (``valueChanged``), como antes.
    """

    valueChanged = Signal(float)
    dica_padrao = "Digite o valor: 1.234,56, 1234,56 ou 1234.56"

    def __init__(self, valor: Decimal | float = 0, prefixo: str = "", sufixo: str = "",
                 maximo: Decimal | float = Decimal("99999999.99"), parent=None) -> None:
        super().__init__(parent)
        self._prefixo, self._sufixo = prefixo, sufixo
        self._minimo = Decimal(0)
        self._maximo = Decimal(str(maximo))
        self._valor = Decimal("0.00")
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setToolTip(self.dica_padrao)
        self.textEdited.connect(self._digitando)
        self.editingFinished.connect(self._terminou)
        self.definir(valor)

    # ---- interface de sempre (a do QDoubleSpinBox que ele substitui)
    def valor(self) -> Decimal:
        return self._valor

    def definir(self, valor: Decimal | float | None) -> None:
        self._aplicar(Decimal(str(valor or 0)).quantize(Decimal("0.01")))

    def value(self) -> float:
        return float(self._valor)

    def setValue(self, valor: float) -> None:  # noqa: N802
        self.definir(valor)

    def setPrefix(self, texto: str) -> None:  # noqa: N802
        self._prefixo = texto
        self._mostrar()

    def setSuffix(self, texto: str) -> None:  # noqa: N802
        self._sufixo = texto
        self._mostrar()

    def setMaximum(self, valor: float) -> None:  # noqa: N802
        self._maximo = Decimal(str(valor))

    def setMinimum(self, valor: float) -> None:  # noqa: N802
        self._minimo = Decimal(str(valor))

    # ---- digitação
    def _sem_simbolo(self) -> str:
        return formatar_moeda(self._valor, com_simbolo=False)

    def _mostrar(self) -> None:
        self.setText(self._sem_simbolo() if self.hasFocus()
                     else f"{self._prefixo}{self._sem_simbolo()}{self._sufixo}")

    def _aplicar(self, valor: Decimal, formatar: bool = True) -> None:
        mudou = valor != self._valor
        self._valor = valor
        if formatar:
            self._mostrar()
        self._avisar()
        if mudou:
            self.valueChanged.emit(float(valor))

    def _ler(self, texto: str) -> Decimal:
        valor = ler_numero_livre(texto)
        if valor < self._minimo:
            raise ValueError("O valor não pode ser negativo." if self._minimo == 0
                             else f"O mínimo é {formatar_moeda(self._minimo, False)}.")
        if valor > self._maximo:
            raise ValueError(f"O máximo é {formatar_moeda(self._maximo, False)}.")
        return valor

    def _digitando(self, texto: str) -> None:
        try:
            self._aplicar(self._ler(texto), formatar=False)
        except ValueError as falha:
            self._avisar(str(falha))

    def _terminou(self) -> None:
        try:
            self._aplicar(self._ler(self.text()))
        except ValueError as falha:
            self._avisar(str(falha))   # o texto fica, para corrigir; o valor não muda

    def focusInEvent(self, evento) -> None:  # noqa: N802
        super().focusInEvent(evento)
        if not self.property("invalido"):
            self.setText(self._sem_simbolo())   # só o número para editar, sem "R$"
        QTimer.singleShot(0, self.selectAll)   # digitar já troca o valor inteiro

    def focusOutEvent(self, evento) -> None:  # noqa: N802
        super().focusOutEvent(evento)
        if not self.property("invalido"):
            self._mostrar()


class CampoMoeda(CampoNumero):
    def __init__(self, valor: Decimal | float = 0, parent=None) -> None:
        super().__init__(valor, prefixo="R$ ", parent=parent)


class CampoTaxa(CampoNumero):
    """Juros ao dia em reais, com 2 casas (a planilha usa 2)."""

    def __init__(self, valor: Decimal | float = 0, parent=None) -> None:
        super().__init__(valor, prefixo="R$ ", sufixo=" / dia", maximo=Decimal("9999.99"),
                         parent=parent)


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
    """Campo de busca que só avisa depois que a pessoa para de digitar.

    Cada tecla refazendo a consulta e a lista inteira deixava a tela pesada; com a
    espera, "empresa" é uma busca só, não sete. Enter busca na hora. Com
    ``atraso_ms`` em 0 (os testes) o sinal sai a cada mudança, sem timer.
    """

    buscou = Signal(str)
    atraso_ms = 300

    def __init__(self, dica: str = "Buscar…", parent=None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(dica)
        self.setClearButtonEnabled(True)
        self._espera = QTimer(self)
        self._espera.setSingleShot(True)
        self._espera.timeout.connect(self._avisar)
        self.textChanged.connect(self._ao_mudar)
        self.returnPressed.connect(self._avisar)

    def _ao_mudar(self, _texto: str) -> None:
        if self.atraso_ms <= 0:
            self._avisar()
        else:
            self._espera.start(self.atraso_ms)

    def _avisar(self) -> None:
        self._espera.stop()
        self.buscou.emit(self.text())
