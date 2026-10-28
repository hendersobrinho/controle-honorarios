"""Histórico de um honorário: datas, cobranças e pagamentos, em cartões."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QFormLayout, QGroupBox, QHBoxLayout, QVBoxLayout

from ...dominio.valores import formatar_data, formatar_moeda
from ...servicos import acompanhamento as servico_acompanhamento
from ...servicos import historico as servico
from ..comum import cores, tema, widgets
from ..comum.campos import Rotulo
from ..comum.cartoes import Acao, DadosCartao, PainelDeCartoes, SecaoCartoes
from ..contexto import Contexto

CORES_EVENTO = {
    servico.LANCAMENTO: "texto_fraco",
    servico.ENVIO: "texto_fraco",
    servico.COBRANCA: "destaque_texto",
    servico.RESPOSTA: "atencao",
    servico.PAGAMENTO: "pago",
    servico.ESTORNO: "atrasado",
    servico.CANCELAMENTO: "atrasado",
    servico.RENEGOCIACAO: "atencao",
}


class DialogoHistorico(QDialog):
    def __init__(self, contexto: Contexto, honorario, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.honorario = honorario
        self.setWindowTitle(f"Histórico – {honorario.cliente.nome}")
        self.resize(820, 700)
        self._montar()
        self.recarregar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        self.cabecalho = widgets.Cabecalho(self.honorario.cliente.nome)
        self.cabecalho.adicionar_botao("Atualizar", self.recarregar, atalho="F5")
        layout.addWidget(self.cabecalho)

        grupo = QGroupBox("Situação")
        formulario = QFormLayout(grupo)
        self.campo_situacao = Rotulo()
        formulario.addRow("Situação:", self.campo_situacao)
        self.campo_valores = Rotulo()
        formulario.addRow("Valores:", self.campo_valores)
        self.campo_cobrancas = Rotulo()
        formulario.addRow("Cobranças:", self.campo_cobrancas)
        layout.addWidget(grupo)

        self.lista = PainelDeCartoes("Nada registrado ainda para este honorário.")
        layout.addWidget(self.lista, 1)

        rodape = QHBoxLayout()
        rodape.addStretch(1)
        fechar = widgets.QPushButton("Fechar")
        fechar.clicked.connect(self.accept)
        rodape.addWidget(fechar)
        layout.addLayout(rodape)

    # ------------------------------------------------------------------ dados
    def recarregar(self) -> None:
        self.contexto.atualizar()
        sessao = self.contexto.sessao
        dados = servico.resumo(sessao, self.honorario, self.contexto.data_referencia)
        honorario = self.honorario

        self.cabecalho.definir_subtitulo(
            f"{honorario.tipo.nome} · {honorario.competencia_rotulo or honorario.descricao} · "
            f"vencimento {formatar_data(honorario.vencimento)}"
        )
        self.campo_situacao.setText(dados.situacao)
        self.campo_valores.setText(
            f"Original {formatar_moeda(dados.atualizacao.valor_original)} · "
            f"juros {formatar_moeda(dados.atualizacao.juros)} · "
            f"total {formatar_moeda(dados.atualizacao.total)}"
        )
        promessa = (
            f" · promessa para {formatar_data(dados.promessa)}" if dados.promessa else ""
        )
        ultima = (
            f"última em {formatar_data(dados.ultima_cobranca)}"
            if dados.ultima_cobranca
            else "nunca cobrado"
        )
        self.campo_cobrancas.setText(f"{dados.cobrancas} · {ultima}{promessa}")

        eventos = servico.do_honorario(sessao, honorario, self.contexto.data_referencia)
        self.lista.definir_secoes(
            [
                SecaoCartoes(
                    "Linha do tempo",
                    itens=eventos,
                    construtor=self._cartao,
                    subtitulo="mais recente primeiro",
                )
            ],
            preservar_selecao=False,
        )

    def _cartao(self, evento: servico.Evento) -> DadosCartao:
        detalhes = [("Quando", formatar_data(evento.quando))]
        if evento.tipo == servico.COBRANCA:
            detalhes.append(("Como", evento.rotulo_lote))
            if evento.companheiros:
                detalhes.append(("Junto com", evento.resumo_companheiros))
        acoes = []
        if evento.texto:
            acoes.append(Acao("Ver mensagem", self._ver_mensagem, "Mensagem exata enviada"))
        if evento.cobranca is not None and evento.tipo == servico.COBRANCA:
            acoes.append(Acao("Registrar resposta", self._responder))
        return DadosCartao(
            titulo=evento.titulo,
            subtitulo=evento.detalhe,
            detalhes=detalhes,
            situacao=evento.tipo,
            valor=formatar_moeda(evento.valor) if evento.valor is not None else "",
            cor=tema.cor(CORES_EVENTO.get(evento.tipo, "texto_fraco"), cores.tema_atual()),
            item=evento,
            acoes=acoes,
        )

    # ------------------------------------------------------------------ ações
    def _ver_mensagem(self, evento: servico.Evento) -> None:
        widgets.informar(self, evento.texto, "Mensagem enviada")

    def _responder(self, evento: servico.Evento) -> None:
        cobranca = evento.cobranca
        if cobranca is None or cobranca.lote is None:
            widgets.aviso(
                self, "Esta cobrança não tem mensagem associada (veio da planilha antiga)."
            )
            return
        from .resposta import DialogoResposta

        linha = servico_acompanhamento.linha_do_lote(
            self.contexto.sessao, cobranca.lote, self.contexto.data_referencia
        )
        if DialogoResposta(self.contexto, linha, self).exec():
            self.recarregar()
