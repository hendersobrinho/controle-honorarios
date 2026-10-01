"""As três telas de honorários: atrasados, a vencer e pagos.

Cada situação tem a sua tela, com só os filtros e botões que fazem sentido para
ela — em vez de uma tela única com alternância e filtros que valem para uma
situação e não para outra. Cada honorário é um cartão com faixa colorida e
botão para o histórico.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from ...dominio.enums import StatusPagamento, TipoPessoa
from ...dominio.valores import ZERO, formatar_data, formatar_moeda, hoje, somar_meses
from ...servicos import cobrancas as servico_cobrancas
from ...servicos import honorarios as servico
from ...servicos import tipos as servico_tipos
from ...servicos.honorarios import Filtro, LinhaHonorario
from ..comum import cores, tema, widgets
from ..comum.campos import CampoBusca, CampoData, ComboEnum, ComboRegistros
from ..comum.cartoes import Acao, DadosCartao, DataCartao, PainelDeCartoes, SecaoCartoes
from ..contexto import Contexto
from ..dialogos.cobrar import DialogoCobrar
from ..dialogos.ficha import DialogoFicha
from ..dialogos.historico import DialogoHistorico
from ..dialogos.pagamento import DialogoPagamento
from ..dialogos.renegociacao import DialogoRenegociacao

# --------------------------------------------------------------------- cartões


def etiqueta_de_situacao(linha: LinhaHonorario, dias_em_breve: int = 5) -> str:
    """Frase curta que explica a cor da faixa do cartão."""
    atualizacao = linha.atualizacao
    if linha.cobranca_suspensa and atualizacao.status is StatusPagamento.EM_ABERTO:
        return "Cobrança suspensa"
    if atualizacao.status is StatusPagamento.PAGO:
        pago_em = linha.honorario.pago_em
        return f"Pago em {formatar_data(pago_em)}" if pago_em else "Pago"
    if atualizacao.status in (StatusPagamento.CANCELADO, StatusPagamento.RENEGOCIADO):
        return atualizacao.status.rotulo
    if linha.promessa_vencida:
        return "Promessa vencida"  # a data está na pílula da promessa
    if atualizacao.dias_atraso > 0:
        return f"Em atraso há {atualizacao.dias_atraso} dia(s)"
    # mesma data do cálculo (a de referência da tela), não o relógio: senão a
    # simulação de data mostraria juros de um dia e etiqueta de outro
    falta = (linha.honorario.vencimento - atualizacao.data_referencia).days
    if falta <= 0:
        return "Vence hoje"
    if 0 < falta <= dias_em_breve:
        return f"Vence em {falta} dia(s)"
    if linha.promessa:
        return f"Promessa para {formatar_data(linha.promessa)}"
    return "No prazo"


def _descricao(honorario) -> str:
    """Tipo e competência, sem repetir o nome quando a competência já o traz."""
    competencia = honorario.competencia_rotulo or honorario.descricao or "sem competência"
    if competencia.startswith(honorario.tipo.nome):
        return competencia
    return f"{honorario.tipo.nome} · {competencia}"


def datas_do_honorario(
    linha: LinhaHonorario, cor_situacao, dias_em_breve: int = 5
) -> list[DataCartao]:
    """As datas que contam a história do honorário em aberto, para bater o olho."""
    honorario = linha.honorario
    referencia = linha.atualizacao.data_referencia
    falta = (honorario.vencimento - referencia).days
    if falta < 0:
        rotulo = "Venceu"
    elif falta == 0:
        rotulo = "Vence hoje"
    else:
        rotulo = "Vence"
    atrasado_ou_perto = linha.atualizacao.dias_atraso > 0 or falta <= dias_em_breve
    datas = [
        DataCartao(
            rotulo,
            formatar_data(honorario.vencimento),
            cor_situacao if atrasado_ou_perto else None,
        ),
        DataCartao(
            "Última cobrança",
            formatar_data(linha.ultima_cobranca) if linha.ultima_cobranca else "nunca",
        ),
    ]
    if linha.promessa:
        cor = tema.cor("atrasado" if linha.promessa_vencida else "roxo", cores.tema_atual())
        datas.append(DataCartao("Promessa", formatar_data(linha.promessa), cor))
    return datas


def cartao_de_honorario(
    linha: LinhaHonorario, acoes: list[Acao], dias_em_breve: int = 5
) -> DadosCartao:
    """Cartão de honorário em aberto (atrasado ou a vencer)."""
    atualizacao = linha.atualizacao
    detalhes = []
    if atualizacao.juros:
        detalhes += [
            ("Valor original", formatar_moeda(atualizacao.valor_original)),
            ("Juros", formatar_moeda(atualizacao.juros)),
        ]
    detalhes.append(("Cobranças", str(linha.cobrancas)))
    if atualizacao.parcialmente_pago:
        detalhes.append(("Saldo", formatar_moeda(atualizacao.saldo)))
    # no prazo e sem nada pedindo atenção: azul, para toda faixa ter significado
    cor = cores.cor_de_linha(linha, dias_em_breve) or tema.cor("destaque", cores.tema_atual())
    return DadosCartao(
        titulo=f"{linha.cliente.codigo} – {linha.cliente.nome}",
        subtitulo=_descricao(linha.honorario),
        detalhes=detalhes,
        valor=formatar_moeda(atualizacao.total),
        valor_rotulo="Total atualizado" if atualizacao.juros else "Valor",
        situacao=etiqueta_de_situacao(linha, dias_em_breve),
        cor=cor,
        item=linha,
        acoes=acoes,
        datas=datas_do_honorario(linha, cor, dias_em_breve),
    )


def cartao_de_pago(linha: LinhaHonorario, acoes: list[Acao]) -> DadosCartao:
    """Cartão do registro de pagos: quando pagou e quanto de atraso e juros houve."""
    honorario = linha.honorario
    pagamentos = [p for p in honorario.pagamentos if p.ativo]
    ultimo = pagamentos[-1] if pagamentos else None
    atraso = ultimo.dias_atraso if ultimo else 0
    juros = sum((p.juros_cobrados for p in pagamentos), start=ZERO)
    desconto = sum((p.desconto for p in pagamentos), start=ZERO)

    cor = tema.cor("atencao" if atraso else "pago", cores.tema_atual())
    datas = [
        DataCartao("Venceu", formatar_data(honorario.vencimento)),
        DataCartao("Pago em", formatar_data(honorario.pago_em) or "sem data", cor),
    ]
    detalhes = []
    if atraso:
        detalhes.append(("Atraso", f"{atraso} dia(s)"))
    if juros:
        detalhes.append(("Juros cobrados", formatar_moeda(juros)))
    if desconto:
        detalhes.append(("Abono", formatar_moeda(desconto)))
    if ultimo:
        detalhes.append(("Forma", ultimo.forma_pagamento.rotulo))
    if len(pagamentos) > 1:
        detalhes.append(("Parcelas", str(len(pagamentos))))

    if not honorario.pago_em:
        situacao = "Pago (a planilha não guardava a data)"
    elif atraso:
        situacao = f"Pago com {atraso} dia(s) de atraso"
    else:
        situacao = "Pago em dia"
    return DadosCartao(
        titulo=f"{linha.cliente.codigo} – {linha.cliente.nome}",
        subtitulo=_descricao(honorario),
        detalhes=detalhes,
        valor=formatar_moeda(linha.atualizacao.total),
        valor_rotulo="Recebido",
        situacao=situacao,
        cor=cor,
        item=linha,
        acoes=acoes,
        datas=datas,
    )


# ----------------------------------------------------------------------- base


class _PainelDeHonorarios(QWidget):
    """Estrutura comum: cabeçalho, filtros, cartões e rodapé com o resumo."""

    titulo = ""
    subtitulo = ""
    vazio = "Nada por aqui."
    # None = todos; False = sem os clientes só de IR (que têm tela própria); True = só eles
    clientes_so_ir: bool | None = False
    mostrar_filtro_grupo = True

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.linhas: list[LinhaHonorario] = []
        self._montar()
        self.recarregar()

    # ------------------------------------------------------------ o que muda
    def _botoes_do_cabecalho(self) -> list[tuple[str, Callable[[], None], bool, str]]:
        return []

    def _botoes_do_rodape(self) -> list[tuple[str, Callable[[], None]]]:
        return [("Exportar lista", self._exportar)]

    def _montar_filtros(self, linha: QHBoxLayout) -> None:
        """Filtros próprios da tela, entre os comuns e a busca."""

    def _consultar(self) -> list[LinhaHonorario]:
        raise NotImplementedError

    def _agrupar(self, linhas: list[LinhaHonorario]) -> list[tuple[str, list[LinhaHonorario]]]:
        return servico.agrupar_por_grupo(linhas)

    def _cartao(self, linha: LinhaHonorario) -> DadosCartao:
        return cartao_de_honorario(
            linha, self._acoes_do_cartao(linha), self.contexto.config_int("dias_vence_em_breve", 5)
        )

    def _acoes_do_cartao(self, linha: LinhaHonorario) -> list[Acao]:
        return [Acao("Histórico", self._abrir_historico, "Datas, cobranças e pagamentos")]

    def _rotulo_total(self) -> str:
        return "total"

    # ------------------------------------------------------------------ layout
    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.cabecalho = widgets.Cabecalho(self.titulo, self.subtitulo)
        self.botoes: dict[str, QWidget] = {}
        for texto, funcao, primario, atalho in self._botoes_do_cabecalho():
            self.botoes[texto] = self.cabecalho.adicionar_botao(
                texto, funcao, primario=primario, atalho=atalho
            )
        self.cabecalho.adicionar_botao("Atualizar", self.recarregar, atalho="F5")
        layout.addWidget(self.cabecalho)

        filtros = QHBoxLayout()
        self.tipo_pessoa = ComboEnum(TipoPessoa)
        self.tipo_pessoa.insertItem(0, "PF e PJ", None)
        self.tipo_pessoa.setCurrentIndex(0)
        self.tipo_pessoa.currentIndexChanged.connect(lambda *_: self.recarregar())
        filtros.addWidget(self.tipo_pessoa)
        self.grupo = ComboRegistros(
            servico_tipos.listar_grupos(self.contexto.sessao),
            rotulo=lambda g: g.nome,
            vazio="Todos os grupos",
        )
        self.grupo.currentIndexChanged.connect(lambda *_: self.recarregar())
        self.grupo.setVisible(self.mostrar_filtro_grupo)
        filtros.addWidget(self.grupo)
        self._montar_filtros(filtros)
        filtros.addStretch(1)
        self.busca = CampoBusca("Buscar empresa…")
        self.busca.setMinimumWidth(220)
        self.busca.buscou.connect(lambda *_: self.recarregar())
        filtros.addWidget(self.busca)
        layout.addLayout(filtros)

        self.lista = PainelDeCartoes(self.vazio)
        self.lista.selecao_mudou.connect(self._atualizar_resumo)
        self.lista.item_ativado.connect(self._abrir_historico)
        layout.addWidget(self.lista, 1)

        rodape = QHBoxLayout()
        self.resumo = widgets.rotulo_fraco("")
        rodape.addWidget(self.resumo, 1)
        for texto, funcao in self._botoes_do_rodape():
            botao = widgets.QPushButton(texto)
            botao.clicked.connect(funcao)
            rodape.addWidget(botao)
            self.botoes[texto] = botao
        layout.addLayout(rodape)

    def _agrupamento(self, opcoes: list[tuple[str, str]]) -> QComboBox:
        combo = QComboBox()
        for rotulo, chave in opcoes:
            combo.addItem(rotulo, chave)
        combo.currentIndexChanged.connect(lambda *_: self.recarregar())
        return combo

    # ------------------------------------------------------------------ dados
    def _filtro_base(self, **extras) -> Filtro:
        return Filtro(
            termo=self.busca.text(),
            tipo_pessoa=self.tipo_pessoa.currentData(),
            grupo_id=self.grupo.valor() if self.mostrar_filtro_grupo else None,
            data_referencia=self.contexto.data_referencia,
            clientes_so_ir=self.clientes_so_ir,
            **extras,
        )

    def recarregar(self) -> None:
        self.contexto.atualizar()
        self.linhas = self._consultar()
        secoes = [
            SecaoCartoes(
                titulo=rotulo,
                itens=itens,
                construtor=self._cartao,
                total=formatar_moeda(servico.total_de(itens)),
            )
            for rotulo, itens in self._agrupar(self.linhas)
        ]
        self.lista.definir_secoes(secoes)
        self._atualizar_resumo()

    def _atualizar_resumo(self) -> None:
        total = servico.total_de(self.linhas)
        partes = [
            f"{len(self.linhas)} honorário(s)",
            f"{self._rotulo_total()} {formatar_moeda(total)}",
        ]
        desenhados = self.lista.desenhados
        if desenhados < len(self.linhas):
            partes.append(f"mostrando {desenhados}")
        selecionados = self.lista.selecionados()
        if selecionados:
            partes.append(
                f"{len(selecionados)} selecionado(s): "
                f"{formatar_moeda(servico.total_de(selecionados))}"
            )
        self.resumo.setText(" · ".join(partes))

    # ------------------------------------------------------------------ ações
    def _selecionados(self) -> list[LinhaHonorario]:
        return self.lista.selecionados()

    def _um_selecionado(self, acao: str) -> LinhaHonorario | None:
        linhas = self._selecionados()
        if len(linhas) != 1:
            widgets.aviso(self, f"Selecione um honorário para {acao}.")
            return None
        return linhas[0]

    def _abrir_historico(self, linha: LinhaHonorario) -> None:
        DialogoHistorico(self.contexto, linha.honorario, self).exec()
        self.recarregar()

    def _cobrar_um(self, linha: LinhaHonorario) -> None:
        self._abrir_cobranca([linha])

    def _cobrar(self) -> None:
        self._abrir_cobranca(self._selecionados())

    def _abrir_cobranca(self, linhas) -> None:
        cobraveis = [linha for linha in linhas if linha.honorario.status.cobravel]
        if not cobraveis:
            widgets.aviso(self, "Selecione um ou mais honorários para cobrar.")
            return
        por_empresa: dict[int, list[LinhaHonorario]] = {}
        for linha in cobraveis:
            por_empresa.setdefault(linha.cliente.id, []).append(linha)

        if len(por_empresa) == 1:
            dialogo = DialogoCobrar(self.contexto, cobraveis[0].cliente, cobraveis, self)
            dialogo.exec()
            if dialogo.registrou:
                self.recarregar()
            return

        # várias empresas: uma mensagem por empresa, uma depois da outra
        if not widgets.confirmar(
            self,
            f"Cobrar {len(por_empresa)} empresas em sequência?",
            "Cobrar várias empresas",
            f"{len(cobraveis)} honorário(s) · total "
            f"{formatar_moeda(servico.total_de(cobraveis))}. A mensagem de cada "
            "empresa aparece pronta; você copia ou abre o WhatsApp e passa para a "
            "próxima. Nada é enviado sozinho.",
        ):
            return
        from ..dialogos.assistente import executar_assistente

        grupos = [(linhas[0].cliente, linhas) for linhas in por_empresa.values()]
        andamento = executar_assistente(self.contexto, grupos, self)
        widgets.informar(self, andamento.resumo, "Cobrança concluída")
        self.recarregar()

    def _pagar(self) -> None:
        linha = self._um_selecionado("registrar o pagamento")
        if linha and DialogoPagamento(self.contexto, linha.honorario, self).exec():
            self.recarregar()

    def _ficha(self) -> None:
        linhas = self._selecionados()
        if not linhas:
            widgets.aviso(self, "Selecione um honorário para abrir a ficha da empresa.")
            return
        DialogoFicha(self.contexto, linhas[0].cliente, self).exec()
        self.recarregar()

    def _cancelar(self) -> None:
        linha = self._um_selecionado("cancelar")
        if linha is None:
            return
        from PySide6.QtWidgets import QInputDialog

        motivo, confirmou = QInputDialog.getText(
            self, "Cancelar honorário", "Motivo do cancelamento:"
        )
        if not confirmou:
            return

        def acao():
            servico.cancelar(self.contexto.sessao, linha.honorario, motivo)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.recarregar()

    def _estornar(self) -> None:
        linha = self._um_selecionado("estornar o pagamento")
        if linha is None:
            return
        ativos = [p for p in linha.honorario.pagamentos if p.ativo]
        if not ativos:
            widgets.aviso(
                self,
                "Este honorário veio da planilha antiga como pago e não tem registro de "
                "pagamento para estornar.",
            )
            return
        from PySide6.QtWidgets import QInputDialog

        motivo, confirmou = QInputDialog.getText(
            self, "Estornar pagamento", "Motivo do estorno:"
        )
        if not confirmou:
            return
        if not widgets.confirmar(
            self,
            f"Estornar o pagamento de {formatar_moeda(ativos[-1].valor_pago)}?",
            "Estornar pagamento",
            f"{linha.cliente.nome} · {linha.honorario.competencia_rotulo}. "
            "O honorário volta para Em aberto; o registro do pagamento fica guardado.",
        ):
            return

        from ...servicos import pagamentos as servico_pagamentos

        def acao():
            servico_pagamentos.estornar(self.contexto.sessao, ativos[-1], motivo)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.recarregar()

    def _exportar(self) -> None:
        from ..dialogos.exportar import exportar_linhas

        exportar_linhas(self, self.contexto, self.linhas, self.titulo)


# ------------------------------------------------------------------ atrasados


FAIXAS_ATRASO = (
    ("Qualquer atraso", 1, None),
    ("1 a 30 dias", 1, 30),
    ("31 a 60 dias", 31, 60),
    ("61 a 90 dias", 61, 90),
    ("Mais de 90 dias", 91, None),
)


class PainelAtrasados(_PainelDeHonorarios):
    """Vencidos e ainda em aberto: a tela de trabalho da cobrança."""

    titulo = "Atrasados"
    subtitulo = "Honorários vencidos e ainda em aberto"
    vazio = "Nenhum honorário em atraso."

    def _botoes_do_cabecalho(self):
        return [
            ("Cobrar selecionados", self._cobrar, True, "Ctrl+B"),
            ("Registrar pagamento", self._pagar, False, "Ctrl+P"),
            ("Ficha da empresa", self._ficha, False, "Ctrl+F"),
        ]

    def _botoes_do_rodape(self):
        return [
            ("Registrar cobrança em lote", self._cobrar_em_lote),
            ("Renegociar selecionados", self._renegociar),
            ("Cancelar honorário", self._cancelar),
            ("Exportar lista", self._exportar),
        ]

    def _montar_filtros(self, linha: QHBoxLayout) -> None:
        self.faixa = QComboBox()
        for rotulo, minimo, maximo in FAIXAS_ATRASO:
            self.faixa.addItem(rotulo, (minimo, maximo))
        self.faixa.currentIndexChanged.connect(lambda *_: self.recarregar())
        linha.addWidget(self.faixa)

        self.nunca_cobrado = QCheckBox("Nunca cobrado")
        self.nunca_cobrado.toggled.connect(lambda *_: self.recarregar())
        linha.addWidget(self.nunca_cobrado)

        linha.addSpacing(12)
        linha.addWidget(widgets.rotulo_fraco("Agrupar por:"))
        self.agrupamento = self._agrupamento(
            [("Faixa de atraso", "faixa"), ("Grupo", "grupo"), ("Empresa", "empresa")]
        )
        linha.addWidget(self.agrupamento)

        linha.addSpacing(12)
        linha.addWidget(widgets.rotulo_fraco("Simular para:"))
        self.data_referencia = CampoData(self.contexto.data_referencia)
        self.data_referencia.setToolTip("Calcula os juros como se hoje fosse esta data")
        self.data_referencia.dateChanged.connect(self._mudar_referencia)
        linha.addWidget(self.data_referencia)

    def _mudar_referencia(self) -> None:
        self.contexto.data_referencia = self.data_referencia.valor()
        self.recarregar()

    def _consultar(self) -> list[LinhaHonorario]:
        minimo, maximo = self.faixa.currentData()
        return servico.consultar(
            self.contexto.sessao,
            self._filtro_base(
                status=StatusPagamento.EM_ABERTO,
                atraso_minimo=minimo,
                atraso_maximo=maximo,
                nunca_cobrado=self.nunca_cobrado.isChecked(),
            ),
        )

    def _agrupar(self, linhas):
        modo = self.agrupamento.currentData()
        if modo == "grupo":
            return servico.agrupar_por_grupo(linhas)
        if modo == "empresa":
            return servico.agrupar_por_cliente(linhas)
        return servico.agrupar_por_faixa_de_atraso(linhas)

    def _acoes_do_cartao(self, linha):
        acoes = super()._acoes_do_cartao(linha)
        if linha.honorario.status.cobravel:
            acoes.append(Acao("Cobrar", self._cobrar_um, "Gerar a mensagem só deste honorário"))
        return acoes

    def _rotulo_total(self) -> str:
        return "total atualizado"

    def _cobrar_em_lote(self) -> None:
        linhas = [linha for linha in self._selecionados() if linha.honorario.status.cobravel]
        if not linhas:
            widgets.aviso(self, "Selecione os honorários que você cobrou por fora do sistema.")
            return
        empresas = len({linha.cliente.id for linha in linhas})
        if not widgets.confirmar(
            self,
            f"Registrar cobrança de hoje em {len(linhas)} honorário(s)?",
            "Registrar cobrança em lote",
            f"{empresas} empresa(s) · total {formatar_moeda(servico.total_de(linhas))}. "
            "Nenhuma mensagem é gerada; a resposta você anota depois em Cobranças enviadas.",
        ):
            return
        from PySide6.QtWidgets import QInputDialog

        observacao, _ = QInputDialog.getText(
            self, "Registrar cobrança em lote", "Observação (opcional):"
        )

        def acao():
            servico_cobrancas.registrar_sem_mensagem(
                self.contexto.sessao, linhas, observacao or ""
            )
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.recarregar()

    def _renegociar(self) -> None:
        linhas = [linha for linha in self._selecionados() if linha.honorario.status.cobravel]
        if not linhas or len({linha.cliente.id for linha in linhas}) > 1:
            widgets.aviso(self, "Selecione os honorários em atraso de uma única empresa.")
            return
        if DialogoRenegociacao(self.contexto, linhas[0].cliente, linhas, self).exec():
            self.recarregar()


# ------------------------------------------------------------------- a vencer


class PainelAVencer(_PainelDeHonorarios):
    """Em aberto e dentro do prazo, do vencimento mais próximo para o mais distante."""

    titulo = "A vencer"
    subtitulo = "Em aberto e dentro do prazo, aguardando pagamento"
    vazio = "Nenhum honorário em aberto dentro do prazo."

    def _botoes_do_cabecalho(self):
        return [
            ("Enviar lembrete", self._cobrar, True, "Ctrl+B"),
            ("Registrar pagamento", self._pagar, False, "Ctrl+P"),
            ("Ficha da empresa", self._ficha, False, "Ctrl+F"),
        ]

    def _botoes_do_rodape(self):
        return [
            ("Cancelar honorário", self._cancelar),
            ("Exportar lista", self._exportar),
        ]

    def _montar_filtros(self, linha: QHBoxLayout) -> None:
        linha.addSpacing(12)
        linha.addWidget(widgets.rotulo_fraco("Agrupar por:"))
        self.agrupamento = self._agrupamento(
            [("Vencimento", "vencimento"), ("Empresa", "empresa")]
        )
        linha.addWidget(self.agrupamento)

    def _consultar(self) -> list[LinhaHonorario]:
        return servico.consultar(
            self.contexto.sessao,
            self._filtro_base(status=StatusPagamento.EM_ABERTO, atraso_maximo=0),
        )

    def _agrupar(self, linhas):
        if self.agrupamento.currentData() == "empresa":
            return servico.agrupar_por_cliente(linhas)
        return servico.agrupar_por_proximidade(
            linhas,
            self.contexto.data_referencia,
            self.contexto.config_int("dias_vence_em_breve", 5),
        )

    def _acoes_do_cartao(self, linha):
        acoes = super()._acoes_do_cartao(linha)
        if linha.honorario.status.cobravel:
            acoes.append(
                Acao("Lembrete", self._cobrar_um, "Mensagem de lembrete antes do vencimento")
            )
        return acoes


# ---------------------------------------------------------------------- pagos


PERIODOS_PAGOS = (
    ("Mês atual", 0),
    ("Últimos 3 meses", 3),
    ("Últimos 6 meses", 6),
    ("Últimos 12 meses", 12),
    ("Tudo", None),
)


class PainelPagos(_PainelDeHonorarios):
    """Registro dos honorários quitados, recortado por período."""

    titulo = "Pagos"
    subtitulo = "Registro dos honorários quitados"
    vazio = "Nenhum pagamento nesse período."

    def _botoes_do_cabecalho(self):
        return [("Ficha da empresa", self._ficha, False, "Ctrl+F")]

    def _botoes_do_rodape(self):
        return [
            ("Estornar pagamento", self._estornar),
            ("Exportar lista", self._exportar),
        ]

    def _montar_filtros(self, linha: QHBoxLayout) -> None:
        linha.addSpacing(12)
        linha.addWidget(widgets.rotulo_fraco("Período:"))
        self.periodo = QComboBox()
        for rotulo, meses in PERIODOS_PAGOS:
            self.periodo.addItem(rotulo, meses)
        self.periodo.setCurrentIndex(1)
        self.periodo.currentIndexChanged.connect(lambda *_: self.recarregar())
        linha.addWidget(self.periodo)

        linha.addWidget(widgets.rotulo_fraco("Agrupar por:"))
        self.agrupamento = self._agrupamento(
            [("Mês do pagamento", "mes"), ("Empresa", "empresa")]
        )
        linha.addWidget(self.agrupamento)

    def _desde(self) -> date | None:
        meses = self.periodo.currentData()
        if meses is None:
            return None
        referencia = self.contexto.data_referencia
        primeiro = date(referencia.year, referencia.month, 1)
        if meses == 0:
            return primeiro
        return somar_meses(primeiro, -(meses - 1)).replace(day=1)

    def _consultar(self) -> list[LinhaHonorario]:
        # o recorte de período vai para a consulta: o que está fora nem é lido
        return servico.consultar(
            self.contexto.sessao,
            self._filtro_base(status=StatusPagamento.PAGO, pago_de=self._desde()),
        )

    def _agrupar(self, linhas):
        if self.agrupamento.currentData() == "empresa":
            return servico.agrupar_por_cliente(linhas)
        return servico.agrupar_por_mes_pagamento(linhas)

    def _cartao(self, linha: LinhaHonorario) -> DadosCartao:
        return cartao_de_pago(linha, self._acoes_do_cartao(linha))

    def _rotulo_total(self) -> str:
        return "recebido"


# ----------------------------------------------------------- imposto de renda


class PainelImpostoRenda(_PainelDeHonorarios):
    """Clientes que só têm honorário de Imposto de Renda, com cobrança própria.

    Em aberto e pagos continuam separados: a tela alterna entre os dois, e o
    ano do IR (IRPF 2026, 2025…) é o recorte natural em vez do período.
    """

    titulo = "Imposto de Renda"
    subtitulo = "Clientes que só têm honorário de Imposto de Renda"
    vazio = "Nenhum honorário de Imposto de Renda com esses filtros."
    clientes_so_ir = True
    mostrar_filtro_grupo = False

    def _botoes_do_cabecalho(self):
        return [
            ("Cobrar selecionados", self._cobrar, True, "Ctrl+B"),
            ("Registrar pagamento", self._pagar, False, "Ctrl+P"),
            ("Ficha da empresa", self._ficha, False, "Ctrl+F"),
        ]

    def _botoes_do_rodape(self):
        return [
            ("Estornar pagamento", self._estornar),
            ("Cancelar honorário", self._cancelar),
            ("Exportar lista", self._exportar),
        ]

    def _montar_filtros(self, linha: QHBoxLayout) -> None:
        linha.addSpacing(12)
        self.situacao = QComboBox()
        self.situacao.addItem("Em aberto", StatusPagamento.EM_ABERTO.value)
        self.situacao.addItem("Pagos", StatusPagamento.PAGO.value)
        self.situacao.currentIndexChanged.connect(lambda *_: self.recarregar())
        linha.addWidget(self.situacao)

        linha.addWidget(widgets.rotulo_fraco("Ano do IR:"))
        self.ano = QComboBox()
        self.ano.addItem("Todos", None)
        ano_atual = self.contexto.data_referencia.year
        for ano in range(ano_atual, ano_atual - 6, -1):
            self.ano.addItem(str(ano), ano)
        self.ano.currentIndexChanged.connect(lambda *_: self.recarregar())
        linha.addWidget(self.ano)

    @property
    def mostrando_pagos(self) -> bool:
        return self.situacao.currentData() == StatusPagamento.PAGO.value

    def recarregar(self) -> None:
        pagos = self.mostrando_pagos
        visiveis = {
            "Cobrar selecionados": not pagos,
            "Registrar pagamento": not pagos,
            "Cancelar honorário": not pagos,
            "Estornar pagamento": pagos,
        }
        for texto, visivel in visiveis.items():
            botao = self.botoes.get(texto)
            if botao is not None:
                botao.setVisible(visivel)
        super().recarregar()

    def _consultar(self) -> list[LinhaHonorario]:
        status = StatusPagamento.PAGO if self.mostrando_pagos else StatusPagamento.EM_ABERTO
        return servico.consultar(
            self.contexto.sessao,
            self._filtro_base(status=status, competencia_ano=self.ano.currentData()),
        )

    def _agrupar(self, linhas):
        if self.mostrando_pagos:
            return servico.agrupar_por_mes_pagamento(linhas)
        atrasados = sorted(
            (linha for linha in linhas if linha.atualizacao.dias_atraso > 0),
            key=lambda linha: linha.atualizacao.dias_atraso,
            reverse=True,
        )
        no_prazo = sorted(
            (linha for linha in linhas if linha.atualizacao.dias_atraso == 0),
            key=lambda linha: linha.honorario.vencimento,
        )
        return [
            (rotulo, itens)
            for rotulo, itens in (("Atrasados", atrasados), ("A vencer", no_prazo))
            if itens
        ]

    def _cartao(self, linha: LinhaHonorario) -> DadosCartao:
        if self.mostrando_pagos:
            return cartao_de_pago(linha, self._acoes_do_cartao(linha))
        return super()._cartao(linha)

    def _acoes_do_cartao(self, linha):
        acoes = super()._acoes_do_cartao(linha)
        if linha.honorario.status.cobravel:
            rotulo = "Cobrar" if linha.atualizacao.dias_atraso else "Lembrete"
            acoes.append(Acao(rotulo, self._cobrar_um))
        return acoes

    def _rotulo_total(self) -> str:
        return "recebido" if self.mostrando_pagos else "total atualizado"


__all__ = [
    "PainelAVencer",
    "PainelImpostoRenda",
    "PainelAtrasados",
    "PainelPagos",
    "cartao_de_honorario",
    "cartao_de_pago",
    "etiqueta_de_situacao",
    "hoje",
]
