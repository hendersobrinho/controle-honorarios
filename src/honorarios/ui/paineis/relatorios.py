"""Relatórios e exportações prontas."""

from __future__ import annotations

from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QVBoxLayout, QWidget

from ...dominio.enums import StatusPagamento
from ...servicos import clientes as servico_clientes
from ...servicos import honorarios as servico
from ...servicos.honorarios import Filtro
from ..comum import widgets
from ..comum.seletor_cliente import CampoCliente
from ..contexto import Contexto
from ..dialogos.exportar import exportar_extrato, exportar_linhas


class PainelRelatorios(QWidget):
    titulo = "Relatórios e exportação"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self._montar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(
            widgets.Cabecalho(
                "Relatórios e exportação",
                "Planilhas da situação atual e extrato de débitos em PDF",
            )
        )

        grupo_excel = QGroupBox("Exportar para Excel")
        caixa = QVBoxLayout(grupo_excel)
        caixa.addWidget(
            widgets.rotulo_fraco(
                "Os valores saem atualizados para a data de referência do sistema."
            )
        )
        botoes = QHBoxLayout()
        pendentes = widgets.QPushButton("Todos os pendentes")
        pendentes.clicked.connect(lambda: self._exportar(StatusPagamento.EM_ABERTO))
        pagos = widgets.QPushButton("Todos os pagos")
        pagos.clicked.connect(lambda: self._exportar(StatusPagamento.PAGO))
        atrasados = widgets.QPushButton("Somente em atraso")
        atrasados.clicked.connect(lambda: self._exportar(StatusPagamento.EM_ABERTO, atraso=1))
        for botao in (pendentes, pagos, atrasados):
            botoes.addWidget(botao)
        botoes.addStretch(1)
        caixa.addLayout(botoes)
        layout.addWidget(grupo_excel)

        grupo_extrato = QGroupBox("Extrato de débitos em PDF")
        caixa_extrato = QVBoxLayout(grupo_extrato)
        linha = QHBoxLayout()
        self.cliente = CampoCliente(self.contexto.sessao, vazio="Digite para procurar a empresa…")
        linha.addWidget(self.cliente, 1)
        gerar = widgets.QPushButton("Gerar extrato")
        gerar.setObjectName("primario")
        gerar.clicked.connect(self._extrato)
        linha.addWidget(gerar)
        caixa_extrato.addLayout(linha)
        layout.addWidget(grupo_extrato)
        layout.addStretch(1)

    def recarregar(self) -> None:
        self.contexto.atualizar()

    def _exportar(self, status: StatusPagamento, atraso: int | None = None) -> None:
        linhas = servico.consultar(
            self.contexto.sessao,
            Filtro(
                status=status,
                atraso_minimo=atraso,
                data_referencia=self.contexto.data_referencia,
            ),
        )
        exportar_linhas(self, self.contexto, linhas, status.rotulo)

    def _extrato(self) -> None:
        identificador = self.cliente.valor()
        if identificador is None:
            widgets.aviso(self, "Escolha a empresa.")
            return
        cliente = servico_clientes.obter(self.contexto.sessao, identificador)
        exportar_extrato(self, self.contexto, cliente)
