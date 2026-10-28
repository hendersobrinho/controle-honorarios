"""Gera os ícones .ico do Windows a partir dos arquivos de origem.

- ``src/honorarios/recursos/icone.svg`` → ``instalador/financeiro_metodos.ico``:
  o ícone do programa (área de trabalho, menu Iniciar, barra de tarefas). Por ser
  vetor, cada tamanho é desenhado do zero — nítido de 16 até 256 px. Até 24 px
  vem do ``icone_pequeno.svg`` (F mais grosso, para não sumir).
- ``instalador/instalador.png`` → ``instalador/instalador.ico``: o ícone do
  instalador. A origem tem 96 px, então os tamanhos param em 96 (ampliar borraria).
  O ``instalador.ico`` que veio no kit da identidade é mais nítido nos tamanhos
  pequenos: com ``--sem-instalador`` ele fica como está.
- as imagens do assistente de instalação (Inno Setup), em BMP 24 bits, uma por
  escala de tela do Windows: a lateral (``assistente_*.bmp``, o canhoto navy com
  a marca) e a do canto (``assistente_pequeno_*.bmp``, o ícone).

    .venv/bin/python scripts/gerar_icones.py [--sem-instalador]
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

RAIZ = Path(__file__).resolve().parents[1]
TAMANHOS_PROGRAMA = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
TAMANHOS_INSTALADOR = (16, 20, 24, 32, 40, 48, 64, 96)
# tamanhos que o Inno Setup 6 pede para 100%, 125%, 150%, 175%, 200%, 225% e 250%
ASSISTENTE = ((164, 314), (192, 386), (246, 459), (273, 556), (328, 604), (355, 700),
              (410, 797))
ASSISTENTE_PEQUENO = ((55, 55), (64, 68), (83, 80), (92, 97), (110, 106), (119, 123),
                      (138, 140))


def _png(imagem: QImage) -> bytes:
    dados = QByteArray()
    buffer = QBuffer(dados)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    imagem.save(buffer, "PNG")
    return bytes(dados)


def _do_svg(svg: Path, lado: int) -> QImage:
    renderizador = QSvgRenderer(str(svg))
    imagem = QImage(lado, lado, QImage.Format.Format_ARGB32)
    imagem.fill(QColor(0, 0, 0, 0))
    pintor = QPainter(imagem)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    pintor.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderizador.render(pintor, QRectF(0, 0, lado, lado))
    pintor.end()
    return imagem


def _do_png(origem: QImage, lado: int) -> QImage:
    if origem.width() == lado:
        return origem
    return origem.scaled(lado, lado, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)


def _assistente(largura: int, altura: int) -> QImage:
    """A lateral do assistente: o corpo navy com a marca e o canhoto ciano embaixo."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QLinearGradient

    imagem = QImage(largura, altura, QImage.Format.Format_RGB32)
    imagem.fill(QColor("#FFFFFF"))
    pintor = QPainter(imagem)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    canhoto = round(altura * 0.86)
    fresta = max(4, round(largura * 0.04))
    degrade = QLinearGradient(0, 0, largura, canhoto)
    degrade.setColorAt(0, QColor("#203461"))
    degrade.setColorAt(1, QColor("#16254A"))
    pintor.fillRect(QRectF(0, 0, largura, canhoto), degrade)
    pintor.fillRect(QRectF(0, canhoto + fresta, largura, altura), QColor("#4BBDCD"))
    furo = fresta * 1.6   # os furos do picote nas laterais
    pintor.setPen(Qt.PenStyle.NoPen)
    pintor.setBrush(QColor("#FFFFFF"))
    for x in (0, largura):
        pintor.drawEllipse(QPointF(x, canhoto + fresta / 2), furo, furo)
    tracinho = largura / 15
    pintor.setBrush(QColor("#C5CDE0"))
    x = tracinho
    while x + tracinho * 0.5 < largura - tracinho:
        pintor.drawRect(QRectF(x, canhoto + fresta / 2 - 0.75, tracinho * 0.5, 1.5))
        x += tracinho
    marca = QSvgRenderer(str(RAIZ / "instalador/marca_vertical_negativo.svg"))
    caixa = marca.viewBoxF()
    largura_marca = largura * 0.66
    altura_marca = largura_marca * caixa.height() / caixa.width()
    marca.render(pintor, QRectF((largura - largura_marca) / 2, altura * 0.2,
                                largura_marca, altura_marca))
    pintor.end()
    return imagem.convertToFormat(QImage.Format.Format_RGB888)


def _assistente_pequeno(largura: int, altura: int) -> QImage:
    """O canto do assistente: o ícone do programa sobre o branco do cabeçalho."""
    imagem = QImage(largura, altura, QImage.Format.Format_RGB32)
    imagem.fill(QColor("#FFFFFF"))
    pintor = QPainter(imagem)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    lado = min(largura, altura) * 0.92
    QSvgRenderer(str(RAIZ / "src/honorarios/recursos/icone.svg")).render(
        pintor, QRectF((largura - lado) / 2, (altura - lado) / 2, lado, lado)
    )
    pintor.end()
    return imagem.convertToFormat(QImage.Format.Format_RGB888)


def gravar_ico(destino: Path, imagens: list[QImage]) -> None:
    """ICO com cada tamanho em PNG (o formato que o Windows Vista em diante lê)."""
    blocos = [_png(imagem) for imagem in imagens]
    cabecalho = struct.pack("<HHH", 0, 1, len(blocos))
    deslocamento = 6 + 16 * len(blocos)
    diretorio = b""
    for imagem, bloco in zip(imagens, blocos, strict=True):
        lado = imagem.width()
        diretorio += struct.pack("<BBBBHHII", lado % 256, lado % 256, 0, 0, 1, 32,
                                 len(bloco), deslocamento)
        deslocamento += len(bloco)
    destino.write_bytes(cabecalho + diretorio + b"".join(blocos))


def main() -> int:
    QGuiApplication.instance() or QGuiApplication(sys.argv)
    pasta = RAIZ / "instalador"
    pasta.mkdir(exist_ok=True)
    svg = RAIZ / "src/honorarios/recursos/icone.svg"
    pequeno = RAIZ / "src/honorarios/recursos/icone_pequeno.svg"
    gravar_ico(pasta / "financeiro_metodos.ico",
               [_do_svg(pequeno if lado <= 24 else svg, lado) for lado in TAMANHOS_PROGRAMA])
    if "--sem-instalador" not in sys.argv:
        origem = QImage(str(pasta / "instalador.png"))
        gravar_ico(pasta / "instalador.ico",
                   [_do_png(origem, lado) for lado in TAMANHOS_INSTALADOR
                    if lado <= origem.width()])
    for escala, (largura, altura) in zip((100, 125, 150, 175, 200, 225, 250), ASSISTENTE,
                                         strict=True):
        _assistente(largura, altura).save(str(pasta / f"assistente_{escala}.bmp"), "BMP")
    for escala, (largura, altura) in zip((100, 125, 150, 175, 200, 225, 250),
                                         ASSISTENTE_PEQUENO, strict=True):
        _assistente_pequeno(largura, altura).save(
            str(pasta / f"assistente_pequeno_{escala}.bmp"), "BMP"
        )
    # prévia grande, para conferir a nitidez
    _do_svg(svg, 512).save(str(pasta / "financeiro_metodos_512.png"))
    print("Ícones gerados em", pasta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
