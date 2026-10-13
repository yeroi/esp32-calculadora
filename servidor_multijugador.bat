@echo off
REM Servidor dedicado para el multijugador (mundos en pc\mundos_servidor)
cd /d "%~dp0"
set PY=python
where py >nul 2>nul && set PY=py -3
%PY% pc\scicalc_servidor.py %*
if errorlevel 1 (
  echo.
  echo  Algo ha fallado. Si dice "Falta ...", ejecuta instalar_librerias.bat
)
pause
