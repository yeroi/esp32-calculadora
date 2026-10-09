// =============================================================================
//  Dialog.cpp
// =============================================================================
#include "Dialog.h"

namespace {
  constexpr int16_t BOX_X = 18, BOX_W = Display::W - 2 * BOX_X;
  constexpr int16_t TITLE_H = 21, LINE_H = 12, BTN_H = 16;
  constexpr int16_t PAD = 8;
  constexpr size_t  MAX_LINES = 12;     // lo que cabe en el cuerpo (218 px)
}

DialogManager::DialogManager(Display& d) : gfx_(d) {}

bool DialogManager::begin() {
  lock_ = xSemaphoreCreateMutex();
  uiTask_ = xTaskGetCurrentTaskHandle();   // begin() se llama desde la UI
  return lock_ != nullptr;
}

uint16_t DialogManager::colorFor(const String& t) {
  return (t == "PERMISO" || t == "Desinstalar" || t == "Modo examen") ? Theme::WARN
                                                                       : Theme::ACCENT;
}

void DialogManager::push(Dialog&& d) {
  if (d.lines.size() > MAX_LINES) d.lines.resize(MAX_LINES);
  queue_.push_back(std::move(d));
}

void DialogManager::ask(const char* title, std::vector<String> lines, DlgCallback cb,
                        bool allowAll) {
  Dialog d;
  d.title = title;
  d.lines = std::move(lines);
  d.cb = std::move(cb);
  d.allowAll = allowAll;
  push(std::move(d));
}

void DialogManager::info(const char* title, std::vector<String> lines, DlgCallback cb) {
  Dialog d;
  d.title = title;
  d.lines = std::move(lines);
  d.cb = std::move(cb);
  d.info = true;
  push(std::move(d));
}

DlgAnswer DialogManager::askBlocking(const char* title, std::vector<String> lines,
                                     bool allowAll, uint32_t timeoutMs) {
  // Desde la propia UI esto sería un interbloqueo: nadie dibujaría el diálogo.
  if (xTaskGetCurrentTaskHandle() == uiTask_ || !lock_) return DlgAnswer::No;

  auto remote = std::make_shared<Remote>();
  remote->done = xSemaphoreCreateBinary();
  if (!remote->done) return DlgAnswer::No;

  Dialog d;
  d.title = title;
  d.lines = std::move(lines);
  d.allowAll = allowAll;
  d.remote = remote;
  // El callback se ejecuta en la UI: guarda la respuesta y despierta a la tarea
  d.cb = [remote](DlgAnswer a) {
    remote->answer = a;
    xSemaphoreGive(remote->done);
  };

  xSemaphoreTake(lock_, portMAX_DELAY);
  incoming_.push_back(std::move(d));
  xSemaphoreGive(lock_);

  if (xSemaphoreTake(remote->done, pdMS_TO_TICKS(timeoutMs)) == pdTRUE) return remote->answer;
  remote->expired = true;                 // la UI lo retirará en service()
  return DlgAnswer::No;
}

bool DialogManager::service() {
  bool changed = false;
  const bool hadVisible = !queue_.empty();

  // 1) Peticiones de otras tareas
  if (lock_ && xSemaphoreTake(lock_, 0) == pdTRUE) {
    while (!incoming_.empty()) {
      push(std::move(incoming_.front()));
      incoming_.pop_front();
    }
    xSemaphoreGive(lock_);
  }
  // 2) Retira las que caducaron (la tarea que preguntó ya no espera)
  for (auto it = queue_.begin(); it != queue_.end();) {
    if (it->remote && it->remote->expired) {
      if (it == queue_.begin()) changed = true;
      it = queue_.erase(it);
    } else {
      ++it;
    }
  }
  if (!hadVisible && !queue_.empty()) changed = true;
  return changed;
}

bool DialogManager::handleKey(const KeyEvent& ev) {
  if (queue_.empty()) return false;
  Dialog& d = queue_.front();
  DlgAnswer ans;
  if (d.info) {
    if (ev.key != Key::Exe && ev.key != Key::AC && ev.key != Key::Del && ev.key != Key::Left)
      return false;
    ans = DlgAnswer::Yes;
  } else if (ev.key == Key::Exe) {
    ans = (ev.shift && d.allowAll) ? DlgAnswer::YesAll : DlgAnswer::Yes;
  } else if (ev.key == Key::AC || ev.key == Key::Del) {
    ans = DlgAnswer::No;
  } else {
    return false;
  }
  // Se saca de la cola ANTES del callback: el callback puede abrir otro diálogo
  Dialog closed = std::move(d);
  queue_.pop_front();
  if (closed.cb) closed.cb(ans);
  return true;
}

void DialogManager::draw() {
  if (queue_.empty()) return;
  const Dialog& d = queue_.front();
  const uint16_t col = colorFor(d.title);
  const int16_t n = static_cast<int16_t>(d.lines.size());
  const int16_t h = TITLE_H + PAD + n * LINE_H + PAD + BTN_H + PAD;
  const int16_t y = Display::BODY_Y + max<int16_t>(4, (Display::BODY_H - h) / 2);

  // Marco de 2 px del color del diálogo, cabecera y cuerpo
  gfx_.fillRoundRect(BOX_X, y, BOX_W, h, 5, col);
  gfx_.fillRect(BOX_X + 2, y + TITLE_H, BOX_W - 4, h - TITLE_H - 2, Theme::MODAL_BG);
  gfx_.text(BOX_X + PAD, y + 3, d.title.c_str(), 2, Theme::BG, col, Align::Left, 0,
            false, BOX_W - 2 * PAD);

  // Líneas: las que empiezan por dos espacios (rutas, datos) van en negrita
  int16_t ly = y + TITLE_H + PAD;
  for (const String& ln : d.lines) {
    bool bold = ln.startsWith("  ");
    gfx_.text(BOX_X + PAD + 2, ly, ln.c_str(), 1, Theme::TEXT, Theme::MODAL_BG, Align::Left,
              0, bold, BOX_W - 2 * PAD - 4);
    ly += LINE_H;
  }

  // Botones
  struct Btn { const char* k; const char* label; uint16_t c; };
  Btn btns[3];
  uint8_t nb = 0;
  if (d.info) {
    btns[nb++] = {"EXE", "Aceptar", Theme::OK};
  } else {
    btns[nb++] = {"EXE", "Sí", Theme::OK};
    if (d.allowAll) btns[nb++] = {"SHIFT+EXE", "Sí a todo", Theme::SHIFT};
    btns[nb++] = {"AC", "No", Theme::ERR};
  }
  int16_t bx = BOX_X + PAD;
  const int16_t by = y + h - PAD - BTN_H;
  for (uint8_t i = 0; i < nb; ++i) {
    String t = String(btns[i].k) + "  " + btns[i].label;
    int16_t w = Display::textWidth(t.c_str(), 1) + 14;
    gfx_.fillRoundRect(bx, by, w, BTN_H, 4, btns[i].c);
    gfx_.text(bx, by + 4, t.c_str(), 1, Theme::BG, btns[i].c, Align::Center, w, true);
    bx += w + 6;
  }
}
