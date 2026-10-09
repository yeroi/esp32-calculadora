// =============================================================================
//  FolderBrowser.h  —  Explorador de carpetas de la SD (componente reutilizable)
// -----------------------------------------------------------------------------
//  Lo usan "Archivos SD" (todo) y "Python" (solo carpetas y .py).
//  Igual que Browser del simulador:
//    * Carpetas primero, luego archivos, orden alfabético.
//    * ".." como primera fila para subir (salvo en la raíz).
//    * ▲▼ mover · EXE/► abrir · ◄/DEL subir.
//  Redibujado parcial: al mover la selección solo se repintan las 2 filas
//  que cambian, salvo que la lista tenga que desplazarse.
// =============================================================================
#pragma once
#include <Arduino.h>
#include <vector>
#include "Display.h"
#include "Keyboard.h"
#include "ScrollList.h"
#include "Storage.h"

class FolderBrowser {
 public:
  static constexpr uint8_t ROWS = 7;

  FolderBrowser(Display& d, Storage& s, bool onlyPy) : gfx_(d), sd_(s), onlyPy_(onlyPy) {}

  void refresh();                         // relee la carpeta actual
  bool goUp();                            // sube una carpeta; false si ya está en "/"
  const String& cwd() const { return cwd_; }

  // Resultado de una tecla
  enum class Result : uint8_t { None, Moved, Changed, OpenFile };
  // Procesa la tecla y hace el repintado parcial que toque.
  //  Changed  -> se cambió de carpeta: ya se ha repintado la lista entera.
  //  OpenFile -> el usuario eligió un archivo: ver selectedPath().
  Result key(const KeyEvent& ev);
  String selectedPath() const;

  void draw(const char* emptyMsg = "Carpeta vacía");   // ruta + lista completas

 private:
  bool isUp(uint16_t i) const { return hasUp_ && i == 0; }
  const DirEntry& entry(uint16_t i) const { return items_[i - (hasUp_ ? 1 : 0)]; }
  void drawPathBar();
  void drawRows();
  void drawRow(uint16_t i);
  void drawIcon(FileKind k, int16_t x, int16_t y);

  Display& gfx_;
  Storage& sd_;
  bool onlyPy_;
  String cwd_ = "/";
  std::vector<DirEntry> items_;
  bool hasUp_ = false;
  bool truncated_ = false;
  bool ok_ = true;                        // la carpeta se pudo leer
  ScrollList list_;
  const char* emptyMsg_ = "Carpeta vacía";
};
