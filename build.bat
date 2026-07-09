@echo off
chcp 65001 >nul
echo ============================================
echo   Construir Ajedrez Online .exe
echo ============================================
echo.
echo Requisitos: Python 3.8+ instalado
echo.
echo Paso 1: Instalar dependencias
echo.
pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo Error instalando dependencias
    pause
    exit /b 1
)
echo.
echo Paso 2: Compilar a .exe con PyInstaller
echo.
pyinstaller --onefile --windowed --name "AjedrezOnline" chess_client.py
if %ERRORLEVEL% neq 0 (
    echo Error en la compilacion
    pause
    exit /b 1
)
echo.
echo ============================================
echo   EXITO: dist\AjedrezOnline.exe creado
echo ============================================
pause
