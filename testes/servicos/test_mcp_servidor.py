"""Servidor MCP: as ferramentas usam as mesmas regras das telas e gravam de verdade."""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

pytest.importorskip("mcp")

from honorarios import mcp_servidor as servidor
from honorarios.infra import db
from honorarios.infra.modelos import Cliente
from testes import fabricas


@pytest.fixture(autouse=True)
def banco_pronto(sessao, monkeypatch):
    # o banco do teste já está montado; não deixa o servidor reconfigurar o engine
    monkeypatch.setattr(servidor, "_preparado", True)


@pytest.fixture
def devedor(sessao):
    cliente = fabricas.cliente(sessao, codigo="800", nome="EMPRESA DEVEDORA LTDA")
    fabricas.honorario(sessao, cliente, valor="1000.00", vencimento=date(2026, 8, 10))
    return cliente


def test_todas_as_ferramentas_estao_registradas():
    nomes = {ferramenta.name for ferramenta in asyncio.run(servidor.mcp.list_tools())}
    assert {
        "resumo_geral", "buscar_clientes", "listar_honorarios", "registrar_pagamento",
        "estornar_pagamento", "suspender_cobranca", "criar_cliente", "excluir_contrato",
    } <= nomes


def test_listar_honorarios_traz_juros_e_total(devedor):
    resultado = servidor.listar_honorarios(data_referencia="2026-09-29")

    assert resultado["quantidade"] == 1
    assert resultado["honorarios"][0]["cliente"] == "EMPRESA DEVEDORA LTDA"
    assert resultado["honorarios"][0]["dias_atraso"] > 0
    assert float(resultado["total"]) > 1000


def test_buscar_clientes_ignora_acento_e_caixa(devedor):
    assert [c["codigo"] for c in servidor.buscar_clientes("devedora")] == ["800"]


def test_criar_cliente_grava_e_valida(sessao):
    criado = servidor.criar_cliente(
        "801", "NOVA EMPRESA LTDA", "1,01", documento=fabricas.CNPJ_FICTICIO
    )
    assert criado["id"]
    with db.sessao() as outra:   # outra sessão: gravou de verdade
        assert outra.get(Cliente, criado["id"]).nome == "NOVA EMPRESA LTDA"
    with pytest.raises(ValueError, match="CPF/CNPJ inválido"):
        servidor.criar_cliente("802", "SEM DOCUMENTO VALIDO", "1.01", documento="123")


def test_pagamento_e_estorno_pela_ferramenta(devedor):
    honorario_id = servidor.listar_honorarios()["honorarios"][0]["id"]

    pago = servidor.registrar_pagamento(
        honorario_id, "1.000,00", data="2026-08-10", juros_cobrados="0"
    )
    assert pago["honorario_status"] == "PAGO"
    assert servidor.listar_honorarios()["quantidade"] == 0

    servidor.estornar_pagamento(pago["pagamento"]["id"], "lançado por engano")
    assert servidor.listar_honorarios()["quantidade"] == 1


def test_regra_de_negocio_vira_erro_legivel(devedor):
    honorario_id = servidor.listar_honorarios()["honorarios"][0]["id"]
    with pytest.raises(ValueError, match="maior que zero"):
        servidor.registrar_pagamento(honorario_id, "0")


def test_suspender_e_retomar_cobranca(devedor):
    suspenso = servidor.suspender_cobranca(devedor.id, "acordo judicial")
    assert suspenso["cobranca_suspensa"] is True
    assert servidor.retomar_cobranca(devedor.id)["cobranca_suspensa"] is False


def test_excluir_cliente_com_divida_e_recusado(devedor):
    with pytest.raises(ValueError, match="em aberto"):
        servidor.excluir_cliente(devedor.id)


def test_vincular_pessoa_fisica_a_empresa(devedor):
    pessoa = servidor.criar_cliente(
        "803", "SOCIO EXEMPLO", "0.20", tipo_pessoa="PF", documento=fabricas.CPF_FICTICIO,
        empresa_id=devedor.id,
    )
    assert pessoa["empresa_id"] == devedor.id
    assert servidor.atualizar_cliente(pessoa["id"], desvincular_empresa=True)["empresa_id"] is None


def test_enum_invalido_diz_os_valores_aceitos():
    with pytest.raises(ValueError, match="EM_ABERTO"):
        servidor.listar_honorarios(situacao="QUALQUER")


def test_atualizar_cliente_preserva_os_contatos(devedor):
    antes = servidor.obter_cliente(cliente_id=devedor.id)["contatos"]
    assert antes

    servidor.atualizar_cliente(devedor.id, observacoes="só a observação mudou")

    depois = servidor.obter_cliente(cliente_id=devedor.id)
    assert depois["contatos"] == antes
    assert depois["observacoes"] == "só a observação mudou"


def test_alterar_juros_vale_daqui_para_frente(devedor):
    novo = servidor.alterar_juros_cliente(devedor.id, "2,50", motivo="reajuste")
    assert novo["juros_dia"] == "2.50"


# ------------------------------------------------------------- conexão com o Claude
def test_cada_chamada_anota_o_ultimo_uso(sessao, devedor):
    from honorarios.servicos import conexao_claude

    assert conexao_claude.ultimo_uso(sessao) is None
    servidor.buscar_clientes("devedora")
    sessao.expire_all()

    uso = conexao_claude.ultimo_uso(sessao)
    assert uso is not None and uso.ferramenta == "buscar_clientes"


def test_registrar_no_desktop_preserva_os_outros_servidores(tmp_path):
    import json

    from honorarios.servicos import conexao_claude

    arquivo = tmp_path / "Claude" / "claude_desktop_config.json"
    arquivo.parent.mkdir()
    arquivo.write_text(json.dumps({"mcpServers": {"outro": {"command": "x"}}, "tema": "escuro"}))
    assert not conexao_claude.registrado_no_desktop(arquivo)

    conexao_claude.registrar_no_desktop(arquivo)

    dados = json.loads(arquivo.read_text())
    assert dados["tema"] == "escuro"
    assert dados["mcpServers"]["outro"] == {"command": "x"}
    assert conexao_claude.NOME_SERVIDOR in dados["mcpServers"]
    assert conexao_claude.registrado_no_desktop(arquivo)
    assert arquivo.with_suffix(".json.bak").is_file()


def test_configuracao_do_desktop_quebrada_nao_e_sobrescrita(tmp_path):
    from honorarios.servicos import conexao_claude
    from honorarios.servicos.erros import ErroDeNegocio

    arquivo = tmp_path / "claude_desktop_config.json"
    arquivo.write_text("{ isso não é json")
    with pytest.raises(ErroDeNegocio, match="Não consegui ler"):
        conexao_claude.registrar_no_desktop(arquivo)
    assert arquivo.read_text() == "{ isso não é json"


def test_o_servidor_responde_pelo_protocolo(pasta_dados):
    """Sobe o servidor noutro processo, como o Claude faz, com o SQLite do teste."""
    import os

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from honorarios.servicos import conexao_claude

    comando = conexao_claude.comando_do_servidor()
    parametros = StdioServerParameters(command=comando.executavel, args=comando.argumentos,
                                       env=dict(os.environ))

    async def conversar() -> int:
        async with stdio_client(parametros) as (leitura, escrita):
            async with ClientSession(leitura, escrita) as sessao:
                await sessao.initialize()
                return len((await sessao.list_tools()).tools)

    assert asyncio.run(asyncio.wait_for(conversar(), 60)) >= 38


@pytest.fixture
def computador(tmp_path, monkeypatch):
    """Um Windows de mentira: AppData comum, pacote da Store e o .claude.json do Code."""
    import sys

    from honorarios.servicos import conexao_claude

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "usuario"))
    exe = conexao_claude.Comando("C:/Financeiro/FinanceiroMetodosMCP.exe", [])
    monkeypatch.setattr(conexao_claude, "comando_do_servidor", lambda: exe)
    return tmp_path


def test_claude_da_store_le_de_dentro_do_pacote(computador):
    from honorarios.servicos import conexao_claude

    loja = computador / "Local" / "Packages" / "Claude_pzs8sxrjxfjjc"
    loja.mkdir(parents=True)

    arquivos = conexao_claude.arquivos_do_desktop()

    assert arquivos == [loja / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"]


def test_sem_claude_nenhum_grava_no_lugar_do_instalador_comum(computador):
    from honorarios.servicos import conexao_claude

    assert conexao_claude.arquivos_do_desktop() == [
        computador / "Roaming" / "Claude" / "claude_desktop_config.json"]


def test_registrar_em_todos_grava_no_desktop_na_store_e_no_code(computador):
    import json

    from honorarios.servicos import conexao_claude

    (computador / "Roaming" / "Claude").mkdir(parents=True)
    (computador / "Local" / "Packages" / "Claude_pzs8sxrjxfjjc").mkdir(parents=True)
    code = computador / "usuario" / ".claude.json"
    code.parent.mkdir()
    code.write_text(json.dumps({"numStartups": 7, "mcpServers": {"outro": {"command": "x"}}}))

    registro = conexao_claude.registrar_em_todos()

    assert len(registro.gravados) == 3 and not registro.falhas
    for arquivo in registro.gravados:
        assert conexao_claude.registrado_em(arquivo)
    dados = json.loads(code.read_text())
    assert dados["numStartups"] == 7 and dados["mcpServers"]["outro"] == {"command": "x"}
    assert dados["mcpServers"][conexao_claude.NOME_SERVIDOR] == {
        "type": "stdio", "command": "C:/Financeiro/FinanceiroMetodosMCP.exe", "args": [],
        "env": {}}


def test_configuracao_quebrada_nao_impede_as_outras(computador):
    import json

    from honorarios.servicos import conexao_claude

    quebrado = computador / "Roaming" / "Claude" / "claude_desktop_config.json"
    quebrado.parent.mkdir(parents=True)
    quebrado.write_text("{ isso não é json")
    code = computador / "usuario" / ".claude.json"
    code.parent.mkdir()
    code.write_text(json.dumps({}))

    registro = conexao_claude.registrar_em_todos()

    assert registro.gravados == [code]
    assert "Não consegui ler" in registro.falhas[0]
    assert quebrado.read_text() == "{ isso não é json"


def test_programa_instalado_se_grava_no_claude_ao_abrir(computador, monkeypatch):
    import logging
    import sys

    from honorarios import app
    from honorarios.servicos import conexao_claude

    destino = computador / "Roaming" / "Claude" / "claude_desktop_config.json"
    app.ligar_ao_claude(logging.getLogger("teste"))
    assert not destino.exists()   # do código-fonte não grava nada

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    app.ligar_ao_claude(logging.getLogger("teste"))
    assert conexao_claude.registrado_em(destino)


# ----------------------------------------------------------- e-mail do financeiro
LISTA_DO_FINANCEIRO = """\
Cobranças de 24/09/2026

Cliente                 Competência             Vencimento            Valor

Alfa Móveis Ltda.        07/2026             05/08/2026        1.507,80
"""


@pytest.fixture
def email_do_financeiro(sessao):
    """Alfa continua na lista; Beta saiu (pagou por fora). E-mail aberto de arquivo."""
    from honorarios.dominio.valores import Competencia
    from honorarios.servicos import caixa_email
    from honorarios.servicos import email_cobrancas as servico_email

    alfa = fabricas.cliente(sessao, codigo="301", nome="ALFA MOVEIS LTDA", documento="")
    beta = fabricas.cliente(sessao, codigo="302", nome="BETA SERVICOS LTDA", documento="")
    fabricas.honorario(sessao, alfa, valor="1507.80", vencimento=date(2026, 8, 5),
                       competencia=Competencia(2026, 7))
    pago_por_fora = fabricas.honorario(sessao, beta, valor="399.00",
                                       vencimento=date(2026, 9, 8),
                                       competencia=Competencia(2026, 8))
    mensagem = caixa_email.guardar_do_arquivo(
        sessao, servico_email.EmailRecebido(LISTA_DO_FINANCEIRO, de="financeiro@exemplo.com"))
    sessao.commit()
    return mensagem, pago_por_fora


def test_ler_email_confere_com_o_sistema(email_do_financeiro):
    mensagem, pago_por_fora = email_do_financeiro

    lido = servidor.ler_email(mensagem.id)

    conferencia = lido["conferencia"]
    assert [x["cliente"] for x in conferencia["continuam"]] == ["Alfa Móveis Ltda."]
    assert [x["id"] for x in conferencia["sairam_da_lista"]] == [pago_por_fora.id]
    assert servidor.listar_emails()[0]["lido"] is True


def test_baixar_quem_saiu_da_lista(email_do_financeiro):
    mensagem, pago_por_fora = email_do_financeiro

    feito = servidor.baixar_quem_saiu_da_lista(
        mensagem.id, [pago_por_fora.id], data_pagamento="2026-09-20", com_juros=False)

    assert feito["baixados"] == 1
    assert feito["itens"][0]["valor"] == "399.00"
    assert servidor.obter_honorario(pago_por_fora.id)["status"] == "PAGO"


def test_resposta_ao_financeiro_sem_quem_saiu(email_do_financeiro):
    mensagem, _ = email_do_financeiro

    resposta = servidor.montar_resposta_financeiro(mensagem.id, introducao="Bom dia!")

    assert resposta["para"] == "financeiro@exemplo.com"
    assert resposta["texto"].startswith("Bom dia!")
    assert "ALFA" in resposta["texto"].upper() and "BETA" not in resposta["texto"].upper()


def test_rascunho_da_resposta_vira_eml(email_do_financeiro, sessao):
    from honorarios.servicos import email_cobrancas as servico_email

    servico_email.gravar_remetente(sessao, servico_email.Remetente(
        nome="Quem Cobra", email="cobranca@exemplo.com", para="", cc="",
        assunto=servico_email.ASSUNTO_PADRAO))
    sessao.commit()
    mensagem, _ = email_do_financeiro

    feito = servidor.responder_financeiro(mensagem.id, modo="rascunho", introducao="Segue.",
                                          abrir_rascunho=False)

    from pathlib import Path

    bruto = Path(feito["rascunho"]).read_bytes()
    assert b"X-Unsent: 1" in bruto and b"Segue." in bruto


def test_enviar_resposta_de_arquivo_e_recusado(email_do_financeiro):
    mensagem, _ = email_do_financeiro
    with pytest.raises(ValueError, match="rascunho"):
        servidor.responder_financeiro(mensagem.id, modo="enviar")


# ---------------------------------------------------------------------- WhatsApp
def test_cobranca_no_whatsapp_com_a_chave_no_fim(sessao, devedor, monkeypatch):
    from honorarios.servicos import configuracoes

    configuracoes.gravar(sessao, "recebedor_chave", "11.222.333/0001-81")
    sessao.commit()
    abertos = []
    monkeypatch.setattr(servidor, "_abrir", abertos.append)
    monkeypatch.setattr(servidor, "_copiar_imagem", lambda *_: None)

    feito = servidor.cobrar_por_whatsapp(devedor.id, registrar=True)

    assert feito["mensagem"].splitlines()[-1] == "11.222.333/0001-81"
    assert feito["link"].startswith("https://wa.me/5527999990000?text=")
    assert abertos == [feito["link"]]
    assert feito["imagem"].endswith(".png") and feito["imagem_copiada"] is True
    assert servidor.listar_honorarios()["honorarios"][0]["cobrancas"] == 1


def test_cobranca_no_whatsapp_sem_registrar_nao_grava(devedor, monkeypatch):
    monkeypatch.setattr(servidor, "_abrir", lambda _link: None)

    servidor.cobrar_por_whatsapp(devedor.id, com_imagem=False)

    assert servidor.listar_honorarios()["honorarios"][0]["cobrancas"] == 0
