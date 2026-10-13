@echo off
REM SciCalc Link: pasar archivos entre el PC y la calculadora
cd /d "%~dp0"
set PY=python
where py >nul 2>nul && set PY=py -3
%PY% pc\scicalc_link.py %*
if errorlevel 1 (
  echo.
  echo  Algo ha fallado. Si dice "Falta ...", ejecuta instalar_librerias.bat
)
pause
