// =============================================================================
//  StatusBar.h  —  Barra de estado superior (22 px)
// -----------------------------------------------------------------------------
//   [Título .............. SHIFT EXAMEN LINK BT WiFi DEG SD 12:34 [bat]]
//
//  Funciona por "instantáneas": en cada update() se construye una foto del
//  estado (título, SHIFT, DEG/RAD, radios, hora...) y SOLO si difiere de la
//  última dibujada se repinta la barra. Así nadie tiene que acordarse de
//  avisar a la barra cuando cambia algo, y no se gasta SPI de más.
// =============================================================================
#pragma once
#include <Arduino.h>
#include "Display.h"
#include "SystemState.h"

class StatusBar {
 public:
  StatusBar(Display& d, const SystemState& s) : gfx_(d), st_(s) {}

  void setTitle(const char* utf8);
  const char* title() const { return title_; }
  void setShift(bool on) { shift_ = on; }
  void setShowAngle(bool on) { showAngle_ = on; }   // DEG/RAD solo en la calculadora
  void invalidate() { valid_ = false; }              // fuerza el repintado

  // Llamar en cada vuelta del bucle de la UI: repinta solo si hace falta.
  void update(uint32_t nowMs);

 private:
  struct Snapshot {
    char title[48];
    char clock[6];
    bool shift, angle, degrees, wifi, bt, link, exam, sd, charging;
    int8_t battery;
    bool operator==(const Snapshot& o) const;
  };
  void take(Snapshot& s) const;
  void draw(const Snapshot& s);
  int16_t drawBattery(int16_t xRight, const Snapshot& s);
  int16_t drawBadge(int16_t xRight, const char* txt, uint16_t bg);
  int16_t drawLabel(int16_t xRight, const char* txt, uint16_t fg);

  Display& gfx_;
  const SystemState& st_;
  char title_[48] = "";
  bool shift_ = false;
  bool showAngle_ = false;
  bool valid_ = false;
  Snapshot last_{};
  uint32_t nextClockCheck_ = 0;
  char clock_[6] = "--:--";
};
