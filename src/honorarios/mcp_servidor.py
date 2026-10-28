"""Servidor MCP do Financeiro: o Claude trabalha nos honorários como o escritório.

Roda por stdio (``honorarios-mcp``) e usa a mesma camada de serviços das telas,
então toda regra de negócio vale igual: juros, validações, log de alterações. Não
há modo somente leitura — as ferramentas leem e gravam tudo (clientes, honorários,
pagamentos, cobranças, contratos, configurações). Cada ferramenta grava numa
transação própria: se uma regra recusa, nada fica pela metade.

Ferramentas que apagam ou desfazem têm ``destructiveHint`` para o cliente MCP
poder distingui-las; isso é só dica, não bloqueio.
"""

from __future__ import annotations

import functools
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from sqlalchemy.orm import Session

from .dominio.enums import (
    Canal,
    FormaPagamento,
    MeioCobranca,
    Periodicidade,
    ResultadoCobranca,
    SituacaoCliente,
    StatusPagamento,
    SubtipoCliente,
    TipoPessoa,
)
from .dominio.valores import Competencia, agora_utc, formatar_moeda, hoje, ler_data
from .infra import db, esquema
from .infra.modelos import Cobranca, Honorario, Pagamento
from .servicos import (
    calculo,
    clientes,
    cobrancas,
    conexao_claude,
    configuracoes,
    contratos,
    pagamentos,
    rankings,
    tipos,
)
from .servicos import honorarios as servico
from .servicos.erros import ErroDeNegocio

mcp = FastMCP(
    "financeiro-honorarios",
    instructions=(
        "Controle de honorários do escritório (clientes, honorários, juros de atraso, "
        "pagamentos, cobranças e contratos). Datas em AAAA-MM-DD ou DD/MM/AAAA; valores "
        "em reais como texto ('1234.56' ou '1.234,56'). Consulte antes de gravar e "
        "confirme com o usuário antes de excluir, cancelar ou estornar.\n"
        "E-mail do financeiro: verificar_emails → ler_email (já confere com o sistema) → "
        "baixar_quem_saiu_da_lista (confirme antes) → responder_financeiro (prefira "
        "modo='rascunho'; 'enviar' manda pela conta do sistema e não volta atrás).\n"
        "WhatsApp: cobrar_por_whatsapp abre a conversa com a mensagem e a chave Pix e "
        "copia a imagem; quem envia é o usuário. Registre a cobrança (registrar=True ou "
        "registrar_cobranca) só depois que ele confirmar o envio."
    ),
)

LEITURA = ToolAnnotations(readOnlyHint=True)
GRAVA = ToolAnnotations(readOnlyHint=False, destructiveHint=False)
APAGA = ToolAnnotations(readOnlyHint=False, destructiveHint=True)

_preparado = False

# o que a tela de Configurações → Claude lê para dizer se o Claude está usando
CHAVE_ULTIMO_USO = conexao_claude.CHAVE_ULTIMO_USO
CHAVE_ULTIMA_FERRAMENTA = conexao_claude.CHAVE_ULTIMA_FERRAMENTA


def _anotar_uso(nome: str) -> None:
    """Grava quando e qual ferramenta o Claude chamou. Falhar aqui não derruba a chamada."""
    try:
        with db.transacao() as sessao:
            configuracoes.gravar(sessao, CHAVE_ULTIMO_USO, agora_utc().isoformat())
            configuracoes.gravar(sessao, CHAVE_ULTIMA_FERRAMENTA, nome)
    except Exception as falha:  # noqa: BLE001
        print(f"Não consegui anotar o uso de {nome}: {falha}", file=sys.stderr)


def _ferramenta(anotacoes: ToolAnnotations) -> Callable:
    """``mcp.tool`` que também anota o uso (o FastMCP lê a assinatura pelo ``wraps``)."""
    def decorar(funcao: Callable) -> Callable:
        @functools.wraps(funcao)
        def chamada(*args, **kwargs):
            try:
                return funcao(*args, **kwargs)
            finally:
                _anotar_uso(funcao.__name__)

        mcp.tool(annotations=anotacoes)(chamada)
        return chamada
    return decorar


# ----------------------------------------------------------------- infraestrutura
@contextmanager
def _sessao(gravar: bool = False) -> Iterator[Session]:
    """Sessão por chamada; ``gravar`` faz commit no fim e rollback no erro."""
    global _preparado
    if not _preparado:
        esquema.preparar()
        _preparado = True
    aberta = db.sessao()
    try:
        yield aberta
        if gravar:
            aberta.commit()
    except ErroDeNegocio as falha:
        aberta.rollback()
        raise ValueError(str(falha)) from falha
    except Exception:
        aberta.rollback()
        raise
    finally:
        aberta.close()


def _data(texto: str | None) -> date | None:
    return ler_data(texto) if texto else None


def _valor(texto: str | float | int | Decimal) -> Decimal:
    if isinstance(texto, str) and "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return Decimal(str(texto).strip())
    except InvalidOperation as falha:
        raise ValueError(f"Valor inválido: {texto!r}.") from falha


def _enum(enumeracao, texto: str | None, padrao=None):
    if not texto:
        return padrao
    chave = texto.strip().upper().replace(" ", "_")
    try:
        return enumeracao(chave)
    except ValueError as falha:
        validos = ", ".join(item.value for item in enumeracao)
        raise ValueError(
            f"{texto!r} não vale para {enumeracao.__name__}: use {validos}."
        ) from falha


def _plano(valor):
    """Converte para algo que vira JSON: Decimal em texto, data em ISO, enum em valor."""
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    if isinstance(valor, Enum):
        return valor.value
    if is_dataclass(valor) and not isinstance(valor, type):
        return {campo.name: _plano(getattr(valor, campo.name)) for campo in fields(valor)}
    if isinstance(valor, dict):
        return {chave: _plano(item) for chave, item in valor.items()}
    if isinstance(valor, (list, tuple, set)):
        return [_plano(item) for item in valor]
    return valor


def _cliente(sessao: Session, cliente_id: int):
    encontrado = clientes.obter(sessao, cliente_id)
    if encontrado is None or encontrado.excluido_em is not None:
        raise ValueError(f"Cliente {cliente_id} não encontrado.")
    return encontrado


def _honorario(sessao: Session, honorario_id: int) -> Honorario:
    encontrado = sessao.get(Honorario, honorario_id)
    if encontrado is None:
        raise ValueError(f"Honorário {honorario_id} não encontrado.")
    return encontrado


def _linha(sessao: Session, honorario_id: int, referencia: date):
    h = _honorario(sessao, honorario_id)
    return servico.montar_linha(h, calculo.atualizar(h, referencia), referencia)


def _dados_cliente(c) -> dict:
    return {
        "id": c.id,
        "codigo": c.codigo,
        "nome": c.nome,
        "documento": c.documento,
        "tipo_pessoa": c.tipo_pessoa.value,
        "situacao": c.situacao.value,
        "empresa_id": c.empresa_id,
        "juros_dia": _plano(clientes.juros_atual(c)),
        "cobranca_suspensa": c.suspensao_ativa(),
        "motivo_suspensao": c.motivo_suspensao or None,
        "suspensa_ate": _plano(c.suspensa_ate),
        "observacoes": c.observacoes,
    }


def _dados_linha(linha) -> dict:
    h, a = linha.honorario, linha.atualizacao
    return {
        "id": h.id,
        "cliente_id": linha.cliente.id,
        "cliente": linha.cliente.nome,
        "tipo": h.tipo.nome,
        "competencia": h.competencia_rotulo,
        "descricao": h.descricao,
        "vencimento": _plano(h.vencimento),
        "status": h.status.value,
        "valor_original": _plano(a.valor_original),
        "saldo": _plano(a.saldo),
        "juros": _plano(a.juros),
        "total_atualizado": _plano(a.total),
        "dias_atraso": a.dias_atraso,
        "cobrancas": linha.cobrancas,
        "ultima_cobranca": _plano(linha.ultima_cobranca),
        "promessa": _plano(linha.promessa),
        "pago_em": _plano(h.pago_em),
        "numero_boleto": h.numero_boleto,
        "observacoes": h.observacoes,
    }


def _dados_pagamento(p: Pagamento) -> dict:
    return {
        "id": p.id,
        "honorario_id": p.honorario_id,
        "data": _plano(p.data),
        "valor_pago": _plano(p.valor_pago),
        "juros_cobrados": _plano(p.juros_cobrados),
        "desconto": _plano(p.desconto),
        "dias_atraso": p.dias_atraso,
        "forma_pagamento": p.forma_pagamento.value,
        "ativo": p.ativo,
    }


# --------------------------------------------------------------------- consultas
@_ferramenta(LEITURA)
def resumo_geral(data_referencia: str | None = None) -> dict:
    """Visão geral: quantos honorários atrasados, a vencer e de IR, e o total em aberto."""
    referencia = _data(data_referencia) or hoje()
    with _sessao() as sessao:
        contagem = servico.contar_pendentes(sessao, referencia)
        em_aberto = servico.consultar(sessao, servico.Filtro(data_referencia=referencia))
        return {
            "data_referencia": _plano(referencia),
            "atrasados": contagem.atrasados,
            "a_vencer": contagem.a_vencer,
            "imposto_de_renda": contagem.imposto_de_renda,
            "total_em_aberto": _plano(servico.total_de(em_aberto)),
            "total_em_aberto_formatado": formatar_moeda(servico.total_de(em_aberto)),
        }


@_ferramenta(LEITURA)
def buscar_clientes(
    termo: str = "", tipo_pessoa: str | None = None, limite: int = 50
) -> list[dict]:
    """Acha clientes por nome (sem acento), código ou CPF/CNPJ. tipo_pessoa: PF ou PJ."""
    with _sessao() as sessao:
        achados = clientes.buscar(sessao, termo, _enum(TipoPessoa, tipo_pessoa), limite=limite)
        return [_dados_cliente(c) for c in achados]


@_ferramenta(LEITURA)
def obter_cliente(cliente_id: int | None = None, codigo: str | None = None) -> dict:
    """Ficha do cliente (por id ou código): contatos, vínculo com empresa e pessoas vinculadas."""
    with _sessao() as sessao:
        c = _cliente(sessao, cliente_id) if cliente_id else (
            clientes.por_codigo(sessao, codigo) if codigo else None
        )
        if c is None:
            raise ValueError("Informe cliente_id ou um código que exista.")
        dados = _dados_cliente(c)
        dados["contatos"] = [
            {"id": x.id, "nome": x.nome, "tratamento": x.nome_tratamento,
             "telefone": x.telefone, "email": x.email, "principal": x.principal,
             "ativo": x.ativo}
            for x in c.contatos
        ]
        dados["empresa"] = c.empresa.nome if c.empresa else None
        dados["vinculados"] = [
            {"id": v.id, "nome": v.nome} for v in clientes.vinculados(sessao, c)
        ]
        return dados


@_ferramenta(LEITURA)
def listar_honorarios(
    situacao: str | None = "EM_ABERTO",
    termo: str = "",
    cliente_id: int | None = None,
    incluir_vinculados: bool = False,
    tipo_pessoa: str | None = None,
    vencimento_de: str | None = None,
    vencimento_ate: str | None = None,
    pago_de: str | None = None,
    pago_ate: str | None = None,
    atraso_minimo: int | None = None,
    atraso_maximo: int | None = None,
    data_referencia: str | None = None,
    limite: int = 100,
) -> dict:
    """Honorários com juros calculados. situacao: EM_ABERTO, PAGO, CANCELADO, RENEGOCIADO ou
    vazio para todas. Já vêm ordenados por vencimento; ``total`` soma tudo que casou, mesmo
    acima do ``limite``."""
    with _sessao() as sessao:
        filtro = servico.Filtro(
            termo=termo,
            cliente_id=cliente_id,
            incluir_vinculados_de=cliente_id if incluir_vinculados else None,
            tipo_pessoa=_enum(TipoPessoa, tipo_pessoa),
            status=_enum(StatusPagamento, situacao),
            vencimento_de=_data(vencimento_de),
            vencimento_ate=_data(vencimento_ate),
            pago_de=_data(pago_de),
            pago_ate=_data(pago_ate),
            atraso_minimo=atraso_minimo,
            atraso_maximo=atraso_maximo,
            data_referencia=_data(data_referencia),
        )
        linhas = servico.consultar(sessao, filtro)
        return {
            "quantidade": len(linhas),
            "total": _plano(servico.total_de(linhas)),
            "mostrando": min(len(linhas), limite),
            "honorarios": [_dados_linha(linha) for linha in linhas[:limite]],
        }


@_ferramenta(LEITURA)
def obter_honorario(honorario_id: int, data_referencia: str | None = None) -> dict:
    """Um honorário com pagamentos, cobranças e o cálculo de juros na data."""
    with _sessao() as sessao:
        h = _honorario(sessao, honorario_id)
        referencia = _data(data_referencia) or hoje()
        linha = servico.montar_linha(h, calculo.atualizar(h, referencia), referencia)
        dados = _dados_linha(linha)
        dados["pagamentos"] = [_dados_pagamento(p) for p in h.pagamentos]
        dados["historico_cobrancas"] = [
            {"id": c.id, "data_hora": _plano(c.data_hora), "canal": c.canal.value,
             "resultado": c.resultado.value, "promessa": _plano(c.promessa_data),
             "observacao": c.observacao, "estornada": c.estornada_em is not None}
            for c in h.cobrancas
        ]
        return dados


@_ferramenta(LEITURA)
def historico_de_cobrancas(cliente_id: int) -> list[dict]:
    """Todas as cobranças feitas a um cliente, da mais recente para a mais antiga."""
    with _sessao() as sessao:
        return [
            {"id": c.id, "honorario_id": c.honorario_id, "data_hora": _plano(c.data_hora),
             "canal": c.canal.value, "resultado": c.resultado.value,
             "promessa": _plano(c.promessa_data), "observacao": c.observacao,
             "estornada": c.estornada_em is not None}
            for c in cobrancas.historico_do_cliente(sessao, cliente_id)
        ]


@_ferramenta(LEITURA)
def previa_de_pagamento(honorario_id: int, data: str | None = None) -> dict:
    """O que a baixa mostraria: saldo, juros devidos e total na data (hoje se vazia)."""
    with _sessao() as sessao:
        return _plano(pagamentos.previa(_honorario(sessao, honorario_id), _data(data)))


@_ferramenta(LEITURA)
def ranking_de_devedores(criterio: str = "maiores", limite: int = 10) -> dict:
    """Ranking de quem deve. criterio: maiores (valor), antigos (há mais tempo),
    quantidade (mais honorários em aberto) ou cobrados (mais cobranças)."""
    with _sessao() as sessao:
        if criterio == "cobrados":
            return _plano(rankings.mais_cobrados(sessao, limite))
        grupos = servico.agrupar_por_cliente(servico.consultar(sessao, servico.Filtro()))
        funcoes = {
            "maiores": lambda: rankings.maiores_devedores(grupos, limite),
            "antigos": lambda: rankings.devendo_ha_mais_tempo(grupos, limite, hoje()),
            "quantidade": lambda: rankings.mais_honorarios_em_aberto(grupos, limite),
        }
        if criterio not in funcoes:
            raise ValueError("criterio: maiores, antigos, quantidade ou cobrados.")
        return _plano(funcoes[criterio]())


@_ferramenta(LEITURA)
def listar_tipos_e_grupos(incluir_inativos: bool = False) -> dict:
    """Grupos e tipos de honorário (com ids), formas de envio e formas de pagamento válidas."""
    with _sessao() as sessao:
        return {
            "grupos": [{"id": g.id, "nome": g.nome, "ativo": g.ativo}
                       for g in tipos.listar_grupos(sessao, not incluir_inativos)],
            "tipos": [{"id": t.id, "nome": t.nome, "grupo_id": t.grupo_id, "ativo": t.ativo}
                      for t in tipos.listar_tipos(sessao, not incluir_inativos)],
            "formas_de_envio": [{"id": f.id, "nome": f.nome}
                                for f in tipos.listar_formas(sessao)],
            "formas_de_pagamento": [item.value for item in FormaPagamento],
        }


@_ferramenta(LEITURA)
def listar_contratos(cliente_id: int | None = None, incluir_suspensos: bool = True) -> dict:
    """Contratos de honorário recorrente, com o total mensal."""
    with _sessao() as sessao:
        lista = contratos.listar(sessao, cliente_id, incluir_suspensos)
        return {
            "total_mensal": _plano(contratos.total_mensal(sessao)),
            "contratos": [
                {"id": c.id, "cliente_id": c.cliente_id, "cliente": c.cliente.nome,
                 "tipo_id": c.tipo_id, "tipo": c.tipo.nome, "valor": _plano(c.valor),
                 "periodicidade": c.periodicidade.value, "dia_vencimento": c.dia_vencimento,
                 "suspenso": c.suspenso}
                for c in lista
            ],
        }


@_ferramenta(LEITURA)
def ler_configuracao(chave: str, padrao: str = "") -> str:
    """Lê uma configuração do sistema pela chave."""
    with _sessao() as sessao:
        return configuracoes.obter(sessao, chave, padrao)


# ---------------------------------------------------------------------- clientes
@_ferramenta(GRAVA)
def criar_cliente(
    codigo: str,
    nome: str,
    juros_dia: str,
    tipo_pessoa: str = "PJ",
    documento: str = "",
    observacoes: str = "",
    empresa_id: int | None = None,
) -> dict:
    """Cadastra um cliente. ``juros_dia`` é o juros de atraso em R$ por dia (obrigatório, sem
    padrão). Pessoa física pode ser vinculada (empresa_id) à empresa PJ que paga por ela."""
    with _sessao(gravar=True) as sessao:
        criado = clientes.criar(sessao, clientes.DadosCliente(
            codigo=codigo, nome=nome, documento=documento,
            tipo_pessoa=_enum(TipoPessoa, tipo_pessoa), observacoes=observacoes,
            juros_dia=_valor(juros_dia), empresa_id=empresa_id,
        ))
        return _dados_cliente(criado)


@_ferramenta(GRAVA)
def atualizar_cliente(
    cliente_id: int,
    nome: str | None = None,
    codigo: str | None = None,
    documento: str | None = None,
    situacao: str | None = None,
    subtipo: str | None = None,
    observacoes: str | None = None,
    empresa_id: int | None = None,
    desvincular_empresa: bool = False,
) -> dict:
    """Altera só os campos informados; os contatos ficam como estão. empresa_id vincula à
    empresa; desvincular_empresa tira o vínculo. Para o juros use alterar_juros_cliente."""
    with _sessao(gravar=True) as sessao:
        c = _cliente(sessao, cliente_id)
        dados = clientes.DadosCliente(
            codigo=codigo or c.codigo,
            nome=nome or c.nome,
            documento=c.documento if documento is None else documento,
            tipo_pessoa=c.tipo_pessoa,
            subtipo=_enum(SubtipoCliente, subtipo, c.subtipo),
            situacao=_enum(SituacaoCliente, situacao, c.situacao),
            observacoes=c.observacoes if observacoes is None else observacoes,
            # a camada de serviço trata a lista como a verdade: sem repassar os
            # contatos atuais, eles seriam apagados
            contatos=[
                clientes.DadosContato(
                    id=x.id, nome=x.nome, nome_tratamento=x.nome_tratamento,
                    telefone=x.telefone, email=x.email, principal=x.principal,
                    ativo=x.ativo, observacoes=x.observacoes,
                )
                for x in c.contatos
            ],
            empresa_id=None if desvincular_empresa else (empresa_id or c.empresa_id),
        )
        return _dados_cliente(clientes.atualizar(sessao, c, dados))


@_ferramenta(GRAVA)
def alterar_juros_cliente(
    cliente_id: int, juros_dia: str, vigencia_inicio: str | None = None, motivo: str = ""
) -> dict:
    """Novo juros de atraso (R$ por dia) do cliente, valendo da vigência em diante (hoje se
    vazia); o que já venceu antes continua com o juros da época."""
    with _sessao(gravar=True) as sessao:
        c = _cliente(sessao, cliente_id)
        clientes.registrar_juros(sessao, c, _valor(juros_dia), _data(vigencia_inicio), motivo)
        return _dados_cliente(c)


@_ferramenta(APAGA)
def excluir_cliente(cliente_id: int, motivo: str = "") -> str:
    """Exclusão lógica (o histórico fica). Recusa se houver honorário em aberto."""
    with _sessao(gravar=True) as sessao:
        c = _cliente(sessao, cliente_id)
        clientes.excluir(sessao, c, motivo)
        return f"{c.nome} excluído."


@_ferramenta(GRAVA)
def suspender_cobranca(cliente_id: int, motivo: str, ate: str | None = None) -> dict:
    """Tira o cliente das filas de cobrança (a dívida e os juros continuam). Sem ``ate``,
    vale até retomar."""
    with _sessao(gravar=True) as sessao:
        c = _cliente(sessao, cliente_id)
        clientes.suspender_cobranca(sessao, c, motivo, _data(ate))
        return _dados_cliente(c)


@_ferramenta(GRAVA)
def retomar_cobranca(cliente_id: int, motivo: str = "") -> dict:
    """Volta a cobrar um cliente que estava com a cobrança suspensa."""
    with _sessao(gravar=True) as sessao:
        c = _cliente(sessao, cliente_id)
        clientes.retomar_cobranca(sessao, c, motivo)
        return _dados_cliente(c)


# ------------------------------------------------------------------- honorários
def _competencia(ano: int | None, mes: int | None) -> Competencia:
    return Competencia(ano=ano, mes=mes)


@_ferramenta(GRAVA)
def criar_honorario(
    cliente_id: int,
    tipo_id: int,
    valor: str,
    vencimento: str,
    competencia_ano: int | None = None,
    competencia_mes: int | None = None,
    descricao: str = "",
    meio: str = "BOLETO",
    numero_boleto: str = "",
    observacoes: str = "",
) -> dict:
    """Lança um honorário avulso. A competência (ano/mês) depende do tipo; use
    listar_tipos_e_grupos para os ids."""
    with _sessao(gravar=True) as sessao:
        criado = servico.criar(sessao, servico.DadosHonorario(
            cliente_id=cliente_id, tipo_id=tipo_id, valor=_valor(valor),
            vencimento=_data(vencimento),
            competencia=_competencia(competencia_ano, competencia_mes),
            descricao=descricao, meio=_enum(MeioCobranca, meio), numero_boleto=numero_boleto,
            observacoes=observacoes,
        ))
        return _dados_linha(servico.montar_linha(criado, None, hoje()))


@_ferramenta(GRAVA)
def atualizar_honorario(
    honorario_id: int,
    valor: str | None = None,
    vencimento: str | None = None,
    descricao: str | None = None,
    numero_boleto: str | None = None,
    observacoes: str | None = None,
) -> dict:
    """Corrige valor, vencimento ou textos de um honorário em aberto (pago não edita)."""
    with _sessao(gravar=True) as sessao:
        h = _honorario(sessao, honorario_id)
        atualizado = servico.atualizar(sessao, h, servico.DadosHonorario(
            cliente_id=h.cliente_id, tipo_id=h.tipo_id,
            valor=_valor(valor) if valor else h.valor_original,
            vencimento=_data(vencimento) or h.vencimento,
            competencia=_competencia(h.competencia_ano, h.competencia_mes),
            descricao=h.descricao if descricao is None else descricao,
            meio=h.meio, forma_envio_id=h.forma_envio_id,
            observacoes=h.observacoes if observacoes is None else observacoes,
            numero_boleto=h.numero_boleto if numero_boleto is None else numero_boleto,
            contrato_id=h.contrato_id, situacao_envio=h.situacao_envio, enviado_em=h.enviado_em,
        ))
        return _dados_linha(servico.montar_linha(atualizado, None, hoje()))


@_ferramenta(APAGA)
def cancelar_honorario(honorario_id: int, motivo: str) -> str:
    """Cancela um honorário (zera o saldo). Pago precisa de estorno antes."""
    with _sessao(gravar=True) as sessao:
        servico.cancelar(sessao, _honorario(sessao, honorario_id), motivo)
        return f"Honorário {honorario_id} cancelado."


# -------------------------------------------------------------------- pagamentos
@_ferramenta(GRAVA)
def registrar_pagamento(
    honorario_id: int,
    valor_pago: str,
    data: str | None = None,
    juros_cobrados: str | None = None,
    desconto: str = "0",
    justificativa_desconto: str = "",
    forma_pagamento: str = "PIX",
    observacoes: str = "",
) -> dict:
    """Dá baixa (total ou parcial). Sem ``juros_cobrados`` cobra os juros devidos; desconto
    exige justificativa. Use previa_de_pagamento antes para ver os valores."""
    with _sessao(gravar=True) as sessao:
        h = _honorario(sessao, honorario_id)
        pago = pagamentos.registrar(sessao, h, pagamentos.DadosPagamento(
            data=_data(data) or hoje(), valor_pago=_valor(valor_pago),
            juros_cobrados=_valor(juros_cobrados) if juros_cobrados else None,
            desconto=_valor(desconto), justificativa_desconto=justificativa_desconto,
            forma_pagamento=_enum(FormaPagamento, forma_pagamento), observacoes=observacoes,
        ))
        return {"pagamento": _dados_pagamento(pago), "honorario_status": h.status.value}


@_ferramenta(APAGA)
def estornar_pagamento(pagamento_id: int, motivo: str) -> str:
    """Desfaz um pagamento (o registro fica guardado e o honorário volta para em aberto)."""
    with _sessao(gravar=True) as sessao:
        pago = sessao.get(Pagamento, pagamento_id)
        if pago is None:
            raise ValueError(f"Pagamento {pagamento_id} não encontrado.")
        pagamentos.estornar(sessao, pago, motivo)
        return f"Pagamento {pagamento_id} estornado."


# ---------------------------------------------------------------------- cobranças
@_ferramenta(GRAVA)
def registrar_cobranca(
    honorario_ids: list[int],
    canal: str = "WHATSAPP",
    resultado: str = "AGUARDANDO",
    observacao: str = "",
    data: str | None = None,
) -> str:
    """Registra que os honorários foram cobrados (a mensagem foi enviada por fora).
    resultado: AGUARDANDO, SEM_RESPOSTA, PROMETEU_PAGAR, PEDIU_RENEGOCIACAO, CONTESTOU,
    PAGOU ou OUTRO. Para PROMETEU_PAGAR use registrar_promessa."""
    resultado_enum = _enum(ResultadoCobranca, resultado)
    if resultado_enum is ResultadoCobranca.PROMETEU_PAGAR:
        raise ValueError("Para promessa de pagamento use registrar_promessa (precisa da data).")
    with _sessao(gravar=True) as sessao:
        referencia = hoje()
        linhas = [_linha(sessao, i, referencia) for i in honorario_ids]
        total = cobrancas.registrar_sem_mensagem(
            sessao, linhas, observacao, _enum(Canal, canal), resultado_enum, _data(data),
        )
        return f"{total} cobrança(s) registrada(s)."


@_ferramenta(GRAVA)
def registrar_promessa(cobranca_id: int, promessa_data: str, observacao: str | None = None) -> str:
    """Marca uma cobrança já registrada como 'prometeu pagar' em tal data."""
    with _sessao(gravar=True) as sessao:
        c = sessao.get(Cobranca, cobranca_id)
        if c is None:
            raise ValueError(f"Cobrança {cobranca_id} não encontrada.")
        cobrancas.atualizar_resultado(
            sessao, c, ResultadoCobranca.PROMETEU_PAGAR, _data(promessa_data), observacao
        )
        return f"Promessa para {promessa_data} registrada."


@_ferramenta(APAGA)
def estornar_cobranca(cobranca_id: int, motivo: str) -> str:
    """Marca uma cobrança como estornada (registrada por engano)."""
    with _sessao(gravar=True) as sessao:
        c = sessao.get(Cobranca, cobranca_id)
        if c is None:
            raise ValueError(f"Cobrança {cobranca_id} não encontrada.")
        cobrancas.estornar(sessao, c, motivo)
        return f"Cobrança {cobranca_id} estornada."


@_ferramenta(LEITURA)
def gerar_mensagem_de_cobranca(cliente_id: int, honorario_ids: list[int] | None = None) -> str:
    """Texto pronto de cobrança do cliente (todos os honorários cobráveis, ou só os
    informados). Não envia nem registra nada."""
    with _sessao() as sessao:
        c = _cliente(sessao, cliente_id)
        referencia = hoje()
        alvo = cobrancas.linhas_em_aberto_do_cliente(sessao, cliente_id, referencia) \
            if not honorario_ids else [_linha(sessao, i, referencia) for i in honorario_ids]
        if not alvo:
            raise ValueError("Esse cliente não tem honorário em aberto para cobrar.")
        return cobrancas.gerar_texto(sessao, cobrancas.Selecao(cliente=c, linhas=list(alvo)))


# ---------------------------------------------------------------------- contratos
@_ferramenta(GRAVA)
def criar_contrato(
    cliente_id: int,
    tipo_id: int,
    valor: str,
    periodicidade: str = "MENSAL",
    dia_vencimento: int = 10,
    vigencia_inicio: str | None = None,
    vigencia_fim: str | None = None,
    observacoes: str = "",
) -> dict:
    """Cria o contrato recorrente de um cliente para um tipo de honorário."""
    with _sessao(gravar=True) as sessao:
        c = contratos.criar(sessao, contratos.DadosContrato(
            cliente_id=cliente_id, tipo_id=tipo_id, valor=_valor(valor),
            periodicidade=_enum(Periodicidade, periodicidade), dia_vencimento=dia_vencimento,
            vigencia_inicio=_data(vigencia_inicio), vigencia_fim=_data(vigencia_fim),
            observacoes=observacoes,
        ))
        return {"id": c.id, "valor": _plano(c.valor)}


@_ferramenta(GRAVA)
def reajustar_contrato(contrato_id: int, novo_valor: str, motivo: str = "") -> dict:
    """Novo valor do contrato daqui para frente (o que já foi gerado não muda)."""
    with _sessao(gravar=True) as sessao:
        contrato = sessao.get(contratos.Contrato, contrato_id)
        if contrato is None:
            raise ValueError(f"Contrato {contrato_id} não encontrado.")
        contratos.reajustar(sessao, contrato, _valor(novo_valor), motivo=motivo)
        return {"id": contrato.id, "valor": _plano(contrato.valor)}


@_ferramenta(GRAVA)
def suspender_contrato(contrato_id: int, suspenso: bool = True) -> str:
    """Pausa (ou retoma, com suspenso=false) a geração mensal de um contrato."""
    with _sessao(gravar=True) as sessao:
        contrato = sessao.get(contratos.Contrato, contrato_id)
        if contrato is None:
            raise ValueError(f"Contrato {contrato_id} não encontrado.")
        contratos.suspender(sessao, contrato, suspenso)
        return "Contrato suspenso." if suspenso else "Contrato retomado."


@_ferramenta(APAGA)
def excluir_contrato(contrato_id: int) -> str:
    """Exclui o contrato (lógico). Os honorários já gerados continuam."""
    with _sessao(gravar=True) as sessao:
        contrato = sessao.get(contratos.Contrato, contrato_id)
        if contrato is None:
            raise ValueError(f"Contrato {contrato_id} não encontrado.")
        contratos.excluir(sessao, contrato)
        return f"Contrato {contrato_id} excluído."


# ------------------------------------------------------------------ configuração
@_ferramenta(GRAVA)
def gravar_configuracao(chave: str, valor: str) -> str:
    """Grava uma configuração do sistema (chave/valor em texto)."""
    with _sessao(gravar=True) as sessao:
        configuracoes.gravar(sessao, chave, valor)
        return f"{chave} gravada."


# -------------------------------------------------------- e-mail do financeiro
def _email_guardado(sessao: Session, email_id: int):
    from .infra.modelos import EmailMensagem

    mensagem = sessao.get(EmailMensagem, email_id)
    if mensagem is None:
        raise ValueError(f"E-mail {email_id} não encontrado (use listar_emails).")
    return mensagem


def _conferencia(sessao: Session, mensagem, referencia: date):
    from .servicos import caixa_email
    from .servicos import email_cobrancas as servico_email

    leitura = servico_email.ler(caixa_email.recebido_de(mensagem).texto)
    if not (leitura.linhas or leitura.incompletas):
        return None
    return servico_email.conferir(sessao, leitura, referencia, caixa_email.correcoes(mensagem))


def _linha_lida(lida) -> dict:
    return {"cliente": lida.cliente, "codigo": lida.codigo or None,
            "competencia": lida.competencia, "vencimento": _plano(lida.vencimento),
            "valor": _plano(lida.valor), "notas": lida.notas}


@_ferramenta(GRAVA)
def verificar_emails() -> dict:
    """Busca na caixa (Outlook/Gmail, pasta "Cobranças") os e-mails novos da conversa com o
    financeiro e guarda no sistema, como o botão "Verificar caixa"."""
    from .servicos import caixa_email
    from .servicos import email_cobrancas as servico_email

    with _sessao() as sessao:
        caixa = caixa_email.abrir_caixa(sessao)
        conta = caixa_email.conta(sessao).provedor
        ja_tenho = caixa_email.ja_baixados(sessao, conta)
        assunto = servico_email.remetente(sessao).assunto
    try:   # a rede fica fora da sessão do banco
        resultado = caixa_email.verificar(caixa, conta, ja_tenho, assunto)
    except ErroDeNegocio as falha:
        raise ValueError(str(falha)) from falha
    with _sessao(gravar=True) as sessao:
        novas = caixa_email.guardar(sessao, resultado.conta, resultado.mensagens)
        caixa_email.registrar_verificacao(sessao)
        return {"novos": len(novas),
                "emails": [{"id": m.id, "assunto": m.assunto, "de": m.de,
                            "recebido_em": _plano(m.recebido_em)} for m in novas]}


@_ferramenta(LEITURA)
def listar_emails(limite: int = 20, so_nao_respondidos: bool = False) -> list[dict]:
    """Os e-mails da conversa com o financeiro guardados no sistema, do mais novo ao mais
    antigo (recebidos e enviados daqui)."""
    from .servicos import caixa_email

    with _sessao() as sessao:
        return [
            {"id": m.id, "assunto": m.assunto, "de": m.de, "para": m.para,
             "recebido_em": _plano(m.recebido_em), "enviado_por_voce": m.enviada,
             "lido": m.lida_em is not None, "respondido_em": _plano(m.respondida_em),
             "origem": m.conta}
            for m in caixa_email.listar(sessao, limite * 3)
            if not (so_nao_respondidos and (m.enviada or m.respondida_em))
        ][:limite]


@_ferramenta(GRAVA)
def ler_email(email_id: int, data_referencia: str | None = None) -> dict:
    """Abre um e-mail do financeiro (marca como lido) e já confere a lista dele com o
    sistema: quem continua em aberto, quem saiu da lista (provavelmente pagou: candidato a
    baixa), quem já está pago e as linhas que não bateram com nenhum honorário."""
    from .servicos import caixa_email

    with _sessao(gravar=True) as sessao:
        mensagem = _email_guardado(sessao, email_id)
        caixa_email.marcar_lido(sessao, mensagem)
        dados = {
            "id": mensagem.id, "assunto": mensagem.assunto, "de": mensagem.de,
            "para": mensagem.para, "cc": mensagem.cc,
            "recebido_em": _plano(mensagem.recebido_em),
            "texto": caixa_email.recebido_de(mensagem).texto,
            "respondido_em": _plano(mensagem.respondida_em),
        }
        conferencia = _conferencia(sessao, mensagem, _data(data_referencia) or hoje())
        if conferencia is None:
            dados["conferencia"] = None
            return dados
        dados["conferencia"] = {
            "data_do_email": _plano(conferencia.data),
            "continuam": [dict(_linha_lida(c.lida), honorario_id=c.linha.honorario.id)
                          for c in conferencia.continuam],
            "sairam_da_lista": [_dados_linha(linha) for linha in conferencia.sairam],
            "ja_pagos_no_sistema": [dict(_linha_lida(c.lida), honorario_id=c.linha.honorario.id)
                                    for c in conferencia.pagos],
            "nao_encontradas": [_linha_lida(lida) for lida in conferencia.nao_encontradas],
        }
        return dados


@_ferramenta(GRAVA)
def baixar_quem_saiu_da_lista(
    email_id: int,
    honorario_ids: list[int],
    data_pagamento: str | None = None,
    com_juros: bool = True,
    forma_pagamento: str = "BOLETO",
) -> dict:
    """Dá baixa nos honorários que saíram da lista do financeiro (use os ids de
    ``sairam_da_lista`` de ler_email). Com juros: valor atualizado até a data do pagamento;
    sem juros: só o saldo, e o juros vira abono justificado pela lista. Tudo ou nada."""
    from .servicos import email_cobrancas as servico_email

    with _sessao(gravar=True) as sessao:
        mensagem = _email_guardado(sessao, email_id)
        conferencia = _conferencia(sessao, mensagem, hoje())
        data_do_email = conferencia.data if conferencia else hoje()
        honorarios = [_honorario(sessao, i) for i in honorario_ids]
        quando = _data(data_pagamento) or data_do_email
        itens = servico_email.previa_baixa(honorarios, quando, com_juros, data_do_email)
        quantos = servico_email.dar_baixa(
            sessao, itens, quando, _enum(FormaPagamento, forma_pagamento), data_do_email,
        )
        return {"baixados": quantos, "itens": [
            {"honorario_id": item.honorario.id, "cliente": item.cliente.nome,
             "valor": _plano(item.valor), "juros_cobrados": _plano(item.juros_cobrados)}
            for item in itens
        ]}


def _email_de_resposta(sessao: Session, email_id: int | None, referencia: date):
    """A resposta como a tela monta: à lista do e-mail, ou nova com os vencidos do sistema."""
    from .servicos import caixa_email
    from .servicos import email_cobrancas as servico_email

    if email_id is None:
        email = servico_email.montar(sessao, referencia)
        email.assunto = servico_email.remetente(sessao).assunto   # e-mail novo, sem "RE:"
        if not email.para:
            email.para = caixa_email.ultimo_remetente(sessao)
        return email, None
    mensagem = _email_guardado(sessao, email_id)
    conferencia = _conferencia(sessao, mensagem, referencia)
    if conferencia is None:
        raise ValueError("Esse e-mail não tem a lista de honorários para responder.")
    email = servico_email.responder(sessao, conferencia, referencia,
                                    caixa_email.recebido_de(mensagem))
    return email, mensagem


def _com_introducao(email, introducao: str) -> tuple[str, str]:
    from html import escape

    from .servicos import email_cobrancas as servico_email

    html, texto = servico_email.html(email), servico_email.texto(email)
    if introducao.strip():
        paragrafos = "".join(f"<p>{escape(p)}</p>" for p in introducao.strip().split("\n\n"))
        html = paragrafos + html
        texto = introducao.strip() + "\n\n" + texto
    return html, texto


@_ferramenta(LEITURA)
def montar_resposta_financeiro(
    email_id: int | None = None, introducao: str = "", data_referencia: str | None = None
) -> dict:
    """Monta (sem enviar) a resposta ao financeiro: a lista dele sem quem saiu, com o
    andamento das cobranças por cliente. Sem email_id, um e-mail novo com os vencidos do
    sistema. Devolve para/cc/assunto, o corpo em HTML e texto e, quando o e-mail veio do
    Outlook, o id dele (outlook_message_id) para responder ou criar rascunho por outro meio."""
    with _sessao() as sessao:
        email, mensagem = _email_de_resposta(sessao, email_id, _data(data_referencia) or hoje())
        html, texto = _com_introducao(email, introducao)
        return {
            "para": email.para, "cc": email.cc, "assunto": email.assunto,
            "em_resposta_a": email.em_resposta_a or None,
            "outlook_message_id": (mensagem.ref_provedor or None) if mensagem else None,
            "html": html, "texto": texto,
        }


@_ferramenta(GRAVA)
def responder_financeiro(
    email_id: int | None = None,
    modo: str = "rascunho",
    introducao: str = "",
    para: str | None = None,
    cc: str | None = None,
    assunto: str | None = None,
    com_assinatura: bool = True,
    abrir_rascunho: bool = True,
) -> dict:
    """Responde ao financeiro com a lista atualizada (a mesma de montar_resposta_financeiro).

    modo="enviar": envia pela conta configurada no sistema (Outlook/Gmail), citando o
    e-mail dele, e guarda nos enviados — não dá para desfazer.
    modo="rascunho": grava um .eml ligado à conversa e (com abrir_rascunho) abre no
    Outlook, pronto para revisar e enviar. Nada sai sem você clicar em Enviar.
    """
    from .config import caminhos
    from .servicos import caixa_email
    from .servicos import email_cobrancas as servico_email

    if modo not in ("enviar", "rascunho"):
        raise ValueError('modo: "enviar" ou "rascunho".')
    with _sessao(gravar=True) as sessao:
        email, mensagem = _email_de_resposta(sessao, email_id, hoje())
        email.para = email.para if para is None else para
        email.cc = email.cc if cc is None else cc
        email.assunto = email.assunto if assunto is None else assunto
        html, texto = _com_introducao(email, introducao)

        if modo == "rascunho":
            bruto = servico_email.eml(email)
            if introducao.strip():   # o .eml é montado do e-mail; a introdução vai junto
                from email import policy
                from email.parser import BytesParser

                rascunho = BytesParser(policy=policy.default).parsebytes(bruto)
                rascunho.get_body(("plain",)).set_content(texto)
                rascunho.get_body(("html",)).set_content(html, subtype="html")
                bruto = bytes(rascunho)
            destino = caminhos.pasta_exportacoes() / \
                f"resposta-cobrancas-{email.referencia:%Y-%m-%d}.eml"
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(bruto)
            if abrir_rascunho:
                _abrir(str(destino))
            return {"rascunho": str(destino), "para": email.para, "assunto": email.assunto}

        if mensagem is not None and mensagem.conta not in (
            caixa_email.GMAIL, caixa_email.IMAP, caixa_email.MICROSOFT,
        ):
            raise ValueError("Esse e-mail veio de arquivo: use modo=\"rascunho\".")
        caixa = caixa_email.abrir_caixa(sessao)
        resposta = caixa_email.Resposta(
            para=email.para, cc=email.cc, assunto=email.assunto, html=html, texto=texto,
            assinatura=caixa_email.assinatura(sessao) if com_assinatura else b"",
        )
        if mensagem is None:
            enviada = caixa.enviar_novo(resposta)
            caixa_email.registrar_nova_enviada(sessao, caixa_email.conta(sessao).provedor,
                                               enviada)
        else:
            enviada = caixa.responder(caixa_email.original_de(mensagem), resposta)
            caixa_email.registrar_enviada(sessao, mensagem, enviada)
        return {"enviado": True, "para": email.para, "cc": email.cc, "assunto": email.assunto}


# --------------------------------------------------------------------- WhatsApp
def _abrir(alvo: str) -> None:
    """Abre link ou arquivo no computador (WhatsApp, Outlook), como um clique."""
    if sys.platform == "win32":
        import os

        os.startfile(alvo)   # noqa: S606 - é o comportamento pedido: abrir no Windows
        return
    import webbrowser

    if not webbrowser.open(alvo):
        raise ValueError(f"Não consegui abrir {alvo}.")


def _app_grafico():
    """Qt sem janela, para desenhar a imagem de cobrança e usar a área de transferência."""
    import os

    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.instance() is None:
        if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") \
                and not os.environ.get("WAYLAND_DISPLAY"):
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _app_grafico.app = QGuiApplication(["financeiro-mcp"])
    return QGuiApplication.instance()


def _imagem_de_cobranca(sessao: Session, selecao, nome: str):
    """Gera o PNG da imagem de cobrança (o mesmo da tela) na pasta de exportações."""
    from .config import caminhos
    from .servicos import imagem_cobranca
    from .ui.comum.imagem_cobranca import renderizar

    _app_grafico()
    dados = imagem_cobranca.montar(sessao, selecao)
    texto_svg = imagem_cobranca.caminho_fundo(sessao).read_text(encoding="utf-8")
    imagem = renderizar(texto_svg, dados)
    destino = caminhos.pasta_exportacoes() / f"{nome}.png"
    destino.parent.mkdir(parents=True, exist_ok=True)
    if not imagem.save(str(destino), "PNG"):
        raise ValueError(f"Não consegui salvar a imagem em {destino}.")
    return imagem, destino


def _copiar_imagem(imagem, arquivo) -> None:
    """Põe a imagem na área de transferência, para colar no WhatsApp com Ctrl+V.

    No Windows vai por um PowerShell à parte: a área de transferência do Qt depende do
    laço de mensagens, que o servidor (sem janela) não tem; o .NET copia e deixa a
    imagem lá mesmo depois de terminar.
    """
    if sys.platform != "win32":
        _app_grafico().clipboard().setImage(imagem)
        return
    import subprocess

    caminho = str(arquivo).replace("'", "''")
    script = ("Add-Type -AssemblyName System.Windows.Forms, System.Drawing; "
              f"$img = [System.Drawing.Image]::FromFile('{caminho}'); "
              "[System.Windows.Forms.Clipboard]::SetImage($img); $img.Dispose()")
    subprocess.run(
        ["powershell", "-NoProfile", "-STA", "-Command", script],
        check=True, timeout=30, capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


@_ferramenta(GRAVA)
def cobrar_por_whatsapp(
    cliente_id: int,
    honorario_ids: list[int] | None = None,
    contato_id: int | None = None,
    texto: str | None = None,
    chave_pix_no_fim: bool = True,
    com_imagem: bool = True,
    abrir: bool = True,
    registrar: bool = False,
) -> dict:
    """Prepara a cobrança no WhatsApp do cliente (telefone do contato principal, ou do
    contato_id): a mensagem do modelo (ou ``texto``) com a chave Pix sozinha na última
    linha — para o cliente copiar, já que da imagem não dá — e abre o WhatsApp com tudo
    escrito. Com imagem, a imagem de cobrança (com o QR do Pix) fica copiada: no WhatsApp,
    Ctrl+V cola a imagem. O WhatsApp não deixa enviar sozinho: quem aperta Enviar é você.
    ``registrar`` grava a cobrança (só quando ela for de fato enviada)."""
    from .servicos import configuracoes as servico_config

    with _sessao(gravar=registrar) as sessao:
        c = _cliente(sessao, cliente_id)
        referencia = hoje()
        linhas = [_linha(sessao, i, referencia) for i in honorario_ids] if honorario_ids \
            else cobrancas.linhas_em_aberto_do_cliente(sessao, cliente_id, referencia)
        linhas = [linha for linha in linhas if linha.honorario.status.cobravel]
        if not linhas:
            raise ValueError(f"{c.nome} não tem honorário em aberto para cobrar.")
        contato = next((x for x in c.contatos if x.id == contato_id), None) if contato_id \
            else c.contato_principal
        if contato_id and contato is None:
            raise ValueError(f"O contato {contato_id} não é de {c.nome}.")
        selecao = cobrancas.Selecao(cliente=c, linhas=list(linhas), contato=contato)
        mensagem = (texto or cobrancas.gerar_texto(sessao, selecao)).strip()

        recebedor = servico_config.recebedor(sessao)
        if chave_pix_no_fim and recebedor.chave:
            ultima = mensagem.splitlines()[-1].strip() if mensagem else ""
            if ultima != recebedor.chave.strip():
                mensagem += f"\n\n{recebedor.chave.strip()}"

        link = cobrancas.link_whatsapp(sessao, contato, mensagem)
        resultado = {"cliente": c.nome, "telefone": contato.telefone if contato else None,
                     "contato": contato.tratamento_ou_nome if contato else None,
                     "mensagem": mensagem, "link": link, "imagem": None,
                     "total": _plano(selecao.total)}
        if com_imagem:
            imagem, destino = _imagem_de_cobranca(
                sessao, selecao, f"cobranca_{c.codigo}_{referencia:%Y-%m-%d}")
            try:
                _copiar_imagem(imagem, destino)
                resultado["imagem_copiada"] = True
            except Exception as falha:  # noqa: BLE001 - a imagem fica salva do mesmo jeito
                resultado["imagem_copiada"] = False
                resultado["aviso"] = f"Não consegui copiar a imagem ({falha}); ela está salva."
            resultado["imagem"] = str(destino)
        if abrir:
            _abrir(link)
        if registrar:
            cobrancas.registrar(sessao, selecao, texto=mensagem, canal=Canal.WHATSAPP)
            resultado["cobranca_registrada"] = True
        return resultado


def main() -> None:
    # stdout é o canal do protocolo: nada de print; erros vão para o stderr
    try:
        mcp.run()
    except KeyboardInterrupt:
        pass
    except Exception as falha:  # noqa: BLE001
        print(f"Servidor MCP parou: {falha}", file=sys.stderr)
        raise SystemExit(1) from falha


if __name__ == "__main__":
    main()
