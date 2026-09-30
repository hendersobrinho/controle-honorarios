"""Fila do dia: o que precisa de cobrança hoje (substitui o Recall)."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ...dominio.valores import ZERO, formatar_moeda
from ...servicos import cobrancas as servico
from ...servicos.honorarios import LinhaHonorario
from ..comum import widgets
from ..comum.cartoes import Acao, PainelDeCartoes, SecaoCartoes
from ..contexto import Contexto
from ..dialogos.cobrar import DialogoCobrar
from ..dialogos.ficha import DialogoFicha
from ..dialogos.historico import DialogoHistorico
from ..dialogos.pagamento import DialogoPagamento
from .cobranca_geral import cartao_de_honorario


class PainelFilaDia(QWidget):
    titulo = "Fila do dia"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.linhas: list[LinhaHonorario] = []
        self._montar()
        self.recarregar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self.cabecalho = widgets.Cabecalho("Fila do dia", "")
        self.cabecalho.adicionar_botao(
            "Cobrar selecionados", self._cobrar, primario=True, atalho="Ctrl+B"
        )
        self.cabecalho.adicionar_botao("Registrar pagamento", self._pagar, atalho="Ctrl+P")
        self.cabecalho.adicionar_botao("Ficha", self._ficha, atalho="Ctrl+F")
        self.cabecalho.adicionar_botao("Atualizar", self.recarregar, atalho="F5")
        layout.addWidget(self.cabecalho)

        self.lista = PainelDeCartoes("Nada pedindo ação hoje. Bom sinal.")
        self.lista.selecao_mudou.connect(self._atualizar_resumo)
        self.lista.item_ativado.connect(self._abrir_historico)
        layout.addWidget(self.lista, 1)

        rodape = QHBoxLayout()
        self.resumo = widgets.rotulo_fraco("")
        rodape.addWidget(self.resumo, 1)
        layout.addLayout(rodape)

    def recarregar(self) -> None:
        self.contexto.atualizar()
        em_breve = self.contexto.config_int("dias_vence_em_breve", 5)
        def acoes_de(linha):
            acoes = [Acao("Histórico", self._abrir_historico, "Datas, cobranças e pagamentos")]
            if linha.honorario.status.cobravel:
                acoes.append(
                    Acao("Cobrar", self._cobrar_um, "Gerar a mensagem só deste honorário")
                )
            return acoes
        secoes = []
        self.linhas = []
        for secao in servico.fila_do_dia(self.contexto.sessao, self.contexto.data_referencia):
            if not secao.linhas:
                continue
            secoes.append(
                SecaoCartoes(
                    titulo=secao.titulo,
                    subtitulo=secao.descricao,
                    itens=secao.linhas,
                    construtor=lambda linha: cartao_de_honorario(
                        linha, acoes_de(linha), em_breve
                    ),
                    total=formatar_moeda(secao.total),
                )
            )
            self.linhas.extend(secao.linhas)
        self.lista.definir_secoes(secoes)
        self.cabecalho.definir_subtitulo(
            f"Referência {self.contexto.data_referencia:%d/%m/%Y} · "
            f"{len(self.linhas)} honorário(s) pedindo ação"
        )
        self._atualizar_resumo()

    def _atualizar_resumo(self) -> None:
        total = sum((linha.atualizacao.total for linha in self.linhas), start=ZERO)
        selecionados = self.lista.selecionados()
        parte = f" · {len(selecionados)} selecionado(s)" if selecionados else ""
        self.resumo.setText(f"Total envolvido: {formatar_moeda(total)}{parte}")

    # ------------------------------------------------------------------ ações
    def _abrir_historico(self, linha: LinhaHonorario) -> None:
        DialogoHistorico(self.contexto, linha.honorario, self).exec()
        self.recarregar()

    def _cobrar_um(self, linha: LinhaHonorario) -> None:
        self._abrir_cobranca([linha])

    def _cobrar(self) -> None:
        self._abrir_cobranca(self.lista.selecionados())

    def _abrir_cobranca(self, linhas) -> None:
        if not linhas:
            widgets.aviso(self, "Selecione um ou mais honorários da fila.")
            return
        if len({linha.cliente.id for linha in linhas}) > 1:
            widgets.aviso(self, "Selecione honorários de uma empresa só, ou use a Fila de envio.")
            return
        dialogo = DialogoCobrar(self.contexto, linhas[0].cliente, list(linhas), self)
        dialogo.exec()
        if dialogo.registrou:
            self.recarregar()

    def _pagar(self) -> None:
        linhas = self.lista.selecionados()
        if len(linhas) != 1:
            widgets.aviso(self, "Selecione um honorário.")
            return
        if DialogoPagamento(self.contexto, linhas[0].honorario, self).exec():
            self.recarregar()

    def _ficha(self) -> None:
        linhas = self.lista.selecionados()
        if not linhas:
            widgets.aviso(self, "Selecione um honorário.")
            return
        DialogoFicha(self.contexto, linhas[0].cliente, self).exec()
        self.recarregar()
