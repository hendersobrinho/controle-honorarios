"""Desenha a imagem de cobrança: fundo SVG + lista de honorários + QR code.

O SVG é renderizado em vetor na largura final, então o fundo não perde
qualidade. A lista e o QR são desenhados por cima, dentro dos retângulos
``lista`` e ``qrcode`` do próprio SVG.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from ...servicos.erros import ErroDeValidacao
from ...servicos.imagem_cobranca import DadosImagem, LinhaImagem, preencher

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
            "o total abaixo inclui todos",
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
    preenchido = preencher(texto_svg, dados.campos)
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


def renderizar_pagina(texto_svg: str, largura: int, altura: int) -> QImage:
    """O fundo como papel de uma página (ex.: A4 para o PDF).

    Na largura da página; se o fundo for mais curto que a página, estica no meio
    (onde costuma haver só fundo liso e faixa lateral) e os logos ficam intactos.
    """
    renderizador = QSvgRenderer(QByteArray(texto_svg.encode("utf-8")))
    if not renderizador.isValid():
        raise ErroDeValidacao("O fundo não é um SVG que o sistema consiga desenhar.")
    caixa = renderizador.viewBoxF()
    if caixa.isEmpty():
        tamanho = renderizador.defaultSize()
        caixa = QRectF(0, 0, tamanho.width(), tamanho.height())
    altura_svg = round(caixa.height() * largura / caixa.width())
    if altura_svg > altura:   # fundo mais comprido que a página: cabe pela altura
        largura_svg = round(caixa.width() * altura / caixa.height())
        imagem = QImage(largura, altura, QImage.Format.Format_ARGB32)
        imagem.fill(QColor("#ffffff"))
        pintor = QPainter(imagem)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderizador.render(pintor, QRectF((largura - largura_svg) / 2, 0, largura_svg, altura))
        pintor.end()
        return imagem
    imagem = QImage(largura, altura_svg, QImage.Format.Format_ARGB32)
    imagem.fill(QColor("#ffffff"))
    pintor = QPainter(imagem)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderizador.render(pintor, QRectF(0, 0, largura, altura_svg))
    pintor.end()
    if altura_svg < altura:
        imagem, _ = _esticar_em(imagem, altura_svg // 2, altura - altura_svg)
    return imagem
