@echo off
REM Instala solo las librerias de Python (requirements.txt)
cd /d "%~dp0"
set PY=python
where py >nul 2>nul && set PY=py -3
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo  Algo ha fallado. Si dice "Falta ...", ejecuta instalar_librerias.bat
)
pause
