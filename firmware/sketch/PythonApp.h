// =============================================================================
//  PythonApp.h  —  Modo Python: explorador de scripts .py
// -----------------------------------------------------------------------------
//  Muestra solo carpetas y archivos .py. EXE sobre un script lo ejecutará en
//  el sandbox MicroPython (Paso 5: tarea FreeRTOS con heap propio, watchdog
//  de 5 s, permisos de escritura). En el Paso 3 todavía no hay intérprete:
//  EXE ofrece ver el código en modo lectura.
//
//  En modo examen Python está bloqueado (mismo aviso que el simulador).
// =============================================================================
#pragma once
#include "App.h"
#include "FileViewer.h"
#include "FolderBrowser.h"

class PythonApp : public App {
 public:
  explicit PythonApp(AppManager& m);

  const char* title() const override { return "Python"; }
  void onEnter() override;
  void draw() override;
  void onKey(const KeyEvent& ev) override;
  void onExit() override { viewer_.close(); }

 private:
  void start(const String& path);
  void drawFooter();

  FolderBrowser browser_;
  FileViewer viewer_;
};
