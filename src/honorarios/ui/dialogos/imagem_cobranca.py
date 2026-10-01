"""Prévia da imagem de cobrança, com copiar (para colar no WhatsApp) e salvar."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap
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
from ..comum.imagem_cobranca import renderizar


class DialogoImagemCobranca(QDialog):
    def __init__(self, contexto, dados: servico.DadosImagem, nome_arquivo: str,
                 titulo: str = "Imagem da cobrança", parent=None) -> None:
        super().__init__(parent)
        self.contexto = contexto
        self.dados = dados
        self.nome_arquivo = nome_arquivo
        self.setWindowTitle(titulo)
        self.resize(620, 820)
        caminho = servico.caminho_fundo(contexto.sessao)
        self.imagem = renderizar(caminho.read_text(encoding="utf-8"), dados)
        self._montar(caminho)

    def _montar(self, caminho: Path) -> None:
        layout = QVBoxLayout(self)
        avisos = list(self.dados.avisos)
        if self.dados.qrcode is None:
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
        pixmap = QPixmap.fromImage(self.imagem)
        self.previa.setPixmap(
            pixmap.scaledToWidth(560, Qt.TransformationMode.SmoothTransformation)
        )
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setWidget(self.previa)
        layout.addWidget(rolagem, 1)
        layout.addWidget(
            widgets.rotulo_fraco(
                f"{self.imagem.width()} × {self.imagem.height()} px · fundo: {caminho.name}. "
                "Copiar não registra a cobrança."
            )
        )

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

        # texto em imagem não se seleciona com garantia: a chave vai como mensagem
        textos = QHBoxLayout()
        textos.addWidget(
            widgets.rotulo_fraco(
                "Depois da imagem, mande a chave como texto: assim o cliente toca e copia."
            ),
            1,
        )
        chave = widgets.QPushButton("Copiar chave Pix")
        chave.setToolTip(self.dados.campos.get("chave_pix", ""))
        chave.clicked.connect(lambda: self.copiar_texto("chave"))
        chave.setEnabled(bool(self.dados.campos.get("chave_pix")))
        textos.addWidget(chave)
        layout.addLayout(textos)

    def copiar(self) -> None:
        QGuiApplication.clipboard().setImage(self.imagem)
        self.aviso.setText("Imagem copiada: cole na conversa do WhatsApp (Ctrl+V).")

    def copiar_texto(self, qual: str = "chave") -> None:
        widgets.copiar(self.dados.campos.get("chave_pix", ""))
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
