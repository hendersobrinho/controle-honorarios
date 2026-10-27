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
        "destaque": "#203461",         # navy da marca
        "destaque_hover": "#2E4A85",
        "atrasado": "#c0392b",
        "atencao": "#b7791f",
        "pago": "#1f7a45",
        "pago_forte": "#17603a",
        "texto_sobre_pago": "#ffffff",
        "faixa": "#f0f2f5",
        "roxo": "#7c5cff",
        "marca": "#F9B259",            # laranja da logo: contadores do menu
        "texto_sobre_marca": "#203461",  # azul da logo, legível sobre o laranja
    },
    "escuro": {
        "fundo": "#161a1f",
        "superficie": "#1e242b",
        "borda": "#2d353f",
        "texto": "#e6eaef",
        "texto_fraco": "#98a2b0",
        "destaque": "#4A6FC2",
        "destaque_hover": "#3B5DA8",
        "atrasado": "#ff7a6b",
        "atencao": "#e9b949",
        "pago": "#5fd08a",
        "pago_forte": "#7ddca0",
        "texto_sobre_pago": "#0f1f16",
        "faixa": "#222a31",
        "roxo": "#a48bff",
        "marca": "#F9B259",
        "texto_sobre_marca": "#203461",
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
    QLabel#rankingTitulo {{ font-size: 17px; font-weight: 700; }}
    QLabel#rankingCuriosidade {{
        background: {c["faixa"]};
        border-radius: 8px;
        padding: 8px 10px;
        font-size: 12px;
    }}
    QListWidget#listaGrupos {{
        background: transparent;
        border: none;
    }}
    QListWidget#listaGrupos::item {{
        padding: 10px 12px;
        margin-bottom: 4px;
        border: 1px solid {c["borda"]};
        border-radius: 8px;
    }}
    QListWidget#listaGrupos::item:selected {{
        background: {c["destaque"]};
        color: #ffffff;
        border-color: {c["destaque"]};
    }}
    QLabel#previaMensagem {{
        background: {c["faixa"]};
        border-left: 3px solid {c["destaque"]};
        border-radius: 4px;
        padding: 6px 10px;
        color: {c["texto"]};
    }}
    QLabel#previaMensagem[erro="true"] {{
        border-left-color: {c["atrasado"]};
        color: {c["atrasado"]};
    }}
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
    QPushButton#primario:hover {{
        background: {c["destaque_hover"]}; border-color: {c["destaque_hover"]};
    }}
    QPushButton#botaoPerigo {{
        background: {c["atrasado"]}; color: #ffffff; border: 1px solid {c["atrasado"]};
        font-weight: 600; padding: 6px 14px;
    }}
    QDialog#dialogoConfirmacao {{ background: {c["superficie"]}; }}
    QLabel#perguntaConfirmacao {{ font-size: 16px; font-weight: 700; }}
    QFrame#resumoConfirmacao {{
        background: {c["faixa"]}; border: 1px solid {c["borda"]}; border-radius: 8px;
    }}
    QLabel#rotuloResumoConfirmacao {{ color: {c["texto_fraco"]}; background: transparent; }}
    QLabel#valorResumoConfirmacao {{ font-weight: 600; background: transparent; }}
    QLabel#detalheConfirmacao {{ color: {c["texto_fraco"]}; }}
    QPushButton#primario:disabled {{
        background: {c["faixa"]}; border-color: {c["borda"]}; color: {c["texto_fraco"]};
    }}

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
    QLabel#cartaoEtiqueta {{
        font-size: 11px;
        font-weight: 700;
        border-radius: 9px;
        padding: 2px 9px;
    }}
    QLabel#cartaoData {{
        font-size: 12px;
        border-radius: 10px;
        padding: 3px 10px;
        background: {c["faixa"]};
        border: 1px solid {c["borda"]};
    }}
    QLabel#cartaoValor {{ font-size: 16px; font-weight: 600; }}
    QPushButton#cartaoAcao {{
        padding: 4px 10px;
        font-size: 12px;
        color: {c["destaque"]};
        border-color: {c["borda"]};
        background: transparent;
    }}
    QPushButton#cartaoAcao:hover {{ border-color: {c["destaque"]}; background: {c["faixa"]}; }}
    QToolButton#chipFiltro {{
        background: {c["superficie"]};
        border: 1px solid {c["borda"]};
        border-radius: 11px;   /* acima de meia altura o Qt ignora o arredondado */
        padding: 4px 12px;
        font-size: 12px;
        color: {c["texto"]};
    }}
    QToolButton#chipFiltro:hover {{ border-color: {c["destaque"]}; }}
    QToolButton#chipFiltro[ativo="true"] {{
        border-color: {c["destaque"]};
        color: {c["destaque"]};
        background: {c["faixa"]};
        font-weight: 600;
    }}
    QToolButton#chipFiltro::menu-indicator {{ image: none; width: 0px; }}
    QPushButton#linkFiltro {{
        border: none;
        background: transparent;
        color: {c["destaque"]};
        padding: 4px 6px;
        font-size: 12px;
    }}
    QPushButton#linkFiltro:hover {{ text-decoration: underline; }}
    QPushButton#navegaMes {{ padding: 5px 11px; font-size: 13px; }}
    QToolButton#botaoMes {{
        background: transparent;
        border: none;
        padding: 4px 8px;
        font-size: 18px;
        font-weight: 700;
        color: {c["texto"]};
    }}
    QToolButton#botaoMes:hover {{ color: {c["destaque"]}; }}
    QToolButton#botaoMes::menu-indicator {{ image: none; width: 0px; }}
    QToolButton#menuAcoes {{
        background: {c["superficie"]};
        border: 1px solid {c["borda"]};
        border-radius: 6px;
        padding: 6px 12px;
        color: {c["texto"]};
    }}
    QToolButton#menuAcoes:hover {{ border-color: {c["destaque"]}; }}
    QToolButton#menuAcoes::menu-indicator {{ image: none; width: 0px; }}
    QPushButton#cartaoPagamento {{
        padding: 4px 10px;
        font-size: 12px;
        font-weight: 600;
        color: {c["texto_sobre_pago"]};
        background: {c["pago"]};
        border: 1px solid {c["pago"]};
    }}
    QPushButton#cartaoPagamento:hover {{
        background: {c["pago_forte"]};
        border-color: {c["pago_forte"]};
    }}
    QPushButton#cartaoPagamento:disabled {{
        color: {c["texto_fraco"]};
        background: {c["faixa"]};
        border-color: {c["borda"]};
    }}

    QWidget#colunaNavegacao {{
        background: {c["superficie"]};
        border-right: 1px solid {c["borda"]};
    }}
    QListWidget#navegacao {{
        background: {c["superficie"]};
        border: none;
        padding: 8px 6px;
        font-size: 14px;
    }}
    QFrame#resumoDia {{
        background: {c["superficie"]};
        border: 1px solid {c["borda"]};
        border-radius: 12px;
    }}
    QLabel#resumoTitulo {{ font-size: 14px; font-weight: 700; }}
    /* e-mail de cobranças: lista à esquerda, leitor à direita */
    QListWidget#listaEmails {{
        background: {c["superficie"]}; border: 1px solid {c["borda"]}; border-radius: 10px;
        padding: 4px;
    }}
    QListWidget#listaEmails::item {{ border-radius: 8px; }}
    QListWidget#listaEmails::item:selected {{ background: {c["faixa"]}; }}
    QListWidget#listaEmails::item:hover {{ background: {c["faixa"]}; }}
    QFrame#itemEmail {{ background: transparent; border: none;
        border-left: 3px solid transparent; }}
    QFrame#itemEmail[naoLido="true"] {{ border-left-color: {c["destaque"]}; }}
    QLabel#remetenteEmail {{ font-size: 13px; background: transparent; }}
    QFrame#itemEmail[naoLido="true"] QLabel#remetenteEmail {{ font-weight: 700; }}
    QLabel#dataEmail {{ color: {c["texto_fraco"]}; font-size: 11px; background: transparent; }}
    QLabel#assuntoItemEmail {{ color: {c["texto_fraco"]}; font-size: 12px;
        background: transparent; }}
    QLabel#etiquetaEmail {{ font-size: 10px; font-weight: 600; padding: 1px 7px;
        border-radius: 8px; background: {c["faixa"]}; color: {c["texto_fraco"]}; }}
    QLabel#etiquetaEmail[tipo="nova"] {{ background: {c["destaque"]}; color: #ffffff; }}
    QLabel#etiquetaEmail[tipo="respondida"] {{ background: {c["pago"]};
        color: {c["texto_sobre_pago"]}; }}
    QLabel#etiquetaEmail[tipo="enviada"] {{ background: {c["marca"]};
        color: {c["texto_sobre_marca"]}; }}
    QLabel#vazioEmail {{ color: {c["texto_fraco"]}; padding: 24px;
        background: {c["superficie"]}; border: 1px dashed {c["borda"]};
        border-radius: 10px; }}
    QPushButton#abaCaixa {{
        background: {c["faixa"]}; color: {c["texto_fraco"]}; border: 1px solid {c["borda"]};
        border-radius: 8px; padding: 6px 8px; font-weight: 600;
    }}
    QPushButton#abaCaixa:hover {{ color: {c["texto"]}; }}
    QPushButton#abaCaixa:checked {{
        background: {c["destaque"]}; color: #ffffff; border-color: {c["destaque"]};
    }}
    QLabel#vazioTitulo {{ font-size: 16px; font-weight: 600; color: {c["texto_fraco"]}; }}
    QFrame#cabecalhoEmail {{ background: {c["superficie"]}; border: 1px solid {c["borda"]};
        border-radius: 10px; }}
    QLabel#assuntoEmail {{ font-size: 17px; font-weight: 700; background: transparent; }}
    QLabel#deEmail {{ background: transparent; }}
    QLabel#codigoEntrada {{ font-size: 30px; font-weight: 700; letter-spacing: 4px;
        padding: 12px; border: 1px dashed {c["borda"]}; border-radius: 10px; }}
    QLabel#ajudaConta {{ color: {c["texto_fraco"]}; background: {c["faixa"]};
        border-radius: 8px; padding: 10px; }}
    QLabel#resultadoConexao[ok="true"] {{ color: {c["pago"]}; font-weight: 600; }}
    QLabel#resultadoConexao[ok="false"] {{ color: {c["atrasado"]}; }}
    QFrame#faixaSaiu {{ background: {c["faixa"]}; border: 1px solid {c["borda"]};
        border-left: 4px solid {c["pago"]}; border-radius: 8px; }}
    QLabel#textoSaiu {{ background: transparent; }}
    QLabel#totalBaixa {{ font-weight: 600; }}
    QPushButton#botaoNotificacoes {{
        background: {c["faixa"]}; border: 1px solid {c["borda"]}; border-radius: 8px;
        text-align: left; padding: 0px;
    }}
    QPushButton#botaoNotificacoes:hover {{ border-color: {c["destaque"]}; }}
    QLabel#contadorNotificacoes {{
        background: {c["atrasado"]}; color: #ffffff; border-radius: 10px;
        min-width: 20px; min-height: 20px; max-height: 20px; padding: 0px 6px;
        font-size: 11px; font-weight: 700;
    }}
    QFrame#listaNotificacoes {{
        background: {c["superficie"]}; border: 1px solid {c["borda"]}; border-radius: 10px;
    }}
    QFrame#itemNotificacao {{
        background: {c["faixa"]}; border: none; border-left: 3px solid {c["atrasado"]};
        border-radius: 6px;
    }}
    QFrame#itemNotificacao[lida="true"] {{
        background: transparent; border-left-color: {c["borda"]};
    }}
    QLabel#tituloNotificacao {{ font-weight: 700; background: transparent; }}
    QFrame#itemNotificacao[lida="true"] QLabel#tituloNotificacao {{
        font-weight: 400; color: {c["texto_fraco"]};
    }}
    QLabel#detalheNotificacao {{
        color: {c["texto_fraco"]}; font-size: 12px; background: transparent;
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
