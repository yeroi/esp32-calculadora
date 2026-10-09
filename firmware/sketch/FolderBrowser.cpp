// =============================================================================
//  FolderBrowser.cpp
// =============================================================================
#include "FolderBrowser.h"

namespace {
  constexpr int16_t PATH_Y = Display::BODY_Y;          // barra de ruta
  constexpr int16_t PATH_H = 15;
  constexpr int16_t LIST_Y = PATH_Y + PATH_H + 3;
  constexpr int16_t ROW_STEP = 25, ROW_H = 22;
  constexpr int16_t ROW_X = 6, ROW_W = Display::W - 12;
  constexpr int16_t ICON_X = ROW_X + 6, NAME_X = ICON_X + 26;
}

void FolderBrowser::refresh() {
  if (!sd_.isDir(cwd_)) cwd_ = "/";
  ok_ = sd_.listDir(cwd_, items_, onlyPy_, &truncated_);
  hasUp_ = cwd_ != "/";
  list_.reset(items_.size() + (hasUp_ ? 1 : 0), ROWS);
}

bool FolderBrowser::goUp() {
  if (cwd_ == "/") return false;
  String old = Path::name(cwd_);
  cwd_ = Path::parent(cwd_);
  list_.sel = 0;
  list_.top = 0;
  refresh();
  // Deja seleccionada la carpeta de la que venimos (como el simulador)
  for (size_t i = 0; i < items_.size(); ++i) {
    if (items_[i].dir && items_[i].name == old) {
      list_.select(i + (hasUp_ ? 1 : 0));
      break;
    }
  }
  return true;
}

String FolderBrowser::selectedPath() const {
  if (list_.count == 0 || isUp(list_.sel)) return "";
  return Path::join(cwd_, entry(list_.sel).name);
}

FolderBrowser::Result FolderBrowser::key(const KeyEvent& ev) {
  const uint16_t old = list_.sel;
  switch (ev.key) {
    case Key::Up:
    case Key::Down: {
      if (!list_.count) return Result::None;
      bool scrolled = list_.move(ev.key == Key::Up ? -1 : +1);
      if (scrolled) drawRows();
      else { drawRow(old); drawRow(list_.sel); }
      return Result::Moved;
    }
    case Key::Left:
    case Key::Del:
      if (!goUp()) return Result::None;
      draw(emptyMsg_);
      return Result::Changed;
    case Key::Exe:
    case Key::Right: {
      if (!list_.count) return Result::None;
      if (isUp(list_.sel)) {
        goUp();
        draw(emptyMsg_);
        return Result::Changed;
      }
      const DirEntry& e = entry(list_.sel);
      if (e.dir) {
        cwd_ = Path::join(cwd_, e.name);
        list_.sel = 0;
        list_.top = 0;
        refresh();
        draw(emptyMsg_);
        return Result::Changed;
      }
      return Result::OpenFile;
    }
    default:
      return Result::None;
  }
}

// ---- Dibujo -------------------------------------------------------------------
void FolderBrowser::draw(const char* emptyMsg) {
  emptyMsg_ = emptyMsg;
  drawPathBar();
  drawRows();
}

void FolderBrowser::drawPathBar() {
  gfx_.fillRect(0, PATH_Y, Display::W, PATH_H, Theme::PATH_BG);
  char cnt[24];
  snprintf(cnt, sizeof cnt, "%u elementos%s", (unsigned)items_.size(), truncated_ ? "+" : "");
  int16_t cw = Display::textWidth(cnt, 1);
  gfx_.text(Display::W - 7 - cw, PATH_Y + 4, cnt, 1, Theme::MUTED, Theme::PATH_BG);
  gfx_.textBold(7, PATH_Y + 4, cwd_.c_str(), 1, Theme::ACCENT, Theme::PATH_BG,
                Display::W - 7 - cw - 14);
}

void FolderBrowser::drawRows() {
  gfx_.fillRect(0, LIST_Y, Display::W, ROWS * ROW_STEP, Theme::BG);
  if (!ok_) {
    gfx_.text(0, 100, "No se puede leer la MicroSD", 2, Theme::ERR, Theme::BG, Align::Center,
              Display::W);
    return;
  }
  if (list_.count == 0) {
    gfx_.text(0, 100, emptyMsg_, 2, Theme::MUTED, Theme::BG, Align::Center, Display::W);
    return;
  }
  for (uint16_t i = list_.top; i < list_.count && i < list_.top + ROWS; ++i) drawRow(i);
}

void FolderBrowser::drawRow(uint16_t i) {
  if (!list_.visible(i) || i >= list_.count) return;
  const int16_t y = LIST_Y + (i - list_.top) * ROW_STEP;
  const bool hi = i == list_.sel;
  const uint16_t bg = hi ? Theme::ACCENT : Theme::PANEL;
  gfx_.fillRoundRect(ROW_X, y, ROW_W, ROW_H, 4, bg);

  if (isUp(i)) {
    drawIcon(FileKind::Up, ICON_X, y + 4);
    gfx_.textBold(NAME_X, y + 7, "..", 1, Theme::TEXT, bg);
    return;
  }
  const DirEntry& e = entry(i);
  drawIcon(Path::kind(e.name, e.dir), ICON_X, y + 4);
  String name = e.dir ? e.name + "/" : e.name;
  int16_t sizeW = 0;
  if (!e.dir) {
    String sz = humanSize(e.size);
    sizeW = Display::textWidth(sz.c_str(), 1);
    gfx_.text(ROW_X + ROW_W - 8 - sizeW, y + 7, sz.c_str(), 1, hi ? Theme::TEXT : Theme::MUTED, bg);
  }
  gfx_.textBold(NAME_X, y + 7, name.c_str(), 1, Theme::TEXT, bg,
                ROW_X + ROW_W - 8 - sizeW - 10 - NAME_X);
}

// Iconos de 20x14 px, como draw_icon() del simulador
void FolderBrowser::drawIcon(FileKind k, int16_t x, int16_t y) {
  if (k == FileKind::Dir || k == FileKind::Up) {
    gfx_.fillRoundRect(x, y, 8, 4, 1, Theme::ICON_DIR);          // pestaña
    gfx_.fillRoundRect(x, y + 2, 18, 12, 2, Theme::ICON_DIR);    // cuerpo
    if (k == FileKind::Up) gfx_.fillTriangle(x + 9, y + 4, x + 5, y + 11, x + 13, y + 11, Theme::BG);
    return;
  }
  uint16_t c;
  const char* tag;
  switch (k) {
    case FileKind::Py:  c = Theme::ICON_PY;  tag = "PY";  break;
    case FileKind::Img: c = Theme::ICON_IMG; tag = "IMG"; break;
    case FileKind::Txt: c = Theme::ICON_TXT; tag = "TXT"; break;
    default:            c = Theme::ICON_BIN; tag = "BIN"; break;
  }
  gfx_.fillRoundRect(x, y, 20, 14, 2, c);
  gfx_.text(x, y + 3, tag, 1, Theme::WHITE, c, Align::Center, 20);
}
