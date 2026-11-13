"""Tarefas: enviar o honorário trimestral quando o trimestre da empresa se completa,
cada parcela dos parcelamentos alguns dias antes do vencimento e o pagamento dos
acordos feitos no Cobrar até a data combinada.

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
            "Envio do honorário trimestral (o trimestre conta da competência em que a "
            "empresa virou cliente), das parcelas dos parcelamentos e o pagamento dos "
            "acordos.",
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
        dias = servico.dias_antes_da_parcela(self.contexto.sessao)
        secoes = [
            SecaoCartoes("Enviar parcelas", quadro.parcelas, self._cartao_parcela,
                         subtitulo=f"parcelamentos: lembrete {dias} dia(s) antes do "
                                   "vencimento de cada parcela"),
            SecaoCartoes("Pagamento de acordos", quadro.acordos, self._cartao_acordo,
                         subtitulo="acordo feito no Cobrar: acompanhe até a data combinada "
                                   "(pago, sai sozinho)"),
            SecaoCartoes("Para fazer", quadro.pendentes, self._cartao_pendente,
                         subtitulo="trimestre completo: é hora de enviar o honorário"),
            SecaoCartoes("Próximos trimestres", quadro.proximas, self._cartao_proximo,
                         subtitulo="quando cada empresa completa o próximo"),
            SecaoCartoes("Sem data de entrada", quadro.sem_data, self._cartao_sem_data,
                         subtitulo="honorário trimestral, mas sem \"Cliente do escritório "
                                   "desde\" no cadastro: preencha para entrar nas tarefas"),
            SecaoCartoes("Próximas parcelas", quadro.parcelas_proximas,
                         self._cartao_parcela_proxima,
                         subtitulo="a próxima de cada parcelamento, com o dia do lembrete"),
            SecaoCartoes("Feitas", quadro.feitas, self._cartao_feito,
                         subtitulo="com baixa (dá para desfazer)"),
            SecaoCartoes("Parcelas enviadas", quadro.parcelas_feitas, self._cartao_parcela_feita,
                         subtitulo="com baixa (dá para desfazer)"),
            SecaoCartoes("Acordos com baixa", quadro.acordos_feitos, self._cartao_acordo_feito,
                         subtitulo="dá para desfazer"),
        ]
        self.lista.definir_secoes(secoes)
        self.botao_todas.setEnabled(bool(quadro.pendentes))
        partes = [f"<b>{quadro.para_fazer}</b> para fazer"]
        if quadro.acordos:
            partes.append(f"{len(quadro.acordos)} acordo(s) para acompanhar")
        if quadro.parcelas:
            partes.append(f"{len(quadro.parcelas)} parcela(s) para enviar")
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
            "titulo": f"{cliente.rotulo}",
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
            titulo=f"{cliente.rotulo}",
            subtitulo="Tem honorário trimestral, mas falta a data de entrada",
            situacao="Falta a data",
            cor=self._cor("texto_fraco"),
            item=cliente,
            acoes=[Acao("Preencher a data", self._abrir_cadastro_do_item,
                        "Abre o cadastro: campo \"Cliente do escritório desde\"",
                        primaria=True)],
        )

    def _base_parcela(self, tarefa: servico.TarefaParcela) -> dict:
        cliente, honorario = tarefa.cliente, tarefa.honorario
        return {
            "titulo": f"{cliente.rotulo}",
            "subtitulo": f"Enviar a parcela {tarefa.periodo} do parcelamento",
            "detalhes": [
                ("Valor", formatar_moeda(honorario.valor_original)),
                ("Parcelamento de", formatar_data(tarefa.parcelamento.acordo.data)),
            ],
            "item": tarefa,
        }

    def _cartao_parcela(self, tarefa: servico.TarefaParcela) -> DadosCartao:
        referencia = self.contexto.data_referencia
        faltam = (tarefa.vencimento - referencia).days
        if faltam < 0:
            situacao, cor = f"Venceu há {-faltam} dia(s)", self._cor("atrasado")
        elif faltam == 0:
            situacao, cor = "Vence hoje", self._cor("atencao")
        else:
            situacao, cor = f"Vence em {faltam} dia(s)", self._cor("atencao")
        return DadosCartao(
            **self._base_parcela(tarefa),
            situacao=situacao,
            cor=cor,
            datas=[DataCartao("Vencimento", formatar_data(tarefa.vencimento), cor)],
            acoes=[
                Acao("Ver parcelas", self._ver_parcelas, "Todas as parcelas do parcelamento"),
                Acao("Enviar lembrete", self._enviar_parcela,
                     "Mensagem com o valor e o vencimento da parcela; ao registrar, dá baixa",
                     primaria=True),
                Acao("Dar baixa", self._dar_baixa, "A parcela já foi enviada ao cliente",
                     pagamento=True),
            ],
        )

    def _cartao_parcela_proxima(self, tarefa: servico.TarefaParcela) -> DadosCartao:
        faltam = (tarefa.prazo - self.contexto.data_referencia).days
        return DadosCartao(
            **self._base_parcela(tarefa),
            situacao=f"Lembrete em {faltam} dia(s)",
            cor=self._cor("destaque_texto"),
            datas=[DataCartao("Lembrar em", formatar_data(tarefa.prazo)),
                   DataCartao("Vencimento", formatar_data(tarefa.vencimento))],
            acoes=[Acao("Ver parcelas", self._ver_parcelas,
                        "Todas as parcelas do parcelamento")],
        )

    def _cartao_parcela_feita(self, tarefa: servico.TarefaParcela) -> DadosCartao:
        return DadosCartao(
            **self._base_parcela(tarefa),
            situacao=f"Enviada em {formatar_data(tarefa.feita.concluida_em)}",
            cor=self._cor("pago"),
            datas=[DataCartao("Vencimento", formatar_data(tarefa.vencimento))],
            acoes=[Acao("Desfazer baixa", self._desfazer, "Volta para as parcelas a enviar")],
        )

    def _base_acordo(self, tarefa: servico.TarefaAcordo) -> dict:
        cliente = tarefa.cliente
        honorarios = ", ".join(f"{h.tipo.nome} {h.competencia_rotulo}".strip()
                               for h in tarefa.honorarios)
        return {
            "titulo": f"{cliente.rotulo}",
            "subtitulo": f"Pagamento do acordo · {formatar_moeda(tarefa.total)} até "
                         f"{formatar_data(tarefa.vencimento)}",
            "detalhes": [
                ("Honorários", honorarios),
                ("Valor do acordo", formatar_moeda(tarefa.total)),
                ("Valores de", formatar_data(tarefa.data_base)),
            ],
            "item": tarefa,
        }

    def _cartao_acordo(self, tarefa: servico.TarefaAcordo) -> DadosCartao:
        faltam = (tarefa.vencimento - self.contexto.data_referencia).days
        if faltam < 0:
            situacao = f"Venceu há {-faltam} dia(s) — o juros voltou a correr"
            cor = self._cor("atrasado")
        elif faltam == 0:
            situacao, cor = "Vence hoje", self._cor("atencao")
        else:
            situacao, cor = f"Vence em {faltam} dia(s)", self._cor("destaque_texto")
        dados = self._base_acordo(tarefa)
        if len(tarefa.em_aberto) < len(tarefa.honorarios):
            dados["detalhes"].append(
                ("Em aberto", f"{len(tarefa.em_aberto)} de {len(tarefa.honorarios)}"))
        return DadosCartao(
            **dados,
            situacao=situacao,
            cor=cor,
            datas=[DataCartao("Pagar até", formatar_data(tarefa.vencimento), cor)],
            acoes=[
                Acao("Cadastro", self._abrir_cadastro_do_item, "Abrir o painel do cliente"),
                Acao("Cobrar", self._cobrar_acordo,
                     "Lembrar o cliente do acordo (ou combinar outro)", primaria=True),
                Acao("Dar baixa", self._dar_baixa,
                     "Não precisa mais acompanhar este acordo", pagamento=True),
            ],
        )

    def _cartao_acordo_feito(self, tarefa: servico.TarefaAcordo) -> DadosCartao:
        return DadosCartao(
            **self._base_acordo(tarefa),
            situacao=f"Baixa em {formatar_data(tarefa.feita.concluida_em)}",
            cor=self._cor("pago"),
            datas=[DataCartao("Pagar até", formatar_data(tarefa.vencimento))],
            acoes=[Acao("Desfazer baixa", self._desfazer,
                        "Volta para os acordos a acompanhar")],
        )

    # ------------------------------------------------------------------ ações
    def _cobrar_acordo(self, tarefa: servico.TarefaAcordo) -> None:
        from ...servicos import honorarios as servico_honorarios
        from ..dialogos.cobrar import DialogoCobrar

        referencia = self.contexto.data_referencia
        linhas = [servico_honorarios.montar_linha(h, data_referencia=referencia)
                  for h in tarefa.em_aberto]
        if not linhas:
            return
        DialogoCobrar(self.contexto, tarefa.cliente, linhas, self).exec()
        self.recarregar()

    def _ver_parcelas(self, tarefa: servico.TarefaParcela) -> None:
        from ..dialogos.parcelas import DialogoParcelas

        dialogo = DialogoParcelas(self.contexto, tarefa.parcelamento, self)
        dialogo.exec()
        if dialogo.mudou:
            self.recarregar()

    def _enviar_parcela(self, tarefa: servico.TarefaParcela) -> None:
        """A mensagem da parcela (o lembrete do Cobrar); registrada, a tarefa tem baixa."""
        from ..dialogos.cobrar import DialogoCobrar

        dialogo = DialogoCobrar(self.contexto, tarefa.cliente, [tarefa.parcela.linha], self)
        # a parcela ainda vai vencer: o valor do dia do vencimento, com o juros até lá
        dialogo.valores_ate(tarefa.parcela.honorario.vencimento)
        dialogo.exec()
        if dialogo.registrou:
            self._dar_baixa(tarefa)

    def _dar_baixa(self, tarefa: servico.TarefaTrimestral) -> None:
        def acao():
            servico.concluir(self.contexto.sessao, tarefa)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.recarregar()
        if isinstance(tarefa, servico.TarefaParcela):
            self.aviso.setText(f"✓ Parcela {tarefa.periodo} de {tarefa.cliente.nome} enviada. "
                               "Se foi engano, \"Desfazer baixa\" em Parcelas enviadas.")
            return
        if isinstance(tarefa, servico.TarefaAcordo):
            self.aviso.setText(f"✓ Acordo de {tarefa.cliente.nome} com baixa. Se foi engano, "
                               "\"Desfazer baixa\" em Acordos com baixa.")
            return
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
        rotulo = ("parcela" if isinstance(tarefa, servico.TarefaParcela)
                  else "acordo" if isinstance(tarefa, servico.TarefaAcordo) else "trimestre")
        self.aviso.setText(f"Baixa desfeita: {tarefa.cliente.nome}, {rotulo} {tarefa.periodo}.")

    def _abrir_cadastro_do_item(self, item) -> None:
        from ..dialogos.cliente import DialogoCliente

        if isinstance(item, servico.TarefaParcela):   # a parcela leva às parcelas
            self._ver_parcelas(item)
            return
        cliente = (item.cliente
                   if isinstance(item, servico.TarefaTrimestral | servico.TarefaAcordo)
                   else item)
        if DialogoCliente(self.contexto, cliente, self).exec():
            self.recarregar()
