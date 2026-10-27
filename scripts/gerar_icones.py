"""Gera os ícones .ico do Windows a partir dos arquivos de origem.

- ``src/honorarios/recursos/icone.svg`` → ``instalador/financeiro_metodos.ico``:
  o ícone do programa (área de trabalho, menu Iniciar, barra de tarefas). Por ser
  vetor, cada tamanho é desenhado do zero — nítido de 16 até 256 px. Até 24 px
  vem do ``icone_pequeno.svg`` (F mais grosso, para não sumir).
- ``instalador/instalador.png`` → ``instalador/instalador.ico``: o ícone do
  instalador. A origem tem 96 px, então os tamanhos param em 96 (ampliar borraria).

    .venv/bin/python scripts/gerar_icones.py
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
    origem = QImage(str(pasta / "instalador.png"))
    gravar_ico(pasta / "instalador.ico",
               [_do_png(origem, lado) for lado in TAMANHOS_INSTALADOR if lado <= origem.width()])
    # prévia grande, para conferir a nitidez
    _do_svg(svg, 512).save(str(pasta / "financeiro_metodos_512.png"))
    print("Ícones gerados em", pasta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
