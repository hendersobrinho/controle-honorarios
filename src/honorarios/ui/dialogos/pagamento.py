"""Baixa de pagamento: total ou parcial, com abono de juros justificado."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from ...dominio.enums import FormaPagamento
from ...dominio.valores import formatar_data, formatar_moeda, hoje
from ...servicos import pagamentos
from ..comum import widgets
from ..comum.campos import CampoData, CampoMoeda, ComboEnum, Rotulo
from ..contexto import Contexto


class DialogoPagamento(QDialog):
    def __init__(self, contexto: Contexto, honorario, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.honorario = honorario
        self.setWindowTitle("Registrar pagamento")
        self.resize(560, 520)
        self._montar()
        self._recalcular()

    def _montar(self) -> None:
        honorario = self.honorario
        layout = QVBoxLayout(self)
        layout.addWidget(
            widgets.Cabecalho(
                honorario.cliente.nome,
                f"{honorario.tipo.nome} · {honorario.competencia_rotulo} · "
                f"vencimento {formatar_data(honorario.vencimento)}",
            )
        )

        grupo = QGroupBox("Situação na data do pagamento")
        resumo = QFormLayout(grupo)
        self.data = CampoData(hoje())
        self.data.dateChanged.connect(self._recalcular)
        resumo.addRow("Data do pagamento:", self.data)
        self.dias = Rotulo("—")
        resumo.addRow("Dias em atraso:", self.dias)
        self.saldo = Rotulo("—")
        resumo.addRow("Saldo em aberto:", self.saldo)
        self.juros_devidos = Rotulo("—")
        resumo.addRow("Juros devidos:", self.juros_devidos)
        self.total_devido = Rotulo("—")
        resumo.addRow("Total devido:", self.total_devido)
        layout.addWidget(grupo)

        grupo_valores = QGroupBox("Valores recebidos")
        formulario = QFormLayout(grupo_valores)
        self.valor_pago = CampoMoeda()
        self.valor_pago.valueChanged.connect(self._avaliar)
        formulario.addRow("Valor pago:", self.valor_pago)
        self.juros_cobrados = CampoMoeda()
        self.juros_cobrados.valueChanged.connect(self._avaliar)
        formulario.addRow("Juros cobrados:", self.juros_cobrados)
        self.justificativa = QPlainTextEdit()
        self.justificativa.setMaximumHeight(60)
        self.justificativa.setPlaceholderText("Obrigatória quando há abono de juros")
        formulario.addRow("Justificativa do abono:", self.justificativa)
        self.forma = ComboEnum(FormaPagamento, FormaPagamento.PIX)
        formulario.addRow("Forma de pagamento:", self.forma)
        self.observacoes = QPlainTextEdit()
        self.observacoes.setMaximumHeight(60)
        formulario.addRow("Observações:", self.observacoes)
        layout.addWidget(grupo_valores)

        self.resultado = widgets.rotulo_fraco("")
        layout.addWidget(self.resultado)
        layout.addStretch(1)

        from ...servicos import configuracoes

        self.agradecer = QCheckBox("Abrir a imagem de agradecimento depois de registrar")
        self.agradecer.setToolTip(
            "Gera a imagem \"Pagamento recebido\" para mandar ao cliente, se quiser"
        )
        self.agradecer.setChecked(
            configuracoes.obter_bool(self.contexto.sessao, "agradecimento_apos_baixa", False)
        )
        layout.addWidget(self.agradecer)

        self.info_acordo = QLabel()
        self.info_acordo.setObjectName("previaMensagem")
        self.info_acordo.setWordWrap(True)
        self.info_acordo.setVisible(False)
        layout.addWidget(self.info_acordo)
        self._justificativa_automatica = ""

        acoes = QHBoxLayout()
        acoes.addStretch(1)
        cancelar = widgets.QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        confirmar = widgets.QPushButton("Registrar pagamento")
        confirmar.setObjectName("primario")
        confirmar.clicked.connect(self._registrar)
        acoes.addWidget(cancelar)
        acoes.addWidget(confirmar)
        layout.addLayout(acoes)

    def _recalcular(self) -> None:
        previa = pagamentos.previa(self.honorario, self.data.valor())
        self.previa = previa
        self.dias.setText(str(previa.dias_atraso))
        self.saldo.setText(formatar_moeda(previa.saldo))
        self.juros_devidos.setText(formatar_moeda(previa.juros_devidos))
        self.total_devido.setText(formatar_moeda(previa.total_devido))
        self.valor_pago.definir(previa.sugestao_valor)
        acordo = previa.juros_acordo is not None
        self.juros_cobrados.definir(previa.juros_acordo if acordo else previa.juros_devidos)
        # a justificativa do acordo entra sozinha, mas não apaga o que foi digitado
        atual = self.justificativa.toPlainText()
        if acordo and atual in ("", self._justificativa_automatica):
            self.justificativa.setPlainText(previa.justificativa_acordo)
            self._justificativa_automatica = previa.justificativa_acordo
        elif not acordo and atual == self._justificativa_automatica:
            self.justificativa.setPlainText("")
            self._justificativa_automatica = ""
        self.info_acordo.setVisible(acordo)
        if acordo:
            self.info_acordo.setText(
                "<b>Acordo vigente nesta data.</b> " + previa.justificativa_acordo
                + " O juros a mais desde então entra como abono."
            )
        self._avaliar()

    def _avaliar(self) -> None:
        pago = self.valor_pago.valor()
        juros = self.juros_cobrados.valor()
        principal = pago - juros
        saldo_final = self.previa.saldo - principal
        abono = self.previa.juros_devidos - juros
        partes = []
        if saldo_final > 0:
            partes.append(
                f"Pagamento parcial: fica {formatar_moeda(saldo_final)} em aberto, "
                "e o juros passa a correr sobre esse saldo."
            )
        elif saldo_final < 0:
            partes.append(
                f"O valor excede o saldo em {formatar_moeda(-saldo_final)}: "
                "confira o valor pago e os juros."
            )
        else:
            partes.append("Quita o honorário.")
        if abono > 0:
            partes.append(f"Abono de juros: {formatar_moeda(abono)} (exige justificativa).")
        self.resultado.setText(" ".join(partes))

    def _registrar(self) -> None:
        dados = pagamentos.DadosPagamento(
            data=self.data.valor(),
            valor_pago=self.valor_pago.valor(),
            juros_cobrados=self.juros_cobrados.valor(),
            justificativa_desconto=self.justificativa.toPlainText(),
            forma_pagamento=self.forma.valor(),
            observacoes=self.observacoes.toPlainText(),
        )

        def acao():
            from ...servicos import configuracoes

            pagamentos.registrar(self.contexto.sessao, self.honorario, dados)
            # a escolha da caixa fica guardada para a próxima baixa
            configuracoes.gravar(self.contexto.sessao, "agradecimento_apos_baixa",
                                 "1" if self.agradecer.isChecked() else "0")
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        if self.agradecer.isChecked():
            abrir_agradecimento(self.parent() or self, self.contexto, [self.honorario])
        self.accept()


def abrir_agradecimento(parent, contexto, honorarios) -> None:
    """A imagem "Pagamento recebido" dos honorários, para copiar ou salvar."""
    from ...servicos import imagem_cobranca
    from .imagem_cobranca import DialogoImagemCobranca

    def acao():
        return imagem_cobranca.montar_agradecimento(contexto.sessao, honorarios)

    deu_certo, dados = widgets.executar(parent, acao)
    if not deu_certo:
        return
    cliente = honorarios[0].cliente
    DialogoImagemCobranca(
        contexto, dados, f"agradecimento_{cliente.codigo}_{dados.campos['data'].replace('/', '-')}",
        f"Agradecimento – {cliente.nome}", parent, agradecimento=True,
    ).exec()
