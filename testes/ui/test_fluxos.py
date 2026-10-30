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


def test_atrasados_da_empresa_juntos_com_o_total(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.paineis.honorarios import PainelAtrasados

    painel = PainelAtrasados(contexto)
    qtbot.addWidget(painel)
    # dois da mesma empresa: um grupo, a dívida mais antiga primeiro (41 e 10 dias)
    assert painel.lista.titulos() == ["900 – EMPRESA EXEMPLO LTDA"]
    assert [i.atualizacao.dias_atraso for i in painel.lista.itens] == [41, 10]
    assert painel.lista.secoes[0].total == "R$ 1.551,00"  # 541 + 1.010 com juros
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
    assert [acao.texto for acao in cartao.acoes] == [
        "Histórico", "Editar", "Cobrar", "Confirmar pagamento",
    ]
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
    pagos.ir_para_competencia(linha.honorario.competencia_ano, linha.honorario.competencia_mes)
    assert len(pagos.lista.itens) == 1
    assert not pagos.lista.secoes[0].mostrar_titulo      # um só da empresa: sem grupo
    cartao = pagos.lista.secoes[0].cartoes[0]
    assert cartao.valor_rotulo == "Recebido"
    assert cartao.situacao.startswith("Pago com")          # pagou com atraso
    assert [acao.texto for acao in cartao.acoes] == ["Histórico", "Agradecimento"]


def test_atrasados_agrupados_por_empresa(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.paineis.honorarios import PainelAtrasados

    painel = PainelAtrasados(contexto)
    qtbot.addWidget(painel)
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
    assert len(painel.lista.itens) == 3
    assert all(item.atualizacao.dias_atraso == 0 for item in painel.lista.itens)
    cartao = painel.lista.secoes[0].cartoes[0]
    assert cartao.situacao == "Vence hoje"
    assert [acao.texto for acao in cartao.acoes] == [
        "Histórico", "Editar", "Lembrete", "Confirmar pagamento",
    ]

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


def test_clientes_so_de_ir_ficam_na_aba_deles(qtbot, contexto, cliente_com_debito):
    from honorarios.dominio.enums import SituacaoCliente, TipoPessoa
    from honorarios.ui.paineis.clientes import PainelClientes

    so_ir = fabricas.cliente(contexto.sessao, codigo="960", nome="SO IMPOSTO DE RENDA",
                             documento=fabricas.CPF_FICTICIO, tipo=TipoPessoa.PF)
    fabricas.honorario(contexto.sessao, so_ir, valor="400.00", vencimento=date(2026, 4, 30),
                       competencia=Competencia(2026), tipo=fabricas.tipo_irpf(contexto.sessao))
    ir_inativo = fabricas.cliente(contexto.sessao, codigo="961", nome="IR INATIVO",
                                  documento="", tipo=TipoPessoa.PF)
    fabricas.honorario(contexto.sessao, ir_inativo, valor="300.00", vencimento=date(2026, 4, 30),
                       competencia=Competencia(2026), tipo=fabricas.tipo_irpf(contexto.sessao))
    ir_inativo.situacao = SituacaoCliente.INATIVO
    contexto.salvar()

    painel = PainelClientes(contexto)
    qtbot.addWidget(painel)
    ids = lambda: [linha.cliente.id for linha in painel.modelo.itens]  # noqa: E731
    assert ids() == [cliente_com_debito.id]              # ativos: sem os só de IR
    painel.abas.setCurrentIndex(1)
    assert ids() == [so_ir.id]
    assert "só de Imposto de Renda" in painel.resumo.text()
    painel.abas.setCurrentIndex(2)
    assert ids() == [ir_inativo.id]                      # inativo fica em Inativos


def test_painel_clientes_separa_inativos_e_nao_mostra_divida(
    qtbot, contexto, cliente_com_debito
):
    from honorarios.dominio.enums import SituacaoCliente
    from honorarios.ui.paineis.clientes import PainelClientes

    inativo = fabricas.cliente(contexto.sessao, codigo="950", nome="INATIVA LTDA", documento="")
    inativo.situacao = SituacaoCliente.INATIVO
    contexto.salvar()

    painel = PainelClientes(contexto)
    qtbot.addWidget(painel)
    titulos = [coluna.titulo for coluna in painel.modelo.colunas]
    for removida in ("Situação", "Em aberto", "Total atualizado", "Maior atraso", "Perfil"):
        assert removida not in titulos
    # o inativo só aparece na aba dele
    assert painel.modelo.rowCount() == 1
    assert painel.abas.tabText(0) == "Ativos (1)"
    assert painel.abas.tabText(1) == "Imposto de Renda (0)"
    assert painel.abas.tabText(2) == "Inativos (1)"
    painel.abas.setCurrentIndex(2)
    assert [linha.cliente.id for linha in painel.modelo.itens] == [inativo.id]
    painel.abas.setCurrentIndex(0)
    assert "1 cliente(s) ativo(s)" in painel.resumo.text()

    painel.busca.setText("inexistente")
    assert painel.modelo.rowCount() == 0
    painel.busca.setText("empresa exemplo")
    assert painel.modelo.rowCount() == 1


def test_dialogo_cliente_salva_e_valida(qtbot, contexto, monkeypatch):
    from honorarios.ui.comum import widgets
    from honorarios.ui.dialogos.cliente import DialogoCliente

    avisos: list[str] = []
    monkeypatch.setattr(widgets, "aviso", lambda parent, texto, *a, **k: avisos.append(texto))
    perguntas: list[str] = []
    monkeypatch.setattr(widgets, "confirmar", lambda _p, texto, *a, **k: perguntas.append(texto)
                        or True)

    dialogo = DialogoCliente(contexto)
    qtbot.addWidget(dialogo)
    dialogo.codigo.setText("777")
    dialogo.nome.setText("NOVA EMPRESA EXEMPLO LTDA")
    dialogo.documento.definir("11.222.333/0001-99")  # dígito errado
    dialogo.juros.definir(Decimal("0.54"))
    dialogo._salvar()
    assert avisos and "CPF/CNPJ inválido" in avisos[0]
    assert perguntas == []                        # com erro nos dados, nem pergunta

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
    assert perguntas == ["Salvar o cliente sem honorário recorrente?"]


def test_cadastro_do_cliente_ja_cria_o_honorario_recorrente(qtbot, contexto, monkeypatch):
    from honorarios.dominio.enums import Periodicidade
    from honorarios.servicos import clientes, contratos
    from honorarios.ui.comum import widgets
    from honorarios.ui.dialogos.cliente import DialogoCliente

    perguntas: list[str] = []
    monkeypatch.setattr(widgets, "confirmar", lambda _p, texto, *a, **k: perguntas.append(texto)
                        or False)
    dialogo = DialogoCliente(contexto)
    qtbot.addWidget(dialogo)
    assert dialogo.abas.tabText(2) == "Honorário recorrente"
    dialogo.codigo.setText("778")
    dialogo.nome.setText("EMPRESA COM MENSAL LTDA")
    dialogo.juros.definir(Decimal("1.00"))
    # sem honorário: pergunta; recusando, vai para a aba e nada é gravado
    dialogo._salvar()
    assert perguntas == ["Salvar o cliente sem honorário recorrente?"]
    assert dialogo.abas.currentIndex() == 2
    assert clientes.por_codigo(contexto.sessao, "778") is None

    formulario = dialogo.formulario_honorario
    formulario.tipo.setCurrentIndex(1)
    formulario.valor.definir(Decimal("850.00"))
    formulario.dia.setValue(8)
    dialogo._salvar()
    criado = clientes.por_codigo(contexto.sessao, "778")
    [contrato] = contratos.listar(contexto.sessao, cliente_id=criado.id)
    assert contrato.valor == Decimal("850.00") and contrato.dia_vencimento == 8
    assert contrato.periodicidade is Periodicidade.MENSAL
    assert len(perguntas) == 1                       # com honorário não pergunta

    # o cliente já cadastrado mostra os honorários recorrentes dele
    existente = DialogoCliente(contexto, criado)
    qtbot.addWidget(existente)
    assert existente.tabela_contratos.rowCount() == 1
    assert existente.botao_novo_contrato.isEnabled()


def test_paga_pela_empresa_salva_sem_honorario(qtbot, contexto, monkeypatch):
    from honorarios.dominio.enums import TipoPessoa
    from honorarios.servicos import clientes, contratos
    from honorarios.ui.comum import widgets
    from honorarios.ui.dialogos.cliente import DialogoCliente

    empresa = fabricas.cliente(contexto.sessao, codigo="780", nome="EMPRESA PAGADORA LTDA",
                               documento="")
    perguntas: list[str] = []
    monkeypatch.setattr(widgets, "confirmar", lambda _p, texto, *a, **k: perguntas.append(texto)
                        or True)
    dialogo = DialogoCliente(contexto)
    qtbot.addWidget(dialogo)
    dialogo.codigo.setText("781")
    dialogo.nome.setText("SOCIO DA PAGADORA")
    dialogo.tipo.definir(TipoPessoa.PF)
    dialogo.juros.definir(Decimal("1.00"))
    dialogo.empresa.definir(empresa.id)
    dialogo._ajustar_honorario()
    assert not dialogo.formulario_honorario.isEnabled()
    assert "Paga pela empresa" in dialogo.aviso_honorario.text()
    dialogo._salvar()
    pessoa = clientes.por_codigo(contexto.sessao, "781")
    assert pessoa is not None and pessoa.empresa_id == empresa.id
    assert perguntas == []                           # não precisa perguntar
    assert contratos.listar(contexto.sessao, cliente_id=pessoa.id) == []


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


def test_painel_mostra_o_ano_em_graficos_sem_atraso(
    qtbot, contexto, cliente_com_debito, monkeypatch, tmp_path
):
    from honorarios.ui.paineis.painel import PainelResumo

    painel = PainelResumo(contexto)
    qtbot.addWidget(painel)
    dados = painel.indicadores
    assert painel.cartoes["emitido"]._valor.text() == "R$ 1.500,00"   # 1000 + 500
    assert set(painel.cartoes) == {"emitido", "quitado", "aberto", "caixa", "clientes",
                                   "ticket"}
    # os gráficos recebem os meses e a composição do ano
    assert len(painel.quitacao.meses) == 12
    assert painel.origem.secoes[0][0] == "Por grupo"
    assert painel.leituras.text()
    # nada de atraso no painel: isso é do Ranking dos atrasados
    textos = " ".join(cartao._rotulo.text() for cartao in painel.cartoes.values())
    assert "Juros" not in textos and "Inadimpl" not in textos
    assert "atraso" not in painel.leituras.text().lower()
    # o PDF sai com os gráficos e o mesmo visual da análise de juros
    from honorarios.ui.comum import widgets as widgets_comuns

    abertos = []
    monkeypatch.setattr(widgets_comuns, "abrir_url", lambda url: abertos.append(url))
    painel._exportar(str(tmp_path / "painel.pdf"))
    assert painel.pdf_gerado.read_bytes().count(b"/Subtype /Image") >= 4   # papel + gráficos
    assert abertos == [f"file://{painel.pdf_gerado}"]

    # a mesma série em tabela, para conferir
    painel.alternar.click()
    assert painel.pilha_quitacao.currentWidget() is painel.tabela_mes
    assert painel.modelo_mes.rowCount() == 12
    assert dados.emitido == sum((mes.emitido for mes in dados.meses), start=Decimal(0))


def test_janela_principal_abre_todas_as_telas(qtbot, contexto):
    from honorarios.ui.janela_principal import JanelaPrincipal

    janela = JanelaPrincipal(contexto)
    qtbot.addWidget(janela)
    assert janela.telas.count() == 13
    assert len(janela.linhas_de_tela) == 13
    titulos = [janela.telas.widget(i).titulo for i in range(janela.telas.count())]
    assert "Importação personalizada" in titulos
    assert "Gerenciador de e-mail" in titulos
    assert "Cobranças enviadas" in titulos and "Ranking dos atrasados" in titulos
    assert "Clientes de IR" in titulos and "Tipos e formas de envio" in titulos
    # recorrentes e avulsos viraram abas de uma tela só
    assert "Honorários" in titulos
    assert "Honorários recorrentes" not in titulos and "Honorários avulsos" not in titulos
    assert not any("Fila" in titulo for titulo in titulos)
    # a vencer, atrasados e pagos são abas de Vencimentos, nessa ordem
    assert titulos[0] == "Vencimentos"
    assert not {"A vencer", "Atrasados", "Pagos"} & set(titulos)
    vencimentos = janela.telas.widget(0)
    assert [vencimentos.abas.widget(i).titulo for i in range(3)] == [
        "A vencer", "Atrasados", "Pagos"]
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


def test_pagos_uma_competencia_por_vez(qtbot, contexto, cliente_com_debito):
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
    honorario = linha.honorario
    competencia = (honorario.competencia_ano, honorario.competencia_mes)
    # abre na competência mais recente com pagos
    assert (painel.ano, painel.mes) == competencia
    assert painel.botao_mes.text().startswith(f"Competência {competencia[1]:02d}/")
    assert len(painel.lista.itens) == 1
    painel.anterior.click()                           # a anterior não tem pagos
    assert painel.lista.itens == []
    painel.proximo.click()
    assert len(painel.lista.itens) == 1
    # o menu marca as competências com pagos
    textos = [a.text() for m in painel.botao_mes.menu().actions() if m.menu()
              for a in m.menu().actions()]
    assert f"{competencia[1]:02d}/{competencia[0]}  •" in textos


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


def test_avulso_salvo_ja_abre_a_cobranca_so_dele(
    qtbot, contexto, cliente_com_debito, monkeypatch
):
    from honorarios.ui.dialogos import cobrar
    from honorarios.ui.dialogos.honorario import DialogoHonorario

    abertos: list = []
    monkeypatch.setattr(
        cobrar.DialogoCobrar, "exec", lambda self: abertos.append(self.modelo.itens) or 0
    )
    dialogo = DialogoHonorario(contexto, cliente=cliente_com_debito)
    qtbot.addWidget(dialogo)
    dialogo.tipo.definir(fabricas.tipo_avulso(contexto.sessao).id)
    dialogo.descricao.setText("Mudança de sócio")
    dialogo.valor.definir(Decimal("350.00"))
    dialogo._salvar(cobrar=True)

    # só o avulso recém-lançado, não as outras pendências do cliente
    assert len(abertos) == 1
    assert [linha.honorario.id for linha in abertos[0]] == [dialogo.honorario.id]


def test_painel_de_avulsos_cobra_o_selecionado(qtbot, contexto, cliente_com_debito, monkeypatch):
    from honorarios.ui.dialogos import cobrar
    from honorarios.ui.paineis.avulsos import PainelAvulsos

    avulso = fabricas.honorario(
        contexto.sessao, cliente_com_debito, valor="350.00", competencia=Competencia(),
        tipo=fabricas.tipo_avulso(contexto.sessao), descricao="Mudança de sócio",
    )
    abertos: list = []
    monkeypatch.setattr(
        cobrar.DialogoCobrar, "exec", lambda self: abertos.append(self.modelo.itens) or 0
    )
    painel = PainelAvulsos(contexto)
    qtbot.addWidget(painel)
    painel.tabela.selectRow(0)
    painel._cobrar()

    assert [linha.honorario.id for linha in abertos[0]] == [avulso.id]


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


def test_aba_de_analise_de_juros(
    qtbot, contexto, cliente_com_debito, monkeypatch, tmp_path
):
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
    # os gráficos do cliente: ele × média (4 medidas) e o atraso de cada honorário
    assert [m.rotulo for m in detalhe.comparacao.medidas] == [
        "Pagos com atraso", "Atraso médio", "Cobranças por atraso", "Juros por cobrança",
    ]
    assert [item.honorario.id for item in detalhe.atrasos.itens] == [linha.honorario.id]
    assert not detalhe.caixa_historico.isVisibleTo(detalhe)   # cartões só sob demanda
    detalhe.mostrar_historico.setChecked(True)
    assert detalhe.caixa_historico.isVisibleTo(detalhe)
    assert detalhe.equacao.original._valor.text() == formatar_moeda(linha.honorario.valor_original)

    # testar outro juros ao dia: o dobro da taxa dobra o juros do período
    cenarios = detalhe.cenarios
    taxa = float(detalhe.analise.taxa_atual)
    cenarios.valor.setValue(taxa * 2)
    ultima = cenarios.tabela.rowCount() - 1
    assert "+100%" in cenarios.tabela.item(ultima, 0).text()
    juros = formatar_moeda(detalhe.analise.juros_cobrados * 2)
    assert cenarios.tabela.item(ultima, 2).text() == juros

    # o gráfico de cenários acompanha a tabela, e clicar nele escolhe na tabela
    grafico = detalhe.grafico_cenarios
    assert len(grafico.cenarios) == cenarios.tabela.rowCount()
    ultima = cenarios.tabela.rowCount() - 1          # a linha "Testado"
    cenarios.escolher(0)
    grafico.escolhido.emit(ultima)
    assert cenarios.tabela.currentRow() == ultima and grafico.selecionado == ultima

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

    # exportar o PDF da análise, com o cenário escolhido na tabela
    from honorarios.ui.comum import widgets as widgets_comuns

    abertos_pdf = []
    monkeypatch.setattr(widgets_comuns, "abrir_url", lambda url: abertos_pdf.append(url))
    arquivo_pdf = tmp_path / "analise.pdf"
    from PySide6.QtWidgets import QFileDialog, QPushButton

    # pelo botão, como o usuário faz: o clique manda um bool que não pode virar destino
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **k: (str(arquivo_pdf), "PDF (*.pdf)")
    )
    botao_pdf = next(
        b for b in detalhe.findChildren(QPushButton) if b.text() == "Exportar PDF…"
    )
    botao_pdf.click()
    assert detalhe.pdf_gerado == arquivo_pdf
    assert arquivo_pdf.read_bytes().startswith(b"%PDF")
    # o PDF leva os gráficos da tela (comparação, atrasos, cenários e por honorário)
    assert arquivo_pdf.read_bytes().count(b"/Subtype /Image") >= 4
    assert abertos_pdf == [f"file://{arquivo_pdf}"]

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


def test_lista_de_clientes_poe_o_so_ir_na_aba_dele(qtbot, contexto, cliente_so_ir):
    from honorarios.ui.paineis.clientes import PainelClientes

    painel = PainelClientes(contexto)
    qtbot.addWidget(painel)
    assert cliente_so_ir.id not in [item.cliente.id for item in painel.modelo.itens]
    painel.abas.setCurrentIndex(1)                 # Imposto de Renda
    assert cliente_so_ir.id in [item.cliente.id for item in painel.modelo.itens]


# ------------------------------------------------------ imagem da cobrança


def test_imagem_desenha_fundo_lista_e_qr(qtbot, contexto, cliente_com_debito, tmp_path):
    from PySide6.QtGui import QColor

    from honorarios.servicos import cobrancas as servico
    from honorarios.servicos import imagem_cobranca
    from honorarios.ui.comum.imagem_cobranca import renderizar
    from testes.servicos.test_imagem_cobranca import png_de_qrcode

    imagem_cobranca.definir_qrcode(contexto.sessao, png_de_qrcode(tmp_path / "qr.png"))
    linhas = linhas_do(contexto.sessao, cliente_com_debito)
    dados = imagem_cobranca.montar(
        contexto.sessao, servico.Selecao(cliente=cliente_com_debito, linhas=linhas)
    )
    imagem = renderizar(imagem_cobranca.FUNDO_MODELO.read_text(encoding="utf-8"), dados)
    assert (imagem.width(), imagem.height()) == (1080, 1350)   # proporção do SVG

    # o PNG do QR fica no retângulo id="qrcode" (x 88–360, y 1008–1280)
    pretos = sum(
        1
        for x in range(90, 358, 4)
        for y in range(1010, 1278, 4)
        if QColor(imagem.pixel(x, y)).lightness() < 60
    )
    assert pretos > 200

    # sem QR não há QR: no lugar dele fica só o texto do Pix (bem menos tinta)
    dados.qrcode = None
    sem_qr = renderizar(imagem_cobranca.FUNDO_MODELO.read_text(encoding="utf-8"), dados)
    tinta = sum(
        1
        for x in range(90, 358, 4)
        for y in range(1010, 1278, 4)
        if QColor(sem_qr.pixel(x, y)).lightness() < 60
    )
    assert tinta < pretos / 4


def test_cobrar_gera_imagem_dos_honorarios_marcados(qtbot, contexto, cliente_com_debito):
    from PySide6.QtGui import QGuiApplication

    from honorarios.ui.dialogos.cobrar import ABA_IMAGEM, DialogoCobrar

    linhas = linhas_do(contexto.sessao, cliente_com_debito)
    dialogo = DialogoCobrar(contexto, cliente_com_debito, linhas)
    qtbot.addWidget(dialogo)
    dialogo.abas.setCurrentIndex(ABA_IMAGEM)
    assert dialogo._atualizar_imagem()

    dados = dialogo.dados_imagem
    assert len(dados.linhas) == len(dialogo.modelo.marcados())
    assert dados.campos["cliente"] == cliente_com_debito.nome
    assert dados.campos["total"] == "R$ 1.551,00"
    assert "Valores atualizados até 29/09/2026" in dialogo.imagem_info.text()

    dialogo.copiar_imagem()
    assert not QGuiApplication.clipboard().image().isNull()   # para colar no WhatsApp
    assert QGuiApplication.clipboard().text() == dados.campos["chave_pix"]
    assert "1/2" in dialogo.aviso.text()
    assert dialogo.botao_chave.text() == "2/2 · Copiar chave Pix"
    dialogo.botao_chave.click()
    assert QGuiApplication.clipboard().text() == dados.campos["chave_pix"]


def test_vencimento_da_imagem_nao_aumenta_os_juros(qtbot, contexto, cliente_com_debito):
    """O "pagar até" é só o prazo: os juros vão até a data dos valores (hoje)."""
    from datetime import timedelta

    from honorarios.ui.dialogos.cobrar import DialogoCobrar

    dialogo = DialogoCobrar(contexto, cliente_com_debito, linhas_do(contexto.sessao,
                                                                    cliente_com_debito))
    qtbot.addWidget(dialogo)
    assert dialogo.usar_hoje.isChecked() and dialogo.pagar_ate.valor() == REFERENCIA

    dialogo.pagar_ate.definir(REFERENCIA + timedelta(days=10))
    assert dialogo.total.text() == "R$ 1.551,00"
    assert dialogo._atualizar_imagem()
    assert dialogo.dados_imagem.campos["total"] == "R$ 1.551,00"
    assert dialogo.dados_imagem.campos["vencimento"] == "09/10/2026"
    assert dialogo.dados_imagem.campos["data"] == "29/09/2026"

    # outra data para os valores: aí sim os juros mudam (10 dias a mais × 2 honorários)
    dialogo.data_referencia.definir(REFERENCIA + timedelta(days=10))
    assert dialogo.usar_outra_data.isChecked()
    assert dialogo.total.text() == "R$ 1.571,00"
    dialogo.usar_hoje.setChecked(True)
    assert dialogo.total.text() == "R$ 1.551,00"


def test_conferencia_mostra_a_conta_e_aceita_juros_a_mao(
    qtbot, contexto, cliente_com_debito, monkeypatch
):
    from honorarios.ui.comum import widgets
    from honorarios.ui.dialogos.cobrar import DialogoCobrar

    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: True)
    dialogo = DialogoCobrar(contexto, cliente_com_debito, linhas_do(contexto.sessao,
                                                                    cliente_com_debito))
    qtbot.addWidget(dialogo)
    conta = dialogo.conferencia.toPlainText()
    assert "10 dias × R$ 1,00 por dia = R$ 10,00" in conta
    assert "41 dias × R$ 1,00 por dia = R$ 41,00" in conta

    # juros do primeiro honorário digitado à mão, pelo campo da conferência
    dialogo.tabela.selectRow(0)
    linha = dialogo.modelo.item(0)
    dialogo.juros_editor.definir(Decimal("5.00"))
    dialogo._aplicar_juros_digitado()
    assert linha.atualizacao.juros == Decimal("5.00")
    assert "Juros digitados à mão: R$ 5,00" in dialogo.conferencia.toPlainText()
    assert dialogo.botao_calculado.isEnabled()
    novo_total = linha.atualizacao.total + dialogo.modelo.item(1).atualizacao.total
    assert dialogo.total.text() == formatar_moeda(novo_total)
    assert formatar_moeda(novo_total) in dialogo.texto.toPlainText()

    # a imagem e o acordo usam o juros digitado
    assert dialogo._atualizar_imagem()
    assert dialogo.dados_imagem.campos["total"] == formatar_moeda(novo_total)
    dialogo.acordo.setChecked(True)
    dialogo.copiar_imagem()
    assert "Acordo guardado" in dialogo.aviso.text()
    assert linha.honorario.acordos[-1].juros == Decimal("5.00")

    # e o registro guarda o total com ele
    dialogo._registrar()
    historico = servico_cobrancas.historico_do_cliente(contexto.sessao, cliente_com_debito.id)
    assert sum(c.valor_atualizado_no_momento for c in historico) == novo_total

    # voltar ao calculado
    outro = DialogoCobrar(contexto, cliente_com_debito, linhas_do(contexto.sessao,
                                                                  cliente_com_debito))
    qtbot.addWidget(outro)
    outro.definir_juros(outro.modelo.item(0), Decimal("1"))
    outro.tabela.selectRow(0)
    outro._voltar_ao_calculado()
    assert outro.total.text() == "R$ 1.551,00"


def test_lembrete_antes_do_vencimento_com_outro_vencimento(qtbot, contexto, cliente_com_debito):
    """Competência que só vence no mês seguinte: vai o lembrete, com o vencimento certo."""
    from honorarios.ui.dialogos.cobrar import DialogoCobrar

    futuro = fabricas.honorario(contexto.sessao, cliente_com_debito, valor="800.00",
                                vencimento=date(2026, 10, 10),
                                competencia=Competencia(2026, 9))
    linhas = [linha for linha in linhas_do(contexto.sessao, cliente_com_debito)
              if linha.honorario.id == futuro.id]
    dialogo = DialogoCobrar(contexto, cliente_com_debito, linhas)
    qtbot.addWidget(dialogo)

    assert dialogo.lembrete.isChecked() and not dialogo.tipo_cobranca.isEnabled()
    assert dialogo.pagar_ate.valor() == date(2026, 10, 10)     # o vencimento dele
    assert "10/10/2026" in dialogo.texto.toPlainText()
    assert "Ainda no prazo: sem juros." in dialogo.conferencia.toPlainText()

    dialogo.pagar_ate.definir(date(2026, 10, 15))
    assert "15/10/2026" in dialogo.texto.toPlainText()
    assert dialogo._atualizar_imagem()
    assert dialogo.dados_imagem.campos["vencimento"] == "15/10/2026"
    dialogo._vencimento_automatico()
    assert dialogo.pagar_ate.valor() == date(2026, 10, 10)


def test_imagem_estica_quando_os_honorarios_nao_cabem(qtbot, contexto, tmp_path):
    from PySide6.QtGui import QColor

    from honorarios.servicos import imagem_cobranca
    from honorarios.ui.comum import imagem_cobranca as desenho
    from testes.servicos.test_imagem_cobranca import png_de_qrcode

    imagem_cobranca.definir_qrcode(contexto.sessao, png_de_qrcode(tmp_path / "qr.png"))
    fundo = imagem_cobranca.FUNDO_MODELO.read_text(encoding="utf-8")
    dados = imagem_cobranca.exemplo(contexto.sessao)

    assert desenho.renderizar(fundo, dados).height() == 1350      # 3 cabem no fundo

    dados.linhas = [dados.linhas[i % 3] for i in range(12)]
    esticada = desenho.renderizar(fundo, dados)
    # a lista do modelo tem 364 px; 12 linhas × 84 px pedem 644 px a mais
    assert esticada.width() == 1080
    assert esticada.height() == 1350 + 12 * desenho.ALTURA_ESTICADA - 364

    # o QR desceu junto com o resto do desenho
    deslocamento = esticada.height() - 1350
    pretos = sum(
        1
        for x in range(118, 358, 4)
        for y in range(934 + deslocamento, 1174 + deslocamento, 4)
        if QColor(esticada.pixel(x, y)).lightness() < 60
    )
    assert pretos > 200

    # acima do máximo, a imagem para de crescer e o resto vira "e mais N"
    dados.linhas = [dados.linhas[i % 3] for i in range(60)]
    maior = desenho.renderizar(fundo, dados)
    assert maior.height() == 1350 + desenho.MAXIMO_LINHAS * desenho.ALTURA_ESTICADA - 364


# ---------------------------------------------------- avulsos e editar no cartão


def test_avulsos_e_historico_cobram_mas_nao_pagam(qtbot, contexto, cliente_com_debito):
    from PySide6.QtWidgets import QPushButton

    from honorarios.servicos import pagamentos
    from honorarios.ui.paineis.avulsos import PainelAvulsos

    avulso = fabricas.honorario(
        contexto.sessao, cliente_com_debito, valor="300.00", vencimento=date(2026, 9, 10),
        tipo=fabricas.tipo_avulso(contexto.sessao), competencia=Competencia(),
        descricao="Alteração de endereço",
    )
    pago = fabricas.honorario(
        contexto.sessao, cliente_com_debito, valor="200.00", vencimento=date(2026, 8, 10),
        tipo=fabricas.tipo_avulso(contexto.sessao), competencia=Competencia(),
        descricao="Ata de sócios",
    )
    previa = pagamentos.previa(pago, date(2026, 8, 10))
    pagamentos.registrar(contexto.sessao, pago, pagamentos.DadosPagamento(
        data=date(2026, 8, 10), valor_pago=previa.total_devido))
    contexto.salvar()

    painel = PainelAvulsos(contexto)
    qtbot.addWidget(painel)
    textos = [b.text() for b in painel.findChildren(QPushButton)]
    assert "Lançar avulso" in textos and "Editar" in textos and "Cancelar…" in textos
    # cobra daqui mesmo; a baixa continua em Atrasados e A vencer
    assert "Cobrar" in textos and "Registrar pagamento" not in textos

    # pagos continuam no histórico, com a data do pagamento; mais recente primeiro
    itens = painel.modelo.itens
    assert [linha.honorario.id for linha in itens] == [avulso.id, pago.id]
    coluna = next(c for c in painel.modelo.colunas if c.titulo == "Situação")
    assert coluna.texto(itens[1]) == "Pago em 10/08/2026"
    assert coluna.texto(itens[0]).startswith("Em atraso há")

    painel.situacao.setCurrentIndex(2)          # só os pagos
    assert [linha.honorario.id for linha in painel.modelo.itens] == [pago.id]


def test_cartao_em_aberto_tem_editar(qtbot, contexto, cliente_com_debito, monkeypatch):
    from honorarios.ui.dialogos import honorario as dialogo_honorario
    from honorarios.ui.paineis.honorarios import PainelAtrasados

    abertos = []
    monkeypatch.setattr(
        dialogo_honorario.DialogoHonorario, "exec",
        lambda self: abertos.append(self) or 0,
    )
    painel = PainelAtrasados(contexto)
    qtbot.addWidget(painel)
    linha = linhas_do(contexto.sessao, cliente_com_debito)[0]
    acoes = {acao.texto: acao for acao in painel._acoes_do_cartao(linha)}
    assert list(acoes) == ["Histórico", "Editar", "Cobrar", "Confirmar pagamento"]
    acoes["Editar"].funcao(linha)
    assert len(abertos) == 1


def test_confirmar_pagamento_no_cartao(qtbot, contexto, cliente_com_debito, monkeypatch):
    from PySide6.QtWidgets import QPushButton

    from honorarios.ui.comum.cartoes import CartaoRegistro
    from honorarios.ui.paineis import honorarios as paineis

    abertos = []
    monkeypatch.setattr(
        paineis.DialogoPagamento, "exec", lambda self: abertos.append(self.honorario) or 0
    )
    painel = paineis.PainelAtrasados(contexto)
    qtbot.addWidget(painel)
    linha = linhas_do(contexto.sessao, cliente_com_debito)[0]
    pagar = next(a for a in painel._acoes_do_cartao(linha) if a.texto == "Confirmar pagamento")
    assert pagar.pagamento                                    # o botão verde

    # o cartão desenha o botão no estilo de pagamento e o clique abre a baixa
    cartao = CartaoRegistro(painel._cartao(linha))
    qtbot.addWidget(cartao)
    botao = next(b for b in cartao.findChildren(QPushButton) if b.text() == "Confirmar pagamento")
    assert botao.objectName() == "cartaoPagamento"
    botao.click()
    assert abertos == [linha.honorario]


def test_honorarios_tem_abas_recorrentes_e_avulsos(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.paineis.cadastro_honorarios import PainelHonorarios

    painel = PainelHonorarios(contexto)
    qtbot.addWidget(painel)
    assert [painel.abas.tabText(i) for i in range(painel.abas.count())] == [
        "Mês a mês", "Recorrentes", "Avulsos",
    ]
    assert painel.abas.currentWidget() is painel.mes_a_mes
    painel.abas.setCurrentIndex(2)
    assert painel.abas.currentWidget() is painel.avulsos
    painel.recarregar()                     # recarrega a aba aberta


def test_topo_da_cobranca_enxuto_com_chips(qtbot, contexto, cliente_com_debito):
    from PySide6.QtWidgets import QPushButton

    from honorarios.ui.paineis.honorarios import PainelAtrasados

    painel = PainelAtrasados(contexto)
    qtbot.addWidget(painel)
    painel.show()
    # à mostra só a ação principal; o resto fica no menu Ações, com os atalhos
    visiveis = [b.text() for b in painel.findChildren(QPushButton) if b.isVisible()]
    assert "Cobrar selecionados" in visiveis
    assert "Registrar pagamento" not in visiveis and "Exportar lista" not in visiveis
    acoes = {acao.text(): acao.shortcut().toString() for acao in painel.menu_acoes.actions()
             if acao.text()}
    assert acoes["Registrar pagamento"] == "Ctrl+P"
    assert acoes["Ficha da empresa"] == "Ctrl+F"
    assert acoes["Atualizar"] == "F5"
    assert "Renegociar selecionados" in acoes and "Exportar lista" in acoes

    # sem os filtros de faixa, "nunca cobrado" e agrupar: a lista é sempre por empresa
    assert not hasattr(painel, "faixa") and not hasattr(painel, "nunca_cobrado")
    assert not hasattr(painel, "agrupamento")


def test_janela_tem_logo_e_progresso(qtbot, contexto):
    from honorarios.ui.janela_principal import JanelaPrincipal

    passos = []
    janela = JanelaPrincipal(contexto, progresso=lambda pct, texto: passos.append((pct, texto)))
    qtbot.addWidget(janela)
    # a tela de abertura recebe o progresso de cada tela montada
    assert len(passos) == janela.telas.count()
    assert passos[0][1].startswith("Carregando ")
    assert not janela.logo_menu.pixmap().isNull()          # a logo fica no menu
    assert not hasattr(janela, "resumo_do_dia")            # sem cartão de resumo ao abrir


def test_tela_de_abertura(qtbot):
    from honorarios.ui.comum.logo import TelaAbertura

    abertura = TelaAbertura()
    qtbot.addWidget(abertura)
    abertura.avancar(40, "Carregando Atrasados…")
    assert abertura.barra.value() == 40
    assert abertura.mensagem.text() == "Carregando Atrasados…"


def test_mes_a_mes_navega_e_gera_a_competencia_do_mes(
    qtbot, contexto, cliente_com_debito, monkeypatch
):
    from honorarios.ui.dialogos import competencia
    from honorarios.ui.paineis.mes_a_mes import PainelMesAMes

    fabricas.contrato(contexto.sessao, cliente_com_debito)
    painel = PainelMesAMes(contexto)
    qtbot.addWidget(painel)
    painel.ir_para(2026, 8)
    assert painel.botao_mes.text().startswith("Agosto de 2026")
    # competência 08/2026 do cliente (vence em 19/09) está em agosto
    assert [linha.honorario.competencia_mes for linha in painel.modelo.itens] == [8]

    painel.anterior.click()
    assert (painel.ano, painel.mes) == (2026, 7)
    painel.proximo.click()
    painel.proximo.click()
    assert (painel.ano, painel.mes) == (2026, 9)

    # o menu do mês leva direto a qualquer mês, por ano
    anos = [acao.text() for acao in painel.botao_mes.menu().actions()]
    assert "2026" in anos

    # o contrato ainda não gerou setembro: aviso e botão com a contagem
    assert painel.aviso_geracao.isVisibleTo(painel)
    assert painel.gerar.text() == "Gerar competência (1)"
    abertos = []
    monkeypatch.setattr(competencia.DialogoGerarCompetencia, "exec",
                        lambda self: abertos.append((self.ano.value(), self.mes.currentData())))
    painel.gerar.click()
    assert abertos == [(2026, 9)]                       # abre no mês da tela

    # filtros: origem e situação
    painel.origem.setCurrentIndex(2)                    # só avulsos
    assert painel.modelo.itens == []


def test_agradecimento_pelo_pagamento(qtbot, contexto, cliente_com_debito, monkeypatch):
    from honorarios.servicos import imagem_cobranca
    from honorarios.ui.comum.imagem_cobranca import renderizar_agradecimento
    from honorarios.ui.dialogos import imagem_cobranca as dialogo_imagem
    from honorarios.ui.dialogos.pagamento import DialogoPagamento

    linha = linhas_do(contexto.sessao, cliente_com_debito)[0]
    abertos = []
    monkeypatch.setattr(dialogo_imagem.DialogoImagemCobranca, "exec",
                        lambda self: abertos.append(self) or 0)

    # na baixa: a caixa marcada abre a imagem de agradecimento e fica lembrada
    dialogo = DialogoPagamento(contexto, linha.honorario)
    qtbot.addWidget(dialogo)
    dialogo.agradecer.setChecked(True)
    dialogo._registrar()
    [aberto] = abertos
    assert aberto.agradecimento
    assert aberto.dados.campos["cliente"] == cliente_com_debito.nome
    assert aberto.dados.linhas[0].detalhe.startswith("Vencimento ")
    from honorarios.servicos import configuracoes
    assert configuracoes.obter_bool(contexto.sessao, "agradecimento_apos_baixa")

    # o desenho: proporção da cobrança, em resolução maior
    dados = imagem_cobranca.montar_agradecimento(contexto.sessao, [linha.honorario])
    imagem = renderizar_agradecimento(
        imagem_cobranca.FUNDO_MODELO.read_text(encoding="utf-8"), dados
    )
    assert (imagem.width(), imagem.height()) == (1620, 2025)


def test_imagem_de_cobranca_usa_a_logo_nova():
    from honorarios.servicos import imagem_cobranca

    fundo = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<g id="logo-imagem"><rect width="1" height="1"/></g>'
        '<g id="logo-pdf"><rect width="2" height="2"/></g>'
        '<g id="conteudo"><text>{cliente}</text></g></svg>'
    )
    imagem = imagem_cobranca.para_imagem(fundo)
    assert 'id="logo-pdf"' in imagem and 'id="logo-imagem"' not in imagem
    papel = imagem_cobranca.base_do_fundo(fundo)
    assert 'id="logo-pdf"' in papel and "conteudo" not in papel


def test_notificacoes_na_janela(qtbot, contexto, cliente_com_debito, monkeypatch):
    from PySide6.QtWidgets import QPushButton

    from honorarios.ui import janela_principal
    from honorarios.ui.janela_principal import JanelaPrincipal

    monkeypatch.setattr(janela_principal, "hoje", lambda: date(2026, 9, 30))
    avisos_do_sistema = []
    janela = JanelaPrincipal(contexto)
    qtbot.addWidget(janela)
    monkeypatch.setattr(janela, "_notificar_sistema", avisos_do_sistema.append)

    # ao abrir: cria e conta, sem aviso no canto (não atrapalha a abertura)
    janela.iniciar_notificacoes()
    assert janela.botao_notificacoes.quantidade == 1     # venceu em 19/09 sem pagamento
    assert janela.verificacao.isActive()
    assert not janela.aviso_novo.isVisible() and avisos_do_sistema == []

    # com o sistema aberto, surge um vencimento de hoje: aviso no canto e do sistema
    fabricas.honorario(contexto.sessao, cliente_com_debito, valor="200.00",
                       vencimento=date(2026, 9, 30), competencia=Competencia(2026, 9))
    janela.show()
    assert len(janela.verificar_notificacoes()) == 1
    assert janela.aviso_novo.isVisible()
    assert avisos_do_sistema == ["1 cliente com vencimento hoje"]
    assert janela.botao_notificacoes.quantidade == 2

    # "Abrir" marca como lida e leva à tela já buscando o cliente
    janela.abrir_notificacoes()
    lista = janela.lista_notificacoes
    item = lista.itens.itemAt(0).widget()
    item.findChild(QPushButton, "cartaoAcao").click()
    vencimentos = janela.telas.currentWidget()
    assert vencimentos.titulo == "Vencimentos"
    painel = vencimentos.abas.currentWidget()                # já na aba do aviso
    assert painel.titulo in ("A vencer", "Atrasados")
    assert painel.busca.text() == cliente_com_debito.nome
    assert janela.botao_notificacoes.quantidade == 1

    lista.botao_todas.click()
    assert janela.botao_notificacoes.quantidade == 0


def test_configuracao_da_geracao_automatica(qtbot, contexto, monkeypatch):
    from honorarios.servicos import geracao_automatica
    from honorarios.ui.comum import widgets
    from honorarios.ui.paineis.configuracoes import PainelConfiguracoes

    monkeypatch.setattr(widgets, "informar", lambda *a, **k: None)
    painel = PainelConfiguracoes(contexto)
    qtbot.addWidget(painel)
    painel.recarregar()
    assert not painel.geracao_automatica.isChecked()      # desligada por padrão
    assert not painel.geracao_dia.isEnabled()
    painel.geracao_automatica.setChecked(True)
    painel.geracao_dia.setValue(10)
    painel._salvar()
    assert geracao_automatica.ligada(contexto.sessao)
    assert geracao_automatica.dia(contexto.sessao) == 10


def test_aviso_do_canto_fica_por_cima_ao_trocar_de_tela(qtbot, contexto):
    from PySide6.QtCore import QPoint

    from honorarios.ui.janela_principal import JanelaPrincipal

    janela = JanelaPrincipal(contexto)
    qtbot.addWidget(janela)
    janela.show()
    aviso = janela.aviso_novo
    aviso.mostrar("1 cliente com vencimento hoje")
    janela._posicionar_aviso()

    def por_cima() -> bool:
        centro = aviso.mapTo(janela.central, QPoint(aviso.width() // 2, 12))
        alvo = janela.central.childAt(centro)
        return alvo is aviso or aviso.isAncestorOf(alvo)

    for linha in list(janela.linhas_de_tela)[:4]:   # passa por várias telas e volta
        janela.navegacao.setCurrentRow(linha)
        assert aviso.isVisible() and por_cima()


def _lista_do_financeiro(contexto, sem: str = "19/09/2026") -> bytes:
    """O e-mail do financeiro: a lista do sistema sem o honorário de ``sem``."""
    from email.message import EmailMessage

    from honorarios.servicos import email_cobrancas

    lista = email_cobrancas.texto(email_cobrancas.montar(contexto.sessao, date(2026, 9, 30)))
    lista = "\n".join(linha for linha in lista.splitlines() if sem not in linha)
    mensagem = EmailMessage()
    mensagem["From"] = "Financeiro <financeiro@exemplo.com.br>"
    mensagem["To"] = "cobranca@exemplo.com.br"
    mensagem["Cc"] = "Gerencia <gerencia@exemplo.com.br>"
    mensagem["Subject"] = "Clientes c/Honorários vencidos"
    mensagem["Date"] = "Wed, 30 Sep 2026 09:00:00 -0300"
    mensagem["Message-ID"] = "<lista@exemplo.com.br>"
    mensagem.set_content(lista)
    return bytes(mensagem)


class CaixaDeMentira:
    def __init__(self, brutos):
        self.brutos, self.respostas = brutos, []

    def baixar(self, ja_tenho, assunto):
        from honorarios.servicos import caixa_email

        return [m for m in (caixa_email.de_mime(b, ref_provedor="1") for b in self.brutos)
                if m.message_id not in ja_tenho]

    def responder(self, original, resposta):
        from honorarios.servicos import caixa_email

        self.respostas.append((original, resposta))
        return caixa_email.MensagemBaixada(
            message_id="<resposta@exemplo.com.br>", assunto=resposta.assunto,
            de="cobranca@exemplo.com.br", para=resposta.para, cc=resposta.cc,
            data=original.recebido_em, html=resposta.html, texto=resposta.texto,
        )

    def enviar_novo(self, resposta):
        from honorarios.servicos import caixa_email

        self.respostas.append((None, resposta))
        return caixa_email.MensagemBaixada(
            message_id="<novo@exemplo.com.br>", assunto=resposta.assunto,
            de="cobranca@exemplo.com.br", para=resposta.para, cc=resposta.cc,
            data=date(2026, 9, 30), html=resposta.html, texto=resposta.texto,
        )


def test_caixa_de_email_verificar_conferir_e_responder(
    qtbot, contexto, cliente_com_debito, monkeypatch
):
    from honorarios.servicos import caixa_email
    from honorarios.ui.comum import segundo_plano, widgets
    from honorarios.ui.paineis import email_cobrancas as tela

    contexto.data_referencia = date(2026, 9, 30)
    caixa_email.gravar_conta(contexto.sessao, caixa_email.ContaEmail(
        provedor=caixa_email.GMAIL, endereco="cobranca@exemplo.com.br"))
    caixa = CaixaDeMentira([_lista_do_financeiro(contexto)])
    monkeypatch.setattr(caixa_email, "abrir_caixa", lambda sessao: caixa)
    painel = tela.PainelEmailCobrancas(contexto)
    painel.executor = segundo_plano.imediato
    qtbot.addWidget(painel)
    painel.recarregar()
    assert painel.lista_vazia.isVisibleTo(painel)
    assert "Gmail" in painel.situacao.text()

    chegaram = []
    painel.chegaram.connect(chegaram.append)
    painel.verificar()
    assert chegaram == [1] and painel.lista.count() == 1
    assert "1 e-mail(s) novo(s)" in painel.situacao.text()
    item = painel.lista.itemWidget(painel.lista.item(0))
    assert item.quem.text() == "Financeiro"

    # abrir: marca como lido, confere e já prepara a resposta
    painel.lista.setCurrentRow(0)
    assert painel.mensagem.lida
    assert painel.abas.tabText(1) == "Conferir com o sistema · 1 saíram"
    assert "1 continuam · 1 saíram" in painel.conferencia_aba.resumo.text()
    responder = painel.responder
    assert responder.para.text() == "Financeiro <financeiro@exemplo.com.br>"
    assert responder.cc.text() == "Gerencia <gerencia@exemplo.com.br>"
    assert responder.assunto.text() == "RE: Clientes c/Honorários vencidos"
    assert "19/09/2026" not in responder.editor.toPlainText()     # quem saiu não volta
    assert responder.botao_enviar.isEnabled()

    # enviar pede confirmação; recusando, nada sai
    perguntas = []
    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: perguntas.append(a) or False)
    responder.botao_enviar.click()
    assert perguntas and caixa.respostas == []
    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: True)
    responder.editor.insertPlainText("Bom dia! ")                # dá para escrever antes
    responder.botao_enviar.click()
    [(original, resposta)] = caixa.respostas
    assert original.message_id == "<lista@exemplo.com.br>"
    assert "Bom dia!" in resposta.texto
    assert painel.mensagem.message_id == original.message_id
    assert painel.mensagem.respondida_em is not None
    assert responder.aviso.text() == "✓ Resposta enviada."
    # recebidos e enviados ficam separados
    assert painel.lista.count() == 1
    assert painel.botao_enviados.text() == "Enviados por você (1)"
    painel.mostrar_caixa(enviados=True)
    assert painel.lista.count() == 1 and painel.direita.currentIndex() == 0
    painel.lista.setCurrentRow(0)                                # a resposta: só leitura
    assert painel.mensagem.enviada and not painel.abas.isTabEnabled(2)
    painel.mostrar_caixa(enviados=False)
    painel.lista.setCurrentRow(0)                                # reabrindo o original
    assert "Já respondido" in responder.aviso.text()

    # de novo, nada repetido
    painel.verificar()
    assert painel.lista.count() == 1 and chegaram == [1]

    # "Montar resposta" refaz com os dados de agora; com texto editado, pergunta antes
    painel.lista.setCurrentRow(0)
    painel.responder.editor.insertPlainText("rascunho meu ")
    perguntas.clear()
    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: perguntas.append(a[1]) or False)
    painel.botao_responder.click()
    assert perguntas == ["Montar a resposta de novo?"]
    assert "rascunho meu" in painel.responder.editor.toPlainText()   # recusou: ficou
    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: True)
    painel.botao_responder.click()
    assert "rascunho meu" not in painel.responder.editor.toPlainText()
    assert painel.abas.currentWidget() is painel.responder

    # e-mail novo pelo sistema: já para quem mandou o último e-mail, e envia daqui
    painel.botao_novo.click()
    assert painel.responder.para.text() == "Financeiro <financeiro@exemplo.com.br>"
    assert painel.responder.botao_enviar.isEnabled()
    painel.responder.botao_enviar.click()
    novo, resposta = caixa.respostas[-1]
    assert novo is None and resposta.assunto == "Clientes c/Honorários vencidos"
    assert painel.botao_enviados.text() == "Enviados por você (2)"


def test_caixa_de_email_sem_conta(qtbot, contexto, cliente_com_debito, tmp_path):
    from honorarios.ui.comum import segundo_plano
    from honorarios.ui.paineis import email_cobrancas as tela

    contexto.data_referencia = date(2026, 9, 30)
    painel = tela.PainelEmailCobrancas(contexto)
    painel.executor = segundo_plano.imediato
    qtbot.addWidget(painel)
    painel.recarregar()
    assert not painel.botao_verificar.isEnabled()
    assert painel.vazio_configurar.isVisibleTo(painel)

    arquivo = tmp_path / "lista.eml"
    arquivo.write_bytes(_lista_do_financeiro(contexto))
    painel.abrir_arquivo(str(arquivo))
    assert painel.lista.count() == 1
    assert painel.abas.currentWidget() is painel.conferencia_aba
    assert not painel.responder.botao_enviar.isEnabled()       # veio de arquivo: copiar
    destino = tmp_path / "resposta.eml"
    from honorarios.servicos import email_cobrancas

    email_cobrancas.gravar_remetente(contexto.sessao, email_cobrancas.Remetente(
        email="cobranca@exemplo.com.br"))
    painel.responder.salvar_rascunho(str(destino))
    assert b"In-Reply-To: <lista@exemplo.com.br>" in destino.read_bytes()

    # o botão do topo: e-mail novo, já endereçado a quem mandou o último e-mail
    painel.botao_novo.click()
    assert painel.assunto.text() == "Novo e-mail pelo sistema"
    assert "19/09/2026" in painel.responder.editor.toPlainText()
    assert painel.responder.assunto.text() == "Clientes c/Honorários vencidos"   # sem "RE:"
    assert painel.responder.para.isEnabled()
    assert not painel.responder.botao_enviar.isEnabled()      # sem conta: copiar/rascunho
    painel.recarregar()                                       # continua na tela
    assert painel.direita.currentIndex() == 1


def test_dialogo_conta_de_email(qtbot, contexto, cofre, monkeypatch):
    from honorarios.servicos import caixa_email
    from honorarios.ui.comum import segundo_plano
    from honorarios.ui.dialogos.conta_email import DialogoContaEmail

    dialogo = DialogoContaEmail(contexto, executor=segundo_plano.imediato)
    qtbot.addWidget(dialogo)
    dialogo.provedor.setCurrentIndex(dialogo.provedor.findData(caixa_email.GMAIL))
    dialogo.endereco.setText("cobranca@exemplo.com.br")
    dialogo.senha_gmail.setText("abcd efgh ijkl mnop")          # o Gmail mostra com espaços
    monkeypatch.setattr(caixa_email.CaixaImap, "testar", lambda self: "Conectado: 2 e-mail(s)")
    dialogo.testar()
    assert dialogo.resultado.text() == "✓ Conectado: 2 e-mail(s)"
    dialogo._salvar()
    conta = caixa_email.conta(contexto.sessao)
    assert conta.provedor == caixa_email.GMAIL and conta.pasta == "Cobranças"
    assert caixa_email.ler_segredo(caixa_email.chave_senha("cobranca@exemplo.com.br")) == \
        "abcdefghijklmnop"                                       # no cofre, sem espaços
    from honorarios.infra.modelos import Configuracao

    valores = " ".join(c.valor for c in contexto.sessao.query(Configuracao))
    assert "abcdefgh" not in valores                             # nunca no banco


def test_caixa_de_email_baixa_dos_que_sairam_e_retorno(
    qtbot, contexto, cliente_com_debito, monkeypatch
):
    from honorarios.dominio.enums import StatusPagamento
    from honorarios.servicos import caixa_email
    from honorarios.ui.comum import segundo_plano, widgets
    from honorarios.ui.dialogos import retorno
    from honorarios.ui.paineis import email_cobrancas as tela

    contexto.data_referencia = date(2026, 9, 30)
    caixa_email.gravar_conta(contexto.sessao, caixa_email.ContaEmail(
        provedor=caixa_email.GMAIL, endereco="cobranca@exemplo.com.br"))
    caixa = CaixaDeMentira([_lista_do_financeiro(contexto)])
    monkeypatch.setattr(caixa_email, "abrir_caixa", lambda sessao: caixa)
    painel = tela.PainelEmailCobrancas(contexto)
    painel.executor = segundo_plano.imediato
    qtbot.addWidget(painel)
    painel.recarregar()
    painel.verificar()

    # e-mail novo com gente que saiu: a baixa abre sozinha, ao lado
    painel.lista.setCurrentRow(0)
    janela = painel.janela_baixa
    assert janela is not None and janela.isVisible() and not janela.isModal()
    assert painel.abas.currentWidget() is painel.conferencia_aba
    assert painel.conferencia_aba.faixa_saiu.isVisibleTo(painel)
    [item] = janela.itens
    assert item.honorario.vencimento == date(2026, 9, 19)
    assert janela.data.valor() == date(2026, 9, 30)            # a data do e-mail
    assert item.valor > item.saldo                             # com juros, por padrão
    janela.sem_juros.setChecked(True)
    [item] = janela.itens
    assert item.valor == item.saldo and item.justificativa

    perguntas = []
    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: perguntas.append(a[1]) or True)
    janela.botao_baixa.click()
    assert perguntas[0] == "Confirmar o pagamento de 1 honorário?"
    assert item.honorario.status is StatusPagamento.PAGO
    assert painel.conferencia.sairam == []
    assert not painel.conferencia_aba.faixa_saiu.isVisibleTo(painel)
    assert "Baixa de 1" in painel.responder.aviso.text()

    # anotar o retorno de quem continua: entra na resposta ao financeiro
    arvore = painel.conferencia_aba.arvore
    continuam = arvore.topLevelItem(0)
    assert continuam.text(0).startswith("Continuam em aberto")
    arvore.clearSelection()
    continuam.child(0).setSelected(True)
    assert painel.conferencia_aba.botao_retorno.isEnabled()

    def responder_e_salvar(dialogo):
        dialogo.resultado.definir(ResultadoCobranca.PROMETEU_PAGAR)
        dialogo.promessa.definir(date(2026, 10, 5))
        dialogo.observacao.setPlainText("vai pagar o de agosto dia 05")
        dialogo._salvar()
        return dialogo.result()

    monkeypatch.setattr(retorno.DialogoRetorno, "exec", responder_e_salvar)
    painel.conferencia_aba.botao_retorno.click()
    texto = painel.responder.editor.toPlainText()
    assert "prometeu pagar em 05/10 - vai pagar o de agosto dia 05" in texto
    assert "A resposta já inclui o retorno" in painel.responder.aviso.text()


def test_telas_montadas_ao_abrir_e_sem_reler_a_toa(qtbot, contexto, monkeypatch):
    from honorarios.ui.janela_principal import JanelaPrincipal, TelaAdiada

    janela = JanelaPrincipal(contexto)
    qtbot.addWidget(janela)
    adiadas = [janela.telas.widget(i) for i in range(janela.telas.count())
               if isinstance(janela.telas.widget(i), TelaAdiada)]
    assert len(adiadas) == janela.telas.count() - 2       # só Atrasados e E-mail já montadas

    linha_pagos = next(linha for linha, indice in janela.linhas_de_tela.items()
                       if janela.telas.widget(indice).titulo == "Clientes")
    janela.navegacao.setCurrentRow(linha_pagos)            # monta na primeira vez
    pagos = janela.telas.currentWidget()
    assert not isinstance(pagos, TelaAdiada) and pagos.titulo == "Clientes"

    leituras = []
    monkeypatch.setattr(pagos, "recarregar", lambda: leituras.append(1))
    primeira = next(iter(janela.linhas_de_tela))
    janela.navegacao.setCurrentRow(primeira)
    janela.navegacao.setCurrentRow(linha_pagos)
    assert leituras == []                                  # nada mudou: não relê
    contexto.salvar()                                      # gravou algo
    janela.navegacao.setCurrentRow(primeira)
    janela.navegacao.setCurrentRow(linha_pagos)
    assert leituras == [1]
    janela._recarregar_atual(forcar=True)                  # F5 sempre relê
    assert leituras == [1, 1]


def test_confirmacao_no_visual_do_sistema(qtbot):
    from honorarios.ui.comum.widgets import DialogoConfirmacao

    dialogo = DialogoConfirmacao(None, "Confirmar o pagamento de 2 honorários?", "Dar baixa",
                                 "Dá para estornar depois.", acao="Dar baixa em 2",
                                 resumo=[("Total recebido", "R$ 895,08")], tipo="pagamento")
    qtbot.addWidget(dialogo)
    assert dialogo.botao_acao.text() == "Dar baixa em 2"
    assert dialogo.botao_acao.objectName() == "cartaoPagamento"
    dialogo.botao_acao.click()
    assert dialogo.result() == 1


def test_corrigir_linha_do_email_libera_a_baixa(qtbot, contexto, cliente_com_debito, tmp_path,
                                                monkeypatch):
    from email.message import EmailMessage

    from honorarios.servicos import caixa_email
    from honorarios.ui.comum import segundo_plano
    from honorarios.ui.dialogos import corrigir_linha
    from honorarios.ui.paineis import email_cobrancas as tela

    contexto.data_referencia = date(2026, 9, 30)
    # o e-mail traz o honorário de agosto com outro nome e outra competência
    mensagem = EmailMessage()
    mensagem["From"] = "financeiro@exemplo.com.br"
    mensagem["Subject"] = "Clientes c/Honorários vencidos"
    mensagem["Message-ID"] = "<lista@exemplo.com.br>"
    mensagem.set_content("Cobranças de 30/09/2026\nNome Diferente SA  Agosto  19/08/2026  500,00\n")
    arquivo = tmp_path / "lista.eml"
    arquivo.write_bytes(bytes(mensagem))

    painel = tela.PainelEmailCobrancas(contexto)
    painel.executor = segundo_plano.imediato
    qtbot.addWidget(painel)
    painel.abrir_arquivo(str(arquivo))
    aba = painel.conferencia_aba
    assert len(painel.conferencia.nao_encontradas) == 1
    assert len(painel.conferencia.sairam) == 2               # sem par, os dois "saíram"

    fora = next(aba.arvore.topLevelItem(i) for i in range(aba.arvore.topLevelItemCount())
                if aba.arvore.topLevelItem(i).text(0).startswith("No e-mail, mas sem"))
    aba.arvore.clearSelection()
    fora.child(0).setSelected(True)
    assert aba.botao_corrigir.isEnabled()

    def escolher(dialogo):
        # o mais parecido vem primeiro: o de vencimento 19/08 (valor 500)
        assert dialogo.linhas[0].honorario.vencimento == date(2026, 8, 19)
        dialogo._associar()
        return dialogo.result()

    monkeypatch.setattr(corrigir_linha.DialogoCorrigirLinha, "exec", escolher)
    aba.botao_corrigir.click()
    conferencia = painel.conferencia
    assert conferencia.nao_encontradas == [] and len(conferencia.continuam) == 1
    [saiu] = conferencia.sairam                               # só o de setembro: dá baixa
    assert saiu.honorario.vencimento == date(2026, 9, 19)
    assert caixa_email.correcoes(painel.mensagem)            # guardado no e-mail

    # desfazer volta ao que era
    continua = next(aba.arvore.topLevelItem(i) for i in range(aba.arvore.topLevelItemCount())
                    if aba.arvore.topLevelItem(i).text(0).startswith("Continuam"))
    aba.arvore.clearSelection()
    continua.child(0).setSelected(True)
    assert aba.botao_desfazer.isVisibleTo(aba)
    aba.botao_desfazer.click()
    assert len(painel.conferencia.nao_encontradas) == 1


def test_voltar_para_o_meu_fundo(qtbot, contexto, tmp_path, monkeypatch):
    from honorarios.servicos import imagem_cobranca
    from honorarios.ui.comum import widgets
    from honorarios.ui.paineis.configuracoes import PainelConfiguracoes

    meu = tmp_path / "meu_fundo.svg"
    meu.write_text(imagem_cobranca.FUNDO_MODELO.read_text(encoding="utf-8"), encoding="utf-8")
    imagem_cobranca.definir_fundo(contexto.sessao, meu)
    contexto.salvar()
    painel = PainelConfiguracoes(contexto)
    qtbot.addWidget(painel)
    painel.recarregar()
    voltar = painel.botoes_fundo["Voltar para o meu fundo"]
    assert voltar.isHidden()                    # já está usando o seu

    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: True)
    painel.botoes_fundo["Usar o modelo do sistema"].click()
    assert imagem_cobranca.usa_modelo(contexto.sessao)
    assert not voltar.isHidden()                        # dá para voltar
    voltar.click()
    assert not imagem_cobranca.usa_modelo(contexto.sessao)
    assert imagem_cobranca.caminho_fundo(contexto.sessao) == imagem_cobranca.fundo_guardado()


def test_vencimentos_pelo_numero_da_empresa(qtbot, contexto):
    from honorarios.ui.paineis.honorarios import PainelAtrasados

    zeta = fabricas.cliente(contexto.sessao, codigo="101", nome="ZETA LTDA", documento="")
    alfa = fabricas.cliente(contexto.sessao, codigo="909", nome="ALFA LTDA", documento="")
    sozinha = fabricas.cliente(contexto.sessao, codigo="1000", nome="AAA LTDA", documento="")
    fabricas.honorario(contexto.sessao, sozinha, valor="50.00", vencimento=date(2026, 9, 1),
                       competencia=Competencia(2026, 8))
    for cliente in (zeta, alfa):
        for vencimento in (date(2026, 9, 10), date(2026, 8, 10)):
            fabricas.honorario(contexto.sessao, cliente, valor="100.00", vencimento=vencimento,
                               competencia=Competencia(2026, vencimento.month - 1))
    painel = PainelAtrasados(contexto)
    qtbot.addWidget(painel)
    # pelo número, do menor para o maior ("1000" depois de "909", não antes)
    assert painel.lista.titulos() == ["101 – ZETA LTDA", "909 – ALFA LTDA", "1000 – AAA LTDA"]
    # só quem tem mais de um honorário ganha o título de grupo
    assert [s.mostrar_titulo for s in painel.lista.secoes] == [True, True, False]
    # dentro da empresa, do vencimento mais antigo para o mais novo
    itens = painel.lista.itens_da_secao("909 – ALFA LTDA")
    assert [linha.honorario.vencimento for linha in itens] == [date(2026, 8, 10),
                                                               date(2026, 9, 10)]


def test_formas_de_envio_junto_dos_tipos(qtbot, contexto, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    from honorarios.servicos import tipos
    from honorarios.ui.comum import widgets
    from honorarios.ui.paineis.tipos_e_envio import PainelTiposEEnvio

    painel = PainelTiposEEnvio(contexto)
    qtbot.addWidget(painel)
    assert [painel.abas.tabText(i) for i in range(2)] == ["Grupos e tipos", "Formas de envio"]
    painel.abas.setCurrentWidget(painel.formas)
    formas = painel.formas
    antes = formas.modelo.rowCount()
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Correio", True)))
    formas._nova_forma()
    assert formas.modelo.rowCount() == antes + 1
    # renomear para um nome que já existe: aviso claro, nada muda
    existente = tipos.listar_formas(contexto.sessao, somente_ativas=False)[0].nome
    correio = next(f for f in tipos.listar_formas(contexto.sessao) if f.nome == "Correio")
    formas.tabela.selectRow(formas.modelo.itens.index(correio))
    avisos = []
    monkeypatch.setattr(widgets, "aviso", lambda _p, texto, *a: avisos.append(texto))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: (existente, True)))
    formas._renomear()
    assert avisos and "Já existe" in avisos[0]
    assert correio.nome == "Correio"
    # "Em uso" conta contratos e honorários com a forma
    cliente = fabricas.cliente(contexto.sessao)
    honorario = fabricas.honorario(contexto.sessao, cliente, valor="10.00",
                                   vencimento=date(2026, 9, 1))
    honorario.forma_envio_id = correio.id
    contexto.salvar()
    formas.recarregar()
    assert formas._texto_uso(correio) == "0 contrato(s) · 1 honorário(s)"


def test_configuracoes_sem_formas_de_envio(qtbot, contexto):
    from honorarios.ui.paineis.configuracoes import PainelConfiguracoes

    painel = PainelConfiguracoes(contexto)
    qtbot.addWidget(painel)
    from PySide6.QtWidgets import QTabWidget

    abas = painel.findChild(QTabWidget)
    assert "Formas de envio" not in [abas.tabText(i) for i in range(abas.count())]


def test_importacao_personalizada_da_tela(qtbot, contexto, tmp_path, monkeypatch):
    """Layout preenchido na tela, salvo, exportado como modelo e importado."""
    from openpyxl import load_workbook

    from honorarios.servicos.importacao import personalizada
    from honorarios.ui.comum import widgets
    from honorarios.ui.paineis import importacao_personalizada as tela

    painel = tela.PainelImportacaoPersonalizada(contexto)
    qtbot.addWidget(painel)
    painel.nome_layout.setText("Simples")
    for chave, letra in (("cliente_codigo", "A"), ("cliente_nome", "B"),
                         ("honorario_competencia", "C"), ("honorario_vencimento", "D"),
                         ("honorario_valor", "E")):
        painel.colunas[chave].setText(letra)
    tipo = painel.padroes["honorario_tipo"]
    tipo.setCurrentIndex(tipo.findText("Honorário mensal"))
    painel._salvar_layout()
    assert "Simples" in personalizada.listar_layouts(contexto.sessao)

    modelo = tmp_path / "modelo.xlsx"
    monkeypatch.setattr(tela.QFileDialog, "getSaveFileName", lambda *a, **k: (str(modelo), ""))
    monkeypatch.setattr(widgets, "informar", lambda *a, **k: None)
    painel._exportar_modelo()
    livro = load_workbook(modelo)
    aba = livro.worksheets[0]
    aba.append(["300", "EMPRESA DA TELA LTDA", "08/2026", date(2026, 9, 10), 450])
    livro.save(modelo)

    monkeypatch.setattr(tela.QFileDialog, "getOpenFileName", lambda *a, **k: (str(modelo), ""))
    painel._escolher()
    assert painel.previa is not None
    assert painel.previa.linhas[0].acao_cliente == "Novo cliente"

    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: True)
    painel._importar()
    from honorarios.servicos import clientes

    novo = clientes.por_codigo(contexto.sessao, "300")
    assert novo is not None and len(novo.honorarios) == 1


def test_aba_do_claude_mostra_onde_esta_gravado(qtbot, contexto, tmp_path, monkeypatch):
    from honorarios.servicos import conexao_claude
    from honorarios.ui.comum import widgets
    from honorarios.ui.paineis.configuracoes import PainelConfiguracoes

    arquivo = tmp_path / "Claude" / "claude_desktop_config.json"
    monkeypatch.setattr(conexao_claude, "arquivos_do_desktop", lambda: [arquivo])
    monkeypatch.setattr(conexao_claude, "arquivo_do_claude_code", lambda: None)
    mensagens = []
    monkeypatch.setattr(widgets, "informar", lambda _p, texto, *_a: mensagens.append(texto))

    painel = PainelConfiguracoes(contexto)
    qtbot.addWidget(painel)
    assert painel.claude_onde.text() == "em nenhum Claude ainda"
    assert painel.claude_uso.text() == "nunca usou"

    painel._gravar_no_claude()

    assert painel.claude_onde.text() == str(arquivo)
    assert str(arquivo) in mensagens[0]


def test_cobrar_se_ajusta_a_tela_pequena(qtbot, contexto, cliente_com_debito):
    """Notebook: as dicas somem, o "Venceu em" se esconde e o total fica à vista."""
    from PySide6.QtWidgets import QApplication, QLabel

    from honorarios.ui.dialogos.cobrar import DialogoCobrar

    dialogo = DialogoCobrar(contexto, cliente_com_debito, linhas_do(contexto.sessao,
                                                                    cliente_com_debito))
    qtbot.addWidget(dialogo)
    colunas = [c.titulo for c in dialogo.modelo.colunas]
    vencimento = colunas.index("Venceu em")

    dialogo.resize(1320, 900)
    dialogo.show()
    QApplication.processEvents()
    QApplication.processEvents()
    assert all(d.isVisible() for d in dialogo.findChildren(QLabel, "etapaDica"))
    assert not dialogo.tabela.isColumnHidden(vencimento)
    assert dialogo.tabela.minimumHeight() > 0

    dialogo.resize(900, 600)
    QApplication.processEvents()
    QApplication.processEvents()
    assert not any(d.isVisible() for d in dialogo.findChildren(QLabel, "etapaDica"))
    assert dialogo.tabela.isColumnHidden(vencimento)
    total = colunas.index("Total")
    assert dialogo.tabela.columnViewportPosition(total) + dialogo.tabela.columnWidth(total) \
        <= dialogo.tabela.viewport().width()
