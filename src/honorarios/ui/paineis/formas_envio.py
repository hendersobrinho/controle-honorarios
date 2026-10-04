"""Formas de envio da cobrança (WhatsApp do cliente, e-mail, malote…).

Cadastro que antes ficava nas Configurações: aqui, junto dos grupos e tipos.
Mostra quantos clientes, contratos e honorários usam cada forma, para saber o
que se pode desativar sem susto.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QInputDialog, QTableView, QVBoxLayout, QWidget
from sqlalchemy import func, select

from ...infra.modelos import Contrato, Honorario
from ...servicos import tipos as servico_tipos
from ..comum import widgets
from ..comum.tabelas import Coluna, ModeloTabela, ajustar_colunas, item_atual, preparar_tabela
from ..contexto import Contexto


class PainelFormasEnvio(QWidget):
    titulo = "Formas de envio"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.uso: dict[int, tuple[int, int]] = {}
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self.cabecalho = widgets.Cabecalho(
            "Formas de envio", "Por onde a cobrança chega a cada cliente"
        )
        self.cabecalho.adicionar_botao("Nova forma de envio", self._nova_forma, primario=True)
        self.cabecalho.adicionar_botao("Renomear", self._renomear)
        self.cabecalho.adicionar_botao("Ativar / desativar", self._alternar_forma)
        layout.addWidget(self.cabecalho)
        self.modelo = ModeloTabela([
            Coluna("Forma de envio", lambda f: f.nome),
            Coluna("Em uso", lambda f: self._texto_uso(f),
                   alinhamento=Qt.AlignmentFlag.AlignCenter),
            Coluna("Situação", lambda f: "Ativa" if f.ativo else "Inativa",
                   alinhamento=Qt.AlignmentFlag.AlignCenter),
        ])
        self.tabela = preparar_tabela(QTableView(), esticar=0)
        self.tabela.setModel(self.modelo)
        self.tabela.doubleClicked.connect(lambda *_: self._renomear())
        layout.addWidget(self.tabela, 1)
        layout.addWidget(widgets.rotulo_fraco(
            "Inativa: deixa de aparecer para escolher, mas quem já usa continua com ela."
        ))
        self.recarregar()

    def _texto_uso(self, forma) -> str:
        contratos, honorarios = self.uso.get(forma.id, (0, 0))
        if not (contratos or honorarios):
            return "—"
        return f"{contratos} contrato(s) · {honorarios} honorário(s)"

    def recarregar(self) -> None:
        sessao = self.contexto.sessao
        self.contexto.atualizar()
        contratos = dict(sessao.execute(
            select(Contrato.forma_envio_id, func.count()).group_by(Contrato.forma_envio_id)
        ).all())
        honorarios = dict(sessao.execute(
            select(Honorario.forma_envio_id, func.count()).group_by(Honorario.forma_envio_id)
        ).all())
        self.uso = {chave: (contratos.get(chave, 0), honorarios.get(chave, 0))
                    for chave in set(contratos) | set(honorarios) if chave}
        self.modelo.definir_itens(servico_tipos.listar_formas(sessao, somente_ativas=False))
        ajustar_colunas(self.tabela, self.modelo.colunas)

    def _nova_forma(self) -> None:
        nome, confirmou = QInputDialog.getText(
            self, "Nova forma de envio", "Nome da forma de envio:"
        )
        if not confirmou or not nome.strip():
            return

        def acao():
            servico_tipos.criar_forma(self.contexto.sessao, nome)
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if deu_certo:
            self.recarregar()

    def _renomear(self) -> None:
        forma = item_atual(self.tabela)
        if forma is None:
            widgets.aviso(self, "Selecione uma forma de envio.")
            return
        nome, confirmou = QInputDialog.getText(
            self, "Renomear forma de envio", "Novo nome:", text=forma.nome
        )
        if not confirmou or not nome.strip() or nome.strip() == forma.nome:
            return

        def acao():
            from ...servicos.erros import ErroDeValidacao

            existentes = {f.nome.lower() for f in servico_tipos.listar_formas(
                self.contexto.sessao, somente_ativas=False) if f.id != forma.id}
            if nome.strip().lower() in existentes:
                raise ErroDeValidacao(f"Já existe a forma de envio \"{nome.strip()}\".")
            forma.nome = nome.strip()
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
        self.recarregar()

    def _alternar_forma(self) -> None:
        forma = item_atual(self.tabela)
        if forma is None:
            widgets.aviso(self, "Selecione uma forma de envio.")
            return

        def acao():
            forma.ativo = not forma.ativo
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if deu_certo:
            self.recarregar()
