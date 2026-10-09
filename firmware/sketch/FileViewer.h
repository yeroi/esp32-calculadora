// =============================================================================
//  FileViewer.h  —  Visor de archivos de solo lectura (componente reutilizable)
// -----------------------------------------------------------------------------
//  Elige la vista según el CONTENIDO (como FilesApp.open() del simulador):
//    * Imagen (PNG/JPG/BMP/GIF) -> escalada y centrada
//    * Texto UTF-8               -> con números de línea; los .py con resaltado
//                                   de sintaxis (comentarios, cadenas, claves)
//    * Cualquier otra cosa       -> vista hexadecimal
//
//  RAM: el texto NO se carga entero. Se indexa una vez el inicio de cada línea
//  (4 bytes por línea, máx. MAX_LINES) y en cada repintado se leen de la SD
//  solo las 18 líneas visibles.
//
//  Teclas: ▲▼ desplazar · ► página siguiente · ◄/DEL/AC cerrar
// =============================================================================
#pragma once
#include <Arduino.h>
#include <vector>
#include "Display.h"
#include "ImageDecoder.h"
#include "Keyboard.h"
#include "Storage.h"

class FileViewer {
 public:
  static constexpr uint16_t MAX_LINES = 4000;     // 16 KB de índice como máximo
  static constexpr uint8_t TEXT_ROWS = 18;
  static constexpr uint8_t HEX_ROWS = 16;
  static constexpr uint8_t HEX_COLS = 8;          // bytes por fila (cabe en 320 px)

  FileViewer(Display& d, Storage& s) : gfx_(d), sd_(s) {}

  bool open(const String& path);   // false si no se puede leer
  void close();                    // libera la memoria
  bool isOpen() const { return mode_ != Mode::None; }
  const String& path() const { return path_; }

  void draw();                     // cuerpo completo (el gestor ya lo limpió)
  // Devuelve true si el usuario pidió cerrar el visor
  bool onKey(const KeyEvent& ev);

 private:
  enum class Mode : uint8_t { None, Text, Hex, Image };

  bool looksLikeText();
  void indexLines();
  void drawText();
  void drawTextLine(int16_t y, const String& line);
  void drawCode(int16_t x, int16_t y, const String& line);
  void drawHex();
  void drawImage();
  void drawFooter();

  Display& gfx_;
  Storage& sd_;
  Mode mode_ = Mode::None;
  String path_;
  uint32_t size_ = 0;
  bool isPy_ = false;

  std::vector<uint32_t> lineOff_;  // desplazamiento de cada línea en el archivo
  bool linesCut_ = false;          // había más de MAX_LINES
  uint16_t top_ = 0;               // primera línea (texto) o fila (hex) visible

  ImageDecoder::Info img_;
};
