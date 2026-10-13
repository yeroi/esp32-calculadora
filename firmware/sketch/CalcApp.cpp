// =============================================================================
//  CalcApp.cpp  —  Calculadora científica (ver CalcApp.h)
// -----------------------------------------------------------------------------
//  Pantalla (320 x 240):
//     barra de estado                                  (0..21)
//     operaciones anteriores, en gris, de abajo arriba (hasta y = 160)
//     ─────────────────────────────────────────────    (y = 166)
//     expresión actual con cursor (tamaño 2)           (y = 174)
//     resultado a la derecha (tamaño 3)                (y = 198)
//     ayuda                                            (y = 228)
// =============================================================================
#include "CalcApp.h"
#include "CalcEngine.h"

namespace {

constexpr int16_t LINE_Y = 166;
constexpr int16_t EXPR_Y = 174;
constexpr int16_t RES_Y = 198;
constexpr int16_t MARGIN = 10;
constexpr int16_t EXPR_CHARS = (Display::W - 2 * MARGIN) / 12 - 1;   // tamaño 2: 12 px

const char* const DIGITS[] = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9"};

const char* digitOf(Key k) {
  switch (k) {
    case Key::N0: return DIGITS[0];
    case Key::N1: return DIGITS[1];
    case Key::N2: return DIGITS[2];
    case Key::N3: return DIGITS[3];
    case Key::N4: return DIGITS[4];
    case Key::N5: return DIGITS[5];
    case Key::N6: return DIGITS[6];
    case Key::N7: return DIGITS[7];
    case Key::N8: return DIGITS[8];
    case Key::N9: return DIGITS[9];
    default: return nullptr;
  }
}

// Token de cada tecla (KEY_TOKENS / SHIFT_TOKENS del simulador)
const char* tokenOf(Key k, bool shift) {
  if (shift) {
    switch (k) {
      case Key::Sin: return "asin(";
      case Key::Cos: return "acos(";
      case Key::Tan: return "atan(";
      case Key::Pow: return "²";
      case Key::Ln: return "log(";
      case Key::Sqrt: return "π";
      case Key::LParen: return "e";
      case Key::RParen: return "Ans";
      case Key::Div: return "!";
      case Key::Dot: return "E";
      default: break;
    }
  }
  switch (k) {
    case Key::Add: return "+";
    case Key::Sub: return "−";
    case Key::Mul: return "×";
    case Key::Div: return "÷";
    case Key::Pow: return "^";
    case Key::LParen: return "(";
    case Key::RParen: return ")";
    case Key::Sin: return "sin(";
    case Key::Cos: return "cos(";
    case Key::Tan: return "tan(";
    case Key::Ln: return "ln(";
    case Key::Sqrt: return "√(";
    case Key::Dot: return ".";
    default: return nullptr;
  }
}

bool isOp(const char* t) {
  static const char* const OPS[] = {"+", "−", "×", "÷", "^", "²", "!"};
  for (const char* o : OPS)
    if (strcmp(o, t) == 0) return true;
  return false;
}

// Salta n caracteres UTF-8
const char* skipChars(const char* s, size_t n) {
  while (*s && n) {
    s++;
    while ((*s & 0xC0) == 0x80) s++;
    n--;
  }
  return s;
}

}  // namespace

String CalcApp::joined(size_t upto) const {
  String s;
  for (size_t i = 0; i < upto && i < toks_.size(); i++) s += toks_[i];
  return s;
}

void CalcApp::insert(const char* tok) {
  if (toks_.empty() && isOp(tok) && !history_.empty()) {
    toks_.push_back("Ans");                    // 5 EXE  + 3  ->  Ans+3
    cur_ = 1;
  }
  toks_.insert(toks_.begin() + cur_, tok);
  cur_++;
  recall_ = -1;
}

void CalcApp::run() {
  if (toks_.empty()) {
    if (history_.empty()) return;
    toks_ = history_.back().toks;              // EXE solo: repite la última
  }
  String expr = joined(toks_.size());
  double v = 0;
  Calc::Err e = Calc::evaluate(expr.c_str(), ans_, st().degrees, v);
  Entry en;
  en.toks = toks_;
  if (e == Calc::Err::None) {
    ans_ = v;
    en.result = Calc::format(v);
    en.error = false;
  } else {
    en.result = e == Calc::Err::Math ? "Math ERROR" : "Syntax ERROR";
    en.error = true;
  }
  history_.push_back(en);
  if (history_.size() > 30) history_.erase(history_.begin());
  toks_.clear();
  cur_ = 0;
  recall_ = -1;
}

void CalcApp::onKey(const KeyEvent& ev) {
  const char* d = digitOf(ev.key);
  if (d) {
    insert(d);
  } else if (ev.shift && ev.key == Key::AC) {
    st().degrees = !st().degrees;              // la barra de estado se actualiza sola
    return;
  } else if (const char* t = tokenOf(ev.key, ev.shift)) {
    insert(t);
  } else {
    switch (ev.key) {
      case Key::Exe:
        run();
        break;
      case Key::Del:
        if (cur_ > 0) toks_.erase(toks_.begin() + --cur_);
        break;
      case Key::AC:
        if (!toks_.empty()) { toks_.clear(); cur_ = 0; }
        else history_.clear();
        recall_ = -1;
        break;
      case Key::Left:
        if (cur_ > 0) cur_--;
        break;
      case Key::Right:
        if (cur_ < toks_.size()) cur_++;
        break;
      case Key::Up:
        if (history_.empty()) return;
        recall_ = recall_ < 0 ? (int)history_.size() - 1 : max(0, recall_ - 1);
        toks_ = history_[recall_].toks;
        cur_ = toks_.size();
        break;
      case Key::Down:
        if (recall_ < 0) return;
        recall_++;
        if (recall_ >= (int)history_.size()) { recall_ = -1; toks_.clear(); }
        else toks_ = history_[recall_].toks;
        cur_ = toks_.size();
        break;
      default:
        return;
    }
  }
  blinkOn_ = true;
  blinkT_ = millis();
  requestRedraw();
}

void CalcApp::draw() {
  Display& g = gfx();
  bool typing = !toks_.empty() || recall_ >= 0 || history_.empty();
  size_t past = typing ? history_.size() : history_.size() - 1;

  // Operaciones anteriores: la más reciente abajo
  int16_t y = LINE_Y - 34;
  for (size_t i = past; i-- > 0 && y >= Display::BODY_Y + 2; y -= 34) {
    const Entry& e = history_[i];
    String ex;
    for (const char* t : e.toks) ex += t;
    g.text(MARGIN, y, ex.c_str(), 1, Theme::MUTED, Theme::BG, Align::Left, 0, false,
           Display::W - 2 * MARGIN);
    g.text(0, y + 12, e.result.c_str(), 2, e.error ? Theme::HIST_ERR : Theme::HIST, Theme::BG,
           Align::Right, Display::W - MARGIN);
  }
  g.hLine(MARGIN, LINE_Y, Display::W - 2 * MARGIN, Theme::PANEL);

  if (!typing) {
    const Entry& e = history_.back();
    String ex;
    for (const char* t : e.toks) ex += t;
    g.text(MARGIN, EXPR_Y, ex.c_str(), 2, Theme::TEXT, Theme::BG, Align::Left, 0, false,
           Display::W - 2 * MARGIN);
    g.text(0, RES_Y, e.result.c_str(), 3, e.error ? Theme::ERR : Theme::TEXT, Theme::BG,
           Align::Right, Display::W - MARGIN, true);
    cursorX_ = -1;
  } else {
    if (history_.empty() && toks_.empty()) {
      g.text(0, 70, "Escribe una operación y pulsa EXE", 1, Theme::MUTED, Theme::BG,
             Align::Center, Display::W);
      g.text(0, 86, "ej.  2sin(30)+√(16)", 1, Theme::MUTED, Theme::BG, Align::Center,
             Display::W);
      g.text(0, 102, "SHIFT = funciones amarillas", 1, Theme::MUTED, Theme::BG, Align::Center,
             Display::W);
    }
    drawInput();
  }
  g.footer("SHIFT+AC DEG/RAD  ↑ recuperar  DEL borra  AC limpia");
}

// La expresión, desplazada si no cabe para que el cursor siempre se vea
void CalcApp::drawInput() {
  Display& g = gfx();
  String full = joined(toks_.size());
  size_t curChars = Display::utf8Length(joined(cur_).c_str());
  size_t off = curChars > (size_t)EXPR_CHARS ? curChars - EXPR_CHARS : 0;
  const char* vis = skipChars(full.c_str(), off);
  g.fillRect(0, EXPR_Y - 2, Display::W, 20, Theme::BG);
  g.text(MARGIN, EXPR_Y, vis, 2, Theme::TEXT, Theme::BG, Align::Left, 0, false,
         Display::W - 2 * MARGIN);
  cursorX_ = MARGIN + (int16_t)(curChars - off) * 12;
  drawCursor(blinkOn_);
}

void CalcApp::drawCursor(bool on) {
  if (cursorX_ < 0) return;
  gfx().fillRect(cursorX_ - 1, EXPR_Y - 2, 2, 20, on ? Theme::ACCENT : Theme::BG);
}

void CalcApp::onTick(uint32_t nowMs) {
  if (cursorX_ < 0 || !canDraw()) return;
  if (nowMs - blinkT_ >= 500) {                  // parpadeo del cursor
    blinkT_ = nowMs;
    blinkOn_ = !blinkOn_;
    drawCursor(blinkOn_);
  }
}
