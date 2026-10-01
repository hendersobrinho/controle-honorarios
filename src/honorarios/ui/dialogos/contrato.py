"""Contrato de honorário recorrente e reajuste (individual e em massa)."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QRadioButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
)

from ...dominio.enums import MeioCobranca, Periodicidade
from ...dominio.valores import formatar_moeda, hoje
from ...servicos import contratos as servico
from ...servicos import tipos as servico_tipos
from ..comum import widgets
from ..comum.campos import (
    CampoData,
    CampoDataOpcional,
    CampoMoeda,
    ComboEnum,
    ComboRegistros,
)
from ..comum.seletor_cliente import CampoCliente
from ..comum.tabelas import (
    Coluna,
    ModeloTabelaMarcavel,
    ajustar_colunas,
    coluna_moeda,
    preparar_tabela,
)
from ..contexto import Contexto


class DialogoContrato(QDialog):
    def __init__(self, contexto: Contexto, contrato=None, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.contrato = contrato
        self.setWindowTitle("Editar contrato" if contrato else "Novo contrato recorrente")
        self.resize(600, 560)
        self._montar()
        if contrato:
            self._carregar()

    def _montar(self) -> None:
        sessao = self.contexto.sessao
        layout = QVBoxLayout(self)
        formulario = QFormLayout()
        self.cliente = CampoCliente(sessao)
        formulario.addRow("Cliente:", self.cliente)
        self.tipo = ComboRegistros(
            [
                tipo
                for tipo in servico_tipos.listar_tipos(sessao)
                if tipo.periodicidade is not Periodicidade.AVULSO
            ],
            rotulo=lambda t: f"{t.nome}  ({t.grupo.nome})",
            vazio="— selecione —",
        )
        formulario.addRow("Tipo de honorário:", self.tipo)
        self.valor = CampoMoeda()
        formulario.addRow("Valor:", self.valor)
        self.periodicidade = ComboEnum(
            Periodicidade, Periodicidade.MENSAL, excluir=(Periodicidade.AVULSO,)
        )
        formulario.addRow("Periodicidade:", self.periodicidade)
        self.dia = QSpinBox()
        self.dia.setRange(1, 31)
        self.dia.setValue(10)
        formulario.addRow("Dia do vencimento:", self.dia)
        self.meses_vencimento = QSpinBox()
        self.meses_vencimento.setRange(0, 6)
        self.meses_vencimento.setValue(1)
        self.meses_vencimento.setSuffix(" mês(es) após a competência")
        formulario.addRow("Vence:", self.meses_vencimento)
        self.meses_referencia = QLineEdit()
        self.meses_referencia.setPlaceholderText("Ex.: 1,4,7,10 — em branco usa a periodicidade")
        formulario.addRow("Gerar nos meses:", self.meses_referencia)
        self.meio = ComboEnum(MeioCobranca, MeioCobranca.BOLETO)
        formulario.addRow("Boleto ou Pix:", self.meio)
        self.forma_envio = ComboRegistros(
            servico_tipos.listar_formas(sessao), rotulo=lambda f: f.nome, vazio="— não informado —"
        )
        formulario.addRow("Forma de envio:", self.forma_envio)
        self.vigencia_inicio = CampoData(hoje())
        formulario.addRow("Vigência a partir de:", self.vigencia_inicio)
        self.vigencia_fim = CampoDataOpcional(None)
        formulario.addRow("Vigência até:", self.vigencia_fim)
        self.suspenso = QCheckBox("Suspenso temporariamente (não gera competência)")
        formulario.addRow("", self.suspenso)
        self.observacoes = QPlainTextEdit()
        self.observacoes.setMaximumHeight(70)
        formulario.addRow("Observações:", self.observacoes)
        layout.addLayout(formulario)

        self.nota = widgets.rotulo_fraco(
            "Mudança de valor é reajuste e passa pelo botão Reajustar, "
            "para guardar o histórico e valer só daqui para frente."
        )
        layout.addWidget(self.nota)
        layout.addStretch(1)

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
        contrato = self.contrato
        self.cliente.definir(contrato.cliente_id)
        self.cliente.setEnabled(False)
        self.tipo.definir(contrato.tipo_id)
        self.valor.definir(contrato.valor)
        self.valor.setEnabled(False)
        self.periodicidade.definir(contrato.periodicidade)
        self.dia.setValue(contrato.dia_vencimento)
        self.meses_vencimento.setValue(contrato.meses_vencimento)
        self.meses_referencia.setText(contrato.meses_referencia)
        self.meio.definir(contrato.meio)
        self.forma_envio.definir(contrato.forma_envio_id)
        self.vigencia_inicio.definir(contrato.vigencia_inicio)
        self.vigencia_fim.definir(contrato.vigencia_fim)
        self.suspenso.setChecked(contrato.suspenso)
        self.observacoes.setPlainText(contrato.observacoes)

    def _salvar(self) -> None:
        if self.cliente.valor() is None or self.tipo.valor() is None:
            widgets.aviso(self, "Selecione o cliente e o tipo de honorário.")
            return
        dados = servico.DadosContrato(
            cliente_id=self.cliente.valor(),
            tipo_id=self.tipo.valor(),
            valor=(
                self.valor.valor()
                if self.contrato is None
                else Decimal(str(self.contrato.valor))
            ),
            periodicidade=self.periodicidade.valor(),
            dia_vencimento=self.dia.value(),
            meses_vencimento=self.meses_vencimento.value(),
            meses_referencia=self.meses_referencia.text(),
            forma_envio_id=self.forma_envio.valor(),
            meio=self.meio.valor(),
            vigencia_inicio=self.vigencia_inicio.valor(),
            vigencia_fim=self.vigencia_fim.valor(),
            suspenso=self.suspenso.isChecked(),
            observacoes=self.observacoes.toPlainText(),
        )

        def acao():
            if self.contrato is None:
                self.contrato = servico.criar(self.contexto.sessao, dados)
            else:
                servico.atualizar(self.contexto.sessao, self.contrato, dados)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.accept()


class DialogoReajuste(QDialog):
    """Reajuste de um contrato só."""

    def __init__(self, contexto: Contexto, contrato, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.contrato = contrato
        self.setWindowTitle("Reajustar honorário")
        self.resize(480, 300)
        layout = QVBoxLayout(self)
        layout.addWidget(
            widgets.Cabecalho(
                contrato.cliente.nome,
                f"{contrato.tipo.nome} · valor atual {formatar_moeda(contrato.valor)}",
            )
        )
        formulario = QFormLayout()
        self.valor = CampoMoeda(contrato.valor)
        formulario.addRow("Novo valor:", self.valor)
        self.vigencia = CampoData(hoje())
        formulario.addRow("Vale a partir de:", self.vigencia)
        self.motivo = QPlainTextEdit()
        self.motivo.setMaximumHeight(70)
        formulario.addRow("Motivo:", self.motivo)
        layout.addLayout(formulario)
        layout.addWidget(
            widgets.rotulo_fraco(
                "As competências já geradas continuam com o valor antigo."
            )
        )
        layout.addStretch(1)
        acoes = QHBoxLayout()
        acoes.addStretch(1)
        cancelar = widgets.QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        confirmar = widgets.QPushButton("Reajustar")
        confirmar.setObjectName("primario")
        confirmar.clicked.connect(self._confirmar)
        acoes.addWidget(cancelar)
        acoes.addWidget(confirmar)
        layout.addLayout(acoes)

    def _confirmar(self) -> None:
        def acao():
            servico.reajustar(
                self.contexto.sessao,
                self.contrato,
                self.valor.valor(),
                self.vigencia.valor(),
                self.motivo.toPlainText().strip(),
            )
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.accept()


class DialogoReajusteEmMassa(QDialog):
    """Reajuste de vários contratos, sempre com prévia antes de aplicar."""

    def __init__(self, contexto: Contexto, contratos, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.contratos = list(contratos)
        self.setWindowTitle("Reajuste em massa")
        self.resize(760, 600)
        layout = QVBoxLayout(self)
        layout.addWidget(
            widgets.Cabecalho(
                "Reajuste em massa", f"{len(self.contratos)} contrato(s) selecionado(s)"
            )
        )

        grupo = QGroupBox("Como reajustar")
        caixa = QVBoxLayout(grupo)
        linha = QHBoxLayout()
        self.por_percentual = QRadioButton("Percentual")
        self.por_percentual.setChecked(True)
        self.por_percentual.toggled.connect(self._calcular)
        self.percentual = CampoMoeda(0)
        self.percentual.setPrefix("")
        self.percentual.setSuffix(" %")
        self.percentual.valueChanged.connect(self._calcular)
        self.por_valor = QRadioButton("Valor fixo")
        self.por_valor.toggled.connect(self._calcular)
        self.valor_fixo = CampoMoeda(0)
        self.valor_fixo.valueChanged.connect(self._calcular)
        for widget in (self.por_percentual, self.percentual, self.por_valor, self.valor_fixo):
            linha.addWidget(widget)
        linha.addStretch(1)
        caixa.addLayout(linha)
        formulario = QFormLayout()
        self.vigencia = CampoData(hoje())
        formulario.addRow("Vale a partir de:", self.vigencia)
        self.motivo = QLineEdit("Reajuste anual")
        formulario.addRow("Motivo:", self.motivo)
        caixa.addLayout(formulario)
        layout.addWidget(grupo)

        self.modelo = ModeloTabelaMarcavel(
            [
                Coluna("", lambda item: "", largura=28),
                Coluna("Cliente", lambda item: item.contrato.cliente.nome),
                Coluna("Tipo", lambda item: item.contrato.tipo.nome),
                coluna_moeda("Valor atual", lambda item: item.valor_atual),
                coluna_moeda("Novo valor", lambda item: item.valor_novo, negrito=True),
                coluna_moeda(
                    "Diferença", lambda item: item.valor_novo - item.valor_atual
                ),
            ]
        )
        self.tabela = preparar_tabela(QTableView(), esticar=1)
        self.tabela.setModel(self.modelo)
        self.tabela.setSortingEnabled(False)
        layout.addWidget(self.tabela, 1)

        self.resumo = widgets.rotulo_fraco("")
        layout.addWidget(self.resumo)

        acoes = QHBoxLayout()
        acoes.addStretch(1)
        cancelar = widgets.QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        aplicar = widgets.QPushButton("Aplicar reajuste")
        aplicar.setObjectName("primario")
        aplicar.clicked.connect(self._aplicar)
        acoes.addWidget(cancelar)
        acoes.addWidget(aplicar)
        layout.addLayout(acoes)
        self._calcular()

    def _calcular(self) -> None:
        percentual = self.percentual.valor() if self.por_percentual.isChecked() else None
        valor_fixo = self.valor_fixo.valor() if self.por_valor.isChecked() else None
        self.percentual.setEnabled(self.por_percentual.isChecked())
        self.valor_fixo.setEnabled(self.por_valor.isChecked())
        try:
            itens = servico.previa_reajuste(
                self.contratos, percentual=percentual, valor_fixo=valor_fixo
            )
        except Exception:  # noqa: BLE001
            itens = []
        self.modelo.definir_itens(itens)
        ajustar_colunas(self.tabela, self.modelo.colunas)
        total = sum((item.valor_novo - item.valor_atual for item in itens), start=Decimal("0.00"))
        self.resumo.setText(
            f"{len(itens)} contrato(s) · diferença mensal total de {formatar_moeda(total)}"
        )

    def _aplicar(self) -> None:
        marcados = self.modelo.marcados()
        if not marcados:
            widgets.aviso(self, "Marque os contratos que quer reajustar.")
            return
        total = sum(
            (item.valor_novo - item.valor_atual for item in marcados), start=Decimal("0.00")
        )
        if not widgets.confirmar(
            self,
            f"Aplicar reajuste em {len(marcados)} contrato(s)?",
            "Reajuste em massa",
            f"Diferença mensal total: {formatar_moeda(total)}. "
            f"Vigência a partir de {self.vigencia.valor():%d/%m/%Y}.",
        ):
            return

        def acao():
            servico.aplicar_reajuste(
                self.contexto.sessao, marcados, self.vigencia.valor(), self.motivo.text()
            )
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.accept()
