// =============================================================================
//  Display.cpp
// =============================================================================
#include "Display.h"
#include <SPI.h>
#include "config.h"

#if SCICALC_REMOTE
#include "RemoteLink.h"

// =============================================================================
//  Motor PC: cada primitiva es una trama para pc/scicalc_pantalla.py
// =============================================================================
namespace {
inline void put16(uint8_t*& p, int32_t v) { *p++ = v & 0xFF; *p++ = (v >> 8) & 0xFF; }
constexpr int16_t CUSTOM_BASE = 256;     // ids de los glifos propios: 256..
}

Display::Display() { glyphCanvas_.cp437(true); }

bool Display::begin() {
  scratch_ = static_cast<uint8_t*>(malloc(Proto::MAX_PAYLOAD));
  return scratch_ != nullptr;
}

bool Display::takeFullRedraw() {
  uint32_t s = remoteLink.session();
  if (s == redrawSession_) return false;
  redrawSession_ = s;
  return true;
}

void Display::sendShape(uint8_t type, const int16_t* v, uint8_t nv, uint16_t c) {
  uint8_t b[16];
  uint8_t* p = b;
  for (uint8_t i = 0; i < nv; ++i) put16(p, v[i]);
  put16(p, c);
  remoteLink.send(type, b, p - b);
}

void Display::clear(uint16_t c) { fillRect(0, 0, W, H, c); }
void Display::clearBody(uint16_t c) { fillRect(0, BODY_Y, W, BODY_H, c); }
void Display::fillRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t c) {
  if (w <= 0 || h <= 0) return;
  const int16_t v[] = {x, y, w, h};
  sendShape(Proto::FILL, v, 4, c);
}
void Display::drawRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t c) {
  if (w <= 0 || h <= 0) return;
  const int16_t v[] = {x, y, w, h};
  sendShape(Proto::RECT, v, 4, c);
}
void Display::fillRoundRect(int16_t x, int16_t y, int16_t w, int16_t h, int16_t r, uint16_t c) {
  if (w <= 0 || h <= 0) return;
  const int16_t v[] = {x, y, w, h, r};
  sendShape(Proto::FILL_RR, v, 5, c);
}
void Display::drawRoundRect(int16_t x, int16_t y, int16_t w, int16_t h, int16_t r, uint16_t c) {
  if (w <= 0 || h <= 0) return;
  const int16_t v[] = {x, y, w, h, r};
  sendShape(Proto::RECT_RR, v, 5, c);
}
void Display::fillTriangle(int16_t x0, int16_t y0, int16_t x1, int16_t y1, int16_t x2, int16_t y2, uint16_t c) {
  const int16_t v[] = {x0, y0, x1, y1, x2, y2};
  sendShape(Proto::TRI, v, 6, c);
}
void Display::hLine(int16_t x, int16_t y, int16_t w, uint16_t c) { fillRect(x, y, w, 1, c); }
void Display::vLine(int16_t x, int16_t y, int16_t h, uint16_t c) { fillRect(x, y, 1, h, c); }

void Display::pushPixels(int16_t x, int16_t y, int16_t w, int16_t h, const uint16_t* px) {
  if (w <= 0 || h <= 0 || x >= W || y >= H || x + w <= 0 || y + h <= 0) return;
  int16_t x0 = max<int16_t>(x, 0), x1 = min<int16_t>(x + w, W);
  int16_t y0 = max<int16_t>(y, 0), y1 = min<int16_t>(y + h, H);
  sendPixelRows(x0, y0, x1 - x0, y1 - y0, px + (y0 - y) * w + (x0 - x), w);
}

// Trocea el bloque en tramas de <= 4 KB. Cada trozo va comprimido por
// tramos (RLE) si así ocupa menos: los fondos e iconos lisos vuelan; las
// fotos van en crudo (~90 KB/s a 921600 baudios).
void Display::sendPixelRows(int16_t x, int16_t y, int16_t w, int16_t h, const uint16_t* px,
                            int16_t stride) {
  if (!scratch_) return;
  const size_t room = Proto::MAX_PAYLOAD - 8;
  int16_t rowsPer = room / (w * 2);
  if (rowsPer < 1) rowsPer = 1;
  for (int16_t r0 = 0; r0 < h; r0 += rowsPer) {
    int16_t rows = min<int16_t>(rowsPer, h - r0);
    size_t raw = (size_t)w * rows * 2;
    uint8_t* p = scratch_;
    put16(p, x); put16(p, y + r0); put16(p, w); put16(p, rows);

    // 1) Intento RLE: {n, color}; se abandona si ya no compensa
    uint8_t* q = p;
    bool rle = true;
    uint16_t cur = 0;
    uint16_t run = 0;
    for (int16_t r = 0; r < rows && rle; ++r) {
      const uint16_t* line = px + (size_t)(r0 + r) * stride;
      for (int16_t i = 0; i < w; ++i) {
        uint16_t c = line[i];
        if (run && c == cur && run < 255) { ++run; continue; }
        if (run) {
          if ((size_t)(q - p) + 3 > raw - 3) { rle = false; break; }
          *q++ = run; put16(q, cur);
        }
        cur = c; run = 1;
      }
    }
    if (rle && run) {
      if ((size_t)(q - p) + 3 >= raw) rle = false;
      else { *q++ = run; put16(q, cur); }
    }
    if (rle) {
      remoteLink.send(Proto::PIXELS_RLE, scratch_, q - scratch_);
      continue;
    }
    // 2) En crudo
    q = p;
    for (int16_t r = 0; r < rows; ++r) {
      const uint16_t* line = px + (size_t)(r0 + r) * stride;
      for (int16_t i = 0; i < w; ++i) put16(q, line[i]);
    }
    remoteLink.send(Proto::PIXELS, scratch_, q - scratch_);
  }
}

// Devuelve el id del glifo y, si el PC aún no lo tiene, se lo manda
uint16_t Display::glyphId(uint16_t cp) {
  uint32_t s = remoteLink.session();
  if (s != session_) {                     // PC nuevo: no tiene ningún glifo
    session_ = s;
    memset(glyphSent_, 0, sizeof glyphSent_);
  }
  uint8_t cols[5];
  uint16_t id;
  const uint8_t* g = customGlyph(cp);
  if (g) {
    static const uint16_t CUSTOM_CP[] = {0x00D7, 0x2212, 0x02B8, 0x2026, 0x2713};
    id = CUSTOM_BASE;
    for (uint16_t i = 0; i < sizeof CUSTOM_CP / sizeof CUSTOM_CP[0]; ++i)
      if (CUSTOM_CP[i] == cp) id = CUSTOM_BASE + i;
  } else {
    id = toCp437(cp);
  }
  if (glyphSent_[id >> 5] & (1UL << (id & 31))) return id;

  if (g) {
    memcpy(cols, g, 5);
  } else {
    // Se dibuja el carácter de la fuente de Adafruit en un lienzo de 6x8 y se
    // leen sus columnas: el PC usa exactamente la misma fuente.
    glyphCanvas_.fillScreen(0);
    glyphCanvas_.drawChar(0, 0, (unsigned char)id, 1, 0, 1);
    for (uint8_t c = 0; c < 5; ++c) {
      uint8_t bits = 0;
      for (uint8_t r = 0; r < 8; ++r)
        if (glyphCanvas_.getPixel(c, r)) bits |= 1 << r;
      cols[c] = bits;
    }
  }
  uint8_t b[7] = {(uint8_t)(id & 0xFF), (uint8_t)(id >> 8), cols[0], cols[1], cols[2], cols[3], cols[4]};
  remoteLink.send(Proto::GLYPH, b, sizeof b);
  glyphSent_[id >> 5] |= 1UL << (id & 31);
  return id;
}

#else  // ---------------- Motor TFT (ILI9341) ----------------------------

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

bool Display::takeFullRedraw() { return false; }

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

#endif  // SCICALC_REMOTE

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

#if SCICALC_REMOTE
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
  // Una trama TEXT por cada 100 caracteres como mucho
  constexpr size_t CHUNK = 100;
  uint16_t ids[CHUNK];
  size_t i = 0;
  while (i < len && *s) {
    size_t n = 0;
    while (n < CHUNK && i < len && *s) { ids[n++] = glyphId(decodeUtf8(s)); ++i; }
    uint8_t b[11 + 2 * CHUNK];
    uint8_t* p = b;
    put16(p, x); put16(p, y);
    *p++ = size;
    put16(p, fg); put16(p, bg);
    *p++ = bold ? 1 : 0;
    *p++ = (uint8_t)n;
    for (size_t k = 0; k < n; ++k) put16(p, ids[k]);
    remoteLink.send(Proto::TEXT, b, p - b);
    x += (int16_t)n * charW(size);
  }
}

#else
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

#endif

void Display::footer(const char* utf8) {
  fillRect(0, FOOTER_Y - 2, W, H - FOOTER_Y + 2, Theme::BG);
  text(0, FOOTER_Y + 1, utf8, 1, Theme::MUTED, Theme::BG, Align::Center, W, false, W);
}
