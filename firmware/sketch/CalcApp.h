// =============================================================================
//  CalcApp.h  —  Calculadora científica nativa (C++)
// -----------------------------------------------------------------------------
//  PASO 3: solo el "esqueleto" de la app, para que el menú, la barra de estado
//  (DEG/RAD) y las teclas globales ya funcionen igual que en el simulador.
//  PASO 4: aquí irá el analizador por descenso recursivo traducido de
//  scicalc_sim.py (tokens, historial, Ans, errores, formato de 10 cifras).
// =============================================================================
#pragma once
#include "App.h"

class CalcApp : public App {
 public:
  explicit CalcApp(AppManager& m) : App(m) {}

  const char* title() const override { return "Calculadora"; }
  bool showsAngleMode() const override { return true; }   // DEG/RAD en la barra

  void draw() override {
    gfx().text(0, 82, "Escribe una operación y pulsa EXE", 1, Theme::MUTED, Theme::BG,
               Align::Center, Display::W);
    gfx().text(0, 98, "(el motor de cálculo llega en el Paso 4)", 1, Theme::MUTED, Theme::BG,
               Align::Center, Display::W);
    gfx().hLine(10, 161, Display::W - 20, Theme::PANEL);
    gfx().footer("SHIFT+AC DEG/RAD  ↑ recuperar  DEL borra  AC limpia");
  }

  void onKey(const KeyEvent& ev) override {
    // SHIFT+AC cambia DEG/RAD; la barra de estado se actualiza sola
    if (ev.shift && ev.key == Key::AC) st().degrees = !st().degrees;
  }
};
