"""Honorários avulsos: lançar, corrigir e consultar (IRPF, alteração contratual…).

É o histórico dos avulsos lançados, pagos ou não, como "Honorários recorrentes"
é o lugar dos contratos. Cobrar e registrar pagamento ficam nas telas de cobrança
(Atrasados, A vencer, Imposto de Renda), onde o avulso entra assim que é lançado.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QTableView, QVBoxLayout, QWidget

from ...dominio.enums import Periodicidade, StatusPagamento
from ...dominio.valores import formatar_data, formatar_moeda, somar_meses
from ...servicos import honorarios as servico
from ...servicos import tipos as servico_tipos
from ...servicos.honorarios import Filtro
from ..comum import cores, tema, widgets
from ..comum.campos import CampoBusca, ComboRegistros
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
from ..dialogos.honorario import DialogoHonorario

PERIODOS = (
    ("Últimos 3 meses", 3),
    ("Últimos 6 meses", 6),
    ("Últimos 12 meses", 12),
    ("Tudo", None),
)

SITUACOES = (
    ("Todas as situações", None),
    ("Em aberto", StatusPagamento.EM_ABERTO),
    ("Pagos", StatusPagamento.PAGO),
    ("Cancelados", StatusPagamento.CANCELADO),
)


def situacao(linha) -> str:
    """Em aberto, pago (e quando) ou cancelado — em palavras."""
    honorario = linha.honorario
    status = honorario.status
    if status is StatusPagamento.PAGO:
        return f"Pago em {formatar_data(honorario.pago_em)}" if honorario.pago_em else "Pago"
    if status is StatusPagamento.EM_ABERTO:
        if linha.atualizacao.dias_atraso > 0:
            return f"Em atraso há {linha.atualizacao.dias_atraso} dia(s)"
        return "Em aberto, no prazo"
    return status.rotulo


def _cor_da_situacao(linha):
    nome = cores.tema_atual()
    status = linha.honorario.status
    if status is StatusPagamento.PAGO:
        return tema.cor("pago", nome)
    if status is StatusPagamento.EM_ABERTO:
        return tema.cor("atrasado", nome) if linha.atualizacao.dias_atraso > 0 else None
    return tema.cor("texto_fraco", nome)


class PainelAvulsos(QWidget):
    titulo = "Honorários avulsos"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self._montar()
        self.recarregar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self.cabecalho = widgets.Cabecalho(
            "Honorários avulsos",
            "Serviços que não vêm de contrato: lance e corrija aqui; a cobrança fica "
            "em Atrasados e A vencer",
        )
        self.cabecalho.adicionar_botao(
            "Lançar avulso", self._novo, primario=True, atalho="Ctrl+N"
        )
        self.cabecalho.adicionar_botao("Editar", self._editar)
        self.cabecalho.adicionar_botao("Cancelar…", self._cancelar)
        self.cabecalho.adicionar_botao("Atualizar", self.recarregar, atalho="F5")
        layout.addWidget(self.cabecalho)

        filtros = QHBoxLayout()
        self.tipo = ComboRegistros(
            [
                tipo
                for tipo in servico_tipos.listar_tipos(self.contexto.sessao)
                if tipo.periodicidade is Periodicidade.AVULSO
                or tipo.grupo.imposto_de_renda
            ],
            rotulo=lambda t: t.nome,
            vazio="Todos os tipos avulsos",
        )
        self.tipo.currentIndexChanged.connect(lambda *_: self.recarregar())
        filtros.addWidget(widgets.rotulo_fraco("Tipo:"))
        filtros.addWidget(self.tipo)
        self.periodo = QComboBox()
        for rotulo, meses in PERIODOS:
            self.periodo.addItem(rotulo, meses)
        self.periodo.currentIndexChanged.connect(lambda *_: self.recarregar())
        filtros.addWidget(widgets.rotulo_fraco("Vencimento:"))
        filtros.addWidget(self.periodo)
        self.situacao = QComboBox()
        for rotulo, status in SITUACOES:
            self.situacao.addItem(rotulo, status)
        self.situacao.currentIndexChanged.connect(lambda *_: self.recarregar())
        filtros.addWidget(self.situacao)
        filtros.addStretch(1)
        self.busca = CampoBusca("Buscar cliente…")
        self.busca.setMinimumWidth(240)
        self.busca.buscou.connect(lambda *_: self.recarregar())
        filtros.addWidget(self.busca)
        layout.addLayout(filtros)

        self.modelo = ModeloTabela(
            [
                Coluna("Cliente", lambda linha: f"{linha.cliente.codigo} – {linha.cliente.nome}"),
                Coluna("Tipo", lambda linha: linha.honorario.tipo.nome),
                Coluna("Descrição", lambda linha: linha.honorario.competencia_rotulo
                       or linha.honorario.descricao or "—"),
                coluna_data("Vencimento", lambda linha: linha.honorario.vencimento),
                coluna_moeda("Valor", lambda linha: linha.atualizacao.valor_original),
                Coluna("Situação", situacao, cor=_cor_da_situacao,
                       alinhamento=Qt.AlignmentFlag.AlignCenter),
            ]
        )
        self.tabela = preparar_tabela(QTableView(), esticar=0)
        self.tabela.setModel(self.modelo)
        self.tabela.doubleClicked.connect(lambda *_: self._editar())
        layout.addWidget(self.tabela, 1)

        self.resumo = widgets.rotulo_fraco("")
        layout.addWidget(self.resumo)

    def _desde(self):
        meses = self.periodo.currentData()
        if meses is None:
            return None
        return somar_meses(self.contexto.data_referencia, -(meses - 1)).replace(day=1)

    def recarregar(self) -> None:
        self.contexto.atualizar()
        avulsos = {
            tipo.id
            for tipo in servico_tipos.listar_tipos(self.contexto.sessao, somente_ativos=False)
            if tipo.periodicidade is Periodicidade.AVULSO or tipo.grupo.imposto_de_renda
        }
        filtro = Filtro(
            termo=self.busca.text(),
            status=self.situacao.currentData(),
            tipo_id=self.tipo.valor(),
            vencimento_de=self._desde(),
            data_referencia=self.contexto.data_referencia,
        )
        linhas = [
            linha
            for linha in servico.consultar(self.contexto.sessao, filtro)
            if linha.honorario.tipo_id in avulsos
            # renegociado vira parcelas: o original sai do histórico de lançamentos
            and linha.honorario.status is not StatusPagamento.RENEGOCIADO
        ]
        # mais recentes primeiro; a seta do cabeçalho fica em Vencimento, que é a ordem
        linhas.sort(key=lambda linha: linha.honorario.vencimento, reverse=True)
        self.modelo.definir_itens(linhas)
        ajustar_colunas(self.tabela, self.modelo.colunas)
        self.tabela.horizontalHeader().setSortIndicator(3, Qt.SortOrder.DescendingOrder)
        abertos = [x for x in linhas if x.honorario.status is StatusPagamento.EM_ABERTO]
        pagos = [x for x in linhas if x.honorario.status is StatusPagamento.PAGO]
        self.resumo.setText(
            f"{len(linhas)} lançamento(s) · {len(abertos)} em aberto "
            f"({formatar_moeda(servico.total_de(abertos))}) · {len(pagos)} pago(s). "
            "Para cobrar ou dar baixa, use Atrasados e A vencer."
        )

    def _selecionada(self):
        linha = item_atual(self.tabela)
        if linha is None:
            widgets.aviso(self, "Selecione um lançamento.")
        return linha

    def _novo(self) -> None:
        if DialogoHonorario(self.contexto, parent=self).exec():
            self.recarregar()

    def _editar(self) -> None:
        linha = self._selecionada()
        if linha and DialogoHonorario(
            self.contexto, honorario=linha.honorario, parent=self
        ).exec():
            self.recarregar()

    def _cancelar(self) -> None:
        linha = self._selecionada()
        if linha is None:
            return
        cancelar_com_motivo(self, self.contexto, linha.honorario, self.recarregar)


def cancelar_com_motivo(parent, contexto: Contexto, honorario, depois) -> None:
    """Pede o motivo, cancela e recarrega a tela (o motivo fica no histórico)."""
    from PySide6.QtWidgets import QInputDialog

    motivo, confirmou = QInputDialog.getText(
        parent, "Cancelar honorário", "Motivo do cancelamento:"
    )
    if not confirmou:
        return

    def acao():
        servico.cancelar(contexto.sessao, honorario, motivo)
        contexto.salvar()

    deu_certo, _ = widgets.executar(parent, acao)
    if not deu_certo:
        contexto.desfazer()
        return
    depois()
