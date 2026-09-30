"""Honorários recorrentes: contratos e geração de competência."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...dominio.valores import ZERO, formatar_moeda
from ...servicos import contratos as servico
from ..comum import widgets
from ..comum.campos import CampoBusca
from ..comum.tabelas import (
    Coluna,
    ModeloTabela,
    ajustar_colunas,
    coluna_data,
    coluna_inteiro,
    coluna_moeda,
    item_atual,
    itens_selecionados,
    preparar_tabela,
)
from ..contexto import Contexto
from ..dialogos.competencia import DialogoGerarCompetencia
from ..dialogos.contrato import DialogoContrato, DialogoReajuste, DialogoReajusteEmMassa


class PainelContratos(QWidget):
    titulo = "Honorários recorrentes"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self._montar()
        self.recarregar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self.cabecalho = widgets.Cabecalho(
            "Honorários recorrentes",
            "Contratos que geram os honorários de cada competência",
        )
        self.cabecalho.adicionar_botao(
            "Gerar competência", self._gerar, primario=True, atalho="Ctrl+G"
        )
        self.cabecalho.adicionar_botao("Novo contrato", self._novo, atalho="Ctrl+N")
        self.cabecalho.adicionar_botao("Editar", self._editar)
        self.cabecalho.adicionar_botao("Reajustar", self._reajustar)
        self.cabecalho.adicionar_botao("Atualizar", self.recarregar, atalho="F5")
        layout.addWidget(self.cabecalho)

        filtros = QHBoxLayout()
        self.mostrar_suspensos = QCheckBox("Mostrar suspensos")
        self.mostrar_suspensos.setChecked(True)
        self.mostrar_suspensos.toggled.connect(lambda *_: self.recarregar())
        filtros.addWidget(self.mostrar_suspensos)
        filtros.addStretch(1)
        self.busca = CampoBusca("Buscar cliente ou tipo…")
        self.busca.setMinimumWidth(260)
        self.busca.buscou.connect(self._filtrar)
        filtros.addWidget(self.busca)
        layout.addLayout(filtros)

        self.modelo = ModeloTabela(
            [
                Coluna("Cliente", lambda c: f"{c.cliente.codigo} – {c.cliente.nome}"),
                Coluna("Tipo", lambda c: c.tipo.nome),
                Coluna("Periodicidade", lambda c: c.periodicidade.rotulo,
                       alinhamento=Qt.AlignmentFlag.AlignCenter),
                coluna_moeda("Valor", lambda c: c.valor, negrito=True),
                coluna_inteiro("Dia venc.", lambda c: c.dia_vencimento),
                Coluna("Vence", lambda c: f"+{c.meses_vencimento} mês(es)",
                       alinhamento=Qt.AlignmentFlag.AlignCenter),
                Coluna("Forma de envio", lambda c: c.forma_envio.nome if c.forma_envio else "—"),
                coluna_data("Vigência", lambda c: c.vigencia_inicio),
                Coluna(
                    "Situação",
                    lambda c: "Suspenso" if c.suspenso else "Ativo",
                    alinhamento=Qt.AlignmentFlag.AlignCenter,
                ),
                coluna_inteiro("Reajustes", lambda c: len(c.historico)),
            ]
        )
        self.proxy_termo = ""
        self.tabela = preparar_tabela(QTableView(), esticar=0)
        self.tabela.setModel(self.modelo)
        self.tabela.doubleClicked.connect(lambda *_: self._editar())
        layout.addWidget(self.tabela, 1)

        rodape = QHBoxLayout()
        self.resumo = widgets.rotulo_fraco("")
        rodape.addWidget(self.resumo, 1)
        suspender = widgets.QPushButton("Suspender / reativar")
        suspender.clicked.connect(self._suspender)
        massa = widgets.QPushButton("Reajuste em massa")
        massa.clicked.connect(self._reajuste_em_massa)
        excluir = widgets.QPushButton("Excluir contrato")
        excluir.clicked.connect(self._excluir)
        for botao in (suspender, massa, excluir):
            rodape.addWidget(botao)
        layout.addLayout(rodape)

    # ------------------------------------------------------------------ dados
    def recarregar(self) -> None:
        self.contexto.atualizar()
        contratos = servico.listar(
            self.contexto.sessao, incluir_suspensos=self.mostrar_suspensos.isChecked()
        )
        if self.proxy_termo:
            from ...dominio.valores import normalizar_busca

            alvo = normalizar_busca(self.proxy_termo)
            contratos = [
                contrato
                for contrato in contratos
                if alvo in normalizar_busca(f"{contrato.cliente.nome} {contrato.tipo.nome}")
            ]
        self.modelo.definir_itens(contratos)
        ajustar_colunas(self.tabela, self.modelo.colunas)
        ativos = [c for c in contratos if not c.suspenso]
        total = sum((c.valor for c in ativos), start=ZERO)
        self.resumo.setText(
            f"{len(contratos)} contrato(s) · {len(ativos)} ativo(s) · "
            f"soma dos valores ativos {formatar_moeda(total)}"
        )

    def _filtrar(self, termo: str) -> None:
        self.proxy_termo = termo
        self.recarregar()

    def _selecionado(self):
        contrato = item_atual(self.tabela)
        if contrato is None:
            widgets.aviso(self, "Selecione um contrato.")
        return contrato

    # ------------------------------------------------------------------ ações
    def _novo(self) -> None:
        if DialogoContrato(self.contexto, parent=self).exec():
            self.recarregar()

    def _editar(self) -> None:
        contrato = self._selecionado()
        if contrato and DialogoContrato(self.contexto, contrato, parent=self).exec():
            self.recarregar()

    def _reajustar(self) -> None:
        contrato = self._selecionado()
        if contrato and DialogoReajuste(self.contexto, contrato, parent=self).exec():
            self.recarregar()

    def _reajuste_em_massa(self) -> None:
        contratos = itens_selecionados(self.tabela) or self.modelo.itens
        if not contratos:
            widgets.aviso(self, "Não há contratos para reajustar.")
            return
        if DialogoReajusteEmMassa(self.contexto, contratos, parent=self).exec():
            self.recarregar()

    def _suspender(self) -> None:
        contrato = self._selecionado()
        if contrato is None:
            return

        def acao():
            servico.suspender(self.contexto.sessao, contrato, not contrato.suspenso)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if deu_certo:
            self.recarregar()

    def _excluir(self) -> None:
        contrato = self._selecionado()
        if contrato is None:
            return
        if not widgets.confirmar(
            self,
            f"Excluir o contrato de {contrato.cliente.nome} ({contrato.tipo.nome})?",
            "Excluir contrato",
            "Os honorários já gerados continuam no sistema. "
            "Para apenas pausar a geração, use Suspender.",
        ):
            return

        def acao():
            servico.excluir(self.contexto.sessao, contrato)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if deu_certo:
            self.recarregar()

    def _gerar(self) -> None:
        dialogo = DialogoGerarCompetencia(self.contexto, self)
        dialogo.exec()
        if dialogo.gerados:
            self.recarregar()
