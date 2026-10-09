// =============================================================================
//  DiagApp.h  —  Diagnóstico: chip, flash, PSRAM, memoria, SD y prueba de teclas
// -----------------------------------------------------------------------------
//  La rejilla muestra las 32 teclas en el mismo orden que el enum Key;
//  la última pulsada se resalta. El heap se refresca cada segundo.
//  Ojo: MENU no llega aquí (es global y vuelve al menú).
// =============================================================================
#pragma once
#include "App.h"

class DiagApp : public App {
 public:
  explicit DiagApp(AppManager& m) : App(m) {}

  const char* title() const override { return "Diagnóstico"; }
  void onEnter() override { lastIdx_ = -1; presses_ = 0; }
  void draw() override;
  void onKey(const KeyEvent& ev) override;
  void onTick(uint32_t now) override;

 private:
  void drawMemory();
  void drawCell(uint8_t idx, bool highlight);
  void drawLastKey(const KeyEvent* ev);

  int lastIdx_ = -1;
  KeyEvent last_{};
  uint32_t nextMemAt_ = 0;
  uint32_t presses_ = 0;
};
