// =============================================================================
//  T9Input.cpp  (ver T9Input.h)
// =============================================================================
#include "T9Input.h"

namespace {
constexpr uint32_t WAIT_MS = 1000;
}

const char* T9Input::lettersFor(Key k) {
  switch (k) {
    case Key::N1: return ".,-_!?@1";
    case Key::N2: return "abc2";
    case Key::N3: return "def3";
    case Key::N4: return "ghi4";
    case Key::N5: return "jkl5";
    case Key::N6: return "mno6";
    case Key::N7: return "pqrs7";
    case Key::N8: return "tuv8";
    case Key::N9: return "wxyz9";
    case Key::N0: return " 0";
    default: return nullptr;
  }
}

void T9Input::begin(const String& text, Mode mode, uint8_t maxLen) {
  text_ = text;
  mode_ = mode;
  max_ = maxLen;
  last_ = Key::None;
  pending_ = false;
}

T9Input::Result T9Input::key(const KeyEvent& ev) {
  uint32_t now = millis();
  if (ev.ch) {                                                 // teclado del PC: tal cual
    bool ok = mode_ != Mode::Ip || (ev.ch >= '0' && ev.ch <= '9') || ev.ch == '.';
    if (ok && text_.length() < max_) {
      if (ev.ch < 0x80) {
        text_ += (char)ev.ch;
      } else {                                                 // ñ, á... en UTF-8
        char u[4] = {0};
        if (ev.ch < 0x800) { u[0] = 0xC0 | (ev.ch >> 6); u[1] = 0x80 | (ev.ch & 0x3F); }
        else { u[0] = 0xE0 | (ev.ch >> 12); u[1] = 0x80 | ((ev.ch >> 6) & 0x3F); u[2] = 0x80 | (ev.ch & 0x3F); }
        text_ += u;
      }
    }
    last_ = Key::None;
    pending_ = false;
    return Result::Editing;
  }
  switch (ev.key) {
    case Key::Exe: return Result::Ok;
    case Key::AC:  return Result::Cancel;
    case Key::Del:
      if (text_.length()) text_.remove(text_.length() - 1);
      last_ = Key::None;
      pending_ = false;
      return Result::Editing;
    case Key::Right:
      last_ = Key::None;
      pending_ = false;
      return Result::Editing;
    default: break;
  }
  const char* letters = lettersFor(ev.key);
  if (mode_ == Mode::Ip) {
    if (text_.length() >= max_) return Result::Editing;
    if (letters) text_ += letters[strlen(letters) - 1];       // el número
    else if (ev.key == Key::Dot) text_ += '.';
    return Result::Editing;
  }
  if (ev.key == Key::Dot) {
    if (text_.length() < max_) text_ += '.';
    last_ = Key::None;
    pending_ = false;
    return Result::Editing;
  }
  if (!letters) return Result::Editing;
  if (ev.key == last_ && pending_ && now - t_ < WAIT_MS && text_.length()) {
    i_ = (i_ + 1) % strlen(letters);                          // misma tecla: otra letra
    text_.remove(text_.length() - 1);
  } else if (text_.length() >= max_) {
    return Result::Editing;
  } else {
    i_ = 0;
  }
  char c = letters[i_];
  if (ev.shift || (text_.length() == 0 && mode_ == Mode::T9)) c = toupper(c);
  text_ += c;
  last_ = ev.key;
  t_ = now;
  pending_ = true;
  return Result::Editing;
}

bool T9Input::tick(uint32_t nowMs) {
  if (pending_ && nowMs - t_ >= WAIT_MS) {
    pending_ = false;
    return true;
  }
  return false;
}

String T9Input::shown() const {
  String s;
  if (mode_ == Mode::Pass) {
    size_t n = text_.length();
    for (size_t i = 0; i < n; i++) {
      if (i + 1 == n && pending_) s += text_[i];              // la letra que se escribe
      else s += "*";
    }
  } else {
    s = text_;
  }
  if (!pending_) s += "_";
  return s;
}

const char* T9Input::help() const {
  if (mode_ == Mode::Ip) return "Números y . · DEL borra · EXE ok · AC cancela";
  return "2abc..9wxyz 0=esp 1=.,-_!?@ · SHIFT=MAYÚS";
}
