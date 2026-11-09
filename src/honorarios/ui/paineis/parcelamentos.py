"""Parcelamentos: gerar e acompanhar os acordos que dividem honorários em parcelas.

Um cartão por parcelamento: quanto já entrou, quanto falta, a próxima parcela e
as atrasadas. As parcelas ficam aqui e saem das abas A vencer e Atrasados de
Vencimentos. As regras estão em ``servicos/parcelamentos.py``.
"""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...dominio.valores import ZERO, formatar_data, formatar_moeda
from ...servicos import parcelamentos as servico
from ..comum import cores, tema, widgets
from ..comum.campos import CampoBusca
from ..comum.cartoes import Acao, DadosCartao, DataCartao, PainelDeCartoes, SecaoCartoes
from ..contexto import Contexto
from ..dialogos.parcelas import DialogoParcelas, situacao_da_parcela
from ..dialogos.renegociacao import DialogoRenegociacao


class PainelParcelamentos(QWidget):
    titulo = "Parcelamentos"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.parcelamentos: list[servico.Parcelamento] = []
        self._montar()
        self.recarregar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self.cabecalho = widgets.Cabecalho(
            "Parcelamentos",
            "Honorários divididos em parcelas: o que já entrou, o que falta e as parcelas "
            "atrasadas.",
        )
        self.busca = CampoBusca("Buscar empresa…")
        self.busca.setMinimumWidth(220)
        self.busca.buscou.connect(lambda *_: self.recarregar_com_aviso())
        self.cabecalho.acoes.addWidget(self.busca)
        self.cabecalho.adicionar_botao("Atualizar", self.recarregar, atalho="F5")
        self.botao_novo = self.cabecalho.adicionar_botao(
            "Novo parcelamento", self._novo, primario=True, atalho="Ctrl+N")
        layout.addWidget(self.cabecalho)

        linha = QHBoxLayout()
        self.resumo = QLabel("")
        self.resumo.setObjectName("rankingCuriosidade")
        self.resumo.setWordWrap(True)
        linha.addWidget(self.resumo, 1)
        self.mostrar_cancelados = QCheckBox("Mostrar cancelados")
        self.mostrar_cancelados.toggled.connect(lambda *_: self.recarregar_com_aviso())
        linha.addWidget(self.mostrar_cancelados)
        layout.addLayout(linha)

        self.lista = PainelDeCartoes(
            "Nenhum parcelamento. Use \"Novo parcelamento\" para dividir honorários em "
            "parcelas.")
        self.lista.item_ativado.connect(self._ver_parcelas)
        layout.addWidget(self.lista, 1)
        self.aviso = widgets.rotulo_fraco("")
        layout.addWidget(self.aviso)

    # ------------------------------------------------------------------ dados
    def recarregar_com_aviso(self) -> None:
        with self.lista.carregando_durante():
            self.recarregar()

    def recarregar(self) -> None:
        self.contexto.atualizar()
        self.parcelamentos = servico.listar(
            self.contexto.sessao, self.contexto.data_referencia, self.busca.text(),
            incluir_cancelados=self.mostrar_cancelados.isChecked(),
        )
        atrasados = [p for p in self.parcelamentos if not p.cancelado and p.atrasadas]
        em_dia = [p for p in self.parcelamentos
                  if not p.cancelado and not p.atrasadas and not p.quitado]
        quitados = [p for p in self.parcelamentos if p.quitado]
        cancelados = [p for p in self.parcelamentos if p.cancelado]
        secoes = [
            SecaoCartoes("Com parcela atrasada", atrasados, self._cartao,
                         subtitulo="cobre a parcela vencida",
                         total=formatar_moeda(sum((p.falta for p in atrasados),
                                                  start=ZERO))),
            SecaoCartoes("Em dia", em_dia, self._cartao,
                         subtitulo="as próximas parcelas ainda não venceram",
                         total=formatar_moeda(sum((p.falta for p in em_dia),
                                                  start=ZERO))),
            SecaoCartoes("Quitados", quitados, self._cartao,
                         subtitulo="todas as parcelas pagas"),
        ]
        if self.mostrar_cancelados.isChecked():
            secoes.append(SecaoCartoes("Cancelados", cancelados, self._cartao,
                                       subtitulo="os honorários voltaram para Em aberto"))
        self.lista.definir_secoes(secoes)

        parcelas_atrasadas = sum(len(p.atrasadas) for p in atrasados)
        partes = [f"<b>{len(atrasados) + len(em_dia)}</b> em andamento"]
        if parcelas_atrasadas:
            partes.append(f"{parcelas_atrasadas} parcela(s) atrasada(s)")
        a_receber = sum((p.falta for p in atrasados + em_dia), start=ZERO)
        partes.append(f"a receber {formatar_moeda(a_receber)}")
        if quitados:
            partes.append(f"{len(quitados)} quitado(s)")
        self.resumo.setText(" · ".join(partes))

    # ----------------------------------------------------------------- cartões
    def _cor(self, nome: str):
        return tema.cor(nome, cores.tema_atual())

    def _cartao(self, parcelamento: servico.Parcelamento) -> DadosCartao:
        acordo, cliente = parcelamento.acordo, parcelamento.cliente
        total = len(parcelamento.validas) or acordo.parcelas
        pagas = len(parcelamento.pagas)
        detalhes = [
            ("Parcelado", formatar_moeda(acordo.valor_acordado)),
            ("Pago", formatar_moeda(parcelamento.pago)),
            ("Parcelas pagas", f"{pagas} de {total}"),
            ("Honorários", ", ".join(f"{h.tipo.nome} {h.competencia_rotulo}".strip()
                                     for h in parcelamento.originais) or "—"),
        ]
        juros = sum((p.linha.atualizacao.juros for p in parcelamento.abertas), start=ZERO)
        if juros or any(p.linha.atualizacao.juros_manual for p in parcelamento.abertas):
            manual = any(p.linha.atualizacao.juros_manual for p in parcelamento.abertas)
            detalhes.append(("Juros ✎" if manual else "Juros", formatar_moeda(juros)))
        if acordo.observacoes:
            detalhes.append(("Observações", acordo.observacoes))
        datas, acoes = [], []
        opcoes = [
            Acao("Ver parcelas", self._ver_parcelas, "Todas as parcelas, com o que foi pago"),
            Acao("Ficha da empresa", self._ficha, "Tudo da empresa numa tela só"),
        ]
        if parcelamento.cancelado:
            situacao = f"Cancelado em {formatar_data(acordo.cancelada_em.date())}"
            cor = self._cor("texto_fraco")
        elif parcelamento.quitado:
            situacao = "✓ Quitado"
            cor = self._cor("pago")
        else:
            proxima = parcelamento.proxima
            atrasadas = parcelamento.atrasadas
            if atrasadas:
                situacao = (f"Parcela {atrasadas[0].numero}/{total} atrasada há "
                            f"{atrasadas[0].linha.atualizacao.dias_atraso} dia(s)"
                            if len(atrasadas) == 1 else f"{len(atrasadas)} parcelas atrasadas")
                cor = self._cor("atrasado")
                acoes.append(Acao("Cobrar", self._cobrar, "Cobrar as parcelas atrasadas",
                                  primaria=True))
            else:
                situacao = f"{pagas} de {total} pagas"
                cor = self._cor("destaque_texto")
            if proxima is not None:
                datas.append(DataCartao(
                    "Próxima:",
                    f"{proxima.numero}/{total} · {formatar_data(proxima.honorario.vencimento)} · "
                    f"{formatar_moeda(proxima.linha.atualizacao.total)}",
                    self._cor("atrasado") if proxima.atrasada else None,
                ))
                acoes.append(Acao("Confirmar pagamento", self._pagar_proxima,
                                  f"Pagamento da parcela {proxima.numero}/{total}",
                                  pagamento=True))
            if any(p.linha.atualizacao.juros > 0 for p in atrasadas):
                opcoes.insert(1, Acao("Tirar o juros das atrasadas…", self._tirar_juros,
                                      "Fica só o valor das parcelas vencidas", separar=True))
            opcoes.append(Acao("Cancelar parcelamento…", self._cancelar,
                               "Os honorários voltam para Em aberto", separar=True))
        return DadosCartao(
            titulo=f"{cliente.codigo} – {cliente.nome}",
            subtitulo=(f"Parcelamento de {formatar_data(acordo.data)} · {total}x · "
                       f"{len(parcelamento.originais)} honorário(s)"),
            detalhes=detalhes,
            valor=formatar_moeda(parcelamento.falta) if not parcelamento.cancelado else "",
            valor_rotulo="Falta",
            situacao=situacao,
            cor=cor,
            item=parcelamento,
            datas=datas,
            acoes=acoes,
            opcoes=opcoes,
        )

    # ------------------------------------------------------------------ ações
    def _depois(self, texto: str = "") -> None:
        self.recarregar()
        if texto:
            self.aviso.setText(texto)

    def _novo(self) -> None:
        dialogo = DialogoRenegociacao(self.contexto, parent=self)
        if dialogo.exec():
            acordo = dialogo.acordo
            self._depois(f"✓ Parcelamento de {acordo.cliente.nome}: "
                         f"{formatar_moeda(acordo.valor_acordado)} em {acordo.parcelas} "
                         "parcela(s).")

    def _ver_parcelas(self, parcelamento: servico.Parcelamento) -> None:
        dialogo = DialogoParcelas(self.contexto, parcelamento, self)
        dialogo.exec()
        if dialogo.mudou:
            self.recarregar()

    def _pagar_proxima(self, parcelamento: servico.Parcelamento) -> None:
        proxima = parcelamento.proxima
        if proxima is None:
            return
        from ..dialogos.pagamento import DialogoPagamento

        if DialogoPagamento(self.contexto, proxima.honorario, self).exec():
            self._depois(f"✓ Parcela {proxima.numero} de {parcelamento.cliente.nome} paga.")

    def _cobrar(self, parcelamento: servico.Parcelamento) -> None:
        linhas = [p.linha for p in parcelamento.atrasadas]
        if not linhas:
            return
        from ..dialogos.cobrar import DialogoCobrar

        dialogo = DialogoCobrar(self.contexto, parcelamento.cliente, linhas, self)
        dialogo.exec()
        if dialogo.registrou:
            self.recarregar()

    def _ficha(self, parcelamento: servico.Parcelamento) -> None:
        from ..dialogos.ficha import DialogoFicha

        DialogoFicha(self.contexto, parcelamento.cliente, self).exec()
        self.recarregar()

    def _cancelar(self, parcelamento: servico.Parcelamento) -> None:
        from PySide6.QtWidgets import QInputDialog

        motivo, confirmou = QInputDialog.getText(
            self, "Cancelar parcelamento", "Motivo do cancelamento:")
        if not confirmou:
            return
        situacoes = "; ".join(f"{p.numero}: {situacao_da_parcela(p)}"
                              for p in parcelamento.parcelas)
        if not widgets.confirmar(
            self, f"Cancelar o parcelamento de {parcelamento.cliente.nome}?",
            "Cancelar parcelamento",
            "Os honorários parcelados voltam para Em aberto, com o juros desde o "
            f"vencimento de cada um, e as parcelas são canceladas. ({situacoes})",
            acao="Cancelar parcelamento", tipo="perigo",
        ):
            return

        def acao():
            servico.cancelar(self.contexto.sessao, parcelamento, motivo)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self._depois(f"Parcelamento de {parcelamento.cliente.nome} cancelado: os honorários "
                     "voltaram para Vencimentos.")

    def _tirar_juros(self, parcelamento: servico.Parcelamento) -> None:
        from ...dominio.valores import hoje
        from ...servicos import honorarios as servico_honorarios

        alvo = [p for p in parcelamento.atrasadas if p.linha.atualizacao.juros > 0]
        juros = sum((p.linha.atualizacao.juros for p in alvo), start=ZERO)
        if not alvo or not widgets.confirmar(
            self, f"Tirar {formatar_moeda(juros)} de juros de {parcelamento.cliente.nome}?",
            "Tirar o juros",
            f"{len(alvo)} parcela(s) atrasada(s) ficam só com o valor, a partir de hoje. "
            "Para acertar parcela por parcela ou voltar ao calculado, use Ver parcelas → "
            "Juros….", acao="Tirar o juros",
        ):
            return

        def acao():
            for parcela in alvo:
                servico_honorarios.ajustar_juros(self.contexto.sessao, parcela.honorario,
                                                 ZERO, hoje())
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self._depois(f"Juros tirado de {len(alvo)} parcela(s) de {parcelamento.cliente.nome}.")
