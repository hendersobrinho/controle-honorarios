"""Tarefas: enviar o honorário trimestral quando o trimestre da empresa se completa.

O trimestre conta da competência em que a empresa virou cliente do escritório
(campo "Cliente do escritório desde", no cadastro), não do trimestre do ano. As
regras estão em ``servicos/tarefas.py``.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...dominio.valores import formatar_data, formatar_moeda
from ...servicos import tarefas as servico
from ..comum import cores, tema, widgets
from ..comum.cartoes import Acao, DadosCartao, DataCartao, PainelDeCartoes, SecaoCartoes
from ..contexto import Contexto

ATRASO_FORTE = 15   # dias esperando: a partir daqui a faixa fica vermelha


class PainelTarefas(QWidget):
    titulo = "Tarefas"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.quadro = servico.Quadro()
        self._montar()
        self.recarregar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self.cabecalho = widgets.Cabecalho(
            "Tarefas",
            "Envio do honorário trimestral: o trimestre conta da competência em que a "
            "empresa virou cliente do escritório.",
        )
        self.botao_todas = self.cabecalho.adicionar_botao(
            "Dar baixa em todas", self._baixa_em_todas)
        self.botao_todas.setToolTip(
            "Para o começo: dá baixa nos trimestres que já foram enviados antes de o "
            "sistema controlar")
        self.cabecalho.adicionar_botao("Atualizar", self.recarregar, atalho="F5")
        layout.addWidget(self.cabecalho)

        resumo = QHBoxLayout()
        self.resumo = QLabel("")
        self.resumo.setObjectName("rankingCuriosidade")
        self.resumo.setWordWrap(True)
        resumo.addWidget(self.resumo, 1)
        layout.addLayout(resumo)

        self.lista = PainelDeCartoes("Nenhuma tarefa por enquanto.")
        self.lista.item_ativado.connect(self._abrir_cadastro_do_item)
        layout.addWidget(self.lista, 1)
        self.aviso = widgets.rotulo_fraco("")
        layout.addWidget(self.aviso)

    # ------------------------------------------------------------------ dados
    def recarregar(self) -> None:
        self.contexto.atualizar()
        self.quadro = servico.quadro(self.contexto.sessao, self.contexto.data_referencia)
        quadro = self.quadro
        secoes = [
            SecaoCartoes("Para fazer", quadro.pendentes, self._cartao_pendente,
                         subtitulo="trimestre completo: é hora de enviar o honorário"),
            SecaoCartoes("Próximos trimestres", quadro.proximas, self._cartao_proximo,
                         subtitulo="quando cada empresa completa o próximo"),
            SecaoCartoes("Sem data de entrada", quadro.sem_data, self._cartao_sem_data,
                         subtitulo="honorário trimestral, mas sem \"Cliente do escritório "
                                   "desde\" no cadastro: preencha para entrar nas tarefas"),
            SecaoCartoes("Feitas", quadro.feitas, self._cartao_feito,
                         subtitulo="com baixa (dá para desfazer)"),
        ]
        self.lista.definir_secoes(secoes)
        self.botao_todas.setEnabled(bool(quadro.pendentes))
        partes = [f"<b>{len(quadro.pendentes)}</b> para fazer"]
        atrasadas = sum(1 for t in quadro.pendentes
                        if t.dias_esperando(self.contexto.data_referencia) > ATRASO_FORTE)
        if atrasadas:
            partes.append(f"{atrasadas} esperando há mais de {ATRASO_FORTE} dias")
        if quadro.proximas:
            proxima = quadro.proximas[0]
            partes.append(f"próxima em {formatar_data(proxima.prazo)} "
                          f"({proxima.cliente.nome})")
        if quadro.sem_data:
            partes.append(f"{len(quadro.sem_data)} trimestral(is) sem data de entrada")
        self.resumo.setText(" · ".join(partes))

    # ----------------------------------------------------------------- cartões
    def _cor(self, nome: str):
        return tema.cor(nome, cores.tema_atual())

    def _base(self, tarefa: servico.TarefaTrimestral) -> dict:
        cliente = tarefa.cliente
        return {
            "titulo": f"{cliente.codigo} – {cliente.nome}",
            "subtitulo": f"Enviar o honorário trimestral · {tarefa.contrato.tipo.nome}",
            "detalhes": [
                ("Trimestre", tarefa.periodo),
                ("Valor do contrato", formatar_moeda(tarefa.contrato.valor)),
                ("Cliente desde", formatar_data(cliente.cliente_desde)),
            ],
            "item": tarefa,
        }

    def _cartao_pendente(self, tarefa: servico.TarefaTrimestral) -> DadosCartao:
        dias = tarefa.dias_esperando(self.contexto.data_referencia)
        cor = self._cor("atrasado" if dias > ATRASO_FORTE else "atencao")
        situacao = "Pronta para enviar" if dias == 0 else f"Esperando há {dias} dia(s)"
        return DadosCartao(
            **self._base(tarefa),
            situacao=situacao,
            cor=cor,
            datas=[DataCartao("Trimestre completou em", formatar_data(tarefa.fim)),
                   DataCartao("Enviar desde", formatar_data(tarefa.prazo), cor)],
            acoes=[
                Acao("Cadastro", self._abrir_cadastro_do_item, "Abrir o cadastro da empresa"),
                Acao("Dar baixa", self._dar_baixa, "O honorário deste trimestre foi enviado",
                     pagamento=True),
            ],
        )

    def _cartao_proximo(self, tarefa: servico.TarefaTrimestral) -> DadosCartao:
        faltam = (tarefa.prazo - self.contexto.data_referencia).days
        return DadosCartao(
            **self._base(tarefa),
            situacao=f"Em {faltam} dia(s)",
            cor=self._cor("destaque_texto"),
            datas=[DataCartao("Enviar a partir de", formatar_data(tarefa.prazo))],
            acoes=[Acao("Cadastro", self._abrir_cadastro_do_item,
                        "Abrir o cadastro da empresa")],
        )

    def _cartao_feito(self, tarefa: servico.TarefaTrimestral) -> DadosCartao:
        dados = self._base(tarefa)
        if tarefa.feita.observacao:
            dados["detalhes"].append(("Observação", tarefa.feita.observacao))
        return DadosCartao(
            **dados,
            situacao=f"Baixa em {formatar_data(tarefa.feita.concluida_em)}",
            cor=self._cor("pago"),
            datas=[DataCartao("Enviar desde", formatar_data(tarefa.prazo))],
            acoes=[Acao("Desfazer baixa", self._desfazer, "Volta para as pendentes")],
        )

    def _cartao_sem_data(self, cliente) -> DadosCartao:
        return DadosCartao(
            titulo=f"{cliente.codigo} – {cliente.nome}",
            subtitulo="Tem honorário trimestral, mas falta a data de entrada",
            situacao="Falta a data",
            cor=self._cor("texto_fraco"),
            item=cliente,
            acoes=[Acao("Preencher a data", self._abrir_cadastro_do_item,
                        "Abre o cadastro: campo \"Cliente do escritório desde\"",
                        primaria=True)],
        )

    # ------------------------------------------------------------------ ações
    def _dar_baixa(self, tarefa: servico.TarefaTrimestral) -> None:
        def acao():
            servico.concluir(self.contexto.sessao, tarefa)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.recarregar()
        self.aviso.setText(f"✓ Baixa: {tarefa.cliente.nome}, trimestre {tarefa.periodo}. "
                           "Se foi engano, \"Desfazer baixa\" em Feitas.")

    def _baixa_em_todas(self) -> None:
        pendentes = list(self.quadro.pendentes)
        if not pendentes or not widgets.confirmar(
            self, f"Dar baixa nas {len(pendentes)} tarefas pendentes?", "Dar baixa em todas",
            "Serve para o começo: os trimestres que já foram enviados antes de o sistema "
            "controlar. Cada uma pode ser desfeita depois, em Feitas.",
            acao="Dar baixa em todas",
        ):
            return

        def acao():
            for tarefa in pendentes:
                servico.concluir(self.contexto.sessao, tarefa, "Baixa em lote")
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.recarregar()
        self.aviso.setText(f"✓ Baixa em {len(pendentes)} tarefa(s).")

    def _desfazer(self, tarefa: servico.TarefaTrimestral) -> None:
        def acao():
            servico.reabrir(self.contexto.sessao, tarefa.chave)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.recarregar()
        self.aviso.setText(f"Baixa desfeita: {tarefa.cliente.nome}, trimestre {tarefa.periodo}.")

    def _abrir_cadastro_do_item(self, item) -> None:
        from ..dialogos.cliente import DialogoCliente

        cliente = item.cliente if isinstance(item, servico.TarefaTrimestral) else item
        if DialogoCliente(self.contexto, cliente, self).exec():
            self.recarregar()
