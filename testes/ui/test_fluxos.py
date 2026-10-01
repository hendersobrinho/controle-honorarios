"""Fluxos principais da interface, com pytest-qt.

Não testa aparência: testa que a tela lê o serviço certo, mostra o que deveria e
grava o que o usuário confirmou.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from honorarios.dominio.enums import ResultadoCobranca, StatusPagamento
from honorarios.dominio.valores import Competencia, formatar_data, formatar_moeda
from honorarios.servicos import cobrancas as servico_cobrancas
from testes import fabricas

REFERENCIA = date(2026, 9, 29)


@pytest.fixture
def cliente_com_debito(sessao):
    cliente = fabricas.cliente(sessao, juros_dia="1.00")
    cliente.juros[0].vigencia_inicio = date(2020, 1, 1)
    sessao.commit()
    fabricas.honorario(sessao, cliente, valor="1000.00", vencimento=date(2026, 9, 19))
    fabricas.honorario(
        sessao,
        cliente,
        valor="500.00",
        vencimento=date(2026, 8, 19),
        competencia=Competencia(2026, 7),
    )
    return cliente


def linhas_do(sessao, cliente):
    return servico_cobrancas.linhas_em_aberto_do_cliente(sessao, cliente.id, REFERENCIA)


# ------------------------------------------------------------- cobrança geral


def test_atrasados_agrupa_por_faixa_de_atraso(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.paineis.honorarios import PainelAtrasados

    painel = PainelAtrasados(contexto)
    qtbot.addWidget(painel)
    # dívida mais antiga primeiro: 41 dias e depois 10 dias
    assert painel.lista.titulos() == ["31 a 60 dias", "1 a 30 dias"]
    assert len(painel.lista.itens) == 2
    assert painel.lista.secoes[0].total == "R$ 541,00"    # 500 + 41 de juros
    assert painel.lista.secoes[1].total == "R$ 1.010,00"  # 1000 + 10 de juros
    assert "2 honorário(s)" in painel.resumo.text()


def test_cartao_de_atrasado_mostra_situacao_e_leva_ao_historico(
    qtbot, contexto, cliente_com_debito
):
    from honorarios.ui.paineis.honorarios import PainelAtrasados

    painel = PainelAtrasados(contexto)
    qtbot.addWidget(painel)
    cartao = painel.lista.secoes[0].cartoes[0]
    assert "Em atraso há" in cartao.situacao
    assert cartao.cor is not None                      # faixa vermelha de atraso
    assert [acao.texto for acao in cartao.acoes] == ["Histórico", "Cobrar"]
    assert cartao.valor == "R$ 541,00"


def test_pago_sai_de_atrasados_e_vai_para_pagos(qtbot, contexto, cliente_com_debito):
    from honorarios.dominio.enums import FormaPagamento
    from honorarios.servicos import pagamentos
    from honorarios.ui.paineis.honorarios import PainelAtrasados, PainelPagos

    linha = linhas_do(contexto.sessao, cliente_com_debito)[0]
    # o total muda com a data: pagar em 20/09 usa o total daquele dia
    previa = pagamentos.previa(linha.honorario, date(2026, 9, 20))
    pagamentos.registrar(
        contexto.sessao,
        linha.honorario,
        pagamentos.DadosPagamento(
            data=date(2026, 9, 20),
            valor_pago=previa.total_devido,
            forma_pagamento=FormaPagamento.PIX,
        ),
    )
    contexto.salvar()

    atrasados = PainelAtrasados(contexto)
    qtbot.addWidget(atrasados)
    assert len(atrasados.lista.itens) == 1
    assert all(
        item.atualizacao.status is StatusPagamento.EM_ABERTO for item in atrasados.lista.itens
    )

    pagos = PainelPagos(contexto)
    qtbot.addWidget(pagos)
    assert len(pagos.lista.itens) == 1
    assert pagos.lista.titulos() == ["Set/2026"]
    cartao = pagos.lista.secoes[0].cartoes[0]
    assert cartao.valor_rotulo == "Recebido"
    assert cartao.situacao.startswith("Pago com")          # pagou com atraso
    assert [acao.texto for acao in cartao.acoes] == ["Histórico"]


def test_filtro_de_faixa_de_atraso(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.paineis.honorarios import PainelAtrasados

    painel = PainelAtrasados(contexto)
    qtbot.addWidget(painel)
    painel.faixa.setCurrentIndex(2)  # 31 a 60 dias
    itens = painel.lista.itens
    assert len(itens) == 1
    assert itens[0].atualizacao.dias_atraso == 41


def test_atrasados_agrupados_por_empresa(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.paineis.honorarios import PainelAtrasados

    painel = PainelAtrasados(contexto)
    qtbot.addWidget(painel)
    painel.agrupamento.setCurrentIndex(2)  # Empresa
    assert painel.lista.titulos()[0].startswith("900 – EMPRESA EXEMPLO")


def test_a_vencer_mostra_so_o_que_esta_no_prazo(qtbot, contexto, cliente_com_debito):
    from honorarios.dominio.valores import Competencia
    from honorarios.ui.paineis.honorarios import PainelAtrasados, PainelAVencer

    for vencimento, mes in (
        (date(2026, 9, 29), 9),     # vence no dia de referência
        (date(2026, 10, 2), 10),    # dentro de 5 dias
        (date(2026, 11, 10), 11),   # mais adiante
    ):
        fabricas.honorario(
            contexto.sessao,
            cliente_com_debito,
            valor="300.00",
            vencimento=vencimento,
            competencia=Competencia(2026, mes),
        )

    painel = PainelAVencer(contexto)
    qtbot.addWidget(painel)
    assert painel.lista.titulos() == [
        "Vence hoje",
        "Vence nos próximos 5 dias",
        "Vence mais adiante",
    ]
    assert all(item.atualizacao.dias_atraso == 0 for item in painel.lista.itens)
    cartao = painel.lista.secoes[0].cartoes[0]
    assert cartao.situacao == "Vence hoje"
    assert [acao.texto for acao in cartao.acoes] == ["Histórico", "Lembrete"]

    # e nenhum deles aparece em atrasados
    atrasados = PainelAtrasados(contexto)
    qtbot.addWidget(atrasados)
    assert len(atrasados.lista.itens) == 2


# ----------------------------------------------------------------- cobrar


def test_dialogo_cobrar_gera_mensagem_com_os_marcados(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.dialogos.cobrar import DialogoCobrar

    linhas = linhas_do(contexto.sessao, cliente_com_debito)
    dialogo = DialogoCobrar(contexto, cliente_com_debito, linhas)
    qtbot.addWidget(dialogo)
    texto = dialogo.texto.toPlainText()
    assert "Constam em aberto os seguintes honorários:" in texto
    assert "R$ 1.551,00" in texto
    assert dialogo.total.text() == "R$ 1.551,00"


def test_desmarcar_troca_para_o_modelo_de_um_honorario(qtbot, contexto, cliente_com_debito):
    from PySide6.QtCore import Qt

    from honorarios.ui.dialogos.cobrar import DialogoCobrar

    linhas = linhas_do(contexto.sessao, cliente_com_debito)
    dialogo = DialogoCobrar(contexto, cliente_com_debito, linhas)
    qtbot.addWidget(dialogo)
    dialogo.modelo.setData(
        dialogo.modelo.index(1, 0), Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole
    )
    texto = dialogo.texto.toPlainText()
    assert "Consta em aberto o honorário referente à competência" in texto
    assert "seguintes" not in texto


def test_simular_outra_data_recalcula_o_total(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.dialogos.cobrar import DialogoCobrar

    linhas = linhas_do(contexto.sessao, cliente_com_debito)
    dialogo = DialogoCobrar(contexto, cliente_com_debito, linhas)
    qtbot.addWidget(dialogo)
    antes = dialogo.total.text()
    dialogo.data_referencia.definir(date(2026, 10, 9))
    assert dialogo.total.text() != antes
    assert "R$ 1.571,00" == dialogo.total.text()  # 10 dias x 1,00 em cada honorário


def test_copiar_mensagem_nao_registra_cobranca(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.dialogos.cobrar import DialogoCobrar

    linhas = linhas_do(contexto.sessao, cliente_com_debito)
    dialogo = DialogoCobrar(contexto, cliente_com_debito, linhas)
    qtbot.addWidget(dialogo)
    dialogo._copiar()
    assert servico_cobrancas.historico_do_cliente(contexto.sessao, cliente_com_debito.id) == []
    assert "não registra" in dialogo.aviso.text()


def test_marcar_como_cobrado_nasce_aguardando_resposta(
    qtbot, contexto, cliente_com_debito, monkeypatch
):
    """Na hora de cobrar não existe resposta: ela é anotada depois."""
    from honorarios.ui.comum import widgets
    from honorarios.ui.dialogos.cobrar import DialogoCobrar

    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: True)
    linhas = linhas_do(contexto.sessao, cliente_com_debito)
    dialogo = DialogoCobrar(contexto, cliente_com_debito, linhas)
    qtbot.addWidget(dialogo)
    assert not hasattr(dialogo, "resultado")   # o bloco de resposta saiu da tela
    dialogo._registrar()

    assert dialogo.registrou
    historico = servico_cobrancas.historico_do_cliente(contexto.sessao, cliente_com_debito.id)
    assert len(historico) == 2
    assert all(c.resultado is ResultadoCobranca.AGUARDANDO for c in historico)
    assert all(c.promessa_data is None for c in historico)
    assert "Constam em aberto" in historico[0].texto


# -------------------------------------------------------------- pagamento


def test_dialogo_pagamento_sugere_o_total_e_registra(qtbot, contexto, cliente_com_debito):
    from honorarios.servicos import pagamentos
    from honorarios.ui.dialogos.pagamento import DialogoPagamento

    linha = linhas_do(contexto.sessao, cliente_com_debito)[0]
    dialogo = DialogoPagamento(contexto, linha.honorario)
    qtbot.addWidget(dialogo)
    # o diálogo abre na data de hoje; o valor sugerido é o total daquele dia
    esperado = pagamentos.previa(linha.honorario, dialogo.data.valor()).total_devido
    assert dialogo.valor_pago.valor() == esperado
    assert "Quita o honorário." in dialogo.resultado.text()

    dialogo.valor_pago.definir(Decimal("200.00"))
    assert "Pagamento parcial" in dialogo.resultado.text()

    dialogo.valor_pago.definir(esperado)
    dialogo._registrar()
    assert linha.honorario.status is StatusPagamento.PAGO
    assert linha.honorario.total_congelado == esperado


# ------------------------------------------------------------- competência


def test_dialogo_gerar_competencia_previa_e_geracao(qtbot, contexto, monkeypatch):
    from honorarios.ui.comum import widgets
    from honorarios.ui.dialogos.competencia import DialogoGerarCompetencia

    cliente = fabricas.cliente(contexto.sessao)
    fabricas.contrato(contexto.sessao, cliente, valor="1507.80", dia=8)
    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: True)
    monkeypatch.setattr(widgets, "informar", lambda *a, **k: None)

    dialogo = DialogoGerarCompetencia(contexto)
    qtbot.addWidget(dialogo)
    dialogo.mes.setCurrentIndex(7)  # agosto
    dialogo.ano.setValue(2026)
    assert len(dialogo.modelo.itens) == 1
    assert "1 honorário(s) a gerar" in dialogo.resumo.text()

    dialogo._gerar()
    assert dialogo.gerados == 1
    assert dialogo.modelo.itens[0].impedimento == "Já lançado nesta competência"
    assert "0 honorário(s) a gerar" in dialogo.resumo.text()


# ------------------------------------------------------------------ clientes


def test_painel_clientes_filtra_e_mostra_total(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.paineis.clientes import PainelClientes

    painel = PainelClientes(contexto)
    qtbot.addWidget(painel)
    assert painel.modelo.rowCount() == 1
    assert "total em aberto R$ 1.551,00" in painel.resumo.text()

    painel.busca.setText("inexistente")
    assert painel.modelo.rowCount() == 0
    painel.busca.setText("empresa exemplo")
    assert painel.modelo.rowCount() == 1


def test_dialogo_cliente_salva_e_valida(qtbot, contexto, monkeypatch):
    from honorarios.ui.comum import widgets
    from honorarios.ui.dialogos.cliente import DialogoCliente

    avisos: list[str] = []
    monkeypatch.setattr(widgets, "aviso", lambda parent, texto, *a, **k: avisos.append(texto))

    dialogo = DialogoCliente(contexto)
    qtbot.addWidget(dialogo)
    dialogo.codigo.setText("777")
    dialogo.nome.setText("NOVA EMPRESA EXEMPLO LTDA")
    dialogo.documento.definir("11.222.333/0001-99")  # dígito errado
    dialogo.juros.definir(Decimal("0.54"))
    dialogo._salvar()
    assert avisos and "CPF/CNPJ inválido" in avisos[0]

    dialogo.documento.definir(fabricas.CNPJ_FICTICIO)
    dialogo._nova_linha()
    dialogo.contatos.item(0, 0).setText("Fulano de Teste")
    dialogo.contatos.item(0, 1).setText("Fulano")
    dialogo.contatos.item(0, 2).setText("27999990000")
    dialogo._salvar()

    from honorarios.servicos import clientes

    criado = clientes.por_codigo(contexto.sessao, "777")
    assert criado is not None
    assert criado.contato_principal.nome_tratamento == "Fulano"
    assert clientes.juros_atual(criado) == Decimal("0.54")


def test_ficha_reune_pendentes_pagos_e_linha_do_tempo(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.dialogos.ficha import DialogoFicha

    servico_cobrancas.registrar(
        contexto.sessao,
        servico_cobrancas.Selecao(
            cliente=cliente_com_debito, linhas=linhas_do(contexto.sessao, cliente_com_debito)
        ),
        texto="mensagem de teste",
    )
    contexto.salvar()

    ficha = DialogoFicha(contexto, cliente_com_debito)
    qtbot.addWidget(ficha)
    assert ficha.modelo_pendentes.rowCount() == 2
    assert ficha.modelo_cobrancas.rowCount() == 2
    assert ficha.modelo_tempo.rowCount() >= 4
    assert "R$ 1.551,00" in ficha.cabecalho._subtitulo.text()


# ----------------------------------------------------------------- fila do dia


# -------------------------------------------------------------------- painel


def test_painel_resumo_calcula_indicadores(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.paineis.painel import PainelResumo

    painel = PainelResumo(contexto)
    qtbot.addWidget(painel)
    assert painel.indicadores.quantidade_em_aberto == 2
    assert painel.cartao_total._valor.text() == "R$ 1.551,00"


def test_janela_principal_abre_todas_as_telas(qtbot, contexto):
    from honorarios.ui.janela_principal import JanelaPrincipal

    janela = JanelaPrincipal(contexto)
    qtbot.addWidget(janela)
    assert janela.telas.count() == 14
    assert len(janela.linhas_de_tela) == 14
    titulos = [janela.telas.widget(i).titulo for i in range(janela.telas.count())]
    assert "Cobranças enviadas" in titulos and "Rankings" in titulos
    assert "Imposto de Renda" in titulos and "Grupos e tipos" in titulos
    assert not any("Fila" in titulo for titulo in titulos)
    for linha in janela.linhas_de_tela:
        janela.navegacao.setCurrentRow(linha)
    assert janela.telas.currentWidget().titulo == "Configurações"


def test_titulo_de_grupo_da_navegacao_nao_troca_de_tela(qtbot, contexto):
    """Os títulos COBRANÇA/CADASTROS/GESTÃO são rótulos, não telas."""
    from honorarios.ui.janela_principal import JanelaPrincipal

    janela = JanelaPrincipal(contexto)
    qtbot.addWidget(janela)
    antes = janela.telas.currentIndex()
    janela.navegacao.setCurrentRow(0)  # "COBRANÇA"
    assert janela.telas.currentIndex() == antes


# ------------------------------------------------------------ acompanhamento


def cobrar_pelo_sistema(contexto, cliente, quando=None):
    from datetime import datetime, time

    linhas = linhas_do(contexto.sessao, cliente)
    selecao = servico_cobrancas.Selecao(cliente=cliente, linhas=linhas)
    lote = servico_cobrancas.registrar(
        contexto.sessao,
        selecao,
        texto=servico_cobrancas.gerar_texto(contexto.sessao, selecao),
        quando=datetime.combine(quando, time(9, 0)) if quando else None,
    )
    contexto.salvar()
    return lote


def test_painel_acompanhamento_agrupa_por_situacao(qtbot, contexto, cliente_com_debito):
    from honorarios.servicos import acompanhamento
    from honorarios.ui.paineis.acompanhamento import PainelAcompanhamento

    cobrar_pelo_sistema(contexto, cliente_com_debito, date(2026, 9, 25))
    painel = PainelAcompanhamento(contexto)
    qtbot.addWidget(painel)
    assert painel.lista.titulos() == [acompanhamento.AGUARDANDO]
    cartao = painel.lista.secoes[0].cartoes[0]
    assert cartao.situacao == acompanhamento.AGUARDANDO
    assert [acao.texto for acao in cartao.acoes] == ["Registrar resposta", "Ver mensagem"]
    assert "1 sem resposta anotada" in painel.resumo.text()


def test_acompanhamento_muda_de_periodo_e_de_agrupamento(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.paineis.acompanhamento import PainelAcompanhamento

    cobrar_pelo_sistema(contexto, cliente_com_debito, date(2026, 5, 10))
    painel = PainelAcompanhamento(contexto)
    qtbot.addWidget(painel)
    assert painel.lista.itens == []          # fora dos últimos 3 meses

    painel.periodo.setCurrentIndex(4)        # Tudo
    assert len(painel.lista.itens) == 1
    painel.agrupamento.setCurrentIndex(1)    # por mês
    assert painel.lista.titulos() == ["Mai/2026"]


def test_dialogo_de_resposta_grava_promessa(qtbot, contexto, cliente_com_debito):
    from honorarios.servicos import acompanhamento
    from honorarios.ui.dialogos.resposta import DialogoResposta

    cobrar_pelo_sistema(contexto, cliente_com_debito, date(2026, 9, 25))
    linha = acompanhamento.listar(
        contexto.sessao, acompanhamento.Filtro(data_referencia=REFERENCIA)
    )[0]
    dialogo = DialogoResposta(contexto, linha)
    qtbot.addWidget(dialogo)
    dialogo.resultado.definir(ResultadoCobranca.PROMETEU_PAGAR)
    dialogo.promessa.definir(date(2026, 10, 8))
    dialogo.observacao.setPlainText("Falou com o financeiro")
    dialogo._salvar()

    atualizada = acompanhamento.listar(
        contexto.sessao, acompanhamento.Filtro(data_referencia=REFERENCIA)
    )[0]
    assert atualizada.resultado is ResultadoCobranca.PROMETEU_PAGAR
    assert atualizada.promessa == date(2026, 10, 8)
    assert atualizada.situacao == acompanhamento.PROMESSA_EM_ABERTO


def test_dialogo_de_historico_mostra_o_lote(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.dialogos.historico import DialogoHistorico

    cobrar_pelo_sistema(contexto, cliente_com_debito, date(2026, 9, 25))
    linha = linhas_do(contexto.sessao, cliente_com_debito)[0]
    dialogo = DialogoHistorico(contexto, linha.honorario)
    qtbot.addWidget(dialogo)
    titulos = [cartao.titulo for cartao in dialogo.lista.secoes[0].cartoes]
    assert "Cobrança enviada em lote" in titulos
    assert "Honorário mensal lançado" in titulos
    cobranca = next(
        cartao for cartao in dialogo.lista.secoes[0].cartoes
        if cartao.titulo == "Cobrança enviada em lote"
    )
    assert any("Em lote" in valor for _, valor in cobranca.detalhes)
    assert [acao.texto for acao in cobranca.acoes] == ["Ver mensagem", "Registrar resposta"]


def test_lista_de_cartoes_desenha_so_o_que_cabe_no_orcamento(qtbot):
    """Centenas de registros não viram centenas de widgets."""
    from honorarios.ui.comum.cartoes import DadosCartao, PainelDeCartoes, SecaoCartoes

    montados = []

    def construtor(numero: int) -> DadosCartao:
        montados.append(numero)
        return DadosCartao(titulo=f"Registro {numero}", item=numero)

    lista = PainelDeCartoes(limite_secao=10, orcamento=25)
    qtbot.addWidget(lista)
    lista.definir_secoes(
        [
            SecaoCartoes(f"Seção {secao}", itens=list(range(secao * 100, secao * 100 + 40)),
                         construtor=construtor)
            for secao in range(4)
        ]
    )
    assert len(lista.itens) == 160          # todos os registros continuam na lista
    assert lista.desenhados == 25           # mas só o orçamento vira widget
    assert len(montados) == 25              # e só esses foram formatados


def test_secoes_pequenas_nao_consomem_o_orcamento_das_seguintes(qtbot):
    """Regressão: o orçamento descontava o limite da seção, não o que foi desenhado."""
    from honorarios.ui.comum.cartoes import DadosCartao, PainelDeCartoes, SecaoCartoes

    lista = PainelDeCartoes(limite_secao=30, orcamento=90)
    qtbot.addWidget(lista)
    lista.definir_secoes(
        [
            SecaoCartoes(
                f"Seção {numero}",
                itens=[f"{numero}-{i}" for i in range(tamanho)],
                construtor=lambda item: DadosCartao(titulo=item, item=item),
            )
            for numero, tamanho in enumerate((11, 2, 4, 11))
        ]
    )
    assert lista.desenhados == 28   # todas as quatro seções aparecem


def test_mostrar_mais_amplia_a_secao(qtbot):
    from honorarios.ui.comum.cartoes import DadosCartao, PainelDeCartoes, SecaoCartoes

    lista = PainelDeCartoes(limite_secao=5, orcamento=5)
    qtbot.addWidget(lista)
    lista.definir_secoes(
        [
            SecaoCartoes(
                "Tudo",
                itens=list(range(20)),
                construtor=lambda numero: DadosCartao(titulo=str(numero), item=numero),
            )
        ]
    )
    assert lista.desenhados == 5
    lista._mostrar_mais("Tudo", 5)
    assert lista.desenhados == 10


def test_periodo_na_tela_de_pagos(qtbot, contexto, cliente_com_debito):
    from honorarios.servicos import pagamentos
    from honorarios.ui.paineis.honorarios import PainelPagos

    linha = linhas_do(contexto.sessao, cliente_com_debito)[0]
    previa = pagamentos.previa(linha.honorario, date(2026, 5, 10))
    pagamentos.registrar(
        contexto.sessao,
        linha.honorario,
        pagamentos.DadosPagamento(data=date(2026, 5, 10), valor_pago=previa.total_devido),
    )
    contexto.salvar()

    painel = PainelPagos(contexto)
    qtbot.addWidget(painel)
    assert painel.lista.itens == []                   # fora dos últimos 3 meses
    painel.periodo.setCurrentIndex(4)                 # Tudo
    assert len(painel.lista.itens) == 1


# ----------------------------------------------- suspensão e vínculo na tela


@pytest.fixture
def empresa_com_vinculado(sessao, contexto):
    from honorarios.dominio.enums import TipoPessoa
    from honorarios.dominio.valores import Competencia
    from honorarios.servicos import clientes

    empresa = fabricas.cliente(sessao, codigo="800", nome="EMPRESA DO SOCIO LTDA")
    fabricas.honorario(sessao, empresa, valor="1000.00", vencimento=date(2026, 8, 10))
    pessoa = fabricas.cliente(
        sessao,
        codigo="801",
        nome="SOCIO EXEMPLO",
        documento=fabricas.CPF_FICTICIO,
        tipo=TipoPessoa.PF,
        juros_dia="0.20",
    )
    fabricas.honorario(
        sessao,
        pessoa,
        valor="500.00",
        vencimento=date(2026, 8, 20),
        competencia=Competencia(2026, 7),
    )
    pessoa.empresa_id = empresa.id
    contexto.salvar()
    _ = clientes
    return empresa, pessoa


def test_cobrar_inclui_honorarios_da_pessoa_vinculada(qtbot, contexto, empresa_com_vinculado):
    from honorarios.servicos import cobrancas
    from honorarios.ui.dialogos.cobrar import DialogoCobrar

    empresa, pessoa = empresa_com_vinculado
    linhas = cobrancas.linhas_em_aberto_do_cliente(contexto.sessao, empresa.id, REFERENCIA)
    dialogo = DialogoCobrar(contexto, empresa, linhas)
    qtbot.addWidget(dialogo)

    assert dialogo.incluir_vinculados.isVisible() or dialogo.linhas_vinculados
    assert len(dialogo.modelo.itens) == 1
    assert "Titular" not in [coluna.titulo for coluna in dialogo.modelo.colunas][:1]

    dialogo.incluir_vinculados.setChecked(True)
    assert len(dialogo.modelo.itens) == 2
    texto = dialogo.texto.toPlainText()
    assert "SOCIO EXEMPLO:" in texto


def test_cobrar_avisa_e_recusa_cliente_com_cobranca_suspensa(
    qtbot, contexto, cliente_com_debito, monkeypatch
):
    from honorarios.servicos import clientes
    from honorarios.ui.comum import widgets
    from honorarios.ui.dialogos.cobrar import DialogoCobrar

    clientes.suspender_cobranca(contexto.sessao, cliente_com_debito, "Acordo judicial")
    contexto.salvar()

    avisos: list[str] = []
    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: True)
    monkeypatch.setattr(widgets, "aviso", lambda parent, texto, *a, **k: avisos.append(texto))

    linhas = linhas_do(contexto.sessao, cliente_com_debito)
    dialogo = DialogoCobrar(contexto, cliente_com_debito, linhas)
    qtbot.addWidget(dialogo)
    dialogo._registrar()

    assert not dialogo.registrou
    assert avisos and "suspensa" in avisos[0]
    assert servico_cobrancas.historico_do_cliente(contexto.sessao, cliente_com_debito.id) == []


def test_lista_de_clientes_mostra_suspensao_e_vinculo(qtbot, contexto, empresa_com_vinculado):
    from honorarios.servicos import clientes
    from honorarios.ui.paineis.clientes import PainelClientes

    empresa, _ = empresa_com_vinculado
    clientes.suspender_cobranca(contexto.sessao, empresa, "Em acordo")
    contexto.salvar()

    painel = PainelClientes(contexto)
    qtbot.addWidget(painel)
    linhas = {linha.cliente.codigo: linha for linha in painel.modelo.itens}
    assert linhas["800"].cobranca_suspensa
    assert not linhas["801"].cobranca_suspensa
    assert linhas["801"].cliente.empresa.codigo == "800"
    assert "1 com cobrança suspensa" in painel.resumo.text()


def test_cartao_mostra_etiqueta_de_cobranca_suspensa(qtbot, contexto, cliente_com_debito):
    from honorarios.servicos import clientes
    from honorarios.ui.paineis.honorarios import PainelAtrasados

    clientes.suspender_cobranca(contexto.sessao, cliente_com_debito, "Acordo")
    contexto.salvar()
    painel = PainelAtrasados(contexto)
    qtbot.addWidget(painel)
    cartao = painel.lista.secoes[0].cartoes[0]
    assert cartao.situacao == "Cobrança suspensa"
    # sem botão de cobrar quem está suspenso não faria sentido: o botão continua,
    # mas o registro é recusado pelo serviço — a etiqueta avisa antes
    assert "Histórico" in [acao.texto for acao in cartao.acoes]


# ---------------------------------------------------- seletor, juros, rankings


def test_campo_cliente_escolhe_direto_pelo_codigo(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.comum.seletor_cliente import CampoCliente

    campo = CampoCliente(contexto.sessao)
    qtbot.addWidget(campo)
    escolhas = []
    campo.mudou.connect(escolhas.append)
    campo.texto.setText("900")
    campo.procurar()          # código exato: escolhe sem abrir a janela
    assert campo.valor() == cliente_com_debito.id
    assert campo.texto.text().startswith("900 – ")
    assert escolhas and escolhas[-1].id == cliente_com_debito.id


def test_digitar_por_cima_desfaz_a_escolha(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.comum.seletor_cliente import CampoCliente

    campo = CampoCliente(contexto.sessao)
    qtbot.addWidget(campo)
    campo.definir(cliente_com_debito.id)
    assert campo.valor() == cliente_com_debito.id
    campo.texto.textEdited.emit("outra coisa")
    assert campo.valor() is None


def test_janela_de_busca_filtra_enquanto_digita(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.comum.seletor_cliente import DialogoProcurarCliente

    fabricas.cliente(
        contexto.sessao, codigo="950", nome="OUTRA PESSOA", documento=fabricas.CPF_FICTICIO,
        tipo=__import__("honorarios.dominio.enums", fromlist=["TipoPessoa"]).TipoPessoa.PF,
    )
    dialogo = DialogoProcurarCliente(contexto.sessao)
    qtbot.addWidget(dialogo)
    assert dialogo.modelo.rowCount() == 2
    dialogo.busca.setText("empresa exemplo")
    assert [c.codigo for c in dialogo.modelo.itens] == ["900"]
    dialogo._escolher()
    assert dialogo.escolhido.codigo == "900"


def test_cadastro_mostra_botao_de_alterar_juros(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.dialogos.cliente import DialogoCliente

    novo = DialogoCliente(contexto)
    qtbot.addWidget(novo)
    assert novo.juros.isEnabled()                 # no cadastro novo, digita-se o valor
    assert not novo.botao_juros.isVisibleTo(novo)

    existente = DialogoCliente(contexto, cliente_com_debito)
    qtbot.addWidget(existente)
    assert not existente.juros.isEnabled()        # depois, muda com vigência
    assert existente.botao_juros.isVisibleTo(existente)
    assert "Vigente hoje" in existente.nota_juros.text()


def test_ficha_tem_botao_de_alterar_juros(qtbot, contexto, cliente_com_debito):
    from PySide6.QtWidgets import QPushButton

    from honorarios.ui.dialogos.ficha import DialogoFicha

    ficha = DialogoFicha(contexto, cliente_com_debito)
    qtbot.addWidget(ficha)
    textos = [botao.text() for botao in ficha.findChildren(QPushButton)]
    assert "Alterar juros" in textos


def test_painel_de_rankings_monta_os_quatro_graficos(
    qtbot, contexto, cliente_com_debito, monkeypatch
):
    from honorarios.ui.dialogos import ficha
    from honorarios.ui.paineis.rankings import PainelRankings

    # clicar num nome abre a ficha (modal): no teste, só registra que abriria
    abertas = []
    monkeypatch.setattr(
        ficha.DialogoFicha, "exec", lambda self: abertas.append(self.cliente.id) or 0
    )

    painel = PainelRankings(contexto)
    qtbot.addWidget(painel)
    assert set(painel.graficos) == {"devedores", "tempo", "honorarios", "cobrados"}
    assert painel.abas.count() == 3                   # + análise de juros
    devedores = painel.graficos["devedores"]
    assert devedores.titulo.text() == "💸 Quem mais deve"
    assert len(devedores.barras.itens) == 1
    assert devedores.barras.itens[0].cliente.id == cliente_com_debito.id

    devedores.barras.clicado.emit(devedores.barras.itens[0].cliente)
    assert abertas == [cliente_com_debito.id]     # o clique leva à ficha do cliente


def test_aba_de_analise_de_juros(qtbot, contexto, cliente_com_debito, monkeypatch):
    from honorarios.servicos import pagamentos
    from honorarios.ui.dialogos import ficha
    from honorarios.ui.paineis.rankings import PainelRankings

    abertas = []
    monkeypatch.setattr(
        ficha.DialogoFicha, "exec", lambda self: abertas.append(self.cliente.id) or 0
    )
    linha = linhas_do(contexto.sessao, cliente_com_debito)[0]
    data = date(2026, 9, 20)
    previa = pagamentos.previa(linha.honorario, data)
    pagamentos.registrar(
        contexto.sessao,
        linha.honorario,
        pagamentos.DadosPagamento(data=data, valor_pago=previa.total_devido),
    )
    contexto.salvar()

    painel = PainelRankings(contexto)
    qtbot.addWidget(painel)
    painel.abas.setCurrentIndex(painel.indice_analise)
    aba = painel.analise
    assert len(aba.analise.honorarios) == 1

    # começa na visão geral; o cliente que pagou aparece na lista
    assert aba.paginas.currentWidget() is aba.rolagem_geral
    assert "com atraso" in aba.visao_geral.leituras.text()
    assert aba.visao_geral.cartoes["atraso"]._valor.text().startswith("1 de 1")
    assert aba.lista.count() == 2                     # visão geral + o cliente

    # clicar no ranking abre a análise daquele cliente
    ranking = aba.visao_geral.ranking_juros
    ranking.barras.clicado.emit(ranking.barras.itens[0].cliente)
    assert aba.cliente_escolhido_id() == cliente_com_debito.id
    assert aba.paginas.currentWidget() is aba.rolagem_cliente
    detalhe = aba.detalhe
    assert "Pagou 1 honorário no período" in detalhe.explicacao.text()
    assert detalhe.pagamentos.count() == 1
    assert detalhe.equacao.original._valor.text() == formatar_moeda(linha.honorario.valor_original)

    # testar outro juros ao dia: o dobro da taxa dobra o juros do período
    cenarios = detalhe.cenarios
    taxa = float(detalhe.analise.taxa_atual)
    cenarios.valor.setValue(taxa * 2)
    ultima = cenarios.tabela.rowCount() - 1
    assert "+100%" in cenarios.tabela.item(ultima, 0).text()
    juros = formatar_moeda(detalhe.analise.juros_cobrados * 2)
    assert cenarios.tabela.item(ultima, 2).text() == juros

    # clicar num cenário mostra o efeito honorário por honorário
    por_honorario = detalhe.por_honorario
    assert "Testado" in por_honorario.resumo.text()          # começa no testado
    cenarios.escolher(0)                                      # como está hoje
    assert "como está hoje" in por_honorario.resumo.text()
    assert por_honorario.pagos.item(0, 7).text() == "—"       # sem diferença
    dobrar = [c.rotulo for c in cenarios.cenarios].index("Dobrar")
    cenarios.escolher(dobrar)
    assert "Dobrar" in por_honorario.resumo.text()
    assert por_honorario.pagos.item(0, 6).text() == juros    # juros no cenário
    assert por_honorario.pagos.rowCount() == 2               # o honorário + total

    # a busca filtra a lista; o botão leva à ficha
    aba.busca.setText("nao existe")
    assert aba.lista.count() == 1
    aba.busca.clear()
    aba.escolher_cliente(cliente_com_debito)
    detalhe.abrir_ficha.emit(detalhe.analise.cliente)
    assert abertas == [cliente_com_debito.id]


def test_cartoes_de_honorario_destacam_as_datas(contexto, cliente_com_debito):
    from honorarios.ui.paineis.honorarios import cartao_de_honorario

    linha = linhas_do(contexto.sessao, cliente_com_debito)[0]
    dados = cartao_de_honorario(linha, [])
    rotulos = [data.rotulo for data in dados.datas]
    assert rotulos[:2] == ["Venceu", "Última cobrança"]
    assert dados.datas[0].valor == formatar_data(linha.honorario.vencimento)
    assert dados.datas[0].cor is not None             # atrasado: pílula na cor da faixa
    assert "Vencimento" not in [rotulo for rotulo, _ in dados.detalhes]


def test_atrasados_de_varias_empresas_abre_o_assistente(
    qtbot, contexto, cliente_com_debito, monkeypatch
):
    from honorarios.ui.comum import widgets
    from honorarios.ui.dialogos import assistente
    from honorarios.ui.paineis.honorarios import PainelAtrasados

    outra = fabricas.cliente(
        contexto.sessao, codigo="901", nome="OUTRA EMPRESA LTDA", documento="", juros_dia="0.50"
    )
    fabricas.honorario(contexto.sessao, outra, valor="200.00", vencimento=date(2026, 8, 1))

    chamadas = []

    def falso_assistente(ctx, grupos, parent=None):
        chamadas.append(grupos)
        return assistente.Andamento()

    monkeypatch.setattr(assistente, "executar_assistente", falso_assistente)
    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: True)
    monkeypatch.setattr(widgets, "informar", lambda *a, **k: None)

    painel = PainelAtrasados(contexto)
    qtbot.addWidget(painel)
    painel.lista.selecionar(painel.lista.itens)
    painel._cobrar()
    assert len(chamadas) == 1
    assert len(chamadas[0]) == 2                  # uma entrada por empresa


# ------------------------------------------------- imposto de renda e tipos


@pytest.fixture
def cliente_so_ir(contexto):
    from honorarios.dominio.enums import TipoPessoa
    from honorarios.dominio.valores import Competencia

    cliente = fabricas.cliente(
        contexto.sessao, codigo="700", nome="SO IMPOSTO DE RENDA",
        documento=fabricas.CPF_FICTICIO, tipo=TipoPessoa.PF, juros_dia="0.20",
    )
    cliente.juros[0].vigencia_inicio = date(2020, 1, 1)
    contexto.salvar()
    tipo = fabricas.tipo_irpf(contexto.sessao)
    fabricas.honorario(
        contexto.sessao, cliente, valor="400.00", vencimento=date(2026, 6, 25),
        competencia=Competencia(2026), tipo=tipo,
    )
    fabricas.honorario(
        contexto.sessao, cliente, valor="300.00", vencimento=date(2026, 10, 15),
        competencia=Competencia(2025), tipo=tipo,
    )
    return cliente


def test_tela_de_imposto_de_renda_so_mostra_clientes_so_de_ir(
    qtbot, contexto, cliente_com_debito, cliente_so_ir
):
    from honorarios.ui.paineis.honorarios import PainelAtrasados, PainelImpostoRenda

    ir = PainelImpostoRenda(contexto)
    qtbot.addWidget(ir)
    assert {linha.cliente.id for linha in ir.lista.itens} == {cliente_so_ir.id}
    assert ir.lista.titulos() == ["Atrasados", "A vencer"]
    assert not ir.grupo.isVisibleTo(ir)            # filtro de grupo não faz sentido aqui

    atrasados = PainelAtrasados(contexto)
    qtbot.addWidget(atrasados)
    assert cliente_so_ir.id not in {linha.cliente.id for linha in atrasados.lista.itens}
    assert cliente_com_debito.id in {linha.cliente.id for linha in atrasados.lista.itens}


def test_tela_de_imposto_de_renda_filtra_ano_e_mostra_pagos(qtbot, contexto, cliente_so_ir):
    from honorarios.servicos import pagamentos
    from honorarios.ui.paineis.honorarios import PainelImpostoRenda

    painel = PainelImpostoRenda(contexto)
    qtbot.addWidget(painel)
    painel.ano.setCurrentIndex(painel.ano.findData(2025))
    assert [linha.honorario.competencia_ano for linha in painel.lista.itens] == [2025]

    painel.ano.setCurrentIndex(0)
    linha = next(item for item in painel.lista.itens if item.honorario.competencia_ano == 2026)
    previa = pagamentos.previa(linha.honorario, date(2026, 7, 1))
    pagamentos.registrar(
        contexto.sessao, linha.honorario,
        pagamentos.DadosPagamento(data=date(2026, 7, 1), valor_pago=previa.total_devido),
    )
    contexto.salvar()

    painel.situacao.setCurrentIndex(1)             # Pagos
    assert [item.honorario.id for item in painel.lista.itens] == [linha.honorario.id]
    assert painel.lista.secoes[0].cartoes[0].valor_rotulo == "Recebido"


def test_tela_de_grupos_e_tipos_mostra_os_tipos_do_grupo(qtbot, contexto):
    from honorarios.ui.paineis.tipos import PainelTipos

    painel = PainelTipos(contexto)
    qtbot.addWidget(painel)
    assert painel.lista_grupos.count() == 4
    assert "Imposto de Renda" in painel.lista_grupos.item(2).text()

    painel.lista_grupos.setCurrentRow(0)            # Mensais
    nomes = [tipo.nome for tipo in painel.lista_tipos.itens]
    assert nomes == ["Honorário mensal"]
    cartao = painel.lista_tipos.secoes[0].cartoes[0]
    assert "competência 08/2026" in cartao.subtitulo
    assert [acao.texto for acao in cartao.acoes] == ["Editar", "Desativar"]


def test_dialogo_de_tipo_mostra_previa_e_insere_variavel(qtbot, contexto):
    from honorarios.dominio.enums import ExigeCompetencia
    from honorarios.ui.dialogos.tipo import DialogoTipo

    dialogo = DialogoTipo(contexto)
    qtbot.addWidget(dialogo)
    # tipo novo já vem com o texto padrão da competência escolhida
    assert "competência 08/2026" in dialogo.previas[0].text()

    dialogo.exige.definir(ExigeCompetencia.NENHUMA)
    dialogo.nome.setText("Certidão negativa")
    dialogo._usar_padrao()
    assert "serviço de Certidão negativa" in dialogo.previas[0].text()

    dialogo.texto.setText("honorário de ")
    dialogo._ultimo_campo = dialogo.texto
    dialogo.texto.setCursorPosition(len(dialogo.texto.text()))
    dialogo._inserir("nome_do_tipo")
    assert dialogo.texto.text() == "honorário de {nome_do_tipo}"

    dialogo.texto.setText("referente a {inexistente}")
    assert "⚠" in dialogo.previas[0].text()


def test_lista_de_clientes_marca_perfil_so_ir(qtbot, contexto, cliente_so_ir):
    from honorarios.ui.paineis.clientes import PainelClientes

    painel = PainelClientes(contexto)
    qtbot.addWidget(painel)
    coluna = next(c for c in painel.modelo.colunas if c.titulo == "Perfil")
    linha = next(item for item in painel.modelo.itens if item.cliente.id == cliente_so_ir.id)
    assert coluna.texto(linha) == "Só IR"
