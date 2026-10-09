// =============================================================================
//  RemoteLink.h  —  Enlace con el PC por USB-serie ("modo PC")
// -----------------------------------------------------------------------------
//  Con SCICALC_REMOTE = 1 el ESP32 no tiene pantalla, teclado ni SD propios:
//  el programa pc/scicalc_pantalla.py hace de periféricos.
//
//    ESP32 -> PC : órdenes de dibujo, tonos, estado del sistema, peticiones
//                  de archivos (la "MicroSD" es una carpeta del PC)
//    PC -> ESP32 : saludo, teclas (pulsar/soltar), respuestas de archivos,
//                  parámetros simulados (batería)
//
//  Trama (igual en los dos sentidos):
//     A5 5A | tipo (1) | longitud (2, LE) | datos | suma (1)
//  suma = (tipo + long_lo + long_hi + datos) & 0xFF
//  Los bytes que no forman una trama válida son texto de depuración
//  (Serial.printf): el PC los muestra en su consola. Así el monitor serie
//  sigue sirviendo aunque el cable lo use el modo PC.
//
//  Hilos: el dibujo (core 1) solo AÑADE tramas a un búfer protegido por un
//  mutex; una tarea en el core 0 vacía ese búfer cada pocos ms, lee lo que
//  llega del PC y gestiona la autorrepetición de teclas.
// =============================================================================
#pragma once
#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>
#include <freertos/task.h>
#include "Keyboard.h"

namespace Proto {
constexpr uint8_t SYNC0 = 0xA5, SYNC1 = 0x5A;
constexpr uint8_t VERSION = 1;
constexpr size_t  MAX_PAYLOAD = 4096;          // por trama, en los dos sentidos

// ---- ESP32 -> PC ------------------------------------------------------------
enum : uint8_t {
  HELLO      = 0x01,   // u8 versión, u16 ancho, u16 alto, texto "nombre vX"
  STATE      = 0x03,   // texto JSON con el estado del sistema (1 vez/s)
  FILL       = 0x10,   // i16 x, y, w, h, u16 color
  RECT       = 0x11,   // igual que FILL (solo borde)
  FILL_RR    = 0x12,   // i16 x, y, w, h, r, u16 color
  RECT_RR    = 0x13,
  TRI        = 0x14,   // i16 x0, y0, x1, y1, x2, y2, u16 color
  PIXELS     = 0x15,   // i16 x, y, w, h, u16[w*h] RGB565
  PIXELS_RLE = 0x16,   // i16 x, y, w, h, {u8 n, u16 color}...
  GLYPH      = 0x17,   // u16 id, u8[5] columnas (bit 0 = fila de arriba)
  TEXT       = 0x18,   // i16 x, y, u8 size, u16 fg, u16 bg, u8 bold, u8 n, u16 id[n]
  TONE       = 0x20,   // u16 Hz (0 = silencio), u16 ms. Se reproducen en orden.
  FS_REQ     = 0x40,   // u8 id, u8 op, datos de la operación
};
// ---- PC -> ESP32 --------------------------------------------------------------
enum : uint8_t {
  PC_HELLO = 0x81,     // u8 versión. El ESP32 responde HELLO y repinta todo.
  PC_KEY   = 0x82,     // u8 tecla (valor del enum Key), u8 1 = pulsada / 0 = soltada
  PC_SET   = 0x83,     // i8 batería % (-1 = ?), u8 cargando
  PC_PING  = 0x84,     // latido (1 por segundo)
  FS_RESP  = 0xC0,     // u8 id, u8 estado (0 = OK, si no errno), datos
};
// ---- Operaciones de archivos ----------------------------------------------------
enum : uint8_t {
  FS_STAT = 1,         // ruta                      -> u8 tipo (0 no, 1 arch, 2 carpeta), u32 tamaño
  FS_LIST = 2,         // u16 desde, ruta           -> u8 hay_más, {u8 tipo, u32 tamaño, u8 len, nombre}...
  FS_READ = 3,         // u32 offset, u16 len, ruta -> bytes
  FS_INFO = 4,         // (nada)                    -> u64 total, u64 libre
  // Escrituras: SOLO las pide el sandbox de Python tras preguntar al usuario
  FS_WRITE  = 5,       // u32 offset, u8 truncar, u16 len_ruta, ruta, datos -> (nada)
  FS_REMOVE = 6,       // ruta
  FS_RENAME = 7,       // u16 len_origen, origen, destino
  FS_MKDIR  = 8,       // ruta
  FS_RMDIR  = 9,       // ruta
};
}  // namespace Proto

class RemoteLink {
 public:
  bool begin(uint32_t baud);

  // true si el programa del PC está conectado (saludó y sigue latiendo)
  bool connected() const;
  bool waitConnected(uint32_t ms);
  // Cambia cada vez que el PC (re)conecta: hay que reenviar glifos y repintar
  uint32_t session() const { return session_; }

  // ---- Envío de tramas (cualquier tarea) -----------------------------------
  void send(uint8_t type, const uint8_t* data, size_t len);
  void flush();                          // fuerza el envío inmediato

  // ---- Petición/respuesta (archivos). Bloquea a la tarea que llama. --------
  // Devuelve los bytes de respuesta (>= 0) o -errno (-ETIMEDOUT si no hay PC).
  int request(uint8_t op, const uint8_t* req, size_t reqLen,
              uint8_t* resp, size_t respCap, uint32_t timeoutMs = 2000);

  // ---- Teclado -------------------------------------------------------------
  bool pollKey(KeyEvent& ev, uint32_t waitMs);
  void flushKeys();
  bool isDown(Key k) const;              // tecla mantenida (para juegos)

  // ---- Parámetros que manda el PC ------------------------------------------
  int8_t batteryPct() const { return battery_; }
  bool charging() const { return charging_; }

 private:
  static void taskEntry(void* arg);
  void taskLoop();
  void flushLocked();
  void rxByte(uint8_t b);
  void handleFrame(uint8_t type, const uint8_t* p, size_t n);
  void onKey(uint8_t key, bool down);
  void releaseAll();
  void sendHello();

  SemaphoreHandle_t txMutex_ = nullptr;
  SemaphoreHandle_t rpcMutex_ = nullptr;
  SemaphoreHandle_t rpcDone_ = nullptr;
  QueueHandle_t keys_ = nullptr;
  TaskHandle_t task_ = nullptr;

  uint8_t* tx_ = nullptr;
  size_t txLen_ = 0;
  static constexpr size_t TX_CAP = Proto::MAX_PAYLOAD + 512;

  // Recepción
  enum class Rx : uint8_t { Sync0, Sync1, Type, Len0, Len1, Data, Sum };
  Rx rxState_ = Rx::Sync0;
  uint8_t rxType_ = 0;
  uint16_t rxLen_ = 0, rxPos_ = 0;
  uint8_t rxSum_ = 0;
  uint8_t* rx_ = nullptr;

  volatile bool hello_ = false;
  volatile uint32_t lastRxMs_ = 0;
  volatile uint32_t session_ = 0;

  // Petición en curso
  volatile uint8_t rpcId_ = 0;
  volatile bool rpcWaiting_ = false;
  uint8_t* rpcResp_ = nullptr;
  size_t rpcCap_ = 0;
  volatile int rpcResult_ = 0;

  // Teclas mantenidas y autorrepetición
  volatile uint64_t held_ = 0;            // bit (valor del enum Key)
  Key repeatKey_ = Key::None;
  uint32_t nextRepeatAt_ = 0;

  volatile int8_t battery_ = -1;
  volatile bool charging_ = false;
};

extern RemoteLink remoteLink;

// Teclado "virtual": las teclas llegan del PC
class RemoteKeyboard : public IKeyboard {
 public:
  bool begin() override { return true; }
  bool poll(KeyEvent& ev, uint32_t waitMs = 0) override { return remoteLink.pollKey(ev, waitMs); }
  void flush() override { remoteLink.flushKeys(); }
};
