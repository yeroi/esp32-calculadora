@echo off
REM Arrastra un juego .py (o una carpeta) encima para precompilarlo a .mpy para el ESP32
cd /d "%~dp0"
set PY=python
where py >nul 2>nul && set PY=py -3
if "%~1"=="" (echo Arrastra un .py o una carpeta encima de compilar_mpy.bat & pause & exit /b)
%PY% pc\compilar_mpy.py %*
if errorlevel 1 (
  echo.
  echo  Algo ha fallado. Si dice "Falta ...", ejecuta instalar_librerias.bat
)
pause
