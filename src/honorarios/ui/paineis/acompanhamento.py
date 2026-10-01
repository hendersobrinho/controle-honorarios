"""Cobranças enviadas: o que já foi cobrado e o que cada cliente respondeu.

A resposta não é anotada na hora de cobrar — quando a mensagem sai, ainda não
existe resposta. É aqui que o retorno entra, com o período à escolha e cada
cobrança em um cartão.
"""

from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from ...dominio.enums import Canal
from ...dominio.valores import ZERO, formatar_data, formatar_moeda, somar_meses
from ...servicos import acompanhamento as servico
from ...servicos import cobrancas as servico_cobrancas
from ..comum import cores, tema, widgets
from ..comum.campos import CampoBusca, ComboEnum
from ..comum.cartoes import Acao, DadosCartao, DataCartao, PainelDeCartoes, SecaoCartoes
from ..contexto import Contexto
from ..dialogos.cobrar import DialogoCobrar
from ..dialogos.ficha import DialogoFicha
from ..dialogos.pagamento import DialogoPagamento
from ..dialogos.resposta import DialogoResposta

PERIODOS = (
    ("Mês atual", 0),
    ("Últimos 3 meses", 3),
    ("Últimos 6 meses", 6),
    ("Últimos 12 meses", 12),
    ("Tudo", None),
)

CORES_SITUACAO = {
    servico.PROMESSA_VENCIDA: "atrasado",
    servico.AGUARDANDO: "atencao",
    servico.PRECISA_DECISAO: "atencao",
    servico.PROMESSA_EM_ABERTO: "destaque",
    servico.NAO_RESPONDEU: "atrasado",
    servico.ENCERRADA: "pago",
}


class PainelAcompanhamento(QWidget):
    titulo = "Cobranças enviadas"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.linhas: list[servico.LinhaAcompanhamento] = []
        self._montar()
        self.recarregar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self.cabecalho = widgets.Cabecalho(
            "Cobranças enviadas",
            "Cada mensagem enviada e o que o cliente respondeu — anote aqui o retorno",
        )
        self.cabecalho.adicionar_botao(
            "Registrar resposta", self._responder, primario=True, atalho="Ctrl+R"
        )
        self.cabecalho.adicionar_botao("Cobrar de novo", self._cobrar, atalho="Ctrl+B")
        self.cabecalho.adicionar_botao("Registrar pagamento", self._pagar, atalho="Ctrl+P")
        self.cabecalho.adicionar_botao("Ficha", self._ficha, atalho="Ctrl+F")
        self.cabecalho.adicionar_botao("Atualizar", self.recarregar, atalho="F5")
        layout.addWidget(self.cabecalho)

        filtros = QHBoxLayout()
        filtros.addWidget(widgets.rotulo_fraco("Período:"))
        self.periodo = QComboBox()
        for rotulo, meses in PERIODOS:
            self.periodo.addItem(rotulo, meses)
        self.periodo.setCurrentIndex(1)
        self.periodo.currentIndexChanged.connect(lambda *_: self.recarregar())
        filtros.addWidget(self.periodo)

        filtros.addWidget(widgets.rotulo_fraco("Agrupar por:"))
        self.agrupamento = QComboBox()
        self.agrupamento.addItem("Situação", "situacao")
        self.agrupamento.addItem("Mês", "mes")
        self.agrupamento.addItem("Empresa", "empresa")
        self.agrupamento.currentIndexChanged.connect(lambda *_: self.recarregar())
        filtros.addWidget(self.agrupamento)

        self.somente_pendentes = QCheckBox("Só o que espera ação")
        self.somente_pendentes.setChecked(True)
        self.somente_pendentes.toggled.connect(lambda *_: self.recarregar())
        filtros.addWidget(self.somente_pendentes)

        filtros.addWidget(widgets.rotulo_fraco("Canal:"))
        self.canal = ComboEnum(Canal)
        self.canal.insertItem(0, "Todos", None)
        self.canal.setCurrentIndex(0)
        self.canal.currentIndexChanged.connect(lambda *_: self.recarregar())
        filtros.addWidget(self.canal)

        filtros.addStretch(1)
        self.busca = CampoBusca("Buscar empresa…")
        self.busca.setMinimumWidth(240)
        self.busca.buscou.connect(lambda *_: self.recarregar())
        filtros.addWidget(self.busca)
        layout.addLayout(filtros)

        self.lista = PainelDeCartoes("Nenhuma cobrança registrada nesse período.")
        self.lista.selecao_mudou.connect(self._atualizar_resumo)
        self.lista.item_ativado.connect(self._responder_linha)
        layout.addWidget(self.lista, 1)

        rodape = QHBoxLayout()
        self.resumo = widgets.rotulo_fraco("")
        rodape.addWidget(self.resumo, 1)
        estornar = widgets.QPushButton("Estornar cobrança")
        estornar.clicked.connect(self._estornar)
        rodape.addWidget(estornar)
        layout.addLayout(rodape)

    # ------------------------------------------------------------------ dados
    def _desde(self) -> date | None:
        meses = self.periodo.currentData()
        if meses is None:
            return None
        referencia = self.contexto.data_referencia
        if meses == 0:
            return date(referencia.year, referencia.month, 1)
        inicio = somar_meses(date(referencia.year, referencia.month, 1), -(meses - 1))
        return date(inicio.year, inicio.month, 1)

    def _filtro(self) -> servico.Filtro:
        return servico.Filtro(
            termo=self.busca.text(),
            canal=self.canal.currentData(),
            somente_pendentes=self.somente_pendentes.isChecked(),
            desde=self._desde(),
            data_referencia=self.contexto.data_referencia,
        )

    def _cartao(self, linha: servico.LinhaAcompanhamento) -> DadosCartao:
        cor = tema.cor(CORES_SITUACAO.get(linha.situacao, "texto_fraco"), cores.tema_atual())
        datas = [
            DataCartao(
                "Cobrado em", f"{formatar_data(linha.data)} · há {linha.dias} dia(s)", cor
            )
        ]
        if linha.promessa:
            datas.append(
                DataCartao(
                    "Promessa", formatar_data(linha.promessa), tema.cor("roxo", cores.tema_atual())
                )
            )
        detalhes = [
            ("Canal", linha.canal.rotulo),
            ("Honorários", linha.competencias or f"{linha.quantidade}"),
            ("Valor na época", formatar_moeda(linha.lote.total_no_momento)),
        ]
        if linha.quitados:
            detalhes.append(("Quitados", f"{linha.quitados} de {linha.quantidade}"))
        acoes = [Acao("Registrar resposta", self._responder_linha, primaria=True)]
        if linha.texto:
            acoes.append(Acao("Ver mensagem", self._ver_mensagem))
        return DadosCartao(
            titulo=f"{linha.cliente.codigo} – {linha.cliente.nome}",
            subtitulo=(
                f"{linha.resultado.rotulo}"
                + (f" · {linha.observacao}" if linha.observacao else "")
            ),
            detalhes=detalhes,
            valor=formatar_moeda(linha.saldo_atual),
            valor_rotulo="Em aberto hoje",
            situacao=linha.situacao,
            cor=cor,
            item=linha,
            acoes=acoes,
            datas=datas,
        )

    def recarregar(self) -> None:
        self.contexto.atualizar()
        self.linhas = servico.listar(self.contexto.sessao, self._filtro())
        modo = self.agrupamento.currentData()
        if modo == "mes":
            grupos = servico.por_mes(self.linhas)
            descricoes = {}
        elif modo == "empresa":
            grupos = servico.por_empresa(self.linhas)
            descricoes = {}
        else:
            grupos = servico.por_situacao(self.linhas)
            descricoes = servico.DESCRICOES

        secoes = [
            SecaoCartoes(
                titulo=rotulo,
                subtitulo=descricoes.get(rotulo, ""),
                itens=itens,
                construtor=self._cartao,
                total=formatar_moeda(
                    sum((linha.saldo_atual for linha in itens), start=ZERO)
                ),
            )
            for rotulo, itens in grupos
        ]
        self.lista.definir_secoes(secoes)
        self._atualizar_resumo()

    def _atualizar_resumo(self) -> None:
        aguardando = sum(
            1 for linha in self.linhas if linha.situacao == servico.AGUARDANDO
        )
        total = sum((linha.saldo_atual for linha in self.linhas), start=ZERO)
        desde = self._desde()
        periodo = f"desde {formatar_data(desde)}" if desde else "todo o histórico"
        self.resumo.setText(
            f"{len(self.linhas)} cobrança(s) {periodo} · {aguardando} sem resposta "
            f"anotada · {formatar_moeda(total)} ainda em aberto"
        )

    # ------------------------------------------------------------------ ações
    def _selecionada(self) -> servico.LinhaAcompanhamento | None:
        linhas = self.lista.selecionados()
        if len(linhas) != 1:
            widgets.aviso(self, "Selecione uma cobrança da lista.")
            return None
        return linhas[0]

    def _responder(self) -> None:
        linha = self._selecionada()
        if linha is not None:
            self._responder_linha(linha)

    def _responder_linha(self, linha: servico.LinhaAcompanhamento) -> None:
        if DialogoResposta(self.contexto, linha, self).exec():
            self.recarregar()

    def _ver_mensagem(self, linha: servico.LinhaAcompanhamento) -> None:
        widgets.informar(self, linha.texto, "Mensagem enviada")

    def _cobrar(self) -> None:
        linha = self._selecionada()
        if linha is None:
            return
        pendentes = servico_cobrancas.linhas_em_aberto_do_cliente(
            self.contexto.sessao, linha.cliente.id, self.contexto.data_referencia
        )
        if not pendentes:
            widgets.informar(
                self, f"{linha.cliente.nome} não tem honorário em aberto.", "Nada a cobrar"
            )
            return
        dialogo = DialogoCobrar(self.contexto, linha.cliente, pendentes, self)
        dialogo.exec()
        if dialogo.registrou:
            self.recarregar()

    def _pagar(self) -> None:
        linha = self._selecionada()
        if linha is None:
            return
        abertos = [c.honorario for c in linha.cobrancas if c.honorario.status.cobravel]
        if not abertos:
            widgets.informar(self, "Os honorários desta cobrança já estão quitados.", "Tudo pago")
            return
        if DialogoPagamento(self.contexto, abertos[0], self).exec():
            self.recarregar()

    def _ficha(self) -> None:
        linha = self._selecionada()
        if linha is None:
            return
        DialogoFicha(self.contexto, linha.cliente, self).exec()
        self.recarregar()

    def _estornar(self) -> None:
        linha = self._selecionada()
        if linha is None:
            return
        from PySide6.QtWidgets import QInputDialog

        motivo, confirmou = QInputDialog.getText(
            self, "Estornar cobrança", "Motivo do estorno:"
        )
        if not confirmou or not motivo.strip():
            return

        def acao():
            for cobranca in linha.cobrancas:
                servico_cobrancas.estornar(self.contexto.sessao, cobranca, motivo)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.recarregar()
