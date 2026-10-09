// =============================================================================
//  PySandbox.cpp
// =============================================================================
#include "PySandbox.h"
#include <errno.h>
#include <esp_heap_caps.h>
#include <esp_system.h>
#include "config.h"
#include "src/mpy/port/scicalc_py.h"

PySandbox pySandbox;

namespace {
constexpr uint32_t STACK_BYTES = 16 * 1024;      // pila de la tarea del script
constexpr size_t   HEAP_MAX = 112 * 1024;        // tope del heap de MicroPython
constexpr size_t   HEAP_MIN = 24 * 1024;
constexpr size_t   RESERVE = 36 * 1024;          // lo que se deja al sistema

const char* permText(const char* op) {
  if (!strcmp(op, "write"))  return "quiere ESCRIBIR en el archivo";
  if (!strcmp(op, "remove")) return "quiere BORRAR el archivo";
  if (!strcmp(op, "rename")) return "quiere RENOMBRAR el archivo";
  if (!strcmp(op, "mkdir"))  return "quiere CREAR la carpeta";
  if (!strcmp(op, "rmdir"))  return "quiere BORRAR la carpeta";
  return op;
}
}  // namespace

void PySandbox::begin(Storage& sd, DialogManager& dlg) {
  sd_ = &sd;
  dlg_ = &dlg;
  mutex_ = xSemaphoreCreateMutex();
}

// ---- Arranque ---------------------------------------------------------------------
bool PySandbox::start(const String& path, const std::vector<String>& args) {
  if (task_ || !mutex_) return false;
  path_ = path;
  name_ = Path::name(path);
  cwd_ = Path::parent(path);
  args_.clear();
  args_.push_back(name_);
  for (const String& a : args) args_.push_back(a);

  xSemaphoreTake(mutex_, portMAX_DELAY);
  lines_.clear();
  cur_ = "";
  totalLines_ = 0;
  outVersion_ = outVersion_ + 1;
  xSemaphoreGive(mutex_);

  granted_.clear();
  grantAll_ = false;
  stopReq_ = false;
  pausedMs_ = 0;
  askSince_ = 0;
  heapSize_ = 0;
  t0_ = millis();
  aliveMs_ = t0_;
  endMs_ = 0;
  state_ = State::Running;

  // Core 1 (como la UI) y prioridad 1: el loop de Arduino espera casi siempre
  // en la cola del teclado, así que el script se queda con la CPU, pero una
  // tecla (AC) se atiende al momento.
  if (xTaskCreatePinnedToCore(taskEntry, "python", STACK_BYTES, this, 1, &task_, CORE_UI) != pdPASS) {
    task_ = nullptr;
    pushLine("\x01No se pudo crear la tarea de Python (sin memoria).");
    state_ = State::Failed;
    endMs_ = millis();
    return false;
  }
  return true;
}

void PySandbox::taskEntry(void* arg) { static_cast<PySandbox*>(arg)->run(); }

void PySandbox::run() {
  volatile int top = 0;                       // cima aproximada de esta pila

  // Heap de MicroPython: lo más grande que quepa dejando margen al sistema
  size_t largest = heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);
  size_t want = largest > RESERVE ? largest - RESERVE : 0;
  if (want > HEAP_MAX) want = HEAP_MAX;
  want &= ~(size_t)15;
  if (want >= HEAP_MIN) heap_ = malloc(want);
  State end;
  if (!heap_) {
    pushLine("\x01No hay memoria libre para Python.");
    end = State::NoMem;
  } else {
    heapSize_ = want;
    Serial.printf("[python] %s  (heap %u KB)\n", path_.c_str(), (unsigned)(want / 1024));
    int r = scpy_run(path_.c_str(), heap_, heapSize_, (void*)&top, STACK_BYTES - 512);
    switch (r) {
      case SCPY_OK:          end = stopReq_ ? stopReason_ : State::Ok; break;
      case SCPY_INTERRUPTED: end = stopReq_ ? stopReason_ : State::Stopped; break;
      case SCPY_NOMEM:       end = State::NoMem; break;
      default:               end = State::Error; break;
    }
    free(heap_);
    heap_ = nullptr;
  }

  xSemaphoreTake(mutex_, portMAX_DELAY);
  if (cur_.length()) { lines_.push_back(cur_); cur_ = ""; }
  outVersion_ = outVersion_ + 1;
  xSemaphoreGive(mutex_);

  endMs_ = millis();
  state_ = end;
  Serial.printf("[python] fin: estado %d, %u ms\n", (int)end, (unsigned)elapsedMs());
  task_ = nullptr;
  vTaskDelete(nullptr);
}

// ---- Parada y watchdog (desde la UI) -----------------------------------------------
void PySandbox::stop() {
  if (!task_ || stopReq_) return;
  stopReason_ = State::Stopped;
  stopReq_ = true;
  nextKick_ = 0;
}

void PySandbox::tick() {
  if (!task_) return;
  uint32_t now = millis();
  if (!stopReq_ && state_ == State::Running && now - aliveMs_ > WATCHDOG_MS) {
    stopReason_ = State::Watchdog;
    stopReq_ = true;
    nextKick_ = 0;
  }
  // Se repite: el script puede tragarse un KeyboardInterrupt con "except:"
  if (stopReq_ && (int32_t)(now - nextKick_) >= 0) {
    scpy_interrupt();
    nextKick_ = now + 150;
  }
}

uint32_t PySandbox::elapsedMs() const {
  uint32_t end = finished() ? endMs_ : millis();
  uint32_t paused = pausedMs_;
  if (state_ == State::Asking) paused += millis() - askSince_;
  uint32_t e = end - t0_;
  return e > paused ? e - paused : 0;
}

// ---- Salida ---------------------------------------------------------------------------
void PySandbox::pushLine(const String& l) {
  // (con el mutex tomado, salvo en start())
  lines_.push_back(l);
  if (lines_.size() > MAX_LINES) lines_.erase(lines_.begin(), lines_.begin() + (lines_.size() - MAX_LINES));
  outVersion_ = outVersion_ + 1;
  if (++totalLines_ > MAX_TOTAL_LINES && !stopReq_) {
    stopReason_ = State::Overflow;
    stopReq_ = true;
    nextKick_ = 0;
  }
}

void PySandbox::out(const char* s, size_t n) {
  xSemaphoreTake(mutex_, portMAX_DELAY);
  for (size_t i = 0; i < n; ++i) {
    char c = s[i];
    if (c == '\r') continue;
    if (c == '\n' || cur_.length() >= 1000) {
      pushLine(cur_);
      cur_ = "";
      if (c == '\n') continue;
    }
    cur_ += c;
  }
  outVersion_ = outVersion_ + 1;
  xSemaphoreGive(mutex_);
}

void PySandbox::copyLines(std::vector<String>& out) {
  out.clear();
  if (!mutex_) return;
  xSemaphoreTake(mutex_, portMAX_DELAY);
  out = lines_;
  if (cur_.length()) out.push_back(cur_);
  xSemaphoreGive(mutex_);
}

// ---- Rutas: siempre dentro de la SD ------------------------------------------------------
int PySandbox::resolve(const char* in, char* out, size_t cap) {
  String p(in ? in : "");
  p.replace('\\', '/');
  String full = p.startsWith("/") ? p : cwd_ + "/" + p;
  std::vector<String> parts;
  int start = 0;
  while (start <= (int)full.length()) {
    int end = full.indexOf('/', start);
    if (end < 0) end = full.length();
    String seg = full.substring(start, end);
    start = end + 1;
    if (seg.length() == 0 || seg == ".") continue;
    if (seg == "..") {
      if (parts.empty()) return -EACCES;          // intento de salir de la SD
      parts.pop_back();
      continue;
    }
    parts.push_back(seg);
  }
  String r = "/";
  for (size_t i = 0; i < parts.size(); ++i) {
    if (i) r += "/";
    r += parts[i];
  }
  if (r.length() + 1 > cap) return -ENAMETOOLONG;
  memcpy(out, r.c_str(), r.length() + 1);
  return 0;
}

// ---- Permisos (desde la tarea del script) ----------------------------------------------
int PySandbox::ask(const char* op, const char* abs, const char* extra) {
  String key = String(op) + "|" + abs;
  if (grantAll_ || granted_.count(key)) return 1;

  askSince_ = millis();
  state_ = State::Asking;                     // el watchdog se pausa
  std::vector<String> lines = {"El script " + name_, permText(op), String("  ") + abs};
  if (extra && *extra) lines.push_back(String("  -> ") + extra);
  DlgAnswer a = dlg_->askBlocking("PERMISO", lines, true, 120000);
  pausedMs_ = pausedMs_ + (millis() - askSince_);
  aliveMs_ = millis();                        // preguntar no cuenta para el watchdog
  if (state_ == State::Asking) state_ = State::Running;

  const char* verdict = a == DlgAnswer::Yes ? "permitido" : a == DlgAnswer::YesAll ? "permitido (todo)" : "DENEGADO";
  String msg = String("\x03[permiso ") + verdict + ": " + op + " " + abs + "]\n";
  out(msg.c_str(), msg.length());
  if (a == DlgAnswer::YesAll) grantAll_ = true;
  if (a == DlgAnswer::No) return 0;
  granted_.insert(key);
  return 1;
}

// =============================================================================
//  Puente C (lo llama MicroPython desde la tarea del script)
// =============================================================================
extern "C" {

void scpy_out(const char* s, size_t n) { pySandbox.out(s, n); }
int scpy_resolve(const char* in, char* out, size_t cap) { return pySandbox.resolve(in, out, cap); }

int scpy_stat(const char* abs, uint32_t* size) {
  if (!pySandbox.sd().mounted()) return -EIO;
  uint32_t s = 0;
  int t = pySandbox.sd().stat(String(abs), s);
  if (size) *size = s;
  return t;
}

int scpy_read(const char* abs, uint32_t off, uint8_t* buf, size_t n) {
  if (!pySandbox.sd().mounted()) return -EIO;
  return (int)pySandbox.sd().readAt(String(abs), off, buf, n);
}

int scpy_list(const char* abs, scpy_list_cb cb, void* ctx) {
  std::vector<DirEntry> v;
  if (!pySandbox.sd().listDir(String(abs), v, false)) return -ENOENT;
  for (const DirEntry& e : v) cb(ctx, e.name.c_str(), e.dir ? 1 : 0);
  return (int)v.size();
}

int scpy_write(const char* abs, uint32_t off, const uint8_t* d, size_t n, int trunc) {
  return pySandbox.sd().writeAt(String(abs), off, d, n, trunc != 0);
}
int scpy_remove(const char* abs) { return pySandbox.sd().removeFile(String(abs)); }
int scpy_rename(const char* a, const char* b) { return pySandbox.sd().renamePath(String(a), String(b)); }
int scpy_mkdir(const char* abs) { return pySandbox.sd().makeDir(String(abs)); }
int scpy_rmdir(const char* abs) { return pySandbox.sd().removeDir(String(abs)); }
int scpy_ask(const char* op, const char* abs, const char* extra) { return pySandbox.ask(op, abs, extra); }

uint32_t scpy_ticks_ms(void) { return millis(); }
void scpy_sleep_ms(uint32_t ms) { vTaskDelay(pdMS_TO_TICKS(ms ? ms : 1)); }
int scpy_argc(void) { return pySandbox.argc(); }
const char* scpy_argv(int i) { return pySandbox.argv(i); }
uint32_t scpy_random_seed(void) { return esp_random(); }

void scpy_fatal(const char* why) {
  Serial.printf("[python] ERROR FATAL: %s\n", why);
  const char m[] = "\x01" "Error interno de MicroPython.\n";
  pySandbox.out(m, sizeof m - 1);
  // No hay vuelta atrás desde aquí: se para la tarea (el heap se pierde
  // hasta reiniciar, pero el sistema sigue funcionando).
  vTaskSuspend(nullptr);
}

}  // extern "C"
