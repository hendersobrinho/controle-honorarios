"""Tema claro e escuro. Cor só quando significa algo."""

from __future__ import annotations

from PySide6.QtGui import QColor

CORES = {
    "claro": {
        "fundo": "#f5f6f8",
        "superficie": "#ffffff",
        "borda": "#dfe3e8",
        "texto": "#1c2430",
        "texto_fraco": "#6b7684",
        "destaque": "#1f6feb",
        "atrasado": "#c0392b",
        "atencao": "#b7791f",
        "pago": "#1f7a45",
        "faixa": "#f0f2f5",
    },
    "escuro": {
        "fundo": "#161a1f",
        "superficie": "#1e242b",
        "borda": "#2d353f",
        "texto": "#e6eaef",
        "texto_fraco": "#98a2b0",
        "destaque": "#5596ff",
        "atrasado": "#ff7a6b",
        "atencao": "#e9b949",
        "pago": "#5fd08a",
        "faixa": "#222a31",
    },
}


def cor(nome: str, tema: str = "claro") -> QColor:
    return QColor(CORES.get(tema, CORES["claro"])[nome])


def folha_de_estilo(tema: str = "claro") -> str:
    c = CORES.get(tema, CORES["claro"])
    return f"""
    QWidget {{
        background: {c["fundo"]};
        color: {c["texto"]};
        font-size: 13px;
    }}
    /* sem isso o rótulo pinta o fundo da janela por cima do cartão branco.
       caixas de marcação ficam de fora: estilizá-las faz o Qt desenhar o
       indicador pelo stylesheet, e ele some. */
    QLabel {{ background: transparent; }}
    QFrame#cartao, QGroupBox {{
        background: {c["superficie"]};
        border: 1px solid {c["borda"]};
        border-radius: 8px;
    }}
    QGroupBox {{
        margin-top: 14px;
        padding: 14px 12px 12px 12px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 4px;
        color: {c["texto_fraco"]};
    }}
    QLabel#titulo {{ font-size: 20px; font-weight: 600; }}
    QLabel#subtitulo {{ color: {c["texto_fraco"]}; }}
    QLabel#avisoForte {{
        background: {c["faixa"]};
        color: {c["atrasado"]};
        border: 1px solid {c["atrasado"]};
        border-radius: 6px;
        padding: 8px 10px;
        font-weight: 600;
    }}
    QLabel#rotuloCartao {{ color: {c["texto_fraco"]}; font-size: 11px; }}
    QLabel#valorCartao {{ font-size: 21px; font-weight: 600; }}
    QLabel#valorDestaque {{ font-size: 21px; font-weight: 600; color: {c["destaque"]}; }}

    QPushButton {{
        background: {c["superficie"]};
        border: 1px solid {c["borda"]};
        border-radius: 6px;
        padding: 6px 14px;
    }}
    QPushButton:hover {{ border-color: {c["destaque"]}; }}
    QPushButton:disabled {{ color: {c["texto_fraco"]}; }}
    QPushButton#primario {{
        background: {c["destaque"]};
        border-color: {c["destaque"]};
        color: #ffffff;
        font-weight: 600;
    }}
    QPushButton#primario:hover {{ background: {c["texto"]}; border-color: {c["texto"]}; }}

    QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
        background: {c["superficie"]};
        border: 1px solid {c["borda"]};
        border-radius: 6px;
        padding: 5px 8px;
        selection-background-color: {c["destaque"]};
    }}
    QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QPlainTextEdit:focus {{
        border-color: {c["destaque"]};
    }}

    QTableView, QTreeView {{
        background: {c["superficie"]};
        alternate-background-color: {c["faixa"]};
        border: 1px solid {c["borda"]};
        border-radius: 8px;
        gridline-color: {c["borda"]};
        selection-background-color: {c["destaque"]};
        selection-color: #ffffff;
    }}
    QHeaderView::section {{
        background: {c["faixa"]};
        color: {c["texto_fraco"]};
        border: none;
        border-bottom: 1px solid {c["borda"]};
        padding: 6px 8px;
        font-weight: 600;
    }}
    QFrame#cartaoRegistro {{
        background: {c["superficie"]};
        border: 1px solid {c["borda"]};
        border-radius: 8px;
    }}
    QFrame#cartaoRegistro:hover {{ border-color: {c["destaque"]}; }}
    QFrame#cartaoRegistro[selecionado="true"] {{
        border: 2px solid {c["destaque"]};
        background: {c["faixa"]};
    }}
    QLabel#cartaoTitulo {{ font-size: 14px; font-weight: 600; }}
    QLabel#cartaoSubtitulo {{ color: {c["texto_fraco"]}; font-size: 12px; }}
    QLabel#cartaoDetalheRotulo {{ color: {c["texto_fraco"]}; font-size: 10px; }}
    QLabel#cartaoDetalheValor {{ font-size: 12px; }}
    QLabel#cartaoEtiqueta {{ font-size: 11px; font-weight: 600; }}
    QLabel#cartaoValor {{ font-size: 16px; font-weight: 600; }}
    QPushButton#cartaoAcao {{
        padding: 4px 10px;
        font-size: 12px;
        color: {c["destaque"]};
        border-color: {c["borda"]};
        background: transparent;
    }}
    QPushButton#cartaoAcao:hover {{ border-color: {c["destaque"]}; background: {c["faixa"]}; }}

    QListWidget#navegacao {{
        background: {c["superficie"]};
        border: none;
        border-right: 1px solid {c["borda"]};
        padding: 8px 6px;
        font-size: 14px;
    }}
    QListWidget#navegacao::item {{ padding: 9px 12px; border-radius: 6px; }}
    QListWidget#navegacao::item:selected {{ background: {c["destaque"]}; color: #ffffff; }}
    /* barra de abas visível: trilho cinza, aba ativa branca com marca colorida */
    QTabWidget::pane {{
        background: {c["superficie"]};
        border: 1px solid {c["borda"]};
        border-radius: 8px;
        top: -1px;
    }}
    QTabWidget::tab-bar {{ left: 8px; }}
    QTabBar {{ background: transparent; }}
    QTabBar::tab {{
        background: {c["faixa"]};
        color: {c["texto_fraco"]};
        border: 1px solid {c["borda"]};
        border-bottom: none;
        border-top-left-radius: 7px;
        border-top-right-radius: 7px;
        padding: 7px 16px 8px 16px;
        margin-right: 3px;
        font-weight: 500;
    }}
    QTabBar::tab:hover {{
        background: {c["superficie"]};
        color: {c["texto"]};
    }}
    QTabBar::tab:selected {{
        background: {c["superficie"]};
        color: {c["destaque"]};
        border-top: 3px solid {c["destaque"]};
        padding-top: 5px;
        font-weight: 700;
    }}
    QTabBar::tab:!selected {{ margin-top: 3px; }}
    QStatusBar {{ color: {c["texto_fraco"]}; }}
    """
