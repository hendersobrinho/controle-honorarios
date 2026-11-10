"""Lançamento e edição de um honorário (usado nos avulsos e na ficha)."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...dominio.enums import ExigeCompetencia, MeioCobranca, SituacaoEnvio
from ...dominio.valores import Competencia, formatar_data, formatar_moeda, hoje
from ...servicos import calculo
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
        self.resize(620, 640)
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
        self.juros_linha = self._montar_juros()
        formulario.addRow("Juros:", self.juros_linha)
        self.juros_conta = widgets.rotulo_fraco("")
        self.juros_conta.setWordWrap(True)
        formulario.addRow("", self.juros_conta)
        self.total_hoje = QLabel()
        self.total_hoje.setObjectName("cartaoValor")
        formulario.addRow("Total de hoje:", self.total_hoje)
        # só o honorário em aberto tem juros correndo para acertar
        # (só esconder: setVisible(True) num widget ainda sem pai abriria uma janelinha)
        if not (self.honorario is not None and self.honorario.status.cobravel):
            for campo in (self.juros_linha, self.juros_conta, self.total_hoje):
                campo.hide()
                rotulo = formulario.labelForField(campo)
                if rotulo is not None:
                    rotulo.hide()
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

    # ------------------------------------------------------------------ juros
    def _montar_juros(self) -> QWidget:
        """O juros de hoje, para acertar à mão (o inteiro ou só os centavos)."""
        self._juros_manual = False   # o campo vale no lugar do calculado
        self._juros_mexido = False   # a pessoa mexeu no juros nesta janela
        linha = QWidget()
        caixa = QHBoxLayout(linha)
        caixa.setContentsMargins(0, 0, 0, 0)
        self.juros = CampoMoeda()
        self.juros.setPrefix("R$ ")
        self.juros.setToolTip(
            "O juros de hoje. Digite outro valor para acertar: ele passa a valer no lugar "
            "do calculado, e os próximos dias continuam somando por cima dele."
        )
        self.juros.textEdited.connect(self._digitou_juros)
        self.juros.valueChanged.connect(lambda *_: self._mostrar_juros())
        caixa.addWidget(self.juros, 1)
        self.botao_por_dia = widgets.QPushButton("Por dia…")
        self.botao_por_dia.setObjectName("linkFiltro")
        self.botao_por_dia.setToolTip("Informar o juros por dia: o sistema multiplica pelos "
                                      "dias de atraso e põe o total aqui")
        self.botao_por_dia.clicked.connect(self._juros_por_dia)
        caixa.addWidget(self.botao_por_dia)
        self.botao_calculado = widgets.QPushButton("Voltar ao calculado")
        self.botao_calculado.setObjectName("linkFiltro")
        self.botao_calculado.clicked.connect(self._voltar_ao_calculado)
        caixa.addWidget(self.botao_calculado)
        self.valor.valueChanged.connect(lambda *_: self._seguir_calculado())
        self.vencimento.dateChanged.connect(lambda *_: self._seguir_calculado())
        return linha

    def _referencia(self):
        # hoje de verdade: o acerto vale a partir do dia em que foi digitado, mesmo
        # com a tela simulando outra data para os juros
        return hoje()

    def _calculado(self) -> Decimal:
        if self.honorario is None or not self.honorario.status.cobravel:
            return Decimal(0)
        return calculo.juros_calculado(
            self.honorario, self._referencia(), self.valor.valor(), self.vencimento.valor()
        )

    def _carregar_juros(self) -> None:
        atual = calculo.atualizar(self.honorario, self._referencia())
        self._juros_manual = atual.juros_manual
        self.juros.definir(atual.juros)
        self._mostrar_juros()

    def _digitou_juros(self, *_):
        self._juros_mexido = True
        self._juros_manual = True
        self._mostrar_juros()

    def _seguir_calculado(self) -> None:
        """Mudou valor ou vencimento: o juros acompanha, se não foi acertado à mão."""
        calculado = self._calculado()
        if not self._juros_manual:
            self.juros.blockSignals(True)   # o _mostrar_juros abaixo já atualiza
            self.juros.definir(calculado)
            self.juros.blockSignals(False)
        self._mostrar_juros(calculado)

    def _dias_de_atraso(self) -> int:
        from ...dominio.juros import dias_em_atraso

        return dias_em_atraso(self.vencimento.valor(), self._referencia())

    def _taxa_dia(self) -> Decimal:
        cliente = self.honorario.cliente if self.honorario is not None else None
        return calculo.taxa_vigente_em(cliente, self._referencia()) if cliente else Decimal(0)

    def _juros_por_dia(self) -> None:
        from ..comum.juros_por_dia import DialogoJurosPorDia

        dialogo = DialogoJurosPorDia(self._dias_de_atraso(), self._taxa_dia(), self)
        if dialogo.exec() and dialogo.total is not None:
            self._juros_mexido = True
            self._juros_manual = True
            self.juros.definir(dialogo.total)
            self._mostrar_juros()

    def _voltar_ao_calculado(self) -> None:
        self._juros_mexido = True
        self._juros_manual = False
        self.juros.definir(self._calculado())
        self._mostrar_juros()

    def _mostrar_juros(self, calculado: Decimal | None = None) -> None:
        if self.honorario is None or not self.honorario.status.cobravel:
            return
        if calculado is None:
            calculado = self._calculado()
        manual = self._juros_manual and self.juros.valor() != calculado
        self.botao_calculado.setVisible(manual)
        referencia = formatar_data(self._referencia())
        if manual:
            from ..comum.juros_por_dia import aviso_do_dia

            self.juros_conta.setText(
                aviso_do_dia(self.juros.valor(), self._dias_de_atraso(), self._taxa_dia())
                or f"✎ Acertado à mão (é o juros inteiro, não o de um dia) — o cálculo dá "
                f"{formatar_moeda(calculado)} em {referencia}. Daqui para a frente, os dias "
                "de atraso continuam somando por cima."
            )
        elif calculado:
            self.juros_conta.setText(f"Calculado em {referencia}. Digite outro valor para "
                                     "acertar (o inteiro ou só os centavos).")
        else:
            self.juros_conta.setText("No prazo: sem juros por enquanto.")
        pago = self.honorario.valor_original - self.honorario.saldo_aberto
        saldo = max(Decimal(0), self.valor.valor() - pago)
        self.total_hoje.setText(formatar_moeda(saldo + self.juros.valor()))

    def _gravar_juros(self) -> None:
        """Só grava se a pessoa mexeu no juros: abrir e salvar não mexe no acerto."""
        if not self._juros_mexido or not self.honorario.status.cobravel:
            return
        manual = self._juros_manual and self.juros.valor() != self._calculado()
        servico.ajustar_juros(self.contexto.sessao, self.honorario,
                              self.juros.valor() if manual else None, self._referencia())

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
        if honorario.status.cobravel:
            self._carregar_juros()

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
                self._gravar_juros()
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.accept()
        if cobrar:
            from .cobrar import cobrar_honorarios

            cobrar_honorarios(self.parentWidget(), self.contexto, [self.honorario])
