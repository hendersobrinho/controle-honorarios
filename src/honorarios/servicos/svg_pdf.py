"""Desenha os SVGs da marca no PDF (reportlab), em vetor, sem Qt.

Lê só o que os arquivos de ``recursos/`` usam: ``<path>`` com comandos absolutos
(M, L, H, V, Q, A, Z), ``fill``, ``fill-rule`` e um ``<g transform>`` com
``translate``/``scale``. Arcos e curvas viram Bézier cúbicas.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

_NS = "{http://www.w3.org/2000/svg}"
_TOKENS = re.compile(r"[A-Za-z]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")

# matriz afim (a, b, c, d, e, f): x' = a*x + c*y + e, y' = b*x + d*y + f
Matriz = tuple[float, float, float, float, float, float]
IDENTIDADE: Matriz = (1, 0, 0, 1, 0, 0)


def _compor(m: Matriz, n: Matriz) -> Matriz:
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + c * b2, b * a2 + d * b2, a * c2 + c * d2, b * c2 + d * d2,
            a * e2 + c * f2 + e, b * e2 + d * f2 + f)


def _transformacao(texto: str) -> Matriz:
    matriz = IDENTIDADE
    for nome, args in re.findall(r"(translate|scale)\(([^)]*)\)", texto):
        valores = [float(v) for v in re.split(r"[\s,]+", args.strip())]
        if nome == "translate":
            passo = (1, 0, 0, 1, valores[0], valores[1] if len(valores) > 1 else 0)
        else:
            sy = valores[1] if len(valores) > 1 else valores[0]
            passo = (valores[0], 0, 0, sy, 0, 0)
        matriz = _compor(matriz, passo)
    return matriz


def _arco(x1, y1, rx, ry, rotacao, grande, horario, x2, y2):
    """Arco elíptico do SVG em cúbicas: [(c1x, c1y, c2x, c2y, x, y), ...]."""
    if rx == 0 or ry == 0 or (x1 == x2 and y1 == y2):
        return [(x1, y1, x2, y2, x2, y2)]
    fi = math.radians(rotacao)
    cos_fi, sen_fi = math.cos(fi), math.sin(fi)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1l, y1l = cos_fi * dx + sen_fi * dy, -sen_fi * dx + cos_fi * dy
    rx, ry = abs(rx), abs(ry)
    lam = (x1l / rx) ** 2 + (y1l / ry) ** 2
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1l * y1l - ry * ry * x1l * x1l
    den = rx * rx * y1l * y1l + ry * ry * x1l * x1l
    fator = math.sqrt(max(0.0, num / den)) * (-1 if grande == horario else 1)
    cxl, cyl = fator * rx * y1l / ry, -fator * ry * x1l / rx
    cx = cos_fi * cxl - sen_fi * cyl + (x1 + x2) / 2
    cy = sen_fi * cxl + cos_fi * cyl + (y1 + y2) / 2

    def angulo(ux, uy, vx, vy):
        return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)

    inicio = angulo(1, 0, (x1l - cxl) / rx, (y1l - cyl) / ry)
    extensao = angulo((x1l - cxl) / rx, (y1l - cyl) / ry, (-x1l - cxl) / rx, (-y1l - cyl) / ry)
    if not horario and extensao > 0:
        extensao -= 2 * math.pi
    elif horario and extensao < 0:
        extensao += 2 * math.pi
    partes = max(1, math.ceil(abs(extensao) / (math.pi / 2)))
    passo = extensao / partes
    k = 4 / 3 * math.tan(passo / 4)

    def ponto(t):
        return (cx + rx * math.cos(t) * cos_fi - ry * math.sin(t) * sen_fi,
                cy + rx * math.cos(t) * sen_fi + ry * math.sin(t) * cos_fi)

    def derivada(t):
        return (-rx * math.sin(t) * cos_fi - ry * math.cos(t) * sen_fi,
                -rx * math.sin(t) * sen_fi + ry * math.cos(t) * cos_fi)

    curvas = []
    t = inicio
    for _ in range(partes):
        (ax, ay), (bx, by) = ponto(t), ponto(t + passo)
        (dax, day), (dbx, dby) = derivada(t), derivada(t + passo)
        curvas.append((ax + k * dax, ay + k * day, bx - k * dbx, by - k * dby, bx, by))
        t += passo
    return curvas


def _comandos(d: str):
    """O ``d`` do path em segmentos absolutos: ("M", x, y), ("L", x, y),
    ("C", c1x, c1y, c2x, c2y, x, y) e ("Z",)."""
    tokens = _TOKENS.findall(d)
    i, comando = 0, ""
    x = y = inicio_x = inicio_y = 0.0
    saida = []

    def numero():
        nonlocal i
        i += 1
        return float(tokens[i - 1])

    while i < len(tokens):
        if tokens[i].isalpha():
            comando = tokens[i]
            i += 1
            if comando == "Z":
                saida.append(("Z",))
                x, y = inicio_x, inicio_y
                continue
        if comando == "M":
            x, y = numero(), numero()
            inicio_x, inicio_y = x, y
            saida.append(("M", x, y))
            comando = "L"   # pares seguintes ao M são linhas
        elif comando == "L":
            x, y = numero(), numero()
            saida.append(("L", x, y))
        elif comando == "H":
            x = numero()
            saida.append(("L", x, y))
        elif comando == "V":
            y = numero()
            saida.append(("L", x, y))
        elif comando == "Q":
            qx, qy, nx, ny = numero(), numero(), numero(), numero()
            saida.append(("C", x + 2 / 3 * (qx - x), y + 2 / 3 * (qy - y),
                          nx + 2 / 3 * (qx - nx), ny + 2 / 3 * (qy - ny), nx, ny))
            x, y = nx, ny
        elif comando == "A":
            rx, ry, rot, grande, horario, nx, ny = (numero() for _ in range(7))
            for curva in _arco(x, y, rx, ry, rot, int(grande), int(horario), nx, ny):
                saida.append(("C", *curva))
            x, y = nx, ny
        else:
            raise ValueError(f"Comando de path não suportado: {comando}")
    return saida


@lru_cache(maxsize=8)
def _ler(arquivo: str) -> tuple[float, float, tuple]:
    raiz = ET.parse(arquivo).getroot()
    _, _, largura, altura = (float(v) for v in raiz.get("viewBox").split())
    caminhos = []

    def visitar(elemento, matriz: Matriz) -> None:
        matriz = _compor(matriz, _transformacao(elemento.get("transform", "")))
        if elemento.tag == f"{_NS}path":
            caminhos.append((matriz, elemento.get("fill", "#000000"),
                             elemento.get("fill-rule") == "evenodd",
                             tuple(_comandos(elemento.get("d", "")))))
        for filho in elemento:
            visitar(filho, matriz)

    visitar(raiz, IDENTIDADE)
    return largura, altura, tuple(caminhos)


def proporcao(arquivo: Path) -> float:
    """Largura ÷ altura do desenho."""
    largura, altura, _ = _ler(str(arquivo))
    return largura / altura


def desenhar(canvas, arquivo: Path, x: float, y: float, altura: float) -> float:
    """Desenha o SVG com o canto inferior esquerdo em (x, y) e a altura pedida, em
    pontos. Devolve a largura ocupada."""
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen.canvas import FILL_EVEN_ODD, FILL_NON_ZERO

    largura_svg, altura_svg, caminhos = _ler(str(arquivo))
    escala = altura / altura_svg
    canvas.saveState()
    for matriz, cor, par_impar, comandos in caminhos:
        a, b, c, d, e, f = matriz

        def pdf(px, py, a=a, b=b, c=c, d=d, e=e, f=f):
            sx, sy = a * px + c * py + e, b * px + d * py + f
            return x + sx * escala, y + altura - sy * escala   # SVG desce, PDF sobe

        caminho = canvas.beginPath()
        for comando in comandos:
            if comando[0] == "M":
                caminho.moveTo(*pdf(*comando[1:]))
            elif comando[0] == "L":
                caminho.lineTo(*pdf(*comando[1:]))
            elif comando[0] == "C":
                caminho.curveTo(*pdf(*comando[1:3]), *pdf(*comando[3:5]), *pdf(*comando[5:7]))
            else:
                caminho.close()
        canvas.setFillColor(HexColor(cor))
        canvas.drawPath(caminho, stroke=0, fill=1,
                        fillMode=FILL_EVEN_ODD if par_impar else FILL_NON_ZERO)
    canvas.restoreState()
    return largura_svg * escala
