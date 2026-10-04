"""Corrigir uma linha do e-mail que não bateu com o sistema.

Mostra a linha como veio no e-mail e os honorários do sistema mais parecidos
(mesmo cliente, mesma competência, vencimento perto). A pessoa escolhe a qual
honorário a linha se refere — ou marca para ignorar. A escolha fica guardada no
e-mail, e a conferência passa a usar.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...dominio.enums import StatusPagamento
from ...dominio.valores import formatar_data, formatar_moeda, normalizar_busca
from ...servicos import email_cobrancas as servico
from ...servicos import honorarios as servico_honorarios
from ..comum import widgets
from ..contexto import Contexto

IGNORAR = 0
COLUNAS = ("Cliente", "Competência", "Vencimento", "Valor", "Situação")


def _nota(lida: servico.LinhaLida, honorario) -> float:
    """Quão parecido o honorário é com a linha do e-mail (maior = mais parecido)."""
    nome = servico.semelhanca(lida.cliente, honorario.cliente.nome)
    if lida.codigo and lida.codigo == honorario.cliente.codigo:
        nome = 1.0
    competencia = 1.0 if honorario.competencia_rotulo == lida.competencia else 0.0
    dias = abs((honorario.vencimento - lida.vencimento).days)
    perto = max(0.0, 1 - dias / 60)
    valor = 1.0 if lida.valor is not None and lida.valor in (
        honorario.saldo_aberto, honorario.valor_original) else 0.0
    return nome * 3 + competencia * 2 + perto + valor


class DialogoCorrigirLinha(QDialog):
    def __init__(self, contexto: Contexto, lida: servico.LinhaLida, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.lida = lida
        self.escolha: int | None = None    # id do honorário, IGNORAR ou None (cancelou)
        self.setWindowTitle("Corrigir linha do e-mail")
        self.resize(820, 560)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(widgets.Cabecalho(
            "A qual honorário esta linha se refere?",
            "Escolha o honorário do sistema; a escolha fica guardada neste e-mail.",
        ))

        cartao = QFrame()
        cartao.setObjectName("resumoConfirmacao")
        grade = QGridLayout(cartao)
        grade.setContentsMargins(14, 10, 14, 10)
        grade.setHorizontalSpacing(18)
        cliente = f"{lida.codigo} – {lida.cliente}" if lida.codigo else lida.cliente
        valor = formatar_moeda(lida.valor) if lida.valor is not None else "—"
        for coluna, (rotulo, texto) in enumerate((
            ("No e-mail", cliente), ("Competência", lida.competencia),
            ("Vencimento", formatar_data(lida.vencimento)), ("Valor", valor),
        )):
            nome = QLabel(rotulo)
            nome.setObjectName("rotuloResumoConfirmacao")
            dado = QLabel(texto)
            dado.setObjectName("valorResumoConfirmacao")
            grade.addWidget(nome, 0, coluna)
            grade.addWidget(dado, 1, coluna)
        grade.setColumnStretch(0, 1)
        layout.addWidget(cartao)

        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Buscar outro cliente…")
        self.busca.textChanged.connect(self._listar)
        layout.addWidget(self.busca)
        self.tabela = QTableWidget(0, len(COLUNAS))
        self.tabela.setHorizontalHeaderLabels(COLUNAS)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabela.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.tabela.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabela.horizontalHeader().setStretchLastSection(True)
        self.tabela.itemSelectionChanged.connect(self._atualizar)
        self.tabela.itemDoubleClicked.connect(lambda *_: self._associar())
        layout.addWidget(self.tabela, 1)
        self.dica = widgets.rotulo_fraco("")
        layout.addWidget(self.dica)

        botoes = QHBoxLayout()
        ignorar = QPushButton("Ignorar esta linha")
        ignorar.setToolTip("Para o que não é do sistema: a linha fica fora da conferência "
                           "(continua na resposta como veio)")
        ignorar.clicked.connect(self._ignorar)
        botoes.addWidget(ignorar)
        botoes.addStretch(1)
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        self.botao_associar = QPushButton("Usar este honorário")
        self.botao_associar.setObjectName("primario")
        self.botao_associar.clicked.connect(self._associar)
        botoes.addWidget(cancelar)
        botoes.addWidget(self.botao_associar)
        layout.addLayout(botoes)

        sessao = contexto.sessao
        self.candidatos = (
            servico_honorarios.pendentes(sessao, servico_honorarios.Filtro())
            + servico_honorarios.pagos(sessao, servico_honorarios.Filtro())
        )
        self._listar()

    def _listar(self) -> None:
        termo = normalizar_busca(self.busca.text())
        linhas = [linha for linha in self.candidatos
                  if not termo or termo in normalizar_busca(linha.cliente.nome)]
        linhas.sort(key=lambda linha: -_nota(self.lida, linha.honorario))
        if not termo:   # sem busca: os mais prováveis (nome, competência, data ou valor)
            linhas = [linha for linha in linhas
                      if _nota(self.lida, linha.honorario) >= 0.5][:40] or linhas[:40]
        self.linhas = linhas
        self.tabela.setRowCount(len(linhas))
        direita = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        for numero, linha in enumerate(linhas):
            honorario = linha.honorario
            pago = honorario.status is StatusPagamento.PAGO
            textos = (
                servico.nome_no_email(linha.cliente),
                honorario.competencia_rotulo or honorario.tipo.nome,
                formatar_data(honorario.vencimento),
                formatar_moeda(honorario.valor_original if pago else honorario.saldo_aberto),
                "Pago" if pago else "Em aberto",
            )
            for coluna, texto in enumerate(textos):
                celula = QTableWidgetItem(texto)
                if coluna == 3:
                    celula.setTextAlignment(direita)
                self.tabela.setItem(numero, coluna, celula)
        self.tabela.resizeColumnsToContents()
        if linhas:
            self.tabela.selectRow(0)   # o mais parecido já vem escolhido
        self.dica.setText(
            "Os mais parecidos primeiro (cliente, competência, vencimento e valor). "
            if linhas else "Nenhum honorário encontrado. Busque pelo nome do cliente."
        )
        self._atualizar()

    def _atualizar(self) -> None:
        self.botao_associar.setEnabled(bool(self.tabela.selectionModel().selectedRows()))

    def _associar(self) -> None:
        selecionadas = self.tabela.selectionModel().selectedRows()
        if not selecionadas:
            return
        self.escolha = self.linhas[selecionadas[0].row()].honorario.id
        self.accept()

    def _ignorar(self) -> None:
        self.escolha = IGNORAR
        self.accept()
