"""Mês a mês: tudo o que foi emitido num mês, recorrente ou avulso, e o que falta gerar.

◀ ▶ andam de mês em mês; o botão do mês abre um menu por ano para ir direto. O
mês de um honorário é o da competência (ou o do vencimento, quando a competência
não tem mês — IR, avulsos).
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...dominio.enums import StatusPagamento
from ...dominio.valores import Competencia, formatar_moeda, somar_meses
from ...servicos import contratos as servico_contratos
from ...servicos import honorarios as servico
from ..comum import widgets
from ..comum.campos import CampoBusca
from ..comum.filtros import BarraDeFiltros, FiltroOpcoes
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
from .avulsos import _cor_da_situacao, cancelar_com_motivo, situacao

MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro")

ORIGENS = (("todos", None), ("Recorrentes", "recorrente"), ("Avulsos", "avulso"))
SITUACOES = (
    ("todas", None),
    ("Em aberto", StatusPagamento.EM_ABERTO),
    ("Pagos", StatusPagamento.PAGO),
    ("Cancelados", StatusPagamento.CANCELADO),
)


def nome_do_mes(ano: int, mes: int) -> str:
    return f"{MESES[mes - 1].capitalize()} de {ano}"


class PainelMesAMes(QWidget):
    titulo = "Mês a mês"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        referencia = contexto.data_referencia
        self.ano, self.mes = referencia.year, referencia.month
        self.linhas: list = []
        self._montar()
        self.recarregar()

    # ------------------------------------------------------------------ tela
    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        # título e explicação ficam no nome da aba e no cabeçalho de Honorários
        self.cabecalho = widgets.Cabecalho("Mês a mês")
        self.cabecalho.ocultar_titulo()

        # navegação: ◀ mês ▶ e "este mês"
        self.anterior = QPushButton("◀")
        self.anterior.setObjectName("navegaMes")
        self.anterior.setToolTip("Mês anterior (Alt+←)")
        self.anterior.setShortcut("Alt+Left")
        self.anterior.clicked.connect(lambda: self.ir_para(*self._deslocar(-1)))
        self.botao_mes = QToolButton()
        self.botao_mes.setObjectName("botaoMes")
        self.botao_mes.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.botao_mes.setToolTip("Escolher o mês")
        self.proximo = QPushButton("▶")
        self.proximo.setObjectName("navegaMes")
        self.proximo.setToolTip("Próximo mês (Alt+→)")
        self.proximo.setShortcut("Alt+Right")
        self.proximo.clicked.connect(lambda: self.ir_para(*self._deslocar(1)))
        self.este_mes = QPushButton("Este mês")
        self.este_mes.setObjectName("linkFiltro")
        self.este_mes.clicked.connect(
            lambda: self.ir_para(self.contexto.data_referencia.year,
                                 self.contexto.data_referencia.month)
        )
        navegacao = QHBoxLayout()
        navegacao.setSpacing(6)
        for widget in (self.anterior, self.botao_mes, self.proximo, self.este_mes):
            navegacao.addWidget(widget)
        navegacao.addStretch(1)
        navegacao.addWidget(self.cabecalho, 1)
        layout.addLayout(navegacao)

        self.busca = CampoBusca("Buscar cliente…")
        self.busca.setMinimumWidth(220)
        self.busca.buscou.connect(lambda *_: self._filtrar())
        self.cabecalho.acoes.addWidget(self.busca)
        self.gerar = self.cabecalho.adicionar_botao(
            "Gerar competência", self._gerar, primario=True, atalho="Ctrl+G"
        )
        menu = QMenu(self)
        for texto, funcao, atalho in (
            ("Lançar avulso", self._lancar_avulso, "Ctrl+N"),
            ("Editar", self._editar, ""),
            ("Cancelar honorário…", self._cancelar, ""),
            ("Atualizar", self.recarregar, "F5"),
        ):
            acao = QAction(texto, self)
            if atalho:
                acao.setShortcut(atalho)
                acao.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            acao.triggered.connect(lambda _=False, f=funcao: f())
            menu.addAction(acao)
            self.addAction(acao)
        acoes = QToolButton()
        acoes.setObjectName("menuAcoes")
        acoes.setText("Ações  ▾")
        acoes.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        acoes.setMenu(menu)
        self.menu_acoes = menu
        self.cabecalho.acoes.addWidget(acoes)

        # o mês em números
        linha_cartoes = QHBoxLayout()
        linha_cartoes.setSpacing(10)
        self.cartoes = {
            "emitido": widgets.Cartao("Emitido no mês"),
            "pago": widgets.Cartao("Pago"),
            "aberto": widgets.Cartao("Em aberto (atualizado)"),
            "cancelado": widgets.Cartao("Cancelados / renegociados"),
        }
        for cartao in self.cartoes.values():
            linha_cartoes.addWidget(cartao)
        layout.addLayout(linha_cartoes)

        # contratos que ainda não geraram este mês
        self.aviso_geracao = QLabel()
        self.aviso_geracao.setObjectName("previaMensagem")   # lembrete, não erro
        self.aviso_geracao.setWordWrap(True)
        self.aviso_geracao.setVisible(False)
        layout.addWidget(self.aviso_geracao)

        self.filtros = BarraDeFiltros()
        self.origem = self.filtros.adicionar(FiltroOpcoes("Origem", list(ORIGENS)))
        self.origem.currentIndexChanged.connect(lambda *_: self._filtrar())
        self.situacao = self.filtros.adicionar(FiltroOpcoes("Situação", list(SITUACOES)))
        self.situacao.currentIndexChanged.connect(lambda *_: self._filtrar())
        layout.addWidget(self.filtros)

        self.modelo = ModeloTabela([
            Coluna("Cliente", lambda linha: f"{linha.cliente.codigo} – {linha.cliente.nome}"),
            Coluna("Origem", lambda linha: "Recorrente" if linha.honorario.contrato_id
                   else "Avulso", alinhamento=Qt.AlignmentFlag.AlignCenter, largura=92),
            Coluna("Tipo", lambda linha: linha.honorario.tipo.nome),
            Coluna("Competência / descrição", lambda linha: linha.honorario.competencia_rotulo
                   or linha.honorario.descricao or "—", largura=210),
            coluna_data("Vencimento", lambda linha: linha.honorario.vencimento),
            coluna_moeda("Valor", lambda linha: linha.atualizacao.valor_original),
            Coluna("Situação", situacao, cor=_cor_da_situacao,
                   alinhamento=Qt.AlignmentFlag.AlignCenter),
        ])
        self.tabela = preparar_tabela(QTableView(), esticar=0)
        self.tabela.setModel(self.modelo)
        self.tabela.doubleClicked.connect(lambda *_: self._editar())
        layout.addWidget(self.tabela, 1)
        self.resumo = widgets.rotulo_fraco("")
        layout.addWidget(self.resumo)

    # --------------------------------------------------------------- navegar
    def _deslocar(self, meses: int) -> tuple[int, int]:
        destino = somar_meses(date(self.ano, self.mes, 1), meses)
        return destino.year, destino.month

    def ir_para(self, ano: int, mes: int) -> None:
        self.ano, self.mes = ano, mes
        self.recarregar()

    def _montar_menu_de_meses(self) -> None:
        """Um submenu por ano; os meses com lançamento ficam marcados com •."""
        com_lancamento = set(servico.meses_com_lancamento(self.contexto.sessao))
        referencia = self.contexto.data_referencia
        anos = {ano for ano, _ in com_lancamento} | {referencia.year, referencia.year + 1}
        menu = QMenu(self)
        for ano in sorted(anos, reverse=True):
            submenu = menu.addMenu(str(ano))
            for mes in range(1, 13):
                marca = "  •" if (ano, mes) in com_lancamento else ""
                acao = submenu.addAction(f"{MESES[mes - 1].capitalize()}{marca}")
                acao.setCheckable(True)
                acao.setChecked((ano, mes) == (self.ano, self.mes))
                acao.triggered.connect(lambda _=False, a=ano, m=mes: self.ir_para(a, m))
        self.botao_mes.setMenu(menu)

    # ------------------------------------------------------------------ dados
    def recarregar(self) -> None:
        self.contexto.atualizar()
        self.botao_mes.setText(f"{nome_do_mes(self.ano, self.mes)}  ▾")
        self._montar_menu_de_meses()
        self.linhas = servico.do_mes(
            self.contexto.sessao, self.ano, self.mes, self.contexto.data_referencia
        )
        self._resumir_mes()
        self._avisar_geracao()
        self._filtrar()

    def _resumir_mes(self) -> None:
        def total(linhas, campo="valor_original"):
            return sum((getattr(linha.atualizacao, campo) for linha in linhas),
                       start=servico.ZERO)

        validos = [linha for linha in self.linhas if linha.honorario.status not in
                   (StatusPagamento.CANCELADO, StatusPagamento.RENEGOCIADO)]
        pagos = [linha for linha in validos if linha.honorario.status is StatusPagamento.PAGO]
        abertos = [linha for linha in validos
                   if linha.honorario.status is StatusPagamento.EM_ABERTO]
        fora = len(self.linhas) - len(validos)
        self.cartoes["emitido"].definir(f"{formatar_moeda(total(validos))}  ·  {len(validos)}")
        self.cartoes["pago"].definir(f"{formatar_moeda(total(pagos, 'total'))}  ·  {len(pagos)}")
        self.cartoes["aberto"].definir(
            f"{formatar_moeda(total(abertos, 'total'))}  ·  {len(abertos)}"
        )
        self.cartoes["cancelado"].definir(str(fora))

    def _avisar_geracao(self) -> None:
        competencia = Competencia(self.ano, self.mes)
        try:
            faltando = [item for item in servico_contratos.previa_geracao(
                self.contexto.sessao, competencia) if not item.impedimento]
        except Exception:  # noqa: BLE001 — o aviso é ajuda, não pode travar a tela
            faltando = []
        self.faltando = len(faltando)
        if faltando:
            self.aviso_geracao.setText(
                f"{len(faltando)} contrato(s) ainda não geraram a competência "
                f"{competencia.rotulo()} — total "
                f"{formatar_moeda(sum((i.valor for i in faltando), start=servico.ZERO))}. "
                'Use "Gerar competência".'
            )
        self.aviso_geracao.setVisible(bool(faltando))
        self.gerar.setText(
            f"Gerar competência ({len(faltando)})" if faltando else "Gerar competência"
        )

    def _filtrar(self) -> None:
        from ...dominio.valores import normalizar_busca

        termo = normalizar_busca(self.busca.text())
        origem = self.origem.currentData()
        status = self.situacao.currentData()
        visiveis = [
            linha for linha in self.linhas
            if (not termo or termo in normalizar_busca(linha.cliente.nome)
                or termo == linha.cliente.codigo)
            and (origem is None
                 or (origem == "recorrente") == bool(linha.honorario.contrato_id))
            and (status is None or linha.honorario.status is status
                 or (status is StatusPagamento.CANCELADO
                     and linha.honorario.status is StatusPagamento.RENEGOCIADO))
        ]
        self.modelo.definir_itens(visiveis)
        ajustar_colunas(self.tabela, self.modelo.colunas)
        self.resumo.setText(
            f"{len(visiveis)} de {len(self.linhas)} honorário(s) de "
            f"{nome_do_mes(self.ano, self.mes).lower()} · duplo clique para editar"
        )

    # ------------------------------------------------------------------ ações
    def _selecionada(self):
        linha = item_atual(self.tabela)
        if linha is None:
            widgets.aviso(self, "Selecione um honorário na lista.")
        return linha

    def _gerar(self) -> None:
        from ..dialogos.competencia import DialogoGerarCompetencia

        dialogo = DialogoGerarCompetencia(self.contexto, self, self.ano, self.mes)
        dialogo.exec()
        if dialogo.gerados:
            self.recarregar()

    def _lancar_avulso(self) -> None:
        from ..dialogos.honorario import DialogoHonorario

        if DialogoHonorario(self.contexto, parent=self).exec():
            self.recarregar()

    def _editar(self) -> None:
        from ..dialogos.honorario import DialogoHonorario

        linha = self._selecionada()
        if linha and DialogoHonorario(
            self.contexto, honorario=linha.honorario, parent=self
        ).exec():
            self.recarregar()

    def _cancelar(self) -> None:
        linha = self._selecionada()
        if linha is not None:
            cancelar_com_motivo(self, self.contexto, linha.honorario, self.recarregar)
