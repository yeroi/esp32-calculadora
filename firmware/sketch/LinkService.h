// =============================================================================
//  LinkService.h  —  SciCalc Link (Wi-Fi + Bluetooth) y Bluetooth real
// -----------------------------------------------------------------------------
//  Una tarea en el CORE 0 hace todo lo que puede bloquear, para que la UI
//  nunca se congele:
//
//    * SERVIDOR SciCalc Link (el mismo protocolo que el simulador: una
//      petición JSON por línea, una respuesta por línea):
//        - Wi-Fi: TCP en el puerto 8266 mientras haya conexión.
//        - Bluetooth: puerto serie SPP. En el PC: Agregar dispositivo >
//          "SciCalc-XXXX" -> Windows crea un COM -> SciCalc Link (Bluetooth).
//      hello / info / ls / get / confirm / put / mkdir / rm / done / wifi.
//      La calculadora PREGUNTA en pantalla al conectar y antes de escribir.
//
//    * BLUETOOTH (Classic SPP):
//        - "que se conecten a mí": encendido = visible como SciCalc-XXXX.
//        - "conectarme a otro": buscar dispositivos (~10 s) y conectar como
//          maestro. Con otra calculadora se le pueden ENVIAR scripts (el
//          protocolo Link, pero siendo nosotros el cliente).
//
//  La UI solo pide cosas (request*) y lee una copia del estado (snapshot()).
// =============================================================================
#pragma once
#include <Arduino.h>
#include <vector>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include "Dialog.h"
#include "Storage.h"
#include "SystemState.h"

class LinkService {
 public:
  enum class Bt : uint8_t { Off, Starting, Visible, ClientIn, Scanning, Connecting, ConnectedOut, Failed };

  struct Device {
    String name;
    String addr;                // "aa:bb:cc:dd:ee:ff"
    int rssi;
  };

  struct Snapshot {
    Bt bt = Bt::Off;
    String btText;              // estado legible
    String peer;                // con quién estamos conectados
    std::vector<Device> devices;
    uint32_t devStamp = 0;      // cambia con cada búsqueda
    String sendText;            // progreso / resultado del último envío
    bool sending = false;
    uint8_t clients = 0;        // conexiones SciCalc Link aceptadas
  };

  void begin(Storage& sd, DialogManager& dlg, SystemState& st);

  // ---- Desde la UI (no bloquean) ------------------------------------------------
  void requestBt(bool on);
  void requestScan();
  void requestConnect(const String& addr, const String& name);
  void requestDisconnect();
  void requestSend(const String& path);     // enviar un archivo al dispositivo conectado
  Snapshot snapshot();
  uint32_t stamp() const { return stamp_; } // cambia cuando cambia el estado
  String btName() const;

  // Red Wi-Fi recibida por SciCalc Link ("wifi"): la recoge la UI
  bool takeWifi(String& ssid, String& pass);

 private:
  struct Cmd {
    enum Kind : uint8_t { BtOn, BtOff, Scan, Connect, Disconnect, Send } kind;
    String a, b;
  };
  struct Conn {                             // una conexión que habla el protocolo
    Stream* s = nullptr;
    String buf;
    bool ok = false;                        // hello aceptado
    bool op = false;                        // operación confirmada
    String name = "PC";
    const char* transport = "";
  };

  static void taskEntry(void* arg);
  void loop();
  void runCmd(const Cmd& c);
  void serve(Conn& c);
  String handle(const String& line, Conn& c);
  bool clientRequest(Stream& s, const String& req, String& reply, uint32_t timeoutMs);
  void sendFile(const String& path);
  void setBt(Bt b, const String& text);
  void touch() { stamp_++; }

  Storage* sd_ = nullptr;
  DialogManager* dlg_ = nullptr;
  SystemState* st_ = nullptr;
  SemaphoreHandle_t mtx_ = nullptr;
  std::vector<Cmd> cmds_;                   // pedidos de la UI (protegido por mtx_)
  volatile uint32_t stamp_ = 0;
  Snapshot snap_;                           // protegido por mtx_
  String wifiSsid_, wifiPass_;
  bool wifiNew_ = false;
};

extern LinkService linkService;
