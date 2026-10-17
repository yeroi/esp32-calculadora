// =============================================================================
//  Buzzer.h  —  Sonido (zumbador piezo con LEDC, o el altavoz del PC)
// -----------------------------------------------------------------------------
//  Los tonos se reproducen EN ORDEN (una melodía son varios tone() seguidos).
//  En modo PC cada tono es una trama TONE y suena en el ordenador.
// =============================================================================
#pragma once
#include <Arduino.h>

class Buzzer {
 public:
  void begin();
  void tone(uint16_t hz, uint16_t ms);  // hz = 0 -> silencio de 'ms'
  void stop();                          // corta lo que esté sonando
  void click();                         // pulsación de tecla
  void alert();                         // aparece un diálogo
  void chime();                         // fin del arranque

  bool enabled = true;                  // sonido general
  bool keyClick = true;                 // "clic" al pulsar teclas
};

extern Buzzer buzzer;
