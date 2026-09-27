@echo off
chcp 65001 >nul
title Contabilidade e Previsao - Iuri/Youup
cd /d "%~dp0"

echo ============================================================
echo   Contabilidade e Previsao de Gastos
echo ============================================================
echo.

REM 1) Confere se o Python esta instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado.
    echo.
    echo Instale o Python em https://www.python.org/downloads/
    echo IMPORTANTE: na primeira tela do instalador, MARQUE a caixa
    echo "Add python.exe to PATH" antes de clicar em Install.
    echo.
    pause
    exit /b 1
)

REM 2) Cria o ambiente isolado na primeira vez
if not exist ".venv\Scripts\activate.bat" (
    echo Criando ambiente pela primeira vez...
    python -m venv .venv
)
call ".venv\Scripts\activate.bat"

REM 3) Instala/atualiza as dependencias
echo Verificando dependencias ^(pode demorar so na primeira vez^)...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

REM 4) Abre o app no navegador
echo.
echo Abrindo no navegador... deixe ESTA janela aberta enquanto usa.
echo Para fechar o app depois: volte aqui e aperte Ctrl+C, ou feche a janela.
echo.
streamlit run app.py

pause
