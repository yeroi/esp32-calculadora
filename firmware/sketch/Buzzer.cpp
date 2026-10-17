// =============================================================================
//  Buzzer.cpp
// =============================================================================
#include "Buzzer.h"
#include "config.h"
#if SCICALC_REMOTE
#include "RemoteLink.h"
#endif

Buzzer buzzer;

void Buzzer::begin() {
#if !SCICALC_REMOTE
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_BUZZER, LOW);
#endif
}

void Buzzer::tone(uint16_t hz, uint16_t ms) {
  if (!enabled || ms == 0) return;
#if SCICALC_REMOTE
  uint8_t b[4] = {(uint8_t)(hz & 0xFF), (uint8_t)(hz >> 8), (uint8_t)(ms & 0xFF), (uint8_t)(ms >> 8)};
  remoteLink.send(Proto::TONE, b, sizeof b);
#else
  // tone() de Arduino-ESP32 encola las notas en su propia tarea (LEDC)
  if (hz) ::tone(PIN_BUZZER, hz, ms);
  else ::tone(PIN_BUZZER, 0, ms);
#endif
}

void Buzzer::stop() {
#if SCICALC_REMOTE
  uint8_t b[4] = {0, 0, 0, 0};          // ms = 0 -> el PC vacía la cola
  remoteLink.send(Proto::TONE, b, sizeof b);
#else
  ::noTone(PIN_BUZZER);
#endif
}

void Buzzer::click()  { if (keyClick) tone(2400, 12); }
void Buzzer::alert()  { tone(880, 70); tone(1175, 90); }
void Buzzer::chime()  { tone(1047, 70); tone(1319, 70); tone(1568, 110); }
