// =============================================================================
//  ESP32 SciCalc  —  Paso 3: menú e interfaz completos
// -----------------------------------------------------------------------------
//  Placa:     ESP32 DevKit (ELEGOO, ESP32-WROOM-32, sin PSRAM) / Wokwi
//  Pantalla:  ILI9341 320x240 (SPI)       MicroSD: SPI (bus compartido)
//  Teclado:   2 matrices 4x4 = 32 teclas  (bloque A funciones + B numérico)
//
//  MODO PC (SCICALC_REMOTE = 1 en config.h, por defecto): sin pantalla,
//  teclado ni SD. Todo corre aquí; el programa pc/scicalc_pantalla.py dibuja
//  la pantalla, manda las teclas, hace de MicroSD y suena por el PC.
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
#include "Buzzer.h"
#include "PySandbox.h"
#if SCICALC_REMOTE
#include "RemoteLink.h"
#endif

// ---- Servicios del sistema ---------------------------------------------------
Display        display;
Storage        storage;
#if SCICALC_REMOTE
RemoteKeyboard keyboard;          // las teclas llegan del PC
#else
MatrixKeyboard keyboard;          // hardware real: Mcp23017Keyboard (paso 9)
#endif
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

#if SCICALC_REMOTE
static void sendState();          // declarada aquí: algunas versiones del preprocesador de
#endif                            // Arduino colocan mal el prototipo que generan solas

void setup() {
#if SCICALC_REMOTE
  remoteLink.begin(REMOTE_BAUD);              // abre el Serial a REMOTE_BAUD
  Serial.printf("\n%s v%s (modo PC)\n", FW_NAME, FW_VERSION);
  // Da tiempo a que el programa del PC conecte para que se vea el arranque.
  // Si no llega, sigue igual: al conectar más tarde se repinta todo.
  bool pc = remoteLink.waitConnected(REMOTE_WAIT_MS);
  Serial.printf("[boot] PC %s\n", pc ? "conectado" : "no conectado (se espera)");
#else
  Serial.begin(115200);
  Serial.printf("\n%s v%s\n", FW_NAME, FW_VERSION);
#endif
  buzzer.begin();

  // ---- Arranque con autodiagnóstico ------------------------------------------
  display.begin();
  BootScreen boot(display, 5);
  boot.begin();
  boot.check("Pantalla", SCICALC_REMOTE ? "PC" : "OK", Theme::OK);
  bool kbOk = keyboard.begin();
  boot.check("Teclado", kbOk ? "OK" : "FALLO", kbOk ? Theme::OK : Theme::ERR);
  sysState.sdMounted = storage.begin();
  boot.check("MicroSD", sysState.sdMounted ? (SCICALC_REMOTE_SD ? "PC" : "OK") : "NO (sigue sin SD)",
             sysState.sdMounted ? Theme::OK : Theme::ERR);
  bool psram = ESP.getPsramSize() > 0;
  boot.check("PSRAM", psram ? "OK" : "no (WROOM)", psram ? Theme::OK : Theme::WARN);
  dialogs.begin();
  pySandbox.begin(storage, dialogs);
  boot.check("Sandbox Python", "MicroPython 1.24", Theme::OK);
  boot.finish();

  // ---- Menú principal (teclas 1-6) ---------------------------------------------
  menuApp.addItem("Calculadora", "C++ nativo", &calcApp);
  menuApp.addItem("Python", "sandbox .py", &pythonApp);
  menuApp.addItem("Archivos SD", "fotos · texto · todo", &filesApp);
  menuApp.addItem("Consola", "tipo cmd", &consoleApp);
  menuApp.addItem("Ajustes", "Wi-Fi · BT · USB", &settingsApp);
  menuApp.addItem("Diagnóstico", "HW y teclado", &diagApp);
  apps.setHome(&menuApp);

  buzzer.chime();
  keyboard.flush();               // ignora lo pulsado durante el arranque
  display.clear();
  apps.goHome();
  Serial.printf("[boot] heap libre %u KB, bloque máx %u KB\n", (unsigned)(ESP.getFreeHeap() / 1024),
                (unsigned)(ESP.getMaxAllocHeap() / 1024));
}

#if SCICALC_REMOTE
// Estado del sistema para el panel del programa del PC (1 vez por segundo)
static void sendState() {
  static uint32_t next = 0;
  uint32_t now = millis();
  if ((int32_t)(now - next) < 0) return;
  next = now + 1000;
  char js[320];
  int n = snprintf(js, sizeof js,
      "{\"heap\":%u,\"maxblk\":%u,\"minheap\":%u,\"up\":%lu,\"app\":\"%s\","
      "\"deg\":%d,\"exam\":%d,\"wifi\":%d,\"bt\":%d,\"sd\":%d,\"cpu\":%lu,\"chip\":\"%s\"}",
      (unsigned)ESP.getFreeHeap(), (unsigned)ESP.getMaxAllocHeap(), (unsigned)ESP.getMinFreeHeap(),
      (unsigned long)(now / 1000), statusBar.title(), sysState.degrees, sysState.exam,
      sysState.wifiConnected, sysState.btOn, sysState.sdMounted,
      (unsigned long)getCpuFrequencyMhz(), ESP.getChipModel());
  if (n > 0 && n < (int)sizeof js) remoteLink.send(Proto::STATE, (const uint8_t*)js, n);
}
#endif

void loop() {
#if SCICALC_REMOTE
  sysState.sdMounted = storage.mounted();     // la "SD" es el PC: va y viene
  sysState.batteryPct = remoteLink.batteryPct();
  sysState.charging = remoteLink.charging();
  sendState();
#endif
  apps.update();                  // diálogos -> teclas -> app activa -> dibujo
}
