// =============================================================================
//  Display.cpp
// =============================================================================
#include "Display.h"
#include <SPI.h>
#include "config.h"

Display::Display() : tft_(PIN_TFT_CS, PIN_TFT_DC, PIN_TFT_RST) {}

bool Display::begin() {
  SPI.begin(PIN_SPI_SCK, PIN_SPI_MISO, PIN_SPI_MOSI);
  tft_.begin(TFT_SPI_HZ);
  tft_.setRotation(1);          // horizontal: 320 x 240
  tft_.cp437(true);             // tabla CP437 correcta (acentos, símbolos)
  tft_.setTextWrap(false);
  clear();
  return true;                  // el ILI9341 no confirma; asumimos OK
}

// ---- Primitivas -------------------------------------------------------------
void Display::clear(uint16_t c) { tft_.fillScreen(c); }
void Display::clearBody(uint16_t c) { tft_.fillRect(0, BODY_Y, W, BODY_H, c); }
void Display::fillRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t c) { tft_.fillRect(x, y, w, h, c); }
void Display::drawRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t c) { tft_.drawRect(x, y, w, h, c); }
void Display::fillRoundRect(int16_t x, int16_t y, int16_t w, int16_t h, int16_t r, uint16_t c) { tft_.fillRoundRect(x, y, w, h, r, c); }
void Display::drawRoundRect(int16_t x, int16_t y, int16_t w, int16_t h, int16_t r, uint16_t c) { tft_.drawRoundRect(x, y, w, h, r, c); }
void Display::fillTriangle(int16_t x0, int16_t y0, int16_t x1, int16_t y1, int16_t x2, int16_t y2, uint16_t c) {
  tft_.fillTriangle(x0, y0, x1, y1, x2, y2, c);
}
void Display::hLine(int16_t x, int16_t y, int16_t w, uint16_t c) { tft_.drawFastHLine(x, y, w, c); }
void Display::vLine(int16_t x, int16_t y, int16_t h, uint16_t c) { tft_.drawFastVLine(x, y, h, c); }

void Display::pushPixels(int16_t x, int16_t y, int16_t w, int16_t h, const uint16_t* px) {
  // Recorte: solo se admiten bloques que caben en horizontal tras recortar
  // filas; para el recorte horizontal se dibuja fila a fila.
  if (w <= 0 || h <= 0 || x >= W || y >= H || x + w <= 0 || y + h <= 0) return;
  int16_t x0 = max<int16_t>(x, 0), x1 = min<int16_t>(x + w, W);
  int16_t y0 = max<int16_t>(y, 0), y1 = min<int16_t>(y + h, H);
  tft_.startWrite();
  if (x0 == x && x1 == x + w) {                       // sin recorte horizontal
    tft_.setAddrWindow(x0, y0, w, y1 - y0);
    tft_.writePixels(const_cast<uint16_t*>(px + (y0 - y) * w), (uint32_t)w * (y1 - y0));
  } else {
    for (int16_t row = y0; row < y1; ++row) {
      tft_.setAddrWindow(x0, row, x1 - x0, 1);
      tft_.writePixels(const_cast<uint16_t*>(px + (row - y) * w + (x0 - x)), x1 - x0);
    }
  }
  tft_.endWrite();
}

// ---- UTF-8 -> CP437 --------------------------------------------------------
uint16_t Display::decodeUtf8(const char*& p) {
  uint8_t c = static_cast<uint8_t>(*p++);
  if (c < 0x80) return c;
  if ((c & 0xE0) == 0xC0 && *p) {                         // 2 bytes
    return ((c & 0x1F) << 6) | (static_cast<uint8_t>(*p++) & 0x3F);
  }
  if ((c & 0xF0) == 0xE0 && p[0] && p[1]) {               // 3 bytes
    uint16_t cp = ((c & 0x0F) << 12) | ((static_cast<uint8_t>(p[0]) & 0x3F) << 6) |
                  (static_cast<uint8_t>(p[1]) & 0x3F);
    p += 2;
    return cp;
  }
  if ((c & 0xF8) == 0xF0) {                               // 4 bytes (emoji...): se salta
    for (int i = 0; i < 3 && *p; ++i) ++p;
  }
  return '?';
}

uint8_t Display::toCp437(uint16_t cp) {
  if (cp < 0x80) return static_cast<uint8_t>(cp);
  switch (cp) {
    // Español y latinos frecuentes
    case 0x00E1: return 0xA0;  // á
    case 0x00E9: return 0x82;  // é
    case 0x00ED: return 0xA1;  // í
    case 0x00F3: return 0xA2;  // ó
    case 0x00FA: return 0xA3;  // ú
    case 0x00FC: return 0x81;  // ü
    case 0x00F1: return 0xA4;  // ñ
    case 0x00D1: return 0xA5;  // Ñ
    case 0x00C9: return 0x90;  // É
    case 0x00DC: return 0x9A;  // Ü
    case 0x00C1: return 'A';   // Á (CP437 no la tiene)
    case 0x00CD: return 'I';   // Í
    case 0x00D3: return 'O';   // Ó
    case 0x00DA: return 'U';   // Ú
    case 0x00E0: return 0x85;  // à
    case 0x00E8: return 0x8A;  // è
    case 0x00F2: return 0x95;  // ò
    case 0x00E7: return 0x87;  // ç
    case 0x00C7: return 0x80;  // Ç
    case 0x00BF: return 0xA8;  // ¿
    case 0x00A1: return 0xAD;  // ¡
    case 0x00BA: return 0xA7;  // º
    case 0x00AA: return 0xA6;  // ª
    // Matemáticas
    case 0x00B0: return 0xF8;  // °
    case 0x00B2: return 0xFD;  // ²
    case 0x00B7: return 0xFA;  // ·
    case 0x00F7: return 0xF6;  // ÷
    case 0x00B1: return 0xF1;  // ±
    case 0x03C0: return 0xE3;  // π
    case 0x03A3: return 0xE4;  // Σ
    case 0x221A: return 0xFB;  // √
    case 0x221E: return 0xEC;  // ∞
    case 0x2248: return 0xF7;  // ≈
    case 0x2264: return 0xF3;  // ≤
    case 0x2265: return 0xF2;  // ≥
    // Flechas y comillas
    case 0x00BB: return 0xAF;  // »
    case 0x00AB: return 0xAE;  // «
    case 0x203A: return 0xAF;  // › (se ve como »)
    case 0x2039: return 0xAE;  // ‹
    case 0x2191: return 0x18;  // ↑
    case 0x2193: return 0x19;  // ↓
    case 0x2192: return 0x1A;  // →
    case 0x2190: return 0x1B;  // ←
    case 0x25B2: return 0x1E;  // ▲
    case 0x25BC: return 0x1F;  // ▼
    case 0x25BA: return 0x10;  // ►
    case 0x25B6: return 0x10;  // ▶
    case 0x25C4: return 0x11;  // ◄
    case 0x25C0: return 0x11;  // ◀
    // Cajas (árbol de carpetas en la consola)
    case 0x2500: return 0xC4;  // ─
    case 0x2502: return 0xB3;  // │
    case 0x251C: return 0xC3;  // ├
    case 0x2514: return 0xC0;  // └
    case 0x2588: return 0xDB;  // █
    case 0x25A0: return 0xFE;  // ■
    case 0x2022: return 0x07;  // •
    default:     return '?';
  }
}

// Glifos propios 5x8 (mismo formato que la fuente "glcdfont" de Adafruit:
// 5 columnas, bit 0 = fila superior). Solo para lo que CP437 no tiene.
const uint8_t* Display::customGlyph(uint16_t cp) {
  static const uint8_t TIMES[5]  = {0x22, 0x14, 0x08, 0x14, 0x22};  // ×
  static const uint8_t MINUS[5]  = {0x08, 0x08, 0x08, 0x08, 0x08};  // − (signo menos)
  static const uint8_t SUP_Y[5]  = {0x00, 0x03, 0x14, 0x0F, 0x00};  // ʸ (y volada)
  static const uint8_t ELLIP[5]  = {0x40, 0x00, 0x40, 0x00, 0x40};  // …
  static const uint8_t CHECK[5]  = {0x10, 0x20, 0x10, 0x08, 0x04};  // ✓
  switch (cp) {
    case 0x00D7: return TIMES;
    case 0x2212: return MINUS;
    case 0x02B8: return SUP_Y;
    case 0x2026: return ELLIP;
    case 0x2713: return CHECK;
    default:     return nullptr;
  }
}

size_t Display::utf8Length(const char* s) {
  size_t n = 0;
  while (*s) { decodeUtf8(s); ++n; }
  return n;
}

int16_t Display::textWidth(const char* s, uint8_t size) {
  return static_cast<int16_t>(utf8Length(s)) * charW(size);
}

void Display::drawGlyph(int16_t x, int16_t y, uint16_t cp, uint8_t size,
                        uint16_t fg, uint16_t bg, bool bold) {
  const uint8_t* g = customGlyph(cp);
  if (!g) {
    uint8_t c = toCp437(cp);
    tft_.drawChar(x, y, c, fg, bg, size);                // fondo opaco
    if (bold) tft_.drawChar(x + size, y, c, fg, fg, size);  // 2ª pasada transparente
    return;
  }
  // Glifo propio: fondo de la celda 6x8 y luego los píxeles encendidos
  tft_.fillRect(x, y, 6 * size, 8 * size, bg);
  for (uint8_t col = 0; col < 5; ++col) {
    uint8_t bits = g[col];
    for (uint8_t row = 0; row < 8; ++row, bits >>= 1) {
      if (!(bits & 1)) continue;
      tft_.fillRect(x + col * size, y + row * size, size * (bold ? 2 : 1), size, fg);
    }
  }
}

void Display::text(int16_t x, int16_t y, const char* s, uint8_t size,
                   uint16_t fg, uint16_t bg, Align align, int16_t boxW,
                   bool bold, int16_t maxW) {
  if (!s) return;
  size_t len = utf8Length(s);
  if (maxW > 0) {
    size_t fit = maxW / charW(size);
    if (len > fit) len = fit;
  }
  const int16_t w = static_cast<int16_t>(len) * charW(size);
  if (boxW > 0) {
    if (align == Align::Center) x += (boxW - w) / 2;
    else if (align == Align::Right) x += boxW - w;
  }
  // Ojo: no envolver en startWrite()/endWrite(): drawChar y fillRect ya abren
  // su propia transacción SPI y en el ESP32 el bloqueo del bus no es recursivo.
  for (size_t i = 0; i < len && *s; ++i) {
    uint16_t cp = decodeUtf8(s);
    drawGlyph(x, y, cp, size, fg, bg, bold);
    x += charW(size);
  }
}

void Display::footer(const char* utf8) {
  fillRect(0, FOOTER_Y - 2, W, H - FOOTER_Y + 2, Theme::BG);
  text(0, FOOTER_Y + 1, utf8, 1, Theme::MUTED, Theme::BG, Align::Center, W, false, W);
}
