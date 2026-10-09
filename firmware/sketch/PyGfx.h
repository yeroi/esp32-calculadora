// =============================================================================
//  PyGfx.h  —  Pantalla y teclas para los scripts gráficos (módulo scicalc)
// -----------------------------------------------------------------------------
//  Igual que en el simulador, el script NO dibuja: apunta órdenes en una cola
//  (limpiar, rect, texto, sprite...) y mostrar() se la entrega a la UI, que
//  es la única que toca la pantalla. Así la tarea del script y la del menú
//  nunca dibujan a la vez (en modo PC, ni mezclan tramas por el USB).
//
//      tarea del script (productor)          tarea de la UI (consumidor)
//      ----------------------------          ---------------------------
//      push(op) ... push(op)  ─── cola ───►  drain(): ejecuta las órdenes
//      show(): espera a que se vacíe         con recorte, en la zona del
//              y limita a ~30 fps            script (320 x 218, bajo la barra)
//
//  Sprites (PNG de la SD):
//    * pequeños (<= 24 KB decodificados): se guardan decodificados en RAM
//      (RGB565 + máscara de 1 bit), hasta 48 KB entre todos (se expulsa el
//      que lleva más tiempo sin usarse).
//    * grandes (fondos de Scratch de 320x218 = 140 KB): no caben; se vuelven
//      a decodificar de la SD cada vez que se dibujan (sin girar).
//  Un PNG en decodificación ocupa ~45 KB (PNGdec) mientras dura.
//
//  Teclas: la UI le pasa al script las pulsaciones (cola) y, para saber qué
//  teclas están MANTENIDAS: en modo PC el estado real del teclado del PC; con
//  la matriz física, una tecla cuenta como mantenida mientras llegan sus
//  autorrepeticiones.
// =============================================================================
#pragma once
#include <Arduino.h>
#include <vector>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include "Display.h"
#include "Keyboard.h"
#include "Storage.h"

class PyGfx {
 public:
  static constexpr int16_t AREA_Y = Display::BODY_Y;     // la zona del script
  static constexpr int16_t AREA_W = Display::W;          // 320
  static constexpr int16_t AREA_H = Display::BODY_H;     // 218

  enum Kind : uint8_t { CLEAR, RECT, FRAME, LINE, TEXT, SPRITE, CLIP, LOAD };
  struct Op {
    uint8_t kind = 0;
    uint8_t flags = 0;          // TEXT: tamaño | 0x80 con fondo · SPRITE: 1 espejo, 2 centro
    uint16_t id = 0;            // SPRITE/LOAD: sprite · TEXT/LOAD: posición en el texto
    int16_t x = 0, y = 0, w = 0, h = 0;   // LINE: x0, y0, x1, y1 · TEXT: w = largo
    uint16_t c = 0, bg = 0;     // RGB565
    float fx = 0, fy = 0, sx = 1, sy = 1, ang = 0, cx = 0, cy = 0;   // SPRITE
  };

  // ---- Desde la tarea del script --------------------------------------------
  bool begin();                               // entra en modo gráfico (reserva la cola)
  void push(const Op& op, const char* text = nullptr, size_t n = 0);
  int  show();                                // 1 si hay que parar el script
  int  newSprite(const char* path);           // id
  bool popKey(Key& k, bool& shift);
  uint64_t held();

  // ---- Desde la UI ------------------------------------------------------------
  bool active() const { return active_; }
  void drain(Display& d, Storage& sd, uint32_t budgetMs);
  void onKey(const KeyEvent& ev);             // tecla para el script
  void end();                                 // el script terminó: libera todo

  // (interno) pinta una fila de un sprite grande; la llama el decodificador
  void bigRow(int16_t y, const uint16_t* line, const uint8_t* mask);

 private:
  struct Sprite {
    String path;
    uint16_t w = 0, h = 0;
    uint16_t* px = nullptr;                   // RGB565
    uint8_t* mask = nullptr;                  // 1 bit por píxel (bit alto primero)
    bool big = false, bad = false;
    uint32_t used = 0;
  };

  // dibujo con recorte (coordenadas de pantalla)
  void fill(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t c);
  void line(int16_t x0, int16_t y0, int16_t x1, int16_t y1, uint16_t c);
  void text(const Op& op, const char* s);
  void drawSprite(const Op& op);
  bool load(Sprite& s);
  void drawBig(Sprite& s, const Op& op);
  void freeSprite(Sprite& s);
  void makeRoom(size_t bytes);
  void pushRun(int16_t x, int16_t y, int16_t n);

  Display* d_ = nullptr;
  Storage* sd_ = nullptr;
  volatile bool active_ = false;
  bool cleared_ = false;

  static constexpr uint16_t QCAP = 160;
  static constexpr uint16_t TCAP = 2048;
  Op* q_ = nullptr;
  char* txt_ = nullptr;
  volatile uint16_t head_ = 0, tail_ = 0;     // productor / consumidor
  uint16_t txtUsed_ = 0;
  uint16_t nextId_ = 0;                       // próximo sprite (lo usa el script)
  uint32_t lastShow_ = 0;

  int16_t clipX0_ = 0, clipY0_ = AREA_Y, clipX1_ = AREA_W, clipY1_ = AREA_Y + AREA_H;
  std::vector<Sprite> sprites_;
  size_t cacheBytes_ = 0;
  uint16_t* row_ = nullptr;                   // fila de trabajo (320 px)

  QueueHandle_t keys_ = nullptr;
  uint32_t heldUntil_[KEY_COUNT + 1] = {};    // matriz física: mantenida hasta (ms)
};

extern PyGfx pyGfx;
