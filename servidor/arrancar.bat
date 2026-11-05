@echo off
REM ============================================================
REM  Arranca el servidor de correo (SMTP + webmail) de la practica IFOR.
REM  Ejecutar como ADMINISTRADOR si usas el puerto 25 (por defecto).
REM  Sin administrador: edita este archivo y anade  --puerto 2525
REM ============================================================
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 servidor.py todo %*
) else (
    python servidor.py todo %*
)
timeout /t 2 >nul
start "" "http://localhost:8080/"
echo.
pause
