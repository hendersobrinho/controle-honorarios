"""As parcelas de um parcelamento: pagar, cobrar, estornar e ver o histórico."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QInputDialog, QTableView, QVBoxLayout

from ...dominio.valores import ZERO, formatar_data, formatar_moeda, hoje
from ...servicos import honorarios as servico_honorarios
from ...servicos import pagamentos as servico_pagamentos
from ...servicos import parcelamentos as servico
from ..comum import widgets
from ..comum.tabelas import (
    Coluna,
    ModeloTabela,
    ajustar_colunas,
    coluna_data,
    coluna_moeda,
    item_atual,
    preparar_tabela,
)
from ..contexto import Contexto


def situacao_da_parcela(parcela: servico.Parcela) -> str:
    honorario = parcela.honorario
    if parcela.paga:
        return f"Paga em {formatar_data(honorario.pago_em)}" if honorario.pago_em else "Paga"
    if not parcela.em_aberto:
        return honorario.status.rotulo
    if parcela.atrasada:
        return f"Atrasada há {parcela.linha.atualizacao.dias_atraso} dia(s)"
    return "Em aberto"


class DialogoParcelas(QDialog):
    def __init__(self, contexto: Contexto, parcelamento: servico.Parcelamento,
                 parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.parcelamento = parcelamento
        self.mudou = False
        self.setWindowTitle(f"Parcelas – {parcelamento.cliente.nome}")
        self.resize(820, 520)
        self._montar()
        self._preencher()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        self.cabecalho = widgets.Cabecalho(self.parcelamento.cliente.nome)
        layout.addWidget(self.cabecalho)
        total = len(self.parcelamento.parcelas)
        self.modelo = ModeloTabela(
            [
                Coluna("Parcela", lambda p: f"{p.numero}/{total}"),
                coluna_data("Vencimento", lambda p: p.honorario.vencimento),
                coluna_moeda("Valor", lambda p: p.honorario.valor_original),
                coluna_moeda("Juros", lambda p: p.linha.atualizacao.juros),
                Coluna("", lambda p: "✎ à mão" if p.linha.atualizacao.juros_manual else ""),
                coluna_moeda("Total hoje", lambda p: p.linha.atualizacao.total, negrito=True),
                Coluna("Situação", situacao_da_parcela),
            ]
        )
        self.tabela = preparar_tabela(QTableView(), esticar=6)
        self.tabela.setModel(self.modelo)
        self.tabela.doubleClicked.connect(lambda *_: self._pagar())
        layout.addWidget(self.tabela, 1)
        self.originais = widgets.rotulo_fraco("")
        self.originais.setWordWrap(True)
        layout.addWidget(self.originais)

        botoes = QHBoxLayout()
        self.botao_historico = widgets.QPushButton("Histórico")
        self.botao_historico.clicked.connect(self._historico)
        self.botao_juros = widgets.QPushButton("Juros…")
        self.botao_juros.setToolTip("Conferir o juros da parcela, acertar à mão ou tirar")
        self.botao_juros.clicked.connect(self._alterar_juros)
        self.botao_sem_juros = widgets.QPushButton("Tirar o juros das atrasadas")
        self.botao_sem_juros.clicked.connect(self._tirar_juros)
        self.botao_estornar = widgets.QPushButton("Estornar pagamento…")
        self.botao_estornar.clicked.connect(self._estornar)
        self.botao_cobrar = widgets.QPushButton("Cobrar")
        self.botao_cobrar.clicked.connect(self._cobrar)
        self.botao_pagar = widgets.QPushButton("Confirmar pagamento")
        self.botao_pagar.setObjectName("primario")
        self.botao_pagar.clicked.connect(self._pagar)
        fechar = widgets.QPushButton("Fechar")
        fechar.clicked.connect(self.accept)
        for botao in (self.botao_historico, self.botao_estornar, self.botao_juros,
                      self.botao_sem_juros):
            botoes.addWidget(botao)
        botoes.addStretch(1)
        for botao in (self.botao_cobrar, self.botao_pagar, fechar):
            botoes.addWidget(botao)
        layout.addLayout(botoes)
        self.tabela.selectionModel().currentRowChanged.connect(lambda *_: self._botoes())

    def _preencher(self) -> None:
        p = self.parcelamento
        juros = sum((x.linha.atualizacao.juros for x in p.abertas), start=ZERO)
        self.cabecalho.definir_subtitulo(
            (f"Juros das parcelas em aberto: {formatar_moeda(juros)} · " if juros else "")
            + f"Parcelamento de {formatar_data(p.acordo.data)} · "
            f"{formatar_moeda(p.acordo.valor_acordado)} em {len(p.validas)} parcela(s) · "
            f"pago {formatar_moeda(p.pago)} · falta {formatar_moeda(p.falta)}"
        )
        self.modelo.definir_itens(p.parcelas)
        ajustar_colunas(self.tabela, self.modelo.colunas)
        partes = [f"{h.tipo.nome} {h.competencia_rotulo} ({formatar_moeda(h.valor_original)})"
                  for h in p.originais]
        self.originais.setText("Honorários parcelados: " + "; ".join(partes)
                               + (f"\nObservações: {p.acordo.observacoes}"
                                  if p.acordo.observacoes else ""))
        # a parcela que interessa já vem escolhida: a próxima em aberto
        alvo = p.parcelas.index(p.proxima) if p.proxima else 0
        if p.parcelas:
            self.tabela.selectRow(alvo)
        self._botoes()

    def _botoes(self) -> None:
        parcela = self.atual()
        aberta = parcela is not None and parcela.em_aberto and not self.parcelamento.cancelado
        self.botao_pagar.setEnabled(aberta)
        self.botao_cobrar.setEnabled(aberta)
        self.botao_estornar.setEnabled(parcela is not None and parcela.paga)
        self.botao_historico.setEnabled(parcela is not None)
        self.botao_juros.setEnabled(aberta)
        self.botao_sem_juros.setEnabled(
            not self.parcelamento.cancelado
            and any(p.linha.atualizacao.juros > 0 for p in self.parcelamento.atrasadas))

    def atual(self) -> servico.Parcela | None:
        return item_atual(self.tabela)

    def _recarregar(self) -> None:
        self.mudou = True
        self.contexto.atualizar()
        novo = servico.obter(self.contexto.sessao, self.parcelamento.acordo.id,
                             self.contexto.data_referencia)
        if novo is not None:
            self.parcelamento = novo
        self._preencher()

    # ------------------------------------------------------------------ ações
    def _pagar(self) -> None:
        parcela = self.atual()
        if parcela is None or not parcela.em_aberto:
            return
        from .pagamento import DialogoPagamento

        if DialogoPagamento(self.contexto, parcela.honorario, self).exec():
            self._recarregar()

    def _cobrar(self) -> None:
        parcela = self.atual()
        if parcela is None or not parcela.em_aberto:
            return
        from .cobrar import DialogoCobrar

        dialogo = DialogoCobrar(self.contexto, self.parcelamento.cliente, [parcela.linha], self)
        dialogo.exec()
        if dialogo.registrou:
            self._recarregar()

    def _historico(self) -> None:
        parcela = self.atual()
        if parcela is None:
            return
        from .historico import DialogoHistorico

        DialogoHistorico(self.contexto, parcela.honorario, self).exec()

    def _estornar(self) -> None:
        parcela = self.atual()
        if parcela is None or not parcela.paga:
            return
        ativos = [p for p in parcela.honorario.pagamentos if p.ativo]
        if not ativos:
            widgets.aviso(self, "Esta parcela não tem registro de pagamento para estornar.")
            return
        motivo, confirmou = QInputDialog.getText(self, "Estornar pagamento", "Motivo do estorno:")
        if not confirmou:
            return

        def acao():
            servico_pagamentos.estornar(self.contexto.sessao, ativos[-1], motivo)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self._recarregar()

    def _gravar_juros(self, parcelas, juros) -> None:
        def acao():
            for parcela in parcelas:
                servico_honorarios.ajustar_juros(self.contexto.sessao, parcela.honorario,
                                                 juros, hoje())
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self._recarregar()

    def _alterar_juros(self) -> None:
        parcela = self.atual()
        if parcela is None or not parcela.em_aberto:
            return
        from .juros_manual import DialogoJurosManual

        total = len(self.parcelamento.parcelas)
        dialogo = DialogoJurosManual(
            f"{self.parcelamento.cliente.nome} · parcela {parcela.numero}/{total}",
            parcela.honorario, parcela.linha.atualizacao,
            aviso="O valor vale a partir de hoje: se a parcela continuar em aberto, os "
                  "próximos dias de atraso somam por cima.", parent=self)
        if dialogo.exec():
            self._gravar_juros([parcela], dialogo.juros)

    def _tirar_juros(self) -> None:
        alvo = [p for p in self.parcelamento.atrasadas if p.linha.atualizacao.juros > 0]
        if not alvo or not widgets.confirmar(
            self, f"Tirar o juros de {len(alvo)} parcela(s) atrasada(s)?", "Tirar o juros",
            "Fica só o valor de cada parcela, a partir de hoje. Dá para voltar ao "
            "calculado em Juros….", acao="Tirar o juros",
        ):
            return
        self._gravar_juros(alvo, ZERO)
