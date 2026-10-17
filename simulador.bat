@echo off
REM Abre el simulador de la calculadora (no necesita el ESP32)
cd /d "%~dp0"
set PY=python
where py >nul 2>nul && set PY=py -3
%PY% simulador\scicalc_sim.py
if errorlevel 1 (
  echo.
  echo  Algo ha fallado. Si dice "Falta ...", ejecuta instalar_librerias.bat
)
pause
