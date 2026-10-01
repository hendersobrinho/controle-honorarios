"""PDF da análise de juros de um cliente, para compartilhar.

Mostra o mesmo que a tela: original + juros = pago, o trabalho para receber, a
explicação, os cenários (com o escolhido destacado), o cenário honorário por
honorário e o histórico dos pagamentos. É um documento interno: traz a leitura
do comportamento do cliente, que não é texto para mandar a ele.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from ..dominio.valores import ZERO, formatar_data, formatar_moeda, hoje
from . import analise_juros as analise_servico
from .analise_juros import AnaliseJuros, Cenario, percentual

AZUL = "#203461"
TEAL = "#4BBDCD"
LARANJA = "#F9B259"
FRACO = "#5B6577"
BORDA = "#D5DAE1"
FAIXA = "#EEF1F5"
VERDE = "#1F7A45"
VERMELHO = "#B03A2E"

# Com o fundo da cobrança como papel: o conteúdo vai num cartão branco entre o
# logo do topo e o do rodapé (medidas em pontos, página A4 de 595 × 842).
CARTAO_TOPO = 120        # distância do topo da página até o cartão
CARTAO_BASE = 84         # distância do pé da página até o fim do cartão
CARTAO_LADO = 28
RESPIRO = 18             # do cartão até o texto


def _texto(valor: str) -> str:
    """Helvetica (a fonte padrão do PDF) não tem seta nem sinal de menos tipográfico."""
    return escape(str(valor)).replace("→", "->").replace("−", "-")


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
    fundo: Path | None = None,
) -> Path:
    """Gera o PDF da análise de um cliente e devolve o caminho.

    ``fundo`` é a imagem da página (a base do fundo da cobrança, já no formato
    A4). Com ele, o título vai sobre o fundo e o conteúdo num cartão branco.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    if analise.cliente is None or not analise.honorarios:
        raise ValueError("A análise precisa ser de um cliente com honorários pagos.")
    cliente = analise.cliente
    gerado_em = gerado_em or hoje()
    cor = colors.HexColor
    if fundo is not None:
        margem_lado = CARTAO_LADO + RESPIRO
        margem_topo = CARTAO_TOPO + RESPIRO
        margem_base = CARTAO_BASE + RESPIRO + 14   # + a linha do rodapé, dentro do cartão
    else:
        margem_lado, margem_topo, margem_base = 18 * mm, 15 * mm, 16 * mm
    largura_util = A4[0] - 2 * margem_lado

    base = getSampleStyleSheet()["Normal"]
    estilo = {
        "titulo": ParagraphStyle("t", parent=base, fontName="Helvetica-Bold", fontSize=18,
                                 leading=22, textColor=cor(AZUL)),
        "cliente": ParagraphStyle("c", parent=base, fontName="Helvetica-Bold", fontSize=12.5,
                                  leading=16, textColor=cor(AZUL)),
        "fraco": ParagraphStyle("f", parent=base, fontSize=8.5, leading=11,
                                textColor=cor(FRACO)),
        "secao": ParagraphStyle("s", parent=base, fontName="Helvetica-Bold", fontSize=11.5,
                                leading=14, textColor=cor(AZUL), spaceBefore=12,
                                spaceAfter=6),
        "normal": ParagraphStyle("n", parent=base, fontSize=9, leading=12.5),
        "rotulo": ParagraphStyle("r", parent=base, fontSize=7.5, leading=9,
                                 textColor=cor(FRACO)),
        "valor": ParagraphStyle("v", parent=base, fontName="Helvetica-Bold", fontSize=13,
                                leading=16, textColor=cor(AZUL)),
        "nota": ParagraphStyle("o", parent=base, fontSize=7.2, leading=9,
                               textColor=cor(FRACO)),
        "celula": ParagraphStyle("e", parent=base, fontSize=8, leading=10),
        "cabecalho": ParagraphStyle("h", parent=base, fontName="Helvetica-Bold", fontSize=7.3,
                                    leading=8.6, textColor=cor(FRACO), alignment=2),
        "cabecalho_esq": ParagraphStyle("he", parent=base, fontName="Helvetica-Bold",
                                        fontSize=7.3, leading=8.6, textColor=cor(FRACO)),
    }

    def p(texto: str, nome: str = "normal") -> Paragraph:
        return Paragraph(texto, estilo[nome])

    def tabela(linhas, larguras, total: bool = False, destaque: int | None = None) -> Table:
        """Tabela no padrão do relatório: cabeçalho cinza, números à direita.

        O cabeçalho vira parágrafo para quebrar linha: título longo não invade a
        coluna vizinha.
        """
        linhas = [[
            Paragraph(titulo, estilo["cabecalho_esq" if coluna == 0 else "cabecalho"])
            for coluna, titulo in enumerate(linhas[0])
        ]] + list(linhas[1:])
        t = Table(linhas, colWidths=larguras, hAlign="LEFT", repeatRows=1)
        regras = [
            ("BACKGROUND", (0, 0), (-1, 0), cor(FAIXA)),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, 0), (-1, 0), cor(FRACO)),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, cor(BORDA)),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ]
        if total:
            regras += [
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, cor(FRACO)),
            ]
        if destaque is not None:
            regras += [
                ("BACKGROUND", (0, destaque), (-1, destaque), cor("#E6F6F8")),
                ("FONTNAME", (0, destaque), (-1, destaque), "Helvetica-Bold"),
            ]
        t.setStyle(TableStyle(regras))
        return t

    taxa = analise.taxa_atual or ZERO
    corpo = []

    # ---------------------------------------------------------------- topo
    topo = Table(
        [[
            [p("Análise de juros", "titulo"),
             p(f"{_texto(cliente.codigo)} – {_texto(cliente.nome)}", "cliente")],
            [p(_texto(recebedor.razao_social), "fraco"),
             p(f"Gerado em {formatar_data(gerado_em)}", "fraco")],
        ]],
        colWidths=[largura_util * 0.66, largura_util * 0.34],
    )
    topo.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, 0), 2, cor(TEAL)),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
    ]))
    corpo += [
        *([] if fundo is not None else [topo]),   # com fundo, o título vai no papel
        Spacer(1, 6),
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
    indicadores = analise_servico.indicadores_de_trabalho(analise, analise.geral)
    celulas = []
    for chave, rotulo, _ in analise_servico.INDICADORES_TRABALHO:
        valor, nota = indicadores[chave]
        celulas.append([p(rotulo, "rotulo"), p(_texto(valor), "valor"), p(_texto(nota), "nota")])
    grade = Table(
        [celulas[0:3], celulas[3:6]],
        colWidths=[largura_util / 3] * 3,
    )
    grade.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, cor(BORDA)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
    ]))
    corpo += [p("O trabalho que deu para receber", "secao"), grade]

    # ---------------------------------------------------------------- leitura
    frases = analise_servico.explicar_cliente(analise)
    corpo.append(p("Explicando", "secao"))
    for frase in frases:
        corpo.append(Paragraph(f"•&nbsp;&nbsp;{_texto(frase)}", estilo["normal"]))

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
        if pagos:
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
        if atrasados:
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

    # ------------------------------------------------------------ rodapé
    def pagina_com_fundo(canvas, documento) -> None:
        largura, altura = A4
        canvas.saveState()
        canvas.drawImage(str(fundo), 0, 0, largura, altura)
        canvas.setFillColor(colors.white)
        canvas.roundRect(
            CARTAO_LADO, CARTAO_BASE, largura - 2 * CARTAO_LADO,
            altura - CARTAO_TOPO - CARTAO_BASE, 14, stroke=0, fill=1,
        )
        # título no fundo, como na imagem de cobrança (à esquerda do logo do topo)
        canvas.setFillColor(cor(AZUL))
        canvas.setFont("Helvetica-Bold", 22)
        canvas.drawString(CARTAO_LADO + 14, altura - 58, "Análise de juros")
        canvas.setFont("Helvetica-Bold", 11)
        nome = f"{cliente.codigo} – {cliente.nome}"
        while canvas.stringWidth(nome, "Helvetica-Bold", 11) > 400 and len(nome) > 10:
            nome = nome[:-2].rstrip() + "…"
        canvas.drawString(CARTAO_LADO + 14, altura - 78, nome)
        canvas.setFillColor(cor(TEAL))
        canvas.roundRect(CARTAO_LADO + 14, altura - 92, 40, 3.5, 1.7, stroke=0, fill=1)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(cor(FRACO))
        canvas.drawString(
            margem_lado, CARTAO_BASE + 12,
            f"Documento interno · {recebedor.razao_social[:50]} · gerado em "
            f"{formatar_data(gerado_em)}",
        )
        canvas.drawRightString(largura - margem_lado, CARTAO_BASE + 12,
                               f"Página {documento.page}")
        canvas.restoreState()

    def rodape(canvas, documento) -> None:
        canvas.saveState()
        canvas.setFillColor(cor(LARANJA))
        canvas.rect(0, 0, 4 * mm, A4[1] / 3, stroke=0, fill=1)
        canvas.setFillColor(cor(TEAL))
        canvas.rect(0, A4[1] / 3, 4 * mm, A4[1] / 3, stroke=0, fill=1)
        canvas.setFillColor(cor(AZUL))
        canvas.rect(0, 2 * A4[1] / 3, 4 * mm, A4[1] / 3, stroke=0, fill=1)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(cor(FRACO))
        canvas.drawString(
            18 * mm, 9 * mm,
            f"Documento interno · {cliente.nome[:60]} · gerado em {formatar_data(gerado_em)}",
        )
        canvas.drawRightString(A4[0] - 18 * mm, 9 * mm, f"Página {documento.page}")
        canvas.restoreState()

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    documento = SimpleDocTemplate(
        str(destino),
        pagesize=A4,
        leftMargin=margem_lado,
        rightMargin=margem_lado,
        topMargin=margem_topo,
        bottomMargin=margem_base,
        title=f"Análise de juros – {cliente.nome}",
        author=recebedor.razao_social,
    )
    pagina = pagina_com_fundo if fundo is not None else rodape
    documento.build(corpo, onFirstPage=pagina, onLaterPages=pagina)
    return destino
