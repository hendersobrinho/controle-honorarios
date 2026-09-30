"""Tipos de valor do domínio: dinheiro, datas, competência, documento e telefone.

Nada aqui depende de Qt nem do banco. Dinheiro é sempre ``Decimal``: a planilha
arredonda com ``ROUND(x; 2)``, que é meio-para-cima, e é isso que reproduzimos.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from zoneinfo import ZoneInfo

FUSO_LOCAL = ZoneInfo("America/Sao_Paulo")
CENTAVO = Decimal("0.01")
ZERO = Decimal("0.00")

MESES_ABREVIADOS = (
    "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
    "Jul", "Ago", "Set", "Out", "Nov", "Dez",
)


# --------------------------------------------------------------------------- data


def agora_local() -> datetime:
    """Data e hora corrente em America/Sao_Paulo."""
    return datetime.now(FUSO_LOCAL)


def hoje() -> date:
    """"Hoje" do sistema: data local em America/Sao_Paulo."""
    return agora_local().date()


def agora_utc() -> datetime:
    return datetime.now(UTC)


def formatar_data(valor: date | datetime | None) -> str:
    if valor is None:
        return ""
    if isinstance(valor, datetime):
        valor = valor.date()
    return valor.strftime("%d/%m/%Y")


def formatar_data_hora(valor: datetime | None) -> str:
    if valor is None:
        return ""
    if valor.tzinfo is not None:
        valor = valor.astimezone(FUSO_LOCAL)
    return valor.strftime("%d/%m/%Y %H:%M")


def ler_data(texto: str) -> date:
    """Lê uma data em dd/mm/aaaa (aceita também dd/mm/aa e aaaa-mm-dd)."""
    texto = (texto or "").strip()
    for formato in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    raise ValueError(f"Data inválida: {texto!r}. Use o formato dd/mm/aaaa.")


def dia_do_mes(ano: int, mes: int, dia: int) -> date:
    """Data do dia informado, recuando quando o mês é curto (31 em fevereiro)."""
    import calendar

    ultimo = calendar.monthrange(ano, mes)[1]
    return date(ano, mes, min(dia, ultimo))


def somar_meses(referencia: date, meses: int) -> date:
    total = referencia.month - 1 + meses
    ano = referencia.year + total // 12
    mes = total % 12 + 1
    return dia_do_mes(ano, mes, referencia.day)


# ------------------------------------------------------------------------ dinheiro


def dinheiro(valor: Decimal | int | float | str | None) -> Decimal:
    """Converte para Decimal com 2 casas, arredondando meio-para-cima.

    ``float`` é aceito só porque a planilha entrega float; a conversão passa por
    ``str`` para não arrastar o erro binário (0.1 + 0.2 e afins).
    """
    if valor is None or valor == "":
        return ZERO
    if isinstance(valor, float):
        valor = str(valor)
    try:
        return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)
    except InvalidOperation as erro:
        raise ValueError(f"Valor monetário inválido: {valor!r}") from erro


def arredondar(valor: Decimal) -> Decimal:
    """``ROUND(x; 2)`` da planilha: meio-para-cima, só no total."""
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def formatar_moeda(valor: Decimal | int | float | None, com_simbolo: bool = True) -> str:
    """R$ 1.234,56 (padrão brasileiro, sem depender de locale do sistema)."""
    if valor is None:
        valor = ZERO
    valor = dinheiro(valor)
    negativo = valor < 0
    inteiro, _, centavos = f"{abs(valor):.2f}".partition(".")
    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    texto = ".".join(grupos) + "," + centavos
    if negativo:
        texto = "-" + texto
    return f"R$ {texto}" if com_simbolo else texto


def ler_moeda(texto: str) -> Decimal:
    """Lê "R$ 1.234,56", "1234,56" ou "1234.56"."""
    texto = (texto or "").strip()
    if not texto:
        return ZERO
    limpo = re.sub(r"[^\d,.\-]", "", texto)
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    return dinheiro(limpo)


def formatar_taxa_dia(valor: Decimal | None) -> str:
    """Juros ao dia tem 2 casas na planilha, mas aceita mais precisão no cálculo."""
    if valor is None:
        return ""
    return formatar_moeda(valor)


# --------------------------------------------------------------------- competência


@dataclass(frozen=True, order=True)
class Competencia:
    """Competência do honorário: mês/ano, só ano (IRPF) ou nenhuma (avulso)."""

    ano: int | None = None
    mes: int | None = None

    def __post_init__(self) -> None:
        if self.mes is not None and not 1 <= self.mes <= 12:
            raise ValueError(f"Mês de competência inválido: {self.mes}")
        if self.mes is not None and self.ano is None:
            raise ValueError("Competência com mês exige o ano.")

    @property
    def vazia(self) -> bool:
        return self.ano is None and self.mes is None

    def rotulo(self) -> str:
        if self.mes and self.ano:
            return f"{self.mes:02d}/{self.ano}"
        if self.ano:
            return str(self.ano)
        return ""

    def rotulo_curto(self) -> str:
        if self.mes and self.ano:
            return f"{MESES_ABREVIADOS[self.mes - 1]}/{str(self.ano)[-2:]}"
        return self.rotulo()

    def proxima(self, meses: int = 1) -> Competencia:
        if not (self.ano and self.mes):
            raise ValueError("Só competência mensal tem próxima competência.")
        total = (self.ano * 12 + self.mes - 1) + meses
        return Competencia(ano=total // 12, mes=total % 12 + 1)

    @classmethod
    def de_texto(cls, valor: object) -> Competencia:
        """Normaliza o que a planilha antiga guardava na coluna Competência.

        Aceita ``MM/AAAA``, ``AAAA-MM``, ``mmm/aa``, data, serial do Excel,
        ``IRPF 2026`` e texto que não é competência nenhuma (devolve vazia).
        """
        if valor is None or valor == "":
            return cls()
        if isinstance(valor, datetime):
            return cls(ano=valor.year, mes=valor.month)
        if isinstance(valor, date):
            return cls(ano=valor.year, mes=valor.month)
        if isinstance(valor, (int, float)) and not isinstance(valor, bool):
            numero = int(valor)
            if 1900 <= numero <= 2200:  # foi digitado o ano
                return cls(ano=numero)
            if 20000 <= numero <= 80000:  # serial de data do Excel
                convertida = date(1899, 12, 30).toordinal() + numero
                data = date.fromordinal(convertida)
                return cls(ano=data.year, mes=data.month)
            raise ValueError(f"Competência numérica não reconhecida: {valor!r}")

        texto = str(valor).strip()
        casamento = re.fullmatch(r"(\d{1,2})\s*[/\-.]\s*(\d{4})", texto)
        if casamento:
            return cls(ano=int(casamento.group(2)), mes=int(casamento.group(1)))
        casamento = re.fullmatch(r"(\d{4})\s*[/\-.]\s*(\d{1,2})", texto)
        if casamento:
            return cls(ano=int(casamento.group(1)), mes=int(casamento.group(2)))
        casamento = re.fullmatch(r"(\d{1,2})\s*[/\-.]\s*(\d{2})", texto)
        if casamento:
            ano = int(casamento.group(2))
            return cls(ano=2000 + ano, mes=int(casamento.group(1)))
        # "IRPF 2026", "Imposto de Renda 2026", "2026"
        anos = re.findall(r"(19\d{2}|20\d{2})", texto)
        if anos:
            mes = None
            sem_acento = remover_acentos(texto).lower()
            for indice, abreviado in enumerate(MESES_ABREVIADOS, start=1):
                if remover_acentos(abreviado).lower() in sem_acento:
                    mes = indice
                    break
            return cls(ano=int(anos[0]), mes=mes)
        return cls()


# ---------------------------------------------------------------------- documento


def remover_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def normalizar_busca(texto: str) -> str:
    """Texto comparável: sem acento, sem pontuação, minúsculo."""
    return re.sub(r"[^0-9a-z ]+", "", remover_acentos(texto or "").lower()).strip()


def so_digitos(texto: str | None) -> str:
    return re.sub(r"\D", "", texto or "")


def _digito_cpf(base: str) -> str:
    def calcular(parcial: str, peso_inicial: int) -> str:
        soma = sum(int(d) * p for d, p in zip(parcial, range(peso_inicial, 1, -1), strict=True))
        resto = (soma * 10) % 11
        return str(resto if resto < 10 else 0)

    primeiro = calcular(base[:9], 10)
    segundo = calcular(base[:9] + primeiro, 11)
    return primeiro + segundo


def _digito_cnpj(base: str) -> str:
    pesos_primeiro = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos_segundo = [6, *pesos_primeiro]

    def calcular(parcial: str, pesos: list[int]) -> str:
        soma = sum(int(d) * p for d, p in zip(parcial, pesos, strict=True))
        resto = soma % 11
        return "0" if resto < 2 else str(11 - resto)

    primeiro = calcular(base[:12], pesos_primeiro)
    segundo = calcular(base[:12] + primeiro, pesos_segundo)
    return primeiro + segundo


def validar_documento(documento: str | None) -> bool:
    """Valida CPF (11) ou CNPJ (14) pelos dígitos verificadores."""
    digitos = so_digitos(documento)
    if len(digitos) == 11:
        if digitos == digitos[0] * 11:
            return False
        return digitos[9:] == _digito_cpf(digitos)
    if len(digitos) == 14:
        if digitos == digitos[0] * 14:
            return False
        return digitos[12:] == _digito_cnpj(digitos)
    return False


def formatar_documento(documento: str | None) -> str:
    digitos = so_digitos(documento)
    if len(digitos) == 11:
        return f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"
    if len(digitos) == 14:
        return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"
    return documento or ""


# ----------------------------------------------------------------------- telefone


def normalizar_telefone(telefone: str | None, ddi_padrao: str = "55") -> str:
    """Devolve o número só com dígitos e DDI, pronto para o link do WhatsApp.

    Números brasileiros sem DDI recebem o 55; nada é inventado quando falta DDD.
    """
    digitos = so_digitos(telefone)
    if not digitos:
        return ""
    if digitos.startswith("00"):
        digitos = digitos[2:]
    if len(digitos) in (10, 11):  # DDD + número
        return ddi_padrao + digitos
    if len(digitos) in (8, 9):  # sem DDD: não há como completar
        return digitos
    return digitos


def formatar_telefone(telefone: str | None) -> str:
    digitos = so_digitos(telefone)
    if len(digitos) >= 12 and digitos.startswith("55"):
        ddi, resto = digitos[:2], digitos[2:]
        prefixo = f"+{ddi} "
    else:
        resto = digitos
        prefixo = ""
    if len(resto) == 11:
        return f"{prefixo}({resto[:2]}) {resto[2:7]}-{resto[7:]}"
    if len(resto) == 10:
        return f"{prefixo}({resto[:2]}) {resto[2:6]}-{resto[6:]}"
    if len(resto) == 9:
        return f"{prefixo}{resto[:5]}-{resto[5:]}"
    if len(resto) == 8:
        return f"{prefixo}{resto[:4]}-{resto[4:]}"
    return telefone or ""
