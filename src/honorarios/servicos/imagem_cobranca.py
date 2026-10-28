"""Imagem de cobrança: o fundo SVG do escritório com os dados da cobrança em cima.

O fundo é um SVG desenhado fora do sistema. Nele:

* textos com ``{campo}`` são trocados pelos valores (ver ``CAMPOS``);
* o retângulo ``id="lista"`` recebe os honorários selecionados, um por linha;
* o retângulo ``id="qrcode"`` recebe o PNG do QR code do Pix, gerado no banco: o
  do escritório vem com o sistema, e outro pode ser escolhido nas Configurações;
* sem QR code anexado, sai o que tiver ``id="mensagem-qrcode"`` (o "aponte a
  câmera…") ou ``id="quadro-qrcode"`` (a moldura dele) e quem tiver
  ``data-sem-qrcode="translate(x y)"`` se move — para o bloco do Pix ocupar o
  lugar do QR em vez de deixar um quadrado vazio.

Aqui fica só o que não depende de Qt: os dados e o texto do SVG preenchido. O
desenho em si está em ``ui/comum/imagem_cobranca.py``.
"""

from __future__ import annotations

import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from sqlalchemy.orm import Session

from ..config.caminhos import pasta_dados
from ..dominio.enums import StatusPagamento, TipoPessoa
from ..dominio.valores import ZERO, formatar_data, formatar_documento, formatar_moeda
from . import calculo, configuracoes
from .cobrancas import Selecao
from .erros import ErroDeValidacao

FUNDO_MODELO = Path(__file__).resolve().parent.parent / "recursos" / "fundo_cobranca.svg"
NOME_FUNDO = "fundo_cobranca.svg"
NOME_QRCODE = "qrcode_pix.png"
# o QR do Pix do escritório (gerado no app do banco), usado enquanto não se escolhe outro
QRCODE_MODELO = FUNDO_MODELO.parent / NOME_QRCODE
SEM_QRCODE = "nenhum"   # valor da configuração quando a pessoa tira o QR da imagem

CAMPOS = (
    ("cliente", "nome do cliente"),
    ("codigo", "código do cliente"),
    ("documento", "CNPJ ou CPF do cliente cobrado"),
    ("tipo_documento", "\"CNPJ\" ou \"CPF\""),
    ("vencimento", "data para pagar (editável na prévia)"),
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
    valor_detalhe: str = ""   # vazio: a imagem mostra só o valor final cheio


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
    """Passa a usar o modelo — o seu fundo continua guardado na pasta de dados."""
    configuracoes.gravar(sessao, "imagem_fundo", "")
    sessao.flush()


def fundo_guardado() -> Path | None:
    """O último fundo escolhido, guardado na pasta de dados (para poder voltar a ele)."""
    caminho = pasta_dados() / NOME_FUNDO
    return caminho if caminho.is_file() else None


def voltar_ao_fundo_guardado(sessao: Session) -> list[str]:
    caminho = fundo_guardado()
    if caminho is None:
        raise ErroDeValidacao("Não há fundo seu guardado: escolha um arquivo SVG.")
    configuracoes.gravar(sessao, "imagem_fundo", str(caminho))
    sessao.flush()
    return validar_svg(caminho.read_text(encoding="utf-8"))


def caminho_qrcode(sessao: Session) -> Path | None:
    """O PNG do QR code: o escolhido nas Configurações, o do escritório que vem com o
    sistema, ou nenhum (se a pessoa removeu)."""
    escolhido = configuracoes.obter(sessao, "imagem_qrcode_png", "")
    if escolhido == SEM_QRCODE:
        return None
    if escolhido and Path(escolhido).is_file():
        return Path(escolhido)
    return QRCODE_MODELO if QRCODE_MODELO.is_file() else None


def usa_qrcode_modelo(sessao: Session) -> bool:
    return caminho_qrcode(sessao) == QRCODE_MODELO


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
    """A imagem passa a sair sem QR (o bloco do Pix ocupa o lugar dele)."""
    configuracoes.gravar(sessao, "imagem_qrcode_png", SEM_QRCODE)
    sessao.flush()


def usar_qrcode_modelo(sessao: Session) -> None:
    """Volta ao QR do escritório que vem com o sistema."""
    configuracoes.gravar(sessao, "imagem_qrcode_png", "")
    sessao.flush()


def _sem_elementos(texto_svg: str, ids: set[str]) -> tuple[str, set[str]]:
    """O SVG sem os elementos destes ids, e quais deles existiam."""
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    raiz = ET.fromstring(texto_svg.encode("utf-8"))
    achados: set[str] = set()
    for pai in list(raiz.iter()):
        for filho in list(pai):
            if filho.get("id") in ids:
                achados.add(filho.get("id"))
                pai.remove(filho)
    return ET.tostring(raiz, encoding="unicode"), achados


def base_do_fundo(texto_svg: str) -> str | None:
    """O papel dos PDFs: o fundo sem a camada da cobrança (``id="conteudo"``).

    Se o fundo tiver um logo só para a imagem (``logo-imagem``) e outro só para os
    PDFs (``logo-pdf``), sai o da imagem. Sem o grupo ``conteudo`` não dá para
    separar o desenho da camada da cobrança: devolve ``None``.
    """
    try:
        base, achados = _sem_elementos(texto_svg, {"conteudo", "logo-imagem"})
    except ET.ParseError:
        return None
    return base if "conteudo" in achados else None


MENSAGEM_QRCODE = "mensagem-qrcode"
SO_COM_QRCODE = {MENSAGEM_QRCODE, "quadro-qrcode"}   # saem quando não há QR code


def sem_qrcode(texto_svg: str) -> str:
    """O fundo para quando não há QR code: sem a mensagem dele, com o Pix no lugar."""
    if not any(nome in texto_svg for nome in (*SO_COM_QRCODE, "data-sem-qrcode")):
        return texto_svg
    try:
        texto, _ = _sem_elementos(texto_svg, SO_COM_QRCODE)
        raiz = ET.fromstring(texto.encode("utf-8"))
    except ET.ParseError:
        return texto_svg
    for elemento in raiz.iter():
        mover = elemento.attrib.pop("data-sem-qrcode", None)
        if mover:
            atual = elemento.get("transform", "")
            elemento.set("transform", f"{mover} {atual}".strip())
    return ET.tostring(raiz, encoding="unicode")


def para_imagem(texto_svg: str) -> str:
    """O fundo como vai na imagem de cobrança: com a logo nova, se o fundo tiver as duas.

    A imagem e os PDFs usam a mesma logo (``logo-pdf``); o logo antigo
    (``logo-imagem``) só aparece se for o único do fundo.
    """
    if 'id="logo-pdf"' not in texto_svg or 'id="logo-imagem"' not in texto_svg:
        return texto_svg
    return _sem_elementos(texto_svg, {"logo-imagem"})[0]


# ----------------------------------------------------------------------- dados


def _linha(linha, selecao: Selecao, atualizacao) -> LinhaImagem:
    honorario = linha.honorario
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
    # só o valor final cheio: o juros não aparece separado na imagem
    return LinhaImagem(titulo=titulo, detalhe=detalhe, valor=formatar_moeda(atualizacao.total))


def montar(
    sessao: Session,
    selecao: Selecao,
    vencimento: date | None = None,
    atualizado_em: date | None = None,
) -> DadosImagem:
    """Os dados da imagem para os honorários selecionados na tela de cobrança.

    ``atualizado_em``: a data em que os valores são calculados (juros até ela).
    ``vencimento``: até quando esse valor vale — a data "pagar até" da imagem. Sem
    elas, as duas são a data de referência da cobrança.
    """
    if not selecao.linhas:
        raise ErroDeValidacao("Marque ao menos um honorário para gerar a imagem.")
    data = atualizado_em or selecao.data_referencia
    vencimento = vencimento or data
    if vencimento < data:
        raise ErroDeValidacao(
            "O \"pagar até\" não pode ser antes da data em que os valores foram atualizados."
        )
    atualizacoes = [calculo.atualizar(linha.honorario, data) for linha in selecao.linhas]
    recebedor = configuracoes.recebedor(sessao)
    original = sum((atual.valor_original for atual in atualizacoes), start=ZERO)
    juros = sum((atual.juros for atual in atualizacoes), start=ZERO)
    total = sum((atual.total for atual in atualizacoes), start=ZERO)
    quantidade = len(selecao.linhas)
    cliente = selecao.cliente
    campos = {
        "cliente": cliente.nome,
        "codigo": cliente.codigo,
        "documento": formatar_documento(cliente.documento) or "",
        "tipo_documento": (
            ("CNPJ" if cliente.tipo_pessoa is TipoPessoa.PJ else "CPF")
            if cliente.documento else ""
        ),
        "vencimento": formatar_data(vencimento),
        "data": formatar_data(data),
        "total": formatar_moeda(total),
        "total_original": formatar_moeda(original),
        "total_juros": formatar_moeda(juros),
        "quantidade": f"{quantidade} honorário{'s' if quantidade > 1 else ''}",
        "recebedor": recebedor.razao_social,
        "chave_pix": recebedor.chave,
    }
    return DadosImagem(
        campos=campos,
        linhas=[
            _linha(linha, selecao, atual)
            for linha, atual in zip(selecao.linhas, atualizacoes, strict=True)
        ],
        qrcode=caminho_qrcode(sessao),
    )


def montar_agradecimento(sessao: Session, honorarios) -> DadosImagem:
    """Os dados da imagem de agradecimento: o que foi pago, quando e quanto."""
    if not honorarios:
        raise ErroDeValidacao("Escolha um honorário pago para gerar o agradecimento.")
    linhas, total, ultima = [], ZERO, None
    for honorario in honorarios:
        pagamentos = [p for p in honorario.pagamentos if p.ativo]
        if not pagamentos:
            raise ErroDeValidacao("Este honorário não tem pagamento registrado.")
        pago = sum((p.valor_pago for p in pagamentos), start=ZERO)
        data = max(p.data for p in pagamentos)
        parcial = honorario.status is not StatusPagamento.PAGO
        competencia = honorario.competencia_rotulo or honorario.descricao
        tipo = honorario.tipo.nome
        titulo = tipo if not competencia else (
            competencia if competencia.startswith(tipo) else f"{tipo} · {competencia}"
        )
        linhas.append(LinhaImagem(
            titulo=titulo,
            # sem a data do pagamento: o dia exato nem sempre se sabe
            detalhe=f"Vencimento {formatar_data(honorario.vencimento)}"
            + (" · pagamento parcial" if parcial else ""),
            valor=formatar_moeda(pago),
        ))
        total += pago
        ultima = data if ultima is None or data > ultima else ultima
    cliente = honorarios[0].cliente
    recebedor = configuracoes.recebedor(sessao)
    return DadosImagem(
        campos={
            "cliente": cliente.nome,
            "codigo": cliente.codigo,
            "documento": formatar_documento(cliente.documento) or "",
            "tipo_documento": (
                ("CNPJ" if cliente.tipo_pessoa is TipoPessoa.PJ else "CPF")
                if cliente.documento else ""
            ),
            "data": formatar_data(ultima),
            "total": formatar_moeda(total),
            "quantidade": f"{len(linhas)} honorário{'s' if len(linhas) > 1 else ''}",
            "recebedor": recebedor.razao_social,
        },
        linhas=linhas,
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
            "documento": "12.345.678/0001-95",
            "tipo_documento": "CNPJ",
            "vencimento": "30/09/2026",
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
                        "atraso", "R$ 1.564,36"),
            LinhaImagem("Honorário mensal · 08/2026", "Vencimento 05/09/2026 · 25 dias de "
                        "atraso", "R$ 1.533,05"),
            LinhaImagem("Alteração contratual", "Vencimento 10/09/2026 · 20 dias de atraso",
                        "R$ 783,28"),
        ],
    )
    dados.qrcode = caminho_qrcode(sessao)
    return dados
