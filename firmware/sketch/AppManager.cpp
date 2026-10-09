// =============================================================================
//  AppManager.cpp  (incluye los accesos de la clase App)
// =============================================================================
#include "App.h"
#include "Buzzer.h"

// ---- App ----------------------------------------------------------------------
Display& App::gfx() { return mgr_.gfx(); }
Storage& App::sd() { return mgr_.storage(); }
SystemState& App::st() { return mgr_.state(); }
DialogManager& App::dialogs() { return mgr_.dialogs(); }
bool App::canDraw() const { return !mgr_.dialogs().active(); }
void App::setTitle(const char* t) { mgr_.setTitle(t); }
void App::requestRedraw() { mgr_.requestRedraw(); }

// ---- AppManager -----------------------------------------------------------------
void AppManager::launch(App* app) {
  if (!app) return;
  if (current_) current_->onExit();
  current_ = app;
  setShift(false);
  bar_.setTitle(app->title());
  bar_.setShowAngle(app->showsAngleMode());
  app->onEnter();
  bodyDirty_ = true;
}

void AppManager::dispatch(KeyEvent ev) {
  if (!ev.repeat) buzzer.click();
  // --- SHIFT es global (también dentro de los diálogos: SHIFT+EXE) ---------
  if (ev.key == Key::Shift) {
    if (!ev.repeat) setShift(!shift_);
    return;
  }

  // --- Con un diálogo abierto, las teclas van al diálogo -------------------
  if (dlg_.active()) {
    ev.shift = shift_;
    if (dlg_.handleKey(ev)) {
      setShift(false);
      bodyDirty_ = true;          // al cerrarse se repinta la app (y el siguiente)
    }
    return;                       // MENU y el resto se ignoran con un diálogo
  }

  if (ev.key == Key::Menu) {
    if (current_ != home_) goHome();
    return;
  }

  // --- Resto: a la app activa, con SHIFT "de un solo uso" -------------------
  ev.shift = shift_;
  if (shift_ && !ev.repeat) setShift(false);
  if (current_) current_->onKey(ev);
}

void AppManager::render() {
  if (bodyDirty_ && current_) {
    bodyDirty_ = false;
    gfx_.clearBody();
    current_->draw();
    dialogDirty_ = true;          // el diálogo (si hay) va encima
  }
  if (dialogDirty_) {
    dialogDirty_ = false;
    if (dlg_.active()) dlg_.draw();
  }
}

void AppManager::update() {
  // 0) Modo PC: el programa del PC se acaba de conectar -> repintar TODO
  if (gfx_.takeFullRedraw()) {
    gfx_.clear();
    bar_.invalidate();
    bodyDirty_ = true;
  }

  // 1) Diálogos pedidos desde otras tareas (sandbox, SciCalc Link)
  const bool wasActive = dlg_.active();
  if (dlg_.service()) {
    if (wasActive) bodyDirty_ = true;     // se retiró el visible: repintar todo
    else dialogDirty_ = true;             // aparece uno nuevo encima de la app
  }

  // 2) Teclas. Espera breve: libera la CPU y responde en < 10 ms.
  KeyEvent ev;
  if (kb_.poll(ev, 10)) {
    dispatch(ev);
    while (kb_.poll(ev, 0)) dispatch(ev);     // vacía lo acumulado
  }

  // 3) Tic de la app (animaciones, tareas en curso)
  if (current_) current_->onTick(millis());

  // 4) Un diálogo abierto desde onKey()/onTick() se pinta encima; si se
  //    cerró sin pasar por una tecla, se repinta la app.
  if (dlg_.active() != dialogShown_) {
    if (dlg_.active()) dialogDirty_ = true;
    else bodyDirty_ = true;
  }

  // 5) Dibujo
  render();
  if (dlg_.active() && !dialogShown_) buzzer.alert();
  dialogShown_ = dlg_.active();
  bar_.update(millis());
}
