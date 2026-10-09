// =============================================================================
//  DiagApp.cpp
// =============================================================================
#include "DiagApp.h"

namespace {
  // Medidas del simulador a escala 1:2
  constexpr int16_t INFO_X = 8, INFO_Y = Display::BODY_Y + 5, LINE = 11;
  constexpr int16_t SEP_Y = 75, LAST_LBL_Y = 80, LAST_Y = 92;
  constexpr int16_t GRID_Y = 118, CELL_W = 35, CELL_H = 22, STEP_X = 38, STEP_Y = 25;
  constexpr int16_t BLOCK_X[2] = {8, 164};
}

void DiagApp::draw() {
  char buf[64];
  snprintf(buf, sizeof buf, "Chip: %s rev %d · %lu MHz · %d núcleos", ESP.getChipModel(),
           (int)ESP.getChipRevision(), (unsigned long)getCpuFrequencyMhz(), (int)ESP.getChipCores());
  gfx().text(INFO_X, INFO_Y, buf, 1, Theme::TEXT, Theme::BG);

  uint32_t psram = ESP.getPsramSize();
  snprintf(buf, sizeof buf, "Flash: %lu MB · PSRAM: %s", (unsigned long)(ESP.getFlashChipSize() >> 20),
           psram ? "sí" : "no (WROOM)");
  gfx().text(INFO_X, INFO_Y + LINE, buf, 1, psram ? Theme::TEXT : Theme::WARN, Theme::BG);

  if (sd().mounted()) {
    snprintf(buf, sizeof buf, "MicroSD: %s · %lu MB", sd().cardTypeName(),
             (unsigned long)(sd().cardSizeBytes() >> 20));
    gfx().text(INFO_X, INFO_Y + 2 * LINE, buf, 1, Theme::OK, Theme::BG);
  } else {
    gfx().text(INFO_X, INFO_Y + 2 * LINE, "MicroSD: no detectada", 1, Theme::ERR, Theme::BG);
  }
  drawMemory();
  nextMemAt_ = millis() + 1000;

  gfx().hLine(INFO_X, SEP_Y, Display::W - 16, Theme::PANEL);
  gfx().text(INFO_X, LAST_LBL_Y, "Última tecla:", 1, Theme::MUTED, Theme::BG);
  drawLastKey(lastIdx_ >= 0 ? &last_ : nullptr);

  for (uint8_t i = 0; i < KEY_COUNT; ++i) drawCell(i, i == lastIdx_);
  gfx().footer("MENU vuelve · SHIFT aparece en la barra superior");
}

void DiagApp::drawMemory() {
  char buf[64];
  snprintf(buf, sizeof buf, "Heap libre: %lu KB · bloque máx: %lu KB   ",
           (unsigned long)(ESP.getFreeHeap() / 1024), (unsigned long)(ESP.getMaxAllocHeap() / 1024));
  gfx().text(INFO_X, INFO_Y + 3 * LINE, buf, 1, Theme::TEXT, Theme::BG);
}

void DiagApp::drawCell(uint8_t idx, bool hi) {
  // idx = posición lógica 0..31 (mismo orden que el enum Key, sin None)
  uint8_t block = idx / 16, r = (idx % 16) / 4, c = idx % 4;
  int16_t x = BLOCK_X[block] + c * STEP_X;
  int16_t y = GRID_Y + r * STEP_Y;
  uint16_t bg = hi ? Theme::ACCENT : Theme::PANEL;
  gfx().fillRoundRect(x, y, CELL_W, CELL_H, 4, bg);
  Key k = static_cast<Key>(idx + 1);
  gfx().text(x, y + 7, keyLabel(k), 1, Theme::TEXT, bg, Align::Center, CELL_W, true);
}

void DiagApp::drawLastKey(const KeyEvent* ev) {
  gfx().fillRect(INFO_X, LAST_Y, Display::W - 16, 16, Theme::BG);
  if (!ev) {
    gfx().text(INFO_X, LAST_Y, "(pulsa cualquier tecla)", 2, Theme::MUTED, Theme::BG);
    return;
  }
  char buf[48];
  const char* sh = keyShiftLabel(ev->key);
  if (ev->shift && *sh) snprintf(buf, sizeof buf, "SHIFT+%s = %s   #%lu", keyLabel(ev->key), sh,
                                 (unsigned long)presses_);
  else snprintf(buf, sizeof buf, "%s%s%s   #%lu", ev->shift ? "SHIFT+" : "", keyLabel(ev->key),
                ev->repeat ? " (rep)" : "", (unsigned long)presses_);
  gfx().text(INFO_X, LAST_Y, buf, 2, ev->shift ? Theme::SHIFT : Theme::TEXT, Theme::BG,
             Align::Left, 0, false, Display::W - 16);
}

void DiagApp::onKey(const KeyEvent& ev) {
  ++presses_;
  int idx = static_cast<int>(ev.key) - 1;
  if (idx < 0 || idx >= KEY_COUNT) return;
  if (lastIdx_ >= 0 && lastIdx_ != idx) drawCell(lastIdx_, false);
  drawCell(idx, true);
  lastIdx_ = idx;
  last_ = ev;
  drawLastKey(&ev);
  Serial.printf("[kbd] %s%s\n", ev.shift ? "SHIFT+" : "", keyName(ev.key));
}

void DiagApp::onTick(uint32_t now) {
  if ((int32_t)(now - nextMemAt_) >= 0 && canDraw()) {
    drawMemory();
    nextMemAt_ = now + 1000;
  }
}
