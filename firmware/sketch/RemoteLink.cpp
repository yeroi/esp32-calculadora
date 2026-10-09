// =============================================================================
//  RemoteLink.cpp
// =============================================================================
#include "RemoteLink.h"
#include <errno.h>
#include "config.h"

RemoteLink remoteLink;

namespace {
constexpr uint32_t ALIVE_MS = 3500;        // sin noticias del PC -> desconectado
portMUX_TYPE rpcMux = portMUX_INITIALIZER_UNLOCKED;

bool isRepeatable(Key k) {
  return k == Key::Up || k == Key::Down || k == Key::Left || k == Key::Right || k == Key::Del;
}
}  // namespace

bool RemoteLink::begin(uint32_t baud) {
  tx_ = static_cast<uint8_t*>(malloc(TX_CAP));
  rx_ = static_cast<uint8_t*>(malloc(Proto::MAX_PAYLOAD));
  txMutex_ = xSemaphoreCreateMutex();
  rpcMutex_ = xSemaphoreCreateMutex();
  rpcDone_ = xSemaphoreCreateBinary();
  keys_ = xQueueCreate(32, sizeof(KeyEvent));
  if (!tx_ || !rx_ || !txMutex_ || !rpcMutex_ || !rpcDone_ || !keys_) return false;

  // Búferes grandes ANTES de begin(): el dibujo no se queda esperando al UART
  Serial.setRxBufferSize(4096);
  Serial.setTxBufferSize(8192);
  Serial.begin(baud);

  return xTaskCreatePinnedToCore(taskEntry, "pclink", 4096, this, 3, &task_,
                                 CORE_SERVICES) == pdPASS;
}

bool RemoteLink::connected() const {
  return hello_ && (millis() - lastRxMs_) < ALIVE_MS;
}

bool RemoteLink::waitConnected(uint32_t ms) {
  uint32_t t0 = millis();
  while (!connected() && millis() - t0 < ms) delay(20);
  return connected();
}

// ---- Envío ------------------------------------------------------------------
void RemoteLink::send(uint8_t type, const uint8_t* data, size_t len) {
  if (!tx_ || len > Proto::MAX_PAYLOAD) return;
  // Sin PC no se envía nada (al conectar se repinta todo). El saludo sí.
  if (type != Proto::HELLO && !connected()) return;
  xSemaphoreTake(txMutex_, portMAX_DELAY);
  if (txLen_ + len + 6 > TX_CAP) flushLocked();
  uint8_t* p = tx_ + txLen_;
  p[0] = Proto::SYNC0;
  p[1] = Proto::SYNC1;
  p[2] = type;
  p[3] = len & 0xFF;
  p[4] = len >> 8;
  uint8_t sum = p[2] + p[3] + p[4];
  for (size_t i = 0; i < len; ++i) sum += (p[5 + i] = data[i]);
  p[5 + len] = sum;
  txLen_ += len + 6;
  xSemaphoreGive(txMutex_);
}

void RemoteLink::flushLocked() {
  if (txLen_) Serial.write(tx_, txLen_);   // una sola escritura: no se mezcla con printf
  txLen_ = 0;
}

void RemoteLink::flush() {
  if (!txMutex_) return;
  xSemaphoreTake(txMutex_, portMAX_DELAY);
  flushLocked();
  xSemaphoreGive(txMutex_);
}

void RemoteLink::sendHello() {
  uint8_t b[64];
  b[0] = Proto::VERSION;
  b[1] = 320 & 0xFF; b[2] = 320 >> 8;
  b[3] = 240 & 0xFF; b[4] = 240 >> 8;
  int n = snprintf(reinterpret_cast<char*>(b + 5), sizeof b - 5, "%s v%s", FW_NAME, FW_VERSION);
  send(Proto::HELLO, b, 5 + (n > 0 ? n : 0));
  flush();
}

// ---- Tarea del enlace (core 0) ----------------------------------------------
void RemoteLink::taskEntry(void* arg) { static_cast<RemoteLink*>(arg)->taskLoop(); }

void RemoteLink::taskLoop() {
  uint8_t buf[256];
  bool wasConnected = false;
  for (;;) {
    int avail;
    while ((avail = Serial.available()) > 0) {
      size_t n = Serial.read(buf, avail < (int)sizeof buf ? avail : sizeof buf);
      for (size_t i = 0; i < n; ++i) rxByte(buf[i]);
    }

    uint32_t now = millis();
    if (repeatKey_ != Key::None && (int32_t)(now - nextRepeatAt_) >= 0) {
      KeyEvent ev;
      ev.key = repeatKey_;
      ev.repeat = true;
      xQueueSend(keys_, &ev, 0);
      nextRepeatAt_ = now + KB_REPEAT_RATE;
    }

    bool c = connected();
    if (wasConnected && !c) releaseAll();   // el PC se fue: suelta las teclas
    wasConnected = c;

    flush();
    vTaskDelay(pdMS_TO_TICKS(4));
  }
}

void RemoteLink::rxByte(uint8_t b) {
  switch (rxState_) {
    case Rx::Sync0: if (b == Proto::SYNC0) rxState_ = Rx::Sync1; break;
    case Rx::Sync1: rxState_ = (b == Proto::SYNC1) ? Rx::Type : (b == Proto::SYNC0 ? Rx::Sync1 : Rx::Sync0); break;
    case Rx::Type:  rxType_ = b; rxSum_ = b; rxState_ = Rx::Len0; break;
    case Rx::Len0:  rxLen_ = b; rxSum_ += b; rxState_ = Rx::Len1; break;
    case Rx::Len1:
      rxLen_ |= (uint16_t)b << 8;
      rxSum_ += b;
      rxPos_ = 0;
      if (rxLen_ > Proto::MAX_PAYLOAD) rxState_ = Rx::Sync0;
      else rxState_ = rxLen_ ? Rx::Data : Rx::Sum;
      break;
    case Rx::Data:
      rx_[rxPos_++] = b;
      rxSum_ += b;
      if (rxPos_ >= rxLen_) rxState_ = Rx::Sum;
      break;
    case Rx::Sum:
      if (b == rxSum_) handleFrame(rxType_, rx_, rxLen_);
      rxState_ = Rx::Sync0;
      break;
  }
}

void RemoteLink::handleFrame(uint8_t type, const uint8_t* p, size_t n) {
  lastRxMs_ = millis();
  // Un latido de un PC que no nos ha saludado (p. ej. el ESP32 se reinició
  // por su cuenta) cuenta como saludo: así nunca se queda la pantalla negra.
  if (type == Proto::PC_PING && !hello_) type = Proto::PC_HELLO;
  switch (type) {
    case Proto::PC_HELLO:
      releaseAll();
      hello_ = true;
      session_ = session_ + 1;               // -> glifos de nuevo y repintado total
      sendHello();
      break;
    case Proto::PC_PING:
      break;
    case Proto::PC_KEY:
      if (n >= 2) onKey(p[0], p[1] != 0);
      break;
    case Proto::PC_SET:
      if (n >= 2) { battery_ = (int8_t)p[0]; charging_ = p[1] != 0; }
      break;
    case Proto::FS_RESP: {
      if (n < 2) break;
      bool mine;
      portENTER_CRITICAL(&rpcMux);
      mine = rpcWaiting_ && p[0] == rpcId_;
      if (mine) rpcWaiting_ = false;        // la reclamamos: ya nadie más la toca
      portEXIT_CRITICAL(&rpcMux);
      if (!mine) break;                      // respuesta tardía de una caducada
      if (p[1] != 0) {
        rpcResult_ = -(int)p[1];
      } else {
        size_t len = n - 2;
        if (len > rpcCap_) len = rpcCap_;
        if (len) memcpy(rpcResp_, p + 2, len);
        rpcResult_ = (int)len;
      }
      xSemaphoreGive(rpcDone_);
      break;
    }
    default:
      break;
  }
}

// ---- Petición / respuesta -------------------------------------------------------
int RemoteLink::request(uint8_t op, const uint8_t* req, size_t reqLen,
                        uint8_t* resp, size_t respCap, uint32_t timeoutMs) {
  static uint8_t out[Proto::MAX_PAYLOAD];
  if (!connected()) return -ETIMEDOUT;
  if (reqLen + 2 > sizeof out) return -ENAMETOOLONG;
  xSemaphoreTake(rpcMutex_, portMAX_DELAY);

  uint8_t id = rpcId_ + 1;
  if (id == 0) id = 1;
  xSemaphoreTake(rpcDone_, 0);               // por si quedó una señal antigua
  rpcResp_ = resp;
  rpcCap_ = respCap;
  portENTER_CRITICAL(&rpcMux);
  rpcId_ = id;
  rpcWaiting_ = true;
  portEXIT_CRITICAL(&rpcMux);

  out[0] = id;
  out[1] = op;
  if (reqLen) memcpy(out + 2, req, reqLen);
  send(Proto::FS_REQ, out, reqLen + 2);
  flush();

  int result;
  if (xSemaphoreTake(rpcDone_, pdMS_TO_TICKS(timeoutMs)) == pdTRUE) {
    result = rpcResult_;
  } else {
    bool claimed;
    portENTER_CRITICAL(&rpcMux);
    claimed = !rpcWaiting_;                  // llegó justo ahora: espera la copia
    rpcWaiting_ = false;
    portEXIT_CRITICAL(&rpcMux);
    if (claimed && xSemaphoreTake(rpcDone_, pdMS_TO_TICKS(200)) == pdTRUE) result = rpcResult_;
    else result = -ETIMEDOUT;
  }
  xSemaphoreGive(rpcMutex_);
  return result;
}

// ---- Teclado -------------------------------------------------------------------
void RemoteLink::onKey(uint8_t key, bool down) {
  if (key == 0 || key >= static_cast<uint8_t>(Key::Count)) return;
  const Key k = static_cast<Key>(key);
  const uint64_t bit = 1ULL << key;
  if (down) {
    if (held_ & bit) return;                 // ya estaba pulsada
    held_ = held_ | bit;
    KeyEvent ev;
    ev.key = k;
    xQueueSend(keys_, &ev, 0);
    if (isRepeatable(k)) {
      repeatKey_ = k;
      nextRepeatAt_ = millis() + KB_REPEAT_DELAY;
    }
  } else {
    held_ = held_ & ~bit;
    if (repeatKey_ == k) repeatKey_ = Key::None;
  }
}

void RemoteLink::releaseAll() {
  held_ = 0;
  repeatKey_ = Key::None;
}

bool RemoteLink::pollKey(KeyEvent& ev, uint32_t waitMs) {
  if (!keys_) return false;
  return xQueueReceive(keys_, &ev, pdMS_TO_TICKS(waitMs)) == pdTRUE;
}

void RemoteLink::flushKeys() {
  if (keys_) xQueueReset(keys_);
}

bool RemoteLink::isDown(Key k) const {
  return (held_ >> static_cast<uint8_t>(k)) & 1;
}
