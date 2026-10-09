// =============================================================================
//  PythonApp.h  —  Modo Python: explorador de scripts y consola de salida
// -----------------------------------------------------------------------------
//  Igual que el simulador:
//    * Explorador: solo carpetas y .py. EXE ejecuta. SHIFT+EXE ve el código.
//    * Consola: barra de estado (ejecutando / OK / ERROR / WATCHDOG...) y la
//      salida del script, con las líneas largas partidas por palabras.
//      Mientras corre: AC (o DEL) lo detiene.
//      Al terminar: EXE repetir · ▲▼ desplazar · ◄/AC/DEL volver.
//  El script corre en PySandbox (otra tarea): esta app solo lo pinta.
//  En modo examen Python está bloqueado.
// =============================================================================
#pragma once
#include <vector>
#include "App.h"
#include "FileViewer.h"
#include "FolderBrowser.h"
#include "PySandbox.h"

class PythonApp : public App {
 public:
  explicit PythonApp(AppManager& m);

  const char* title() const override { return "Python"; }
  void onEnter() override;
  void draw() override;
  void onKey(const KeyEvent& ev) override;
  void onTick(uint32_t nowMs) override;
  void onExit() override;

  // Ejecutar un script desde otro sitio (Consola, en el futuro)
  void run(const String& path);

 private:
  struct Row { String text; uint16_t color; };
  static constexpr int16_t STATUS_Y = Display::BODY_Y;
  static constexpr int16_t STATUS_H = 14;
  static constexpr int16_t CON_Y = STATUS_Y + STATUS_H + 3;
  static constexpr int16_t ROW_H = 10;
  static constexpr uint8_t ROWS = 18;
  static constexpr uint8_t COLS = 52;

  void start(const String& path);
  void drawFooter();
  void drawStatus(bool force);
  void drawConsole(bool force);
  void drawConsoleFooter();
  void buildRows();
  void closeConsole();

  FolderBrowser browser_;
  FileViewer viewer_;
  bool console_ = false;               // mostrando la salida de un script
  String script_;
  std::vector<Row> rows_;              // salida ya partida en filas
  std::vector<String> shown_;          // lo pintado en cada fila (para no repetir)
  std::vector<uint16_t> shownColor_;
  int scroll_ = 0;                     // filas desplazadas hacia arriba
  uint32_t seenVersion_ = 0;
  String statusShown_;
  int stateShown_ = -1;
  uint32_t nextPaint_ = 0;
  bool cursorOn_ = false;
};
