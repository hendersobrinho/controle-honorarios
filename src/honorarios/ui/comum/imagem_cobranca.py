"""Desenha a imagem de cobrança: fundo SVG + lista de honorários + QR code.

O SVG é renderizado em vetor na largura final, então o fundo não perde
qualidade. A lista e o QR são desenhados por cima, dentro dos retângulos
``lista`` e ``qrcode`` do próprio SVG.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtSvg import QSvgRenderer

from ...servicos.erros import ErroDeValidacao
from ...servicos.imagem_cobranca import (
    DadosImagem,
    LinhaImagem,
    para_imagem,
    preencher,
    sem_qrcode,
)

LARGURA = 1080
ALTURA_LINHA = 96      # na largura de 1080 px
ALTURA_MINIMA = 58     # abaixo disso a linha fica ilegível: o resto vira "e mais N"
# Quando os honorários não cabem na lista, a imagem estica para cada um ter esta
# altura — até MAXIMO_LINHAS; dali em diante, "e mais N".
ALTURA_ESTICADA = 84
MAXIMO_LINHAS = 30
FONTE_PADRAO = "Inter, Segoe UI, Arial, sans-serif"


def _estilo_da_lista(texto_svg: str) -> dict[str, str]:
    """Cores e fonte opcionais da lista: atributos data-* no retângulo id="lista"."""
    try:
        raiz = ET.fromstring(texto_svg.encode("utf-8"))
    except ET.ParseError:
        return {}
    for elemento in raiz.iter():
        if elemento.get("id") == "lista":
            return {
                chave: elemento.get(f"data-{chave}")
                for chave in ("fonte", "cor", "cor-fraca", "cor-linha")
                if elemento.get(f"data-{chave}")
            }
    return {}


def _fonte(familias: str, pixels: float, negrito: bool = False) -> QFont:
    fonte = QFont()
    fonte.setFamilies([nome.strip().strip("'\"") for nome in familias.split(",")])
    fonte.setPixelSize(max(8, round(pixels)))
    fonte.setBold(negrito)
    return fonte


def _area(renderizador: QSvgRenderer, elemento: str, caixa: QRectF, escala: float):
    """Onde o retângulo do SVG ficou na imagem, em pixels."""
    if not renderizador.elementExists(elemento):
        return None
    limites = renderizador.transformForElement(elemento).mapRect(
        renderizador.boundsOnElement(elemento)
    )
    return QRectF(
        (limites.x() - caixa.x()) * escala,
        (limites.y() - caixa.y()) * escala,
        limites.width() * escala,
        limites.height() * escala,
    )


def _linhas_na_lista(quantidade: int) -> int:
    """Quantas linhas a lista ocupa: os honorários, ou o máximo mais o "e mais N"."""
    return quantidade if quantidade <= MAXIMO_LINHAS else MAXIMO_LINHAS


def _desenhar_lista(pintor: QPainter, area: QRectF, linhas: list[LinhaImagem],
                    estilo: dict[str, str], escala_base: float) -> None:
    familias = estilo.get("fonte", FONTE_PADRAO)
    cor = QColor(estilo.get("cor", "#1d2330"))
    cor_fraca = QColor(estilo.get("cor-fraca", "#6b7684"))
    cor_linha = QColor(estilo.get("cor-linha", "#e2e6ec"))

    ideal = ALTURA_LINHA * escala_base
    minimo = ALTURA_MINIMA * escala_base
    mostrar = list(linhas)
    restantes = 0
    cabem_no_maximo = _linhas_na_lista(len(linhas))
    if area.height() / max(1, len(linhas)) < minimo or len(linhas) > cabem_no_maximo:
        cabem = min(cabem_no_maximo, max(1, int(area.height() // minimo)))
        mostrar = linhas[: cabem - 1] if cabem > 1 else linhas[:1]
        restantes = len(linhas) - len(mostrar)
    quantidade = len(mostrar) + (1 if restantes else 0)
    altura = min(ideal, area.height() / quantidade)

    titulo = _fonte(familias, altura * 0.29, negrito=True)
    detalhe = _fonte(familias, altura * 0.21)
    metrica_titulo = QFontMetricsF(titulo)
    metrica_detalhe = QFontMetricsF(detalhe)

    y = area.top()
    for posicao, linha in enumerate(mostrar):
        caixa = QRectF(area.left(), y, area.width(), altura)
        cima = QRectF(caixa.left(), caixa.top() + altura * 0.12, caixa.width(), altura * 0.42)
        baixo = QRectF(caixa.left(), caixa.top() + altura * 0.54, caixa.width(), altura * 0.34)

        pintor.setFont(titulo)
        largura_valor = metrica_titulo.horizontalAdvance(linha.valor)
        pintor.setPen(cor)
        pintor.drawText(cima, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                        linha.valor)
        espaco = cima.width() - largura_valor - 24 * escala_base
        pintor.drawText(
            QRectF(cima.left(), cima.top(), espaco, cima.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            metrica_titulo.elidedText(linha.titulo, Qt.TextElideMode.ElideRight, espaco),
        )

        pintor.setFont(detalhe)
        pintor.setPen(cor_fraca)
        largura_extra = metrica_detalhe.horizontalAdvance(linha.valor_detalhe)
        if linha.valor_detalhe:
            pintor.drawText(baixo, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                            linha.valor_detalhe)
        espaco = baixo.width() - largura_extra - 24 * escala_base
        pintor.drawText(
            QRectF(baixo.left(), baixo.top(), espaco, baixo.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            metrica_detalhe.elidedText(linha.detalhe, Qt.TextElideMode.ElideRight, espaco),
        )

        if posicao < quantidade - 1:
            pintor.setPen(cor_linha)
            pintor.drawLine(
                round(caixa.left()), round(caixa.bottom()),
                round(caixa.right()), round(caixa.bottom()),
            )
        y += altura

    if restantes:
        pintor.setFont(detalhe)
        pintor.setPen(cor_fraca)
        pintor.drawText(
            QRectF(area.left(), y, area.width(), altura),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"e mais {restantes} honorário{'s' if restantes > 1 else ''} — "
            "o total inclui todos",
        )


def _desenhar_qrcode(pintor: QPainter, area: QRectF, arquivo) -> None:
    """O PNG do QR code do banco, centrado no retângulo e sem deformar.

    Ampliado sem suavização: suavizar borra a borda dos quadradinhos e atrapalha
    a leitura. O fundo branco em volta é a margem que os leitores de QR precisam.
    """
    imagem = QImage(str(arquivo))
    if imagem.isNull():
        return
    lado = min(area.width(), area.height())
    escala = min(lado / imagem.width(), lado / imagem.height())
    largura, altura = imagem.width() * escala, imagem.height() * escala
    alvo = QRectF(
        round(area.left() + (area.width() - largura) / 2),
        round(area.top() + (area.height() - altura) / 2),
        round(largura),
        round(altura),
    )
    pintor.save()
    pintor.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    pintor.fillRect(alvo, QColor("#ffffff"))
    pintor.drawImage(alvo, imagem)
    pintor.restore()


def _esticar(imagem: QImage, lista: QRectF, extra: int) -> tuple[QImage, int]:
    """Abre ``extra`` pixels logo acima do fim da lista.

    A faixa de 1 px nesse ponto (no fundo, em geral o cartão e a faixa lateral)
    é repetida no espaço novo; tudo o que estava abaixo desce inteiro. Como o
    fundo é vetor já desenhado na largura final, nada perde qualidade.
    """
    return _esticar_em(imagem, int(lista.bottom()) - 1, extra)


def _esticar_em(imagem: QImage, corte: int, extra: int) -> tuple[QImage, int]:
    largura, altura = imagem.width(), imagem.height()
    corte = max(1, min(altura - 1, corte))
    nova = QImage(largura, altura + extra, QImage.Format.Format_ARGB32)
    nova.fill(QColor("#ffffff"))
    pintor = QPainter(nova)
    pintor.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    pintor.drawImage(QRectF(0, 0, largura, corte), imagem, QRectF(0, 0, largura, corte))
    pintor.drawImage(QRectF(0, corte, largura, extra), imagem, QRectF(0, corte, largura, 1))
    pintor.drawImage(
        QRectF(0, corte + extra, largura, altura - corte),
        imagem,
        QRectF(0, corte, largura, altura - corte),
    )
    pintor.end()
    return nova, corte


def renderizar(texto_svg: str, dados: DadosImagem, largura: int = LARGURA) -> QImage:
    """A imagem pronta, na largura pedida e na proporção do SVG.

    Com muitos honorários, a imagem fica mais comprida que o SVG (ver ``_esticar``).
    """
    if not dados.qrcode:   # sem QR anexado: sem a mensagem dele, Pix no lugar
        texto_svg = sem_qrcode(texto_svg)
    preenchido = preencher(para_imagem(texto_svg), dados.campos)
    renderizador = QSvgRenderer(QByteArray(preenchido.encode("utf-8")))
    if not renderizador.isValid():
        raise ErroDeValidacao("O fundo da imagem não é um SVG que o sistema consiga desenhar.")
    caixa = renderizador.viewBoxF()
    if caixa.isEmpty():
        tamanho = renderizador.defaultSize()
        caixa = QRectF(0, 0, tamanho.width(), tamanho.height())
    escala = largura / caixa.width()
    altura = round(caixa.height() * escala)

    imagem = QImage(largura, altura, QImage.Format.Format_ARGB32)
    imagem.fill(QColor("#ffffff"))
    pintor = QPainter(imagem)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    pintor.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    renderizador.render(pintor, QRectF(0, 0, largura, altura))

    escala_base = largura / LARGURA
    lista = _area(renderizador, "lista", caixa, escala)
    quadro = _area(renderizador, "qrcode", caixa, escala)
    if lista is not None and dados.linhas:
        necessario = _linhas_na_lista(len(dados.linhas)) * ALTURA_ESTICADA * escala_base
        extra = math.ceil(necessario - lista.height())
        if extra > 0:
            pintor.end()
            imagem, corte = _esticar(imagem, lista, extra)
            lista = lista.adjusted(0, 0, 0, extra)
            if quadro is not None and quadro.top() >= corte:
                quadro.translate(0, extra)
            pintor = QPainter(imagem)
            pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
            pintor.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        _desenhar_lista(pintor, lista, dados.linhas, _estilo_da_lista(texto_svg), escala_base)
    if quadro is not None and dados.qrcode:
        _desenhar_qrcode(pintor, quadro, dados.qrcode)
    pintor.end()
    return imagem


# ---------------------------------------------------------- agradecimento

AZUL_MARCA = "#203461"
CINZA_MARCA = "#5B6577"
TEAL_MARCA = "#4BBDCD"
LARANJA_MARCA = "#F9B259"
TEAL_SUAVE = "#DDF3F6"     # o verde-água da logo, clarinho, no painel do valor
LARGURA_AGRADECIMENTO = 1620   # 1,5× a cobrança: comprovante nítido
FUNDO_AGRADECIMENTO = "#EEF1F5"   # o mesmo cinza do fundo da cobrança


def _texto(pintor: QPainter, area: QRectF, texto: str, pixels: float, cor: str,
           negrito: bool = False, alinhamento=Qt.AlignmentFlag.AlignLeft) -> None:
    pintor.setFont(_fonte(FONTE_PADRAO, pixels, negrito))
    pintor.setPen(QColor(cor))
    metrica = QFontMetricsF(pintor.font())
    pintor.drawText(area, alinhamento | Qt.AlignmentFlag.AlignVCenter,
                    metrica.elidedText(texto, Qt.TextElideMode.ElideRight, area.width()))


def _marca(pintor: QPainter, area: QRectF) -> None:
    """A marca do Financeiro nas cores dela, em vetor (nítida em qualquer tamanho)."""
    from . import logo

    renderizador = QSvgRenderer(str(logo.MARCA))
    caixa = renderizador.viewBoxF()
    altura = area.width() * caixa.height() / caixa.width()
    renderizador.render(pintor, QRectF(area.left(), area.top(), area.width(), altura))


def _sombra(pintor: QPainter, caixa: QRectF, raio: float) -> None:
    """Sombra suave embaixo do cartão: camadas translúcidas, cada vez maiores."""
    pintor.setPen(Qt.PenStyle.NoPen)
    for passo in range(14, 0, -1):
        pintor.setBrush(QColor(32, 52, 97, 4))
        pintor.drawRoundedRect(caixa.adjusted(-passo, -passo + 8, passo, passo + 8),
                               raio + passo, raio + passo)


def _recorte(pintor: QPainter, x: float, y: float, raio: float, cor: str) -> None:
    """Os "furos" laterais de comprovante, onde o picote atravessa o cartão."""
    pintor.setPen(Qt.PenStyle.NoPen)
    pintor.setBrush(QColor(cor))
    pintor.drawEllipse(QPointF(x, y), raio, raio)


def renderizar_agradecimento(texto_svg: str, dados: DadosImagem,
                             largura: int = LARGURA_AGRADECIMENTO) -> QImage:
    """"Pagamento confirmado": um comprovante, de propósito diferente da cobrança.

    A cobrança é azul-marinho com o total numa faixa escura embaixo; aqui é um
    cartão branco com a logo nas cores originais no topo, o selo de confirmação e
    o valor num painel verde-água claro, e os honorários num canhoto picotado.
    Sai em resolução maior que a cobrança (1620 px) — o desenho é todo vetor.
    """
    from ...servicos.imagem_cobranca import _sem_elementos, base_do_fundo

    base = base_do_fundo(texto_svg)
    if base is not None:   # a logo do topo vai, nas cores dela, dentro do cartão branco
        base, _ = _sem_elementos(base, {"logo-pdf"})
    escala = largura / LARGURA
    altura = round(1350 * escala)
    imagem = QImage(largura, altura, QImage.Format.Format_ARGB32)
    imagem.fill(QColor(FUNDO_AGRADECIMENTO))
    pintor = QPainter(imagem)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    pintor.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    pintor.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if base is not None:
        QSvgRenderer(QByteArray(base.encode("utf-8"))).render(
            pintor, QRectF(0, 0, largura, altura)
        )
    pintor.scale(escala, escala)   # daqui em diante, coordenadas do fundo de 1080 × 1350
    campos = dados.campos
    centro = Qt.AlignmentFlag.AlignHCenter

    # o cartão branco
    cartao = QRectF(70, 56, 940, 1140)
    _sombra(pintor, cartao, 32)
    pintor.setBrush(QColor("#FFFFFF"))
    pintor.drawRoundedRect(cartao, 32, 32)

    # topo: a marca e o rótulo do documento
    _marca(pintor, QRectF(116, 94, 220, 0))
    _texto(pintor, QRectF(560, 122, 404, 30), "COMPROVANTE DE PAGAMENTO", 20, CINZA_MARCA,
           True, Qt.AlignmentFlag.AlignRight)

    # painel do valor: verde-água claro, com a faixa da cor da logo em cima
    painel = QRectF(116, 210, 848, 360)
    pintor.setPen(Qt.PenStyle.NoPen)
    gradiente = QLinearGradient(painel.topLeft(), painel.bottomLeft())
    gradiente.setColorAt(0, QColor(TEAL_SUAVE))
    gradiente.setColorAt(1, QColor("#F4FBFC"))
    pintor.setBrush(gradiente)
    pintor.drawRoundedRect(painel, 24, 24)
    contorno = QPainterPath()
    contorno.addRoundedRect(painel, 24, 24)
    pintor.save()
    pintor.setClipPath(contorno)   # a faixa acompanha os cantos arredondados
    pintor.fillRect(QRectF(painel.left(), painel.top(), painel.width(), 8), QColor(TEAL_MARCA))
    pintor.restore()

    selo = QPointF(540, 300)
    pintor.setBrush(QColor(75, 189, 205, 70))
    pintor.drawEllipse(selo, 58, 58)
    pintor.setBrush(QColor(AZUL_MARCA))
    pintor.drawEllipse(selo, 44, 44)
    pintor.setPen(QPen(QColor(LARANJA_MARCA), 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                       Qt.PenJoinStyle.RoundJoin))
    pintor.drawPolyline([QPointF(520, 301), QPointF(534, 315), QPointF(562, 286)])

    # sem data: o dia exato em que o dinheiro entrou nem sempre se sabe
    _texto(pintor, QRectF(140, 382, 800, 46), "Pagamento confirmado", 38, AZUL_MARCA, True,
           centro)
    _texto(pintor, QRectF(140, 436, 800, 100), campos["total"], 80, AZUL_MARCA, True, centro)

    # cliente
    _texto(pintor, QRectF(140, 598, 800, 28), "Cliente", 21, CINZA_MARCA)
    _texto(pintor, QRectF(140, 628, 800, 44), campos["cliente"], 32, AZUL_MARCA, True)
    documento = f"{campos.get('tipo_documento', '')} {campos.get('documento', '')}".strip()
    if documento:
        _texto(pintor, QRectF(140, 672, 800, 28), documento, 22, CINZA_MARCA)

    # picote entre o cliente e a lista
    _recorte(pintor, cartao.left(), 724, 18, FUNDO_AGRADECIMENTO)
    _recorte(pintor, cartao.right(), 724, 18, FUNDO_AGRADECIMENTO)
    pintor.setPen(QPen(QColor("#CFD6DE"), 2, Qt.PenStyle.DashLine))
    pintor.drawLine(QPointF(116, 724), QPointF(964, 724))

    _texto(pintor, QRectF(140, 744, 800, 28), f"Referente a {campos['quantidade']}", 22,
           AZUL_MARCA, True)
    pintor.setPen(Qt.PenStyle.NoPen)
    pintor.setBrush(QColor(LARANJA_MARCA))
    pintor.drawRoundedRect(QRectF(140, 776, 56, 5), 2.5, 2.5)
    _desenhar_lista(pintor, QRectF(140, 788, 800, 272), dados.linhas,
                    {"cor": AZUL_MARCA, "cor-fraca": CINZA_MARCA, "cor-linha": "#EDF0F3"},
                    0.9)

    # rodapé do cartão
    rodape = QRectF(116, 1076, 848, 96)
    pintor.setPen(Qt.PenStyle.NoPen)
    pintor.setBrush(QColor("#E6F6F8"))   # o ciano claro do canhoto da cobrança
    pintor.drawRoundedRect(rodape, 18, 18)
    _texto(pintor, QRectF(140, 1088, 800, 40), "Obrigado pela confiança!", 30, AZUL_MARCA,
           True, centro)
    _texto(pintor, QRectF(140, 1128, 800, 30), campos.get("recebedor", ""), 21, CINZA_MARCA,
           False, centro)
    pintor.end()
    return imagem
