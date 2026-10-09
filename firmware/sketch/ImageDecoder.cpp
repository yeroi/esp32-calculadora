// =============================================================================
//  ImageDecoder.cpp
// =============================================================================
#include "ImageDecoder.h"
#include <new>
#include <AnimatedGIF.h>
#include <PNGdec.h>
#include <TJpg_Decoder.h>

namespace ImageDecoder {
namespace {

// -----------------------------------------------------------------------------
//  Escalador de líneas (vecino más próximo)
// -----------------------------------------------------------------------------
//  Recibe líneas de la imagen ORIGEN (en cualquier orden, como hace el BMP que
//  va de abajo arriba) y pinta las filas de pantalla que les corresponden.
struct Scaler {
  Display* gfx = nullptr;
  int16_t srcW = 0, srcH = 0;     // imagen origen
  int16_t dstW = 0, dstH = 0;     // tamaño en pantalla
  int16_t ox = 0, oy = 0;         // esquina superior izquierda en pantalla
  uint16_t* line = nullptr;       // dstW píxeles

  bool begin(Display& d, int16_t w, int16_t h, const Rect& area) {
    gfx = &d;
    srcW = w;
    srcH = h;
    float k = min(min((float)area.w / w, (float)area.h / h), 4.0f);
    dstW = max<int16_t>(1, (int16_t)(w * k));
    dstH = max<int16_t>(1, (int16_t)(h * k));
    ox = area.x + (area.w - dstW) / 2;
    oy = area.y + (area.h - dstH) / 2;
    line = new (std::nothrow) uint16_t[dstW];
    return line != nullptr;
  }
  void end() { delete[] line; line = nullptr; }

  // Línea origen 'sy' (srcW píxeles RGB565 nativos)
  void emit(int sy, const uint16_t* src) {
    if (sy < 0 || sy >= srcH) return;
    // Filas de pantalla r con floor(r*srcH/dstH) == sy
    int r0 = (int)(((int32_t)sy * dstH + srcH - 1) / srcH);
    int r1 = (int)(((int32_t)(sy + 1) * dstH + srcH - 1) / srcH);
    if (r0 >= r1) return;                       // fila descartada al reducir
    for (int x = 0; x < dstW; ++x) line[x] = src[(int32_t)x * srcW / dstW];
    for (int r = r0; r < r1 && r < dstH; ++r) gfx->pushPixels(ox, oy + r, dstW, 1, line);
  }
};

// Estado compartido con los callbacks de las librerías (no tienen "this").
// Solo la UI decodifica, y de una en una: basta con un contexto estático.
struct Context {
  Display* gfx = nullptr;
  Storage* sd = nullptr;
  Scaler scaler;
  uint16_t* srcLine = nullptr;    // una línea origen en RGB565
  Rect area{};
  // JPG: aumento entero y origen
  uint8_t jpgUp = 1;
  int16_t jpgX = 0, jpgY = 0;
};
Context g;

uint16_t rgb565(uint8_t r, uint8_t gg, uint8_t b) { return Theme::rgb(r, gg, b); }

// -----------------------------------------------------------------------------
//  Archivo genérico para PNGdec y AnimatedGIF (mismas firmas)
// -----------------------------------------------------------------------------
void* fileOpen(const char* path, int32_t* size) {
  fs::File* f = new (std::nothrow) fs::File(g.sd->openRead(String(path)));
  if (!f) return nullptr;
  if (!*f) { delete f; return nullptr; }
  *size = (int32_t)f->size();
  return f;
}
void fileClose(void* h) {
  fs::File* f = static_cast<fs::File*>(h);
  if (f) { f->close(); delete f; }
}
template <typename T>
int32_t fileRead(T* pf, uint8_t* buf, int32_t len) {
  fs::File* f = static_cast<fs::File*>(pf->fHandle);
  int32_t n = (int32_t)f->read(buf, len);
  pf->iPos = (int32_t)f->position();
  return n;
}
template <typename T>
int32_t fileSeek(T* pf, int32_t pos) {
  fs::File* f = static_cast<fs::File*>(pf->fHandle);
  f->seek(pos);
  pf->iPos = (int32_t)f->position();
  return pf->iPos;
}
int32_t pngRead(PNGFILE* f, uint8_t* b, int32_t n) { return fileRead(f, b, n); }
int32_t pngSeek(PNGFILE* f, int32_t p) { return fileSeek(f, p); }
int32_t gifRead(GIFFILE* f, uint8_t* b, int32_t n) { return fileRead(f, b, n); }
int32_t gifSeek(GIFFILE* f, int32_t p) { return fileSeek(f, p); }

// -----------------------------------------------------------------------------
//  PNG
// -----------------------------------------------------------------------------
PNG* g_png = nullptr;

int pngDraw(PNGDRAW* d) {
  // Fondo del tema para mezclar la transparencia (formato 0x00RRGGBB)
  g_png->getLineAsRGB565(d, g.srcLine, PNG_RGB565_LITTLE_ENDIAN, 0x000A0C12);
  g.scaler.emit(d->y, g.srcLine);
  return 1;                                     // seguir decodificando
}

bool drawPng(const String& path, String& err) {
  g_png = new (std::nothrow) PNG();
  if (!g_png) { err = "Sin memoria para PNG (~45 KB)"; return false; }
  bool ok = false;
  int rc = g_png->open(path.c_str(), fileOpen, fileClose, pngRead, pngSeek, pngDraw);
  const int w = g_png->getWidth(), h = g_png->getHeight();
  if (rc != PNG_SUCCESS || w <= 0 || h <= 0) {
    err = rc == PNG_TOO_BIG ? "PNG demasiado ancho para la RAM" : "PNG no válido";
  } else {
    g.srcLine = new (std::nothrow) uint16_t[w];
    if (g.srcLine && g.scaler.begin(*g.gfx, w, h, g.area)) {
      rc = g_png->decode(nullptr, 0);
      ok = (rc == PNG_SUCCESS);
      if (!ok) err = rc == PNG_TOO_BIG ? "PNG demasiado ancho para la RAM"
                                       : "PNG no soportado (¿entrelazado?)";
    } else {
      err = "Sin memoria para la imagen";
    }
    g.scaler.end();
    delete[] g.srcLine;
    g.srcLine = nullptr;
  }
  // Siempre: PNGdec no cierra el archivo cuando open() falla, y sin esto se
  // agotarían los descriptores de la SD (máx. 5 abiertos a la vez).
  g_png->close();
  delete g_png;
  g_png = nullptr;
  return ok;
}

// -----------------------------------------------------------------------------
//  GIF (primer fotograma)
// -----------------------------------------------------------------------------
int16_t g_gifCanvasW = 0;

void gifDraw(GIFDRAW* d) {
  // Línea del lienzo completo: fondo + la parte que trae este fotograma
  for (int x = 0; x < g_gifCanvasW; ++x) g.srcLine[x] = Theme::BG;
  for (int x = 0; x < d->iWidth; ++x) {
    int cx = d->iX + x;
    if (cx < 0 || cx >= g_gifCanvasW) continue;
    uint8_t p = d->pPixels[x];
    if (d->ucHasTransparency && p == d->ucTransparent) continue;
    g.srcLine[cx] = d->pPalette[p];
  }
  g.scaler.emit(d->iY + d->y, g.srcLine);
}

bool drawGif(const String& path, String& err) {
  AnimatedGIF* gif = new (std::nothrow) AnimatedGIF();
  if (!gif) { err = "Sin memoria para GIF (~25 KB)"; return false; }
  bool ok = false;
  gif->begin(GIF_PALETTE_RGB565_LE);
  if (gif->open(path.c_str(), fileOpen, fileClose, gifRead, gifSeek, gifDraw) &&
      gif->getCanvasWidth() > 0 && gif->getCanvasHeight() > 0) {
    g_gifCanvasW = gif->getCanvasWidth();
    int h = gif->getCanvasHeight();
    g.srcLine = new (std::nothrow) uint16_t[g_gifCanvasW];
    if (g.srcLine && g.scaler.begin(*g.gfx, g_gifCanvasW, h, g.area)) {
      // Solo el primer fotograma: 1 = hay más, 0 = era el último, -1 = error
      ok = gif->playFrame(false, nullptr) >= 0;
      if (!ok) err = "GIF no soportado";
    } else {
      err = "Sin memoria para la imagen";
    }
    g.scaler.end();
    delete[] g.srcLine;
    g.srcLine = nullptr;
  } else {
    err = "GIF no válido o demasiado ancho";
  }
  gif->close();                                 // también si open() falló
  delete gif;
  return ok;
}

// -----------------------------------------------------------------------------
//  JPG (TJpg_Decoder entrega bloques MCU de 8x8 / 16x16)
// -----------------------------------------------------------------------------
bool jpgBlock(int16_t x, int16_t y, uint16_t w, uint16_t h, uint16_t* px) {
  const uint8_t u = g.jpgUp;
  const Rect& a = g.area;
  if (u == 1) {
    // Recorte al área (por si la imagen no cabe ni a 1/8)
    for (uint16_t r = 0; r < h; ++r) {
      int16_t sy = g.jpgY + y + r;
      if (sy < a.y || sy >= a.y + a.h) continue;
      int16_t sx = g.jpgX + x;
      int16_t c0 = max<int16_t>(0, a.x - sx);
      int16_t c1 = min<int16_t>(w, a.x + a.w - sx);
      if (c1 > c0) g.gfx->pushPixels(sx + c0, sy, c1 - c0, 1, px + r * w + c0);
    }
    return true;
  }
  // Aumento entero: cada píxel se repite u veces en x y en y
  uint16_t row[16 * 4];
  if (w * u > (int)(sizeof row / sizeof row[0])) return false;
  for (uint16_t r = 0; r < h; ++r) {
    for (uint16_t c = 0; c < w; ++c)
      for (uint8_t k = 0; k < u; ++k) row[c * u + k] = px[r * w + c];
    for (uint8_t k = 0; k < u; ++k)
      g.gfx->pushPixels(g.jpgX + (x * u), g.jpgY + (y + r) * u + k, w * u, 1, row);
  }
  return true;
}

bool drawJpg(const String& path, uint16_t w, uint16_t h, String& err) {
  // Escala de TJpgDec (1, 2, 4, 8): la menor que haga caber la imagen
  uint8_t s = 1;
  while (s < 8 && (w / s > g.area.w || h / s > g.area.h)) s <<= 1;
  uint16_t sw = (w + s - 1) / s, sh = (h + s - 1) / s;
  // Imágenes pequeñas: aumento entero hasta x4 (como el simulador)
  uint8_t up = 1;
  if (s == 1) {
    while (up < 4 && sw * (up + 1) <= g.area.w && sh * (up + 1) <= g.area.h) ++up;
  }
  g.jpgUp = up;
  g.jpgX = g.area.x + ((int16_t)g.area.w - (int16_t)(sw * up)) / 2;
  g.jpgY = g.area.y + ((int16_t)g.area.h - (int16_t)(sh * up)) / 2;
  if (g.jpgX < g.area.x) g.jpgX = g.area.x;
  if (g.jpgY < g.area.y) g.jpgY = g.area.y;

  TJpgDec.setJpgScale(s);
  TJpgDec.setSwapBytes(false);
  TJpgDec.setCallback(jpgBlock);
  fs::File f = g.sd->openRead(path);
  JRESULT rc = TJpgDec.drawFsJpg(0, 0, f);
  f.close();
  if (rc != JDR_OK) {
    err = rc == JDR_FMT3 ? "JPG con un formato no soportado" : "JPG no válido";
    return false;
  }
  return true;
}

// -----------------------------------------------------------------------------
//  BMP (sin comprimir: 8 bits con paleta, 24 y 32 bits)
// -----------------------------------------------------------------------------
uint32_t le32(const uint8_t* p) { return p[0] | (p[1] << 8) | (p[2] << 16) | ((uint32_t)p[3] << 24); }
uint16_t le16(const uint8_t* p) { return p[0] | (p[1] << 8); }

bool drawBmp(const String& path, String& err) {
  fs::File f = g.sd->openRead(path);
  uint8_t hdr[54];
  if (!f || f.read(hdr, sizeof hdr) != sizeof hdr || hdr[0] != 'B' || hdr[1] != 'M') {
    err = "BMP no válido";
    return false;
  }
  uint32_t dataOff = le32(hdr + 10), dibSize = le32(hdr + 14);
  int32_t w = (int32_t)le32(hdr + 18), h = (int32_t)le32(hdr + 22);
  uint16_t bpp = le16(hdr + 28);
  uint32_t comp = le32(hdr + 30);
  bool bottomUp = h > 0;
  if (h < 0) h = -h;
  if (w <= 0 || h <= 0 || w > 4096 || h > 4096 || (comp != 0 && comp != 3) ||
      (bpp != 8 && bpp != 24 && bpp != 32)) {
    f.close();
    err = "BMP no soportado (solo 8/24/32 bits)";
    return false;
  }
  // Paleta de 8 bits (BGRA) convertida a RGB565
  uint16_t* pal = nullptr;
  if (bpp == 8) {
    pal = new (std::nothrow) uint16_t[256];
    if (!pal) { f.close(); err = "Sin memoria"; return false; }
    uint32_t nColors = le32(hdr + 46);
    if (nColors == 0 || nColors > 256) nColors = 256;
    f.seek(14 + dibSize);
    for (uint32_t i = 0; i < 256; ++i) {
      uint8_t q[4] = {0, 0, 0, 0};
      if (i < nColors) f.read(q, 4);
      pal[i] = rgb565(q[2], q[1], q[0]);
    }
  }
  const uint32_t rowBytes = ((uint32_t)w * bpp / 8 + 3) & ~3u;   // filas alineadas a 4
  uint8_t* raw = new (std::nothrow) uint8_t[rowBytes];
  g.srcLine = new (std::nothrow) uint16_t[w];
  bool ok = raw && g.srcLine && g.scaler.begin(*g.gfx, w, h, g.area);
  if (!ok) err = "Sin memoria para la imagen";
  if (ok) {
    f.seek(dataOff);
    for (int32_t i = 0; i < h; ++i) {
      if (f.read(raw, rowBytes) != rowBytes) break;
      for (int32_t x = 0; x < w; ++x) {
        if (bpp == 8)       g.srcLine[x] = pal[raw[x]];
        else if (bpp == 24) g.srcLine[x] = rgb565(raw[x * 3 + 2], raw[x * 3 + 1], raw[x * 3]);
        else                g.srcLine[x] = rgb565(raw[x * 4 + 2], raw[x * 4 + 1], raw[x * 4]);
      }
      g.scaler.emit(bottomUp ? h - 1 - i : i, g.srcLine);
    }
  }
  g.scaler.end();
  delete[] g.srcLine;
  g.srcLine = nullptr;
  delete[] raw;
  delete[] pal;
  f.close();
  return ok;
}

// Busca el marcador SOFn del JPEG para leer el tamaño sin decodificar.
// 'progressive' = SOF2 (TJpgDec solo sabe decodificar JPEG "baseline").
bool jpgSize(Storage& sd, const String& path, uint16_t& w, uint16_t& h, bool& progressive) {
  fs::File f = sd.openRead(path);
  if (!f) return false;
  uint8_t m[9];
  uint32_t pos = 2;                             // tras FF D8
  bool found = false;
  while (pos + 9 <= f.size() && pos < 256 * 1024) {
    if (!f.seek(pos) || f.read(m, 4) != 4 || m[0] != 0xFF) break;
    const uint8_t marker = m[1];
    const uint16_t len = (m[2] << 8) | m[3];
    if (marker >= 0xC0 && marker <= 0xCF && marker != 0xC4 && marker != 0xC8 && marker != 0xCC) {
      if (f.read(m, 5) != 5) break;
      h = (m[1] << 8) | m[2];
      w = (m[3] << 8) | m[4];
      progressive = marker == 0xC2;
      found = w > 0 && h > 0;
      break;
    }
    if (marker == 0xD9 || marker == 0xDA || len < 2) break;   // fin o datos: no hay SOF
    pos += 2 + len;
  }
  f.close();
  return found;
}

enum class Fmt : uint8_t { Unknown, Png, Jpg, Gif, Bmp };

Fmt sniff(const uint8_t* b, size_t n) {
  if (n >= 8 && b[0] == 0x89 && b[1] == 'P' && b[2] == 'N' && b[3] == 'G') return Fmt::Png;
  if (n >= 3 && b[0] == 0xFF && b[1] == 0xD8 && b[2] == 0xFF) return Fmt::Jpg;
  if (n >= 6 && memcmp(b, "GIF8", 4) == 0) return Fmt::Gif;
  if (n >= 2 && b[0] == 'B' && b[1] == 'M') return Fmt::Bmp;
  return Fmt::Unknown;
}

}  // namespace

// =============================================================================
bool probe(Storage& sd, const String& path, Info& info) {
  uint8_t b[32];
  size_t n = sd.readAt(path, 0, b, sizeof b);
  switch (sniff(b, n)) {
    case Fmt::Png:
      if (n < 24 || memcmp(b + 12, "IHDR", 4) != 0) return false;
      info.w = (b[18] << 8) | b[19];               // IHDR: ancho y alto big-endian
      info.h = (b[22] << 8) | b[23];
      info.format = "PNG";
      return true;
    case Fmt::Gif:
      info.w = le16(b + 6);
      info.h = le16(b + 8);
      info.format = "GIF";
      return true;
    case Fmt::Bmp: {
      if (n < 26) return false;
      int32_t h = (int32_t)le32(b + 22);
      info.w = (uint16_t)le32(b + 18);
      info.h = (uint16_t)(h < 0 ? -h : h);
      info.format = "BMP";
      return true;
    }
    case Fmt::Jpg: {
      bool progressive = false;
      info.format = "JPG";
      return jpgSize(sd, path, info.w, info.h, progressive);
    }
    default:
      return false;
  }
}

bool draw(Display& gfx, Storage& sd, const String& path, const Rect& area, String& err) {
  g.gfx = &gfx;
  g.sd = &sd;
  g.area = area;
  uint8_t b[32];
  size_t n = sd.readAt(path, 0, b, sizeof b);
  switch (sniff(b, n)) {
    case Fmt::Png: return drawPng(path, err);
    case Fmt::Gif: return drawGif(path, err);
    case Fmt::Bmp: return drawBmp(path, err);
    case Fmt::Jpg: {
      uint16_t w = 0, h = 0;
      bool progressive = false;
      if (!jpgSize(sd, path, w, h, progressive)) { err = "JPG no válido"; return false; }
      if (progressive) { err = "JPG progresivo: no soportado (usa baseline)"; return false; }
      return drawJpg(path, w, h, err);
    }
    default:
      err = "Formato de imagen no reconocido";
      return false;
  }
}

}  // namespace ImageDecoder
