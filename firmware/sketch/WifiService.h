// =============================================================================
//  WifiService.h  —  Wi-Fi real: buscar redes, conectar, recordar, IP/DNS
// -----------------------------------------------------------------------------
//  * Buscar redes es asíncrono (WiFi.scanNetworks(true)): la UI no se queda
//    congelada los ~2-3 s que tarda; update() recoge el resultado.
//  * Las redes con contraseña se recuerdan en la NVS (Preferences, espacio
//    "wifi"), hasta MAX_SAVED. Al encender se conecta sola a la más fuerte
//    de las que conoce.
//  * IP automática (DHCP) o fija: IP, máscara, puerta de enlace y 2 DNS,
//    también guardadas en la NVS.
//  * Mantiene SystemState (wifiOn / wifiConnected / wifiSsid) al día para la
//    barra de estado.
//  Todo se llama desde la tarea de la UI (loop): no hace falta mutex.
// =============================================================================
#pragma once
#include <Arduino.h>
#include <IPAddress.h>
#include <vector>
#include "SystemState.h"

class WifiService {
 public:
  enum class Status : uint8_t { Off, Idle, Scanning, Connecting, Connected, Failed };

  struct Net {
    String ssid;
    int32_t rssi;
    bool secure;
    uint8_t channel;
    bool saved;                 // tenemos su contraseña
  };

  struct IpCfg {
    bool dhcp = true;
    IPAddress ip, mask{255, 255, 255, 0}, gw, dns1{8, 8, 8, 8}, dns2{1, 1, 1, 1};
  };

  static constexpr uint8_t MAX_SAVED = 6;

  void begin(SystemState& st);          // lee la NVS; si estaba encendido, enciende
  void update();                        // llamar en cada vuelta del bucle

  void setOn(bool on);
  bool on() const { return st_ && st_->wifiOn; }
  Status status() const { return status_; }
  String statusText() const;

  bool startScan();
  const std::vector<Net>& nets() const { return nets_; }
  uint32_t scanStamp() const { return scanStamp_; }     // cambia con cada búsqueda

  // Conecta (pass vacío = red abierta o contraseña guardada)
  void connect(const String& ssid, const String& pass);
  void disconnect();
  bool savedPass(const String& ssid, String& pass);
  void forget(const String& ssid);

  IpCfg ipCfg() const { return ip_; }
  void setIpCfg(const IpCfg& c);        // guarda y, si está conectado, reconecta

  // Datos de la conexión actual (vacíos si no hay)
  String localIp() const;
  String mask() const;
  String gateway() const;
  String dns(uint8_t i) const;
  String mac() const;
  int32_t rssi() const;
  uint8_t channel() const;

  // Resuelve un nombre (p. ej. "google.com"). Bloquea hasta ~3 s.
  String dnsTest(const char* host);

  static uint8_t bars(int32_t rssi);    // 0..4

 private:
  void applyIpCfg();
  void loadSaved();
  void storeSaved();
  void autoConnect();

  SystemState* st_ = nullptr;
  Status status_ = Status::Off;
  std::vector<Net> nets_;
  uint32_t scanStamp_ = 0;
  uint32_t connectT_ = 0;
  String target_;                       // red a la que se intenta conectar
  String pendingPass_;                  // contraseña a guardar si conecta
  IpCfg ip_;
  struct Saved { String ssid, pass; };
  std::vector<Saved> saved_;
  bool autoTried_ = false;
};

extern WifiService wifi;
