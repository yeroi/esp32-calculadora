@echo off
REM Arrastra un .sb3 encima de este archivo para convertirlo a juego de la calculadora
cd /d "%~dp0"
set PY=python
where py >nul 2>nul && set PY=py -3
if "%~1"=="" (echo Arrastra un archivo .sb3 encima de convertir_scratch.bat & pause & exit /b)
%PY% pc\sb3_a_scicalc.py "%~1"
if errorlevel 1 (
  echo.
  echo  Algo ha fallado. Si dice "Falta ...", ejecuta instalar_librerias.bat
)
pause
