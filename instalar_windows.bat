@echo off
REM ============================================================================
REM  instalar_windows.bat  -  Prepara un Windows recien instalado para SciCalc
REM ----------------------------------------------------------------------------
REM  Instala (con winget, el instalador de Windows 10/11):
REM    * Python 3.12 + las librerias de requirements.txt
REM    * Git
REM    * VS Code + extension PlatformIO (para compilar y subir el firmware)
REM  Doble clic y esperar. Se puede volver a ejecutar sin problema.
REM ============================================================================
setlocal
cd /d "%~dp0"
title Instalador SciCalc

echo.
echo  === Instalador ESP32 SciCalc ===
echo.

where winget >nul 2>nul
if errorlevel 1 (
  echo  No encuentro "winget". Abre Microsoft Store, busca "Instalador de aplicacion"
  echo  ^(App Installer^), actualizalo y vuelve a ejecutar este archivo.
  pause
  exit /b 1
)

set WG=winget install -e --accept-package-agreements --accept-source-agreements --silent

echo  [1/4] Python 3.12...
%WG% --id Python.Python.3.12
echo  [2/4] Git...
%WG% --id Git.Git
echo  [3/4] VS Code...
%WG% --id Microsoft.VisualStudioCode

REM ---- buscar python (el PATH de esta ventana aun no esta actualizado) ----
set PY=
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%ProgramFiles%\Python312\python.exe" set PY="%ProgramFiles%\Python312\python.exe"
if not defined PY (
  where py >nul 2>nul && set PY=py -3
)
if not defined PY (
  where python >nul 2>nul && set PY=python
)
if not defined PY (
  echo  No encuentro Python. Cierra esta ventana, abre otra y vuelve a ejecutar el .bat.
  pause
  exit /b 1
)

echo  [4/4] Librerias de Python...
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo  Fallo al instalar las librerias. Revisa la conexion y vuelve a probar.
  pause
  exit /b 1
)

REM ---- extension PlatformIO para VS Code ----
set CODE=
if exist "%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd" set CODE="%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd"
if not defined CODE if exist "%ProgramFiles%\Microsoft VS Code\bin\code.cmd" set CODE="%ProgramFiles%\Microsoft VS Code\bin\code.cmd"
if defined CODE (
  echo  Extension PlatformIO para VS Code...
  call %CODE% --install-extension platformio.platformio-ide --force
) else (
  echo  Abre VS Code y en Extensiones instala "PlatformIO IDE".
)

echo.
echo  ===================== LISTO =====================
echo   Simulador:   python simulador\scicalc_sim.py
echo   Modo PC:     python pc\scicalc_pantalla.py
echo   Firmware:    VS Code ^> abrir carpeta "firmware" ^> PlatformIO ^> Upload
echo                ^(entorno esp32dev = modo PC, esp32dev-hw = calculadora^)
echo.
echo   Si Windows no ve el ESP32 por USB ^(no sale puerto COM^), instala el
echo   driver del chip USB de tu placa:
echo     CP2102: https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers
echo     CH340:  https://www.wch-ic.com/downloads/CH341SER_EXE.html
echo  =================================================
echo.
set /p R= Abrir ya el simulador? (s/n): 
if /i "%R%"=="s" start "" %PY% simulador\scicalc_sim.py
pause
