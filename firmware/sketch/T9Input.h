// =============================================================================
//  T9Input.h  —  Escribir texto con el teclado numérico (como un Nokia)
// -----------------------------------------------------------------------------
//  Igual que la clase T9 del simulador:
//    * modo T9:  2 = abc, 3 = def ... 9 = wxyz, 0 = espacio, 1 = . , - _ ! ? 1
//      Repetir la tecla antes de 1 s cambia la letra; SHIFT pone mayúscula;
//      la primera letra va en mayúscula. La tecla "." escribe un punto.
//    * modo PASS: como T9 pero la primera letra en minúscula y el texto se ve
//      con '•' salvo la última letra (contraseñas Wi-Fi).
//    * modo IP:  solo números y '.'.
//  EXE acepta, AC cancela, DEL borra, ► confirma la letra (para repetirla).
//  No dibuja: quien lo usa pinta text() y help().
// =============================================================================
#pragma once
#include <Arduino.h>
#include "Keyboard.h"

class T9Input {
 public:
  enum class Mode : uint8_t { T9, Pass, Ip };
  enum class Result : uint8_t { Editing, Ok, Cancel };

  void begin(const String& text, Mode mode, uint8_t maxLen);
  Result key(const KeyEvent& ev);
  bool tick(uint32_t nowMs);          // true si hay que repintar (letra confirmada)

  const String& value() const { return text_; }
  String shown() const;               // lo que se ve (con '•' y cursor '_')
  const char* help() const;

 private:
  static const char* lettersFor(Key k);

  String text_;
  Mode mode_ = Mode::T9;
  uint8_t max_ = 16;
  Key last_ = Key::None;
  uint32_t t_ = 0;
  uint8_t i_ = 0;
  bool pending_ = false;              // la última letra aún puede cambiar
};
