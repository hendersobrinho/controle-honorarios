"""Fluxos principais da interface, com pytest-qt.

Não testa aparência: testa que a tela lê o serviço certo, mostra o que deveria e
grava o que o usuário confirmou.
"""

from __future__ import annotations

from datetime import date, timedelta
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
    assert [acao.texto for acao in cartao.acoes] == ["Cobrar", "Confirmar pagamento"]
    assert [acao.texto for acao in cartao.opcoes][:2] == ["Histórico", "Editar"]
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
    assert [acao.texto for acao in cartao.acoes] == ["Agradecimento"]
    assert [acao.texto for acao in cartao.opcoes] == [
        "Histórico", "Ficha da empresa", "Estornar pagamento…"]


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
    assert [acao.texto for acao in cartao.acoes] == ["Lembrete", "Confirmar pagamento"]
    assert [acao.texto for acao in cartao.opcoes][:2] == ["Histórico", "Editar"]

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


def test_clientes_de_ir_ficam_com_os_outros(qtbot, contexto, cliente_com_debito):
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
    assert set(ids()) == {cliente_com_debito.id, so_ir.id}   # sem divisão de IR
    assert painel.abas.count() == 2
    painel.abas.setCurrentIndex(1)
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
    assert painel.abas.tabText(1) == "Inativos (1)"
    painel.abas.setCurrentIndex(1)
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
    assert not hasattr(dialogo, "abas")              # tudo numa tela só, sem abas
    dialogo.codigo.setText("778")
    dialogo.nome.setText("EMPRESA COM MENSAL LTDA")
    dialogo.juros.definir(Decimal("1.00"))
    # sem honorário: pergunta; recusando, nada é gravado
    dialogo._salvar()
    assert perguntas == ["Salvar o cliente sem honorário recorrente?"]
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
    assert janela.telas.count() == 11
    assert len(janela.linhas_de_tela) == 11
    titulos = [janela.telas.widget(i).titulo for i in range(janela.telas.count())]
    assert "Tarefas" in titulos
    # as importações ficam em Configurações → Importação, fora do menu
    assert "Importar planilha" not in titulos and "Importação personalizada" not in titulos
    # Cadastros em cima, depois Cobrança (com Parcelamentos no fim)
    assert titulos[:7] == ["Clientes", "Honorários", "Tipos de faturamento", "Honorários em aberto",
                           "Tarefas", "Gerenciador de e-mail", "Parcelamentos"]
    assert "Gerenciador de e-mail" in titulos
    assert "Ranking dos atrasados" in titulos
    # as cobranças enviadas viraram a última aba de Vencimentos
    assert "Cobranças enviadas" not in titulos and "Cobranças" not in titulos
    assert "Clientes de IR" not in titulos and "Tipos e formas de envio" not in titulos
    assert "Formas de envio" not in titulos          # ficou no cadastro dos clientes
    # recorrentes e avulsos viraram abas de uma tela só
    assert "Honorários" in titulos
    assert "Honorários recorrentes" not in titulos and "Honorários avulsos" not in titulos
    assert not any("Fila" in titulo for titulo in titulos)
    # a vencer, atrasados e pagos são abas de Vencimentos, nessa ordem
    assert not {"A vencer", "Atrasados", "Pagos"} & set(titulos)
    # abre no trabalho do dia, mesmo com Cadastros em cima
    assert janela.telas.currentWidget().titulo == "Honorários em aberto"
    vencimentos = janela.telas.currentWidget()
    assert [vencimentos.abas.widget(i).titulo for i in range(4)] == [
        "A vencer", "Atrasados", "Pagos", "Cobranças"]
    for linha in janela.linhas_de_tela:
        janela.navegacao.setCurrentRow(linha)
    assert janela.telas.currentWidget().titulo == "Configurações"


def test_titulo_de_grupo_da_navegacao_nao_troca_de_tela(qtbot, contexto):
    """Os títulos CADASTROS/COBRANÇA/GESTÃO são rótulos, não telas."""
    from honorarios.ui.janela_principal import JanelaPrincipal

    janela = JanelaPrincipal(contexto)
    qtbot.addWidget(janela)
    antes = janela.telas.currentIndex()
    assert janela.navegacao.item(0).text() == "CADASTROS"
    janela.navegacao.setCurrentRow(0)
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
    assert [acao.texto for acao in cartao.acoes] == ["Registrar resposta"]
    assert [acao.texto for acao in cartao.opcoes][0] == "Ver mensagem enviada"
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
    assert "Histórico" in [acao.texto for acao in cartao.opcoes]


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


def test_cadastro_juros_livre_e_cliente_desde(qtbot, contexto, cliente_com_debito):
    """O juros se edita no próprio cadastro e vale para tudo em aberto."""
    from honorarios.servicos import clientes
    from honorarios.ui.dialogos.cliente import DialogoCliente

    existente = DialogoCliente(contexto, cliente_com_debito)
    qtbot.addWidget(existente)
    assert existente.juros.isEnabled()
    assert "tudo o que está em aberto" in existente.nota_juros.text()
    assert existente.cliente_desde.valor() is None

    existente.juros.definir(Decimal("2.00"))
    existente.cliente_desde.definir(date(2025, 8, 15))
    existente._salvar()

    assert clientes.juros_atual(cliente_com_debito) == Decimal("2.0000")
    assert cliente_com_debito.cliente_desde == date(2025, 8, 15)


def test_ficha_edita_o_cadastro(qtbot, contexto, cliente_com_debito, monkeypatch):
    from PySide6.QtWidgets import QPushButton

    from honorarios.ui.dialogos import cliente as dialogo_cliente
    from honorarios.ui.dialogos.ficha import DialogoFicha

    def editar(dialogo):
        dialogo.nome.setText("EMPRESA RENOMEADA LTDA")
        dialogo._salvar()
        return 1

    monkeypatch.setattr(dialogo_cliente.DialogoCliente, "exec", editar)
    ficha = DialogoFicha(contexto, cliente_com_debito)
    qtbot.addWidget(ficha)
    botoes = {botao.text(): botao for botao in ficha.findChildren(QPushButton)}
    assert "Alterar juros" not in botoes   # o juros fica no cadastro

    botoes["Editar cadastro"].click()

    assert cliente_com_debito.nome == "EMPRESA RENOMEADA LTDA"
    assert ficha.windowTitle() == "Ficha – EMPRESA RENOMEADA LTDA"


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


def test_cliente_so_de_ir_aparece_nos_atrasados(qtbot, contexto, cliente_com_debito,
                                                 cliente_so_ir):
    from honorarios.ui.paineis.honorarios import PainelAtrasados

    atrasados = PainelAtrasados(contexto)
    qtbot.addWidget(atrasados)
    ids = {linha.cliente.id for linha in atrasados.lista.itens}
    assert {cliente_so_ir.id, cliente_com_debito.id} <= ids


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


def test_cartao_em_aberto_tem_editar_nas_opcoes(qtbot, contexto, cliente_com_debito,
                                               monkeypatch):
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
    # à mostra só o que se faz a toda hora; o resto vai no "Opções" do cartão
    assert [acao.texto for acao in painel._acoes_do_cartao(linha)] == [
        "Cobrar", "Confirmar pagamento"]
    opcoes = {acao.texto: acao for acao in painel._opcoes_do_cartao(linha)}
    assert list(opcoes) == [
        "Histórico", "Editar", "Anotar retorno do cliente…",
        "Registrar cobrança feita por fora…", "Ficha da empresa", "Parcelar…",
        "Cancelar honorário…",
    ]
    opcoes["Editar"].funcao(linha)
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
    assert "Parcelar selecionados" in acoes and "Exportar lista" in acoes

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
    assert vencimentos.titulo == "Honorários em aberto"
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
    primeira = next(linha for linha, indice in janela.linhas_de_tela.items()
                    if janela.telas.widget(indice).titulo == "Honorários em aberto")
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


def test_formas_de_envio_no_cadastro_dos_clientes(qtbot, contexto, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    from honorarios.servicos import tipos
    from honorarios.ui.comum import widgets
    from honorarios.ui.paineis.formas_envio import DialogoFormasEnvio
    from honorarios.ui.paineis.tipos_e_envio import PainelTiposEEnvio

    faturamento = PainelTiposEEnvio(contexto)
    qtbot.addWidget(faturamento)
    assert faturamento.titulo == "Tipos de faturamento"
    assert not hasattr(faturamento, "formas")        # as formas foram para Clientes

    dialogo = DialogoFormasEnvio(contexto)
    qtbot.addWidget(dialogo)
    formas = dialogo.painel
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


# -------------------------------------------------------------- atualização
def _lancamento(versao):
    from honorarios.servicos import atualizacao

    return atualizacao.Lancamento(
        versao=versao, notas="- tela Cobrar nova", publicado_em=None,
        instalador_url="http://x/i.exe", instalador_nome=f"I_{versao}.exe",
        tamanho=50 * 1024 * 1024, sha256="", pagina="")


def test_atualizacao_ja_em_dia(qtbot, contexto, monkeypatch):
    from honorarios import __version__
    from honorarios.servicos import atualizacao
    from honorarios.ui.comum import segundo_plano
    from honorarios.ui.paineis.configuracoes import PainelConfiguracoes

    monkeypatch.setattr(atualizacao, "ultima", lambda: _lancamento(__version__))
    painel = PainelConfiguracoes(contexto, executor=segundo_plano.imediato)
    qtbot.addWidget(painel)
    painel.mostrar_atualizacoes()
    assert painel.abas.currentWidget() is painel.aba_atualizacoes
    assert painel.versao_instalada.text() == __version__

    painel.verificar_e_atualizar()

    assert "mais recente" in painel.situacao_atualizacao.text()
    assert painel.botao_atualizar.isEnabled()


def test_atualizacao_baixa_instala_e_fecha(qtbot, contexto, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication

    from honorarios.servicos import atualizacao
    from honorarios.ui.comum import segundo_plano, widgets
    from honorarios.ui.paineis.configuracoes import PainelConfiguracoes

    instalados, fechou = [], []
    monkeypatch.setattr(atualizacao, "ultima", lambda: _lancamento("99.0.0"))
    monkeypatch.setattr(atualizacao, "pode_instalar", lambda: True)
    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: True)

    def baixar(lancamento, progresso=None, **_):
        progresso(lancamento.tamanho, lancamento.tamanho)
        return tmp_path / lancamento.instalador_nome

    monkeypatch.setattr(atualizacao, "baixar", baixar)
    monkeypatch.setattr(atualizacao, "instalar", lambda caminho, log=None:
                        instalados.append(caminho))
    monkeypatch.setattr(QApplication, "quit", lambda *_: fechou.append(True))

    painel = PainelConfiguracoes(contexto, executor=segundo_plano.imediato)
    qtbot.addWidget(painel)
    painel.verificar_e_atualizar()

    assert painel.versao_publicada.text() == "99.0.0"
    assert painel.notas_atualizacao.toPlainText() == "- tela Cobrar nova"
    assert "Instalando a versão 99.0.0" in painel.situacao_atualizacao.text()
    assert fechou == [True]
    QApplication.instance().aboutToQuit.emit()   # o instalador roda ao fechar
    QApplication.instance().aboutToQuit.disconnect(painel._ao_sair)
    assert instalados == [tmp_path / "I_99.0.0.exe"]


def test_atualizacao_recusada_ou_sem_internet(qtbot, contexto, monkeypatch):
    from honorarios.servicos import atualizacao
    from honorarios.servicos.erros import ErroDeNegocio
    from honorarios.ui.comum import segundo_plano, widgets
    from honorarios.ui.paineis.configuracoes import PainelConfiguracoes

    baixou = []
    monkeypatch.setattr(atualizacao, "ultima", lambda: _lancamento("99.0.0"))
    monkeypatch.setattr(atualizacao, "pode_instalar", lambda: True)
    monkeypatch.setattr(atualizacao, "baixar", lambda *a, **k: baixou.append(1))
    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: False)
    painel = PainelConfiguracoes(contexto, executor=segundo_plano.imediato)
    qtbot.addWidget(painel)

    painel.verificar_e_atualizar()
    assert "fica para depois" in painel.situacao_atualizacao.text() and not baixou

    def sem_rede():
        raise ErroDeNegocio("Não consegui falar com o GitHub.")

    monkeypatch.setattr(atualizacao, "ultima", sem_rede)
    painel.verificar_e_atualizar()
    assert "Não consegui falar com o GitHub" in painel.situacao_atualizacao.text()
    assert painel.botao_atualizar.isEnabled()


def test_opcao_de_avisar_ao_abrir_fica_gravada(qtbot, contexto):
    from honorarios.servicos import atualizacao, configuracoes
    from honorarios.ui.paineis.configuracoes import PainelConfiguracoes

    painel = PainelConfiguracoes(contexto)
    qtbot.addWidget(painel)
    assert painel.atualizar_ao_abrir.isChecked()
    painel.atualizar_ao_abrir.setChecked(False)
    assert not configuracoes.obter_bool(contexto.sessao, atualizacao.CHAVE_AO_ABRIR, True)


# ----------------------------------------------------------------- tarefas
def test_tela_de_tarefas_da_baixa_e_desfaz(qtbot, contexto, cliente_com_debito):
    from honorarios.dominio.enums import Periodicidade
    from honorarios.ui.paineis.tarefas import PainelTarefas

    cliente_com_debito.cliente_desde = date(2026, 5, 20)   # trimestres 05–07, 08–10…
    fabricas.contrato(contexto.sessao, cliente_com_debito, valor="900.00",
                      periodicidade=Periodicidade.TRIMESTRAL)
    sem_data = fabricas.cliente(contexto.sessao, codigo="901", nome="SEM DATA LTDA",
                                documento="")
    fabricas.contrato(contexto.sessao, sem_data, periodicidade=Periodicidade.TRIMESTRAL)
    contexto.salvar()

    painel = PainelTarefas(contexto)   # referência da tela: 29/09/2026
    qtbot.addWidget(painel)
    assert [t.periodo for t in painel.lista.itens_da_secao("Para fazer")] == [
        "05/2026 a 07/2026"]
    assert [t.prazo for t in painel.lista.itens_da_secao("Próximos trimestres")] == [
        date(2026, 11, 1)]
    assert [c.nome for c in painel.lista.itens_da_secao("Sem data de entrada")] == [
        "SEM DATA LTDA"]
    assert "1</b> para fazer" in painel.resumo.text()

    [tarefa] = painel.lista.itens_da_secao("Para fazer")
    painel._dar_baixa(tarefa)
    assert painel.lista.itens_da_secao("Para fazer") == []
    [feita] = painel.lista.itens_da_secao("Feitas")
    assert "Baixa" in painel.aviso.text()

    painel._desfazer(feita)
    assert len(painel.lista.itens_da_secao("Para fazer")) == 1


def test_tarefas_baixa_em_todas(qtbot, contexto, cliente_com_debito, monkeypatch):
    from honorarios.dominio.enums import Periodicidade
    from honorarios.ui.comum import widgets
    from honorarios.ui.paineis.tarefas import PainelTarefas

    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: True)
    cliente_com_debito.cliente_desde = date(2025, 11, 1)   # 11–01, 02–04, 05–07
    fabricas.contrato(contexto.sessao, cliente_com_debito,
                      periodicidade=Periodicidade.TRIMESTRAL)
    contexto.salvar()
    painel = PainelTarefas(contexto)
    qtbot.addWidget(painel)
    assert len(painel.lista.itens_da_secao("Para fazer")) == 3

    painel._baixa_em_todas()
    assert painel.lista.itens_da_secao("Para fazer") == []
    assert len(painel.lista.itens_da_secao("Feitas")) == 3
    assert not painel.botao_todas.isEnabled()


# ------------------------------------------------- campos de data e de valor
def test_campo_de_data_aceita_digitacao_livre(qtbot):
    from PySide6.QtCore import Qt

    from honorarios.ui.comum.campos import CampoData

    campo = CampoData(date(2026, 1, 1))
    qtbot.addWidget(campo)
    mudou = []
    campo.dateChanged.connect(lambda dia: mudou.append(dia))

    campo.clear()
    qtbot.keyClicks(campo, "30102026")            # sem barras: elas entram sozinhas
    assert campo.text() == "30/10/2026"
    assert campo.valor() == date(2026, 10, 30) and mudou   # já vale, sem sair do campo

    campo.selectAll()
    qtbot.keyClicks(campo, "31/02/2026")
    qtbot.keyClick(campo, Qt.Key.Key_Return)
    assert campo.property("invalido") and "Data inválida" in campo.toolTip()
    assert campo.valor() == date(2026, 10, 30)   # o valor bom continua

    campo.selectAll()
    qtbot.keyClicks(campo, "5/11/26")
    qtbot.keyClick(campo, Qt.Key.Key_Return)
    assert campo.text() == "05/11/2026" and not campo.property("invalido")

    campo.clear()                                 # obrigatória: apagar volta a que estava
    qtbot.keyClick(campo, Qt.Key.Key_Return)
    assert campo.valor() == date(2026, 11, 5) and campo.text() == "05/11/2026"


def test_campo_de_data_opcional_pode_ficar_vazio_e_respeita_limite(qtbot):
    from PySide6.QtCore import QDate, Qt

    from honorarios.ui.comum.campos import CampoData, CampoDataOpcional

    opcional = CampoDataOpcional(date(2026, 3, 1))
    qtbot.addWidget(opcional)
    opcional.clear()
    qtbot.keyClick(opcional, Qt.Key.Key_Return)
    assert opcional.valor() is None and opcional.text() == ""

    limitado = CampoData(date(2026, 1, 10))
    qtbot.addWidget(limitado)
    limitado.setMaximumDate(QDate(2026, 1, 31))
    limitado.selectAll()
    qtbot.keyClicks(limitado, "15/02/2026")
    qtbot.keyClick(limitado, Qt.Key.Key_Return)
    assert "não pode passar de 31/01/2026" in limitado.toolTip()
    assert limitado.valor() == date(2026, 1, 10)


def test_campo_de_valor_aceita_digitacao_livre(qtbot):
    from PySide6.QtCore import Qt

    from honorarios.ui.comum.campos import CampoMoeda, CampoTaxa

    campo = CampoMoeda(Decimal("10"))
    qtbot.addWidget(campo)
    assert campo.text() == "R$ 10,00"
    valores = []
    campo.valueChanged.connect(valores.append)

    campo.selectAll()
    qtbot.keyClicks(campo, "1.234,5")
    assert campo.valor() == Decimal("1234.50") and valores[-1] == 1234.5   # já vale
    qtbot.keyClick(campo, Qt.Key.Key_Return)
    assert campo.text() == "R$ 1.234,50"

    campo.selectAll()
    qtbot.keyClicks(campo, "abc")
    qtbot.keyClick(campo, Qt.Key.Key_Return)
    assert campo.property("invalido") and campo.valor() == Decimal("1234.50")

    campo.selectAll()
    qtbot.keyClicks(campo, "-5")
    assert "negativo" in campo.toolTip()

    campo.clear()                                 # apagar tudo é zero
    qtbot.keyClick(campo, Qt.Key.Key_Return)
    assert campo.valor() == Decimal("0.00") and not campo.property("invalido")

    taxa = CampoTaxa(Decimal("1.01"))
    qtbot.addWidget(taxa)
    assert taxa.text() == "R$ 1,01 / dia"
    taxa.selectAll()
    qtbot.keyClicks(taxa, "2.5")
    qtbot.keyClick(taxa, Qt.Key.Key_Return)
    assert taxa.valor() == Decimal("2.50") and taxa.text() == "R$ 2,50 / dia"


# ------------------------------------------------- cartão: opções e cobrado hoje


def test_cobrado_hoje_fica_azul_e_volta_ao_vermelho_no_dia_seguinte(
    qtbot, contexto, cliente_com_debito
):
    from datetime import timedelta

    from honorarios.dominio.valores import hoje
    from honorarios.ui.comum import cores, tema
    from honorarios.ui.paineis.honorarios import PainelAtrasados

    azul = tema.cor("cobrado", cores.tema_atual())
    vermelho = tema.cor("atrasado", cores.tema_atual())

    cobrar_pelo_sistema(contexto, cliente_com_debito, hoje() - timedelta(days=1))
    painel = PainelAtrasados(contexto)
    qtbot.addWidget(painel)
    ontem = painel._cartao(painel.lista.itens[0])
    assert ontem.cor == vermelho                        # cobrado ontem: de volta ao atraso
    assert "Cobrado hoje" not in ontem.situacao

    cobrar_pelo_sistema(contexto, cliente_com_debito)   # agora
    painel.recarregar()
    dados = painel._cartao(painel.lista.itens[0])
    assert dados.cor == azul
    assert dados.situacao.startswith("✓ Cobrado hoje")
    assert "dia(s) de atraso" in dados.situacao         # o atraso continua dito
    assert dados.datas[0].cor == vermelho               # e o vencimento segue vermelho
    assert dados.datas[1].valor == "hoje ✓"
    assert "2 já cobrado(s) hoje" in painel.resumo.text()


def test_opcoes_do_cartao_viram_um_menu(qtbot, contexto, cliente_com_debito, monkeypatch):
    from PySide6.QtWidgets import QPushButton, QToolButton

    from honorarios.ui.comum.cartoes import CartaoRegistro
    from honorarios.ui.dialogos import retorno
    from honorarios.ui.paineis.honorarios import PainelAtrasados

    abertos = []
    monkeypatch.setattr(retorno.DialogoRetorno, "exec",
                        lambda self: abertos.append(self.honorarios) or 0)
    painel = PainelAtrasados(contexto)
    qtbot.addWidget(painel)
    linha = painel.lista.itens[0]
    cartao = CartaoRegistro(painel._cartao(linha))
    qtbot.addWidget(cartao)
    assert [b.text() for b in cartao.findChildren(QPushButton)] == [
        "Cobrar", "Confirmar pagamento"]
    opcoes = cartao.findChild(QToolButton, "cartaoOpcoes")
    textos = [a.text() for a in opcoes.menu().actions() if not a.isSeparator()]
    assert textos[:3] == ["Histórico", "Editar", "Anotar retorno do cliente…"]
    # agrupado: consultar | anotar | ficha | renegociar e cancelar
    assert sum(a.isSeparator() for a in opcoes.menu().actions()) == 3
    next(a for a in opcoes.menu().actions()
         if a.text() == "Anotar retorno do cliente…").trigger()
    assert abertos == [[linha.honorario]]


def test_registrar_cobranca_feita_por_fora_pelo_cartao(
    qtbot, contexto, cliente_com_debito, monkeypatch
):
    from PySide6.QtWidgets import QInputDialog

    from honorarios.ui.comum import cores
    from honorarios.ui.paineis.honorarios import PainelAtrasados

    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("ligou para o financeiro", True)))
    painel = PainelAtrasados(contexto)
    qtbot.addWidget(painel)
    linha = painel.lista.itens[0]
    painel._registrar_cobranca_um(linha)
    marcadas = [item for item in painel.lista.itens if cores.cobrado_hoje(item)]
    assert [item.honorario.id for item in marcadas] == [linha.honorario.id]


def test_recarregar_nao_tira_a_lista_do_lugar(qtbot):
    from honorarios.ui.comum.cartoes import DadosCartao, PainelDeCartoes, SecaoCartoes

    lista = PainelDeCartoes(limite_secao=200, orcamento=200)
    qtbot.addWidget(lista)
    lista.resize(500, 300)
    lista.show()
    secoes = [SecaoCartoes("Tudo", itens=[DadosCartao(titulo=f"Empresa {n}")
                                         for n in range(60)])]
    lista.definir_secoes(secoes)
    qtbot.wait(20)
    barra = lista.verticalScrollBar()
    meio = barra.maximum() // 2
    assert meio > 0
    barra.setValue(meio)
    lista.definir_secoes(secoes)                        # como depois de salvar
    qtbot.wait(20)
    assert barra.value() == meio


def test_cobrancas_sao_a_ultima_aba_de_vencimentos(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.paineis.vencimentos import PainelVencimentos

    cobrar_pelo_sistema(contexto, cliente_com_debito, date(2026, 9, 25))
    painel = PainelVencimentos(contexto)
    qtbot.addWidget(painel)
    assert painel.abas.tabText(3) == "Cobranças (1)"   # uma esperando resposta
    cobrancas = painel.aba("Cobranças")
    assert cobrancas is painel.cobrancas
    dados = cobrancas._cartao(cobrancas.linhas[0])
    assert [acao.texto for acao in dados.acoes] == ["Registrar resposta"]
    assert "Cobrar de novo" in [acao.texto for acao in dados.opcoes]


def test_limpar_a_busca_traz_os_cartoes_visiveis(qtbot, contexto, cliente_com_debito):
    """Buscar uma empresa e apagar a busca deixava os cartões novos escondidos e
    espremidos: com a lista já na tela, eles precisam ser mostrados na hora."""
    from honorarios.ui.paineis.honorarios import PainelAtrasados

    outro = fabricas.cliente(contexto.sessao, nome="OUTRA EMPRESA LTDA", codigo="901",
                             documento="")
    fabricas.honorario(contexto.sessao, outro, valor="300.00", vencimento=date(2026, 9, 1))
    contexto.salvar()
    painel = PainelAtrasados(contexto)
    qtbot.addWidget(painel)
    painel.resize(900, 600)
    painel.show()
    painel.busca.setText("OUTRA")
    assert len(painel.lista.itens) == 1
    painel.busca.setText("")
    qtbot.wait(20)
    cartoes = list(painel.lista._cartoes.values())
    assert len(cartoes) == 3
    assert all(cartao.isVisible() for cartao in cartoes)
    assert all(cartao.height() == cartao.sizeHint().height() for cartao in cartoes)


def test_busca_mostra_a_roda_de_carregando(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.paineis.honorarios import PainelAtrasados

    painel = PainelAtrasados(contexto)
    qtbot.addWidget(painel)
    painel.show()
    roda = painel.lista._carregando
    vezes = []
    original = roda.comecar
    roda.comecar = lambda: (vezes.append(1), original())
    painel.busca.setText("EXEMPLO")
    assert vezes == [1]                                # a busca mostrou a roda
    qtbot.waitUntil(lambda: not painel.lista.carregando, timeout=3000)
    painel.recarregar()                                # depois de salvar: sem a roda
    assert vezes == [1] and not painel.lista.carregando


# ------------------------------------------------------ editar: juros à mão


def _honorario_de_1000(contexto, cliente):
    return next(linha.honorario for linha in linhas_do(contexto.sessao, cliente)
                if linha.honorario.valor_original == Decimal("1000.00"))


def _juros_de_hoje():
    """O de 1.000,00 vence em 19/09/2026, a R$ 1,00 por dia: o Editar usa o hoje real."""
    from honorarios.dominio.valores import hoje

    return Decimal((hoje() - date(2026, 9, 19)).days).quantize(Decimal("0.01"))


def test_editar_mostra_o_juros_e_aceita_acerto_a_mao(qtbot, contexto, cliente_com_debito):
    from honorarios.dominio.valores import hoje
    from honorarios.servicos import calculo
    from honorarios.ui.dialogos.honorario import DialogoHonorario

    honorario = _honorario_de_1000(contexto, cliente_com_debito)
    dialogo = DialogoHonorario(contexto, honorario=honorario)
    qtbot.addWidget(dialogo)
    dialogo.show()
    calculado = _juros_de_hoje()
    assert dialogo.juros.valor() == calculado
    assert dialogo.total_hoje.text() == formatar_moeda(Decimal("1000.00") + calculado)
    assert not dialogo.botao_calculado.isVisible()

    dialogo.juros.setFocus()
    dialogo.juros.selectAll()
    qtbot.keyClicks(dialogo.juros, "15,00")
    assert dialogo.total_hoje.text() == "R$ 1.015,00"
    assert dialogo.botao_calculado.isVisible()
    assert "Acertado à mão" in dialogo.juros_conta.text()
    dialogo._salvar()
    atual = calculo.atualizar(honorario, hoje())
    assert (atual.juros, atual.juros_calculado) == (Decimal("15.00"), calculado)
    assert honorario.juros_ajustado_em == hoje()   # o dia de verdade, não o simulado


def test_editar_sem_mexer_no_juros_nao_cria_acerto(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.dialogos.honorario import DialogoHonorario

    honorario = _honorario_de_1000(contexto, cliente_com_debito)
    dialogo = DialogoHonorario(contexto, honorario=honorario)
    qtbot.addWidget(dialogo)
    dialogo.valor.definir(Decimal("2000.00"))      # mudou o valor: o juros acompanha
    assert dialogo.total_hoje.text() == formatar_moeda(Decimal("2000.00") + _juros_de_hoje())
    dialogo._salvar()
    assert honorario.juros_ajustado is None


def test_editar_volta_ao_calculado(qtbot, contexto, cliente_com_debito):
    from honorarios.dominio.valores import hoje
    from honorarios.servicos import calculo
    from honorarios.servicos import honorarios as servico
    from honorarios.ui.dialogos.honorario import DialogoHonorario

    honorario = _honorario_de_1000(contexto, cliente_com_debito)
    servico.ajustar_juros(contexto.sessao, honorario, Decimal("3.00"), hoje())
    contexto.salvar()
    dialogo = DialogoHonorario(contexto, honorario=honorario)
    qtbot.addWidget(dialogo)
    dialogo.show()
    assert dialogo.juros.valor() == Decimal("3.00")
    assert dialogo.botao_calculado.isVisible()
    dialogo.botao_calculado.click()
    assert dialogo.juros.valor() == _juros_de_hoje()
    dialogo._salvar()
    assert not calculo.atualizar(honorario, hoje()).juros_manual


def test_editar_nao_abre_janelinhas(qtbot, contexto, cliente_com_debito):
    """Os campos do juros nascem sem pai: mostrá-los antes do layout abria janelas."""
    from PySide6.QtWidgets import QApplication

    from honorarios.ui.dialogos.honorario import DialogoHonorario

    antes = set(QApplication.topLevelWidgets())
    dialogo = DialogoHonorario(contexto, honorario=_honorario_de_1000(contexto,
                                                                      cliente_com_debito))
    qtbot.addWidget(dialogo)
    novas = [w for w in set(QApplication.topLevelWidgets()) - antes
             if w is not dialogo and w.isVisible()]
    assert novas == []


def test_cobrar_volta_ao_juros_acertado_no_editar(qtbot, contexto, cliente_com_debito):
    """No Cobrar, "Voltar ao calculado" desfaz só o digitado ali: o acerto do Editar
    é o juros do honorário."""
    from honorarios.servicos import honorarios as servico
    from honorarios.ui.dialogos.cobrar import DialogoCobrar

    honorario = _honorario_de_1000(contexto, cliente_com_debito)
    servico.ajustar_juros(contexto.sessao, honorario, Decimal("50.00"), REFERENCIA)
    contexto.salvar()
    linhas = linhas_do(contexto.sessao, cliente_com_debito)
    dialogo = DialogoCobrar(contexto, cliente_com_debito, linhas)
    qtbot.addWidget(dialogo)
    linha = next(x for x in dialogo.linhas if x.honorario.id == honorario.id)
    assert linha.atualizacao.juros == Decimal("50.00")
    dialogo._escolher_para_editar(dialogo.linhas.index(linha))
    assert not dialogo.botao_calculado.isEnabled()      # nada digitado aqui
    dialogo.definir_juros(linha, Decimal("20.00"))
    assert linha.atualizacao.juros == Decimal("20.00")
    dialogo._editada = linha
    dialogo._voltar_ao_calculado()
    assert linha.atualizacao.juros == Decimal("50.00")   # de volta ao do honorário


def test_busca_volta_a_lista_para_o_comeco(qtbot):
    from honorarios.ui.comum.cartoes import DadosCartao, PainelDeCartoes, SecaoCartoes

    lista = PainelDeCartoes(limite_secao=200, orcamento=200)
    qtbot.addWidget(lista)
    lista.resize(500, 300)
    lista.show()
    secoes = [SecaoCartoes("Tudo", itens=[DadosCartao(titulo=f"Empresa {n}")
                                         for n in range(60)])]
    lista.definir_secoes(secoes)
    qtbot.wait(20)
    lista.verticalScrollBar().setValue(lista.verticalScrollBar().maximum())
    with lista.carregando_durante(minimo_ms=0):        # como numa busca
        lista.definir_secoes(secoes)
    qtbot.wait(20)
    assert lista.verticalScrollBar().value() == 0
    assert not lista.carregando


def test_cobrar_abre_na_imagem_e_manda_pelo_whatsapp(qtbot, contexto, cliente_com_debito,
                                                     monkeypatch):
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QPushButton

    from honorarios.ui.comum import widgets
    from honorarios.ui.dialogos.cobrar import ABA_IMAGEM, DialogoCobrar

    abertos = []
    monkeypatch.setattr(widgets, "abrir_url", lambda url: abertos.append(url) or True)
    dialogo = DialogoCobrar(contexto, cliente_com_debito, linhas_do(contexto.sessao,
                                                                     cliente_com_debito))
    qtbot.addWidget(dialogo)
    assert dialogo.abas.currentIndex() == ABA_IMAGEM          # a imagem é a principal
    assert dialogo.abas.tabText(ABA_IMAGEM) == "Imagem"
    botao = next(b for b in dialogo.abas.widget(ABA_IMAGEM).findChildren(QPushButton)
                 if b.text() == "Copiar e abrir no WhatsApp")
    botao.click()
    assert not QGuiApplication.clipboard().image().isNull()   # a imagem, para o Ctrl+V
    assert len(abertos) == 1 and "27999990000" in abertos[0]   # a conversa do contato
    assert "WhatsApp aberto e imagem copiada" in dialogo.aviso.text()


# ------------------------------------------------------------- parcelamentos


def test_novo_parcelamento_escolhe_o_cliente_e_os_honorarios(
    qtbot, contexto, cliente_com_debito, monkeypatch
):
    from honorarios.ui.comum import widgets
    from honorarios.ui.dialogos.renegociacao import DialogoRenegociacao
    from honorarios.ui.paineis.honorarios import PainelAtrasados
    from honorarios.ui.paineis.parcelamentos import PainelParcelamentos

    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: True)
    dialogo = DialogoRenegociacao(contexto)
    qtbot.addWidget(dialogo)
    assert not dialogo.botao_confirmar.isEnabled()      # sem cliente, nada a parcelar
    dialogo.campo_cliente.mudou.emit(cliente_com_debito)
    assert len(dialogo.modelo.itens) == 2 and dialogo.escolhidos() == []
    dialogo.modelo.marcar_todos()
    assert dialogo.valor_acordado.valor() == Decimal("1551.00")   # com o juros de hoje
    dialogo.parcelas.setValue(3)
    assert [p.valor for p in dialogo.modelo_parcelas.itens] == [Decimal("517.00")] * 3
    dialogo.primeiro_vencimento.definir(date(2026, 10, 20))
    dialogo._confirmar()
    assert dialogo.acordo is not None

    # as parcelas saem de Vencimentos e aparecem em Parcelamentos
    atrasados = PainelAtrasados(contexto)
    qtbot.addWidget(atrasados)
    assert atrasados.lista.itens == []
    painel = PainelParcelamentos(contexto)
    qtbot.addWidget(painel)
    [parcelamento] = painel.lista.itens
    assert len(parcelamento.parcelas) == 3 and not parcelamento.atrasadas
    cartao = painel._cartao(parcelamento)
    assert cartao.situacao == "0 de 3 pagas"
    assert cartao.valor == "R$ 1.551,00"
    assert [a.texto for a in cartao.acoes] == ["Confirmar pagamento"]
    assert "Cancelar parcelamento…" in [a.texto for a in cartao.opcoes]


def test_parcelar_pelo_cartao_ja_vem_com_o_honorario_marcado(
    qtbot, contexto, cliente_com_debito
):
    from honorarios.ui.dialogos.renegociacao import DialogoRenegociacao

    linha = linhas_do(contexto.sessao, cliente_com_debito)[0]
    dialogo = DialogoRenegociacao(contexto, cliente_com_debito, [linha])
    qtbot.addWidget(dialogo)
    assert [x.honorario.id for x in dialogo.escolhidos()] == [linha.honorario.id]
    assert dialogo.valor_acordado.valor() == linha.atualizacao.total
    dialogo.valor_acordado.definir(Decimal("400.00"))     # à mão: não volta sozinho
    dialogo.parcelas.setValue(2)
    assert dialogo.valor_acordado.valor() == Decimal("400.00")
    assert [p.valor for p in dialogo.modelo_parcelas.itens] == [Decimal("200.00")] * 2


def test_parcela_atrasada_pede_cobranca_e_mostra_as_parcelas(
    qtbot, contexto, cliente_com_debito
):
    from sqlalchemy import select

    from honorarios.infra.modelos import TipoHonorario
    from honorarios.servicos import parcelamentos
    from honorarios.ui.dialogos.parcelas import DialogoParcelas
    from honorarios.ui.paineis.parcelamentos import PainelParcelamentos

    tipo = contexto.sessao.scalar(
        select(TipoHonorario).where(TipoHonorario.nome == "Parcela de acordo"))
    parcelamentos.criar(
        contexto.sessao, cliente_com_debito, linhas_do(contexto.sessao, cliente_com_debito),
        Decimal("1200.00"), 4, date(2026, 9, 9), tipo.id)
    contexto.salvar()
    painel = PainelParcelamentos(contexto)
    qtbot.addWidget(painel)
    assert painel.lista.titulos()[0] == "Com parcela atrasada"
    [parcelamento] = painel.lista.itens
    cartao = painel._cartao(parcelamento)
    assert cartao.situacao == "Parcela 1/4 atrasada há 20 dia(s)"
    assert [a.texto for a in cartao.acoes] == ["Cobrar", "Confirmar pagamento"]

    dialogo = DialogoParcelas(contexto, parcelamento)
    qtbot.addWidget(dialogo)
    assert dialogo.atual().numero == 1                  # a próxima em aberto já escolhida
    assert dialogo.botao_pagar.isEnabled() and not dialogo.botao_estornar.isEnabled()


def test_parcelar_com_juros_acertado_a_mao_e_sem_juros(
    qtbot, contexto, cliente_com_debito, monkeypatch
):
    from honorarios.ui.comum import widgets
    from honorarios.ui.dialogos import juros_manual
    from honorarios.ui.dialogos.renegociacao import DialogoRenegociacao

    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: True)
    linhas = linhas_do(contexto.sessao, cliente_com_debito)
    dialogo = DialogoRenegociacao(contexto, cliente_com_debito, linhas)
    qtbot.addWidget(dialogo)
    assert dialogo.valor_acordado.valor() == Decimal("1551.00")
    assert dialogo.juros_resumo.text() == "Juros incluídos: R$ 51,00"

    # tirar o juros dos marcados: fica só o valor
    dialogo._tirar_juros()
    assert dialogo.valor_acordado.valor() == Decimal("1500.00")
    assert "(calculado R$ 51,00)" in dialogo.juros_resumo.text()
    assert dialogo.escolhidos() == dialogo.modelo.itens        # as marcações ficam

    # acertar um só à mão, pela janela do juros
    def acertar(self):
        self.juros = Decimal("5.00")
        return 1
    monkeypatch.setattr(juros_manual.DialogoJurosManual, "exec", acertar)
    dialogo.tabela.setCurrentIndex(dialogo.modelo.index(0, 0))
    dialogo._alterar_juros()
    assert dialogo.valor_acordado.valor() == Decimal("1505.00")

    dialogo._confirmar()
    assert dialogo.acordo.juros_incluidos == Decimal("5.00")
    assert dialogo.acordo.valor_acordado == Decimal("1505.00")

    dialogo2 = DialogoRenegociacao(contexto, cliente_com_debito, [])
    qtbot.addWidget(dialogo2)
    assert dialogo2.modelo.itens == []       # já parcelados: nada em aberto


def test_janela_do_juros_sem_juros_e_calculado(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.dialogos.juros_manual import DialogoJurosManual

    linha = linhas_do(contexto.sessao, cliente_com_debito)[0]
    dialogo = DialogoJurosManual("Teste", linha.honorario, linha.atualizacao)
    qtbot.addWidget(dialogo)
    assert not dialogo.botao_calculado.isEnabled()      # nada acertado ainda
    dialogo.campo.definir(linha.atualizacao.juros)      # o próprio calculado
    dialogo._aplicar()
    assert dialogo.juros is None
    dialogo.campo.definir(Decimal("7.00"))
    dialogo._aplicar()
    assert dialogo.juros == Decimal("7.00")
    dialogo._sem_juros()
    assert dialogo.juros == Decimal("0.00")


def test_tirar_o_juros_das_parcelas_atrasadas(qtbot, contexto, cliente_com_debito,
                                              monkeypatch):
    from sqlalchemy import select

    from honorarios.dominio.valores import hoje
    from honorarios.infra.modelos import TipoHonorario
    from honorarios.servicos import calculo, parcelamentos
    from honorarios.ui.comum import widgets
    from honorarios.ui.dialogos.parcelas import DialogoParcelas
    from honorarios.ui.paineis.parcelamentos import PainelParcelamentos

    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: True)
    tipo = contexto.sessao.scalar(
        select(TipoHonorario).where(TipoHonorario.nome == "Parcela de acordo"))
    parcelamentos.criar(
        contexto.sessao, cliente_com_debito, linhas_do(contexto.sessao, cliente_com_debito),
        Decimal("1200.00"), 4, date(2026, 9, 9), tipo.id)
    contexto.salvar()
    painel = PainelParcelamentos(contexto)
    qtbot.addWidget(painel)
    [parcelamento] = painel.lista.itens
    cartao = painel._cartao(parcelamento)
    # 20 dias da 1ª parcela, com metade do juros ao dia (2 honorários em 4 parcelas)
    assert ("Juros", "R$ 10,00") in cartao.detalhes
    opcoes = {a.texto: a for a in cartao.opcoes}
    assert "Tirar o juros das atrasadas…" in opcoes

    dialogo = DialogoParcelas(contexto, parcelamento)
    qtbot.addWidget(dialogo)
    assert dialogo.botao_juros.isEnabled() and dialogo.botao_sem_juros.isEnabled()
    dialogo._tirar_juros()
    primeira = dialogo.parcelamento.parcelas[0]
    assert primeira.honorario.juros_ajustado == Decimal("0.00")
    # o acerto vale do dia de hoje (o de verdade) em diante: zero hoje
    hoje_ = calculo.atualizar(primeira.honorario, hoje())
    assert hoje_.juros_manual and hoje_.juros == Decimal("0.00")


def test_menu_tem_o_subtopico_parcelamento(qtbot, contexto):
    from honorarios.ui.janela_principal import ContadorDoMenu, JanelaPrincipal

    janela = JanelaPrincipal(contexto)
    qtbot.addWidget(janela)
    textos = [janela.navegacao.item(i).text() for i in range(janela.navegacao.count())]
    sub = textos.index("Parcelamento")
    # dentro do 2º grupo (Cobrança), com a cor dele
    assert janela.navegacao.item(sub).data(ContadorDoMenu.PAPEL_SUBTOPICO) == 1
    assert textos[sub + 1] == "Parcelamentos"
    assert sub not in janela.linhas_de_tela                 # não é tela: não se escolhe


def test_importacoes_ficam_em_configuracoes(qtbot, contexto):
    from honorarios.ui.paineis.configuracoes import PainelConfiguracoes

    painel = PainelConfiguracoes(contexto, executor=lambda *a, **k: None)
    qtbot.addWidget(painel)
    nomes = [painel.abas.tabText(i) for i in range(painel.abas.count())]
    assert "Importação" in nomes
    abas = painel.abas_importacao
    assert [abas.tabText(i) for i in range(abas.count())] == [
        "Planilha de controle", "Personalizada"]


def test_botao_de_versao_nova_so_aparece_quando_ha(qtbot, contexto, monkeypatch):
    from types import SimpleNamespace

    from honorarios.servicos import atualizacao
    from honorarios.ui.comum import segundo_plano
    from honorarios.ui.janela_principal import JanelaPrincipal

    janela = JanelaPrincipal(contexto)
    qtbot.addWidget(janela)
    assert not janela.botao_versao_nova.isVisibleTo(janela)    # nada novo: escondido

    nova = [True]
    monkeypatch.setattr(atualizacao, "mais_nova", lambda lancamento: nova[0])
    monkeypatch.setattr(segundo_plano, "executar",
                        lambda funcao, ok, erro: ok(SimpleNamespace(versao="9.9.9")))
    janela.verificar_atualizacao()
    assert janela.botao_versao_nova.isVisibleTo(janela)
    assert janela.botao_versao_nova.text() == "⬆  Atualizar para a 9.9.9"

    chamadas = []
    from honorarios.ui.paineis.configuracoes import PainelConfiguracoes
    monkeypatch.setattr(PainelConfiguracoes, "verificar_e_atualizar",
                        lambda self: chamadas.append(self))
    janela.botao_versao_nova.click()
    assert len(chamadas) == 1
    assert janela.telas.currentWidget() is chamadas[0]

    nova[0] = False            # já atualizado: o botão some
    janela.verificar_atualizacao()
    assert not janela.botao_versao_nova.isVisibleTo(janela)


def test_tarefas_mostram_o_envio_das_parcelas(qtbot, contexto, cliente_com_debito,
                                              monkeypatch):
    from sqlalchemy import select

    from honorarios.infra.modelos import TipoHonorario
    from honorarios.servicos import parcelamentos, tarefas
    from honorarios.ui.dialogos import cobrar
    from honorarios.ui.paineis.tarefas import PainelTarefas

    tipo = contexto.sessao.scalar(
        select(TipoHonorario).where(TipoHonorario.nome == "Parcela de acordo"))
    # 1ª parcela vence em 02/10 (lembrete desde 27/09); a 2ª em 02/11
    parcelamentos.criar(
        contexto.sessao, cliente_com_debito, linhas_do(contexto.sessao, cliente_com_debito),
        Decimal("1000.00"), 2, date(2026, 10, 2), tipo.id)
    contexto.salvar()
    painel = PainelTarefas(contexto)
    qtbot.addWidget(painel)
    assert painel.lista.titulos()[0] == "Enviar parcelas"
    assert painel.quadro.acordos == []               # parcelamento não é acordo de valor
    [tarefa] = painel.quadro.parcelas
    cartao = painel._cartao_parcela(tarefa)
    assert cartao.situacao == "Vence em 3 dia(s)"
    assert [a.texto for a in cartao.acoes] == ["Ver parcelas", "Enviar lembrete", "Dar baixa"]
    assert "1 parcela(s) para enviar" in painel.resumo.text()

    # enviar o lembrete pelo Cobrar: registrado, a tarefa tem baixa sozinha
    def enviou(self):
        self.registrou = True
        return 1
    monkeypatch.setattr(cobrar.DialogoCobrar, "exec", enviou)
    painel._enviar_parcela(tarefa)
    assert painel.quadro.parcelas == []
    assert [t.periodo for t in painel.quadro.parcelas_feitas] == ["1/2"]
    assert tarefas.quadro(contexto.sessao, REFERENCIA).parcelas_feitas


def test_previa_do_juros_das_parcelas_e_cobrar_no_vencimento(
    qtbot, contexto, cliente_com_debito, monkeypatch
):
    from honorarios.servicos import renegociacoes
    from honorarios.ui.comum import widgets
    from honorarios.ui.dialogos import renegociacao
    from honorarios.ui.dialogos.cobrar import DialogoCobrar
    from honorarios.ui.dialogos.parcelas import DialogoParcelas, no_vencimento
    from honorarios.ui.paineis.parcelamentos import PainelParcelamentos

    referencia = contexto.data_referencia
    monkeypatch.setattr(renegociacao, "hoje", lambda: referencia)
    monkeypatch.setattr(renegociacoes, "hoje", lambda: referencia)
    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: True)
    dialogo = renegociacao.DialogoRenegociacao(contexto, cliente_com_debito,
                                               linhas_do(contexto.sessao, cliente_com_debito))
    qtbot.addWidget(dialogo)
    dialogo.parcelas.setValue(3)
    dialogo.primeiro_vencimento.definir(referencia + timedelta(days=30))
    previsto = [dialogo._juros_previsto[p.numero] for p in dialogo.modelo_parcelas.itens]
    assert previsto[0] > 0 and previsto[0] < previsto[1] < previsto[2]   # mais longe, mais juros
    dialogo.juros_correndo.setChecked(False)
    assert dialogo._juros_previsto == {}
    assert "só corre juros se atrasar" in dialogo.resumo.text()
    dialogo.juros_correndo.setChecked(True)
    dialogo._confirmar()

    painel = PainelParcelamentos(contexto)
    qtbot.addWidget(painel)
    [parcelamento] = painel.lista.itens
    primeira = parcelamento.parcelas[0]
    assert primeira.honorario.juros_desde == referencia
    assert no_vencimento(primeira) == primeira.honorario.valor_original + previsto[0]
    parcelas = DialogoParcelas(contexto, parcelamento)
    qtbot.addWidget(parcelas)

    cobrar = DialogoCobrar(contexto, parcelamento.cliente, [primeira.linha])
    qtbot.addWidget(cobrar)
    cobrar.valores_ate(primeira.honorario.vencimento)
    assert cobrar.usar_outra_data.isChecked()
    assert cobrar._selecao().data_referencia == primeira.honorario.vencimento
    assert primeira.linha.atualizacao.juros == previsto[0]


def test_parcelar_com_juros_ao_dia_estipulado(qtbot, contexto, cliente_com_debito, monkeypatch):
    from honorarios.servicos import renegociacoes
    from honorarios.ui.comum import widgets
    from honorarios.ui.dialogos import renegociacao

    referencia = contexto.data_referencia
    monkeypatch.setattr(renegociacao, "hoje", lambda: referencia)
    monkeypatch.setattr(renegociacoes, "hoje", lambda: referencia)
    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: True)
    dialogo = renegociacao.DialogoRenegociacao(contexto, cliente_com_debito,
                                               linhas_do(contexto.sessao, cliente_com_debito))
    qtbot.addWidget(dialogo)
    dialogo.parcelas.setValue(2)
    dialogo.primeiro_vencimento.definir(referencia + timedelta(days=10))
    calculado = dialogo.juros_dia.valor()
    assert calculado > 0 and dialogo.juros_dia_estipulado() is None
    assert not dialogo.botao_juros_dia.isVisibleTo(dialogo)
    dialogo.juros_dia.definir(Decimal("3.00"))           # um juros novo, à mão
    assert dialogo.juros_dia_estipulado() == Decimal("3.00")
    assert dialogo._juros_previsto[1] == Decimal("30.00")  # 10 dias × R$ 3,00
    assert dialogo.botao_juros_dia.isVisibleTo(dialogo)
    dialogo.parcelas.setValue(3)                          # mudar o resto não desfaz o à mão
    assert dialogo.juros_dia.valor() == Decimal("3.00")
    dialogo._confirmar()
    from honorarios.servicos import parcelamentos

    criado = parcelamentos.obter(contexto.sessao, dialogo.acordo.id, referencia)
    assert [p.honorario.juros_dia for p in criado.parcelas] == [Decimal("3.00")] * 3

    outro = renegociacao.DialogoRenegociacao(contexto)
    qtbot.addWidget(outro)
    outro.juros_dia.definir(Decimal("1.00"))
    outro._juros_dia_calculado()                          # volta ao calculado
    assert outro.juros_dia_estipulado() is None


# ------------------------------------------------------ parcelar passo a passo


def _assistente(qtbot, contexto, monkeypatch, *args, **kwargs):
    from honorarios.servicos import renegociacoes
    from honorarios.ui.dialogos import assistente_parcelamento as ap

    referencia = contexto.data_referencia
    monkeypatch.setattr(ap, "hoje", lambda: referencia)
    monkeypatch.setattr(renegociacoes, "hoje", lambda: referencia)
    dialogo = ap.AssistenteParcelamento(contexto, *args, **kwargs)
    qtbot.addWidget(dialogo)
    return dialogo


def test_parcelar_numa_tela_so(qtbot, contexto, cliente_com_debito, monkeypatch):
    from honorarios.servicos import parcelamentos
    from honorarios.ui.comum import widgets

    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: True)
    dialogo = _assistente(qtbot, contexto, monkeypatch)
    assert not dialogo.botao_parcelar.isEnabled()          # sem cliente
    dialogo.campo_cliente.mudou.emit(cliente_com_debito)
    dialogo.modelo.marcar_todos()
    assert dialogo.valor_a_parcelar() == Decimal("1551.00")   # com o juros de hoje
    assert not dialogo.juros_total.isEnabled()             # personalizado apagado
    dialogo.parcelas.setValue(3)
    dialogo.primeiro_vencimento.definir(contexto.data_referencia + timedelta(days=10))
    assert [p.valor for p in dialogo.modelo_parcelas.itens] == [Decimal("517.00")] * 3
    assert dialogo._juros_previsto[1] > 0                  # o juros corre até vencer
    assert "3 × R$ 517,00" in dialogo.total_parcelar.text()
    dialogo._confirmar()
    criado = parcelamentos.obter(contexto.sessao, dialogo.acordo.id, contexto.data_referencia)
    assert len(criado.parcelas) == 3
    assert criado.parcelas[0].honorario.juros_desde == contexto.data_referencia


def test_parcelar_com_juros_total_personalizado(qtbot, contexto, cliente_com_debito,
                                                monkeypatch):
    from honorarios.servicos import parcelamentos
    from honorarios.ui.comum import widgets

    monkeypatch.setattr(widgets, "confirmar", lambda *a, **k: True)
    linhas = linhas_do(contexto.sessao, cliente_com_debito)
    dialogo = _assistente(qtbot, contexto, monkeypatch, cliente_com_debito, linhas)
    calculado = dialogo.juros_calculado_total()
    valor = sum((linha.atualizacao.saldo for linha in linhas), start=Decimal(0))
    dialogo.personalizado.setChecked(True)
    assert dialogo.juros_total.isEnabled() and dialogo.juros_total.valor() == calculado
    dialogo.juros_total.definir(Decimal("10.00"))           # o juros inteiro, não por dia
    juros = [dialogo.atualizacao(linha).juros for linha in dialogo.escolhidos()]
    assert sum(juros) == Decimal("10.00")
    assert dialogo.valor_a_parcelar() == valor + Decimal("10.00")
    dialogo.juros_correndo.setChecked(False)               # só se atrasar
    assert dialogo._juros_previsto == {}
    dialogo._confirmar()
    criado = parcelamentos.obter(contexto.sessao, dialogo.acordo.id, contexto.data_referencia)
    assert criado.acordo.valor_acordado == valor + Decimal("10.00")
    assert criado.parcelas[0].honorario.juros_desde is None


def test_alterar_o_juros_da_empresa_ao_parcelar(qtbot, contexto, cliente_com_debito,
                                                monkeypatch):
    from honorarios.servicos import calculo
    from honorarios.ui.dialogos import assistente_parcelamento as ap

    linhas = linhas_do(contexto.sessao, cliente_com_debito)
    dialogo = _assistente(qtbot, contexto, monkeypatch, cliente_com_debito, linhas)
    antes = dialogo.juros_calculado_total()
    janela = ap.DialogoJurosDaEmpresa(contexto, cliente_com_debito)
    qtbot.addWidget(janela)
    novo = calculo.taxa_vigente_em(cliente_com_debito) * 2
    janela.valor_dia.definir(novo)
    janela._salvar()
    assert calculo.taxa_vigente_em(cliente_com_debito) == novo   # gravou no cadastro
    dialogo._carregar_cliente(cliente_com_debito)
    assert len(dialogo.escolhidos()) == 2                  # as marcações ficam
    assert dialogo.juros_calculado_total() == antes * 2
    assert "R$" in dialogo.juros_empresa.text()


def test_juros_do_cobrar_vira_o_personalizado(qtbot, contexto, cliente_com_debito,
                                              monkeypatch):
    linhas = linhas_do(contexto.sessao, cliente_com_debito)
    dialogo = _assistente(qtbot, contexto, monkeypatch, cliente_com_debito, linhas,
                          juros={linhas[0].honorario.id: Decimal("5.00")})
    assert dialogo.personalizado.isChecked()
    assert dialogo.juros_total.valor() == Decimal("5.00") + linhas[1].atualizacao.juros


def test_janela_do_juros_inteiro_ou_por_dia(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.dialogos import juros_manual

    linha = linhas_do(contexto.sessao, cliente_com_debito)[0]

    # a janela do juros: o juros inteiro ou um valor por dia × dias de atraso
    atual = linha.atualizacao
    janela = juros_manual.DialogoJurosManual("x", linha.honorario, atual)
    qtbot.addWidget(janela)
    janela.campo.definir(Decimal("1.00"))
    assert "parece o juros de UM dia" in janela.conta.text()
    janela.modo_dia.setChecked(True)
    janela.campo.definir(Decimal("2.00"))
    assert janela.juros_escolhido() == Decimal("2.00") * atual.dias_atraso
    janela._aplicar()
    assert janela.juros == Decimal("2.00") * atual.dias_atraso
    assert janela.valor_dia == Decimal("2.00")


def test_cobrar_tem_parcelar_com_os_juros_da_tela(qtbot, contexto, cliente_com_debito,
                                                  monkeypatch):
    from honorarios.ui.dialogos import assistente_parcelamento
    from honorarios.ui.dialogos.cobrar import DialogoCobrar

    linhas = linhas_do(contexto.sessao, cliente_com_debito)
    cobrar = DialogoCobrar(contexto, cliente_com_debito, linhas)
    qtbot.addWidget(cobrar)
    assert cobrar.botao_parcelar.isVisibleTo(cobrar)
    cobrar.definir_juros(cobrar.linhas[0], Decimal("7.00"))
    recebido = {}

    def parcelar(contexto_, cliente, linhas_, juros, parent=None):
        recebido.update(cliente=cliente, ids=[x.honorario.id for x in linhas_], juros=juros)
        return "acordo"

    monkeypatch.setattr(assistente_parcelamento, "parcelar", parcelar)
    cobrar._parcelar()
    assert recebido["cliente"] is cliente_com_debito
    assert recebido["juros"] == {cobrar.linhas[0].honorario.id: Decimal("7.00")}
    assert cobrar.parcelou == "acordo" and cobrar.registrou


def test_tarefas_mostram_o_pagamento_do_acordo(qtbot, contexto, cliente_com_debito,
                                               monkeypatch):
    from honorarios.servicos import acordos
    from honorarios.ui.dialogos import cobrar
    from honorarios.ui.paineis.tarefas import PainelTarefas

    honorarios = [linha.honorario for linha in linhas_do(contexto.sessao, cliente_com_debito)]
    acordos.registrar(contexto.sessao, honorarios, REFERENCIA, date(2026, 10, 5))
    contexto.salvar()
    painel = PainelTarefas(contexto)
    qtbot.addWidget(painel)
    assert "Pagamento de acordos" in painel.lista.titulos()
    [tarefa] = painel.quadro.acordos
    cartao = painel._cartao_acordo(tarefa)
    assert cartao.situacao == "Vence em 6 dia(s)"
    assert [a.texto for a in cartao.acoes] == ["Cadastro", "Cobrar", "Dar baixa"]
    assert "1 acordo(s) para acompanhar" in painel.resumo.text()

    abertos = []
    monkeypatch.setattr(cobrar.DialogoCobrar, "exec",
                        lambda self: abertos.append(len(self.linhas)) or 0)
    painel._cobrar_acordo(tarefa)
    assert abertos == [len(honorarios)]

    painel._dar_baixa(tarefa)
    assert painel.quadro.acordos == [] and len(painel.quadro.acordos_feitos) == 1
    painel._desfazer(painel.quadro.acordos_feitos[0])
    assert len(painel.quadro.acordos) == 1


def test_painel_do_cliente_mostra_tudo_numa_tela(qtbot, contexto, cliente_com_debito,
                                                 monkeypatch):
    from PySide6.QtWidgets import QPushButton

    from honorarios.dominio.enums import Periodicidade
    from honorarios.servicos import contratos, tipos
    from honorarios.ui.dialogos import ficha
    from honorarios.ui.dialogos.cliente import COLUNAS_CONTRATO, DialogoCliente
    from honorarios.ui.paineis import formas_envio

    forma = tipos.listar_formas(contexto.sessao)[0]
    tipo = next(t for t in tipos.listar_tipos(contexto.sessao)
                if t.nome == "Honorário mensal")
    contratos.criar(contexto.sessao, contratos.DadosContrato(
        cliente_id=cliente_com_debito.id, tipo_id=tipo.id, valor=Decimal("500.00"),
        periodicidade=Periodicidade.MENSAL, dia_vencimento=10, forma_envio_id=forma.id,
        vigencia_inicio=date(2026, 1, 1)))
    contexto.salvar()

    painel = DialogoCliente(contexto, cliente_com_debito)
    qtbot.addWidget(painel)
    # dados, juros, contatos e honorários recorrentes: tudo na mesma tela
    assert not hasattr(painel, "abas")
    assert painel.nome.text() == cliente_com_debito.nome
    assert painel.contatos.rowCount() == len(cliente_com_debito.contatos)
    coluna = COLUNAS_CONTRATO.index("Forma de envio")
    assert painel.tabela_contratos.item(0, coluna).text() == forma.nome

    botoes = {botao.text(): botao for botao in painel.findChildren(QPushButton)}
    abertas = []
    monkeypatch.setattr(formas_envio.DialogoFormasEnvio, "exec",
                        lambda self: abertas.append("formas") or 0)
    botoes["Formas de envio…"].click()
    monkeypatch.setattr(ficha.DialogoFicha, "exec",
                        lambda self: abertas.append(self.com_cadastro) or 0)
    botoes["Débitos e histórico (ficha)…"].click()
    assert abertas == ["formas", False]       # a ficha não reabre o cadastro por cima


def test_clientes_abre_o_painel_no_duplo_clique(qtbot, contexto, cliente_com_debito,
                                                monkeypatch):
    from honorarios.ui.dialogos import cliente as dialogo_cliente
    from honorarios.ui.paineis.clientes import PainelClientes

    abertos = []
    monkeypatch.setattr(dialogo_cliente.DialogoCliente, "exec",
                        lambda self: abertos.append(self.cliente) or 0)
    painel = PainelClientes(contexto)
    qtbot.addWidget(painel)
    painel.tabela.selectRow(0)
    painel.tabela.doubleClicked.emit(painel.modelo.index(0, 0))
    assert abertos == [cliente_com_debito]


def test_cadastro_do_cliente_cria_subtipo_na_hora(qtbot, contexto, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    from honorarios.dominio.enums import TipoPessoa
    from honorarios.ui.dialogos import subtipos as dialogo_subtipos
    from honorarios.ui.dialogos.cliente import DialogoCliente

    dialogo = DialogoCliente(contexto)
    qtbot.addWidget(dialogo)
    dialogo.tipo.definir(TipoPessoa.PF)
    campo = dialogo.subtipo
    assert [campo.combo.itemData(i) for i in range(campo.combo.count())] == ["", "Doméstica"]

    def criar_caseiro(janela):
        monkeypatch.setattr(QInputDialog, "getText",
                            staticmethod(lambda *a, **k: ("Caseiro", True)))
        janela._novo()
        return 1

    monkeypatch.setattr(dialogo_subtipos.DialogoSubtipos, "exec", criar_caseiro)
    campo.botao.click()
    assert campo.valor() == "Caseiro"                 # o novo já vem escolhido

    dialogo.tipo.definir(TipoPessoa.PJ)
    dialogo._ajustar_subtipo()
    assert campo.valor() == "" and not campo.combo.isEnabled()
