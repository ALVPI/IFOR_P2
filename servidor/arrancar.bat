@echo off
REM ============================================================
REM  Arranca el servidor de correo (SMTP + webmail) de la practica IFOR.
REM  Ejecutar como ADMINISTRADOR si usas el puerto 25 (por defecto).
REM  Sin administrador: edita este archivo y anade  --puerto 2525
REM ============================================================
cd /d "%~dp0"

REM webmail en el navegador ~3 s despues de arrancar. Va en segundo
REM plano porque "servidor.py todo" bloquea mientras el servidor vive.
REM Para dejar de abrirlo solo: borra la linea de abajo.
start "" /b cmd /c "ping -n 4 127.0.0.1 >nul & start http://localhost:8080/"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 servidor.py todo %*
) else (
    python servidor.py todo %*
)
echo.
pause
