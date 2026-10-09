// =============================================================================
//  PyGfx.cpp
// =============================================================================
#include "PyGfx.h"
#include <PNGdec.h>
#include <math.h>
#include "PySandbox.h"
#if SCICALC_REMOTE
#include "RemoteLink.h"
#endif

PyGfx pyGfx;

namespace {
constexpr size_t   SPRITE_MAX_BYTES = 24 * 1024;     // más grande: se decodifica al dibujar
constexpr size_t   CACHE_MAX_BYTES = 48 * 1024;      // total de sprites decodificados
constexpr uint32_t FRAME_MS = 33;                    // ~30 fps como mucho

// ---- Lectura de PNG desde la SD (mismas funciones que ImageDecoder) -----------
Storage* g_sd = nullptr;
void* fOpen(const char* path, int32_t* size) {
  fs::File* f = new (std::nothrow) fs::File(g_sd->openRead(String(path)));
  if (!f) return nullptr;
  if (!*f) { delete f; return nullptr; }
  *size = (int32_t)f->size();
  return f;
}
void fClose(void* h) {
  fs::File* f = static_cast<fs::File*>(h);
  if (f) { f->close(); delete f; }
}
int32_t fRead(PNGFILE* p, uint8_t* b, int32_t n) {
  fs::File* f = static_cast<fs::File*>(p->fHandle);
  int32_t r = (int32_t)f->read(b, n);
  p->iPos = (int32_t)f->position();
  return r;
}
int32_t fSeek(PNGFILE* p, int32_t pos) {
  fs::File* f = static_cast<fs::File*>(p->fHandle);
  f->seek(pos);
  p->iPos = (int32_t)f->position();
  return p->iPos;
}

// Contexto de la decodificación en curso (PNGdec llama a una función libre)
struct Decode {
  PNG* png = nullptr;
  uint16_t* line = nullptr;      // una línea en RGB565
  uint8_t* lmask = nullptr;      // su máscara
  bool alpha = false;
  // a caché
  uint16_t* px = nullptr;
  uint8_t* mask = nullptr;
  // dibujo directo
  PyGfx* gfx = nullptr;
  int (*emit)(PNGDRAW* d) = nullptr;
};
Decode g_dec;

void lineAndMask(PNGDRAW* d) {
  g_dec.png->getLineAsRGB565(d, g_dec.line, PNG_RGB565_LITTLE_ENDIAN, 0);
  int mb = (d->iWidth + 7) / 8;
  if (g_dec.alpha) g_dec.png->getAlphaMask(d, g_dec.lmask, 128);
  else memset(g_dec.lmask, 0xFF, mb);
}

int toCache(PNGDRAW* d) {
  lineAndMask(d);
  int w = d->iWidth, mb = (w + 7) / 8;
  memcpy(g_dec.px + (size_t)d->y * w, g_dec.line, w * 2);
  memcpy(g_dec.mask + (size_t)d->y * mb, g_dec.lmask, mb);
  return 1;
}
int pngCb(PNGDRAW* d) { return g_dec.emit(d); }

inline bool maskBit(const uint8_t* m, int i) { return m[i >> 3] & (0x80 >> (i & 7)); }

// Estado del dibujo de un sprite grande (decodificado al vuelo)
struct BigDraw {
  PyGfx* self;
  float left, top, sx, sy;
  int w;
  bool flip;
  int16_t x0, x1, nextRow, endRow;    // filas de pantalla pendientes
} g_big;
}  // namespace

// =============================================================================
//  Tarea del script
// =============================================================================
bool PyGfx::begin() {
  if (active_) return true;
  if (!keys_) keys_ = xQueueCreate(32, sizeof(KeyEvent));
  q_ = new (std::nothrow) Op[QCAP];
  txt_ = (char*)malloc(TCAP);
  row_ = (uint16_t*)malloc(AREA_W * 2);
  if (!q_ || !txt_ || !row_ || !keys_) {
    delete[] q_; free(txt_); free(row_);
    q_ = nullptr; txt_ = nullptr; row_ = nullptr;
    return false;
  }
  head_ = tail_ = 0;
  txtUsed_ = 0;
  nextId_ = 0;
  lastShow_ = millis();
  clipX0_ = 0; clipY0_ = AREA_Y; clipX1_ = AREA_W; clipY1_ = AREA_Y + AREA_H;
  cleared_ = false;
  if (keys_) xQueueReset(keys_);
  memset(heldUntil_, 0, sizeof heldUntil_);
  active_ = true;
  return true;
}

void PyGfx::push(const Op& op, const char* text, size_t n) {
  if (!active_) return;
  // Esperar sitio (la UI va vaciando la cola). Si hay que parar, se descarta.
  for (;;) {
    if (pySandbox.stopping()) return;
    bool empty = head_ == tail_;
    if (empty) txtUsed_ = 0;                  // nadie usa ya el texto anterior
    bool qFull = (uint16_t)((head_ + 1) % QCAP) == tail_;
    bool tFull = text && txtUsed_ + n + 1 > TCAP;
    if (!qFull && !(tFull && !empty)) break;
    vTaskDelay(1);
  }
  Op o = op;
  if (text) {
    if (n + 1 > TCAP) n = TCAP - 1;
    memcpy(txt_ + txtUsed_, text, n);
    txt_[txtUsed_ + n] = 0;
    o.id = (o.kind == LOAD) ? o.id : txtUsed_;
    o.w = (o.kind == LOAD) ? (int16_t)txtUsed_ : (int16_t)n;
    txtUsed_ += n + 1;
  }
  q_[head_] = o;
  head_ = (head_ + 1) % QCAP;
}

int PyGfx::newSprite(const char* path) {
  Op o;
  o.kind = LOAD;
  o.id = nextId_++;
  push(o, path, strlen(path));
  return o.id;
}

int PyGfx::show() {
  if (!active_) return 0;
  while (head_ != tail_) {                    // hasta que la UI lo haya pintado
    if (pySandbox.stopping()) return 1;
    vTaskDelay(1);
  }
  uint32_t now = millis();
  if (now - lastShow_ < FRAME_MS) vTaskDelay(pdMS_TO_TICKS(FRAME_MS - (now - lastShow_)));
  lastShow_ = millis();
  pySandbox.kick();                           // un juego que pinta está vivo
  return pySandbox.stopping() ? 1 : 0;
}

bool PyGfx::popKey(Key& k, bool& shift) {
  KeyEvent ev;
  if (!keys_ || xQueueReceive(keys_, &ev, 0) != pdTRUE) return false;
  k = ev.key;
  shift = ev.shift;
  return true;
}

uint64_t PyGfx::held() {
  uint64_t bits = 0;
  uint32_t now = millis();
  for (uint8_t k = 1; k <= KEY_COUNT; ++k) {
    if ((int32_t)(heldUntil_[k] - now) > 0) bits |= 1ULL << k;
#if SCICALC_REMOTE
    if (remoteLink.isDown(static_cast<Key>(k))) bits |= 1ULL << k;
#endif
  }
  return bits;
}

// =============================================================================
//  UI
// =============================================================================
void PyGfx::onKey(const KeyEvent& ev) {
  if (!active_ || !keys_) return;
  uint8_t k = static_cast<uint8_t>(ev.key);
  if (k >= 1 && k <= KEY_COUNT) {
    // Con la matriz física solo hay pulsaciones: cuenta como mantenida hasta
    // la siguiente autorrepetición esperada
    heldUntil_[k] = millis() + (ev.repeat ? KB_REPEAT_RATE + 60 : KB_REPEAT_DELAY + 60);
  }
  if (!ev.repeat) xQueueSend(keys_, &ev, 0);
}

void PyGfx::end() {
  active_ = false;
  for (Sprite& s : sprites_) freeSprite(s);
  sprites_.clear();
  sprites_.shrink_to_fit();
  cacheBytes_ = 0;
  delete[] q_; q_ = nullptr;
  free(txt_); txt_ = nullptr;
  free(row_); row_ = nullptr;
  head_ = tail_ = 0;
  if (keys_) xQueueReset(keys_);
}

void PyGfx::drain(Display& d, Storage& sd, uint32_t budgetMs) {
  if (!active_) return;
  d_ = &d;
  sd_ = &sd;
  g_sd = &sd;
  if (!cleared_) {                            // fuera la consola: la zona es del juego
    cleared_ = true;
    d.fillRect(0, AREA_Y, AREA_W, AREA_H, 0);
  }
  uint32_t t0 = millis();
  while (tail_ != head_) {
    const Op& o = q_[tail_];
    switch (o.kind) {
      case CLEAR: fill(0, AREA_Y, AREA_W, AREA_H, o.c); break;
      case RECT:  fill(o.x, o.y + AREA_Y, o.w, o.h, o.c); break;
      case FRAME:
        fill(o.x, o.y + AREA_Y, o.w, 1, o.c);
        fill(o.x, o.y + AREA_Y + o.h - 1, o.w, 1, o.c);
        fill(o.x, o.y + AREA_Y, 1, o.h, o.c);
        fill(o.x + o.w - 1, o.y + AREA_Y, 1, o.h, o.c);
        break;
      case LINE:  line(o.x, o.y + AREA_Y, o.w, o.h + AREA_Y, o.c); break;
      case TEXT:  text(o, txt_ + o.id); break;
      case CLIP:
        if (o.w < 0) {
          clipX0_ = 0; clipY0_ = AREA_Y; clipX1_ = AREA_W; clipY1_ = AREA_Y + AREA_H;
        } else {
          clipX0_ = max<int16_t>(0, o.x);
          clipY0_ = max<int16_t>(AREA_Y, o.y + AREA_Y);
          clipX1_ = min<int16_t>(AREA_W, o.x + o.w);
          clipY1_ = min<int16_t>(AREA_Y + AREA_H, o.y + AREA_Y + o.h);
        }
        break;
      case LOAD:
        if (o.id >= sprites_.size()) sprites_.resize(o.id + 1);
        sprites_[o.id].path = String(txt_ + o.w);
        break;
      case SPRITE: drawSprite(o); break;
    }
    tail_ = (tail_ + 1) % QCAP;
    if (millis() - t0 > budgetMs) break;      // sigue en el próximo tic (teclas al día)
  }
}

// ---- Primitivas con recorte -------------------------------------------------------
void PyGfx::fill(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t c) {
  int16_t x0 = max(x, clipX0_), y0 = max(y, clipY0_);
  int16_t x1 = min<int16_t>(x + w, clipX1_), y1 = min<int16_t>(y + h, clipY1_);
  if (x1 > x0 && y1 > y0) d_->fillRect(x0, y0, x1 - x0, y1 - y0, c);
}

void PyGfx::line(int16_t x0, int16_t y0, int16_t x1, int16_t y1, uint16_t c) {
  if (y0 == y1) { fill(min(x0, x1), y0, abs(x1 - x0) + 1, 1, c); return; }
  if (x0 == x1) { fill(x0, min(y0, y1), 1, abs(y1 - y0) + 1, c); return; }
  int dx = abs(x1 - x0), sx = x0 < x1 ? 1 : -1;
  int dy = -abs(y1 - y0), sy = y0 < y1 ? 1 : -1;
  int err = dx + dy;
  for (int i = 0; i < 2000; ++i) {            // Bresenham (las diagonales son raras)
    fill(x0, y0, 1, 1, c);
    if (x0 == x1 && y0 == y1) break;
    int e2 = 2 * err;
    if (e2 >= dy) { err += dy; x0 += sx; }
    if (e2 <= dx) { err += dx; y0 += sy; }
  }
}

void PyGfx::text(const Op& o, const char* s) {
  uint8_t size = o.flags & 0x0F;
  if (size < 1) size = 1;
  bool hasBg = o.flags & 0x80;
  int16_t x = o.x, y = o.y + AREA_Y;
  const char* p = s;
  for (int n = 0; *p && n < 80; ++n) {
    uint16_t cp = Display::decodeUtf8(p);
    if (x >= clipX1_) break;
    if (hasBg) fill(x, y, 6 * size, 8 * size, o.bg);
    uint8_t cols[5];
    Display::glyphColumns(cp, cols);
    for (uint8_t c = 0; c < 5; ++c) {
      uint8_t bits = cols[c];
      for (uint8_t r = 0; r < 8;) {
        if (!(bits & (1 << r))) { ++r; continue; }
        uint8_t r0 = r;
        while (r < 8 && (bits & (1 << r))) ++r;      // tramo vertical de píxeles
        fill(x + c * size, y + r0 * size, size, (r - r0) * size, o.c);
      }
    }
    x += 6 * size;
  }
}

// ---- Sprites ------------------------------------------------------------------------
void PyGfx::freeSprite(Sprite& s) {
  if (s.px) {
    cacheBytes_ -= (size_t)s.w * s.h * 2 + (size_t)((s.w + 7) / 8) * s.h;
    free(s.px);
    free(s.mask);
    s.px = nullptr;
    s.mask = nullptr;
  }
}

void PyGfx::makeRoom(size_t bytes) {
  while (cacheBytes_ + bytes > CACHE_MAX_BYTES) {
    Sprite* old = nullptr;
    for (Sprite& s : sprites_)
      if (s.px && (!old || s.used < old->used)) old = &s;
    if (!old) return;
    freeSprite(*old);
  }
}

bool PyGfx::load(Sprite& s) {
  PNG* png = new (std::nothrow) PNG();
  if (!png) return false;                     // sin RAM ahora: se reintenta luego
  bool ok = false;
  int rc = png->open(s.path.c_str(), fOpen, fClose, fRead, fSeek, pngCb);
  if (rc == PNG_SUCCESS) {
    s.w = png->getWidth();
    s.h = png->getHeight();
    size_t mb = (s.w + 7) / 8;
    size_t bytes = (size_t)s.w * s.h * 2 + mb * s.h;
    if (bytes > SPRITE_MAX_BYTES) {
      s.big = true;                           // se decodificará cada vez que se dibuje
      ok = true;
    } else {
      makeRoom(bytes);
      s.px = (uint16_t*)malloc((size_t)s.w * s.h * 2);
      s.mask = (uint8_t*)malloc(mb * s.h);
      g_dec.line = (uint16_t*)malloc(s.w * 2);
      g_dec.lmask = (uint8_t*)malloc(mb);
      if (s.px && s.mask && g_dec.line && g_dec.lmask) {
        g_dec.png = png;
        g_dec.alpha = png->hasAlpha();
        g_dec.px = s.px;
        g_dec.mask = s.mask;
        g_dec.emit = toCache;
        ok = png->decode(nullptr, 0) == PNG_SUCCESS;
      }
      free(g_dec.line); free(g_dec.lmask);
      g_dec.line = nullptr; g_dec.lmask = nullptr;
      if (ok) cacheBytes_ += bytes;
      else { free(s.px); free(s.mask); s.px = nullptr; s.mask = nullptr; }
    }
  } else {
    s.bad = true;                             // no es un PNG válido: no se reintenta
    Serial.printf("[python] sprite no válido: %s\n", s.path.c_str());
  }
  png->close();
  delete png;
  return ok;
}

void PyGfx::pushRun(int16_t x, int16_t y, int16_t n) {
  if (n > 0) d_->pushPixels(x, y, n, 1, row_ + x);
}

void PyGfx::drawSprite(const Op& o) {
  if (o.id >= sprites_.size()) return;
  Sprite& s = sprites_[o.id];
  if (s.bad) return;
  if (!s.px && !s.big && !load(s)) return;
  s.used = millis();
  float sx = o.sx, sy = o.sy;
  if (!(sx > 0) || !(sy > 0) || !s.w || !s.h) return;
  const bool flip = o.flags & 1, hasC = o.flags & 2;
  // Pivote en el sprite (sin escalar) y en la pantalla, como el simulador
  float pcx = hasC ? o.cx : s.w / 2.0f, pcy = hasC ? o.cy : s.h / 2.0f;
  if (flip) pcx = s.w - pcx;
  float X = o.fx, Y = o.fy + AREA_Y;
  float PX = hasC ? X : X + s.w * sx / 2, PY = hasC ? Y : Y + s.h * sy / 2;
  float a = s.big ? 0 : o.ang * (float)M_PI / 180.0f;   // los grandes no giran
  float ca = cosf(a), sa = sinf(a);

  if (s.big) {
    drawBig(s, o);
    return;
  }
  // Caja en pantalla de las 4 esquinas transformadas
  float minx = 1e9, miny = 1e9, maxx = -1e9, maxy = -1e9;
  const float cu[4] = {0, (float)s.w, 0, (float)s.w}, cv[4] = {0, 0, (float)s.h, (float)s.h};
  for (int i = 0; i < 4; ++i) {
    float vx = (cu[i] - pcx) * sx, vy = (cv[i] - pcy) * sy;
    float rx = PX + vx * ca - vy * sa, ry = PY + vx * sa + vy * ca;
    minx = min(minx, rx); maxx = max(maxx, rx);
    miny = min(miny, ry); maxy = max(maxy, ry);
  }
  int16_t x0 = max<int16_t>(clipX0_, (int16_t)floorf(minx));
  int16_t x1 = min<int16_t>(clipX1_, (int16_t)ceilf(maxx));
  int16_t y0 = max<int16_t>(clipY0_, (int16_t)floorf(miny));
  int16_t y1 = min<int16_t>(clipY1_, (int16_t)ceilf(maxy));
  const int mb = (s.w + 7) / 8;
  for (int16_t y = y0; y < y1; ++y) {
    int16_t run = -1;
    float ddy = y + 0.5f - PY;
    for (int16_t x = x0; x < x1; ++x) {
      float ddx = x + 0.5f - PX;
      // Transformación inversa: pantalla -> píxel del sprite
      float u = (ddx * ca + ddy * sa) / sx + pcx;
      float v = (-ddx * sa + ddy * ca) / sy + pcy;
      bool on = false;
      if (u >= 0 && v >= 0 && u < s.w && v < s.h) {
        int iu = (int)u, iv = (int)v;
        if (flip) iu = s.w - 1 - iu;
        if (maskBit(s.mask + iv * mb, iu)) {
          row_[x] = s.px[iv * s.w + iu];
          on = true;
        }
      }
      if (on && run < 0) run = x;
      if (!on && run >= 0) { pushRun(run, y, x - run); run = -1; }
    }
    if (run >= 0) pushRun(run, y, x1 - run);
  }
}

// Sprite grande: se decodifica línea a línea y cada línea se pinta en las
// filas de pantalla que le tocan (escala por vecino más próximo, sin girar)
namespace {
int bigLine(PNGDRAW* d) {
  BigDraw& b = g_big;
  lineAndMask(d);
  while (b.nextRow < b.endRow) {
    int v = (int)floorf((b.nextRow + 0.5f - b.top) / b.sy);
    if (v > d->y) break;                      // esta fila usa una línea posterior
    if (v == d->y) b.self->bigRow(b.nextRow, g_dec.line, g_dec.lmask);
    ++b.nextRow;
  }
  return b.nextRow < b.endRow ? 1 : 0;        // 0 = ya no hace falta seguir
}
}  // namespace

void PyGfx::bigRow(int16_t y, const uint16_t* line, const uint8_t* mask) {
  BigDraw& b = g_big;
  int16_t run = -1;
  for (int16_t x = b.x0; x < b.x1; ++x) {
    int u = (int)floorf((x + 0.5f - b.left) / b.sx);
    bool on = false;
    if (u >= 0 && u < b.w) {
      if (b.flip) u = b.w - 1 - u;
      if (maskBit(mask, u)) { row_[x] = line[u]; on = true; }
    }
    if (on && run < 0) run = x;
    if (!on && run >= 0) { pushRun(run, y, x - run); run = -1; }
  }
  if (run >= 0) pushRun(run, y, b.x1 - run);
}

void PyGfx::drawBig(Sprite& s, const Op& o) {
  const bool flip = o.flags & 1, hasC = o.flags & 2;
  float pcx = hasC ? o.cx : 0, pcy = hasC ? o.cy : 0;
  if (flip && hasC) pcx = s.w - pcx;
  BigDraw& b = g_big;
  b.self = this;
  b.sx = o.sx; b.sy = o.sy; b.w = s.w; b.flip = flip;
  b.left = o.fx - pcx * o.sx;
  b.top = o.fy + AREA_Y - pcy * o.sy;
  b.x0 = max<int16_t>(clipX0_, (int16_t)floorf(b.left));
  b.x1 = min<int16_t>(clipX1_, (int16_t)ceilf(b.left + s.w * o.sx));
  b.nextRow = max<int16_t>(clipY0_, (int16_t)floorf(b.top));
  b.endRow = min<int16_t>(clipY1_, (int16_t)ceilf(b.top + s.h * o.sy));
  if (b.x1 <= b.x0 || b.endRow <= b.nextRow) return;
  PNG* png = new (std::nothrow) PNG();
  if (!png) return;
  if (png->open(s.path.c_str(), fOpen, fClose, fRead, fSeek, pngCb) == PNG_SUCCESS) {
    size_t mb = (png->getWidth() + 7) / 8;
    g_dec.line = (uint16_t*)malloc(png->getWidth() * 2);
    g_dec.lmask = (uint8_t*)malloc(mb);
    if (g_dec.line && g_dec.lmask) {
      g_dec.png = png;
      g_dec.alpha = png->hasAlpha();
      g_dec.emit = bigLine;
      png->decode(nullptr, 0);
    }
    free(g_dec.line); free(g_dec.lmask);
    g_dec.line = nullptr; g_dec.lmask = nullptr;
  }
  png->close();
  delete png;
}

// =============================================================================
//  Puente C (lo llama el módulo scicalc de MicroPython desde la tarea del script)
// =============================================================================
#include "src/mpy/port/scicalc_py.h"

namespace {
uint16_t to565(uint32_t rgb) { return Theme::rgb((rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255); }
int16_t clamp16(int v) { return v < -32000 ? -32000 : v > 32000 ? 32000 : (int16_t)v; }
}  // namespace

extern "C" {

int scpy_gfx_begin(void) { return pyGfx.begin() ? 0 : -1; }

void scpy_gfx_shape(int kind, int x, int y, int w, int h, uint32_t rgb) {
  PyGfx::Op o;
  o.kind = kind == 0 ? PyGfx::CLEAR : kind == 1 ? PyGfx::RECT : kind == 2 ? PyGfx::FRAME : PyGfx::LINE;
  o.x = clamp16(x); o.y = clamp16(y); o.w = clamp16(w); o.h = clamp16(h);
  o.c = to565(rgb);
  pyGfx.push(o);
}

void scpy_gfx_text(const char* s, size_t n, int x, int y, uint32_t fg, int32_t bg, int size) {
  PyGfx::Op o;
  o.kind = PyGfx::TEXT;
  o.x = clamp16(x); o.y = clamp16(y);
  o.c = to565(fg);
  o.flags = (uint8_t)(size < 1 ? 1 : size > 8 ? 8 : size);
  if (bg >= 0) { o.flags |= 0x80; o.bg = to565((uint32_t)bg); }
  pyGfx.push(o, s, n);
}

int scpy_gfx_sprite(const char* abs) { return pyGfx.newSprite(abs); }

void scpy_gfx_draw(int id, float x, float y, float sx, float sy, int flip, float ang,
                   int hasCenter, float cx, float cy) {
  PyGfx::Op o;
  o.kind = PyGfx::SPRITE;
  o.id = (uint16_t)id;
  o.fx = x; o.fy = y; o.sx = sx; o.sy = sy; o.ang = ang; o.cx = cx; o.cy = cy;
  o.flags = (flip ? 1 : 0) | (hasCenter ? 2 : 0);
  pyGfx.push(o);
}

void scpy_gfx_clip(int x, int y, int w, int h) {
  PyGfx::Op o;
  o.kind = PyGfx::CLIP;
  o.x = clamp16(x); o.y = clamp16(y); o.w = clamp16(w); o.h = clamp16(h);
  pyGfx.push(o);
}

int scpy_gfx_show(void) { return pyGfx.show(); }
uint64_t scpy_keys_held(void) { return pyGfx.held(); }

int scpy_key_event(int* key, int* shift) {
  Key k;
  bool sh;
  if (!pyGfx.popKey(k, sh)) return 0;
  *key = static_cast<int>(k);
  *shift = sh ? 1 : 0;
  return 1;
}

}  // extern "C"
