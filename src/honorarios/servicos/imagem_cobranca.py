"""Imagem de cobrança: o fundo SVG do escritório com os dados da cobrança em cima.

O fundo é um SVG desenhado fora do sistema. Nele:

* textos com ``{campo}`` são trocados pelos valores (ver ``CAMPOS``);
* o retângulo ``id="lista"`` recebe os honorários selecionados, um por linha;
* o retângulo ``id="qrcode"`` recebe o PNG do QR code do Pix, gerado no banco e
  escolhido nas Configurações.

Aqui fica só o que não depende de Qt: os dados e o texto do SVG preenchido. O
desenho em si está em ``ui/comum/imagem_cobranca.py``.
"""

from __future__ import annotations

import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

from sqlalchemy.orm import Session

from ..config.caminhos import pasta_dados
from ..dominio.valores import ZERO, formatar_data, formatar_moeda
from . import configuracoes
from .cobrancas import Selecao
from .erros import ErroDeValidacao

FUNDO_MODELO = Path(__file__).resolve().parent.parent / "recursos" / "fundo_cobranca.svg"
NOME_FUNDO = "fundo_cobranca.svg"
NOME_QRCODE = "qrcode_pix.png"

CAMPOS = (
    ("cliente", "nome do cliente"),
    ("codigo", "código do cliente"),
    ("data", "data dos valores"),
    ("total", "total a pagar"),
    ("total_original", "soma dos valores originais"),
    ("total_juros", "soma dos juros"),
    ("quantidade", "quantos honorários"),
    ("recebedor", "razão social do escritório"),
    ("chave_pix", "chave Pix do escritório"),
)

_CAMPO = re.compile(r"\{([a-z_]+)\}")


@dataclass
class LinhaImagem:
    """Um honorário na lista da imagem."""

    titulo: str          # competência e tipo (e de quem é, se for de pessoa vinculada)
    detalhe: str         # vencimento e atraso
    valor: str           # total atualizado
    valor_detalhe: str   # original + juros, quando há juros


@dataclass
class DadosImagem:
    campos: dict[str, str]
    linhas: list[LinhaImagem]
    qrcode: Path | None = None          # PNG do QR code do banco; None = sem QR
    avisos: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------- fundo


def caminho_fundo(sessao: Session) -> Path:
    """O fundo escolhido nas Configurações ou, sem ele, o modelo do sistema."""
    escolhido = configuracoes.obter(sessao, "imagem_fundo", "")
    if escolhido and Path(escolhido).is_file():
        return Path(escolhido)
    return FUNDO_MODELO


def usa_modelo(sessao: Session) -> bool:
    return caminho_fundo(sessao) == FUNDO_MODELO


def validar_svg(texto: str) -> list[str]:
    """Confere o SVG e devolve avisos (não erros): faltar a lista ou o QR é permitido."""
    try:
        raiz = ET.fromstring(texto.encode("utf-8"))
    except ET.ParseError as falha:
        raise ErroDeValidacao(f"O arquivo não é um SVG válido: {falha}.") from falha
    if not raiz.tag.endswith("svg"):
        raise ErroDeValidacao("O arquivo não é um SVG.")
    ids = {elemento.get("id") for elemento in raiz.iter() if elemento.get("id")}
    avisos = []
    if "lista" not in ids:
        avisos.append('O fundo não tem o retângulo id="lista": os honorários não vão aparecer.')
    if "qrcode" not in ids:
        avisos.append('O fundo não tem o retângulo id="qrcode": o QR code não vai aparecer.')
    conhecidos = {nome for nome, _ in CAMPOS}
    # só o texto do desenho conta: comentários (o parser os descarta) podem citar {campo}
    textos = " ".join(
        parte
        for elemento in raiz.iter()
        for parte in (elemento.text, elemento.tail, *elemento.attrib.values())
        if parte
    )
    desconhecidos = sorted(set(_CAMPO.findall(textos)) - conhecidos)
    if desconhecidos:
        avisos.append(
            "Campos que o sistema não conhece: "
            + ", ".join("{" + nome + "}" for nome in desconhecidos)
            + "."
        )
    return avisos


def definir_fundo(sessao: Session, origem: Path) -> list[str]:
    """Copia o SVG para a pasta de dados (o original pode mudar de lugar) e o usa."""
    origem = Path(origem)
    try:
        texto = origem.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as falha:
        raise ErroDeValidacao(f"Não foi possível ler {origem.name}: {falha}.") from falha
    avisos = validar_svg(texto)
    destino = pasta_dados() / NOME_FUNDO
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(origem, destino)
    configuracoes.gravar(sessao, "imagem_fundo", str(destino))
    sessao.flush()
    return avisos


def usar_modelo(sessao: Session) -> None:
    configuracoes.gravar(sessao, "imagem_fundo", "")
    sessao.flush()


def caminho_qrcode(sessao: Session) -> Path | None:
    """O PNG do QR code escolhido nas Configurações, se houver."""
    escolhido = configuracoes.obter(sessao, "imagem_qrcode_png", "")
    return Path(escolhido) if escolhido and Path(escolhido).is_file() else None


def definir_qrcode(sessao: Session, origem: Path) -> None:
    """Guarda uma cópia do PNG do QR code (gerado no app do banco) e passa a usá-lo."""
    origem = Path(origem)
    try:
        cabecalho = origem.read_bytes()[:8]
    except OSError as falha:
        raise ErroDeValidacao(f"Não foi possível ler {origem.name}: {falha}.") from falha
    if cabecalho != b"\x89PNG\r\n\x1a\n":
        raise ErroDeValidacao(f"{origem.name} não é uma imagem PNG.")
    destino = pasta_dados() / NOME_QRCODE
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(origem, destino)
    configuracoes.gravar(sessao, "imagem_qrcode_png", str(destino))
    sessao.flush()


def remover_qrcode(sessao: Session) -> None:
    configuracoes.gravar(sessao, "imagem_qrcode_png", "")
    sessao.flush()


def base_do_fundo(texto_svg: str) -> str | None:
    """O fundo sem o grupo ``id="conteudo"`` (a camada que só serve à imagem).

    É o que o PDF da análise usa como papel de fundo. Sem esse grupo no SVG não
    dá para separar o desenho da camada da cobrança: devolve ``None``.
    """
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    try:
        raiz = ET.fromstring(texto_svg.encode("utf-8"))
    except ET.ParseError:
        return None
    for pai in raiz.iter():
        for filho in list(pai):
            if filho.get("id") == "conteudo":
                pai.remove(filho)
                return ET.tostring(raiz, encoding="unicode")
    return None


# ----------------------------------------------------------------------- dados


def _linha(linha, selecao: Selecao) -> LinhaImagem:
    honorario = linha.honorario
    atualizacao = linha.atualizacao
    competencia = honorario.competencia_rotulo or honorario.descricao
    tipo = honorario.tipo.nome
    if not competencia:
        titulo = tipo
    elif competencia.startswith(tipo):
        titulo = competencia
    else:
        titulo = f"{tipo} · {competencia}"
    if honorario.cliente_id != selecao.cliente.id:
        titulo = f"{honorario.cliente.nome}: {titulo}"
    detalhe = f"Vencimento {formatar_data(honorario.vencimento)}"
    if atualizacao.dias_atraso > 0:
        dias = atualizacao.dias_atraso
        detalhe += f" · {dias} dia{'s' if dias > 1 else ''} de atraso"
    valor_detalhe = ""
    if atualizacao.juros > 0:
        valor_detalhe = (
            f"{formatar_moeda(atualizacao.valor_original)} + "
            f"{formatar_moeda(atualizacao.juros)} de juros"
        )
    return LinhaImagem(
        titulo=titulo,
        detalhe=detalhe,
        valor=formatar_moeda(atualizacao.total),
        valor_detalhe=valor_detalhe,
    )


def montar(sessao: Session, selecao: Selecao) -> DadosImagem:
    """Os dados da imagem para os honorários selecionados na tela de cobrança."""
    if not selecao.linhas:
        raise ErroDeValidacao("Marque ao menos um honorário para gerar a imagem.")
    recebedor = configuracoes.recebedor(sessao)
    original = sum((linha.atualizacao.valor_original for linha in selecao.linhas), start=ZERO)
    juros = sum((linha.atualizacao.juros for linha in selecao.linhas), start=ZERO)
    quantidade = len(selecao.linhas)
    campos = {
        "cliente": selecao.cliente.nome,
        "codigo": selecao.cliente.codigo,
        "data": formatar_data(selecao.data_referencia),
        "total": formatar_moeda(selecao.total),
        "total_original": formatar_moeda(original),
        "total_juros": formatar_moeda(juros),
        "quantidade": f"{quantidade} honorário{'s' if quantidade > 1 else ''}",
        "recebedor": recebedor.razao_social,
        "chave_pix": recebedor.chave,
    }
    return DadosImagem(
        campos=campos,
        linhas=[_linha(linha, selecao) for linha in selecao.linhas],
        qrcode=caminho_qrcode(sessao),
    )


def preencher(texto_svg: str, campos: dict[str, str]) -> str:
    """Troca cada ``{campo}`` pelo valor. Campo desconhecido fica como está."""

    def trocar(encontrado: re.Match) -> str:
        nome = encontrado.group(1)
        return escape(campos[nome]) if nome in campos else encontrado.group(0)

    return _CAMPO.sub(trocar, texto_svg)


def exemplo(sessao: Session) -> DadosImagem:
    """Dados fictícios, para ver o fundo nas Configurações sem escolher cliente."""
    recebedor = configuracoes.recebedor(sessao)
    dados = DadosImagem(
        campos={
            "cliente": "EMPRESA EXEMPLO LTDA",
            "codigo": "900",
            "data": "30/09/2026",
            "total": "R$ 3.880,69",
            "total_original": "R$ 3.778,68",
            "total_juros": "R$ 102,01",
            "quantidade": "3 honorários",
            "recebedor": recebedor.razao_social,
            "chave_pix": recebedor.chave,
        },
        linhas=[
            LinhaImagem("Honorário mensal · 07/2026", "Vencimento 05/08/2026 · 56 dias de "
                        "atraso", "R$ 1.564,36", "R$ 1.507,80 + R$ 56,56 de juros"),
            LinhaImagem("Honorário mensal · 08/2026", "Vencimento 05/09/2026 · 25 dias de "
                        "atraso", "R$ 1.533,05", "R$ 1.507,80 + R$ 25,25 de juros"),
            LinhaImagem("Alteração contratual", "Vencimento 10/09/2026 · 20 dias de atraso",
                        "R$ 783,28", "R$ 763,08 + R$ 20,20 de juros"),
        ],
    )
    dados.qrcode = caminho_qrcode(sessao)
    return dados
