"""Lançamento e edição de um honorário (usado nos avulsos e na ficha)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

from ...dominio.enums import ExigeCompetencia, MeioCobranca, SituacaoEnvio
from ...dominio.valores import Competencia, hoje
from ...servicos import honorarios as servico
from ...servicos import tipos as servico_tipos
from ..comum import widgets
from ..comum.campos import (
    CampoData,
    CampoMoeda,
    ComboEnum,
    ComboRegistros,
)
from ..comum.seletor_cliente import CampoCliente
from ..contexto import Contexto


class DialogoHonorario(QDialog):
    def __init__(self, contexto: Contexto, honorario=None, cliente=None, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.honorario = honorario
        self.setWindowTitle("Editar honorário" if honorario else "Novo honorário")
        self.resize(620, 560)
        self._montar(cliente)
        if honorario:
            self._carregar()

    def _montar(self, cliente_inicial) -> None:
        sessao = self.contexto.sessao
        layout = QVBoxLayout(self)
        formulario = QFormLayout()

        self.cliente = CampoCliente(sessao)
        if cliente_inicial is not None:
            self.cliente.definir(cliente_inicial.id)
        formulario.addRow("Cliente:", self.cliente)

        self.tipo = ComboRegistros(
            servico_tipos.listar_tipos(sessao),
            rotulo=lambda t: f"{t.nome}  ({t.grupo.nome})",
            vazio="— selecione —",
        )
        self.tipo.currentIndexChanged.connect(self._ajustar_competencia)
        formulario.addRow("Tipo de honorário:", self.tipo)

        self.competencia = QLineEdit()
        self.competencia.setPlaceholderText("mm/aaaa, ou só o ano para IRPF")
        formulario.addRow("Competência:", self.competencia)

        self.descricao = QLineEdit()
        self.descricao.setPlaceholderText("Ex.: Alteração contratual – mudança de sócio")
        formulario.addRow("Descrição:", self.descricao)

        self.valor = CampoMoeda()
        formulario.addRow("Valor:", self.valor)
        self.vencimento = CampoData(hoje())
        formulario.addRow("Vencimento:", self.vencimento)
        self.meio = ComboEnum(MeioCobranca, MeioCobranca.BOLETO)
        formulario.addRow("Boleto ou Pix:", self.meio)
        self.forma_envio = ComboRegistros(
            servico_tipos.listar_formas(sessao), rotulo=lambda f: f.nome, vazio="— não informado —"
        )
        formulario.addRow("Forma de envio:", self.forma_envio)
        self.situacao_envio = ComboEnum(SituacaoEnvio, SituacaoEnvio.NAO_ENVIADO)
        formulario.addRow("Situação do envio:", self.situacao_envio)
        self.numero_boleto = QLineEdit()
        formulario.addRow("Nº do boleto:", self.numero_boleto)
        self.observacoes = QPlainTextEdit()
        self.observacoes.setMaximumHeight(70)
        formulario.addRow("Observações:", self.observacoes)
        layout.addLayout(formulario)

        self.dica = widgets.rotulo_fraco("")
        layout.addWidget(self.dica)
        layout.addStretch(1)

        acoes = QHBoxLayout()
        acoes.addStretch(1)
        cancelar = widgets.QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        salvar = widgets.QPushButton("Salvar")
        salvar.setObjectName("primario")
        salvar.setShortcut("Ctrl+S")
        salvar.clicked.connect(lambda: self._salvar())
        acoes.addWidget(cancelar)
        if self.honorario is None or self.honorario.status.cobravel:
            # cobrar daqui mesmo, sem ir até Atrasados ou A vencer
            salvar_cobrar = widgets.QPushButton("Salvar e cobrar")
            salvar_cobrar.setShortcut("Ctrl+B")
            salvar_cobrar.setToolTip("Salva e já abre a mensagem de cobrança (Ctrl+B)")
            salvar_cobrar.clicked.connect(lambda: self._salvar(cobrar=True))
            acoes.addWidget(salvar_cobrar)
        acoes.addWidget(salvar)
        layout.addLayout(acoes)
        self._ajustar_competencia()

    def _tipo_atual(self):
        from ...infra.modelos import TipoHonorario

        identificador = self.tipo.valor()
        if identificador is None:
            return None
        return self.contexto.sessao.get(TipoHonorario, identificador)

    def _ajustar_competencia(self) -> None:
        tipo = self._tipo_atual()
        if tipo is None:
            self.dica.setText("")
            return
        if tipo.exige_competencia is ExigeCompetencia.MES:
            self.competencia.setEnabled(True)
            self.competencia.setPlaceholderText("mm/aaaa")
            self.dica.setText("Este tipo exige competência mensal (ex.: 08/2026).")
        elif tipo.exige_competencia is ExigeCompetencia.ANO:
            self.competencia.setEnabled(True)
            self.competencia.setPlaceholderText("aaaa")
            self.dica.setText("Este tipo usa só o ano (ex.: 2026, que vira \"IRPF 2026\").")
        else:
            self.competencia.setEnabled(False)
            self.competencia.clear()
            self.dica.setText("Serviço avulso: descreva o serviço no campo Descrição.")

    def _carregar(self) -> None:
        honorario = self.honorario
        self.cliente.definir(honorario.cliente_id)
        self.cliente.setEnabled(False)
        self.tipo.definir(honorario.tipo_id)
        competencia = Competencia(honorario.competencia_ano, honorario.competencia_mes)
        self.competencia.setText(competencia.rotulo())
        self.descricao.setText(honorario.descricao)
        self.valor.definir(honorario.valor_original)
        self.vencimento.definir(honorario.vencimento)
        self.meio.definir(honorario.meio)
        self.forma_envio.definir(honorario.forma_envio_id)
        self.situacao_envio.definir(honorario.situacao_envio)
        self.numero_boleto.setText(honorario.numero_boleto)
        self.observacoes.setPlainText(honorario.observacoes)

    def _dados(self) -> servico.DadosHonorario:
        competencia = Competencia.de_texto(self.competencia.text())
        return servico.DadosHonorario(
            cliente_id=self.cliente.valor(),
            tipo_id=self.tipo.valor(),
            valor=self.valor.valor(),
            vencimento=self.vencimento.valor(),
            competencia=competencia,
            descricao=self.descricao.text(),
            meio=self.meio.valor(),
            forma_envio_id=self.forma_envio.valor(),
            situacao_envio=self.situacao_envio.valor(),
            enviado_em=hoje() if self.situacao_envio.valor() is SituacaoEnvio.ENVIADO else None,
            numero_boleto=self.numero_boleto.text(),
            observacoes=self.observacoes.toPlainText(),
        )

    def _salvar(self, cobrar: bool = False) -> None:
        if self.cliente.valor() is None:
            widgets.aviso(self, "Selecione o cliente.")
            return
        if self.tipo.valor() is None:
            widgets.aviso(self, "Selecione o tipo de honorário.")
            return
        dados = self._dados()

        def acao():
            if self.honorario is None:
                self.honorario = servico.criar(self.contexto.sessao, dados)
            else:
                servico.atualizar(self.contexto.sessao, self.honorario, dados)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.accept()
        if cobrar:
            from .cobrar import cobrar_honorarios

            cobrar_honorarios(self.parentWidget(), self.contexto, [self.honorario])
