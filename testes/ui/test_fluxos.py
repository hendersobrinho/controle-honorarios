"""Fluxos principais da interface, com pytest-qt.

Não testa aparência: testa que a tela lê o serviço certo, mostra o que deveria e
grava o que o usuário confirmou.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from honorarios.dominio.enums import ResultadoCobranca, StatusPagamento
from honorarios.dominio.valores import Competencia
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


def test_painel_cobranca_geral_mostra_secoes_e_subtotal(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.paineis.cobranca_geral import PainelCobrancaGeral

    painel = PainelCobrancaGeral(contexto)
    qtbot.addWidget(painel)
    assert painel.lista.titulos() == ["Mensais"]
    assert len(painel.lista.itens) == 2
    assert painel.lista.secoes[0].total == "R$ 1.551,00"  # 1000+10 e 500+41
    assert "2 honorário(s)" in painel.resumo.text()


def test_cartao_mostra_situacao_e_leva_ao_historico(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.paineis.cobranca_geral import PainelCobrancaGeral

    painel = PainelCobrancaGeral(contexto)
    qtbot.addWidget(painel)
    cartao = painel.lista.secoes[0].cartoes[0]
    assert "Em atraso há" in cartao.situacao
    assert cartao.cor is not None                      # faixa vermelha de atraso
    assert [acao.texto for acao in cartao.acoes] == ["Histórico", "Cobrar"]
    assert cartao.valor == "R$ 541,00"


def test_alternar_para_pagos_nao_mistura_com_pendentes(qtbot, contexto, cliente_com_debito):
    from honorarios.dominio.enums import FormaPagamento
    from honorarios.servicos import pagamentos
    from honorarios.ui.paineis.cobranca_geral import PainelCobrancaGeral

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

    painel = PainelCobrancaGeral(contexto)
    qtbot.addWidget(painel)
    assert all(
        item.atualizacao.status is StatusPagamento.EM_ABERTO for item in painel.lista.itens
    )

    painel.grupo_situacao.button(1).setChecked(True)  # Pagos
    pagos = painel.lista.itens
    assert pagos and all(
        item.atualizacao.status is StatusPagamento.PAGO for item in pagos
    )
    assert all(titulo.startswith("Pagos · ") for titulo in painel.lista.titulos())


def test_filtro_de_faixa_de_atraso(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.paineis.cobranca_geral import PainelCobrancaGeral

    painel = PainelCobrancaGeral(contexto)
    qtbot.addWidget(painel)
    painel.faixa.setCurrentIndex(3)  # 31 a 60 dias
    itens = painel.lista.itens
    assert len(itens) == 1
    assert itens[0].atualizacao.dias_atraso == 41


def test_agrupar_por_empresa(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.paineis.cobranca_geral import PainelCobrancaGeral

    painel = PainelCobrancaGeral(contexto)
    qtbot.addWidget(painel)
    painel.agrupamento.setCurrentIndex(1)
    assert painel.lista.titulos()[0].startswith("900 – EMPRESA EXEMPLO")


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


def test_painel_fila_do_dia_separa_secoes(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.paineis.fila_dia import PainelFilaDia

    painel = PainelFilaDia(contexto)
    qtbot.addWidget(painel)
    # só as seções com conteúdo aparecem
    assert painel.lista.titulos() == ["Nunca cobrado"]
    assert len(painel.lista.itens_da_secao("Nunca cobrado")) == 2


def test_fila_de_envio_agrupa_e_resume(qtbot, contexto, cliente_com_debito):
    from honorarios.ui.paineis.fila_envio import PainelFilaEnvio

    painel = PainelFilaEnvio(contexto)
    qtbot.addWidget(painel)
    assert painel.modelo.rowCount() == 1
    assert "1 empresa(s) marcada(s)" in painel.resumo.text()
    assert "2 honorário(s)" in painel.resumo.text()


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
    assert janela.telas.count() == 11
    assert len(janela.linhas_de_tela) == 11
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


def test_periodo_dos_pagos_na_cobranca_geral(qtbot, contexto, cliente_com_debito):
    from honorarios.servicos import pagamentos
    from honorarios.ui.paineis.cobranca_geral import PainelCobrancaGeral

    linha = linhas_do(contexto.sessao, cliente_com_debito)[0]
    previa = pagamentos.previa(linha.honorario, date(2026, 5, 10))
    pagamentos.registrar(
        contexto.sessao,
        linha.honorario,
        pagamentos.DadosPagamento(data=date(2026, 5, 10), valor_pago=previa.total_devido),
    )
    contexto.salvar()

    painel = PainelCobrancaGeral(contexto)
    qtbot.addWidget(painel)
    assert not painel.periodo_pagos.isEnabled()      # em Pendentes não faz sentido

    painel.grupo_situacao.button(1).setChecked(True)  # Pagos
    assert painel.periodo_pagos.isEnabled()
    assert painel.lista.itens == []                   # fora dos últimos 3 meses
    painel.periodo_pagos.setCurrentIndex(4)           # Tudo
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


def test_fila_do_dia_nao_mostra_cliente_suspenso(qtbot, contexto, cliente_com_debito):
    from honorarios.servicos import clientes
    from honorarios.ui.paineis.fila_dia import PainelFilaDia

    painel = PainelFilaDia(contexto)
    qtbot.addWidget(painel)
    assert painel.linhas

    clientes.suspender_cobranca(contexto.sessao, cliente_com_debito, "Acordo")
    contexto.salvar()
    painel.recarregar()
    assert painel.linhas == []


def test_cartao_mostra_etiqueta_de_cobranca_suspensa(qtbot, contexto, cliente_com_debito):
    from honorarios.servicos import clientes
    from honorarios.ui.paineis.cobranca_geral import PainelCobrancaGeral

    clientes.suspender_cobranca(contexto.sessao, cliente_com_debito, "Acordo")
    contexto.salvar()
    painel = PainelCobrancaGeral(contexto)
    qtbot.addWidget(painel)
    cartao = painel.lista.secoes[0].cartoes[0]
    assert cartao.situacao == "Cobrança suspensa"
    # sem botão de cobrar quem está suspenso não faria sentido: o botão continua,
    # mas o registro é recusado pelo serviço — a etiqueta avisa antes
    assert "Histórico" in [acao.texto for acao in cartao.acoes]
