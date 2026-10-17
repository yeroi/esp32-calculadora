// =============================================================================
//  PcTaskApp.h  —  "Que lo haga el PC" (solo en modo PC)
// -----------------------------------------------------------------------------
//  Para lo que el ESP32 sin PSRAM no puede hacer:
//    * vídeo y audio (mp4, mkv, mp3, m4a, ogg, wav...): el PC los decodifica
//      con ffmpeg y los reproduce en la pantalla y los altavoces del PC.
//    * juegos que no caben en los ~70 KB de Python (Paper Minecraft): el PC
//      los ejecuta con el mismo intérprete que el simulador.
//  El ESP32 manda PC_TASK con la ruta (el PC tiene la misma "SD") y se queda
//  esperando: mientras tanto el PC dibuja la zona de la app y se queda con
//  las teclas. Al acabar (o si el PC se desconecta) se vuelve a la app de
//  antes. La barra de estado la sigue dibujando el ESP32.
// =============================================================================
#pragma once
#include "App.h"
#include "config.h"
#if SCICALC_REMOTE
#include "RemoteLink.h"
#endif

class PcTaskApp : public App {
 public:
  enum Kind : uint8_t { Media = 1, Script = 2 };

  explicit PcTaskApp(AppManager& m) : App(m) {}

  // Prepara la tarea; luego mgr().launch(&pcTaskApp)
  void prepare(Kind k, const String& path, App* back) {
    kind_ = k;
    path_ = path;
    back_ = back;
    String t = (k == Media ? "▶ " : "PC ► ") + Path::name(path);
    strncpy(title_, t.c_str(), sizeof title_ - 1);
    title_[sizeof title_ - 1] = 0;
  }

  const char* title() const override { return title_; }

  void onEnter() override {
#if SCICALC_REMOTE
    String st;
    uint8_t s;
    remoteLink.takeTaskEnd(s, st);              // restos de una tarea anterior
    remoteLink.startPcTask(kind_, path_);
    running_ = true;
#endif
  }

  // La zona es del PC: aquí no se pinta nada (el gestor ya la ha limpiado)
  void draw() override {}

  // Normalmente las teclas se las queda el PC; por si acaso, AC cancela
  void onKey(const KeyEvent& ev) override {
    if (ev.key == Key::AC) finish(2, "");
  }

  void onTick(uint32_t) override {
#if SCICALC_REMOTE
    uint8_t s;
    String msg;
    if (remoteLink.takeTaskEnd(s, msg)) {
      running_ = false;
      finish(s, msg);
    } else if (!remoteLink.connected()) {
      running_ = false;
      finish(1, "Se desconectó el PC");
    }
#endif
  }

  void onExit() override {
#if SCICALC_REMOTE
    if (running_) remoteLink.stopPcTask();
#endif
    running_ = false;
  }

 private:
  void finish(uint8_t status, const String& msg) {
#if SCICALC_REMOTE
    if (running_) remoteLink.stopPcTask();
#endif
    running_ = false;
    if (back_) mgr().launch(back_);
    else mgr().goHome();
    if (status == 1 && msg.length()) dialogs().info("En el PC", {msg});
  }

  Kind kind_ = Media;
  String path_;
  App* back_ = nullptr;
  bool running_ = false;
  char title_[48] = "PC";
};

extern PcTaskApp pcTaskApp;

// Extensiones de vídeo y audio (las mismas que scicalc_media.py)
inline bool isMediaFile(const String& path) {
  static const char* const EXT[] = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".3gp",
                                    ".mpg", ".mpeg", ".wmv", ".flv", ".mp3", ".wav", ".ogg",
                                    ".oga", ".m4a", ".aac", ".flac", ".opus", ".wma", ".aiff"};
  String e = Path::ext(path);
  for (const char* x : EXT)
    if (e == x) return true;
  return false;
}
