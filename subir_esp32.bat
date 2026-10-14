@echo off
REM ============================================================================
REM  subir_esp32.bat  -  Compila el firmware y lo sube al ESP32 (PlatformIO)
REM ----------------------------------------------------------------------------
REM  No hace falta VS Code: usa PlatformIO desde Python (se instala solo).
REM  La PRIMERA vez descarga el compilador del ESP32 (~500 MB): tarda un rato.
REM  Antes de subir: enchufa el ESP32 por USB y cierra scicalc_pantalla.py
REM  (el puerto solo lo puede usar un programa a la vez).
REM ============================================================================
cd /d "%~dp0"
set PY=python
where py >nul 2>nul && set PY=py -3

%PY% -m platformio --version >nul 2>nul
if errorlevel 1 (
  echo  Instalando PlatformIO...
  %PY% -m pip install -U platformio
)

echo.
echo  Que version quieres subir?
echo    1 = Modo PC  (pantalla y teclado en el PC)          [normal]
echo    2 = Modo PC sin Bluetooth (mas memoria para juegos)
echo    3 = Hardware real (pantalla TFT + teclado cableados)
echo    4 = Hardware real sin Bluetooth
echo    5 = Solo compilar (modo PC), sin subir
set /p OP= Elige (1-5) [1]: 
if "%OP%"=="" set OP=1
set ENV=esp32dev
set TGT=-t upload
if "%OP%"=="2" set ENV=esp32dev-sinbt
if "%OP%"=="3" set ENV=esp32dev-hw
if "%OP%"=="4" set ENV=esp32dev-hw-sinbt
if "%OP%"=="5" set TGT=

echo.
echo  Compilando %ENV% ...  (si se queda en "Connecting...", manten pulsado BOOT)
%PY% -m platformio run -d firmware -e %ENV% %TGT%
if errorlevel 1 (
  echo.
  echo  FALLO. Si no encuentra el puerto: revisa el cable USB ^(que sea de datos^),
  echo  el driver CP2102/CH340 y que scicalc_pantalla.py este cerrado.
  pause
  exit /b 1
)
echo.
if "%OP%"=="1" echo  Listo. Ahora abre modo_pc.bat
if "%OP%"=="2" echo  Listo. Ahora abre modo_pc.bat
echo  Listo.
pause
