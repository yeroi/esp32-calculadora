// =============================================================================
//  MenuApp.h  —  Menú principal (6 modos)
// -----------------------------------------------------------------------------
//  ▲/▼ para moverse, EXE o ► para abrir, o la tecla 1-6 para saltar
//  directamente a un modo (cambio de modo instantáneo).
// =============================================================================
#pragma once
#include "App.h"

class MenuApp : public App {
 public:
  static constexpr uint8_t MAX_ITEMS = 6;

  explicit MenuApp(AppManager& m) : App(m) {}

  void addItem(const char* label, const char* hint, App* target);
  const char* title() const override { return "Menú principal"; }
  void draw() override;
  void onKey(const KeyEvent& ev) override;

 private:
  struct Item { const char* label; const char* hint; App* target; };
  void drawItem(uint8_t i);

  Item items_[MAX_ITEMS] = {};
  uint8_t count_ = 0;
  uint8_t sel_ = 0;
};
