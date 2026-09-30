"""Registro do retorno do cliente a uma cobrança já enviada."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QPlainTextEdit,
    QVBoxLayout,
)

from ...dominio.enums import ResultadoCobranca
from ...dominio.valores import formatar_data, formatar_moeda, hoje
from ...servicos import acompanhamento as servico
from ..comum import widgets
from ..comum.campos import CampoDataOpcional, ComboEnum, Rotulo
from ..contexto import Contexto


class DialogoResposta(QDialog):
    def __init__(self, contexto: Contexto, linha: servico.LinhaAcompanhamento, parent=None):
        super().__init__(parent)
        self.contexto = contexto
        self.linha = linha
        self.setWindowTitle(f"Resposta da cobrança – {linha.cliente.nome}")
        self.resize(560, 520)
        self._montar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(
            widgets.Cabecalho(
                self.linha.cliente.nome,
                f"Cobrado em {formatar_data(self.linha.data)} "
                f"({self.linha.dias} dia(s) atrás) · {self.linha.quantidade} honorário(s)",
            )
        )

        grupo = QGroupBox("O que o cliente respondeu")
        formulario = QFormLayout(grupo)
        self.resultado = ComboEnum(ResultadoCobranca, self.linha.resultado)
        self.resultado.currentIndexChanged.connect(self._ajustar)
        formulario.addRow("Resultado:", self.resultado)
        self.promessa = CampoDataOpcional(self.linha.promessa)
        formulario.addRow("Prometeu pagar em:", self.promessa)
        self.observacao = QPlainTextEdit(self.linha.observacao)
        self.observacao.setPlaceholderText(
            "Ex.: falou com o financeiro, pediu boleto novo, vai pagar metade…"
        )
        self.observacao.setMaximumHeight(90)
        formulario.addRow("Observação:", self.observacao)
        layout.addWidget(grupo)

        situacao = QGroupBox("Situação hoje")
        resumo = QFormLayout(situacao)
        resumo.addRow("Valor na época:", Rotulo(formatar_moeda(self.linha.lote.total_no_momento)))
        resumo.addRow("Ainda em aberto:", Rotulo(formatar_moeda(self.linha.saldo_atual)))
        resumo.addRow(
            "Já quitados:",
            Rotulo(f"{self.linha.quitados} de {self.linha.quantidade} honorário(s)"),
        )
        resumo.addRow("Competências:", Rotulo(self.linha.competencias or "—"))
        layout.addWidget(situacao)

        self.aviso = widgets.rotulo_fraco("")
        layout.addWidget(self.aviso)
        layout.addStretch(1)

        acoes = QHBoxLayout()
        ver = widgets.QPushButton("Ver mensagem enviada")
        ver.clicked.connect(self._ver_mensagem)
        acoes.addWidget(ver)
        acoes.addStretch(1)
        cancelar = widgets.QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        salvar = widgets.QPushButton("Salvar resposta")
        salvar.setObjectName("primario")
        salvar.setShortcut("Ctrl+S")
        salvar.clicked.connect(self._salvar)
        acoes.addWidget(cancelar)
        acoes.addWidget(salvar)
        layout.addLayout(acoes)
        self._ajustar()

    def _ajustar(self) -> None:
        prometeu = self.resultado.valor() is ResultadoCobranca.PROMETEU_PAGAR
        self.promessa.setEnabled(prometeu)
        if prometeu and self.promessa.valor() is None:
            self.promessa.definir(hoje())
        if self.resultado.valor() is ResultadoCobranca.PEDIU_RENEGOCIACAO:
            self.aviso.setText(
                "Depois de salvar, use \"Renegociar selecionados\" na Cobrança geral "
                "para fechar o acordo."
            )
        elif self.resultado.valor() is ResultadoCobranca.PAGOU:
            self.aviso.setText(
                "Se já recebeu, registre a baixa: a cobrança encerra sozinha quando "
                "os honorários ficam pagos."
            )
        else:
            self.aviso.setText("")

    def _ver_mensagem(self) -> None:
        widgets.informar(
            self,
            self.linha.texto or "(cobrança registrada sem mensagem gerada pelo sistema)",
            "Mensagem enviada",
        )

    def _salvar(self) -> None:
        def acao():
            servico.registrar_resposta(
                self.contexto.sessao,
                self.linha,
                self.resultado.valor(),
                self.promessa.valor(),
                self.observacao.toPlainText(),
            )
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.accept()
