"""Enumerações do domínio, com rótulo em português para a interface.

Os valores gravados no banco são as chaves (``EM_ABERTO``), nunca o rótulo: o
texto da tela pode mudar sem migration.
"""

from __future__ import annotations

from enum import StrEnum


class _Rotulado(StrEnum):
    @property
    def rotulo(self) -> str:
        return ROTULOS.get(self, self.value.replace("_", " ").capitalize())

    @classmethod
    def opcoes(cls) -> list[tuple[_Rotulado, str]]:
        return [(item, item.rotulo) for item in cls]


class TipoPessoa(_Rotulado):
    PF = "PF"
    PJ = "PJ"


class SubtipoCliente(_Rotulado):
    NENHUM = "NENHUM"
    DOMESTICA = "DOMESTICA"


class SituacaoCliente(_Rotulado):
    ATIVO = "ATIVO"
    INATIVO = "INATIVO"
    SUSPENSO = "SUSPENSO"


class Periodicidade(_Rotulado):
    MENSAL = "MENSAL"
    TRIMESTRAL = "TRIMESTRAL"
    ANUAL = "ANUAL"
    AVULSO = "AVULSO"

    @property
    def meses(self) -> int | None:
        return {"MENSAL": 1, "TRIMESTRAL": 3, "ANUAL": 12}.get(self.value)


class ExigeCompetencia(_Rotulado):
    MES = "MES"
    ANO = "ANO"
    NENHUMA = "NENHUMA"


class StatusPagamento(_Rotulado):
    EM_ABERTO = "EM_ABERTO"
    PAGO = "PAGO"
    CANCELADO = "CANCELADO"
    RENEGOCIADO = "RENEGOCIADO"

    @property
    def gera_juros(self) -> bool:
        return self is StatusPagamento.EM_ABERTO

    @property
    def cobravel(self) -> bool:
        """Cancelado e renegociado não entram nas filas de cobrança."""
        return self is StatusPagamento.EM_ABERTO


class SituacaoEnvio(_Rotulado):
    NAO_ENVIADO = "NAO_ENVIADO"
    ENVIADO = "ENVIADO"


class MeioCobranca(_Rotulado):
    BOLETO = "BOLETO"
    PIX = "PIX"


class FormaPagamento(_Rotulado):
    PIX = "PIX"
    BOLETO = "BOLETO"
    DIRETO_ELOISA = "DIRETO_ELOISA"
    DINHEIRO = "DINHEIRO"
    OUTRO = "OUTRO"


class Canal(_Rotulado):
    WHATSAPP = "WHATSAPP"
    TELEFONE = "TELEFONE"
    EMAIL = "EMAIL"
    PRESENCIAL = "PRESENCIAL"
    OUTRO = "OUTRO"


class ResultadoCobranca(_Rotulado):
    AGUARDANDO = "AGUARDANDO"
    SEM_RESPOSTA = "SEM_RESPOSTA"
    PROMETEU_PAGAR = "PROMETEU_PAGAR"
    PEDIU_RENEGOCIACAO = "PEDIU_RENEGOCIACAO"
    CONTESTOU = "CONTESTOU"
    PAGOU = "PAGOU"
    OUTRO = "OUTRO"

    @property
    def exige_promessa(self) -> bool:
        return self is ResultadoCobranca.PROMETEU_PAGAR

    @property
    def respondida(self) -> bool:
        """A cobrança já teve retorno anotado."""
        return self is not ResultadoCobranca.AGUARDANDO


class TipoChavePix(_Rotulado):
    CNPJ = "CNPJ"
    CPF = "CPF"
    EMAIL = "EMAIL"
    TELEFONE = "TELEFONE"
    ALEATORIA = "ALEATORIA"


class OrdemSaudacao(_Rotulado):
    SAUDACAO_NOME = "SAUDACAO_NOME"
    NOME_SAUDACAO = "NOME_SAUDACAO"


class ChaveModelo(_Rotulado):
    UNIDADE = "UNIDADE"
    VARIOS = "VARIOS"
    LEMBRETE = "LEMBRETE"


class FormatoLinkWhatsapp(_Rotulado):
    WA_ME = "WA_ME"
    API_WHATSAPP = "API_WHATSAPP"
    PROTOCOLO = "PROTOCOLO"


ROTULOS: dict[_Rotulado, str] = {
    TipoPessoa.PF: "Pessoa física",
    TipoPessoa.PJ: "Pessoa jurídica",
    SubtipoCliente.NENHUM: "—",
    SubtipoCliente.DOMESTICA: "Doméstica",
    SituacaoCliente.ATIVO: "Ativo",
    SituacaoCliente.INATIVO: "Inativo",
    SituacaoCliente.SUSPENSO: "Suspenso",
    Periodicidade.MENSAL: "Mensal",
    Periodicidade.TRIMESTRAL: "Trimestral",
    Periodicidade.ANUAL: "Anual",
    Periodicidade.AVULSO: "Avulso",
    ExigeCompetencia.MES: "Mês e ano (08/2026)",
    ExigeCompetencia.ANO: "Somente ano (2026)",
    ExigeCompetencia.NENHUMA: "Sem competência",
    StatusPagamento.EM_ABERTO: "Em aberto",
    StatusPagamento.PAGO: "Pago",
    StatusPagamento.CANCELADO: "Cancelado",
    StatusPagamento.RENEGOCIADO: "Renegociado",
    SituacaoEnvio.NAO_ENVIADO: "Não enviado",
    SituacaoEnvio.ENVIADO: "Enviado para cliente",
    MeioCobranca.BOLETO: "Boleto",
    MeioCobranca.PIX: "Pix",
    FormaPagamento.PIX: "Pix",
    FormaPagamento.BOLETO: "Boleto",
    FormaPagamento.DIRETO_ELOISA: "Direto para Eloisa",
    FormaPagamento.DINHEIRO: "Dinheiro",
    FormaPagamento.OUTRO: "Outro",
    Canal.WHATSAPP: "WhatsApp",
    Canal.TELEFONE: "Telefone",
    Canal.EMAIL: "E-mail",
    Canal.PRESENCIAL: "Presencial",
    Canal.OUTRO: "Outro",
    ResultadoCobranca.AGUARDANDO: "Aguardando resposta",
    ResultadoCobranca.SEM_RESPOSTA: "Não respondeu",
    ResultadoCobranca.PROMETEU_PAGAR: "Prometeu pagar",
    ResultadoCobranca.PEDIU_RENEGOCIACAO: "Pediu renegociação",
    ResultadoCobranca.CONTESTOU: "Contestou o valor",
    ResultadoCobranca.PAGOU: "Pagou",
    ResultadoCobranca.OUTRO: "Outro",
    TipoChavePix.CNPJ: "CNPJ",
    TipoChavePix.CPF: "CPF",
    TipoChavePix.EMAIL: "E-mail",
    TipoChavePix.TELEFONE: "Telefone",
    TipoChavePix.ALEATORIA: "Chave aleatória",
    OrdemSaudacao.SAUDACAO_NOME: "Boa tarde, Carol!",
    OrdemSaudacao.NOME_SAUDACAO: "Carol, boa tarde!",
    ChaveModelo.UNIDADE: "Um honorário",
    ChaveModelo.VARIOS: "Vários honorários",
    ChaveModelo.LEMBRETE: "Lembrete antes do vencimento",
    FormatoLinkWhatsapp.WA_ME: "wa.me (recomendado)",
    FormatoLinkWhatsapp.API_WHATSAPP: "api.whatsapp.com",
    FormatoLinkWhatsapp.PROTOCOLO: "whatsapp:// (exige app instalado)",
}
