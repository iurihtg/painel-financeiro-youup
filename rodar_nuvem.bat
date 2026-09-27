@echo off
chcp 65001 >nul
title Painel Financeiro (NUVEM / Supabase) - Youup
cd /d "%~dp0"

set "SUPABASE_URL=https://hvbgzwfbqflqlwrsbnrz.supabase.co"

echo ============================================================
echo   Painel Financeiro - modo NUVEM (Supabase)
echo ============================================================
echo.
echo Cole abaixo a sua service_role key do Supabase e aperte ENTER.
echo (para colar: clique com o botao DIREITO do mouse aqui)
echo.
set /p SUPABASE_KEY=Chave:

if "%SUPABASE_KEY%"=="" (
    echo.
    echo Voce nao colou a chave. Rode de novo e cole a chave.
    pause
    exit /b 1
)

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado. Instale em https://www.python.org/downloads/ e marque "Add python.exe to PATH".
    pause
    exit /b 1
)

if not exist ".venv\Scripts\activate.bat" (
    echo Criando ambiente pela primeira vez...
    python -m venv .venv
)
call ".venv\Scripts\activate.bat"
echo Verificando dependencias...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

echo.
echo Conectando ao Supabase e abrindo no navegador...
echo Na barra lateral deve aparecer:  Backend: Supabase (nuvem)
echo.
streamlit run app.py

pause
