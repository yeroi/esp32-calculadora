// =============================================================================
//  PlaceholderApp.h  —  Pantalla provisional para modos aún no implementados
// =============================================================================
#pragma once
#include "App.h"

class PlaceholderApp : public App {
 public:
  PlaceholderApp(AppManager& m, const char* title, const char* line1, const char* line2,
                 const char* line3 = "")
      : App(m), title_(title), l1_(line1), l2_(line2), l3_(line3) {}

  const char* title() const override { return title_; }
  void draw() override {
    gfx().fillRoundRect(24, 66, Display::W - 48, 96, 8, Theme::PANEL);
    gfx().text(24, 82, l1_, 2, Theme::TEXT, Theme::PANEL, Align::Center, Display::W - 48);
    gfx().text(24, 112, l2_, 1, Theme::MUTED, Theme::PANEL, Align::Center, Display::W - 48);
    gfx().text(24, 128, l3_, 1, Theme::MUTED, Theme::PANEL, Align::Center, Display::W - 48);
    gfx().footer("MENU para volver");
  }
  void onKey(const KeyEvent&) override {}

 private:
  const char* title_;
  const char* l1_;
  const char* l2_;
  const char* l3_;
};
