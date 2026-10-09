// =============================================================================
//  PythonApp.cpp
// =============================================================================
#include "PythonApp.h"
#include "PyGfx.h"

namespace {
uint16_t colorFor(char c) {
  switch (c) {
    case '\x01': return Theme::ERR;
    case '\x03': return Theme::SHIFT;
    case '\x04': return Theme::ACCENT;
    case '\x05': return Theme::MUTED;
    default:     return 0;
  }
}

// Parte una línea en filas de 'cols' caracteres (UTF-8), por un espacio si
// se puede (como wrap_console del simulador)
void wrapLine(const String& line, uint8_t cols, uint16_t color, std::vector<String>& outText,
              std::vector<uint16_t>& outColor) {
  // Índices de inicio de cada carácter
  std::vector<uint16_t> idx;
  const char* base = line.c_str();
  const char* p = base;
  while (*p) { idx.push_back(p - base); Display::decodeUtf8(p); }
  size_t n = idx.size();
  size_t pos = 0;
  if (n == 0) { outText.push_back(""); outColor.push_back(color); return; }
  while (n - pos > cols) {
    size_t cut = 0;
    for (size_t k = pos + cols; k > pos + cols / 2; --k) {
      if (line[idx[k]] == ' ') { cut = k; break; }
    }
    if (!cut) cut = pos + cols;
    outText.push_back(line.substring(idx[pos], idx[cut]));
    outColor.push_back(color);
    pos = cut;
    while (pos < n && line[idx[pos]] == ' ') ++pos;
  }
  outText.push_back(line.substring(idx[pos]));
  outColor.push_back(color);
}
}  // namespace

PythonApp::PythonApp(AppManager& m)
    : App(m), browser_(m.gfx(), m.storage(), true), viewer_(m.gfx(), m.storage()) {}

void PythonApp::onEnter() {
  if (pyGfx.active() && !pySandbox.alive()) pyGfx.end();   // juego anterior ya cerrado
  viewer_.close();
  console_ = false;
  browser_.refresh();
}

void PythonApp::onExit() {
  viewer_.close();
  pySandbox.stop();                       // MENU con un script en marcha: se para
  console_ = false;
}

void PythonApp::drawFooter() {
  gfx().footer("EXE ejecutar   SHIFT+EXE ver código   ◄ subir");
}

void PythonApp::draw() {
  if (viewer_.isOpen()) { viewer_.draw(); return; }
  if (console_) {
    stateShown_ = -1;
    statusShown_ = "";
    shown_.assign(ROWS, String("\x7f"));   // fuerza repintar todas las filas
    shownColor_.assign(ROWS, 0);
    drawStatus(true);
    drawConsole(true);
    drawConsoleFooter();
    return;
  }
  if (!st().sdMounted) {
    gfx().text(0, 100, "MicroSD no detectada", 2, Theme::ERR, Theme::BG, Align::Center, Display::W);
    gfx().footer("Los scripts .py se guardan en la MicroSD");
    return;
  }
  browser_.draw("No hay scripts .py aquí");
  drawFooter();
}

// ---- Ejecutar -------------------------------------------------------------------------
void PythonApp::run(const String& path) { start(path); }

void PythonApp::start(const String& path) {
  if (st().exam) {
    dialogs().info("Modo examen", {"Python está bloqueado durante", "el modo examen.", "",
                                   "Desactívalo en Ajustes."});
    return;
  }
  if (pySandbox.alive()) {
    dialogs().info("Python", {"Todavía se está cerrando el", "script anterior. Espera un", "momento."});
    return;
  }
  if (pyGfx.active()) pyGfx.end();
  script_ = path;
  scroll_ = 0;
  rows_.clear();
  seenVersion_ = 0;
  console_ = true;
  pySandbox.start(path);
  String t = "► " + Path::name(path);
  setTitle(t.c_str());
  requestRedraw();
}

void PythonApp::closeConsole() {
  console_ = false;
  rows_.clear();
  rows_.shrink_to_fit();
  setTitle(title());
  browser_.refresh();
  requestRedraw();
}

// ---- Consola ----------------------------------------------------------------------------
void PythonApp::buildRows() {
  std::vector<String> lines;
  pySandbox.copyLines(lines);
  std::vector<String> text;
  std::vector<uint16_t> color;
  for (String& l : lines) {
    uint16_t c = l.length() ? colorFor(l[0]) : 0;
    if (c) l.remove(0, 1);
    wrapLine(l, COLS, c ? c : Theme::TEXT, text, color);
  }
  rows_.clear();
  rows_.reserve(text.size());
  for (size_t i = 0; i < text.size(); ++i) rows_.push_back({text[i], color[i]});
}

void PythonApp::drawStatus(bool force) {
  using S = PySandbox::State;
  S s = pySandbox.state();
  char buf[64];
  uint16_t col;
  float secs = pySandbox.elapsedMs() / 1000.0f;
  switch (s) {
    case S::Running:  snprintf(buf, sizeof buf, "Ejecutando... %4.1f s   (AC detiene)", secs); col = Theme::WARN; break;
    case S::Asking:   snprintf(buf, sizeof buf, "Esperando tu permiso... (watchdog en pausa)"); col = Theme::SHIFT; break;
    case S::Ok:       snprintf(buf, sizeof buf, "OK - terminado en %.2f s", secs); col = Theme::OK; break;
    case S::Error:    snprintf(buf, sizeof buf, "ERROR - el script terminó con una excepción"); col = Theme::ERR; break;
    case S::Watchdog: snprintf(buf, sizeof buf, "WATCHDOG: detenido tras %u s", (unsigned)(PySandbox::WATCHDOG_MS / 1000)); col = Theme::ERR; break;
    case S::Stopped:  snprintf(buf, sizeof buf, "Detenido por el usuario (AC)"); col = Theme::WARN; break;
    case S::Overflow: snprintf(buf, sizeof buf, "ERROR - demasiada salida, script detenido"); col = Theme::ERR; break;
    case S::NoMem:    snprintf(buf, sizeof buf, "ERROR - sin memoria"); col = Theme::ERR; break;
    case S::Failed:   snprintf(buf, sizeof buf, "ERROR - no se pudo iniciar Python"); col = Theme::ERR; break;
    default:          snprintf(buf, sizeof buf, "Preparando..."); col = Theme::MUTED; break;
  }
  if (!force && statusShown_ == buf) return;
  statusShown_ = buf;
  gfx().fillRect(0, STATUS_Y, Display::W, STATUS_H, Theme::PANEL);
  gfx().text(6, STATUS_Y + 3, buf, 1, col, Theme::PANEL, Align::Left, 0, true, Display::W - 12);
}

void PythonApp::drawConsole(bool force) {
  if (force || pySandbox.outVersion() != seenVersion_) {
    seenVersion_ = pySandbox.outVersion();
    buildRows();
  }
  int total = rows_.size();
  int maxScroll = total > ROWS ? total - ROWS : 0;
  if (scroll_ > maxScroll) scroll_ = maxScroll;
  int end = total - scroll_;
  int first = end - ROWS;
  if (first < 0) first = 0;
  bool running = !pySandbox.finished();
  for (int r = 0; r < ROWS; ++r) {
    int i = first + r;
    const String& t = i < end ? rows_[i].text : String();
    uint16_t c = i < end ? rows_[i].color : Theme::TEXT;
    // cursor parpadeante tras la última fila mientras el script corre
    bool cursorRow = running && scroll_ == 0 && i == end && cursorOn_;
    String key = cursorRow ? String("\x7f\x7e") : t;
    if (!force && r < (int)shown_.size() && shown_[r] == key && shownColor_[r] == c) continue;
    int16_t y = CON_Y + r * ROW_H;
    gfx().fillRect(0, y, Display::W, ROW_H, Theme::BG);
    if (t.length()) gfx().text(6, y + 1, t.c_str(), 1, c, Theme::BG, Align::Left, 0, false, Display::W - 8);
    if (cursorRow) gfx().fillRect(6, y + 1, 5, 8, Theme::TEXT);
    if (r < (int)shown_.size()) { shown_[r] = key; shownColor_[r] = c; }
  }
}

void PythonApp::drawConsoleFooter() {
  if (pySandbox.finished()) gfx().footer("EXE repetir   ▲▼ desplazar   ◄/AC volver");
  else gfx().footer("AC detiene el script");
}

void PythonApp::onTick(uint32_t now) {
  pySandbox.tick();
  // Juego (scicalc.pantalla): la zona del script es suya; aquí solo se pintan
  // sus órdenes. Al terminar se vuelve a la consola (errores, print...).
  if (pyGfx.active()) {
    if (canDraw()) pyGfx.drain(gfx(), sd(), 25);
    if (!pySandbox.alive()) {
      pyGfx.end();
      stateShown_ = -1;
      requestRedraw();
    }
    return;
  }
  if (!console_ || viewer_.isOpen() || !canDraw()) return;
  if ((int32_t)(now - nextPaint_) < 0) return;
  nextPaint_ = now + 100;                         // 10 repintados por segundo como mucho
  cursorOn_ = (now / 400) % 2;
  int st = (int)pySandbox.state();
  drawStatus(false);
  drawConsole(false);
  if (st != stateShown_) { stateShown_ = st; drawConsoleFooter(); }
}

// ---- Teclas -------------------------------------------------------------------------------
void PythonApp::onKey(const KeyEvent& ev) {
  if (viewer_.isOpen()) {
    if (viewer_.onKey(ev)) {
      viewer_.close();
      setTitle(title());
      requestRedraw();
    }
    return;
  }

  if (console_) {
    if (!pySandbox.finished()) {                 // corriendo
      if (ev.key == Key::AC) pySandbox.stop();
      else if (pyGfx.active()) pyGfx.onKey(ev);  // un juego: las teclas son suyas
      else if (ev.key == Key::Del) pySandbox.stop();
      return;
    }
    switch (ev.key) {
      case Key::AC: case Key::Del: case Key::Left:
        closeConsole();
        break;
      case Key::Exe:
        start(script_);
        break;
      case Key::Up:
        scroll_++;
        drawConsole(false);
        break;
      case Key::Down:
        if (scroll_ > 0) { scroll_--; drawConsole(false); }
        break;
      default:
        break;
    }
    return;
  }

  if (!st().sdMounted) return;
  if (ev.key == Key::AC) {
    if (browser_.goUp()) { browser_.draw("No hay scripts .py aquí"); drawFooter(); }
    return;
  }
  if (ev.key == Key::Exe && ev.shift) {           // ver el código (el editor llegará)
    String p = browser_.selectedPath();
    uint32_t size;
    if (Path::ext(p) == ".py" && sd().stat(p, size) == 1 && viewer_.open(p)) {
      setTitle(Path::name(p).c_str());
      requestRedraw();
    }
    return;
  }
  if (browser_.key(ev) == FolderBrowser::Result::OpenFile) start(browser_.selectedPath());
}
