"""Prévia da imagem de cobrança, com copiar (para colar no WhatsApp) e salvar."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...config.caminhos import pasta_exportacoes
from ...dominio.valores import formatar_data
from ...servicos import imagem_cobranca as servico
from ..comum import widgets
from ..comum.campos import CampoData
from ..comum.imagem_cobranca import renderizar, renderizar_agradecimento


class DialogoImagemCobranca(QDialog):
    """Prévia da imagem.

    Com ``gerar``, a imagem tem o "Pagar até" e o juros é calculado até ele. Com
    ``registrar_acordo``, a oferta pode ser guardada como acordo: aí aparece a data
    "Valores atualizados em" (o juros congelado nela) e, pagando dentro do prazo, a
    baixa sugere esse valor.
    """

    def __init__(self, contexto, dados: servico.DadosImagem, nome_arquivo: str,
                 titulo: str = "Imagem da cobrança", parent=None,
                 gerar: Callable[[date, date], servico.DadosImagem] | None = None,
                 vencimento: date | None = None,
                 registrar_acordo: Callable[[date, date], object] | None = None,
                 agradecimento: bool = False) -> None:
        super().__init__(parent)
        # agradecimento: a imagem de "pagamento recebido", sem QR nem chave Pix
        self.agradecimento = agradecimento
        self.contexto = contexto
        self.dados = dados
        self.nome_arquivo = nome_arquivo
        self.gerar = gerar
        self.registrar_acordo = registrar_acordo
        self._acordo_registrado: tuple[date, date] | None = None
        self.setWindowTitle(titulo)
        self.resize(620, 860)
        self.caminho_fundo = servico.caminho_fundo(contexto.sessao)
        self.imagem = self._renderizar(dados)
        self._montar(self.caminho_fundo, vencimento)

    def _renderizar(self, dados):
        texto = self.caminho_fundo.read_text(encoding="utf-8")
        if self.agradecimento:
            return renderizar_agradecimento(texto, dados)
        return renderizar(texto, dados)

    def _montar(self, caminho: Path, vencimento: date | None) -> None:
        layout = QVBoxLayout(self)
        if self.gerar is not None:
            linha = QHBoxLayout()
            linha.addWidget(QLabel("Pagar até:"))
            self.vencimento = CampoData(vencimento)
            self.vencimento.setToolTip("O juros da imagem é calculado até esta data")
            self.vencimento.dateChanged.connect(lambda *_: self._refazer())
            linha.addWidget(self.vencimento)
            linha.addSpacing(12)
            self.acordo = QCheckBox("Guardar como acordo")
            self.acordo.setToolTip(
                "Congela o juros numa data: pagando até o prazo, a baixa sugere este valor. "
                "Depois do prazo, o juros volta a correr desde o vencimento original."
            )
            self.acordo.setVisible(self.registrar_acordo is not None)
            self.acordo.toggled.connect(lambda *_: self._alternar_acordo())
            linha.addWidget(self.acordo)
            # só no acordo: a data em que o juros fica congelado
            self.linha_atualizado = QWidget()
            linha_atualizado = QHBoxLayout(self.linha_atualizado)
            linha_atualizado.setContentsMargins(12, 0, 0, 0)
            linha_atualizado.addWidget(QLabel("Valores atualizados em:"))
            self.atualizado_em = CampoData(vencimento)
            self.atualizado_em.setToolTip("O juros do acordo fica congelado nesta data")
            self.atualizado_em.dateChanged.connect(lambda *_: self._refazer())
            linha_atualizado.addWidget(self.atualizado_em)
            self.linha_atualizado.setVisible(False)
            linha.addWidget(self.linha_atualizado)
            linha.addStretch(1)
            layout.addLayout(linha)
            self.explicacao_acordo = widgets.rotulo_fraco("")
            layout.addWidget(self.explicacao_acordo)
            self._explicar_acordo()
        avisos = list(self.dados.avisos)
        if self.dados.qrcode is None and not self.agradecimento:
            avisos.append(
                "A imagem está sem QR code. Escolha o PNG do QR code do Pix (gerado no app "
                "do banco) em Configurações → Imagem da cobrança."
            )
        if self.dados.linhas and servico.usa_modelo(self.contexto.sessao):
            avisos.append(
                "Usando o fundo modelo do sistema. Escolha o seu em Configurações → "
                "Imagem da cobrança."
            )
        for texto in avisos:
            aviso = QLabel(texto)
            aviso.setObjectName("avisoForte")
            aviso.setWordWrap(True)
            layout.addWidget(aviso)

        self.previa = QLabel()
        self.previa.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mostrar_imagem()
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setWidget(self.previa)
        layout.addWidget(rolagem, 1)
        self.tamanho = widgets.rotulo_fraco("")
        layout.addWidget(self.tamanho)
        self._mostrar_tamanho()

        acoes = QHBoxLayout()
        self.aviso = widgets.rotulo_fraco("")
        acoes.addWidget(self.aviso, 1)
        copiar = widgets.QPushButton("Copiar imagem")
        copiar.setObjectName("primario")
        copiar.setShortcut("Ctrl+C")
        copiar.clicked.connect(self.copiar)
        salvar = widgets.QPushButton("Salvar PNG…")
        salvar.clicked.connect(self._salvar)
        fechar = widgets.QPushButton("Fechar")
        fechar.clicked.connect(self.accept)
        for botao in (copiar, salvar, fechar):
            acoes.addWidget(botao)
        layout.addLayout(acoes)

        if self.agradecimento:
            return
        # texto em imagem não se seleciona com garantia: a chave vai como mensagem
        textos = QHBoxLayout()
        textos.addWidget(
            widgets.rotulo_fraco(
                "Depois da imagem, mande a chave como texto: assim o cliente toca e copia."
            ),
            1,
        )
        self.botao_chave = widgets.QPushButton("Copiar chave Pix")
        self.botao_chave.setToolTip(self.dados.campos.get("chave_pix", ""))
        self.botao_chave.clicked.connect(lambda: self.copiar_texto("chave"))
        self.botao_chave.setEnabled(bool(self.dados.campos.get("chave_pix")))
        textos.addWidget(self.botao_chave)
        layout.addLayout(textos)

    def _mostrar_imagem(self) -> None:
        pixmap = QPixmap.fromImage(self.imagem)
        self.previa.setPixmap(
            pixmap.scaledToWidth(560, Qt.TransformationMode.SmoothTransformation)
        )

    def _mostrar_tamanho(self) -> None:
        self.tamanho.setText(
            f"{self.imagem.width()} × {self.imagem.height()} px · fundo: "
            f"{self.caminho_fundo.name}. Copiar não registra a cobrança."
        )

    def _base(self) -> date:
        """A data do juros: a do acordo, se marcado; senão, o próprio "pagar até"."""
        if self.acordo.isChecked():
            return self.atualizado_em.valor()
        return self.vencimento.valor()

    def _alternar_acordo(self) -> None:
        marcado = self.acordo.isChecked()
        self.linha_atualizado.setVisible(marcado)
        self.vencimento.setToolTip(
            "Prazo do acordo: o juros fica congelado em \"Valores atualizados em\""
            if marcado else "O juros da imagem é calculado até esta data"
        )
        self._refazer()

    def _explicar_acordo(self) -> None:
        if not hasattr(self, "explicacao_acordo"):
            return
        base, ate = self._base(), self.vencimento.valor()
        if self.acordo.isChecked():
            texto = (
                f"Acordo: {self.dados.campos.get('total', '')} (valores de "
                f"{formatar_data(base)}) vale até {formatar_data(ate)}. Passado o prazo "
                "sem pagamento, o juros volta a correr desde o vencimento original. Ele é "
                "guardado quando a imagem for copiada ou salva."
            )
        else:
            texto = (
                f"A imagem mostra o valor com juros até {formatar_data(ate)}. Marque "
                "\"Guardar como acordo\" para congelar o juros numa data e a baixa "
                "respeitar esse valor dentro do prazo."
            )
        self.explicacao_acordo.setText(texto)

    def _guardar_acordo(self) -> None:
        """Registra o acordo uma vez por combinação de datas, quando a oferta sai."""
        if self.gerar is None or self.registrar_acordo is None or not self.acordo.isChecked():
            return
        datas = (self.atualizado_em.valor(), self.vencimento.valor())
        if self._acordo_registrado == datas:
            return

        def acao():
            self.registrar_acordo(*datas)

        if widgets.executar(self, acao)[0]:
            self._acordo_registrado = datas

    def _refazer(self) -> None:
        """Uma data mudou: refaz os dados e a imagem."""
        atualizado_em, vencimento = self._base(), self.vencimento.valor()
        ajustada = vencimento < atualizado_em
        if ajustada:
            # o "pagar até" que a pessoa escolheu manda: a data dos valores não passa dele
            self.atualizado_em.blockSignals(True)
            self.atualizado_em.definir(vencimento)
            self.atualizado_em.blockSignals(False)
            atualizado_em = vencimento

        def acao():
            return self.gerar(vencimento, atualizado_em)

        deu_certo, dados = widgets.executar(self, acao)
        if not deu_certo:
            return
        self.dados = dados
        self.imagem = self._renderizar(dados)
        self._mostrar_imagem()
        self._mostrar_tamanho()
        self.aviso.setText(f"Valores de {dados.campos['data']}, pagar até "
                           f"{dados.campos['vencimento']}: total {dados.campos['total']}."
                           + (" \"Valores atualizados em\" não pode passar do \"Pagar até\": "
                              "ficou igual a ele." if ajustada else ""))
        self._explicar_acordo()

    def copiar(self) -> None:
        """A imagem e, junto, a chave Pix como texto: Outlook e Telegram colam os dois;
        o WhatsApp cola só a imagem — por isso o próximo passo fica em destaque."""
        dados = QMimeData()
        dados.setImageData(self.imagem)
        chave = self.dados.campos.get("chave_pix", "") if not self.agradecimento else ""
        if chave:
            dados.setText(chave)
        QGuiApplication.clipboard().setMimeData(dados)
        self._guardar_acordo()
        proximo = (" Depois clique em Copiar chave Pix e cole como mensagem: no WhatsApp o "
                   "cliente toca na chave e copia." if chave else "")
        self.aviso.setText("1/2 · Imagem copiada: cole na conversa (Ctrl+V)." + proximo
                           + (" Acordo guardado." if self._acordo_registrado else ""))
        if chave and hasattr(self, "botao_chave"):   # o segundo passo, em destaque
            self.botao_chave.setObjectName("primario")
            self.botao_chave.setText("2/2 · Copiar chave Pix")
            self.botao_chave.style().unpolish(self.botao_chave)
            self.botao_chave.style().polish(self.botao_chave)

    def copiar_texto(self, qual: str = "chave") -> None:
        widgets.copiar(self.dados.campos.get("chave_pix", ""))
        self.aviso.setText("2/2 · Chave Pix copiada: cole como mensagem logo depois da imagem.")

    def _salvar(self) -> None:
        sugestao = str(pasta_exportacoes() / f"{self.nome_arquivo}.png")
        destino, _ = QFileDialog.getSaveFileName(self, "Salvar imagem", sugestao, "PNG (*.png)")
        if not destino:
            return
        if not destino.lower().endswith(".png"):
            destino += ".png"
        if self.imagem.save(destino, "PNG"):
            self._guardar_acordo()
            self.aviso.setText(f"Imagem salva em {destino}."
                               + (" Acordo guardado." if self._acordo_registrado else ""))
        else:
            widgets.erro(self, f"Não foi possível salvar em {destino}.")
