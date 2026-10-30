"""Ficha da empresa: tudo do cliente junto, com o botão Cobrar sempre visível."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...dominio.valores import (
    formatar_data,
    formatar_data_hora,
    formatar_moeda,
    formatar_telefone,
)
from ...servicos import ficha as servico_ficha
from ...servicos import pagamentos as servico_pagamentos
from ..comum import cores, widgets
from ..comum.campos import Rotulo
from ..comum.tabelas import (
    Coluna,
    ModeloTabela,
    ajustar_colunas,
    coluna_data,
    coluna_inteiro,
    coluna_moeda,
    item_atual,
    preparar_tabela,
)
from ..contexto import Contexto
from .cobrar import DialogoCobrar
from .honorario import DialogoHonorario
from .pagamento import DialogoPagamento


def colunas_honorario(
    mostrar_cobranca: bool = True,
    mostrar_cliente: bool = False,
    mostrar_grupo: bool = True,
) -> list[Coluna]:
    """Colunas da tabela de honorários, reaproveitadas por todas as telas."""
    cor = lambda linha: cores.cor_de_linha(linha)  # noqa: E731
    colunas = []
    if mostrar_cliente:
        colunas.append(
            Coluna(
                "Cliente",
                lambda linha: f"{linha.cliente.codigo} – {linha.cliente.nome}",
                cor=cor,
                largura=280,
            )
        )
    colunas += [
        Coluna("Tipo", lambda linha: linha.honorario.tipo.nome, cor=cor),
    ]
    if mostrar_grupo:
        colunas.append(Coluna("Grupo", lambda linha: linha.grupo.nome))
    colunas += [
        Coluna(
            "Competência",
            lambda linha: linha.honorario.competencia_rotulo,
            alinhamento=Qt.AlignmentFlag.AlignCenter,
        ),
        coluna_data("Vencimento", lambda linha: linha.honorario.vencimento),
        coluna_inteiro("Atraso", lambda linha: linha.atualizacao.dias_atraso, cor=cor),
        coluna_moeda("Valor", lambda linha: linha.atualizacao.valor_original),
        coluna_moeda("Juros", lambda linha: linha.atualizacao.juros),
        coluna_moeda("Total atualizado", lambda linha: linha.atualizacao.total, negrito=True),
    ]
    if mostrar_cobranca:
        colunas += [
            coluna_inteiro("Cobranças", lambda linha: linha.cobrancas),
            coluna_data("Última cobrança", lambda linha: linha.ultima_cobranca),
            coluna_data("Promessa", lambda linha: linha.promessa),
        ]
    return colunas


class DialogoFicha(QDialog):
    def __init__(self, contexto: Contexto, cliente, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.cliente = cliente
        self.setWindowTitle(f"Ficha – {cliente.nome}")
        self.resize(1080, 720)
        self._montar()
        self.recarregar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        self.cabecalho = widgets.Cabecalho(self.cliente.nome)
        self.cabecalho.adicionar_botao("Cobrar", self._cobrar, primario=True, atalho="Ctrl+B")
        self.cabecalho.adicionar_botao("Novo honorário", self._novo_honorario)
        botao = self.cabecalho.adicionar_botao("Editar cadastro", self._editar_cadastro)
        botao.setToolTip("Dados, juros, contatos, data de entrada e honorário recorrente")
        self.botao_suspensao = self.cabecalho.adicionar_botao(
            "Suspender cobrança", self._alternar_suspensao
        )
        self.cabecalho.adicionar_botao("Atualizar", self.recarregar, atalho="F5")
        layout.addWidget(self.cabecalho)

        self.abas = QTabWidget()
        layout.addWidget(self.abas, 1)

        # resumo
        resumo = QWidget()
        caixa_resumo = QVBoxLayout(resumo)
        cartoes = QHBoxLayout()
        self.cartao_total = widgets.Cartao("Total em aberto atualizado")
        self.cartao_qtd = widgets.Cartao("Boletos em aberto")
        self.cartao_atraso = widgets.Cartao("Maior atraso")
        self.cartao_juros = widgets.Cartao(
            "Juros ao dia", dica="Use \"Alterar juros\" no topo para mudar o valor"
        )
        for cartao in (self.cartao_total, self.cartao_qtd, self.cartao_atraso, self.cartao_juros):
            cartoes.addWidget(cartao)
        caixa_resumo.addLayout(cartoes)

        dados = QGroupBox("Cadastro")
        formulario = QFormLayout(dados)
        self.campo_codigo = Rotulo()
        formulario.addRow("Código:", self.campo_codigo)
        self.campo_documento = Rotulo()
        formulario.addRow("CPF/CNPJ:", self.campo_documento)
        self.campo_tipo = Rotulo()
        formulario.addRow("Tipo:", self.campo_tipo)
        self.campo_situacao = Rotulo()
        formulario.addRow("Situação:", self.campo_situacao)
        self.campo_cobranca = Rotulo()
        formulario.addRow("Cobrança:", self.campo_cobranca)
        self.campo_vinculo = Rotulo()
        self.rotulo_vinculo = "Paga pela empresa:"
        formulario.addRow(self.rotulo_vinculo, self.campo_vinculo)
        self.campo_contatos = Rotulo()
        formulario.addRow("Contatos:", self.campo_contatos)
        self.campo_proxima = Rotulo()
        formulario.addRow("Próxima ação:", self.campo_proxima)
        self.campo_ultima = Rotulo()
        formulario.addRow("Última cobrança:", self.campo_ultima)
        self.campo_observacoes = Rotulo()
        formulario.addRow("Observações:", self.campo_observacoes)
        caixa_resumo.addWidget(dados)
        caixa_resumo.addStretch(1)
        self.abas.addTab(resumo, "Resumo")

        # honorários
        honorarios = QWidget()
        caixa = QVBoxLayout(honorarios)
        caixa.addWidget(widgets.rotulo_fraco("Pendentes"))
        self.modelo_pendentes = ModeloTabela(colunas_honorario())
        self.tabela_pendentes = preparar_tabela(QTableView(), esticar=0)
        self.tabela_pendentes.setModel(self.modelo_pendentes)
        self.tabela_pendentes.doubleClicked.connect(lambda *_: self._editar_honorario())
        caixa.addWidget(self.tabela_pendentes, 1)
        acoes = QHBoxLayout()
        botao_baixa = widgets.QPushButton("Registrar pagamento")
        botao_baixa.clicked.connect(self._registrar_pagamento)
        botao_editar = widgets.QPushButton("Editar honorário")
        botao_editar.clicked.connect(self._editar_honorario)
        acoes.addWidget(botao_baixa)
        acoes.addWidget(botao_editar)
        acoes.addStretch(1)
        caixa.addLayout(acoes)
        caixa.addWidget(widgets.rotulo_fraco("Pagos"))
        self.modelo_pagos = ModeloTabela(
            [
                *colunas_honorario(mostrar_cobranca=False),
                coluna_data("Pago em", lambda linha: linha.honorario.pago_em),
                Coluna(
                    "Pago com atraso",
                    lambda linha: "Sim" if servico_pagamentos.pagos_com_atraso(linha.honorario)
                    else "Não",
                    alinhamento=Qt.AlignmentFlag.AlignCenter,
                ),
            ]
        )
        self.tabela_pagos = preparar_tabela(QTableView(), esticar=0)
        self.tabela_pagos.setModel(self.modelo_pagos)
        caixa.addWidget(self.tabela_pagos, 1)
        self.abas.addTab(honorarios, "Honorários")

        # histórico de juros e reajustes
        historico = QWidget()
        caixa_historico = QVBoxLayout(historico)
        caixa_historico.addWidget(widgets.rotulo_fraco("Juros ao dia"))
        self.modelo_juros = ModeloTabela(
            [
                coluna_data("Vigência", lambda item: item.vigencia_inicio),
                Coluna(
                    "Anterior",
                    lambda item: (
                        formatar_moeda(item.valor_anterior)
                        if item.valor_anterior is not None
                        else "—"
                    ),
                ),
                Coluna("Novo", lambda item: formatar_moeda(item.valor_dia), negrito=True),
                Coluna("Motivo", lambda item: item.motivo or "—"),
            ]
        )
        self.tabela_juros = preparar_tabela(QTableView(), esticar=3)
        self.tabela_juros.setModel(self.modelo_juros)
        caixa_historico.addWidget(self.tabela_juros)
        caixa_historico.addWidget(widgets.rotulo_fraco("Reajustes de honorário"))
        self.modelo_reajustes = ModeloTabela(
            [
                coluna_data("Vigência", lambda r: r[1].vigencia_inicio),
                Coluna("Tipo", lambda r: r[0].tipo.nome),
                Coluna("Anterior", lambda r: formatar_moeda(r[1].valor_anterior)),
                Coluna("Novo", lambda r: formatar_moeda(r[1].valor_novo), negrito=True),
                Coluna("Motivo", lambda r: r[1].motivo or "—"),
            ]
        )
        self.tabela_reajustes = preparar_tabela(QTableView(), esticar=4)
        self.tabela_reajustes.setModel(self.modelo_reajustes)
        caixa_historico.addWidget(self.tabela_reajustes)
        self.abas.addTab(historico, "Histórico de juros e reajustes")

        # cobranças
        cobrancas_widget = QWidget()
        caixa_cobrancas = QVBoxLayout(cobrancas_widget)
        self.modelo_cobrancas = ModeloTabela(
            [
                Coluna(
                    "Data",
                    lambda c: formatar_data_hora(c.data_hora),
                    ordem=lambda c: c.data_hora,
                    alinhamento=Qt.AlignmentFlag.AlignCenter,
                ),
                Coluna(
                    "Honorário",
                    lambda c: f"{c.honorario.tipo.nome} {c.honorario.competencia_rotulo}".strip(),
                ),
                Coluna("Canal", lambda c: c.canal.rotulo),
                Coluna("Resultado", lambda c: c.resultado.rotulo),
                coluna_data("Promessa", lambda c: c.promessa_data),
                coluna_moeda("Valor no momento", lambda c: c.valor_atualizado_no_momento),
                Coluna("Observação", lambda c: c.observacao or "—"),
                Coluna(
                    "Situação",
                    lambda c: "Estornada" if not c.ativa else "Registrada",
                    alinhamento=Qt.AlignmentFlag.AlignCenter,
                ),
            ]
        )
        self.tabela_cobrancas = preparar_tabela(QTableView(), esticar=6)
        self.tabela_cobrancas.setModel(self.modelo_cobrancas)
        caixa_cobrancas.addWidget(self.tabela_cobrancas, 1)
        botoes_cobranca = QHBoxLayout()
        responder = widgets.QPushButton("Registrar resposta")
        responder.clicked.connect(self._responder)
        botoes_cobranca.addWidget(responder)
        ver_texto = widgets.QPushButton("Ver mensagem enviada")
        ver_texto.clicked.connect(self._ver_texto)
        estornar = widgets.QPushButton("Estornar cobrança")
        estornar.clicked.connect(self._estornar_cobranca)
        botoes_cobranca.addWidget(ver_texto)
        botoes_cobranca.addWidget(estornar)
        botoes_cobranca.addStretch(1)
        caixa_cobrancas.addLayout(botoes_cobranca)
        self.abas.addTab(cobrancas_widget, "Cobranças")

        # linha do tempo
        tempo = QWidget()
        caixa_tempo = QVBoxLayout(tempo)
        self.modelo_tempo = ModeloTabela(
            [
                coluna_data("Quando", lambda e: e.quando),
                Coluna("Evento", lambda e: e.tipo),
                Coluna("Detalhe", lambda e: e.descricao),
            ]
        )
        self.tabela_tempo = preparar_tabela(QTableView(), esticar=2)
        self.tabela_tempo.setModel(self.modelo_tempo)
        caixa_tempo.addWidget(self.tabela_tempo, 1)
        self.abas.addTab(tempo, "Linha do tempo")

        fechar = QHBoxLayout()
        fechar.addStretch(1)
        botao = widgets.QPushButton("Fechar")
        botao.clicked.connect(self.accept)
        fechar.addWidget(botao)
        layout.addLayout(fechar)

    # ------------------------------------------------------------------ dados
    def recarregar(self) -> None:
        self.contexto.atualizar()
        sessao = self.contexto.sessao
        dados = servico_ficha.resumo(sessao, self.cliente, self.contexto.data_referencia)
        self.resumo = dados

        self.cabecalho.definir_subtitulo(
            f"Código {self.cliente.codigo} · {self.cliente.tipo_pessoa.rotulo} · "
            f"{formatar_moeda(dados.total_em_aberto)} em aberto"
        )
        self.cartao_total.definir(dados.total_em_aberto)
        self.cartao_qtd.definir(str(dados.quantidade_em_aberto))
        self.cartao_atraso.definir(f"{dados.maior_atraso} dia(s)")
        self.cartao_juros.definir(dados.juros_dia)

        from ...dominio.valores import formatar_documento

        self.campo_codigo.setText(self.cliente.codigo)
        self.campo_documento.setText(formatar_documento(self.cliente.documento) or "—")
        subtipo = (
            f" · {self.cliente.subtipo.rotulo}"
            if self.cliente.subtipo.name != "NENHUM"
            else ""
        )
        self.campo_tipo.setText(f"{self.cliente.tipo_pessoa.rotulo}{subtipo}")
        self.campo_situacao.setText(self.cliente.situacao.rotulo)

        from ...servicos import clientes as servico_clientes

        suspensao = servico_clientes.suspensao(self.cliente, self.contexto.data_referencia)
        self.campo_cobranca.setText(suspensao or "Ativa")
        self.botao_suspensao.setText(
            "Retomar cobrança" if suspensao else "Suspender cobrança"
        )
        vinculados = servico_clientes.vinculados(sessao, self.cliente)
        if self.cliente.empresa is not None:
            self.campo_vinculo.setText(
                f"{self.cliente.empresa.codigo} – {self.cliente.empresa.nome}"
            )
        elif vinculados:
            self.campo_vinculo.setText(
                "Paga pelos honorários de: "
                + "; ".join(f"{c.codigo} – {c.nome}" for c in vinculados)
            )
        else:
            self.campo_vinculo.setText("—")
        self.campo_contatos.setText(
            "; ".join(
                f"{c.tratamento_ou_nome or c.nome} "
                f"({formatar_telefone(c.telefone) or 'sem telefone'})"
                for c in self.cliente.contatos
                if c.ativo
            )
            or "— nenhum contato cadastrado —"
        )
        self.campo_proxima.setText(dados.proxima_acao)
        self.campo_ultima.setText(formatar_data(dados.ultima_cobranca) or "—")
        self.campo_observacoes.setText(self.cliente.observacoes or "—")

        self.modelo_pendentes.definir_itens(dados.pendentes)
        self.modelo_pagos.definir_itens(dados.pagos)
        self.modelo_juros.definir_itens(
            sorted(self.cliente.juros, key=lambda item: item.vigencia_inicio, reverse=True)
        )
        reajustes = [
            (contrato, registro)
            for contrato in self.cliente.contratos
            if contrato.excluido_em is None
            for registro in contrato.historico
        ]
        reajustes.sort(key=lambda par: par[1].vigencia_inicio, reverse=True)
        self.modelo_reajustes.definir_itens(reajustes)
        from ...servicos import cobrancas as servico_cobrancas

        self.modelo_cobrancas.definir_itens(
            servico_cobrancas.historico_do_cliente(sessao, self.cliente.id)
        )
        self.modelo_tempo.definir_itens(servico_ficha.linha_do_tempo(sessao, self.cliente))
        for tabela, modelo in (
            (self.tabela_pendentes, self.modelo_pendentes),
            (self.tabela_pagos, self.modelo_pagos),
            (self.tabela_cobrancas, self.modelo_cobrancas),
            (self.tabela_juros, self.modelo_juros),
            (self.tabela_reajustes, self.modelo_reajustes),
            (self.tabela_tempo, self.modelo_tempo),
        ):
            ajustar_colunas(tabela, modelo.colunas)

    # ------------------------------------------------------------------ ações
    def _cobrar(self) -> None:
        if not self.resumo.pendentes:
            widgets.informar(self, "Este cliente não tem honorário em aberto.", "Nada a cobrar")
            return
        dialogo = DialogoCobrar(self.contexto, self.cliente, list(self.resumo.pendentes), self)
        dialogo.exec()
        if dialogo.registrou:
            self.recarregar()

    def _editar_cadastro(self) -> None:
        from .cliente import DialogoCliente

        if DialogoCliente(self.contexto, self.cliente, self).exec():
            self.setWindowTitle(f"Ficha – {self.cliente.nome}")
            self.cabecalho.definir_titulo(self.cliente.nome)
            self.recarregar()

    def _alternar_suspensao(self) -> None:
        from .suspensao import DialogoSuspensao, retomar

        if self.cliente.suspensao_ativa(self.contexto.data_referencia):
            if retomar(self, self.contexto, self.cliente):
                self.recarregar()
            return
        if DialogoSuspensao(self.contexto, self.cliente, self).exec():
            self.recarregar()

    def _novo_honorario(self) -> None:
        dialogo = DialogoHonorario(self.contexto, cliente=self.cliente, parent=self)
        if dialogo.exec():
            self.recarregar()

    def _linha_selecionada(self):
        linha = item_atual(self.tabela_pendentes)
        if linha is None:
            widgets.aviso(self, "Selecione um honorário pendente.")
        return linha

    def _registrar_pagamento(self) -> None:
        linha = self._linha_selecionada()
        if linha is None:
            return
        dialogo = DialogoPagamento(self.contexto, linha.honorario, self)
        if dialogo.exec():
            self.recarregar()

    def _editar_honorario(self) -> None:
        linha = self._linha_selecionada()
        if linha is None:
            return
        dialogo = DialogoHonorario(self.contexto, honorario=linha.honorario, parent=self)
        if dialogo.exec():
            self.recarregar()

    def _responder(self) -> None:
        cobranca = item_atual(self.tabela_cobrancas)
        if cobranca is None:
            widgets.aviso(self, "Selecione uma cobrança.")
            return
        if cobranca.lote is None:
            widgets.aviso(
                self,
                "Esta cobrança veio da planilha antiga e não tem mensagem associada.",
            )
            return
        from ...servicos import acompanhamento as servico_acompanhamento
        from .resposta import DialogoResposta

        linha = servico_acompanhamento.linha_do_lote(
            self.contexto.sessao, cobranca.lote, self.contexto.data_referencia
        )
        if DialogoResposta(self.contexto, linha, self).exec():
            self.recarregar()

    def _ver_texto(self) -> None:
        cobranca = item_atual(self.tabela_cobrancas)
        if cobranca is None:
            widgets.aviso(self, "Selecione uma cobrança.")
            return
        texto = cobranca.texto or "(cobrança registrada sem mensagem gerada pelo sistema)"
        widgets.informar(self, texto, "Mensagem enviada")

    def _estornar_cobranca(self) -> None:
        cobranca = item_atual(self.tabela_cobrancas)
        if cobranca is None:
            widgets.aviso(self, "Selecione uma cobrança.")
            return
        from PySide6.QtWidgets import QInputDialog

        motivo, confirmou = QInputDialog.getText(
            self, "Estornar cobrança", "Motivo do estorno:"
        )
        if not confirmou:
            return
        from ...servicos import cobrancas as servico_cobrancas

        def acao():
            servico_cobrancas.estornar(self.contexto.sessao, cobranca, motivo)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.recarregar()
