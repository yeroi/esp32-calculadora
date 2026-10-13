// =============================================================================
//  CalcApp.h  —  Calculadora científica nativa (C++)
// -----------------------------------------------------------------------------
//  Igual que CalcApp del simulador:
//    * La expresión es una lista de tokens ("sin(", "π", "2"...): DEL borra un
//      token entero y el cursor salta de token en token.
//    * EXE evalúa (CalcEngine), guarda en el historial y en Ans. Empezar por un
//      operador tras un resultado continúa desde Ans (5 EXE + 3 -> Ans+3).
//    * ▲/▼ recuperan operaciones anteriores; AC limpia (dos veces: historial).
//    * SHIFT+AC cambia DEG/RAD.
// =============================================================================
#pragma once
#include <vector>
#include "App.h"

class CalcApp : public App {
 public:
  explicit CalcApp(AppManager& m) : App(m) {}

  const char* title() const override { return "Calculadora"; }
  bool showsAngleMode() const override { return true; }   // DEG/RAD en la barra

  void draw() override;
  void onKey(const KeyEvent& ev) override;
  void onTick(uint32_t nowMs) override;

 private:
  struct Entry {
    std::vector<const char*> toks;
    String result;
    bool error;
  };

  void insert(const char* tok);
  void run();
  String joined(size_t upto) const;
  void drawInput();
  void drawCursor(bool on);

  std::vector<const char*> toks_;
  size_t cur_ = 0;
  std::vector<Entry> history_;
  double ans_ = 0;
  int recall_ = -1;
  uint32_t blinkT_ = 0;
  bool blinkOn_ = true;
  int16_t cursorX_ = -1;                 // dónde se pintó el cursor
};
