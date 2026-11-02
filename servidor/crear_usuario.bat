@echo off
REM ============================================================
REM  Crea un buzón de correo, p. ej.: pepe -> pepe@empresa.local
REM ============================================================
cd /d "%~dp0"

set /p NOMBRE=Nombre del buzón nuevo:
if "%NOMBRE%"=="" goto fin

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 servidor.py usuario alta %NOMBRE%
) else (
    python servidor.py usuario alta %NOMBRE%
)

:fin
echo.
pause
