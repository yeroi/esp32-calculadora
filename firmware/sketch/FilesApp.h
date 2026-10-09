// =============================================================================
//  FilesApp.h  —  "Archivos SD": explorador completo + visores
// -----------------------------------------------------------------------------
//  ▲▼ mover · EXE abrir · ◄/DEL/AC subir carpeta · SHIFT+EXE recargar.
//  Abre texto/código, imágenes y binarios (hex). Todo de SOLO lectura.
// =============================================================================
#pragma once
#include "App.h"
#include "FileViewer.h"
#include "FolderBrowser.h"

class FilesApp : public App {
 public:
  explicit FilesApp(AppManager& m);

  const char* title() const override { return "Archivos SD"; }
  void onEnter() override;
  void draw() override;
  void onKey(const KeyEvent& ev) override;
  void onExit() override { viewer_.close(); }

 private:
  void drawFooter();

  FolderBrowser browser_;
  FileViewer viewer_;
};
