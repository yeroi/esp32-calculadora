// =============================================================================
//  PythonApp.cpp
// =============================================================================
#include "PythonApp.h"

PythonApp::PythonApp(AppManager& m)
    : App(m), browser_(m.gfx(), m.storage(), true), viewer_(m.gfx(), m.storage()) {}

void PythonApp::onEnter() {
  viewer_.close();
  browser_.refresh();
}

void PythonApp::drawFooter() {
  gfx().footer("▲▼ mover   EXE abrir/ejecutar   ◄ subir carpeta");
}

void PythonApp::draw() {
  if (viewer_.isOpen()) { viewer_.draw(); return; }
  if (!st().sdMounted) {
    gfx().text(0, 100, "MicroSD no detectada", 2, Theme::ERR, Theme::BG, Align::Center, Display::W);
    gfx().footer("Los scripts .py se guardan en la MicroSD");
    return;
  }
  browser_.draw("No hay scripts .py aquí");
  drawFooter();
}

void PythonApp::start(const String& path) {
  if (st().exam) {
    dialogs().info("Modo examen", {"Python está bloqueado durante", "el modo examen.", "",
                                   "Desactívalo en Ajustes."});
    return;
  }
  // Paso 3: aún no hay intérprete. Se ofrece ver el código.
  dialogs().ask("Python",
                {"El sandbox MicroPython llega en", "el Paso 5 del firmware.", "",
                 "¿Ver el código en modo lectura?", "  " + Path::name(path)},
                [this, path](DlgAnswer a) {
                  if (a == DlgAnswer::No || !viewer_.open(path)) return;
                  setTitle(Path::name(path).c_str());
                  requestRedraw();
                });
}

void PythonApp::onKey(const KeyEvent& ev) {
  if (viewer_.isOpen()) {
    if (viewer_.onKey(ev)) {
      viewer_.close();
      setTitle(title());
      requestRedraw();
    }
    return;
  }
  if (!st().sdMounted) return;
  if (ev.key == Key::AC) {
    if (browser_.goUp()) { browser_.draw("No hay scripts .py aquí"); drawFooter(); }
    return;
  }
  if (browser_.key(ev) == FolderBrowser::Result::OpenFile) start(browser_.selectedPath());
}
