// =============================================================================
//  App.h  —  Marco de aplicaciones ("modos" de la calculadora)
// -----------------------------------------------------------------------------
//  Cada modo (Menú, Calculadora, Python, Archivos...) es una App.
//
//  Ciclo de vida:
//    onEnter()  al entrar: prepara el estado (NO dibuja)
//    draw()     dibuja TODO el cuerpo (el gestor ya lo ha limpiado). Se llama
//               al entrar, al cerrar un diálogo o cuando la app lo pide con
//               requestRedraw(). Debe poder repetirse sin efectos secundarios.
//    onKey()    tecla (con SHIFT ya resuelto). Aquí se hacen los redibujados
//               parciales (solo lo que cambia).
//    onTick()   en cada vuelta del bucle (animaciones, cursores, relojes).
//               Antes de dibujar, comprobar canDraw(): con un diálogo abierto
//               no se debe pintar encima.
//    onExit()   al salir (liberar memoria, parar tareas).
//
//  El AppManager se encarga de:
//    * La barra de estado y limpiar la pantalla al cambiar de modo.
//    * Teclas globales: MENU vuelve siempre al menú; SHIFT se activa para la
//      siguiente pulsación (como en una Casio) y se muestra en la barra.
//    * Los diálogos modales: mientras hay uno, las teclas van al diálogo.
// =============================================================================
#pragma once
#include <Arduino.h>
#include "Dialog.h"
#include "Display.h"
#include "Keyboard.h"
#include "StatusBar.h"
#include "Storage.h"
#include "SystemState.h"

class AppManager;

class App {
 public:
  explicit App(AppManager& m) : mgr_(m) {}
  virtual ~App() = default;

  virtual const char* title() const = 0;
  virtual void onEnter() {}
  virtual void draw() = 0;
  virtual void onKey(const KeyEvent& ev) = 0;
  virtual void onTick(uint32_t /*nowMs*/) {}
  virtual void onExit() {}
  // true si la barra de estado debe mostrar DEG/RAD (solo la calculadora)
  virtual bool showsAngleMode() const { return false; }

 protected:
  // Accesos cómodos a los servicios del sistema
  Display& gfx();
  Storage& sd();
  SystemState& st();
  DialogManager& dialogs();
  AppManager& mgr() { return mgr_; }
  bool canDraw() const;        // false si hay un diálogo encima
  void setTitle(const char* t);
  void requestRedraw();        // repintar todo el cuerpo en la próxima vuelta

 private:
  AppManager& mgr_;
};

// -----------------------------------------------------------------------------
class AppManager {
 public:
  AppManager(Display& d, IKeyboard& k, Storage& s, SystemState& st,
             StatusBar& bar, DialogManager& dlg)
      : gfx_(d), kb_(k), sd_(s), st_(st), bar_(bar), dlg_(dlg) {}

  void setHome(App* home) { home_ = home; }
  App* current() const { return current_; }
  void launch(App* app);
  void goHome() { launch(home_); }
  void setTitle(const char* t) { bar_.setTitle(t); }
  void requestRedraw() { bodyDirty_ = true; }
  void update();                                 // llamar desde loop()

  Display& gfx() { return gfx_; }
  Storage& storage() { return sd_; }
  SystemState& state() { return st_; }
  DialogManager& dialogs() { return dlg_; }

 private:
  void dispatch(KeyEvent ev);
  void render();
  void setShift(bool on) { shift_ = on; bar_.setShift(on); }

  Display&       gfx_;
  IKeyboard&     kb_;
  Storage&       sd_;
  SystemState&   st_;
  StatusBar&     bar_;
  DialogManager& dlg_;

  App* home_    = nullptr;
  App* current_ = nullptr;
  bool shift_   = false;
  bool bodyDirty_ = false;     // hay que repintar el cuerpo de la app
  bool dialogDirty_ = false;   // hay que pintar el diálogo visible
  bool dialogShown_ = false;   // había un diálogo en pantalla al acabar render()
};
