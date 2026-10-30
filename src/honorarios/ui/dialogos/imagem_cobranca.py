"""Prévia de uma imagem pronta, com copiar (para colar no WhatsApp) e salvar.

Serve ao agradecimento do pagamento e à prévia das Configurações. A imagem da
cobrança, com as datas, o acordo e a conferência dos juros, é montada na própria
tela "Cobrar".
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
)

from ...config.caminhos import pasta_exportacoes
from ...servicos import imagem_cobranca as servico
from ..comum import widgets
from ..comum.imagem_cobranca import copiar_imagem, renderizar, renderizar_agradecimento


class DialogoImagemCobranca(QDialog):
    def __init__(self, contexto, dados: servico.DadosImagem, nome_arquivo: str,
                 titulo: str = "Imagem da cobrança", parent=None,
                 agradecimento: bool = False) -> None:
        super().__init__(parent)
        # agradecimento: a imagem de "pagamento recebido", sem QR nem chave Pix
        self.agradecimento = agradecimento
        self.contexto = contexto
        self.dados = dados
        self.nome_arquivo = nome_arquivo
        self.setWindowTitle(titulo)
        self.resize(620, 860)
        self.caminho_fundo = servico.caminho_fundo(contexto.sessao)
        texto = self.caminho_fundo.read_text(encoding="utf-8")
        self.imagem = (renderizar_agradecimento(texto, dados) if agradecimento
                       else renderizar(texto, dados))
        self._montar(self.caminho_fundo)

    def _montar(self, caminho: Path) -> None:
        layout = QVBoxLayout(self)
        avisos = list(self.dados.avisos)
        if self.dados.qrcode is None and not self.agradecimento:
            avisos.append(
                "A imagem está sem QR code. Para voltar a ter: Configurações → Imagem da "
                "cobrança → Usar o do escritório."
            )
        for texto in avisos:
            aviso = QLabel(texto)
            aviso.setObjectName("avisoForte")
            aviso.setWordWrap(True)
            layout.addWidget(aviso)

        self.previa = QLabel()
        self.previa.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.previa.setPixmap(QPixmap.fromImage(self.imagem).scaledToWidth(
            560, Qt.TransformationMode.SmoothTransformation))
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setWidget(self.previa)
        layout.addWidget(rolagem, 1)
        layout.addWidget(widgets.rotulo_fraco(
            f"{self.imagem.width()} × {self.imagem.height()} px · fundo: {caminho.name}."))

        acoes = QHBoxLayout()
        self.aviso = widgets.rotulo_fraco("")
        acoes.addWidget(self.aviso, 1)
        copiar = widgets.QPushButton("Copiar imagem")
        copiar.setObjectName("primario")
        copiar.setShortcut("Ctrl+C")
        copiar.clicked.connect(self.copiar)
        self.botao_chave = widgets.QPushButton("Copiar chave Pix")
        self.botao_chave.setToolTip(self.dados.campos.get("chave_pix", ""))
        self.botao_chave.clicked.connect(self.copiar_chave)
        self.botao_chave.setVisible(not self.agradecimento
                                    and bool(self.dados.campos.get("chave_pix")))
        salvar = widgets.QPushButton("Salvar PNG…")
        salvar.clicked.connect(self._salvar)
        fechar = widgets.QPushButton("Fechar")
        fechar.clicked.connect(self.accept)
        for botao in (copiar, self.botao_chave, salvar, fechar):
            acoes.addWidget(botao)
        layout.addLayout(acoes)

    def _chave(self) -> str:
        return "" if self.agradecimento else self.dados.campos.get("chave_pix", "")

    def copiar(self) -> None:
        copiar_imagem(self.imagem, self._chave())
        self.aviso.setText("Imagem copiada: cole na conversa (Ctrl+V)."
                           + (" Depois copie a chave Pix e mande como mensagem."
                              if self._chave() else ""))

    def copiar_chave(self) -> None:
        widgets.copiar(self._chave())
        self.aviso.setText("Chave Pix copiada: cole como mensagem logo depois da imagem.")

    def _salvar(self) -> None:
        sugestao = str(pasta_exportacoes() / f"{self.nome_arquivo}.png")
        destino, _ = QFileDialog.getSaveFileName(self, "Salvar imagem", sugestao, "PNG (*.png)")
        if not destino:
            return
        if not destino.lower().endswith(".png"):
            destino += ".png"
        if self.imagem.save(destino, "PNG"):
            self.aviso.setText(f"Imagem salva em {destino}.")
        else:
            widgets.erro(self, f"Não foi possível salvar em {destino}.")
