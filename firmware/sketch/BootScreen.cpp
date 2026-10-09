// =============================================================================
//  BootScreen.cpp
// =============================================================================
#include "BootScreen.h"
#include "config.h"

namespace {
  // Medidas del simulador (draw_boot) a escala 1:2
  constexpr int16_t X = 75, W = 170;
  constexpr int16_t CHECK_Y = 112, CHECK_STEP = 15;
  constexpr int16_t BAR_Y = 200, BAR_H = 4;
}

void BootScreen::begin() {
  gfx_.clear();
  gfx_.text(0, 45, FW_NAME, 3, Theme::TEXT, Theme::BG, Align::Center, Display::W, true);
  gfx_.text(0, 79, "v" FW_VERSION_STR "  ·  C++ nativo + MicroPython", 1, Theme::MUTED, Theme::BG,
            Align::Center, Display::W);
  gfx_.hLine(X, 100, W, Theme::ACCENT);
  drawBar(0);
}

void BootScreen::check(const char* what, const char* result, uint16_t color) {
  const int16_t y = CHECK_Y + done_ * CHECK_STEP;
  gfx_.text(X, y, what, 1, Theme::TEXT, Theme::BG);
  gfx_.text(X, y, result, 1, color, Theme::BG, Align::Right, W, true);
  Serial.printf("[boot] %-15s %s\n", what, result);
  drawBar(++done_);
}

void BootScreen::finish(uint32_t holdMs) {
  drawBar(total_);
  delay(holdMs);
}

void BootScreen::drawBar(uint8_t done) {
  int16_t w = total_ ? (int16_t)((int32_t)W * min(done, total_) / total_) : W;
  gfx_.fillRoundRect(X, BAR_Y, W, BAR_H, 2, Theme::PANEL);
  if (w > 0) gfx_.fillRoundRect(X, BAR_Y, w, BAR_H, 2, Theme::ACCENT);
}
