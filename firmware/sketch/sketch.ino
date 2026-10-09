// =============================================================================
//  ESP32 SciCalc  —  Paso 3: menú e interfaz completos
// -----------------------------------------------------------------------------
//  Placa:     ESP32 DevKit (ELEGOO, ESP32-WROOM-32, sin PSRAM) / Wokwi
//  Pantalla:  ILI9341 320x240 (SPI)       MicroSD: SPI (bus compartido)
//  Teclado:   2 matrices 4x4 = 32 teclas  (bloque A funciones + B numérico)
//
//  Arquitectura (todo en esta carpeta, plana, para Wokwi / Arduino IDE):
//    config.h, Theme.h          pines, constantes y paleta
//    Display.*                  HAL gráfica (hoy Adafruit_ILI9341)
//    Keyboard.*                 escaneo en tarea FreeRTOS (core 0) -> cola
//    Storage.*                  MicroSD de SOLO LECTURA + utilidades de rutas
//    SystemState.h              estado global (DEG/RAD, radios, examen...)
//    StatusBar.*                barra de estado por "instantáneas"
//    Dialog.*                   diálogos modales (también desde otras tareas)
//    App.h / AppManager.cpp     marco de modos + teclas globales
//    ScrollList.h, FolderBrowser.*, FileViewer.*, ImageDecoder.*  componentes
//    MenuApp, CalcApp, PythonApp, FilesApp, SettingsApp, DiagApp  los modos
//    BootScreen.*               arranque con autodiagnóstico
// =============================================================================
#include <Arduino.h>
#include "config.h"
#include "App.h"
#include "BootScreen.h"
#include "CalcApp.h"
#include "DiagApp.h"
#include "FilesApp.h"
#include "MenuApp.h"
#include "PlaceholderApp.h"
#include "PythonApp.h"
#include "SettingsApp.h"

// ---- Servicios del sistema ---------------------------------------------------
Display        display;
Storage        storage;
MatrixKeyboard keyboard;          // hardware real: Mcp23017Keyboard (paso 9)
SystemState    sysState;
StatusBar      statusBar(display, sysState);
DialogManager  dialogs(display);
AppManager     apps(display, keyboard, storage, sysState, statusBar, dialogs);

// ---- Modos -------------------------------------------------------------------
MenuApp        menuApp(apps);
CalcApp        calcApp(apps);
PythonApp      pythonApp(apps);
FilesApp       filesApp(apps);
PlaceholderApp consoleApp(apps, "Consola", "Consola tipo cmd",
                          "help, ls, cd, cat, tree, python x.py...",
                          "Necesita la tecla ALPHA para escribir letras");
SettingsApp    settingsApp(apps);
DiagApp        diagApp(apps);

void setup() {
  Serial.begin(115200);
  Serial.printf("\n%s v%s\n", FW_NAME, FW_VERSION);

  // ---- Arranque con autodiagnóstico ------------------------------------------
  display.begin();
  BootScreen boot(display, 5);
  boot.begin();
  boot.check("Pantalla", "OK", Theme::OK);
  bool kbOk = keyboard.begin();
  boot.check("Teclado", kbOk ? "OK" : "FALLO", kbOk ? Theme::OK : Theme::ERR);
  sysState.sdMounted = storage.begin();
  boot.check("MicroSD", sysState.sdMounted ? "OK" : "NO (sigue sin SD)",
             sysState.sdMounted ? Theme::OK : Theme::ERR);
  bool psram = ESP.getPsramSize() > 0;
  boot.check("PSRAM", psram ? "OK" : "no (WROOM)", psram ? Theme::OK : Theme::WARN);
  boot.check("Sandbox Python", "(Paso 5)", Theme::MUTED);
  dialogs.begin();
  boot.finish();

  // ---- Menú principal (teclas 1-6) ---------------------------------------------
  menuApp.addItem("Calculadora", "C++ nativo", &calcApp);
  menuApp.addItem("Python", "sandbox .py", &pythonApp);
  menuApp.addItem("Archivos SD", "fotos · texto · todo", &filesApp);
  menuApp.addItem("Consola", "tipo cmd", &consoleApp);
  menuApp.addItem("Ajustes", "Wi-Fi · BT · USB", &settingsApp);
  menuApp.addItem("Diagnóstico", "HW y teclado", &diagApp);
  apps.setHome(&menuApp);

  keyboard.flush();               // ignora lo pulsado durante el arranque
  display.clear();
  apps.goHome();
  Serial.printf("[boot] heap libre %u KB, bloque máx %u KB\n", (unsigned)(ESP.getFreeHeap() / 1024),
                (unsigned)(ESP.getMaxAllocHeap() / 1024));
}

void loop() {
  apps.update();                  // diálogos -> teclas -> app activa -> dibujo
}
