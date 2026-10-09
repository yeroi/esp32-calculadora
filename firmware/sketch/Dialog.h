// =============================================================================
//  Dialog.h  —  Diálogos modales reutilizables
// -----------------------------------------------------------------------------
//  Teclas (igual que el simulador):
//     EXE        -> Sí
//     SHIFT+EXE  -> Sí a todo   (solo si el diálogo lo permite: permisos)
//     AC / DEL   -> No
//  Los informativos solo tienen "Aceptar" (EXE, AC, DEL o ◄ lo cierran).
//
//  Dos formas de preguntar:
//   * ask()/info()   desde la UI (core 1): no bloquean; el resultado llega
//                    por un callback cuando el usuario responde.
//   * askBlocking()  desde OTRA tarea (sandbox de Python, SciCalc Link):
//                    la tarea se queda esperando la respuesta con un timeout.
//                    Si caduca, el diálogo se retira solo y la respuesta es No.
//
//  Varios diálogos se encolan: se muestra el primero y, al responderlo, el
//  siguiente.
// =============================================================================
#pragma once
#include <Arduino.h>
#include <deque>
#include <functional>
#include <memory>
#include <vector>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include "Display.h"
#include "Keyboard.h"

enum class DlgAnswer : uint8_t { Yes, YesAll, No };
using DlgCallback = std::function<void(DlgAnswer)>;

class DialogManager {
 public:
  explicit DialogManager(Display& d);
  bool begin();

  // ---- Desde la UI -----------------------------------------------------------
  // Pregunta Sí/No (y "Sí a todo" si allowAll). El color del marco se elige
  // solo: naranja para PERMISO / Desinstalar / Modo examen, azul el resto.
  void ask(const char* title, std::vector<String> lines, DlgCallback cb,
           bool allowAll = false);
  // Mensaje informativo con un único botón "Aceptar"
  void info(const char* title, std::vector<String> lines, DlgCallback cb = nullptr);

  // ---- Desde otra tarea (NUNCA desde la UI: se bloquearía) -------------------
  DlgAnswer askBlocking(const char* title, std::vector<String> lines,
                        bool allowAll = false, uint32_t timeoutMs = 60000);

  // ---- Para el AppManager -----------------------------------------------------
  bool active() const { return !queue_.empty(); }
  // Recoge peticiones de otras tareas y retira las caducadas.
  // Devuelve true si cambió el diálogo visible (hay que repintar).
  bool service();
  // Procesa una tecla. Devuelve true si el diálogo visible se cerró.
  bool handleKey(const KeyEvent& ev);
  void draw();                      // dibuja el diálogo visible

 private:
  // Petición hecha desde otra tarea; compartida entre ambas tareas.
  struct Remote {
    SemaphoreHandle_t done = nullptr;
    volatile DlgAnswer answer = DlgAnswer::No;
    volatile bool expired = false;
    ~Remote() { if (done) vSemaphoreDelete(done); }
  };
  struct Dialog {
    String title;
    std::vector<String> lines;
    DlgCallback cb;
    bool allowAll = false;
    bool info = false;
    std::shared_ptr<Remote> remote;     // solo en askBlocking()
  };

  void push(Dialog&& d);
  static uint16_t colorFor(const String& title);

  Display& gfx_;
  std::deque<Dialog> queue_;            // solo lo toca la tarea de la UI
  std::deque<Dialog> incoming_;         // peticiones de otras tareas
  SemaphoreHandle_t lock_ = nullptr;    // protege incoming_
  TaskHandle_t uiTask_ = nullptr;
};
