"""Cadastro de tipo de honorário: o que se cobra e como aparece na mensagem.

A tela mostra, enquanto se digita, a frase como ela vai sair na cobrança — é o
jeito de entender o que cada um dos três textos faz sem ler manual.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ...dominio import mensagens as dominio_mensagens
from ...dominio.enums import ExigeCompetencia, Periodicidade
from ...servicos import tipos as servico
from ..comum import widgets
from ..comum.campos import ComboEnum, ComboRegistros
from ..contexto import Contexto

# textos prontos para cada tipo de competência
MODELOS = {
    ExigeCompetencia.MES: (
        dominio_mensagens.TEXTO_MENSAL,
        dominio_mensagens.TEXTO_MENSAL_EMPRESA,
        dominio_mensagens.TEXTO_MENSAL_ITEM,
    ),
    ExigeCompetencia.ANO: (
        dominio_mensagens.TEXTO_IRPF,
        dominio_mensagens.TEXTO_IRPF_EMPRESA,
        dominio_mensagens.TEXTO_IRPF_ITEM,
    ),
    ExigeCompetencia.NENHUMA: (
        dominio_mensagens.TEXTO_AVULSO,
        dominio_mensagens.TEXTO_AVULSO_EMPRESA,
        dominio_mensagens.TEXTO_AVULSO_ITEM,
    ),
}

EXPLICA_COMPETENCIA = {
    ExigeCompetencia.MES: "Cada lançamento é de um mês: 08/2026. Para mensais e trimestrais.",
    ExigeCompetencia.ANO: "Cada lançamento é de um ano: IRPF 2026. Para imposto de renda.",
    ExigeCompetencia.NENHUMA: (
        "Serviço pontual, sem mês nem ano: descreve-se o serviço no lançamento. "
        "Para alteração contratual, ata, certificado…"
    ),
}


class DialogoTipo(QDialog):
    def __init__(self, contexto: Contexto, tipo=None, grupo_id: int | None = None, parent=None):
        super().__init__(parent)
        self.contexto = contexto
        self.tipo = tipo
        self._ultimo_campo: QLineEdit | None = None
        self.setWindowTitle("Editar tipo de honorário" if tipo else "Novo tipo de honorário")
        self.resize(760, 640)
        self._montar()
        if tipo:
            self._carregar()
        elif grupo_id:
            self.grupo.definir(grupo_id)
        self._ajustar_competencia()
        self._atualizar_previa()

    # ------------------------------------------------------------------ layout
    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        grupo_basico = QGroupBox("O que se cobra")
        formulario = QFormLayout(grupo_basico)
        self.nome = QLineEdit()
        self.nome.setPlaceholderText("Ex.: Honorário mensal, Alteração contratual, IRPF")
        self.nome.textChanged.connect(lambda *_: self._atualizar_previa())
        formulario.addRow("Nome:", self.nome)
        self.grupo = ComboRegistros(
            servico.listar_grupos(self.contexto.sessao), rotulo=lambda g: g.nome
        )
        formulario.addRow("Aparece no grupo:", self.grupo)
        self.periodicidade = ComboEnum(Periodicidade, Periodicidade.MENSAL)
        formulario.addRow("Periodicidade:", self.periodicidade)
        self.exige = ComboEnum(ExigeCompetencia, ExigeCompetencia.MES)
        self.exige.currentIndexChanged.connect(self._ajustar_competencia)
        formulario.addRow("Competência:", self.exige)
        self.explicacao = widgets.rotulo_fraco("")
        formulario.addRow("", self.explicacao)
        self.ativo = QCheckBox("Ativo (aparece para novos lançamentos)")
        self.ativo.setChecked(True)
        formulario.addRow("", self.ativo)
        layout.addWidget(grupo_basico)

        grupo_textos = QGroupBox("Como aparece na mensagem de cobrança")
        grade = QGridLayout(grupo_textos)
        grade.setVerticalSpacing(4)
        grade.setColumnStretch(1, 1)

        self.texto = QLineEdit()
        self.texto_empresa = QLineEdit()
        self.texto_item = QLineEdit()
        self.previas: list[QLabel] = []
        linhas = (
            (self.texto, "Cobrança de um honorário",
             "Usado quando a mensagem cobra só este honorário."),
            (self.texto_empresa, "Citando a empresa",
             "Usado quando você marca \"citar o nome da empresa\"."),
            (self.texto_item, "Numa lista",
             "Usado quando a mensagem cobra vários honorários de uma vez."),
        )
        posicao = 0
        for campo, titulo, ajuda in linhas:
            rotulo = QLabel(f"<b>{titulo}</b>")
            grade.addWidget(rotulo, posicao, 0, 1, 2)
            grade.addWidget(widgets.rotulo_fraco(ajuda), posicao + 1, 0, 1, 2)
            campo.textChanged.connect(lambda *_: self._atualizar_previa())
            campo.installEventFilter(self)
            grade.addWidget(campo, posicao + 2, 0, 1, 2)
            previa = QLabel("")
            previa.setObjectName("previaMensagem")
            previa.setWordWrap(True)
            previa.setMinimumHeight(32)
            previa.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grade.addWidget(previa, posicao + 3, 0, 1, 2)
            grade.setRowMinimumHeight(posicao + 4, 10)   # respiro entre os blocos
            self.previas.append(previa)
            posicao += 5

        chips = QHBoxLayout()
        chips.addWidget(widgets.rotulo_fraco("Inserir:"))
        for variavel, descricao in servico.VARIAVEIS_DO_TIPO:
            botao = QPushButton(descricao)
            botao.setObjectName("cartaoAcao")
            botao.setToolTip(f"Insere {{{variavel}}} no texto em que está o cursor")
            # sem foco: o cursor continua no campo de texto que se está editando
            botao.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            botao.clicked.connect(lambda _=False, nome=variavel: self._inserir(nome))
            chips.addWidget(botao)
        chips.addStretch(1)
        grade.addLayout(chips, posicao, 0, 1, 2)

        restaurar = QPushButton("Usar os textos padrão deste tipo de competência")
        restaurar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        restaurar.clicked.connect(self._usar_padrao)
        grade.addWidget(restaurar, posicao + 1, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(grupo_textos, 1)

        acoes = QHBoxLayout()
        acoes.addStretch(1)
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        salvar = QPushButton("Salvar")
        salvar.setObjectName("primario")
        salvar.setShortcut("Ctrl+S")
        salvar.clicked.connect(self._salvar)
        acoes.addWidget(cancelar)
        acoes.addWidget(salvar)
        layout.addLayout(acoes)

    # ------------------------------------------------------------------ apoio
    def eventFilter(self, objeto, evento):  # noqa: N802
        if isinstance(objeto, QLineEdit) and evento.type() == evento.Type.FocusIn:
            self._ultimo_campo = objeto
        return super().eventFilter(objeto, evento)

    def _inserir(self, variavel: str) -> None:
        campo = self._ultimo_campo or self.texto
        campo.insert(f"{{{variavel}}}")
        campo.setFocus()

    def _ajustar_competencia(self) -> None:
        exige = self.exige.valor()
        self.explicacao.setText(EXPLICA_COMPETENCIA.get(exige, ""))
        # tipo novo sem texto: já vem com o padrão da competência escolhida
        if self.tipo is None and not any(
            campo.text().strip() for campo in (self.texto, self.texto_empresa, self.texto_item)
        ):
            self._usar_padrao()
        self._atualizar_previa()

    def _usar_padrao(self) -> None:
        textos = MODELOS.get(self.exige.valor(), MODELOS[ExigeCompetencia.MES])
        self.texto.setText(textos[0])
        self.texto_empresa.setText(textos[1])
        self.texto_item.setText(textos[2])

    def _atualizar_previa(self) -> None:
        um, empresa, item = servico.previa_dos_textos(
            self.nome.text().strip(),
            self.exige.valor(),
            self.texto.text(),
            self.texto_empresa.text(),
            self.texto_item.text(),
        )
        frases = (
            f"Consta em aberto o <b>{um}</b>, com vencimento em 08/09/2026.",
            f"Consta em aberto o <b>{empresa}</b>, com vencimento em 08/09/2026.",
            f"• <b>{item}</b>",
        )
        for previa, frase in zip(self.previas, frases, strict=True):
            aviso = "⚠" in frase
            previa.setText(("" if aviso else "→ ") + frase)
            previa.setProperty("erro", aviso)
            previa.style().unpolish(previa)
            previa.style().polish(previa)

    def _carregar(self) -> None:
        self.nome.setText(self.tipo.nome)
        self.grupo.definir(self.tipo.grupo_id)
        self.periodicidade.definir(self.tipo.periodicidade)
        self.exige.definir(self.tipo.exige_competencia)
        self.ativo.setChecked(self.tipo.ativo)
        self.texto.setText(self.tipo.texto_mensagem)
        self.texto_empresa.setText(self.tipo.texto_mensagem_empresa)
        self.texto_item.setText(self.tipo.texto_item_lista)

    def _salvar(self) -> None:
        def acao():
            self.tipo = servico.salvar_tipo(
                self.contexto.sessao,
                self.tipo,
                nome=self.nome.text(),
                grupo_id=self.grupo.valor(),
                periodicidade=self.periodicidade.valor(),
                exige_competencia=self.exige.valor(),
                texto_mensagem=self.texto.text().strip(),
                texto_mensagem_empresa=self.texto_empresa.text().strip(),
                texto_item_lista=self.texto_item.text().strip(),
                ativo=self.ativo.isChecked(),
            )
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.accept()


class DialogoGrupo(QDialog):
    """Nome do grupo e se é o grupo de Imposto de Renda."""

    def __init__(self, contexto: Contexto, grupo=None, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.grupo = grupo
        self.setWindowTitle("Editar grupo" if grupo else "Novo grupo")
        self.resize(520, 260)
        layout = QVBoxLayout(self)
        formulario = QFormLayout()
        self.nome = QLineEdit(grupo.nome if grupo else "")
        self.nome.setPlaceholderText("Ex.: Mensais, Imposto de Renda, Serviços avulsos")
        formulario.addRow("Nome:", self.nome)
        self.imposto_de_renda = QCheckBox("Este é o grupo de Imposto de Renda")
        self.imposto_de_renda.setChecked(bool(grupo and grupo.imposto_de_renda))
        formulario.addRow("", self.imposto_de_renda)
        layout.addLayout(formulario)
        layout.addWidget(
            widgets.rotulo_fraco(
                "O grupo é a seção em que os honorários aparecem nas telas de cobrança. "
                "Clientes que só têm honorários do grupo de Imposto de Renda vão para a "
                "tela Imposto de Renda, separados dos demais. Só um grupo pode ter essa "
                "marcação."
            )
        )
        layout.addStretch(1)
        acoes = QHBoxLayout()
        acoes.addStretch(1)
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        salvar = QPushButton("Salvar")
        salvar.setObjectName("primario")
        salvar.clicked.connect(self._salvar)
        acoes.addWidget(cancelar)
        acoes.addWidget(salvar)
        layout.addLayout(acoes)

    def _salvar(self) -> None:
        def acao():
            self.grupo = servico.salvar_grupo(
                self.contexto.sessao,
                self.grupo,
                self.nome.text(),
                self.imposto_de_renda.isChecked(),
            )
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.accept()


__all__ = ["DialogoGrupo", "DialogoTipo", "QApplication"]
