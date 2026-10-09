// =============================================================================
//  FileViewer.cpp
// =============================================================================
#include "FileViewer.h"

namespace {
  constexpr int16_t TEXT_Y = Display::BODY_Y + 4;
  constexpr int16_t LINE_H = 11;
  constexpr int16_t NUM_X = 3;                    // número de línea
  constexpr int16_t CODE_X = 27;                  // texto
  constexpr uint8_t COLS = (Display::W - CODE_X) / 6;   // 48 caracteres visibles
  constexpr size_t  READ_MAX = 160;               // bytes leídos por línea

  // Palabras clave resaltadas (PY_KEYWORDS del simulador)
  const char* const PY_KEYWORDS[] = {
    "def", "return", "for", "in", "while", "if", "elif", "else", "import", "from",
    "print", "range", "True", "False", "None", "and", "or", "not", "try", "except",
    "class", "with", "as", "break", "continue", "pass", "lambda",
  };
  bool isKeyword(const String& w) {
    for (const char* k : PY_KEYWORDS) if (w == k) return true;
    return false;
  }
  bool isIdentStart(char c) { return isalpha((unsigned char)c) || c == '_'; }
  bool isIdent(char c) { return isalnum((unsigned char)c) || c == '_'; }
}

// ---- Apertura -----------------------------------------------------------------
bool FileViewer::open(const String& path) {
  close();
  fs::File f = sd_.openRead(path);
  if (!f || f.isDirectory()) return false;
  size_ = (uint32_t)f.size();
  f.close();
  path_ = path;
  isPy_ = Path::ext(path) == ".py";
  top_ = 0;

  if (Path::kind(path, false) == FileKind::Img && ImageDecoder::probe(sd_, path, img_)) {
    mode_ = Mode::Image;
  } else if (looksLikeText()) {
    mode_ = Mode::Text;
    indexLines();
  } else {
    mode_ = Mode::Hex;
  }
  return true;
}

void FileViewer::close() {
  mode_ = Mode::None;
  lineOff_.clear();
  lineOff_.shrink_to_fit();            // devolvemos la RAM al heap
  path_ = "";
}

// Texto = sin bytes 0 y UTF-8 válido en los primeros 4 KB (como el simulador)
bool FileViewer::looksLikeText() {
  fs::File f = sd_.openRead(path_);
  if (!f) return false;
  uint8_t buf[256];
  uint32_t total = 0;
  uint8_t pending = 0;                 // bytes de continuación UTF-8 esperados
  bool ok = true;
  while (ok && total < 4096) {
    size_t n = f.read(buf, sizeof buf);
    if (n == 0) break;
    for (size_t i = 0; i < n && ok; ++i) {
      uint8_t c = buf[i];
      if (c == 0) { ok = false; break; }
      if (pending) {
        if ((c & 0xC0) != 0x80) ok = false;
        --pending;
      } else if (c >= 0x80) {
        if ((c & 0xE0) == 0xC0) pending = 1;
        else if ((c & 0xF0) == 0xE0) pending = 2;
        else if ((c & 0xF8) == 0xF0) pending = 3;
        else ok = false;
      }
    }
    total += n;
  }
  f.close();
  return ok;                            // un carácter cortado al final se tolera
}

void FileViewer::indexLines() {
  lineOff_.clear();
  linesCut_ = false;
  lineOff_.push_back(0);
  fs::File f = sd_.openRead(path_);
  if (!f) return;
  uint8_t buf[512];
  uint32_t pos = 0;
  size_t n;
  while ((n = f.read(buf, sizeof buf)) > 0) {
    for (size_t i = 0; i < n; ++i) {
      if (buf[i] != '\n') continue;
      if (lineOff_.size() >= MAX_LINES) { linesCut_ = true; break; }
      lineOff_.push_back(pos + i + 1);
    }
    if (linesCut_) break;
    pos += n;
  }
  f.close();
  // Un '\n' final no abre una línea nueva visible... salvo que haya algo detrás
  if (lineOff_.size() > 1 && lineOff_.back() >= size_) lineOff_.pop_back();
}

// ---- Teclas -------------------------------------------------------------------
bool FileViewer::onKey(const KeyEvent& ev) {
  if (ev.key == Key::Left || ev.key == Key::Del || ev.key == Key::AC) return true;

  uint16_t total = 0, page = 0;
  if (mode_ == Mode::Text) { total = lineOff_.size(); page = TEXT_ROWS; }
  else if (mode_ == Mode::Hex) {
    total = (uint16_t)min<uint32_t>((size_ + HEX_COLS - 1) / HEX_COLS, 65535);
    page = HEX_ROWS;
  } else {
    return false;
  }
  const uint16_t maxTop = total > page ? total - page : 0;
  uint16_t old = top_;
  switch (ev.key) {
    case Key::Up:    if (top_ > 0) --top_; break;
    case Key::Down:  if (top_ < maxTop) ++top_; break;
    case Key::Right: top_ = min<uint16_t>(top_ + page, maxTop); break;
    default: break;
  }
  if (top_ != old) {
    if (mode_ == Mode::Text) drawText(); else drawHex();
    drawFooter();
  }
  return false;
}

// ---- Dibujo -------------------------------------------------------------------
void FileViewer::draw() {
  switch (mode_) {
    case Mode::Text:  drawText(); break;
    case Mode::Hex:   drawHex(); break;
    case Mode::Image: drawImage(); break;
    default: return;
  }
  drawFooter();
}

void FileViewer::drawFooter() {
  char buf[80];
  switch (mode_) {
    case Mode::Text: {
      unsigned n = lineOff_.size();
      snprintf(buf, sizeof buf, "líneas %u-%u de %u%s  (solo lectura)  ◄ volver", top_ + 1,
               (unsigned)min<unsigned>(top_ + TEXT_ROWS, n), n, linesCut_ ? "+" : "");
      break;
    }
    case Mode::Hex:
      snprintf(buf, sizeof buf, "vista hexadecimal (solo lectura)   ◄ volver");
      break;
    case Mode::Image:
      snprintf(buf, sizeof buf, "%s %u×%u px · %s   ◄ volver", img_.format, img_.w, img_.h,
               humanSize(size_).c_str());
      break;
    default:
      return;
  }
  gfx_.footer(buf);
}

void FileViewer::drawText() {
  fs::File f = sd_.openRead(path_);
  char raw[READ_MAX + 1];
  for (uint8_t r = 0; r < TEXT_ROWS; ++r) {
    const int16_t y = TEXT_Y + r * LINE_H;
    gfx_.fillRect(0, y, Display::W, LINE_H, Theme::BG);
    const uint32_t li = top_ + r;
    if (!f || li >= lineOff_.size()) continue;

    // Lee la línea (como mucho READ_MAX bytes) y la limpia
    uint32_t start = lineOff_[li];
    uint32_t end = li + 1 < lineOff_.size() ? lineOff_[li + 1] : size_;
    size_t want = min<uint32_t>(end - start, READ_MAX);
    size_t n = f.seek(start) ? f.read(reinterpret_cast<uint8_t*>(raw), want) : 0;
    raw[n] = '\0';
    String line;
    line.reserve(n + 8);
    for (size_t i = 0; i < n; ++i) {
      char c = raw[i];
      if (c == '\r' || c == '\n') continue;
      if (c == '\t') line += "    ";
      else line += c;
    }
    char num[6];
    snprintf(num, sizeof num, "%3u", (unsigned)(li + 1));
    gfx_.text(NUM_X, y + 1, num, 1, Theme::MUTED, Theme::BG);
    drawTextLine(y + 1, line);
  }
  if (f) f.close();
}

void FileViewer::drawTextLine(int16_t y, const String& line) {
  if (isPy_) drawCode(CODE_X, y, line);
  else gfx_.text(CODE_X, y, line.c_str(), 1, Theme::TEXT, Theme::BG, Align::Left, 0, false,
                 COLS * 6);
}

// Resaltado mínimo, igual que FilesApp.draw_code() del simulador
void FileViewer::drawCode(int16_t x0, int16_t y, const String& line) {
  const int16_t maxX = x0 + COLS * 6;
  String t = line;
  t.trim();
  if (t.startsWith("#")) {
    gfx_.text(x0, y, line.c_str(), 1, Theme::OK, Theme::BG, Align::Left, 0, false, maxX - x0);
    return;
  }
  const char* s = line.c_str();
  const size_t n = line.length();
  size_t i = 0;
  int16_t x = x0;
  auto seg = [&](size_t a, size_t b, uint16_t col) {
    if (x >= maxX || b <= a) return;
    String part = line.substring(a, b);
    gfx_.text(x, y, part.c_str(), 1, col, Theme::BG, Align::Left, 0, false, maxX - x);
    x += Display::textWidth(part.c_str(), 1);
  };
  while (i < n && x < maxX) {
    char c = s[i];
    if (c == '"' || c == '\'') {                       // cadena
      const char* q = strchr(s + i + 1, c);
      size_t j = q ? (size_t)(q - s) + 1 : n;
      seg(i, j, Theme::WARN);
      i = j;
    } else if (c == '#') {                             // comentario hasta el final
      seg(i, n, Theme::OK);
      return;
    } else if (isIdentStart(c)) {                      // palabra
      size_t j = i;
      while (j < n && isIdent(s[j])) ++j;
      String w = line.substring(i, j);
      seg(i, j, isKeyword(w) ? Theme::ACCENT : Theme::TEXT);
      i = j;
    } else {                                           // resto, en bloque
      size_t j = i + 1;
      while (j < n && s[j] != '"' && s[j] != '\'' && s[j] != '#' && !isIdentStart(s[j])) ++j;
      seg(i, j, Theme::TEXT);
      i = j;
    }
  }
}

void FileViewer::drawHex() {
  gfx_.fillRect(0, Display::BODY_Y, Display::W, Display::FOOTER_Y - Display::BODY_Y - 2,
                Theme::BG);
  String head = "Archivo binario · " + humanSize(size_);
  gfx_.textBold(7, Display::BODY_Y + 5, head.c_str(), 1, Theme::WARN, Theme::BG);

  uint8_t data[HEX_ROWS * HEX_COLS];
  const uint32_t off0 = (uint32_t)top_ * HEX_COLS;
  size_t n = sd_.readAt(path_, off0, data, sizeof data);
  char line[64];
  for (uint8_t r = 0; r < HEX_ROWS; ++r) {
    size_t base = (size_t)r * HEX_COLS;
    if (base >= n) break;
    int p = snprintf(line, sizeof line, "%06lX  ", (unsigned long)(off0 + base));
    for (uint8_t c = 0; c < HEX_COLS; ++c) {
      if (base + c < n) p += snprintf(line + p, sizeof line - p, "%02X ", data[base + c]);
      else p += snprintf(line + p, sizeof line - p, "   ");
    }
    line[p++] = ' ';
    for (uint8_t c = 0; c < HEX_COLS && base + c < n; ++c) {
      uint8_t b = data[base + c];
      line[p++] = (b >= 32 && b < 127) ? (char)b : '.';
    }
    line[p] = '\0';
    gfx_.text(7, Display::BODY_Y + 20 + r * 11, line, 1, Theme::TEXT, Theme::BG);
  }
}

void FileViewer::drawImage() {
  // Área de la imagen: como el simulador (márgenes de 5 px y sitio para el pie)
  const ImageDecoder::Rect area{5, (int16_t)(Display::BODY_Y + 4), (int16_t)(Display::W - 10),
                                (int16_t)(Display::FOOTER_Y - Display::BODY_Y - 8)};
  String err;
  if (!ImageDecoder::draw(gfx_, sd_, path_, area, err)) {
    gfx_.text(0, 100, "No se puede mostrar", 2, Theme::ERR, Theme::BG, Align::Center, Display::W);
    gfx_.text(0, 124, err.c_str(), 1, Theme::MUTED, Theme::BG, Align::Center, Display::W);
  }
}
