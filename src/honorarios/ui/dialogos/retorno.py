"""Anotar o retorno do cliente direto da conferência do e-mail.

Se há uma cobrança desses honorários esperando resposta, o retorno vai nela;
senão, fica registrado um contato de hoje já com o retorno. É o que entra nas
anotações da resposta ao financeiro.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from ...dominio.enums import Canal, ResultadoCobranca
from ...dominio.valores import formatar_data, hoje
from ...servicos import acompanhamento
from ..comum import widgets
from ..comum.campos import CampoDataOpcional, ComboEnum
from ..contexto import Contexto


class DialogoRetorno(QDialog):
    def __init__(self, contexto: Contexto, cliente, honorarios, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.cliente = cliente
        self.honorarios = sorted(honorarios, key=lambda h: h.vencimento)
        self.setWindowTitle(f"Anotar retorno – {cliente.nome}")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        competencias = " · ".join(
            f"{h.competencia_rotulo or h.tipo.nome} (venc. {formatar_data(h.vencimento)})"
            for h in self.honorarios
        )
        layout.addWidget(widgets.Cabecalho(cliente.nome, competencias))

        self.lote = acompanhamento.cobranca_aguardando(contexto.sessao, self.honorarios)
        aviso = (f"Vai como resposta da cobrança enviada em {self.lote.data_hora:%d/%m}."
                 if self.lote is not None else
                 "Nenhuma cobrança destes honorários espera resposta: fica registrado um "
                 "contato de hoje, já com o retorno.")
        explicacao = widgets.rotulo_fraco(aviso)
        explicacao.setWordWrap(True)
        layout.addWidget(explicacao)

        formulario = QFormLayout()
        self.canal = ComboEnum(Canal, Canal.WHATSAPP)
        self.canal.setEnabled(self.lote is None)
        formulario.addRow("Como foi o contato:", self.canal)
        self.resultado = ComboEnum(ResultadoCobranca, ResultadoCobranca.SEM_RESPOSTA,
                                   excluir=(ResultadoCobranca.AGUARDANDO,))
        self.resultado.currentIndexChanged.connect(self._ajustar)
        formulario.addRow("O cliente:", self.resultado)
        self.promessa = CampoDataOpcional(None)
        formulario.addRow("Prometeu pagar em:", self.promessa)
        self.observacao = QPlainTextEdit()
        self.observacao.setPlaceholderText(
            "Ex.: vai pagar o boleto de julho dia 28; pediu para parcelar em 3x…"
        )
        self.observacao.setMaximumHeight(100)
        formulario.addRow("Observação:", self.observacao)
        layout.addLayout(formulario)
        self.erro = QLabel("")
        self.erro.setObjectName("resultadoConexao")
        layout.addWidget(self.erro)

        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                  QDialogButtonBox.StandardButton.Cancel)
        botoes.button(QDialogButtonBox.StandardButton.Save).setText("Salvar retorno")
        botoes.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        botoes.accepted.connect(self._salvar)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)
        self._ajustar()

    def _ajustar(self) -> None:
        prometeu = self.resultado.valor() is ResultadoCobranca.PROMETEU_PAGAR
        self.promessa.setEnabled(prometeu)
        if prometeu and self.promessa.valor() is None:
            self.promessa.definir(hoje())
        if not prometeu:
            self.promessa.definir(None)

    def _salvar(self) -> None:
        def acao():
            feito = acompanhamento.anotar_retorno(
                self.contexto.sessao, self.cliente, self.honorarios, self.resultado.valor(),
                self.promessa.valor(), self.observacao.toPlainText(), self.canal.valor(),
                self.contexto.data_referencia,
            )
            self.contexto.salvar()
            return feito

        deu_certo, self.feito = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.accept()
