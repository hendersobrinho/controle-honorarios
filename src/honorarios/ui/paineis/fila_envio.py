"""Fila de envio: seleciona empresas e cobra uma a uma no assistente."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...dominio.enums import TipoPessoa
from ...dominio.valores import ZERO, formatar_data, formatar_moeda, formatar_telefone
from ...servicos import cobrancas as servico
from ...servicos import honorarios as servico_honorarios
from ...servicos import tipos as servico_tipos
from ...servicos.honorarios import Filtro
from ..comum import cores, widgets
from ..comum.campos import ComboEnum, ComboRegistros
from ..comum.tabelas import (
    Coluna,
    ModeloTabelaMarcavel,
    coluna_inteiro,
    coluna_moeda,
    preparar_tabela,
)
from ..contexto import Contexto
from ..dialogos.assistente import executar_assistente


def _maior_atraso(grupo) -> int:
    """Maior atraso entre os honorários da empresa (o item da tabela é (cliente, linhas))."""
    return max((linha.atualizacao.dias_atraso for linha in grupo[1]), default=0)


def _ultima_cobranca(grupo):
    return max((linha.ultima_cobranca for linha in grupo[1] if linha.ultima_cobranca), default=None)


FAIXAS = (
    ("Qualquer atraso", None, None),
    ("1 a 30 dias", 1, 30),
    ("31 a 60 dias", 31, 60),
    ("61 a 90 dias", 61, 90),
    ("Mais de 90 dias", 91, None),
)


class PainelFilaEnvio(QWidget):
    titulo = "Fila de envio"

    def __init__(self, contexto: Contexto, parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self._montar()
        self.recarregar()

    def _montar(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self.cabecalho = widgets.Cabecalho(
            "Fila de envio", "Cobrança em lote, uma empresa por vez"
        )
        self.cabecalho.adicionar_botao(
            "Iniciar assistente", self._iniciar, primario=True, atalho="Ctrl+Return"
        )
        self.cabecalho.adicionar_botao("Registrar cobrança sem mensagem", self._sem_mensagem)
        self.cabecalho.adicionar_botao("Atualizar", self.recarregar, atalho="F5")
        layout.addWidget(self.cabecalho)

        filtros = QHBoxLayout()
        self.tipo_pessoa = ComboEnum(TipoPessoa)
        self.tipo_pessoa.insertItem(0, "PF e PJ", None)
        self.tipo_pessoa.setCurrentIndex(0)
        self.tipo_pessoa.currentIndexChanged.connect(lambda *_: self.recarregar())
        filtros.addWidget(widgets.rotulo_fraco("Tipo:"))
        filtros.addWidget(self.tipo_pessoa)
        self.grupo = ComboRegistros(
            servico_tipos.listar_grupos(self.contexto.sessao),
            rotulo=lambda g: g.nome,
            vazio="Todos os grupos",
        )
        self.grupo.currentIndexChanged.connect(lambda *_: self.recarregar())
        filtros.addWidget(widgets.rotulo_fraco("Grupo:"))
        filtros.addWidget(self.grupo)
        self.faixa = QComboBox()
        for rotulo, minimo, maximo in FAIXAS:
            self.faixa.addItem(rotulo, (minimo, maximo))
        self.faixa.currentIndexChanged.connect(lambda *_: self.recarregar())
        filtros.addWidget(widgets.rotulo_fraco("Atraso:"))
        filtros.addWidget(self.faixa)
        self.sem_cobranca = QCheckBox("Sem cobrança há")
        self.sem_cobranca.setChecked(True)
        self.sem_cobranca.toggled.connect(lambda *_: self.recarregar())
        filtros.addWidget(self.sem_cobranca)
        self.dias = QComboBox()
        for dias in (3, 5, 7, 15, 30):
            self.dias.addItem(f"{dias} dias", dias)
        self.dias.setCurrentIndex(2)
        self.dias.currentIndexChanged.connect(lambda *_: self.recarregar())
        filtros.addWidget(self.dias)
        self.somente_promessa = QCheckBox("Só promessa vencida")
        self.somente_promessa.toggled.connect(lambda *_: self.recarregar())
        filtros.addWidget(self.somente_promessa)
        filtros.addStretch(1)
        layout.addLayout(filtros)

        self.modelo = ModeloTabelaMarcavel(
            [
                Coluna("", lambda item: "", largura=28),
                Coluna("Empresa", lambda item: f"{item[0].codigo} – {item[0].nome}"),
                Coluna(
                    "Contato",
                    lambda item: (
                        item[0].contato_principal.tratamento_ou_nome
                        if item[0].contato_principal
                        else "— sem contato —"
                    ),
                ),
                Coluna(
                    "WhatsApp",
                    lambda grupo: (
                        formatar_telefone(grupo[0].contato_principal.telefone)
                        if grupo[0].contato_principal and grupo[0].contato_principal.telefone
                        else "— sem telefone —"
                    ),
                    alinhamento=Qt.AlignmentFlag.AlignCenter,
                ),
                coluna_inteiro("Honorários", lambda item: len(item[1])),
                coluna_inteiro(
                    "Maior atraso",
                    _maior_atraso,
                    cor=lambda grupo: cores.cor_de_atraso(_maior_atraso(grupo)),
                ),
                coluna_moeda(
                    "Total atualizado",
                    lambda item: servico_honorarios.total_de(item[1]),
                    negrito=True,
                ),
                Coluna(
                    "Última cobrança",
                    lambda grupo: formatar_data(_ultima_cobranca(grupo)) or "nunca",
                    ordem=lambda grupo: _ultima_cobranca(grupo) or date.min,
                    alinhamento=Qt.AlignmentFlag.AlignCenter,
                ),
            ]
        )
        self.tabela = preparar_tabela(QTableView(), esticar=1)
        self.tabela.setModel(self.modelo)
        self.tabela.setSortingEnabled(False)
        self.modelo.dataChanged.connect(lambda *_: self._resumir())
        layout.addWidget(self.tabela, 1)

        rodape = QHBoxLayout()
        self.resumo = widgets.rotulo_fraco("")
        rodape.addWidget(self.resumo, 1)
        marcar = widgets.QPushButton("Marcar todas")
        marcar.clicked.connect(lambda: (self.modelo.marcar_todos(True), self._resumir()))
        desmarcar = widgets.QPushButton("Desmarcar todas")
        desmarcar.clicked.connect(lambda: (self.modelo.marcar_todos(False), self._resumir()))
        rodape.addWidget(marcar)
        rodape.addWidget(desmarcar)
        layout.addLayout(rodape)

    def _filtro(self) -> Filtro:
        minimo, maximo = self.faixa.currentData()
        return Filtro(
            tipo_pessoa=self.tipo_pessoa.currentData(),
            grupo_id=self.grupo.valor(),
            atraso_minimo=minimo,
            atraso_maximo=maximo,
            sem_cobranca_dias=self.dias.currentData() if self.sem_cobranca.isChecked() else None,
            somente_promessa_vencida=self.somente_promessa.isChecked(),
            data_referencia=self.contexto.data_referencia,
        )

    def recarregar(self) -> None:
        self.contexto.atualizar()
        grupos = servico.fila_de_envio(self.contexto.sessao, self._filtro())
        self.modelo.definir_itens(grupos)
        self.tabela.resizeColumnsToContents()
        self._resumir()

    def _resumir(self) -> None:
        marcados = self.modelo.marcados()
        honorarios = sum(len(item[1]) for item in marcados)
        total = sum(
            (servico_honorarios.total_de(item[1]) for item in marcados), start=ZERO
        )
        self.resumo.setText(
            f"{len(marcados)} empresa(s) marcada(s) de {len(self.modelo.itens)} · "
            f"{honorarios} honorário(s) · total {formatar_moeda(total)}"
        )

    def _iniciar(self) -> None:
        marcados = self.modelo.marcados()
        if not marcados:
            widgets.aviso(self, "Marque as empresas que você quer cobrar.")
            return
        honorarios = sum(len(item[1]) for item in marcados)
        total = sum((servico_honorarios.total_de(item[1]) for item in marcados), start=ZERO)
        if not widgets.confirmar(
            self,
            f"Iniciar o assistente para {len(marcados)} empresa(s)?",
            "Fila de envio",
            f"{honorarios} honorário(s) · total {formatar_moeda(total)}. "
            "Cada empresa aparece com a mensagem pronta; nada é enviado automaticamente.",
        ):
            return
        andamento = executar_assistente(self.contexto, marcados, self)
        widgets.informar(self, andamento.resumo, "Fila de envio concluída")
        self.recarregar()

    def _sem_mensagem(self) -> None:
        marcados = self.modelo.marcados()
        if not marcados:
            widgets.aviso(self, "Marque as empresas que você cobrou por fora do sistema.")
            return
        linhas = [linha for item in marcados for linha in item[1]]
        if not widgets.confirmar(
            self,
            f"Registrar cobrança de hoje em {len(linhas)} honorário(s)?",
            "Registro em lote",
            f"{len(marcados)} empresa(s) · nenhuma mensagem é gerada.",
        ):
            return
        from PySide6.QtWidgets import QInputDialog

        observacao, _ = QInputDialog.getText(self, "Registro em lote", "Observação (opcional):")

        def acao():
            servico.registrar_sem_mensagem(self.contexto.sessao, linhas, observacao or "")
            self.contexto.salvar()

        deu_certo, _ = widgets.executar(self, acao)
        if not deu_certo:
            self.contexto.desfazer()
            return
        self.recarregar()
