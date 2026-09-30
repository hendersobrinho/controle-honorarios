"""Cadastro de tipo de honorário, com os textos que vão para a mensagem."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

from ...dominio import mensagens as dominio_mensagens
from ...dominio.enums import ExigeCompetencia, Periodicidade
from ...servicos import tipos as servico
from ..comum import widgets
from ..comum.campos import ComboEnum, ComboRegistros
from ..contexto import Contexto


class DialogoTipo(QDialog):
    def __init__(self, contexto: Contexto, tipo=None, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.tipo = tipo
        self.setWindowTitle("Editar tipo de honorário" if tipo else "Novo tipo de honorário")
        self.resize(640, 520)
        self._montar()
        if tipo:
            self._carregar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        formulario = QFormLayout()
        self.nome = QLineEdit()
        formulario.addRow("Nome:", self.nome)
        self.grupo = ComboRegistros(
            servico.listar_grupos(self.contexto.sessao), rotulo=lambda g: g.nome
        )
        formulario.addRow("Grupo de exibição:", self.grupo)
        self.periodicidade = ComboEnum(Periodicidade, Periodicidade.MENSAL)
        formulario.addRow("Periodicidade padrão:", self.periodicidade)
        self.exige = ComboEnum(ExigeCompetencia, ExigeCompetencia.MES)
        formulario.addRow("Competência:", self.exige)
        self.ativo = QCheckBox("Ativo")
        self.ativo.setChecked(True)
        formulario.addRow("", self.ativo)
        layout.addLayout(formulario)

        layout.addWidget(widgets.rotulo_fraco("Texto na mensagem (sem citar a empresa)"))
        self.texto = QPlainTextEdit(dominio_mensagens.TEXTO_MENSAL)
        self.texto.setMaximumHeight(60)
        layout.addWidget(self.texto)
        layout.addWidget(widgets.rotulo_fraco("Texto na mensagem citando a empresa"))
        self.texto_empresa = QPlainTextEdit(dominio_mensagens.TEXTO_MENSAL_EMPRESA)
        self.texto_empresa.setMaximumHeight(60)
        layout.addWidget(self.texto_empresa)
        layout.addWidget(
            widgets.rotulo_fraco("Linha usada quando a mensagem lista vários honorários")
        )
        self.texto_item = QPlainTextEdit(dominio_mensagens.TEXTO_MENSAL_ITEM)
        self.texto_item.setMaximumHeight(60)
        layout.addWidget(self.texto_item)
        layout.addWidget(
            widgets.rotulo_fraco(
                "Variáveis: {competencia}, {ano}, {empresa}, {nome_do_tipo}, "
                "{vencimento}, {valor}, {valor_original}, {juros}, {dias_atraso}"
            )
        )

        acoes = QHBoxLayout()
        acoes.addStretch(1)
        cancelar = widgets.QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        salvar = widgets.QPushButton("Salvar")
        salvar.setObjectName("primario")
        salvar.clicked.connect(self._salvar)
        acoes.addWidget(cancelar)
        acoes.addWidget(salvar)
        layout.addLayout(acoes)

    def _carregar(self) -> None:
        self.nome.setText(self.tipo.nome)
        self.grupo.definir(self.tipo.grupo_id)
        self.periodicidade.definir(self.tipo.periodicidade)
        self.exige.definir(self.tipo.exige_competencia)
        self.ativo.setChecked(self.tipo.ativo)
        self.texto.setPlainText(self.tipo.texto_mensagem)
        self.texto_empresa.setPlainText(self.tipo.texto_mensagem_empresa)
        self.texto_item.setPlainText(self.tipo.texto_item_lista)

    def _salvar(self) -> None:
        def acao():
            servico.salvar_tipo(
                self.contexto.sessao,
                self.tipo,
                nome=self.nome.text(),
                grupo_id=self.grupo.valor(),
                periodicidade=self.periodicidade.valor(),
                exige_competencia=self.exige.valor(),
                texto_mensagem=self.texto.toPlainText().strip(),
                texto_mensagem_empresa=self.texto_empresa.toPlainText().strip(),
                texto_item_lista=self.texto_item.toPlainText().strip(),
                ativo=self.ativo.isChecked(),
            )
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.accept()
