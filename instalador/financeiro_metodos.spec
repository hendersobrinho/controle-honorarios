# -*- mode: python ; coding: utf-8 -*-
"""Gera o programa para Windows (pasta dist/FinanceiroMetodos).

    pyinstaller --noconfirm instalador/financeiro_metodos.spec

A pasta gerada é o que o Inno Setup (financeiro_metodos.iss) empacota. Rode no
Windows, dentro do ambiente virtual com o projeto instalado (pip install -e .).
"""

import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

RAIZ = Path(SPECPATH).parent
PACOTE = RAIZ / "src" / "honorarios"

# a versão do programa, lida do pacote (src/honorarios/__init__.py)
VERSAO = re.search(
    r'__version__\s*=\s*"([^"]+)"', (PACOTE / "__init__.py").read_text(encoding="utf-8")
).group(1)
NUMEROS = tuple(int(n) for n in (VERSAO.split(".") + ["0"] * 4)[:4])

# o que o Windows mostra em Propriedades → Detalhes do FinanceiroMetodos.exe
# (o módulo só existe no PyInstaller do Windows)
INFO_VERSAO = None
if sys.platform == "win32":
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    INFO_VERSAO = VSVersionInfo(
        ffi=FixedFileInfo(filevers=NUMEROS, prodvers=NUMEROS),
        kids=[
            StringFileInfo([
                StringTable("041604B0", [
                    StringStruct("CompanyName", "Métodos Serviços Contábeis"),
                    StringStruct("FileDescription", "Financeiro Métodos"),
                    StringStruct("FileVersion", VERSAO),
                    StringStruct("InternalName", "FinanceiroMetodos"),
                    StringStruct("OriginalFilename", "FinanceiroMetodos.exe"),
                    StringStruct("ProductName", "Financeiro Métodos"),
                    StringStruct("ProductVersion", VERSAO),
                ])
            ]),
            VarFileInfo([VarStruct("Translation", [0x0416, 1200])]),
        ],
    )

dados = [
    # logo, ícone e fundo modelo da imagem de cobrança
    (str(PACOTE / "recursos"), "honorarios/recursos"),
    # as migrations do banco vão como arquivos: o Alembic as lê do disco
    (str(PACOTE / "infra" / "migracoes"), "honorarios/infra/migracoes"),
    (str(RAIZ / "instalador" / "financeiro_metodos.ico"), "."),
]
dados += collect_data_files("reportlab")        # fontes dos PDFs
dados += collect_data_files("alembic")          # modelos (script.py.mako)

ocultos = []
ocultos += collect_submodules("honorarios")      # módulos importados de dentro de funções
ocultos += collect_submodules("keyring.backends")  # cofre de senhas do Windows
# sem o pacote de testes do Alembic (não é usado e falha ao ser coletado)
ocultos += collect_submodules("alembic", filter=lambda nome: ".testing" not in nome)
ocultos += collect_submodules("psycopg")           # o banco do escritório (PostgreSQL)
ocultos += collect_submodules("psycopg_binary")
ocultos += ["sqlalchemy.dialects.sqlite", "sqlalchemy.dialects.postgresql",
            "sqlalchemy.dialects.postgresql.psycopg", "logging.config"]

a = Analysis(
    [str(RAIZ / "instalador" / "iniciar.py")],
    pathex=[str(RAIZ / "src")],
    datas=dados,
    hiddenimports=ocultos,
    excludes=["tkinter", "pytest", "pytestqt", "ruff"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FinanceiroMetodos",
    icon=str(RAIZ / "instalador" / "financeiro_metodos.ico"),
    version=INFO_VERSAO,
    console=False,          # programa de janela: sem a tela preta do console
    upx=False,
)
coleta = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="FinanceiroMetodos",
)
