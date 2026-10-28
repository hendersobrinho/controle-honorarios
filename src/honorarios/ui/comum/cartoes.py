"""Lista de registros em cartões, com faixa colorida indicando a situação.

Cada registro é um cartão: faixa de cor à esquerda (vermelho em atraso, âmbar
pedindo atenção, verde resolvido), título, detalhes rotulados, valor em destaque
e os botões daquele registro. Os cartões ficam agrupados em seções recolhíveis
com quantidade e subtotal.

Para não criar centenas de widgets, cada seção mostra um limite de cartões e
oferece "mostrar mais" — o resto só entra na tela quando é pedido.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

LIMITE_PADRAO = 30
ORCAMENTO_PADRAO = 90
LARGURA_DETALHE = 240
LARGURA_SUBTITULO = 620


def _encurtar(texto: str, largura: int) -> str:
    """Corta o texto no tamanho que cabe, guardando o inteiro na dica."""
    limite = max(12, largura // 7)
    if len(texto) <= limite:
        return texto
    return texto[: limite - 1].rstrip() + "…"


@dataclass
class Acao:
    """Botão que aparece no próprio cartão."""

    texto: str
    funcao: Callable[[Any], None]
    dica: str = ""
    primaria: bool = False
    pagamento: bool = False   # verde: a ação que resolve o honorário


@dataclass
class DataCartao:
    """Data em destaque no cartão: pílula com o rótulo e a data em negrito."""

    rotulo: str
    valor: str
    cor: QColor | None = None


@dataclass
class DadosCartao:
    titulo: str
    subtitulo: str = ""
    detalhes: list[tuple[str, str]] = field(default_factory=list)
    valor: str = ""
    valor_rotulo: str = ""
    complemento: str = ""
    situacao: str = ""
    cor: QColor | None = None
    item: Any = None
    acoes: list[Acao] = field(default_factory=list)
    datas: list[DataCartao] = field(default_factory=list)


@dataclass
class SecaoCartoes:
    """Uma seção da lista.

    Guarda os itens de domínio e a função que monta o cartão. O cartão só é
    construído quando vai ser desenhado — formatar centenas de registros que
    ninguém vê é o que fazia a tela demorar.
    """

    titulo: str
    itens: Sequence[Any] = field(default_factory=list)
    construtor: Callable[[Any], DadosCartao] | None = None
    subtitulo: str = ""
    total: str = ""
    mostrar_titulo: bool = True   # False: os cartões entram sem o cabeçalho da seção

    def cartao(self, item: Any) -> DadosCartao:
        if self.construtor is None:
            return item if isinstance(item, DadosCartao) else DadosCartao(titulo=str(item))
        return self.construtor(item)

    @property
    def quantidade(self) -> int:
        return len(self.itens)

    @property
    def cartoes(self) -> list[DadosCartao]:
        """Todos os cartões da seção. A tela usa só a fatia visível."""
        return [self.cartao(item) for item in self.itens]


def _estilo_pilula(cor: QColor, preenchida: bool = False) -> str:
    """Fundo tingido com a cor da situação; a borda e o texto na própria cor."""
    alfa = 0.16 if preenchida else 0.09
    return (
        f"background: rgba({cor.red()}, {cor.green()}, {cor.blue()}, {alfa});"
        f"border: 1px solid rgba({cor.red()}, {cor.green()}, {cor.blue()}, 0.55);"
        f"color: {cor.name()};"
    )


class CartaoRegistro(QFrame):
    """Um registro. Clicar seleciona; clicar segurando Ctrl acrescenta à seleção."""

    clicado = Signal(object, bool)   # item, somar à seleção
    duplo_clique = Signal(object)

    def __init__(self, dados: DadosCartao, parent=None) -> None:
        super().__init__(parent)
        self.dados = dados
        self.setObjectName("cartaoRegistro")
        self.setProperty("selecionado", False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._montar()

    def _montar(self) -> None:
        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(0, 0, 12, 0)
        raiz.setSpacing(12)

        self.faixa = QFrame()
        self.faixa.setFixedWidth(5)
        self.faixa.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        cor = self.dados.cor.name() if self.dados.cor else "transparent"
        self.faixa.setStyleSheet(
            f"background: {cor}; border-top-left-radius: 8px; border-bottom-left-radius: 8px;"
        )
        raiz.addWidget(self.faixa)

        texto = QVBoxLayout()
        texto.setContentsMargins(0, 10, 0, 10)
        texto.setSpacing(3)

        primeira = QHBoxLayout()
        primeira.setSpacing(8)
        titulo = QLabel(self.dados.titulo)
        titulo.setObjectName("cartaoTitulo")
        primeira.addWidget(titulo)
        if self.dados.situacao:
            etiqueta = QLabel(self.dados.situacao)
            etiqueta.setObjectName("cartaoEtiqueta")
            if self.dados.cor:
                etiqueta.setStyleSheet(_estilo_pilula(self.dados.cor, preenchida=True))
            primeira.addWidget(etiqueta)
        primeira.addStretch(1)
        texto.addLayout(primeira)

        if self.dados.datas:
            datas = QHBoxLayout()
            datas.setSpacing(6)
            datas.setContentsMargins(0, 2, 0, 2)
            for data in self.dados.datas:
                pilula = QLabel(
                    f"<span style='font-size:10px'>{data.rotulo}</span>"
                    f"&nbsp;<b>{data.valor}</b>"
                )
                pilula.setObjectName("cartaoData")
                pilula.setTextFormat(Qt.TextFormat.RichText)
                if data.cor:
                    pilula.setStyleSheet(_estilo_pilula(data.cor))
                datas.addWidget(pilula)
            datas.addStretch(1)
            texto.addLayout(datas)

        if self.dados.subtitulo:
            subtitulo = QLabel(_encurtar(self.dados.subtitulo, LARGURA_SUBTITULO))
            subtitulo.setObjectName("cartaoSubtitulo")
            subtitulo.setToolTip(self.dados.subtitulo)
            texto.addWidget(subtitulo)

        if self.dados.detalhes:
            detalhes = QHBoxLayout()
            detalhes.setSpacing(18)
            for rotulo, valor in self.dados.detalhes:
                bloco = QVBoxLayout()
                bloco.setSpacing(0)
                etiqueta = QLabel(rotulo)
                etiqueta.setObjectName("cartaoDetalheRotulo")
                conteudo = QLabel(_encurtar(valor or "—", LARGURA_DETALHE))
                conteudo.setObjectName("cartaoDetalheValor")
                conteudo.setMaximumWidth(LARGURA_DETALHE)
                if valor:
                    conteudo.setToolTip(valor)
                bloco.addWidget(etiqueta)
                bloco.addWidget(conteudo)
                detalhes.addLayout(bloco)
            detalhes.addStretch(1)
            texto.addLayout(detalhes)
        raiz.addLayout(texto, 1)

        if self.dados.valor:
            direita = QVBoxLayout()
            direita.setContentsMargins(0, 10, 0, 10)
            direita.setSpacing(0)
            direita.addStretch(1)
            if self.dados.valor_rotulo:
                rotulo = QLabel(self.dados.valor_rotulo)
                rotulo.setObjectName("cartaoDetalheRotulo")
                rotulo.setAlignment(Qt.AlignmentFlag.AlignRight)
                direita.addWidget(rotulo)
            valor = QLabel(self.dados.valor)
            valor.setObjectName("cartaoValor")
            valor.setAlignment(Qt.AlignmentFlag.AlignRight)
            direita.addWidget(valor)
            if self.dados.complemento:
                complemento = QLabel(self.dados.complemento)
                complemento.setObjectName("cartaoDetalheRotulo")
                complemento.setAlignment(Qt.AlignmentFlag.AlignRight)
                direita.addWidget(complemento)
            direita.addStretch(1)
            raiz.addLayout(direita)

        if self.dados.acoes:
            botoes = QVBoxLayout()
            botoes.setContentsMargins(0, 10, 0, 10)
            botoes.setSpacing(4)
            botoes.addStretch(1)
            for acao in self.dados.acoes:
                botao = QPushButton(acao.texto)
                if acao.pagamento:
                    botao.setObjectName("cartaoPagamento")
                else:
                    botao.setObjectName("cartaoAcao" if not acao.primaria else "primario")
                botao.setCursor(Qt.CursorShape.PointingHandCursor)
                if acao.dica:
                    botao.setToolTip(acao.dica)
                botao.clicked.connect(
                    lambda _=False, funcao=acao.funcao: funcao(self.dados.item)
                )
                botoes.addWidget(botao)
            botoes.addStretch(1)
            raiz.addLayout(botoes)

    def definir_selecionado(self, selecionado: bool) -> None:
        self.setProperty("selecionado", selecionado)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, evento) -> None:  # noqa: N802
        somar = bool(evento.modifiers() & Qt.KeyboardModifier.ControlModifier)
        self.clicado.emit(self.dados.item, somar)
        super().mousePressEvent(evento)

    def mouseDoubleClickEvent(self, evento) -> None:  # noqa: N802
        self.duplo_clique.emit(self.dados.item)
        super().mouseDoubleClickEvent(evento)


class PainelDeCartoes(QScrollArea):
    """Área rolável com as seções e seus cartões."""

    selecao_mudou = Signal()
    item_ativado = Signal(object)

    def __init__(
        self,
        vazio: str = "Nada por aqui.",
        limite_secao: int = LIMITE_PADRAO,
        orcamento: int = ORCAMENTO_PADRAO,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._limite_secao = limite_secao
        self._orcamento = orcamento
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # o cartão nunca empurra a lista para os lados: texto longo é encurtado
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._texto_vazio = vazio
        self._selecionados: list[Any] = []
        self._cartoes: dict[int, CartaoRegistro] = {}
        self._limites: dict[str, int] = {}
        self._secoes: list[SecaoCartoes] = []

        self._conteudo = QWidget()
        self._layout = QVBoxLayout(self._conteudo)
        self._layout.setContentsMargins(2, 2, 6, 2)
        self._layout.setSpacing(8)
        self.setWidget(self._conteudo)

    # ------------------------------------------------------------------ dados
    def definir_secoes(
        self, secoes: Sequence[SecaoCartoes], preservar_selecao: bool = True
    ) -> None:
        anteriores = {id(item) for item in self._selecionados} if preservar_selecao else set()
        self._secoes = list(secoes)
        self._limites = {
            secao.titulo: self._limites.get(secao.titulo, self._limite_secao)
            for secao in secoes
        }
        # um redesenho só: sem isso cada cartão novo repinta a lista inteira
        self.setUpdatesEnabled(False)
        try:
            self._redesenhar()
        finally:
            self.setUpdatesEnabled(True)
        if preservar_selecao:
            self._selecionados = [
                cartao.dados.item
                for cartao in self._cartoes.values()
                if id(cartao.dados.item) in anteriores
            ]
        else:
            self._selecionados = []
        self._pintar_selecao()
        self.selecao_mudou.emit()

    def _limpar(self) -> None:
        # tirar do layout não basta: sem soltar o pai, o widget continua desenhado
        # até o Qt processar o deleteLater, e sobram fantasmas na tela
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # esconder antes de soltar o pai: um widget sem pai vira janela
                # própria, e sem o hide() ela chega a piscar na tela
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._cartoes.clear()

    def _redesenhar(self) -> None:
        self._limpar()
        if not any(secao.quantidade for secao in self._secoes):
            vazio = QLabel(self._texto_vazio)
            vazio.setObjectName("subtitulo")
            vazio.setAlignment(Qt.AlignmentFlag.AlignCenter)
            vazio.setMinimumHeight(120)
            self._layout.addWidget(vazio)
            self._layout.addStretch(1)
            return

        # orçamento de cartões desenhados: seções seguintes entram recolhidas,
        # com o botão de mostrar, em vez de criar centenas de widgets de uma vez
        restante = self._orcamento
        for secao in self._secoes:
            if not secao.quantidade:
                continue
            if secao.mostrar_titulo:
                self._layout.addWidget(self._cabecalho(secao))
            limite = min(self._limites.get(secao.titulo, self._limite_secao), max(0, restante))
            # o orçamento desconta o que foi desenhado de fato, não o limite da
            # seção: seções pequenas não podem consumir o espaço das seguintes
            desenhar = min(limite, secao.quantidade)
            for item in secao.itens[:desenhar]:
                dados = secao.cartao(item)
                cartao = CartaoRegistro(dados)
                cartao.clicado.connect(self._ao_clicar)
                cartao.duplo_clique.connect(self.item_ativado.emit)
                self._cartoes[id(dados.item)] = cartao
                self._layout.addWidget(cartao)
            restante -= desenhar
            faltam = secao.quantidade - desenhar
            if faltam > 0:
                passo = min(faltam, self._limite_secao)
                mais = QPushButton(f"Mostrar mais {passo} de {faltam}")
                mais.setObjectName("cartaoAcao")
                mais.clicked.connect(
                    lambda _=False, titulo=secao.titulo, passo=passo: self._mostrar_mais(
                        titulo, passo
                    )
                )
                self._layout.addWidget(mais)
        self._layout.addStretch(1)

    def _cabecalho(self, secao: SecaoCartoes) -> QWidget:
        caixa = QWidget()
        linha = QHBoxLayout(caixa)
        linha.setContentsMargins(4, 10, 4, 2)
        titulo = QLabel(f"{secao.titulo}  ({secao.quantidade})")
        fonte = QFont()
        fonte.setBold(True)
        titulo.setFont(fonte)
        linha.addWidget(titulo)
        if secao.subtitulo:
            complemento = QLabel(secao.subtitulo)
            complemento.setObjectName("subtitulo")
            linha.addWidget(complemento)
        linha.addStretch(1)
        if secao.total:
            total = QLabel(secao.total)
            total.setObjectName("cartaoValor")
            linha.addWidget(total)
        return caixa

    def _mostrar_mais(self, titulo: str, passo: int = LIMITE_PADRAO) -> None:
        self._limites[titulo] = self._limites.get(titulo, self._limite_secao) + passo
        self._orcamento += passo
        selecionados = list(self._selecionados)
        self._redesenhar()
        self._selecionados = selecionados
        self._pintar_selecao()

    # --------------------------------------------------------------- seleção
    def _ao_clicar(self, item: Any, somar: bool) -> None:
        if somar:
            if any(escolhido is item for escolhido in self._selecionados):
                self._selecionados = [e for e in self._selecionados if e is not item]
            else:
                self._selecionados.append(item)
        else:
            self._selecionados = [item]
        self._pintar_selecao()
        self.selecao_mudou.emit()

    def _pintar_selecao(self) -> None:
        marcados = {id(item) for item in self._selecionados}
        for chave, cartao in self._cartoes.items():
            cartao.definir_selecionado(chave in marcados)

    def selecionados(self) -> list[Any]:
        return list(self._selecionados)

    def selecionar(self, itens: Sequence[Any]) -> None:
        self._selecionados = list(itens)
        self._pintar_selecao()
        self.selecao_mudou.emit()

    def limpar_selecao(self) -> None:
        self.selecionar([])

    @property
    def itens(self) -> list[Any]:
        return [item for secao in self._secoes for item in secao.itens]

    @property
    def secoes(self) -> list[SecaoCartoes]:
        return list(self._secoes)

    def titulos(self) -> list[str]:
        return [secao.titulo for secao in self._secoes]

    def itens_da_secao(self, titulo: str) -> list[Any]:
        for secao in self._secoes:
            if secao.titulo == titulo:
                return list(secao.itens)
        return []

    @property
    def desenhados(self) -> int:
        """Quantos cartões existem de fato como widget."""
        return len(self._cartoes)
