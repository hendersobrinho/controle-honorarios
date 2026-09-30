"""Gravação da importação no banco, depois da prévia aprovada.

Regras de honestidade com o dado antigo: a planilha não guardava data nem valor
do pagamento, então honorário pago entra congelado pelo valor do boleto e com
observação dizendo isso; cobrança virada de texto guarda o texto original.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...dominio.enums import Canal, ResultadoCobranca, StatusPagamento
from ...dominio.valores import FUSO_LOCAL, ZERO, hoje, normalizar_busca
from ...infra.modelos import (
    Cliente,
    Cobranca,
    CobrancaLote,
    FormaEnvio,
    Importacao,
    ImportacaoErro,
    TipoHonorario,
)
from .. import calculo
from .. import clientes as servico_clientes
from .. import honorarios as servico_honorarios
from ..erros import ErroDeNegocio
from .leitor import ABA_RECALL, ClienteLido, Leitura, LinhaLida, Problema

PISTAS_RESULTADO = (
    (ResultadoCobranca.PAGOU, ("pagou", "pagamento efetuado", "quitou")),
    (ResultadoCobranca.PEDIU_RENEGOCIACAO, ("parcel", "renegoci", "acordo")),
    (
        ResultadoCobranca.PROMETEU_PAGAR,
        ("ira pagar", "vai pagar", "prazo", "previsao", "pediu prazo", "irá pagar"),
    ),
    (ResultadoCobranca.CONTESTOU, ("contest", "nao reconhece", "discord")),
)


@dataclass
class Resultado:
    clientes_criados: int = 0
    clientes_existentes: int = 0
    honorarios_criados: int = 0
    honorarios_ignorados: int = 0
    cobrancas_criadas: int = 0
    avisos: list[Problema] = field(default_factory=list)
    importacao_id: int | None = None

    @property
    def resumo(self) -> str:
        return (
            f"{self.clientes_criados} cliente(s) criado(s) "
            f"({self.clientes_existentes} já existiam), "
            f"{self.honorarios_criados} honorário(s) e "
            f"{self.cobrancas_criadas} cobrança(s) importadas. "
            f"{self.honorarios_ignorados} linha(s) ignorada(s)."
        )


def _resultado_de(texto: str) -> ResultadoCobranca:
    alvo = normalizar_busca(texto)
    for resultado, pistas in PISTAS_RESULTADO:
        if any(pista in alvo for pista in pistas):
            return resultado
    return ResultadoCobranca.SEM_RESPOSTA


def _tipos_por_nome(sessao: Session) -> dict[str, TipoHonorario]:
    return {
        tipo.nome: tipo
        for tipo in sessao.scalars(select(TipoHonorario)).unique().all()
    }


def _formas_por_nome(sessao: Session) -> dict[str, FormaEnvio]:
    return {
        normalizar_busca(forma.nome): forma
        for forma in sessao.scalars(select(FormaEnvio)).all()
    }


def _cliente_existente(sessao: Session, lido: ClienteLido) -> Cliente | None:
    if lido.documento:
        achado = servico_clientes.por_documento(sessao, lido.documento)
        if achado:
            return achado
    if lido.codigo:
        return servico_clientes.por_codigo(sessao, lido.codigo)
    return None


def _codigo_livre(sessao: Session, base: str, usados: set[str]) -> str:
    codigo = (base or "").strip() or "IMP"
    tentativa = codigo
    contador = 2
    while tentativa in usados or servico_clientes.por_codigo(sessao, tentativa):
        tentativa = f"{codigo}-{contador}"
        contador += 1
    usados.add(tentativa)
    return tentativa


def _ja_importado(sessao: Session, cliente_id: int, tipo_id: int, linha: LinhaLida) -> bool:
    """Evita duplicar na reimportação o que não tem competência (avulsos).

    Com competência, o índice único do honorário já barra; sem ela, a comparação
    é por cliente, tipo, vencimento e valor.
    """
    from ...infra.modelos import Honorario

    if linha.competencia.ano or linha.competencia.mes:
        return False
    return bool(
        sessao.scalar(
            select(Honorario).where(
                Honorario.cliente_id == cliente_id,
                Honorario.tipo_id == tipo_id,
                Honorario.vencimento == linha.vencimento,
                Honorario.valor_original == linha.valor,
                Honorario.status != StatusPagamento.CANCELADO,
            )
        )
    )


def importar(
    sessao: Session,
    leitura: Leitura,
    criar_clientes: bool = True,
    importar_pagos: bool = True,
    importar_cobrancas: bool = True,
) -> Resultado:
    """Grava a leitura já revisada. Roda dentro da transação de quem chamou."""
    resultado = Resultado()
    registro = Importacao(
        arquivo=str(leitura.arquivo),
        aba="Controle Financeiro + IRPF + Recall",
        observacoes=leitura.resumo(),
    )
    sessao.add(registro)
    sessao.flush()
    resultado.importacao_id = registro.id

    for problema in leitura.todos_problemas():
        sessao.add(
            ImportacaoErro(
                importacao_id=registro.id,
                linha=problema.linha,
                aba=problema.aba,
                campo=problema.campo,
                valor=problema.valor[:500],
                gravidade=problema.gravidade,
                motivo=problema.motivo,
            )
        )

    # --- clientes
    tipos = _tipos_por_nome(sessao)
    formas = _formas_por_nome(sessao)
    codigos_usados: set[str] = set()
    mapa_clientes: dict[str, Cliente] = {}
    primeiro_vencimento: dict[str, object] = {}
    for linha in leitura.linhas:
        if linha.vencimento is None:
            continue
        atual = primeiro_vencimento.get(linha.chave_cliente)
        if atual is None or linha.vencimento < atual:
            primeiro_vencimento[linha.chave_cliente] = linha.vencimento

    for chave, lido in leitura.clientes.items():
        existente = _cliente_existente(sessao, lido)
        if existente is not None:
            mapa_clientes[chave] = existente
            resultado.clientes_existentes += 1
            continue
        if not criar_clientes:
            continue
        dados = servico_clientes.DadosCliente(
            codigo=_codigo_livre(sessao, lido.codigo, codigos_usados),
            nome=lido.nome,
            documento=lido.documento,
            tipo_pessoa=lido.tipo_pessoa,
            subtipo=lido.subtipo,
            juros_dia=lido.juros_dia if lido.juros_dia is not None else Decimal("0.00"),
            observacoes=(
                "Importado da planilha"
                + (" (lista de recall)" if lido.origem == ABA_RECALL else "")
            ),
            contatos=[],
        )
        try:
            criado = servico_clientes.criar(sessao, dados)
        except ErroDeNegocio as falha:
            sessao.add(
                ImportacaoErro(
                    importacao_id=registro.id,
                    aba=lido.origem,
                    campo="Cliente",
                    valor=f"{lido.codigo} – {lido.nome}",
                    gravidade="ERRO",
                    motivo=str(falha),
                )
            )
            continue
        vigencia = primeiro_vencimento.get(chave) or hoje()
        if criado.juros:
            criado.juros[0].vigencia_inicio = vigencia
            criado.juros[0].motivo = "Valor que estava na planilha"
        mapa_clientes[chave] = criado
        resultado.clientes_criados += 1
    sessao.flush()

    # --- honorários
    criados_por_linha: dict[int, object] = {}
    for linha in leitura.linhas:
        if not linha.importar or linha.bloqueada:
            resultado.honorarios_ignorados += 1
            continue
        cliente = mapa_clientes.get(linha.chave_cliente)
        if cliente is None:
            resultado.honorarios_ignorados += 1
            sessao.add(
                ImportacaoErro(
                    importacao_id=registro.id,
                    linha=linha.linha,
                    aba=linha.aba,
                    campo="Cliente",
                    valor=linha.nome,
                    gravidade="ERRO",
                    motivo="Cliente não foi criado: honorário não importado",
                )
            )
            continue
        if linha.status is StatusPagamento.PAGO and not importar_pagos:
            resultado.honorarios_ignorados += 1
            continue

        tipo = tipos.get(linha.tipo_honorario)
        if tipo is None:
            resultado.honorarios_ignorados += 1
            sessao.add(
                ImportacaoErro(
                    importacao_id=registro.id,
                    linha=linha.linha,
                    aba=linha.aba,
                    campo="Tipo de Faturamento",
                    valor=linha.tipo_honorario,
                    gravidade="ERRO",
                    motivo="Tipo de honorário não existe no cadastro",
                )
            )
            continue

        forma = formas.get(normalizar_busca(linha.forma_envio))
        observacoes = [linha.observacoes] if linha.observacoes else []
        if linha.status is StatusPagamento.PAGO:
            observacoes.append(
                "Importado como pago: a planilha não guardava data nem valor do "
                "pagamento, então o total foi congelado pelo valor do boleto."
            )
            if linha.forma_pagamento is not None:
                observacoes.append(f"Forma registrada na planilha: {linha.forma_pagamento.rotulo}.")

        if _ja_importado(sessao, cliente.id, tipo.id, linha):
            resultado.honorarios_ignorados += 1
            sessao.add(
                ImportacaoErro(
                    importacao_id=registro.id,
                    linha=linha.linha,
                    aba=linha.aba,
                    campo="Honorário",
                    valor=f"{linha.nome} {linha.descricao or linha.competencia.rotulo()}",
                    gravidade="AVISO",
                    motivo="Já existe lançamento igual: não importado de novo",
                )
            )
            continue

        dados = servico_honorarios.DadosHonorario(
            cliente_id=cliente.id,
            tipo_id=tipo.id,
            valor=linha.valor,
            vencimento=linha.vencimento,
            competencia=linha.competencia,
            descricao=linha.descricao,
            meio=linha.meio,
            forma_envio_id=forma.id if forma else None,
            situacao_envio=linha.situacao_envio,
            observacoes="\n".join(observacoes),
        )
        try:
            honorario = servico_honorarios.criar(sessao, dados)
        except ErroDeNegocio as falha:
            resultado.honorarios_ignorados += 1
            sessao.add(
                ImportacaoErro(
                    importacao_id=registro.id,
                    linha=linha.linha,
                    aba=linha.aba,
                    campo="Honorário",
                    valor=f"{linha.nome} {linha.competencia.rotulo()}",
                    gravidade="AVISO",
                    motivo=str(falha),
                )
            )
            continue

        honorario.origem_importacao_id = registro.id
        honorario.status = linha.status
        if linha.status is StatusPagamento.PAGO:
            honorario.saldo_aberto = ZERO
            honorario.total_congelado = linha.valor
        elif linha.status in (StatusPagamento.CANCELADO, StatusPagamento.RENEGOCIADO):
            honorario.saldo_aberto = ZERO
        if linha.situacao_envio.name == "ENVIADO":
            honorario.enviado_em = linha.vencimento
        criados_por_linha[id(linha)] = honorario
        resultado.honorarios_criados += 1
    sessao.flush()

    # --- cobranças (uma mensagem por cliente e data, como estava na planilha)
    if importar_cobrancas:
        lotes: dict[tuple[int, object], CobrancaLote] = {}
        for linha in leitura.linhas:
            honorario = criados_por_linha.get(id(linha))
            if honorario is None:
                continue
            for cobranca in linha.cobrancas:
                chave = (honorario.cliente_id, cobranca.quando, cobranca.texto)
                lote = lotes.get(chave)
                momento = datetime.combine(cobranca.quando, time(9, 0), tzinfo=FUSO_LOCAL)
                if lote is None:
                    lote = CobrancaLote(
                        cliente_id=honorario.cliente_id,
                        canal=Canal.WHATSAPP,
                        data_hora=momento,
                        texto_enviado="",
                        total_no_momento=ZERO,
                    )
                    sessao.add(lote)
                    sessao.flush()
                    lotes[chave] = lote
                atualizacao = calculo.atualizar(honorario, cobranca.quando)
                honorario.cobrancas.append(
                    Cobranca(
                        lote=lote,
                        data_hora=momento,
                        canal=Canal.WHATSAPP,
                        resultado=_resultado_de(cobranca.texto),
                        observacao=cobranca.texto,
                        origem_texto_planilha=cobranca.texto,
                        valor_atualizado_no_momento=atualizacao.total,
                    )
                )
                lote.total_no_momento += atualizacao.total
                resultado.cobrancas_criadas += 1
        sessao.flush()

    registro.clientes_criados = resultado.clientes_criados
    registro.honorarios_criados = resultado.honorarios_criados
    registro.cobrancas_criadas = resultado.cobrancas_criadas
    registro.linhas_ignoradas = resultado.honorarios_ignorados
    sessao.flush()
    return resultado
