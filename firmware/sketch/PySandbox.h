// =============================================================================
//  PySandbox.h  —  Ejecuta scripts .py con MicroPython, aislados del sistema
// -----------------------------------------------------------------------------
//  Cada script corre en su PROPIA tarea FreeRTOS con:
//    * heap propio de MicroPython (lo que quepa, hasta 112 KB; sin PSRAM
//      suelen ser ~80-100 KB). Se libera entero al terminar.
//    * pila propia de 16 KB con control de recursión.
//    * WATCHDOG de 5 s (sin contar el tiempo esperando un permiso): si se
//      pasa, se le lanza KeyboardInterrupt. AC hace lo mismo.
//  La UI (core 1, loop de Arduino) nunca espera al script: lee su salida y
//  su estado. El script solo toca la SD a través de Storage, con las rutas
//  encerradas en la SD y PREGUNTANDO antes de escribir/borrar/renombrar
//  (DialogManager::askBlocking, desde la tarea del script).
//
//  Igual que el simulador: CWD = carpeta del script, sys.path = ['', '/lib'].
// =============================================================================
#pragma once
#include <Arduino.h>
#include <set>
#include <vector>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>
#include "Dialog.h"
#include "Storage.h"

class PySandbox {
 public:
  enum class State : uint8_t {
    Idle, Running, Asking,                     // vivo
    Ok, Error, Watchdog, Stopped, Overflow, NoMem, Failed   // terminado
  };
  static constexpr uint32_t WATCHDOG_MS = 5000;
  static constexpr size_t MAX_LINES = 300;      // en RAM (las más recientes)
  static constexpr size_t MAX_TOTAL_LINES = 2000;

  void begin(Storage& sd, DialogManager& dlg);

  // Ejecuta 'path' (ruta absoluta en la SD). false si ya hay uno o no hay RAM.
  bool start(const String& path, const std::vector<String>& args = {});
  void stop();                       // AC / salir del modo: pide que pare
  void tick();                       // llamar desde la UI (watchdog)

  State state() const { return state_; }
  bool alive() const { return task_ != nullptr; }
  bool finished() const { return state_ >= State::Ok; }
  uint32_t elapsedMs() const;
  size_t heapKB() const { return heapSize_ / 1024; }
  const String& scriptName() const { return name_; }

  // ---- Salida (líneas; el 1er carácter puede ser un código de color) --------
  uint32_t outVersion() const { return outVersion_; }
  void copyLines(std::vector<String>& out);

  // ---- Para el puente C (scpy_*): se llaman desde la tarea del script ------
  void out(const char* s, size_t n);
  int resolve(const char* in, char* out, size_t cap);
  int ask(const char* op, const char* abs, const char* extra);
  Storage& sd() { return *sd_; }
  int argc() const { return (int)args_.size(); }
  const char* argv(int i) const { return args_[i].c_str(); }

 private:
  static void taskEntry(void* arg);
  void run();
  void pushLine(const String& l);

  Storage* sd_ = nullptr;
  DialogManager* dlg_ = nullptr;
  TaskHandle_t task_ = nullptr;
  SemaphoreHandle_t mutex_ = nullptr;

  volatile State state_ = State::Idle;
  String path_, name_, cwd_;
  std::vector<String> args_;
  void* heap_ = nullptr;
  size_t heapSize_ = 0;

  uint32_t t0_ = 0, endMs_ = 0;
  volatile uint32_t pausedMs_ = 0;           // tiempo preguntando (no cuenta)
  volatile uint32_t askSince_ = 0;
  volatile bool stopReq_ = false;
  volatile State stopReason_ = State::Stopped;
  uint32_t nextKick_ = 0;

  std::vector<String> lines_;
  String cur_;                               // línea a medias
  volatile uint32_t outVersion_ = 0;
  uint32_t totalLines_ = 0;

  std::set<String> granted_;                 // "op|ruta" ya permitidos
  bool grantAll_ = false;
};

extern PySandbox pySandbox;
