"""Contatos dos clientes: um por um e em lote, cruzando uma lista com o cadastro.

**Em lote.** Chega uma lista de contatos das empresas (quem é o responsável, o
telefone, o e-mail). Cada item diz de qual empresa é por algum "número" que o
cadastro conhece — o código do cliente, o CPF/CNPJ, um telefone que a empresa já
tem cadastrado — ou, por último, pelo nome exato. ``cruzar`` acha o cliente de
cada item e decide o que fazer, sem gravar nada; ``gravar`` aplica o que o
cruzamento decidiu. Item sem empresa encontrada, ou que bate com mais de uma, não
grava nada: volta na lista com o motivo.

**Telefone igual é o mesmo contato.** O telefone é comparado pelo DDD e pelos 8
últimos dígitos, então "27 99999-0000", "+55 (27) 9 9999-0000" e o número antigo
sem o 9 são o mesmo. Contato que já existe é atualizado (só o que vier
preenchido); senão, entra como novo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..dominio.valores import normalizar_busca, normalizar_telefone, so_digitos
from ..infra.modelos import Cliente, ClienteContato, LogAlteracao
from .erros import ErroDeValidacao

# ------------------------------------------------------------------- telefone


def chave_telefone(telefone: str | None) -> tuple[str, str] | None:
    """(DDD, 8 últimos dígitos): o mesmo número com ou sem 55, com ou sem o 9."""
    digitos = so_digitos(telefone)
    if digitos.startswith("00"):
        digitos = digitos[2:]
    if len(digitos) in (12, 13) and digitos.startswith("55"):
        digitos = digitos[2:]
    if len(digitos) < 8:
        return None
    ddd = digitos[:2] if len(digitos) in (10, 11) else ""
    return ddd, digitos[-8:]


def mesmo_telefone(um: str | None, outro: str | None) -> bool:
    a, b = chave_telefone(um), chave_telefone(outro)
    if a is None or b is None or a[1] != b[1]:
        return False
    return not a[0] or not b[0] or a[0] == b[0]   # sem DDD de um lado: vale o número


# ------------------------------------------------------------------ um por um


def _registrar(sessao: Session, cliente: Cliente, resumo: str) -> None:
    sessao.add(LogAlteracao(entidade="cliente_contato", entidade_id=cliente.id,
                            acao="CONTATO", resumo=f"{cliente.nome}: {resumo}"))


def _garantir_principal(cliente: Cliente, escolhido: ClienteContato | None = None) -> None:
    """Um principal só entre os ativos: o escolhido, o que já era, ou o primeiro."""
    ativos = [c for c in cliente.contatos if c.ativo]
    if escolhido is not None and escolhido.ativo:
        principal = escolhido
    else:
        principal = next((c for c in ativos if c.principal), ativos[0] if ativos else None)
    for contato in cliente.contatos:
        contato.principal = contato is principal


def adicionar(
    sessao: Session,
    cliente: Cliente,
    nome: str = "",
    tratamento: str = "",
    telefone: str = "",
    email: str = "",
    observacoes: str = "",
    principal: bool = False,
) -> ClienteContato:
    if not (nome or "").strip() and not so_digitos(telefone) and not (email or "").strip():
        raise ErroDeValidacao("Informe o nome, o telefone ou o e-mail do contato.")
    if telefone and any(c.ativo and mesmo_telefone(c.telefone, telefone)
                        for c in cliente.contatos):
        raise ErroDeValidacao(
            f"{cliente.nome} já tem um contato com o telefone {telefone}: atualize esse."
        )
    contato = ClienteContato(
        nome=(nome or "").strip(), nome_tratamento=(tratamento or "").strip(),
        telefone=normalizar_telefone(telefone), email=(email or "").strip(),
        observacoes=observacoes or "", ativo=True,
    )
    cliente.contatos.append(contato)
    _garantir_principal(cliente, contato if principal else None)
    _registrar(sessao, cliente, f"contato novo {contato.nome or contato.telefone}")
    sessao.flush()
    return contato


def atualizar(
    sessao: Session,
    contato: ClienteContato,
    nome: str | None = None,
    tratamento: str | None = None,
    telefone: str | None = None,
    email: str | None = None,
    observacoes: str | None = None,
    principal: bool | None = None,
    ativo: bool | None = None,
) -> list[str]:
    """Muda só o que veio (None = não mexe). Devolve o que mudou."""
    novos = {
        "nome": None if nome is None else nome.strip(),
        "nome_tratamento": None if tratamento is None else tratamento.strip(),
        "telefone": None if telefone is None else normalizar_telefone(telefone),
        "email": None if email is None else email.strip(),
        "observacoes": observacoes,
        "ativo": ativo,
    }
    mudou = []
    for campo, valor in novos.items():
        if valor is not None and getattr(contato, campo) != valor:
            setattr(contato, campo, valor)
            mudou.append(campo)
    cliente = contato.cliente
    if principal and not contato.principal:
        mudou.append("principal")
    _garantir_principal(cliente, contato if principal else None)
    if mudou:
        _registrar(sessao, cliente, f"contato {contato.nome or contato.telefone}: "
                   + ", ".join(mudou))
    sessao.flush()
    return mudou


def remover(sessao: Session, contato: ClienteContato) -> None:
    cliente = contato.cliente
    cliente.contatos.remove(contato)   # delete-orphan apaga do banco
    _garantir_principal(cliente)
    _registrar(sessao, cliente, f"contato removido {contato.nome or contato.telefone}")
    sessao.flush()


# ---------------------------------------------------------------------- lote


@dataclass
class ItemContato:
    """Uma linha da lista: como achar a empresa e os dados do responsável."""

    codigo: str = ""              # código do cliente no sistema
    documento: str = ""           # CPF/CNPJ da empresa
    telefone_empresa: str = ""    # um telefone que a empresa já tem cadastrado
    nome_empresa: str = ""        # nome exato (sem acento e caixa)
    nome: str = ""                # do responsável
    tratamento: str = ""
    telefone: str = ""
    email: str = ""
    observacoes: str = ""
    principal: bool = False


@dataclass
class Cruzamento:
    indice: int
    item: ItemContato
    cliente: Cliente | None = None
    achado_por: str = ""                 # código, CPF/CNPJ, telefone ou nome
    contato: ClienteContato | None = None  # o que já existe e vai ser atualizado
    acao: str = ""                       # novo, atualizar, sem mudança, ignorado
    mudancas: list[str] = field(default_factory=list)
    motivo: str = ""

    @property
    def grava(self) -> bool:
        return self.acao in ("novo", "atualizar")


class _Cadastro:
    """Os clientes e os telefones deles, lidos uma vez para cruzar a lista toda."""

    def __init__(self, sessao: Session) -> None:
        self.clientes = list(sessao.scalars(
            select(Cliente).where(Cliente.excluido_em.is_(None))).unique())
        self.por_codigo = {c.codigo.strip(): c for c in self.clientes}
        self.por_documento = {c.documento: c for c in self.clientes if c.documento}
        self.por_nome: dict[str, list[Cliente]] = {}
        for cliente in self.clientes:
            self.por_nome.setdefault(cliente.nome_busca, []).append(cliente)

    def por_telefone(self, telefone: str) -> list[Cliente]:
        return [c for c in self.clientes
                if any(x.ativo and mesmo_telefone(x.telefone, telefone) for x in c.contatos)]


def _achar(cadastro: _Cadastro, item: ItemContato) -> tuple[Cliente | None, str, str]:
    """(cliente, por onde achou, motivo de não achar)."""
    if item.codigo.strip():
        cliente = cadastro.por_codigo.get(item.codigo.strip())
        if cliente is not None:
            return cliente, "código", ""
    if so_digitos(item.documento):
        cliente = cadastro.por_documento.get(so_digitos(item.documento))
        if cliente is not None:
            return cliente, "CPF/CNPJ", ""
    if chave_telefone(item.telefone_empresa):
        achados = cadastro.por_telefone(item.telefone_empresa)
        if len(achados) == 1:
            return achados[0], "telefone", ""
        if len(achados) > 1:
            nomes = ", ".join(f"{c.codigo} {c.nome}" for c in achados[:5])
            return None, "", f"o telefone {item.telefone_empresa} está em mais de um " \
                             f"cliente ({nomes})"
    if item.nome_empresa.strip():
        achados = cadastro.por_nome.get(normalizar_busca(item.nome_empresa), [])
        if len(achados) == 1:
            return achados[0], "nome", ""
        if len(achados) > 1:
            return None, "", f"há {len(achados)} clientes com o nome {item.nome_empresa}"
    procurado = [x for x in (item.codigo, item.documento, item.telefone_empresa,
                             item.nome_empresa) if x and x.strip()]
    if not procurado:
        return None, "", "a linha não diz de qual empresa é (código, CPF/CNPJ, telefone " \
                         "ou nome)"
    return None, "", "nenhum cliente com " + " / ".join(procurado)


def _contato_existente(cliente: Cliente, item: ItemContato) -> ClienteContato | None:
    if chave_telefone(item.telefone):
        return next((c for c in cliente.contatos if mesmo_telefone(c.telefone, item.telefone)),
                    None)
    if item.nome.strip():   # sem telefone: o mesmo nome é o mesmo contato
        alvo = normalizar_busca(item.nome)
        return next((c for c in cliente.contatos if normalizar_busca(c.nome) == alvo), None)
    return None


def _mudancas(contato: ClienteContato, item: ItemContato) -> list[str]:
    mudou = []
    if item.nome.strip() and contato.nome != item.nome.strip():
        mudou.append("nome")
    if item.tratamento.strip() and contato.nome_tratamento != item.tratamento.strip():
        mudou.append("tratamento")
    if chave_telefone(item.telefone) and contato.telefone != normalizar_telefone(item.telefone):
        mudou.append("telefone")
    if item.email.strip() and contato.email != item.email.strip():
        mudou.append("e-mail")
    if item.observacoes.strip() and item.observacoes.strip() not in (contato.observacoes or ""):
        mudou.append("observações")
    if not contato.ativo:
        mudou.append("reativado")
    if item.principal and not contato.principal:
        mudou.append("principal")
    return mudou


def cruzar(sessao: Session, itens: list[ItemContato]) -> list[Cruzamento]:
    """Acha a empresa de cada item e decide o que fazer. Não grava nada."""
    cadastro = _Cadastro(sessao)
    vistos: set[tuple[int, object]] = set()
    resultado = []
    for indice, item in enumerate(itens, start=1):
        cruzamento = Cruzamento(indice, item)
        resultado.append(cruzamento)
        cliente, achado_por, motivo = _achar(cadastro, item)
        if cliente is None:
            cruzamento.acao, cruzamento.motivo = "ignorado", motivo
            continue
        cruzamento.cliente, cruzamento.achado_por = cliente, achado_por
        if not (item.nome.strip() or chave_telefone(item.telefone) or item.email.strip()):
            cruzamento.acao = "ignorado"
            cruzamento.motivo = "sem nome, telefone nem e-mail do responsável"
            continue
        if item.telefone.strip() and not chave_telefone(item.telefone):
            cruzamento.acao, cruzamento.motivo = "ignorado", f"telefone inválido: {item.telefone}"
            continue
        repetido = (cliente.id, chave_telefone(item.telefone) or normalizar_busca(item.nome))
        if repetido in vistos:
            cruzamento.acao, cruzamento.motivo = "ignorado", "repetido na lista"
            continue
        vistos.add(repetido)
        contato = _contato_existente(cliente, item)
        if contato is None:
            cruzamento.acao = "novo"
            continue
        cruzamento.contato = contato
        cruzamento.mudancas = _mudancas(contato, item)
        cruzamento.acao = "atualizar" if cruzamento.mudancas else "sem mudança"
    return resultado


def gravar(sessao: Session, cruzamentos: list[Cruzamento]) -> int:
    """Aplica o que ``cruzar`` decidiu; devolve quantos contatos foram gravados."""
    gravados = 0
    for cruzamento in cruzamentos:
        if not cruzamento.grava:
            continue
        item, cliente = cruzamento.item, cruzamento.cliente
        if cruzamento.acao == "novo":
            adicionar(sessao, cliente, item.nome, item.tratamento, item.telefone, item.email,
                      item.observacoes, item.principal)
        else:
            contato = cruzamento.contato
            observacoes = None
            if item.observacoes.strip() and item.observacoes.strip() not in contato.observacoes:
                observacoes = f"{contato.observacoes}\n{item.observacoes.strip()}".strip()
            atualizar(
                sessao, contato,
                nome=item.nome or None, tratamento=item.tratamento or None,
                telefone=item.telefone if chave_telefone(item.telefone) else None,
                email=item.email or None, observacoes=observacoes,
                principal=item.principal or None, ativo=True,
            )
        gravados += 1
    return gravados
