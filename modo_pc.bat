@echo off
REM Modo PC: la pantalla del ESP32 (conectado por USB) en una ventana del PC
cd /d "%~dp0"
set PY=python
where py >nul 2>nul && set PY=py -3
%PY% pc\scicalc_pantalla.py %*
if errorlevel 1 (
  echo.
  echo  Algo ha fallado. Si dice "Falta ...", ejecuta instalar_librerias.bat
)
pause
