@echo off
rem Gera o instalador do Financeiro Metodos no Windows.
rem Precisa: Python 3.12, o projeto com .venv (pip install -e .[empacotar]) e o Inno Setup 6.
rem A versao vem de src\honorarios\__init__.py (__version__).
setlocal
cd /d "%~dp0\.."

echo [1/4] Dependencias de empacotamento...
.venv\Scripts\python -m pip install --quiet -e .[empacotar] || goto erro

for /f "usebackq delims=" %%v in (`.venv\Scripts\python -c "import honorarios; print(honorarios.__version__)"`) do set VERSAO=%%v
if "%VERSAO%"=="" goto erro
echo [2/4] Versao %VERSAO%

echo [3/4] Gerando o programa (dist\FinanceiroMetodos)...
.venv\Scripts\pyinstaller --noconfirm --clean instalador\financeiro_metodos.spec || goto erro

echo [4/4] Gerando o instalador...
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (
    echo Inno Setup 6 nao encontrado. Instale em https://jrsoftware.org/isinfo.php
    goto erro
)
%ISCC% /DVersao=%VERSAO% instalador\financeiro_metodos.iss || goto erro

echo.
echo Pronto: instalador\saida\Instalador_Financeiro_Metodos_%VERSAO%.exe
exit /b 0

:erro
echo.
echo Falhou. Veja a mensagem acima.
exit /b 1
