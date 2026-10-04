@echo off
rem Gera o instalador do Financeiro Metodos no Windows.
rem Precisa: Python 3.12, o projeto com .venv (pip install -e .) e o Inno Setup 6.
setlocal
cd /d "%~dp0\.."

echo [1/3] Dependencias de empacotamento...
.venv\Scripts\python -m pip install --quiet pyinstaller || goto erro

echo [2/3] Gerando o programa (dist\FinanceiroMetodos)...
.venv\Scripts\pyinstaller --noconfirm --clean instalador\financeiro_metodos.spec || goto erro

echo [3/3] Gerando o instalador...
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
%ISCC% instalador\financeiro_metodos.iss || goto erro

echo.
echo Pronto: o instalador esta em instalador\saida
exit /b 0

:erro
echo.
echo Falhou. Veja a mensagem acima.
exit /b 1
