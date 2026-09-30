"""Geração do texto de cobrança.

Não depende de Qt nem do banco: recebe um contexto pronto e devolve string, o
que deixa a mensagem testável sem abrir janela. Os modelos são editáveis em
Configurações; os padrões daqui reproduzem as mensagens que o escritório já usa.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal
from string import Formatter

from .enums import ChaveModelo, OrdemSaudacao, TipoChavePix
from .valores import ZERO, Competencia, formatar_data, formatar_moeda


class VariavelDesconhecida(ValueError):
    """Modelo usa uma variável que o sistema não sabe preencher."""

    def __init__(self, variavel: str, disponiveis: Sequence[str]) -> None:
        self.variavel = variavel
        self.disponiveis = list(disponiveis)
        super().__init__(
            f"A variável {{{variavel}}} não existe. Disponíveis: "
            + ", ".join("{" + v + "}" for v in sorted(disponiveis))
        )


# ------------------------------------------------------------------- saudação


def saudacao_por_horario(hora: time) -> str:
    """Bom dia até 11:59, Boa tarde de 12:00 a 17:59, Boa noite depois."""
    if hora.hour < 12:
        return "Bom dia"
    if hora.hour < 18:
        return "Boa tarde"
    return "Boa noite"


def montar_saudacao(
    hora: time,
    nome_tratamento: str | None = None,
    ordem: OrdemSaudacao = OrdemSaudacao.SAUDACAO_NOME,
) -> str:
    base = saudacao_por_horario(hora)
    nome = (nome_tratamento or "").strip()
    if not nome:
        return f"{base}!"
    if ordem is OrdemSaudacao.NOME_SAUDACAO:
        return f"{nome}, {base.lower()}!"
    return f"{base}, {nome}!"


# --------------------------------------------------------------------- itens


@dataclass(frozen=True)
class ItemCobranca:
    """Um honorário dentro da mensagem, com os valores já calculados."""

    tipo_nome: str
    texto_mensagem: str
    texto_mensagem_empresa: str
    texto_item_lista: str
    competencia: Competencia
    vencimento: date | None
    valor_original: Decimal
    juros: Decimal
    valor_atualizado: Decimal
    dias_atraso: int = 0
    honorario_id: int | None = None
    # preenchido quando a empresa cobra pela pessoa física vinculada a ela
    titular: str = ""

    @property
    def em_atraso(self) -> bool:
        return self.dias_atraso > 0

    @property
    def de_terceiro(self) -> bool:
        return bool(self.titular)

    def variaveis(self, empresa: str) -> dict[str, str]:
        return {
            "empresa": self.titular or empresa,
            "titular": self.titular,
            "nome_do_tipo": self.tipo_nome,
            "competencia": self.competencia.rotulo(),
            "ano": str(self.competencia.ano or ""),
            "vencimento": formatar_data(self.vencimento),
            "valor": formatar_moeda(self.valor_atualizado),
            "valor_original": formatar_moeda(self.valor_original),
            "juros": formatar_moeda(self.juros),
            "dias_atraso": str(self.dias_atraso),
        }

    def descricao(self, empresa: str, citar_empresa: bool) -> str:
        # honorário de pessoa vinculada sempre diz de quem é, senão a mensagem
        # sai falando de um débito que o destinatário não reconhece como dele
        usar_empresa = citar_empresa or self.de_terceiro
        modelo = self.texto_mensagem_empresa if usar_empresa else self.texto_mensagem
        if not (modelo or "").strip():
            modelo = self.texto_mensagem
        return renderizar(modelo, self.variaveis(empresa))

    def linha_lista(self, empresa: str) -> str:
        texto = renderizar(self.texto_item_lista, self.variaveis(empresa))
        if self.de_terceiro:
            return f"{self.titular}: {texto[0].lower()}{texto[1:]}" if texto else texto
        return texto


@dataclass(frozen=True)
class Recebedor:
    razao_social: str
    tipo_chave: TipoChavePix
    chave: str

    @property
    def rotulo_chave(self) -> str:
        return self.tipo_chave.rotulo


@dataclass(frozen=True)
class ContextoMensagem:
    empresa: str
    itens: Sequence[ItemCobranca]
    recebedor: Recebedor
    data_referencia: date
    hora_referencia: time
    nome_tratamento: str | None = None
    citar_empresa: bool = False
    ordem_saudacao: OrdemSaudacao = OrdemSaudacao.SAUDACAO_NOME
    modelos: Mapping[ChaveModelo, str] = field(default_factory=dict)
    forcar_lembrete: bool = False

    @property
    def total(self) -> Decimal:
        return sum((item.valor_atualizado for item in self.itens), start=ZERO)

    @property
    def algum_em_atraso(self) -> bool:
        return any(item.em_atraso for item in self.itens)

    @property
    def tem_titular_de_terceiro(self) -> bool:
        """Há honorário de pessoa vinculada sendo cobrado pela empresa."""
        return any(item.de_terceiro for item in self.itens)

    @property
    def chave_modelo(self) -> ChaveModelo:
        # com honorário de terceiro, a lista é obrigatória: é ela que mostra de
        # quem é cada valor
        unico = len(self.itens) == 1 and not self.tem_titular_de_terceiro
        if self.forcar_lembrete or not self.algum_em_atraso:
            return ChaveModelo.LEMBRETE if unico else ChaveModelo.VARIOS
        return ChaveModelo.UNIDADE if unico else ChaveModelo.VARIOS


# ------------------------------------------------------------------ renderização


def variaveis_de(texto: str) -> set[str]:
    """Nomes de variáveis usados num modelo."""
    return {
        nome for _, nome, _, _ in Formatter().parse(texto or "") if nome
    }


def renderizar(modelo: str, variaveis: Mapping[str, str]) -> str:
    usadas = variaveis_de(modelo)
    for nome in usadas:
        if nome not in variaveis:
            raise VariavelDesconhecida(nome, list(variaveis))
    return (modelo or "").format(**variaveis)


def _expressao_valor(valor: Decimal, atualizado: bool, plural: bool = False) -> str:
    rotulo = "o valor total" if plural else "o valor"
    if atualizado:
        rotulo += " atualizado"
    return f"{rotulo} é de {formatar_moeda(valor)}"


def variaveis_do_contexto(contexto: ContextoMensagem) -> dict[str, str]:
    if not contexto.itens:
        raise ValueError("Selecione ao menos um honorário para gerar a mensagem.")
    # a concordância segue o modelo escolhido, não a contagem: o modelo de lista
    # já diz "os seguintes", então singular ali quebraria a frase
    varios = contexto.chave_modelo is ChaveModelo.VARIOS
    primeiro = contexto.itens[0]
    lista = "\n".join(f"• {item.linha_lista(contexto.empresa)}" for item in contexto.itens)
    variaveis = {
        "saudacao": montar_saudacao(
            contexto.hora_referencia, contexto.nome_tratamento, contexto.ordem_saudacao
        ),
        "nome_tratamento": (contexto.nome_tratamento or "").strip(),
        "empresa": contexto.empresa,
        "data_referencia": formatar_data(contexto.data_referencia),
        "razao_social": contexto.recebedor.razao_social,
        "rotulo_chave": contexto.recebedor.rotulo_chave,
        "chave_pix": contexto.recebedor.chave,
        "lista_honorarios": lista,
        "quantidade": str(len(contexto.itens)),
        "valor_total": formatar_moeda(contexto.total),
        "expressao_valor_total": _expressao_valor(
            contexto.total, contexto.algum_em_atraso, plural=True
        ),
        "titular": primeiro.titular or contexto.empresa,
        "descricao": primeiro.descricao(contexto.empresa, contexto.citar_empresa),
        "competencia": primeiro.competencia.rotulo(),
        "ano": str(primeiro.competencia.ano or ""),
        "vencimento": formatar_data(primeiro.vencimento),
        "valor": formatar_moeda(primeiro.valor_atualizado),
        "juros": formatar_moeda(primeiro.juros),
        "dias_atraso": str(primeiro.dias_atraso),
        "expressao_valor": _expressao_valor(
            primeiro.valor_atualizado, primeiro.em_atraso, plural=False
        ),
        "constam": "Constam" if varios else "Consta",
        "honorarios": "honorários" if varios else "honorário",
    }
    return variaveis


def montar_mensagem(contexto: ContextoMensagem) -> str:
    chave = contexto.chave_modelo
    modelo = contexto.modelos.get(chave) or MODELOS_PADRAO[chave]
    texto = renderizar(modelo, variaveis_do_contexto(contexto))
    return _normalizar_espacos(texto)


def _normalizar_espacos(texto: str) -> str:
    """Tira espaço à direita e colapsa linhas em branco repetidas."""
    linhas = [linha.rstrip() for linha in texto.replace("\r\n", "\n").split("\n")]
    saida: list[str] = []
    for linha in linhas:
        if not linha and saida and not saida[-1]:
            continue
        saida.append(linha)
    return "\n".join(saida).strip()


def validar_modelo(modelo: str, chave: ChaveModelo) -> list[str]:
    """Devolve as variáveis inexistentes usadas no modelo (vazio = modelo válido)."""
    disponiveis = set(VARIAVEIS_DISPONIVEIS)
    return sorted(variaveis_de(modelo) - disponiveis)


VARIAVEIS_DISPONIVEIS: tuple[str, ...] = (
    "saudacao",
    "nome_tratamento",
    "empresa",
    "titular",
    "descricao",
    "competencia",
    "ano",
    "vencimento",
    "valor",
    "valor_original",
    "juros",
    "dias_atraso",
    "expressao_valor",
    "data_referencia",
    "lista_honorarios",
    "quantidade",
    "valor_total",
    "expressao_valor_total",
    "razao_social",
    "rotulo_chave",
    "chave_pix",
    "constam",
    "honorarios",
)

BLOCO_PIX = """Qual a previsão de pagamento?
PIX – {razao_social}
{rotulo_chave}: {chave_pix}

Após o pagamento, por gentileza, nos encaminhe o comprovante."""

MODELOS_PADRAO: dict[ChaveModelo, str] = {
    ChaveModelo.UNIDADE: (
        "{saudacao} Tudo bem?\n"
        "Consta em aberto o {descricao}, com vencimento em {vencimento}.\n"
        "Para pagamento hoje, {data_referencia}, {expressao_valor}.\n" + BLOCO_PIX
    ),
    ChaveModelo.VARIOS: (
        "{saudacao} Tudo bem?\n"
        "{constam} em aberto os seguintes {honorarios}:\n"
        "{lista_honorarios}\n"
        "Para pagamento hoje, {data_referencia}, {expressao_valor_total}.\n" + BLOCO_PIX
    ),
    ChaveModelo.LEMBRETE: (
        "{saudacao} Tudo bem?\n"
        "Passando para lembrar do {descricao}, que vence em {vencimento}, "
        "{expressao_valor}.\n" + BLOCO_PIX
    ),
}

# Textos de descrição por tipo de honorário (item 7.4). Ficam em TipoHonorario,
# editáveis; estes são os valores iniciais usados na carga do banco.
TEXTO_MENSAL = "honorário referente à competência {competencia}"
TEXTO_MENSAL_EMPRESA = (
    "honorário referente à empresa {empresa}, competência {competencia}"
)
TEXTO_MENSAL_ITEM = (
    "Honorário referente à competência {competencia}, vencimento {vencimento} – {valor}"
)
TEXTO_IRPF = "honorário referente ao seu imposto de renda/{ano}"
TEXTO_IRPF_EMPRESA = "honorário referente ao imposto de renda/{ano} de {empresa}"
TEXTO_IRPF_ITEM = "Imposto de renda/{ano}, vencimento {vencimento} – {valor}"
TEXTO_AVULSO = "boleto referente ao serviço de {nome_do_tipo}"
TEXTO_AVULSO_EMPRESA = (
    "boleto referente ao serviço de {nome_do_tipo} da empresa {empresa}"
)
TEXTO_AVULSO_ITEM = "{nome_do_tipo}, vencimento {vencimento} – {valor}"


def montar_link_whatsapp(telefone: str, texto: str, formato: str = "WA_ME") -> str:
    """Monta o link de conversa com o texto já codificado."""
    from urllib.parse import quote

    numero = "".join(c for c in telefone if c.isdigit())
    if not numero:
        raise ValueError("Contato sem telefone: não é possível abrir o WhatsApp.")
    corpo = quote(texto or "", safe="")
    if formato == "PROTOCOLO":
        return f"whatsapp://send?phone={numero}&text={corpo}"
    if formato == "API_WHATSAPP":
        return f"https://api.whatsapp.com/send?phone={numero}&text={corpo}"
    return f"https://wa.me/{numero}?text={corpo}"
