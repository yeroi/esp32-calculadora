// =============================================================================
//  WifiService.cpp  (ver WifiService.h)
// =============================================================================
#include "WifiService.h"
#include <Preferences.h>
#include <WiFi.h>
#include <algorithm>

WifiService wifi;

namespace {
constexpr uint32_t CONNECT_TIMEOUT_MS = 15000;
const char* NVS_NS = "wifi";

String ipStr(const IPAddress& a) { return a == IPAddress() ? String("-") : a.toString(); }
}  // namespace

uint8_t WifiService::bars(int32_t rssi) {
  if (rssi >= -55) return 4;
  if (rssi >= -67) return 3;
  if (rssi >= -77) return 2;
  if (rssi >= -87) return 1;
  return 0;
}

// ---- NVS -------------------------------------------------------------------------
void WifiService::loadSaved() {
  Preferences p;
  if (!p.begin(NVS_NS, true)) return;            // aún no existe: valores por defecto
  saved_.clear();
  uint8_t n = p.getUChar("n", 0);
  for (uint8_t i = 0; i < n && i < MAX_SAVED; i++) {
    char ks[6], kp[6];
    snprintf(ks, sizeof ks, "s%u", i);
    snprintf(kp, sizeof kp, "p%u", i);
    Saved s{p.getString(ks, ""), p.getString(kp, "")};
    if (s.ssid.length()) saved_.push_back(s);
  }
  ip_.dhcp = p.getBool("dhcp", true);
  ip_.ip = IPAddress(p.getUInt("ip", 0));
  ip_.mask = IPAddress(p.getUInt("mask", (uint32_t)IPAddress(255, 255, 255, 0)));
  ip_.gw = IPAddress(p.getUInt("gw", 0));
  ip_.dns1 = IPAddress(p.getUInt("dns1", (uint32_t)IPAddress(8, 8, 8, 8)));
  ip_.dns2 = IPAddress(p.getUInt("dns2", (uint32_t)IPAddress(1, 1, 1, 1)));
  if (st_) st_->wifiOn = p.getBool("on", false);
  p.end();
}

void WifiService::storeSaved() {
  Preferences p;
  if (!p.begin(NVS_NS, false)) return;
  p.putUChar("n", saved_.size());
  for (uint8_t i = 0; i < saved_.size(); i++) {
    char ks[6], kp[6];
    snprintf(ks, sizeof ks, "s%u", i);
    snprintf(kp, sizeof kp, "p%u", i);
    p.putString(ks, saved_[i].ssid);
    p.putString(kp, saved_[i].pass);
  }
  p.putBool("dhcp", ip_.dhcp);
  p.putUInt("ip", (uint32_t)ip_.ip);
  p.putUInt("mask", (uint32_t)ip_.mask);
  p.putUInt("gw", (uint32_t)ip_.gw);
  p.putUInt("dns1", (uint32_t)ip_.dns1);
  p.putUInt("dns2", (uint32_t)ip_.dns2);
  p.putBool("on", st_ && st_->wifiOn);
  p.end();
}

bool WifiService::savedPass(const String& ssid, String& pass) {
  for (const Saved& s : saved_)
    if (s.ssid == ssid) { pass = s.pass; return true; }
  return false;
}

void WifiService::forget(const String& ssid) {
  saved_.erase(std::remove_if(saved_.begin(), saved_.end(),
                              [&](const Saved& s) { return s.ssid == ssid; }),
               saved_.end());
  for (Net& n : nets_)
    if (n.ssid == ssid) n.saved = false;
  storeSaved();
  if (st_ && st_->wifiConnected && ssid == st_->wifiSsid) disconnect();
}

// ---- Encender / apagar -------------------------------------------------------------
void WifiService::begin(SystemState& st) {
  st_ = &st;
  loadSaved();
  if (st_->wifiOn && !st_->exam) {
    st_->wifiOn = false;
    setOn(true);                                   // se conectará sola tras buscar
  } else {
    st_->wifiOn = false;
  }
}

void WifiService::setOn(bool on) {
  if (!st_ || on == st_->wifiOn) return;
  st_->wifiOn = on;
  if (on) {
    WiFi.persistent(false);                        // las claves las guardamos nosotros
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    status_ = Status::Idle;
    autoTried_ = false;
    startScan();
  } else {
    WiFi.scanDelete();
    WiFi.disconnect(true, false);
    WiFi.mode(WIFI_OFF);
    status_ = Status::Off;
    nets_.clear();
    st_->wifiConnected = false;
    st_->wifiSsid[0] = '\0';
  }
  storeSaved();                                    // recuerda encendido/apagado
}

// ---- Buscar -------------------------------------------------------------------------
bool WifiService::startScan() {
  if (!on() || status_ == Status::Scanning) return false;
  int r = WiFi.scanNetworks(true /*async*/, false /*ocultas*/);
  if (r == WIFI_SCAN_FAILED) return false;
  if (status_ != Status::Connecting && status_ != Status::Connected) status_ = Status::Scanning;
  scanStamp_++;
  return true;
}

void WifiService::autoConnect() {
  // La red conocida con más señal
  const Net* best = nullptr;
  for (const Net& n : nets_)
    if (n.saved && (!best || n.rssi > best->rssi)) best = &n;
  if (best) connect(best->ssid, "");
}

// ---- Conectar ---------------------------------------------------------------------
void WifiService::applyIpCfg() {
  if (ip_.dhcp) WiFi.config(INADDR_NONE, INADDR_NONE, INADDR_NONE, INADDR_NONE);
  else WiFi.config(ip_.ip, ip_.gw, ip_.mask, ip_.dns1, ip_.dns2);
}

void WifiService::connect(const String& ssid, const String& pass) {
  if (!on()) setOn(true);
  String pw = pass;
  if (!pw.length()) savedPass(ssid, pw);
  WiFi.disconnect(false, false);
  applyIpCfg();
  WiFi.begin(ssid.c_str(), pw.length() ? pw.c_str() : nullptr);
  target_ = ssid;
  pendingPass_ = pw;
  connectT_ = millis();
  status_ = Status::Connecting;
  st_->wifiConnected = false;
  st_->wifiSsid[0] = '\0';
}

void WifiService::disconnect() {
  WiFi.disconnect(false, false);
  target_ = "";
  if (on()) status_ = Status::Idle;
  st_->wifiConnected = false;
  st_->wifiSsid[0] = '\0';
}

void WifiService::setIpCfg(const IpCfg& c) {
  ip_ = c;
  storeSaved();
  if (st_ && st_->wifiConnected) connect(String(st_->wifiSsid), "");
}

// ---- Bucle ----------------------------------------------------------------------------
void WifiService::update() {
  if (!st_) return;
  if (st_->exam && st_->wifiOn) setOn(false);      // modo examen: radio apagada
  if (!on()) return;

  // Resultado de la búsqueda
  int n = WiFi.scanComplete();
  if (n >= 0) {
    nets_.clear();
    for (int i = 0; i < n; i++) {
      String ssid = WiFi.SSID(i);
      if (!ssid.length()) continue;
      bool dup = false;                            // misma red en varios puntos: la mejor
      for (Net& x : nets_)
        if (x.ssid == ssid) {
          dup = true;
          if (WiFi.RSSI(i) > x.rssi) x.rssi = WiFi.RSSI(i);
        }
      if (dup) continue;
      String pw;
      nets_.push_back({ssid, WiFi.RSSI(i), WiFi.encryptionType(i) != WIFI_AUTH_OPEN,
                       (uint8_t)WiFi.channel(i), savedPass(ssid, pw)});
    }
    std::sort(nets_.begin(), nets_.end(), [](const Net& a, const Net& b) { return a.rssi > b.rssi; });
    WiFi.scanDelete();
    scanStamp_++;
    if (status_ == Status::Scanning) status_ = Status::Idle;
    if (!autoTried_ && !st_->wifiConnected && status_ != Status::Connecting) {
      autoTried_ = true;
      autoConnect();
    }
  } else if (n == WIFI_SCAN_FAILED && status_ == Status::Scanning) {
    status_ = Status::Idle;
  }

  // Estado de la conexión
  wl_status_t ws = WiFi.status();
  if (ws == WL_CONNECTED) {
    if (!st_->wifiConnected) {
      String ssid = WiFi.SSID();
      strncpy(st_->wifiSsid, ssid.c_str(), sizeof st_->wifiSsid - 1);
      st_->wifiSsid[sizeof st_->wifiSsid - 1] = '\0';
      st_->wifiConnected = true;
      status_ = Status::Connected;
      // Conectó: recuerda la contraseña (la más reciente, la primera)
      if (target_.length()) {
        saved_.erase(std::remove_if(saved_.begin(), saved_.end(),
                                    [&](const Saved& s) { return s.ssid == target_; }),
                     saved_.end());
        saved_.insert(saved_.begin(), Saved{target_, pendingPass_});
        if (saved_.size() > MAX_SAVED) saved_.resize(MAX_SAVED);
        storeSaved();
        for (Net& x : nets_)
          if (x.ssid == target_) x.saved = true;
      }
    }
  } else {
    if (st_->wifiConnected) {                      // se cayó la conexión
      st_->wifiConnected = false;
      st_->wifiSsid[0] = '\0';
      status_ = Status::Connecting;                // setAutoReconnect lo reintenta
      connectT_ = millis();
    }
    if (status_ == Status::Connecting &&
        (ws == WL_CONNECT_FAILED || ws == WL_NO_SSID_AVAIL ||
         millis() - connectT_ > CONNECT_TIMEOUT_MS)) {
      status_ = Status::Failed;
      WiFi.disconnect(false, false);
    }
  }
}

String WifiService::statusText() const {
  switch (status_) {
    case Status::Off: return "Apagado";
    case Status::Idle: return "Sin conectar";
    case Status::Scanning: return "Buscando redes...";
    case Status::Connecting: return "Conectando a " + target_ + "...";
    case Status::Connected: return String("Conectado a ") + (st_ ? st_->wifiSsid : "");
    case Status::Failed: return "No se pudo conectar a " + target_;
  }
  return "";
}

// ---- Datos ----------------------------------------------------------------------------
String WifiService::localIp() const { return st_ && st_->wifiConnected ? ipStr(WiFi.localIP()) : "-"; }
String WifiService::mask() const { return st_ && st_->wifiConnected ? ipStr(WiFi.subnetMask()) : "-"; }
String WifiService::gateway() const { return st_ && st_->wifiConnected ? ipStr(WiFi.gatewayIP()) : "-"; }
String WifiService::dns(uint8_t i) const { return st_ && st_->wifiConnected ? ipStr(WiFi.dnsIP(i)) : "-"; }
String WifiService::mac() const { return WiFi.macAddress(); }
int32_t WifiService::rssi() const { return st_ && st_->wifiConnected ? WiFi.RSSI() : 0; }
uint8_t WifiService::channel() const { return st_ && st_->wifiConnected ? WiFi.channel() : 0; }

String WifiService::dnsTest(const char* host) {
  if (!st_ || !st_->wifiConnected) return "sin conexión";
  IPAddress a;
  uint32_t t = millis();
  if (!WiFi.hostByName(host, a)) return "no responde";
  return a.toString() + " (" + String(millis() - t) + " ms)";
}
