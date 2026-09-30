"""Cobrança geral: a tela de trabalho do dia a dia.

Cada honorário é um cartão com faixa colorida indicando a situação, e cada
cartão leva ao histórico daquele honorário. Pendentes e pagos nunca aparecem na
mesma lista; as seções trazem quantidade e subtotal atualizado.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ...dominio.enums import StatusPagamento, TipoPessoa
from ...dominio.valores import ZERO, formatar_data, formatar_moeda, somar_meses
from ...servicos import cobrancas as servico_cobrancas
from ...servicos import honorarios as servico
from ...servicos import tipos as servico_tipos
from ...servicos.honorarios import Filtro, LinhaHonorario
from ..comum import cores, widgets
from ..comum.campos import CampoBusca, CampoData, ComboEnum, ComboRegistros
from ..comum.cartoes import Acao, DadosCartao, PainelDeCartoes, SecaoCartoes
from ..contexto import Contexto
from ..dialogos.cobrar import DialogoCobrar
from ..dialogos.ficha import DialogoFicha
from ..dialogos.historico import DialogoHistorico
from ..dialogos.pagamento import DialogoPagamento
from ..dialogos.renegociacao import DialogoRenegociacao

PERIODOS_PAGOS = (
    ("Mês atual", 0),
    ("Últimos 3 meses", 3),
    ("Últimos 6 meses", 6),
    ("Últimos 12 meses", 12),
    ("Tudo", None),
)

FAIXAS = (
    ("Qualquer atraso", None, None),
    ("Em dia (sem atraso)", None, 0),
    ("1 a 30 dias", 1, 30),
    ("31 a 60 dias", 31, 60),
    ("61 a 90 dias", 61, 90),
    ("Mais de 90 dias", 91, None),
)


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
        return f"Promessa vencida ({formatar_data(linha.promessa)})"
    if atualizacao.dias_atraso > 0:
        return f"Em atraso há {atualizacao.dias_atraso} dia(s)"
    falta = (linha.honorario.vencimento - date.today()).days
    if falta == 0:
        return "Vence hoje"
    if 0 < falta <= dias_em_breve:
        return f"Vence em {falta} dia(s)"
    if linha.promessa:
        return f"Promessa para {formatar_data(linha.promessa)}"
    return "Em dia"


def cartao_de_honorario(
    linha: LinhaHonorario, acoes: list[Acao], dias_em_breve: int = 5
) -> DadosCartao:
    honorario = linha.honorario
    atualizacao = linha.atualizacao
    detalhes = [
        ("Vencimento", formatar_data(honorario.vencimento)),
        ("Valor original", formatar_moeda(atualizacao.valor_original)),
        ("Juros", formatar_moeda(atualizacao.juros)),
        ("Cobranças", str(linha.cobrancas)),
        (
            "Última cobrança",
            formatar_data(linha.ultima_cobranca) if linha.ultima_cobranca else "nunca",
        ),
    ]
    if linha.promessa:
        detalhes.append(("Promessa", formatar_data(linha.promessa)))
    if atualizacao.parcialmente_pago:
        detalhes.append(("Saldo", formatar_moeda(atualizacao.saldo)))
    competencia = honorario.competencia_rotulo or honorario.descricao or "sem competência"
    return DadosCartao(
        titulo=f"{linha.cliente.codigo} – {linha.cliente.nome}",
        subtitulo=f"{honorario.tipo.nome} · {competencia}",
        detalhes=detalhes,
        valor=formatar_moeda(atualizacao.total),
        valor_rotulo="Total atualizado" if atualizacao.juros else "Total",
        situacao=etiqueta_de_situacao(linha, dias_em_breve),
        cor=cores.cor_de_linha(linha, dias_em_breve),
        item=linha,
        acoes=acoes,
    )


class PainelCobrancaGeral(QWidget):
    titulo = "Cobrança geral"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self._montar()
        self.recarregar()

    # ------------------------------------------------------------------ layout
    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.cabecalho = widgets.Cabecalho(
            "Cobrança geral", "Honorários pendentes e pagos, separados por grupo"
        )
        self.cabecalho.adicionar_botao(
            "Cobrar selecionados", self._cobrar, primario=True, atalho="Ctrl+B"
        )
        self.cabecalho.adicionar_botao("Registrar pagamento", self._pagar, atalho="Ctrl+P")
        self.cabecalho.adicionar_botao("Ficha da empresa", self._ficha, atalho="Ctrl+F")
        self.cabecalho.adicionar_botao("Atualizar", self.recarregar, atalho="F5")
        layout.addWidget(self.cabecalho)

        topo = QHBoxLayout()
        self.grupo_situacao = QButtonGroup(self)
        for indice, rotulo in enumerate(("Pendentes", "Pagos", "Todos")):
            botao = QRadioButton(rotulo)
            botao.setChecked(indice == 0)
            self.grupo_situacao.addButton(botao, indice)
            topo.addWidget(botao)
        self.grupo_situacao.idToggled.connect(lambda *_: self.recarregar())
        topo.addSpacing(20)
        topo.addWidget(widgets.rotulo_fraco("Agrupar por:"))
        self.agrupamento = QComboBox()
        self.agrupamento.addItem("Grupo", "grupo")
        self.agrupamento.addItem("Empresa", "empresa")
        self.agrupamento.currentIndexChanged.connect(lambda *_: self.recarregar())
        topo.addWidget(self.agrupamento)
        topo.addSpacing(16)
        topo.addWidget(widgets.rotulo_fraco("Pagos de:"))
        self.periodo_pagos = QComboBox()
        for rotulo, meses in PERIODOS_PAGOS:
            self.periodo_pagos.addItem(rotulo, meses)
        self.periodo_pagos.setCurrentIndex(1)
        self.periodo_pagos.setToolTip(
            "Recorte do histórico de pagos. Os pendentes aparecem sempre por inteiro."
        )
        self.periodo_pagos.currentIndexChanged.connect(lambda *_: self.recarregar())
        topo.addWidget(self.periodo_pagos)
        topo.addStretch(1)
        self.busca = CampoBusca("Buscar empresa, tipo ou competência…")
        self.busca.setMinimumWidth(260)
        self.busca.buscou.connect(lambda *_: self.recarregar())
        topo.addWidget(self.busca)
        layout.addLayout(topo)

        filtros = QHBoxLayout()
        self.tipo_pessoa = ComboEnum(TipoPessoa)
        self.tipo_pessoa.insertItem(0, "PF e PJ", None)
        self.tipo_pessoa.setCurrentIndex(0)
        self.tipo_pessoa.currentIndexChanged.connect(lambda *_: self.recarregar())
        filtros.addWidget(widgets.rotulo_fraco("Tipo:"))
        filtros.addWidget(self.tipo_pessoa)

        self.grupo = ComboRegistros(
            servico_tipos.listar_grupos(self.contexto.sessao),
            rotulo=lambda g: g.nome,
            vazio="Todos os grupos",
        )
        self.grupo.currentIndexChanged.connect(lambda *_: self.recarregar())
        filtros.addWidget(widgets.rotulo_fraco("Grupo:"))
        filtros.addWidget(self.grupo)

        self.faixa = QComboBox()
        for rotulo, minimo, maximo in FAIXAS:
            self.faixa.addItem(rotulo, (minimo, maximo))
        self.faixa.currentIndexChanged.connect(lambda *_: self.recarregar())
        filtros.addWidget(widgets.rotulo_fraco("Atraso:"))
        filtros.addWidget(self.faixa)

        self.nunca_cobrado = QCheckBox("Nunca cobrado")
        self.nunca_cobrado.toggled.connect(lambda *_: self.recarregar())
        filtros.addWidget(self.nunca_cobrado)

        self.sem_cobranca = QCheckBox("Sem cobrança há")
        self.sem_cobranca.toggled.connect(lambda *_: self.recarregar())
        filtros.addWidget(self.sem_cobranca)
        self.dias_sem_cobranca = QComboBox()
        for dias in (3, 5, 7, 15, 30):
            self.dias_sem_cobranca.addItem(f"{dias} dias", dias)
        self.dias_sem_cobranca.setCurrentIndex(2)
        self.dias_sem_cobranca.currentIndexChanged.connect(lambda *_: self.recarregar())
        filtros.addWidget(self.dias_sem_cobranca)

        filtros.addStretch(1)
        filtros.addWidget(widgets.rotulo_fraco("Simular para:"))
        self.data_referencia = CampoData(self.contexto.data_referencia)
        self.data_referencia.dateChanged.connect(self._mudar_referencia)
        filtros.addWidget(self.data_referencia)
        layout.addLayout(filtros)

        self.lista = PainelDeCartoes("Nenhum honorário com esses filtros.")
        self.lista.selecao_mudou.connect(self._atualizar_resumo)
        self.lista.item_ativado.connect(lambda linha: self._abrir_historico(linha))
        layout.addWidget(self.lista, 1)

        rodape = QHBoxLayout()
        self.resumo = widgets.rotulo_fraco("")
        rodape.addWidget(self.resumo, 1)
        for texto, funcao in (
            ("Registrar cobrança em lote", self._cobrar_em_lote),
            ("Renegociar selecionados", self._renegociar),
            ("Cancelar honorário", self._cancelar),
            ("Exportar lista", self._exportar),
        ):
            botao = widgets.QPushButton(texto)
            botao.clicked.connect(funcao)
            rodape.addWidget(botao)
        layout.addLayout(rodape)

    # ------------------------------------------------------------------ dados
    def _mudar_referencia(self) -> None:
        self.contexto.data_referencia = self.data_referencia.valor()
        self.recarregar()

    def _pagos_desde(self) -> date | None:
        """Início do recorte do histórico de pagos."""
        meses = self.periodo_pagos.currentData()
        if meses is None:
            return None
        referencia = self.contexto.data_referencia
        primeiro = date(referencia.year, referencia.month, 1)
        if meses == 0:
            return primeiro
        return somar_meses(primeiro, -(meses - 1)).replace(day=1)

    def _filtro(self, status: StatusPagamento) -> Filtro:
        minimo, maximo = self.faixa.currentData()
        em_aberto = status is StatusPagamento.EM_ABERTO
        return Filtro(
            termo=self.busca.text(),
            tipo_pessoa=self.tipo_pessoa.currentData(),
            grupo_id=self.grupo.valor(),
            status=status,
            atraso_minimo=minimo if em_aberto else None,
            atraso_maximo=maximo if em_aberto else None,
            nunca_cobrado=self.nunca_cobrado.isChecked(),
            sem_cobranca_dias=(
                self.dias_sem_cobranca.currentData() if self.sem_cobranca.isChecked() else None
            ),
            pago_de=None if em_aberto else self._pagos_desde(),
            data_referencia=self.contexto.data_referencia,
        )

    def _acoes_do_cartao(self, linha: LinhaHonorario) -> list[Acao]:
        """Pago ou cancelado não mostra botão de cobrar."""
        acoes = [Acao("Histórico", self._abrir_historico, "Datas, cobranças e pagamentos")]
        if linha.honorario.status.cobravel:
            acoes.append(
                Acao("Cobrar", self._cobrar_um, "Gerar a mensagem só deste honorário")
            )
        return acoes

    def recarregar(self) -> None:
        self.contexto.atualizar()
        sessao = self.contexto.sessao
        modo = self.grupo_situacao.checkedId()
        em_breve = self.contexto.config_int("dias_vence_em_breve", 5)
        def construtor(linha: LinhaHonorario) -> DadosCartao:
            return cartao_de_honorario(linha, self._acoes_do_cartao(linha), em_breve)
        secoes: list[SecaoCartoes] = []
        self.linhas: list[LinhaHonorario] = []
        self.periodo_pagos.setEnabled(self.grupo_situacao.checkedId() != 0)

        if modo in (0, 2):
            pendentes = servico.consultar(sessao, self._filtro(StatusPagamento.EM_ABERTO))
            agrupador = (
                servico.agrupar_por_grupo
                if self.agrupamento.currentData() == "grupo"
                else servico.agrupar_por_cliente
            )
            for rotulo, linhas in agrupador(pendentes):
                prefixo = "Pendentes · " if modo == 2 else ""
                secoes.append(
                    SecaoCartoes(
                        titulo=f"{prefixo}{rotulo}",
                        itens=linhas,
                        construtor=construtor,
                        total=formatar_moeda(servico.total_de(linhas)),
                    )
                )
            self.linhas.extend(pendentes)

        if modo in (1, 2):
            pagos = servico.consultar(sessao, self._filtro(StatusPagamento.PAGO))
            for rotulo, linhas in servico.agrupar_por_mes_pagamento(pagos):
                secoes.append(
                    SecaoCartoes(
                        titulo=f"Pagos · {rotulo}",
                        itens=linhas,
                        construtor=construtor,
                        total=formatar_moeda(servico.total_de(linhas)),
                    )
                )
            self.linhas.extend(pagos)

        self.lista.definir_secoes(secoes)
        self._atualizar_resumo()

    def _atualizar_resumo(self) -> None:
        total = sum((linha.atualizacao.total for linha in self.linhas), start=ZERO)
        selecionados = self.lista.selecionados()
        parte = ""
        if selecionados:
            soma = sum((linha.atualizacao.total for linha in selecionados), start=ZERO)
            parte = f" · {len(selecionados)} selecionado(s): {formatar_moeda(soma)}"
        desenhados = self.lista.desenhados
        mostrando = (
            "" if desenhados >= len(self.linhas) else f" · mostrando {desenhados}"
        )
        self.resumo.setText(
            f"{len(self.linhas)} honorário(s) · total {formatar_moeda(total)} · "
            f"valores para {self.contexto.data_referencia:%d/%m/%Y}{mostrando}{parte}"
        )

    # ------------------------------------------------------------------ ações
    def _selecionados(self) -> list[LinhaHonorario]:
        return self.lista.selecionados()

    def _um_cliente(self, linhas) -> bool:
        if len({linha.cliente.id for linha in linhas}) > 1:
            widgets.aviso(
                self,
                "Selecione honorários de uma única empresa. Para cobrar várias, "
                "use a Fila de envio.",
            )
            return False
        return True

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
            widgets.aviso(self, "Selecione um ou mais honorários pendentes para cobrar.")
            return
        if not self._um_cliente(cobraveis):
            return
        dialogo = DialogoCobrar(self.contexto, cobraveis[0].cliente, cobraveis, self)
        dialogo.exec()
        if dialogo.registrou:
            self.recarregar()

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
            "Nenhuma mensagem é gerada; a resposta você anota depois no Acompanhamento.",
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

    def _pagar(self) -> None:
        linhas = self._selecionados()
        if len(linhas) != 1:
            widgets.aviso(self, "Selecione um honorário para registrar o pagamento.")
            return
        if DialogoPagamento(self.contexto, linhas[0].honorario, self).exec():
            self.recarregar()

    def _ficha(self) -> None:
        linhas = self._selecionados()
        if not linhas:
            widgets.aviso(self, "Selecione um honorário para abrir a ficha da empresa.")
            return
        DialogoFicha(self.contexto, linhas[0].cliente, self).exec()
        self.recarregar()

    def _renegociar(self) -> None:
        linhas = [linha for linha in self._selecionados() if linha.honorario.status.cobravel]
        if not linhas or not self._um_cliente(linhas):
            widgets.aviso(self, "Selecione os honorários em aberto de uma empresa.")
            return
        if DialogoRenegociacao(self.contexto, linhas[0].cliente, linhas, self).exec():
            self.recarregar()

    def _cancelar(self) -> None:
        linhas = self._selecionados()
        if len(linhas) != 1:
            widgets.aviso(self, "Selecione um honorário para cancelar.")
            return
        from PySide6.QtWidgets import QInputDialog

        motivo, confirmou = QInputDialog.getText(
            self, "Cancelar honorário", "Motivo do cancelamento:"
        )
        if not confirmou:
            return

        def acao():
            servico.cancelar(self.contexto.sessao, linhas[0].honorario, motivo)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.recarregar()

    def _exportar(self) -> None:
        from ..dialogos.exportar import exportar_linhas

        exportar_linhas(self, self.contexto, self.linhas)


__all__ = ["Decimal", "PainelCobrancaGeral", "cartao_de_honorario", "etiqueta_de_situacao"]
