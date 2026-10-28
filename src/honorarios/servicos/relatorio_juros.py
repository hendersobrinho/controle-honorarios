"""PDF da análise de juros de um cliente, para compartilhar.

Mostra o mesmo que a tela: original + juros = pago, o trabalho para receber, a
explicação, os cenários (com o escolhido destacado), o cenário honorário por
honorário e o histórico dos pagamentos. É um documento interno: traz a leitura
do comportamento do cliente, que não é texto para mandar a ele.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ..dominio.valores import ZERO, formatar_data, formatar_moeda, hoje
from . import analise_juros as analise_servico
from .analise_juros import AnaliseJuros, Cenario, percentual
from .pdf_relatorio import AZUL, BORDA, VERDE, RelatorioPdf
from .pdf_relatorio import texto as _texto


def _sinal(valor) -> str:
    if valor == 0:
        return "—"
    return ("+ " if valor > 0 else "- ") + formatar_moeda(abs(valor))


def _dias(quantidade: int) -> str:
    return f"{quantidade} dia" if quantidade == 1 else f"{quantidade} dias"


def _rotulo(honorario) -> str:
    competencia = honorario.competencia_rotulo or honorario.descricao
    tipo = honorario.tipo.nome
    if not competencia:
        return tipo
    if competencia.startswith(tipo):
        return competencia
    return f"{tipo} · {competencia}"


def _periodo(analise: AnaliseJuros) -> str:
    if analise.desde is None:
        return f"todo o histórico até {formatar_data(analise.ate)}"
    return f"pagos de {formatar_data(analise.desde)} a {formatar_data(analise.ate)}"


def analise_cliente_pdf(
    analise: AnaliseJuros,
    cenario_escolhido: Cenario | None,
    recebedor,
    destino: Path,
    gerado_em: date | None = None,
    graficos: dict[str, Path] | None = None,
) -> Path:
    """Gera o PDF da análise de um cliente e devolve o caminho.

    ``graficos``: os gráficos da tela como imagem (chaves ``comparacao``,
    ``atrasos``, ``cenarios``, ``pagos_cenario``, ``abertos_cenario``). Com eles o
    PDF mostra o mesmo que a tela; sem eles, sai em tabelas.
    """
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

    if analise.cliente is None or not analise.honorarios:
        raise ValueError("A análise precisa ser de um cliente com honorários pagos.")
    cliente = analise.cliente
    gerado_em = gerado_em or hoje()
    r = RelatorioPdf(
        "Análise de juros", f"{cliente.codigo} – {cliente.nome}", recebedor, gerado_em
    )
    cor, estilo, p, tabela = r.cor, r.estilo, r.p, r.tabela
    largura_util = r.largura_util
    taxa = analise.taxa_atual or ZERO
    corpo = [
        *r.inicio(),
        p(
            f"Período: {_periodo(analise)} · {len(analise.honorarios)} honorário(s) pago(s) · "
            f"juros atual: <b>{formatar_moeda(taxa)} ao dia</b>",
            "fraco",
        ),
        Spacer(1, 10),
    ]

    # ------------------------------------------------- original + juros = pago
    def caixa(rotulo: str, valor: str, cor_valor: str = AZUL) -> list:
        return [
            p(rotulo, "rotulo"),
            Paragraph(valor, ParagraphStyle("cx", parent=estilo["valor"], fontSize=15,
                                            leading=18, textColor=cor(cor_valor))),
        ]

    sinal = ParagraphStyle("sn", parent=estilo["valor"], alignment=1, fontSize=16)
    equacao = Table(
        [[
            caixa("Valor original", formatar_moeda(analise.original)),
            Paragraph("+", sinal),
            caixa("Juros recebido", formatar_moeda(analise.juros_cobrados), VERDE),
            Paragraph("=", sinal),
            caixa("Total pago", formatar_moeda(analise.recebido)),
        ]],
        colWidths=[largura_util * 0.3, largura_util * 0.05, largura_util * 0.3,
                   largura_util * 0.05, largura_util * 0.3],
    )
    equacao.setStyle(TableStyle([
        ("BOX", (0, 0), (0, 0), 0.6, cor(BORDA)),
        ("BOX", (2, 0), (2, 0), 0.6, cor(BORDA)),
        ("BOX", (4, 0), (4, 0), 0.6, cor(BORDA)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    rodape_equacao = f"+{percentual(analise.acrescimo, 2)} sobre o original"
    if analise.abono > 0:
        rodape_equacao += f" · {formatar_moeda(analise.abono)} de juros abonados"
    corpo += [equacao, Spacer(1, 3), p(rodape_equacao, "fraco")]

    # ------------------------------------------------- o trabalho para receber
    graficos = graficos or {}
    indicadores = analise_servico.indicadores_de_trabalho(analise, analise.geral)
    if "comparacao" in graficos:
        # o gráfico "ele × a média" substitui a grade; ficam os dois que não cabem nele
        grade = KeepTogether([
            r.p("Comparado com a média dos clientes; o traço é a média.", "fraco"),
            Spacer(1, 4),
            r.imagem(graficos["comparacao"]),
            Spacer(1, 6),
            r.grade([
                (rotulo, *indicadores[chave])
                for chave, rotulo, _ in analise_servico.INDICADORES_TRABALHO
                if chave in ("taxa", "hoje")
            ], colunas=2),
        ])
    else:
        grade = r.grade([
            (rotulo, *indicadores[chave])
            for chave, rotulo, _ in analise_servico.INDICADORES_TRABALHO
        ])
    corpo += [p("O trabalho que deu para receber", "secao"), grade]
    if "atrasos" in graficos:
        corpo.append(KeepTogether([
            p("Atraso honorário por honorário", "secao"),
            p("A barra é quantos dias atrasou; cada ponto é uma cobrança feita até ele pagar.",
              "fraco"),
            Spacer(1, 4),
            r.imagem(graficos["atrasos"]),
        ]))

    # ---------------------------------------------------------------- leitura
    frases = analise_servico.explicar_cliente(analise)
    corpo.append(KeepTogether([   # título e frases juntos: uma frase solta no pé não ajuda
        p("Explicando", "secao"),
        *[Paragraph(f"•&nbsp;&nbsp;{_texto(frase)}", estilo["normal"]) for frase in frases],
    ]))

    # --------------------------------------------------------------- cenários
    cenarios = analise_servico.cenarios(analise)
    escolhido = None
    if cenario_escolhido is not None:
        rotulos = [c.rotulo for c in cenarios]
        if cenario_escolhido.rotulo in rotulos:
            escolhido = rotulos.index(cenario_escolhido.rotulo)
        else:   # o valor testado na tela entra como linha a mais
            cenarios.append(cenario_escolhido)
            escolhido = len(cenarios) - 1
    linhas = [["Cenário", "Juros ao dia", "Juros no período", "A mais no período",
               "A mais por mês, daqui para frente"]]
    for c in cenarios:
        linhas.append([
            _texto(c.rotulo),
            formatar_moeda(c.taxa_dia) if c.taxa_dia is not None else "",
            formatar_moeda(c.juros_no_periodo),
            _sinal(c.a_mais),
            _sinal(c.a_mais_por_mes),
        ])
    # título, tabela e nota juntos: a nota sozinha no topo de outra página não diz nada
    corpo.append(KeepTogether([
        p("Cenários: e se o juros dele fosse outro?", "secao"),
        *([r.imagem(graficos["cenarios"]), Spacer(1, 6)] if "cenarios" in graficos else []),
        tabela(linhas, [largura_util * f for f in (0.28, 0.15, 0.17, 0.17, 0.23)],
               destaque=None if escolhido is None else escolhido + 1),
        Spacer(1, 3),
        p(
            "Cada cenário repete os mesmos atrasos e a mesma proporção de abono do "
            "período, só trocando a taxa. Mudança de juros nunca é retroativa: o juros "
            "que já correu não muda.",
            "fraco",
        ),
    ]))

    # -------------------------------------------- cenário honorário por honorário
    if cenario_escolhido is not None:
        bloco = [p(f"Cenário honorário por honorário: {_texto(cenario_escolhido.rotulo)}",
                   "secao")]
        if cenario_escolhido.atual:
            bloco.append(p(f"Como está hoje: {formatar_moeda(taxa)} ao dia.", "fraco"))
        elif cenario_escolhido.sem_abono:
            bloco.append(p(f"Mesma taxa ({formatar_moeda(taxa)} ao dia), cobrando o juros "
                           "devido inteiro.", "fraco"))
        else:
            bloco.append(p(
                f"Juros de <b>{formatar_moeda(cenario_escolhido.taxa_dia or ZERO)}</b> ao dia "
                f"em vez de {formatar_moeda(taxa)}, com os mesmos atrasos e o mesmo abono.",
                "fraco",
            ))
        pagos = [
            linha for linha in analise_servico.por_honorario(analise, cenario_escolhido)
            if linha.item.com_atraso
        ]
        if pagos and "pagos_cenario" in graficos:
            juros = sum((linha.item.juros_cobrados for linha in pagos), start=ZERO)
            no_cenario = sum((linha.juros_cenario for linha in pagos), start=ZERO)
            bloco += [
                Spacer(1, 4), p("<b>Honorários pagos: o juros que pagou e o do cenário</b>"),
                r.imagem(graficos["pagos_cenario"]),
                p(f"Total de {len(pagos)} honorário(s): {formatar_moeda(juros)} -> "
                  f"{formatar_moeda(no_cenario)} ({_sinal(no_cenario - juros)})", "fraco"),
            ]
        elif pagos:
            linhas = [["Honorário", "Venceu", "Pago em", "Atraso", "Juros pago",
                       "Juros no cenário", "Diferença", "Total no cenário"]]
            for linha in pagos:
                item = linha.item
                linhas.append([
                    Paragraph(_texto(_rotulo(item.honorario)), estilo["celula"]),
                    formatar_data(item.honorario.vencimento),
                    formatar_data(item.pago_em),
                    _dias(item.dias_atraso),
                    formatar_moeda(item.juros_cobrados),
                    formatar_moeda(linha.juros_cenario),
                    _sinal(linha.diferenca),
                    formatar_moeda(linha.total_cenario),
                ])
            juros = sum((linha.item.juros_cobrados for linha in pagos), start=ZERO)
            no_cenario = sum((linha.juros_cenario for linha in pagos), start=ZERO)
            total = sum((linha.total_cenario for linha in pagos), start=ZERO)
            linhas.append([f"Total ({len(pagos)})", "", "",
                           _dias(sum(linha.item.dias_atraso for linha in pagos)),
                           formatar_moeda(juros), formatar_moeda(no_cenario),
                           _sinal(no_cenario - juros), formatar_moeda(total)])
            bloco += [
                Spacer(1, 4), p("<b>Pagos com atraso no período</b>"),
                tabela(linhas, [largura_util * f for f in
                                (0.22, 0.1, 0.1, 0.08, 0.11, 0.13, 0.12, 0.14)], total=True),
            ]
        else:
            bloco.append(p("Nenhum honorário pago com atraso no período: o cenário não muda "
                           "nada no que já foi pago.", "normal"))
        # um KeepTogether por parte, sem um dentro do outro: aninhados, o reportlab
        # erra a altura e pula página à toa
        corpo.append(KeepTogether(bloco))
        atrasados = analise_servico.atrasados_no_cenario(analise, cenario_escolhido)
        if atrasados and "abertos_cenario" in graficos:
            corpo.append(KeepTogether([
                Spacer(1, 8),
                p("<b>Em atraso hoje: o juros de mais 30 dias, como está e no cenário</b>"),
                r.imagem(graficos["abertos_cenario"]),
                p("O juros que já correu não muda: a taxa nova só valeria da data da "
                  "mudança em diante.", "fraco"),
            ]))
        elif atrasados:
            linhas = [["Honorário", "Venceu", "Atraso", "Total hoje", "Juros/dia hoje",
                       "Juros/dia no cenário", "Em 30 dias", "Em 30 dias no cenário"]]
            for linha in atrasados:
                a = linha.atrasado
                linhas.append([
                    Paragraph(_texto(_rotulo(a.honorario)), estilo["celula"]),
                    formatar_data(a.honorario.vencimento),
                    _dias(a.dias_atraso),
                    formatar_moeda(a.total),
                    formatar_moeda(a.juros_por_dia),
                    formatar_moeda(linha.juros_por_dia_cenario),
                    formatar_moeda(linha.total_projetado),
                    formatar_moeda(linha.total_projetado_cenario),
                ])
            corpo.append(KeepTogether([
                Spacer(1, 8), p("<b>Em atraso hoje: daqui para frente</b>"),
                tabela(linhas, [largura_util * f for f in
                                (0.22, 0.1, 0.08, 0.12, 0.11, 0.13, 0.11, 0.13)]),
                Spacer(1, 3),
                p("O juros que já correu não muda: a taxa nova só valeria da data da "
                  "mudança em diante. \"Em 30 dias\" é o total se ele pagar daqui a "
                  "30 dias.", "fraco"),
            ]))

    # ------------------------------------------------- histórico dos pagamentos
    linhas = [["Honorário", "Venceu", "Pago em", "Atraso", "Cobranças", "Original",
               "Juros pago", "Abonado", "Pago"]]
    for item in analise.honorarios:
        linhas.append([
            Paragraph(_texto(_rotulo(item.honorario)), estilo["celula"]),
            formatar_data(item.honorario.vencimento),
            formatar_data(item.pago_em),
            _dias(item.dias_atraso) if item.com_atraso else "em dia",
            str(item.cobrancas) if item.cobrancas else "—",
            formatar_moeda(item.original),
            formatar_moeda(item.juros_cobrados) if item.juros_cobrados else "—",
            formatar_moeda(item.abono) if item.abono else "—",
            formatar_moeda(item.pago),
        ])
    linhas.append([f"Total ({len(analise.honorarios)})", "", "",
                   _dias(analise.dias_em_atraso), str(analise.cobrancas),
                   formatar_moeda(analise.original), formatar_moeda(analise.juros_cobrados),
                   formatar_moeda(analise.abono), formatar_moeda(analise.recebido)])
    corpo.append(KeepTogether([   # tabela maior que a página quebra normalmente
        p("Histórico dos pagamentos", "secao"),
        tabela(linhas, [largura_util * f for f in
                        (0.19, 0.1, 0.1, 0.08, 0.1, 0.12, 0.1, 0.09, 0.12)], total=True),
    ]))

    return r.salvar(corpo, destino, f"Análise de juros – {cliente.nome}")
