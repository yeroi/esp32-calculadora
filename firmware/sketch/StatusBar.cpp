// =============================================================================
//  StatusBar.cpp
// =============================================================================
#include "StatusBar.h"
#include <time.h>

namespace {
  constexpr int16_t H = Display::HEADER_H;
  constexpr int16_t SMALL_Y = 7;          // y del texto de tamaño 1 (8 px) centrado
  constexpr int16_t GAP = 5;
}

void StatusBar::setTitle(const char* t) {
  strlcpy(title_, t ? t : "", sizeof title_);
}

bool StatusBar::Snapshot::operator==(const Snapshot& o) const {
  return strcmp(title, o.title) == 0 && strcmp(clock, o.clock) == 0 &&
         shift == o.shift && angle == o.angle && degrees == o.degrees &&
         wifi == o.wifi && bt == o.bt && link == o.link && exam == o.exam &&
         sd == o.sd && charging == o.charging && battery == o.battery;
}

void StatusBar::take(Snapshot& s) const {
  strlcpy(s.title, title_, sizeof s.title);
  strlcpy(s.clock, clock_, sizeof s.clock);
  s.shift = shift_;
  s.angle = showAngle_;
  s.degrees = st_.degrees;
  s.wifi = st_.wifiConnected;
  s.bt = st_.btOn;
  s.link = st_.linkClients > 0;
  s.exam = st_.exam;
  s.sd = st_.sdMounted;
  s.charging = st_.charging;
  s.battery = st_.batteryPct;
}

void StatusBar::update(uint32_t now) {
  // La hora se consulta dos veces por segundo. Sin Wi-Fi (NTP) ni RTC el
  // ESP32 no sabe la hora: mientras el año sea < 2024 se muestra "--:--".
  if ((int32_t)(now - nextClockCheck_) >= 0) {
    nextClockCheck_ = now + 500;
    time_t t = time(nullptr);
    struct tm tmv;
    localtime_r(&t, &tmv);
    if (tmv.tm_year + 1900 >= 2024) snprintf(clock_, sizeof clock_, "%02d:%02d", tmv.tm_hour, tmv.tm_min);
    else strlcpy(clock_, "--:--", sizeof clock_);
  }
  Snapshot s;
  take(s);
  if (valid_ && s == last_) return;
  draw(s);
  last_ = s;
  valid_ = true;
}

// ---- Elementos (se dibujan de derecha a izquierda; devuelven la nueva x) ----
int16_t StatusBar::drawLabel(int16_t xr, const char* txt, uint16_t fg) {
  int16_t w = Display::textWidth(txt, 1) + 1;
  xr -= w;
  gfx_.textBold(xr, SMALL_Y, txt, 1, fg, Theme::PANEL);
  return xr - GAP;
}

int16_t StatusBar::drawBadge(int16_t xr, const char* txt, uint16_t bg) {
  int16_t w = Display::textWidth(txt, 1) + 9;
  xr -= w;
  gfx_.fillRoundRect(xr, 3, w, 15, 3, bg);
  gfx_.text(xr, SMALL_Y, txt, 1, Theme::BG, bg, Align::Center, w, true);
  return xr - GAP;
}

int16_t StatusBar::drawBattery(int16_t xr, const Snapshot& s) {
  // Icono de 20x10 + "nariz" de 2 px
  const int16_t w = 18, h = 10, y = 6;
  int16_t x = xr - w - 2;
  gfx_.drawRect(x, y, w, h, Theme::TEXT);
  gfx_.fillRect(x + w, y + 3, 2, 4, Theme::TEXT);
  gfx_.fillRect(x + 1, y + 1, w - 2, h - 2, Theme::PANEL);
  if (s.battery < 0) {
    gfx_.text(x + 6, y + 1, "?", 1, Theme::MUTED, Theme::PANEL);   // aún sin ADC
  } else {
    uint16_t c = s.battery > 30 ? Theme::OK : s.battery > 12 ? Theme::WARN : Theme::ERR;
    int16_t fill = (int16_t)((w - 4) * min<int>(s.battery, 100) / 100);
    if (fill > 0) gfx_.fillRect(x + 2, y + 2, fill, h - 4, c);
    if (s.charging) gfx_.text(x + 6, y + 1, "+", 1, Theme::TEXT, c);
  }
  return x - GAP - 1;
}

void StatusBar::draw(const Snapshot& s) {
  gfx_.fillRect(0, 0, Display::W, H - 1, Theme::PANEL);
  gfx_.hLine(0, H - 1, Display::W, Theme::ACCENT);

  // Indicadores, de derecha a izquierda (mismo orden que el simulador)
  int16_t x = Display::W - 3;
  x = drawBattery(x, s);
  x = drawLabel(x, s.clock, Theme::TEXT);
  x = drawLabel(x, "SD", s.sd ? Theme::OK : Theme::MUTED);
  if (s.angle) x = drawLabel(x, s.degrees ? "DEG" : "RAD", Theme::ACCENT);
  if (s.wifi) x = drawLabel(x, "WiFi", Theme::ACCENT);
  if (s.bt)   x = drawLabel(x, "BT", Theme::ACCENT);
  if (s.link) x = drawLabel(x, "LINK", Theme::OK);
  if (s.exam) x = drawBadge(x, "EXAMEN", Theme::WARN);
  if (s.shift) x = drawBadge(x, "SHIFT", Theme::SHIFT);

  // Título: grande si cabe; si no, pequeño y recortado.
  const int16_t avail = x - 6;
  if (Display::textWidth(s.title, 2) <= avail) {
    gfx_.text(6, 3, s.title, 2, Theme::TEXT, Theme::PANEL);
  } else {
    gfx_.textBold(6, SMALL_Y, s.title, 1, Theme::TEXT, Theme::PANEL, avail);
  }
}
