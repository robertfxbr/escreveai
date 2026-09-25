@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Preparando o ambiente na primeira execucao...
    python -m venv .venv
    if errorlevel 1 goto :error
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo Nao foi possivel iniciar o app. Verifique a mensagem acima.
pause
exit /b 1
