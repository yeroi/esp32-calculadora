// =============================================================================
//  FilesApp.cpp
// =============================================================================
#include "FilesApp.h"

FilesApp::FilesApp(AppManager& m)
    : App(m), browser_(m.gfx(), m.storage(), false), viewer_(m.gfx(), m.storage()) {}

void FilesApp::onEnter() {
  viewer_.close();
  browser_.refresh();
}

void FilesApp::drawFooter() {
  gfx().footer("▲▼ mover  EXE abrir  ◄ subir  SHIFT+EXE recargar");
}

void FilesApp::draw() {
  if (viewer_.isOpen()) { viewer_.draw(); return; }
  if (!st().sdMounted) {
    gfx().text(0, 100, "MicroSD no detectada", 2, Theme::ERR, Theme::BG, Align::Center, Display::W);
    gfx().footer("Inserta una tarjeta FAT32 y reinicia");
    return;
  }
  browser_.draw();
  drawFooter();
}

void FilesApp::onKey(const KeyEvent& ev) {
  // --- Visor abierto ----------------------------------------------------------
  if (viewer_.isOpen()) {
    if (viewer_.onKey(ev)) {               // ◄/DEL/AC: volver a la lista
      viewer_.close();
      setTitle(title());
      browser_.refresh();
      requestRedraw();
    }
    return;
  }
  if (!st().sdMounted) return;

  // --- Explorador ---------------------------------------------------------------
  if (ev.key == Key::AC) {                 // AC también sube (como el simulador)
    if (browser_.goUp()) { browser_.draw(); drawFooter(); }
    return;
  }
  if (ev.key == Key::Exe && ev.shift) {    // SHIFT+EXE recarga
    browser_.refresh();
    browser_.draw();
    drawFooter();
    return;
  }
  if (browser_.key(ev) == FolderBrowser::Result::OpenFile) {
    String p = browser_.selectedPath();
    if (viewer_.open(p)) {
      setTitle(Path::name(p).c_str());
      requestRedraw();
    } else {
      dialogs().info("Archivos SD", {"No se pudo abrir:", "  " + Path::name(p)});
    }
  }
}
