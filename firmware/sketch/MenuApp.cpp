// =============================================================================
//  MenuApp.cpp
// =============================================================================
#include "MenuApp.h"

namespace {
  // Medidas del simulador a escala 1:2 (el simulador dibuja a 640x480)
  constexpr int16_t ITEM_X = 10, ITEM_W = Display::W - 20;
  constexpr int16_t ITEM_Y0 = Display::BODY_Y + 5;
  constexpr int16_t ITEM_H = 29, ITEM_STEP = 33;
}

void MenuApp::addItem(const char* label, const char* hint, App* target) {
  if (count_ < MAX_ITEMS) items_[count_++] = {label, hint, target};
}

void MenuApp::drawItem(uint8_t i) {
  const bool selected = (i == sel_);
  const uint16_t bg = selected ? Theme::ACCENT : Theme::PANEL;
  const int16_t y = ITEM_Y0 + i * ITEM_STEP;

  gfx().fillRoundRect(ITEM_X, y, ITEM_W, ITEM_H, 6, bg);

  // "Atajo" numérico a la izquierda
  const uint16_t badge = selected ? Theme::BG : Theme::ACCENT;
  char num[2] = {static_cast<char>('1' + i), 0};
  gfx().fillRoundRect(ITEM_X + 6, y + 5, 19, 19, 4, badge);
  gfx().text(ITEM_X + 6, y + 7, num, 2, Theme::TEXT, badge, Align::Center, 19);

  gfx().text(ITEM_X + 33, y + 7, items_[i].label, 2, Theme::TEXT, bg);
  gfx().text(ITEM_X, y + 11, items_[i].hint, 1, selected ? Theme::TEXT : Theme::MUTED, bg,
             Align::Right, ITEM_W - 10);
}

void MenuApp::draw() {
  for (uint8_t i = 0; i < count_; ++i) drawItem(i);
  char foot[64];
  snprintf(foot, sizeof foot, "▲▼ mover    EXE abrir    1-%u acceso directo", count_);
  gfx().footer(foot);
}

void MenuApp::onKey(const KeyEvent& ev) {
  if (!count_) return;
  switch (ev.key) {
    case Key::Up:
    case Key::Down: {
      uint8_t old = sel_;
      sel_ = (sel_ + count_ + (ev.key == Key::Up ? -1 : 1)) % count_;
      drawItem(old);          // solo se redibujan los 2 elementos que cambian
      drawItem(sel_);
      return;
    }
    case Key::Exe:
    case Key::Right:
      mgr().launch(items_[sel_].target);
      return;
    default:
      break;
  }
  char d = keyDigit(ev.key);
  if (d >= '1' && d < '1' + count_) {
    sel_ = d - '1';
    mgr().launch(items_[sel_].target);
  }
}
