"""Popula o banco com dados fictícios para testar o sistema.

Nada aqui é dado real: nomes, CPF/CNPJ e telefones são inventados (os
documentos têm dígito verificador válido só para o cadastro aceitar, e os
telefones usam o prefixo 5527 9xxxx reservado para exemplos).

    .venv/bin/python scripts/dados_exemplo.py            # cria, se o banco estiver vazio
    .venv/bin/python scripts/dados_exemplo.py --limpar   # apaga tudo antes de criar

O conjunto cobre de propósito: atraso em todas as faixas, honorário que vence
hoje e outro que vence em breve, pagamento em dia, pago com atraso, pagamento
parcial, cancelado, renegociado, IRPF, avulsos, cobranças com promessa cumprida
e vencida, cliente nunca cobrado e cliente com mudança de juros no meio do ano.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import select  # noqa: E402

from honorarios.dominio.enums import (  # noqa: E402
    Canal,
    FormaPagamento,
    MeioCobranca,
    Periodicidade,
    ResultadoCobranca,
    SituacaoEnvio,
    SubtipoCliente,
    TipoPessoa,
)
from honorarios.dominio.valores import Competencia, dia_do_mes, hoje, somar_meses  # noqa: E402
from honorarios.infra import carga_inicial, db, esquema  # noqa: E402
from honorarios.infra.modelos import (  # noqa: E402
    AcordoValor,
    Cliente,
    ClienteContato,
    ClienteJuros,
    Cobranca,
    CobrancaLote,
    Contrato,
    ContratoHistorico,
    Honorario,
    Importacao,
    ImportacaoErro,
    LogAlteracao,
    Notificacao,
    Pagamento,
    Renegociacao,
    RenegociacaoItem,
    TipoHonorario,
)
from honorarios.servicos import (  # noqa: E402
    acompanhamento as servico_acompanhamento,
)
from honorarios.servicos import (
    clientes as servico_clientes,
)
from honorarios.servicos import (
    cobrancas as servico_cobrancas,
)
from honorarios.servicos import (
    contratos as servico_contratos,
)
from honorarios.servicos import (
    honorarios as servico_honorarios,
)
from honorarios.servicos import (
    pagamentos as servico_pagamentos,
)
from honorarios.servicos import (
    renegociacoes as servico_renegociacoes,
)

# --------------------------------------------------------------- documentos


def _digitos_cpf(base: str) -> str:
    def calcular(parcial: str, peso: int) -> str:
        soma = sum(int(d) * p for d, p in zip(parcial, range(peso, 1, -1), strict=True))
        resto = (soma * 10) % 11
        return str(resto if resto < 10 else 0)

    primeiro = calcular(base, 10)
    return primeiro + calcular(base + primeiro, 11)


def _digitos_cnpj(base: str) -> str:
    pesos = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]

    def calcular(parcial: str, lista: list[int]) -> str:
        soma = sum(int(d) * p for d, p in zip(parcial, lista, strict=True))
        resto = soma % 11
        return "0" if resto < 2 else str(11 - resto)

    primeiro = calcular(base, pesos)
    return primeiro + calcular(base + primeiro, [6, *pesos])


def cpf(base9: str) -> str:
    return base9 + _digitos_cpf(base9)


def cnpj(base12: str) -> str:
    return base12 + _digitos_cnpj(base12)


# ------------------------------------------------------------------ clientes

# código, nome, tipo, subtipo, documento, juros/dia, tratamento, telefone
PESSOAS = [
    ("301", "AURORA COMERCIO DE MOVEIS LTDA", TipoPessoa.PJ, SubtipoCliente.NENHUM,
     cnpj("112223330001"), "1.01", "Carol", "27999910001"),
    ("302", "JEQUITIBA INDUSTRIA E COMERCIO LTDA", TipoPessoa.PJ, SubtipoCliente.NENHUM,
     cnpj("223334440001"), "1.01", "Douglas", "27999910002"),
    ("303", "CV CONSULTORIA E COMUNICACAO LTDA", TipoPessoa.PJ, SubtipoCliente.NENHUM,
     cnpj("334445550001"), "0.40", "Renata", "27999910003"),
    ("304", "CLINICA VIDA PLENA LTDA", TipoPessoa.PJ, SubtipoCliente.NENHUM,
     cnpj("445556660001"), "1.67", "Dr. Oswaldo", "27999910004"),
    ("305", "PADARIA DOIS IRMAOS LTDA", TipoPessoa.PJ, SubtipoCliente.NENHUM,
     cnpj("556667770001"), "0.29", "Seu Manuel", "27999910005"),
    ("306", "TECNOLOGIA AMMARE LTDA", TipoPessoa.PJ, SubtipoCliente.NENHUM,
     cnpj("667778880001"), "0.27", "Bianca", "27999910006"),
    ("307", "TRANSPORTES SERRA AZUL LTDA", TipoPessoa.PJ, SubtipoCliente.NENHUM,
     cnpj("778889990001"), "2.16", "Marcelo", "27999910007"),
    ("308", "ESCOLA APRENDER MAIS LTDA", TipoPessoa.PJ, SubtipoCliente.NENHUM,
     cnpj("889990000001"), "0.54", "Solange", ""),
    ("401", "ANTONIO PEREIRA DOS SANTOS", TipoPessoa.PF, SubtipoCliente.NENHUM,
     cpf("529982247"), "0.34", "Antônio", "27999910011"),
    ("402", "BEATRIZ ALMEIDA COSTA", TipoPessoa.PF, SubtipoCliente.NENHUM,
     cpf("398117700"), "0.21", "Bia", "27999910012"),
    ("403", "CARLOS EDUARDO MARTINS", TipoPessoa.PF, SubtipoCliente.NENHUM,
     cpf("111444777"), "0.13", "Carlos", "27999910013"),
    ("404", "DANIELA ROCHA FERREIRA", TipoPessoa.PF, SubtipoCliente.NENHUM,
     cpf("280012389"), "0.11", "Dani", "27999910014"),
    ("501", "MARIA APARECIDA SOUZA", TipoPessoa.PF, SubtipoCliente.DOMESTICA,
     cpf("153122359"), "0.10", "Cida", "27999910021"),
    ("502", "JOSEFA LIMA DA CONCEICAO", TipoPessoa.PF, SubtipoCliente.DOMESTICA,
     cpf("764188942"), "0.08", "Josefa", "27999910022"),
    # clientes que só fazem imposto de renda com o escritório
    ("601", "ROBERTO ALVES LIMA", TipoPessoa.PF, SubtipoCliente.NENHUM,
     cpf("123456789"), "0.20", "Roberto", "27999910031"),
    ("602", "SANDRA MOURA CASTRO", TipoPessoa.PF, SubtipoCliente.NENHUM,
     cpf("987654321"), "0.15", "Sandra", "27999910032"),
    ("603", "PAULO HENRIQUE DIAS", TipoPessoa.PF, SubtipoCliente.NENHUM,
     cpf("246813579"), "0.30", "Paulo", "27999910033"),
]

# código do cliente, valor, dia de vencimento, periodicidade, suspenso
CONTRATOS = [
    ("301", "1507.80", 5, Periodicidade.MENSAL, False),
    ("302", "1507.80", 5, Periodicidade.MENSAL, False),
    ("303", "592.90", 8, Periodicidade.MENSAL, False),
    ("304", "2500.00", 6, Periodicidade.MENSAL, False),
    ("305", "435.00", 10, Periodicidade.MENSAL, False),
    ("306", "405.25", 10, Periodicidade.MENSAL, False),
    ("307", "3230.00", 15, Periodicidade.MENSAL, False),
    ("308", "810.00", 10, Periodicidade.MENSAL, True),   # suspenso temporariamente
    ("401", "505.00", 10, Periodicidade.MENSAL, False),
    ("402", "320.00", 10, Periodicidade.MENSAL, False),
    ("403", "660.00", 6, Periodicidade.TRIMESTRAL, False),
    ("404", "790.00", 25, Periodicidade.ANUAL, False),
    ("501", "165.00", 10, Periodicidade.MENSAL, False),
    ("502", "165.00", 10, Periodicidade.MENSAL, False),
]


def limpar(sessao) -> None:
    """Apaga tudo o que é movimento e cadastro, deixando só as listas base."""
    # a ordem segue as chaves estrangeiras: honorário aponta para renegociação,
    # então ele sai antes dela
    # o delete em massa não dispara o cascade do ORM, então a ordem das chaves
    # estrangeiras é explícita: filhos primeiro, cliente por último
    for modelo in (
        Cobranca, CobrancaLote, Pagamento, AcordoValor, RenegociacaoItem,
        ImportacaoErro, Importacao, Honorario, Renegociacao,
        ContratoHistorico, Contrato, ClienteContato, ClienteJuros,
        LogAlteracao, Notificacao, Cliente,
    ):
        sessao.query(modelo).delete()
    sessao.commit()


def tem_dados(sessao) -> bool:
    return sessao.scalar(select(Cliente).limit(1)) is not None


def criar_clientes(sessao) -> dict[str, Cliente]:
    criados: dict[str, Cliente] = {}
    for codigo, nome, tipo, subtipo, documento, juros, tratamento, telefone in PESSOAS:
        contatos = []
        if telefone:
            contatos.append(
                servico_clientes.DadosContato(
                    nome=f"{tratamento} ({nome.split()[0].title()})",
                    nome_tratamento=tratamento,
                    telefone=telefone,
                    email=f"{tratamento.lower().replace(' ', '.').replace('.', '')}@exemplo.com.br",
                    principal=True,
                )
            )
        cliente = servico_clientes.criar(
            sessao,
            servico_clientes.DadosCliente(
                codigo=codigo,
                nome=nome,
                documento=documento,
                tipo_pessoa=tipo,
                subtipo=subtipo,
                juros_dia=Decimal(juros),
                contatos=contatos,
                observacoes="Cliente de exemplo, criado pelo script de dados.",
            ),
        )
        # a taxa inicial passa a valer desde o começo do ano passado
        cliente.juros[0].vigencia_inicio = date(hoje().year - 1, 1, 1)
        cliente.juros[0].motivo = "Valor inicial do contrato"
        criados[codigo] = cliente
    sessao.commit()

    # um cliente com mudança de juros no meio do ano, para exercitar o histórico
    servico_clientes.registrar_juros(
        sessao, criados["304"], Decimal("2.00"), date(hoje().year, 6, 1),
        "Reajuste do boleto após aumento do honorário",
    )
    sessao.commit()
    return criados


def aplicar_vinculos(sessao, clientes: dict[str, Cliente]) -> None:
    """Uma pessoa física que paga os honorários pela empresa."""
    # o sócio da Clínica Vida Plena paga o IRPF dele pela empresa
    servico_clientes.atualizar(
        sessao,
        clientes["403"],
        servico_clientes.DadosCliente(
            codigo=clientes["403"].codigo,
            nome=clientes["403"].nome,
            documento=clientes["403"].documento,
            tipo_pessoa=clientes["403"].tipo_pessoa,
            subtipo=clientes["403"].subtipo,
            situacao=clientes["403"].situacao,
            observacoes=clientes["403"].observacoes,
            empresa_id=clientes["304"].id,
        ),
    )
    sessao.commit()


def suspender_cobranca_de_exemplo(sessao, clientes: dict[str, Cliente]) -> None:
    """Cliente cobrado, sem acordo, com a cobrança pausada por decisão do escritório.

    Fica por último porque no uso real a suspensão vem depois das cobranças.
    """
    servico_clientes.suspender_cobranca(
        sessao,
        clientes["501"],
        "Cliente internada; combinado retomar a cobrança em novembro.",
        ate=somar_meses(hoje(), 2),
    )
    sessao.commit()


def criar_contratos(sessao, clientes: dict[str, Cliente]) -> dict[str, Contrato]:
    tipos = {
        tipo.nome: tipo
        for tipo in sessao.scalars(select(TipoHonorario)).unique().all()
    }
    por_periodicidade = {
        Periodicidade.MENSAL: tipos["Honorário mensal"],
        Periodicidade.TRIMESTRAL: tipos["Honorário trimestral"],
        Periodicidade.ANUAL: tipos["Honorário anual"],
    }
    criados: dict[str, Contrato] = {}
    for codigo, valor, dia, periodicidade, suspenso in CONTRATOS:
        contrato = servico_contratos.criar(
            sessao,
            servico_contratos.DadosContrato(
                cliente_id=clientes[codigo].id,
                tipo_id=por_periodicidade[periodicidade].id,
                valor=Decimal(valor),
                periodicidade=periodicidade,
                dia_vencimento=dia,
                vigencia_inicio=date(hoje().year - 1, 1, 1),
                suspenso=suspenso,
                meio=MeioCobranca.BOLETO,
            ),
        )
        criados[codigo] = contrato
    sessao.commit()

    # um reajuste com histórico, valendo só daqui para frente
    servico_contratos.reajustar(
        sessao, criados["303"], Decimal("610.20"), date(hoje().year, 8, 1), "Reajuste anual (IPCA)"
    )
    sessao.commit()
    return criados


def gerar_competencias(sessao, meses: int = 9) -> None:
    """Gera as competências dos últimos meses, como o usuário faria na tela."""
    hoje_ = hoje()
    for recuo in range(meses, 0, -1):
        referencia = somar_meses(date(hoje_.year, hoje_.month, 1), -recuo)
        competencia = Competencia(referencia.year, referencia.month)
        previa = servico_contratos.previa_geracao(sessao, competencia)
        servico_contratos.gerar(sessao, previa)
        sessao.commit()


# quantos meses cada cliente deixa em aberto (0 = está em dia)
MESES_EM_ABERTO = {
    "301": 2,    # dois meses atrasados
    "302": 99,   # nunca pagou: dívida antiga, entra na faixa 90+
    "303": 1,
    "304": 1,
    "305": 2,    # um deles vira pagamento parcial
    "306": 1,
    "307": 99,   # devedor antigo, vai para a renegociação
    "308": 0,    # contrato suspenso, sem geração
    "401": 0,
    "402": 1,
    "403": 0,
    "404": 1,
    "501": 1,
    "502": 0,
}


# clientes que dão trabalho: quando atrasam, atrasam mais e precisam de várias
# cobranças até pagar (código → cobranças por honorário atrasado)
TRABALHOSOS = {"306": 3, "401": 2, "302": 2}


def _cobrar_antes_de_pagar(sessao, honorario: Honorario, pagamento: date, vezes: int) -> None:
    """Cobranças enviadas a cada semana de atraso, até o dia do pagamento."""
    for semana in range(vezes):
        dia = honorario.vencimento + timedelta(days=1 + semana * 7)
        if dia >= pagamento:
            break
        linhas = [
            linha
            for linha in servico_cobrancas.linhas_em_aberto_do_cliente(
                sessao, honorario.cliente_id, dia
            )
            if linha.honorario.id == honorario.id
        ]
        if not linhas:
            break
        selecao = servico_cobrancas.Selecao(
            cliente=honorario.cliente, linhas=linhas, data_referencia=dia,
            hora_referencia=time(10, 0),
        )
        servico_cobrancas.registrar(
            sessao,
            selecao,
            texto=servico_cobrancas.gerar_texto(sessao, selecao),
            canal=Canal.WHATSAPP,
            quando=datetime.combine(dia, time(10, 0)),
        )


def registrar_pagamentos(sessao) -> None:
    """Paga o histórico, deixando em aberto só o que cada cliente deve.

    A maioria fica em dia; alguns ficam com um ou dois meses; dois clientes
    arrastam dívida antiga, para as faixas de atraso e a renegociação terem
    conteúdo.
    """
    hoje_ = hoje()
    por_cliente: dict[int, list[Honorario]] = {}
    for honorario in sessao.scalars(select(Honorario)).unique().all():
        por_cliente.setdefault(honorario.cliente_id, []).append(honorario)

    for lista in por_cliente.values():
        lista.sort(key=lambda h: h.vencimento)
        codigo = lista[0].cliente.codigo
        deixar_aberto = MESES_EM_ABERTO.get(codigo, 0)
        a_pagar = lista if deixar_aberto == 0 else lista[: max(0, len(lista) - deixar_aberto)]
        for honorario in a_pagar:
            if honorario.vencimento > hoje_:
                continue
            # parte paga em dia, parte com alguns dias de atraso
            atraso = 0 if honorario.id % 3 else (honorario.id % 9) + 1
            vezes = TRABALHOSOS.get(codigo, 1)
            if atraso and codigo in TRABALHOSOS:
                atraso += 7 * vezes
            data_pagamento = min(honorario.vencimento + timedelta(days=atraso), hoje_)
            if atraso >= 3:
                _cobrar_antes_de_pagar(sessao, honorario, data_pagamento, vezes)
            previa = servico_pagamentos.previa(honorario, data_pagamento)
            servico_pagamentos.registrar(
                sessao,
                honorario,
                servico_pagamentos.DadosPagamento(
                    data=data_pagamento,
                    valor_pago=previa.total_devido,
                    forma_pagamento=FormaPagamento.PIX if atraso else FormaPagamento.BOLETO,
                ),
            )
    sessao.commit()

    # pagamento parcial: paga metade do principal e deixa saldo correndo juros
    parcial = sessao.scalars(
        select(Honorario)
        .join(Cliente)
        .where(Cliente.codigo == "305", Honorario.status == "EM_ABERTO")
        .order_by(Honorario.vencimento)
    ).first()
    if parcial is not None:
        data_parcial = max(parcial.vencimento, hoje_ - timedelta(days=12))
        previa = servico_pagamentos.previa(parcial, data_parcial)
        servico_pagamentos.registrar(
            sessao,
            parcial,
            servico_pagamentos.DadosPagamento(
                data=data_parcial,
                valor_pago=(parcial.valor_original / 2) + previa.juros_devidos,
                juros_cobrados=previa.juros_devidos,
                observacoes="Cliente pediu para dividir em duas vezes.",
            ),
        )
        sessao.commit()

    # pago com abono de juros, para aparecer na coluna de desconto
    abonado = sessao.scalars(
        select(Honorario)
        .join(Cliente)
        .where(Cliente.codigo == "306", Honorario.status == "EM_ABERTO")
        .order_by(Honorario.vencimento)
    ).first()
    if abonado is not None:
        previa = servico_pagamentos.previa(abonado, hoje_)
        servico_pagamentos.registrar(
            sessao,
            abonado,
            servico_pagamentos.DadosPagamento(
                data=hoje_,
                valor_pago=abonado.saldo_aberto,
                juros_cobrados=Decimal("0.00"),
                justificativa_desconto="Cliente antigo e pontual; juros abonado pela gerência.",
            ),
        )
        sessao.commit()


def datar_lancamentos(sessao) -> None:
    """Recua a data de criação dos honorários para a emissão do boleto.

    Só faz sentido em dados de exemplo: no uso real, ``criado_em`` é mesmo o
    momento do lançamento. Sem isso a linha do tempo mostra tudo criado hoje.
    """
    for honorario in sessao.scalars(select(Honorario)).unique().all():
        emissao = honorario.vencimento - timedelta(days=25)
        honorario.criado_em = datetime.combine(emissao, time(8, 0))
    sessao.commit()


def criar_avulsos(sessao, clientes: dict[str, Cliente]) -> None:
    """IRPF, serviços avulsos, um que vence hoje e um que vence em breve."""
    hoje_ = hoje()
    tipos = {
        tipo.nome: tipo
        for tipo in sessao.scalars(select(TipoHonorario)).unique().all()
    }

    # IRPF do ano, dois pagos e dois em aberto
    for codigo, valor, pago in (
        ("401", "550.00", True),
        ("402", "300.00", True),
        ("403", "256.63", False),
        ("404", "700.00", False),
    ):
        honorario = servico_honorarios.criar(
            sessao,
            servico_honorarios.DadosHonorario(
                cliente_id=clientes[codigo].id,
                tipo_id=tipos["Imposto de Renda"].id,
                valor=Decimal(valor),
                vencimento=date(hoje_.year, 6, 25),
                competencia=Competencia(hoje_.year),
                meio=MeioCobranca.BOLETO,
                situacao_envio=SituacaoEnvio.ENVIADO,
                enviado_em=date(hoje_.year, 6, 10),
            ),
        )
        if pago:
            previa = servico_pagamentos.previa(honorario, date(hoje_.year, 6, 25))
            servico_pagamentos.registrar(
                sessao,
                honorario,
                servico_pagamentos.DadosPagamento(
                    data=date(hoje_.year, 6, 25), valor_pago=previa.total_devido
                ),
            )
    sessao.commit()

    # clientes só de IR: um atrasado, um pago e um com parcela a vencer
    for codigo, valor, vencimento, ano, pago_em in (
        ("601", "450.00", date(hoje_.year, 6, 25), hoje_.year, None),
        ("602", "380.00", date(hoje_.year, 6, 25), hoje_.year, date(hoje_.year, 7, 2)),
        ("603", "520.00", hoje_ + timedelta(days=10), hoje_.year, None),
        ("603", "480.00", date(hoje_.year - 1, 6, 28), hoje_.year - 1,
         date(hoje_.year - 1, 6, 28)),
    ):
        honorario = servico_honorarios.criar(
            sessao,
            servico_honorarios.DadosHonorario(
                cliente_id=clientes[codigo].id,
                tipo_id=tipos["Imposto de Renda"].id,
                valor=Decimal(valor),
                vencimento=vencimento,
                competencia=Competencia(ano),
                meio=MeioCobranca.PIX,
            ),
        )
        if pago_em is not None:
            previa = servico_pagamentos.previa(honorario, pago_em)
            servico_pagamentos.registrar(
                sessao,
                honorario,
                servico_pagamentos.DadosPagamento(
                    data=pago_em, valor_pago=previa.total_devido,
                    forma_pagamento=FormaPagamento.PIX,
                ),
            )
    sessao.commit()

    # serviços avulsos
    avulsos = [
        ("301", "Alteração contratual", "763.08", hoje_ - timedelta(days=20),
         "Alteração contratual – entrada de sócio"),
        ("304", "Ata de Sócios", "600.00", hoje_ - timedelta(days=3),
         "Ata de assembleia de sócios"),
        ("306", "Certificado digital", "280.00", hoje_,
         "Certificado digital e-CNPJ A1"),           # vence hoje
        ("402", "Ganho de Capital", "1180.00", hoje_ + timedelta(days=4),
         "Apuração de ganho de capital na venda do imóvel"),  # vence em breve
    ]
    for codigo, tipo, valor, vencimento, descricao in avulsos:
        servico_honorarios.criar(
            sessao,
            servico_honorarios.DadosHonorario(
                cliente_id=clientes[codigo].id,
                tipo_id=tipos[tipo].id,
                valor=Decimal(valor),
                vencimento=vencimento,
                descricao=descricao,
                meio=MeioCobranca.PIX if tipo == "Certificado digital" else MeioCobranca.BOLETO,
            ),
        )
    sessao.commit()

    # um cancelado, com motivo
    cancelado = servico_honorarios.criar(
        sessao,
        servico_honorarios.DadosHonorario(
            cliente_id=clientes["305"].id,
            tipo_id=tipos["Ata de Sócios"].id,
            valor=Decimal("450.00"),
            vencimento=hoje_ - timedelta(days=40),
            descricao="Ata de sócios (serviço não realizado)",
        ),
    )
    servico_honorarios.cancelar(
        sessao, cancelado, "Cliente desistiu do serviço antes da execução."
    )
    sessao.commit()


def criar_cobrancas(sessao, clientes: dict[str, Cliente]) -> None:
    """Cobranças reais, com a mensagem gerada pelo próprio sistema."""
    hoje_ = hoje()
    roteiro = [
        # código, dias atrás, resultado, promessa (dias a partir de hoje), observação
        # resultado AGUARDANDO = cobrança enviada e ainda sem resposta anotada
        ("302", 12, ResultadoCobranca.SEM_RESPOSTA, None, ""),
        ("302", 5, ResultadoCobranca.PROMETEU_PAGAR, -2,
         "Disse que pagaria após receber de um cliente."),          # promessa vencida
        ("307", 20, ResultadoCobranca.SEM_RESPOSTA, None, ""),
        ("307", 9, ResultadoCobranca.PEDIU_RENEGOCIACAO, None,
         "Pediu parcelamento do total em aberto."),
        ("301", 6, ResultadoCobranca.PROMETEU_PAGAR, 5,
         "Financeiro pediu boleto atualizado."),                    # promessa em aberto
        ("304", 15, ResultadoCobranca.CONTESTOU, None,
         "Questionou o valor do honorário de julho."),
        ("501", 8, ResultadoCobranca.AGUARDANDO, None, ""),         # sem resposta anotada
        ("305", 2, ResultadoCobranca.AGUARDANDO, None, ""),         # cobrado ontem
        ("402", 1, ResultadoCobranca.AGUARDANDO, None, ""),
    ]
    for codigo, dias, resultado, promessa, observacao in roteiro:
        cliente = clientes[codigo]
        referencia = hoje_ - timedelta(days=dias)
        linhas = servico_cobrancas.linhas_em_aberto_do_cliente(sessao, cliente.id, referencia)
        linhas = [linha for linha in linhas if linha.honorario.vencimento < referencia]
        if not linhas:
            continue
        selecao = servico_cobrancas.Selecao(
            cliente=cliente,
            linhas=linhas,
            data_referencia=referencia,
            hora_referencia=time(9, 30) if dias % 2 else time(14, 20),
        )
        texto = servico_cobrancas.gerar_texto(sessao, selecao)
        # a cobrança nasce aguardando resposta, como no uso real
        lote = servico_cobrancas.registrar(
            sessao,
            selecao,
            texto=texto,
            canal=Canal.WHATSAPP,
            quando=datetime.combine(referencia, time(9, 30)),
        )
        if resultado is not ResultadoCobranca.AGUARDANDO:
            servico_acompanhamento.registrar_resposta(
                sessao,
                servico_acompanhamento.linha_do_lote(sessao, lote),
                resultado,
                hoje_ + timedelta(days=promessa) if promessa is not None else None,
                observacao,
            )
    sessao.commit()


def criar_renegociacao(sessao, clientes: dict[str, Cliente]) -> None:
    """Acordo fechado com o cliente que pediu parcelamento."""
    tipos = {
        tipo.nome: tipo
        for tipo in sessao.scalars(select(TipoHonorario)).unique().all()
    }
    cliente = clientes["307"]
    linhas = servico_cobrancas.linhas_em_aberto_do_cliente(sessao, cliente.id)
    antigos = [linha for linha in linhas if linha.atualizacao.dias_atraso > 150]
    if len(antigos) < 2:
        return
    total = sum((linha.atualizacao.total for linha in antigos), start=Decimal("0.00"))
    servico_renegociacoes.criar(
        sessao,
        cliente=cliente,
        linhas=antigos,
        valor_acordado=(total * Decimal("0.9")).quantize(Decimal("0.01")),
        desconto=(total * Decimal("0.1")).quantize(Decimal("0.01")),
        parcelas=3,
        primeiro_vencimento=dia_do_mes(hoje().year, hoje().month, 20),
        tipo_id=tipos["Honorário mensal"].id,
        observacoes="Acordo fechado por telefone com o sócio administrador.",
    )
    sessao.commit()


def resumo(sessao) -> str:
    from honorarios.servicos.honorarios import Filtro

    pendentes = servico_honorarios.pendentes(sessao, Filtro())
    pagos = servico_honorarios.pagos(sessao, Filtro())
    cobrancas = sessao.query(Cobranca).count()
    return (
        f"{sessao.query(Cliente).count()} clientes · "
        f"{sessao.query(Contrato).count()} contratos · "
        f"{sessao.query(Honorario).count()} honorários "
        f"({len(pendentes)} em aberto, {len(pagos)} pagos) · "
        f"{cobrancas} cobranças · "
        f"total em aberto {servico_honorarios.total_de(pendentes)}"
    )


def main() -> int:
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument(
        "--limpar", action="store_true", help="apaga os dados existentes antes de criar"
    )
    argumentos = analisador.parse_args()

    esquema.preparar()
    with db.transacao() as sessao:
        carga_inicial.aplicar(sessao)

    sessao = db.sessao()
    if tem_dados(sessao):
        if not argumentos.limpar:
            print(
                "O banco já tem clientes cadastrados. Rode com --limpar para apagar "
                "tudo e recriar os dados de exemplo."
            )
            return 1
        limpar(sessao)

    clientes = criar_clientes(sessao)
    aplicar_vinculos(sessao, clientes)
    criar_contratos(sessao, clientes)
    gerar_competencias(sessao)
    registrar_pagamentos(sessao)
    criar_avulsos(sessao, clientes)
    criar_cobrancas(sessao, clientes)
    criar_renegociacao(sessao, clientes)
    suspender_cobranca_de_exemplo(sessao, clientes)
    datar_lancamentos(sessao)

    print("Dados de exemplo criados.")
    print(resumo(sessao))
    sessao.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
