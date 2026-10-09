// =============================================================================
//  BootScreen.h  —  Pantalla de arranque con autodiagnóstico
// -----------------------------------------------------------------------------
//        ESP32 SciCalc
//   v0.3 · C++ nativo + MicroPython
//   ───────────────────────────────
//   Pantalla ..................... OK
//   Teclado ...................... OK
//   MicroSD ...................... OK
//   PSRAM ................ no (WROOM)
//   Sandbox Python ......... (Paso 5)
//   [██████████████░░░░░░░░░░░░░░░]
// =============================================================================
#pragma once
#include "Display.h"

class BootScreen {
 public:
  BootScreen(Display& d, uint8_t totalChecks) : gfx_(d), total_(totalChecks) {}

  void begin();                                   // título y barra vacía
  // Añade una línea de resultado y avanza la barra de progreso
  void check(const char* what, const char* result, uint16_t color);
  void finish(uint32_t holdMs = 600);             // barra al 100 % y pausa

 private:
  void drawBar(uint8_t done);

  Display& gfx_;
  uint8_t total_;
  uint8_t done_ = 0;
};
