"""Grupos e tipos de honorário, numa tela própria.

Grupos à esquerda (a ordem deles é a ordem das seções nas telas de cobrança),
tipos do grupo escolhido à direita, em cartões que mostram como cada tipo
aparece na mensagem e quanto ele é usado.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...servicos import tipos as servico
from ..comum import cores, tema, widgets
from ..comum.cartoes import Acao, DadosCartao, PainelDeCartoes, SecaoCartoes
from ..contexto import Contexto
from ..dialogos.tipo import DialogoGrupo, DialogoTipo

AJUDA = (
    "<b>Grupo</b> é a seção em que os honorários aparecem nas telas de cobrança "
    "(Mensais, Imposto de Renda…). <b>Tipo</b> é o que se cobra (Honorário mensal, "
    "Alteração contratual…) e define como ele aparece na mensagem de cobrança."
)


class PainelTipos(QWidget):
    titulo = "Grupos e tipos"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self._montar()
        self.recarregar()

    # ------------------------------------------------------------------ layout
    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self.cabecalho = widgets.Cabecalho(
            "Grupos e tipos de honorário", "O que se cobra e onde cada coisa aparece"
        )
        self.cabecalho.adicionar_botao("Novo tipo", self._novo_tipo, primario=True,
                                       atalho="Ctrl+N")
        self.cabecalho.adicionar_botao("Novo grupo", self._novo_grupo)
        self.cabecalho.adicionar_botao("Atualizar", self.recarregar, atalho="F5")
        layout.addWidget(self.cabecalho)

        ajuda = QLabel(AJUDA)
        ajuda.setObjectName("rankingCuriosidade")
        ajuda.setWordWrap(True)
        layout.addWidget(ajuda)

        corpo = QHBoxLayout()
        corpo.setSpacing(14)

        # grupos
        coluna_grupos = QFrame()
        coluna_grupos.setObjectName("cartao")
        coluna_grupos.setFixedWidth(320)
        caixa = QVBoxLayout(coluna_grupos)
        caixa.setContentsMargins(12, 12, 12, 12)
        titulo = QLabel("Grupos")
        titulo.setObjectName("rankingTitulo")
        caixa.addWidget(titulo)
        caixa.addWidget(widgets.rotulo_fraco("Na ordem em que aparecem nas telas"))
        self.lista_grupos = QListWidget()
        self.lista_grupos.setObjectName("listaGrupos")
        self.lista_grupos.currentRowChanged.connect(lambda *_: self._mostrar_tipos())
        self.lista_grupos.itemDoubleClicked.connect(lambda *_: self._editar_grupo())
        caixa.addWidget(self.lista_grupos, 1)
        botoes = QHBoxLayout()
        for texto, funcao, dica in (
            ("Editar", self._editar_grupo, "Renomear ou marcar como Imposto de Renda"),
            ("↑", lambda: self._mover(-1), "Subir o grupo"),
            ("↓", lambda: self._mover(1), "Descer o grupo"),
            ("Ativar/desativar", self._alternar_grupo, ""),
        ):
            botao = QPushButton(texto)
            if dica:
                botao.setToolTip(dica)
            botao.clicked.connect(funcao)
            botoes.addWidget(botao)
        caixa.addLayout(botoes)
        corpo.addWidget(coluna_grupos)

        # tipos do grupo escolhido
        coluna_tipos = QVBoxLayout()
        self.titulo_tipos = QLabel("")
        self.titulo_tipos.setObjectName("rankingTitulo")
        coluna_tipos.addWidget(self.titulo_tipos)
        self.lista_tipos = PainelDeCartoes("Nenhum tipo neste grupo ainda.")
        self.lista_tipos.item_ativado.connect(self._editar_tipo)
        coluna_tipos.addWidget(self.lista_tipos, 1)
        corpo.addLayout(coluna_tipos, 1)
        layout.addLayout(corpo, 1)

    # ------------------------------------------------------------------ dados
    def recarregar(self, manter_grupo: int | None = None) -> None:
        self.contexto.atualizar()
        atual = manter_grupo or self._grupo_atual_id()
        self.grupos = servico.listar_grupos(self.contexto.sessao)
        self.lista_grupos.blockSignals(True)
        self.lista_grupos.clear()
        linha_atual = 0
        for posicao, grupo in enumerate(self.grupos):
            ativos = sum(1 for tipo in grupo.tipos if tipo.ativo)
            texto = f"{grupo.nome}\n{ativos} tipo(s) ativo(s)"
            if grupo.imposto_de_renda:
                texto += " · Imposto de Renda"
            if not grupo.ativo:
                texto += " · inativo"
            item = QListWidgetItem(texto)
            item.setData(Qt.ItemDataRole.UserRole, grupo.id)
            if not grupo.ativo:
                item.setForeground(tema.cor("texto_fraco", cores.tema_atual()))
            self.lista_grupos.addItem(item)
            if grupo.id == atual:
                linha_atual = posicao
        self.lista_grupos.blockSignals(False)
        if self.grupos:
            self.lista_grupos.setCurrentRow(linha_atual)
        self._mostrar_tipos()

    def _grupo_atual_id(self) -> int | None:
        item = self.lista_grupos.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _grupo_atual(self):
        identificador = self._grupo_atual_id()
        return next((g for g in getattr(self, "grupos", []) if g.id == identificador), None)

    def _mostrar_tipos(self) -> None:
        grupo = self._grupo_atual()
        if grupo is None:
            self.titulo_tipos.setText("")
            self.lista_tipos.definir_secoes([])
            return
        self.titulo_tipos.setText(f"Tipos em {grupo.nome}")
        tipos = sorted(grupo.tipos, key=lambda tipo: (not tipo.ativo, tipo.nome))
        ativos = [tipo for tipo in tipos if tipo.ativo]
        inativos = [tipo for tipo in tipos if not tipo.ativo]
        secoes = [
            SecaoCartoes(rotulo, itens=itens, construtor=self._cartao)
            for rotulo, itens in (("Ativos", ativos), ("Inativos", inativos))
            if itens
        ]
        self.lista_tipos.definir_secoes(secoes, preservar_selecao=False)

    def _cartao(self, tipo) -> DadosCartao:
        honorarios, contratos = servico.tipo_em_uso(self.contexto.sessao, tipo)
        um, _, _ = servico.previa_dos_textos(
            tipo.nome,
            tipo.exige_competencia,
            tipo.texto_mensagem,
            tipo.texto_mensagem_empresa,
            tipo.texto_item_lista,
        )
        return DadosCartao(
            titulo=tipo.nome,
            # a frase como sai na cobrança é o que explica o tipo: vai em destaque
            subtitulo=f"“Consta em aberto o {um}…”",
            detalhes=[
                ("Periodicidade", tipo.periodicidade.rotulo),
                ("Competência", tipo.exige_competencia.rotulo),
                ("Em uso", f"{honorarios} honorário(s) · {contratos} contrato(s)"),
            ],
            situacao="Ativo" if tipo.ativo else "Inativo",
            cor=tema.cor("destaque" if tipo.ativo else "texto_fraco", cores.tema_atual()),
            item=tipo,
            acoes=[
                Acao("Editar", self._editar_tipo, primaria=True),
                Acao("Reativar" if not tipo.ativo else "Desativar", self._alternar_tipo),
            ],
        )

    # ------------------------------------------------------------------ ações
    def _novo_tipo(self) -> None:
        grupo = self._grupo_atual()
        dialogo = DialogoTipo(self.contexto, grupo_id=grupo.id if grupo else None, parent=self)
        if dialogo.exec():
            self.recarregar(manter_grupo=dialogo.tipo.grupo_id if dialogo.tipo else None)

    def _editar_tipo(self, tipo) -> None:
        if DialogoTipo(self.contexto, tipo, parent=self).exec():
            self.recarregar(manter_grupo=tipo.grupo_id)

    def _alternar_tipo(self, tipo) -> None:
        if tipo.ativo:
            honorarios, contratos = servico.tipo_em_uso(self.contexto.sessao, tipo)
            if not widgets.confirmar(
                self,
                f"Desativar o tipo {tipo.nome}?",
                "Desativar tipo",
                f"Ele é usado em {honorarios} honorário(s) e {contratos} contrato(s), "
                "que continuam como estão — o tipo só deixa de aparecer em novos "
                "lançamentos.",
            ):
                return

        def acao():
            tipo.ativo = not tipo.ativo
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if deu_certo:
            self.recarregar(manter_grupo=tipo.grupo_id)

    def _novo_grupo(self) -> None:
        dialogo = DialogoGrupo(self.contexto, parent=self)
        if dialogo.exec():
            self.recarregar(manter_grupo=dialogo.grupo.id)

    def _editar_grupo(self) -> None:
        grupo = self._grupo_atual()
        if grupo and DialogoGrupo(self.contexto, grupo, parent=self).exec():
            self.recarregar(manter_grupo=grupo.id)

    def _mover(self, direcao: int) -> None:
        grupo = self._grupo_atual()
        if grupo is None:
            return

        def acao():
            servico.mover_grupo(self.contexto.sessao, grupo, direcao)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if deu_certo:
            self.recarregar(manter_grupo=grupo.id)

    def _alternar_grupo(self) -> None:
        grupo = self._grupo_atual()
        if grupo is None:
            return

        def acao():
            if grupo.ativo:
                servico.desativar_grupo(self.contexto.sessao, grupo)
            else:
                servico.reativar_grupo(self.contexto.sessao, grupo)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.recarregar(manter_grupo=grupo.id)
