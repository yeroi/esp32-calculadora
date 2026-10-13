// =============================================================================
//  LinkService.cpp  (ver LinkService.h)
// =============================================================================
#include "LinkService.h"
#include <ArduinoJson.h>
#include "config.h"
#if SCICALC_BT
#include <BluetoothSerial.h>
#endif
#include <WiFi.h>
#include <mbedtls/base64.h>
#include "PackageManifest.h"

LinkService linkService;

namespace {

constexpr uint16_t LINK_PORT = 8266;
constexpr size_t MAX_LINE = 8 * 1024;          // "put" de 3 KB en base64 + JSON
constexpr size_t MAX_GET = 24 * 1024;          // "get": archivos pequeños (paquetes.json...)
constexpr size_t SEND_CHUNK = 2048;            // bytes por "put" al enviar un archivo
constexpr uint32_t SCAN_MS = 10000;

#if SCICALC_BT
BluetoothSerial serialBt;
#else
// Sin Bluetooth: un "puerto" que nunca tiene nada (así el resto no cambia)
struct NoBt : public Stream {
  int available() override { return 0; }
  int read() override { return -1; }
  int peek() override { return -1; }
  size_t write(uint8_t) override { return 1; }
  bool begin(const String&, bool) { return false; }
  void end() {}
  bool hasClient() { return false; }
  bool connected() { return false; }
  bool disconnect() { return true; }
} serialBt;
#endif
WiFiServer server(LINK_PORT);
WiFiClient tcp;
bool serverOn = false;

// Dirección del que se conecta a nosotros por Bluetooth (callback del SPP)
volatile bool peerNew = false;
uint8_t peerAddr[6];
#if SCICALC_BT
void sppCallback(esp_spp_cb_event_t event, esp_spp_cb_param_t* param) {
  if (event == ESP_SPP_SRV_OPEN_EVT) {
    memcpy(peerAddr, param->srv_open.rem_bda, 6);
    peerNew = true;
  }
}
#endif

String addrStr(const uint8_t a[6]) {
  char b[18];
  snprintf(b, sizeof b, "%02x:%02x:%02x:%02x:%02x:%02x", a[0], a[1], a[2], a[3], a[4], a[5]);
  return b;
}

String b64encode(const uint8_t* data, size_t n) {
  size_t olen = 0;
  mbedtls_base64_encode(nullptr, 0, &olen, data, n);
  String out;
  char* buf = (char*)malloc(olen + 1);
  if (!buf) return out;
  if (mbedtls_base64_encode((uint8_t*)buf, olen + 1, &olen, data, n) == 0) {
    buf[olen] = 0;
    out = buf;
  }
  free(buf);
  return out;
}

// Solo se escribe en /lib y /scripts (igual que el simulador)
bool writable(const String& p) {
  return Path::isSafe(p) && (p == "/lib" || p == "/scripts" || p.startsWith("/lib/") ||
                             p.startsWith("/scripts/"));
}

}  // namespace

// ---- Arranque ---------------------------------------------------------------------
void LinkService::begin(Storage& sd, DialogManager& dlg, SystemState& st) {
  sd_ = &sd;
  dlg_ = &dlg;
  st_ = &st;
  mtx_ = xSemaphoreCreateMutex();
  snap_.btText = "Apagado";
  xTaskCreatePinnedToCore(taskEntry, "link", 8192, this, 1, nullptr, CORE_SERVICES);
}

String LinkService::btName() const {
  // "SciCalc-XXXX" con los 2 últimos bytes de la MAC: único por placa
  uint64_t mac = ESP.getEfuseMac();
  char buf[16];
  snprintf(buf, sizeof buf, "SciCalc-%02X%02X", (unsigned)((mac >> 32) & 0xFF),
           (unsigned)((mac >> 40) & 0xFF));
  return String(buf);
}

// ---- Pedidos de la UI -------------------------------------------------------------
void LinkService::requestBt(bool on) {
  xSemaphoreTake(mtx_, portMAX_DELAY);
  cmds_.push_back({on ? Cmd::BtOn : Cmd::BtOff, "", ""});
  xSemaphoreGive(mtx_);
}
void LinkService::requestScan() {
  xSemaphoreTake(mtx_, portMAX_DELAY);
  cmds_.push_back({Cmd::Scan, "", ""});
  xSemaphoreGive(mtx_);
}
void LinkService::requestConnect(const String& addr, const String& name) {
  xSemaphoreTake(mtx_, portMAX_DELAY);
  cmds_.push_back({Cmd::Connect, addr, name});
  xSemaphoreGive(mtx_);
}
void LinkService::requestDisconnect() {
  xSemaphoreTake(mtx_, portMAX_DELAY);
  cmds_.push_back({Cmd::Disconnect, "", ""});
  xSemaphoreGive(mtx_);
}
void LinkService::requestSend(const String& path) {
  xSemaphoreTake(mtx_, portMAX_DELAY);
  cmds_.push_back({Cmd::Send, path, ""});
  snap_.sending = true;
  snap_.sendText = "En cola: " + Path::name(path);
  xSemaphoreGive(mtx_);
  touch();
}

LinkService::Snapshot LinkService::snapshot() {
  xSemaphoreTake(mtx_, portMAX_DELAY);
  Snapshot s = snap_;
  xSemaphoreGive(mtx_);
  return s;
}

bool LinkService::takeWifi(String& ssid, String& pass) {
  bool r = false;
  xSemaphoreTake(mtx_, portMAX_DELAY);
  if (wifiNew_) {
    ssid = wifiSsid_;
    pass = wifiPass_;
    wifiNew_ = false;
    r = true;
  }
  xSemaphoreGive(mtx_);
  return r;
}

void LinkService::setBt(Bt b, const String& text) {
  xSemaphoreTake(mtx_, portMAX_DELAY);
  snap_.bt = b;
  snap_.btText = text;
  if (b != Bt::ClientIn && b != Bt::ConnectedOut) snap_.peer = "";
  xSemaphoreGive(mtx_);
  st_->btOn = b != Bt::Off;
  touch();
}

// ---- Tarea ----------------------------------------------------------------------------
void LinkService::taskEntry(void* arg) { static_cast<LinkService*>(arg)->loop(); }

void LinkService::loop() {
  Conn tcpConn, btConn;
  for (;;) {
    // 1) Pedidos de la UI
    std::vector<Cmd> todo;
    xSemaphoreTake(mtx_, portMAX_DELAY);
    todo.swap(cmds_);
    xSemaphoreGive(mtx_);
    for (const Cmd& c : todo) runCmd(c);

    // Modo examen: sin radio
    if (st_->exam) {
      if (snap_.bt != Bt::Off) runCmd({Cmd::BtOff, "", ""});
      if (tcp) tcp.stop();
    }

    // 2) SciCalc Link por Wi-Fi (TCP 8266)
    if (st_->wifiConnected && !st_->exam) {
      if (!serverOn) {
        server.begin();
        serverOn = true;
      }
      if (!tcp || !tcp.connected()) {
        if (tcpConn.ok && st_->linkClients) st_->linkClients--;
        tcpConn = Conn();
        WiFiClient c = server.available();
        if (c) {
          tcp = c;
          tcpConn.s = &tcp;
          tcpConn.transport = "Wi-Fi";
        }
      }
      if (tcpConn.s && tcp.connected()) serve(tcpConn);
    } else if (serverOn) {
      tcp.stop();
      server.end();
      serverOn = false;
      if (tcpConn.ok && st_->linkClients) st_->linkClients--;
      tcpConn = Conn();
    }

    // 3) Bluetooth: alguien conectado a nosotros (PC con SciCalc Link u otra calculadora)
    Bt b = snap_.bt;
    if (b == Bt::Visible || b == Bt::ClientIn) {
      bool has = serialBt.hasClient();
      if (has && b == Bt::Visible) {
        btConn = Conn();
        btConn.s = &serialBt;
        btConn.transport = "Bluetooth";
        setBt(Bt::ClientIn, "Conectado: " + (peerNew ? addrStr(peerAddr) : String("?")));
        xSemaphoreTake(mtx_, portMAX_DELAY);
        snap_.peer = peerNew ? addrStr(peerAddr) : String("?");
        xSemaphoreGive(mtx_);
      } else if (!has && b == Bt::ClientIn) {
        if (btConn.ok && st_->linkClients) st_->linkClients--;
        btConn = Conn();
        setBt(Bt::Visible, "Visible como " + btName());
      }
      if (has) serve(btConn);
    } else if (b == Bt::ConnectedOut && !serialBt.connected()) {
      runCmd({Cmd::Disconnect, "", ""});           // el otro se fue
    }

    xSemaphoreTake(mtx_, portMAX_DELAY);
    snap_.clients = st_->linkClients;
    xSemaphoreGive(mtx_);
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}

void LinkService::runCmd(const Cmd& c) {
  String name = btName();
  switch (c.kind) {
    case Cmd::BtOn:
      if (snap_.bt != Bt::Off || st_->exam) break;
#if !SCICALC_BT
      setBt(Bt::Off, "Compilado sin Bluetooth (SCICALC_BT 0)");
      break;
#else
      setBt(Bt::Starting, "Encendiendo...");
      serialBt.register_callback(sppCallback);
      if (serialBt.begin(name, false)) setBt(Bt::Visible, "Visible como " + name);
      else setBt(Bt::Off, "No se pudo encender (memoria)");
      break;
#endif

    case Cmd::BtOff:
      if (snap_.bt == Bt::Off) break;
      serialBt.end();
      setBt(Bt::Off, "Apagado");
      break;

    case Cmd::Scan: {
#if SCICALC_BT
      if (snap_.bt == Bt::Off || snap_.bt == Bt::ConnectedOut) break;
      setBt(Bt::Scanning, "Buscando dispositivos (10 s)...");
      // Buscar necesita el modo maestro; luego se vuelve a ser visible
      serialBt.end();
      std::vector<Device> found;
      if (serialBt.begin(name, true)) {
        BTScanResults* r = serialBt.discover(SCAN_MS);
        if (r) {
          for (int i = 0; i < r->getCount(); i++) {
            BTAdvertisedDevice* d = r->getDevice(i);
            Device dv;
            dv.addr = d->getAddress().toString();
            dv.name = d->haveName() ? String(d->getName().c_str()) : dv.addr;
            dv.rssi = d->haveRSSI() ? d->getRSSI() : -99;
            found.push_back(dv);
          }
        }
        serialBt.end();
      }
      xSemaphoreTake(mtx_, portMAX_DELAY);
      snap_.devices = found;
      snap_.devStamp++;
      xSemaphoreGive(mtx_);
      serialBt.begin(name, false);
      setBt(Bt::Visible, found.empty() ? String("No se encontró nada · visible")
                                       : String(found.size()) + " encontrados · visible");
#endif
      break;
    }

    case Cmd::Connect: {
      if (snap_.bt == Bt::Off) break;
      setBt(Bt::Connecting, "Conectando a " + c.b + "...");
      serialBt.end();
#if SCICALC_BT
      bool ok = serialBt.begin(name, true) && serialBt.connect(BTAddress(c.a));
#else
      bool ok = false;
#endif
      if (ok) {
        setBt(Bt::ConnectedOut, "Conectado a " + c.b);
        xSemaphoreTake(mtx_, portMAX_DELAY);
        snap_.peer = c.b;
        xSemaphoreGive(mtx_);
      } else {
        serialBt.end();
        serialBt.begin(name, false);
        setBt(Bt::Visible, "No se pudo conectar a " + c.b);
      }
      break;
    }

    case Cmd::Disconnect:
      if (snap_.bt == Bt::ConnectedOut) {
        serialBt.disconnect();
        serialBt.end();
        serialBt.begin(name, false);
        setBt(Bt::Visible, "Desconectado · visible");
      } else if (snap_.bt == Bt::ClientIn) {
        serialBt.disconnect();
      }
      break;

    case Cmd::Send:
      sendFile(c.a);
      break;
  }
}

// ---- Servidor: una línea cada vez -------------------------------------------------------
void LinkService::serve(Conn& c) {
  while (c.s && c.s->available()) {
    int ch = c.s->read();
    if (ch < 0) break;
    if (ch == '\r') continue;
    if (ch != '\n') {
      if (c.buf.length() < MAX_LINE) c.buf += (char)ch;
      continue;
    }
    String line = c.buf;
    c.buf = "";
    if (!line.length()) continue;
    String reply = handle(line, c);
    c.s->print(reply);
    c.s->print('\n');
    c.s->flush();
    break;                                       // una petición por vuelta: la UI respira
  }
}

String LinkService::handle(const String& line, Conn& c) {
  JsonDocument req, rep;
  if (deserializeJson(req, line)) {
    rep["ok"] = false;
    rep["error"] = "JSON no válido";
  } else {
    rep["id"] = req["id"];
    String cmd = req["cmd"] | "";
    auto fail = [&](const char* e) {
      rep["ok"] = false;
      rep["error"] = e;
    };
    if (st_->exam) {
      fail("la calculadora está en MODO EXAMEN");
    } else if (cmd == "hello") {
      String name = String(req["client"] | "PC").substring(0, 24);
      DlgAnswer a = dlg_->askBlocking("SciCalc Link",
          {"'" + name + "' quiere conectarse", String("por ") + c.transport + ".", "",
           "Podrá instalar paquetes y scripts.", "Cada operación te la preguntaré.", "",
           "¿Aceptar la conexión?"});
      if (a == DlgAnswer::No) {
        fail("conexión rechazada en la calculadora");
      } else {
        if (!c.ok) st_->linkClients++;
        c.ok = true;
        c.name = name;
        rep["ok"] = true;
        rep["device"] = "ESP32 SciCalc";
        rep["fw"] = FW_VERSION;
        rep["transport"] = c.transport;
      }
    } else if (!c.ok) {
      fail("no autorizado (falta hello)");
    } else if (cmd == "info") {
      rep["ok"] = true;
      rep["device"] = "ESP32 SciCalc";
      rep["fw"] = FW_VERSION;
      rep["free_kb"] = (uint32_t)(sd_->freeBytes() / 1024);
      rep["packages"] = (uint32_t)PackageManifest::read(*sd_).size();
      rep["wifi"] = st_->wifiConnected ? st_->wifiSsid : "";
    } else if (cmd == "ls") {
      String p = req["path"] | "/";
      std::vector<DirEntry> es;
      if (!Path::isSafe(p)) {
        fail("ruta fuera de la SD");
      } else {
        rep["ok"] = true;
        JsonArray arr = rep["entries"].to<JsonArray>();
        if (sd_->listDir(p, es, false)) {
          for (const DirEntry& e : es) {
            JsonObject o = arr.add<JsonObject>();
            o["name"] = e.name;
            o["dir"] = e.dir;
            o["size"] = e.size;
          }
        }
      }
    } else if (cmd == "get") {
      String p = req["path"] | "";
      uint32_t size = 0;
      if (!Path::isSafe(p) || sd_->stat(p, size) != 1) {
        fail("no existe");
      } else if (size > MAX_GET) {
        fail("archivo demasiado grande para get");
      } else {
        uint8_t* buf = (uint8_t*)malloc(size ? size : 1);
        if (!buf) {
          fail("sin memoria");
        } else {
          size_t n = sd_->readAt(p, 0, buf, size);
          rep["ok"] = true;
          rep["data"] = b64encode(buf, n);
          free(buf);
        }
      }
    } else if (cmd == "confirm") {
      std::vector<String> lines;
      JsonArray in = req["lines"].as<JsonArray>();
      for (JsonVariant v : in) {
        if (lines.size() >= 8) break;
        lines.push_back(String(v.as<const char*>() ? v.as<const char*>() : "").substring(0, 40));
      }
      lines.push_back("");
      lines.push_back("¿Aceptar?");
      String title = String(req["title"] | "SciCalc Link").substring(0, 24);
      c.op = dlg_->askBlocking(title.c_str(), lines) != DlgAnswer::No;
      rep["ok"] = true;
      rep["accepted"] = c.op;
    } else if (cmd == "done") {
      c.op = false;
      rep["ok"] = true;
    } else if (cmd == "wifi") {
      String ssid = String(req["ssid"] | "").substring(0, 32);
      DlgAnswer a = dlg_->askBlocking("Red Wi-Fi", {"'" + c.name + "' quiere guardar", "la red Wi-Fi:",
                                                    "  " + ssid, "", "¿Guardarla y conectar?"});
      bool yes = a != DlgAnswer::No;
      if (yes) {
        xSemaphoreTake(mtx_, portMAX_DELAY);
        wifiSsid_ = ssid;
        wifiPass_ = req["password"] | "";
        wifiNew_ = true;
        xSemaphoreGive(mtx_);
      }
      rep["ok"] = true;
      rep["accepted"] = yes;
    } else if (cmd == "put" || cmd == "mkdir" || cmd == "rm") {
      String p = req["path"] | "";
      if (!c.op) {
        fail("operación no confirmada en la calculadora");
      } else if (!writable(p)) {
        fail("solo se puede escribir en /lib y /scripts");
      } else if (cmd == "put") {
        // crea las carpetas que falten
        for (int i = 1; (i = p.indexOf('/', i)) > 0; i++) sd_->makeDir(p.substring(0, i));
        const char* b64 = req["data"] | "";
        size_t inLen = strlen(b64), olen = 0;
        uint8_t* buf = (uint8_t*)malloc(inLen * 3 / 4 + 4);
        if (!buf) {
          fail("sin memoria");
        } else if (mbedtls_base64_decode(buf, inLen * 3 / 4 + 4, &olen, (const uint8_t*)b64, inLen)) {
          free(buf);
          fail("base64 no válido");
        } else {
          bool append = req["append"] | false;
          uint32_t off = 0;
          if (append) sd_->stat(p, off);
          int r = sd_->writeAt(p, off, buf, olen, !append);
          free(buf);
          if (r < 0) fail("no se pudo escribir");
          else rep["ok"] = true;
        }
      } else if (cmd == "mkdir") {
        for (int i = 1; (i = p.indexOf('/', i)) > 0; i++) sd_->makeDir(p.substring(0, i));
        sd_->makeDir(p);
        rep["ok"] = true;
      } else {
        uint32_t sz;
        int k = sd_->stat(p, sz);
        if (k == 1) sd_->removeFile(p);
        else if (k == 2) {
          // borrado recursivo (paquetes): primero el contenido
          std::vector<String> stack{p}, dirs;
          while (!stack.empty()) {
            String d = stack.back();
            stack.pop_back();
            dirs.push_back(d);
            std::vector<DirEntry> es;
            if (!(req["recursive"] | false)) break;
            sd_->listDir(d, es, false);
            for (const DirEntry& e : es) {
              String q = Path::join(d, e.name);
              if (e.dir) stack.push_back(q);
              else sd_->removeFile(q);
            }
          }
          for (size_t i = dirs.size(); i-- > 0;) sd_->removeDir(dirs[i]);
        }
        rep["ok"] = true;
      }
    } else {
      fail("comando desconocido");
    }
  }
  String out;
  serializeJson(rep, out);
  return out;
}

// ---- Cliente: enviar un archivo a la calculadora a la que estamos conectados ------------
bool LinkService::clientRequest(Stream& s, const String& req, String& reply, uint32_t timeoutMs) {
  while (s.available()) s.read();                // restos de antes
  s.print(req);
  s.print('\n');
  s.flush();
  reply = "";
  uint32_t t0 = millis();
  while (millis() - t0 < timeoutMs) {
    while (s.available()) {
      int ch = s.read();
      if (ch == '\n') return true;
      if (ch != '\r' && reply.length() < 2048) reply += (char)ch;
    }
    if (snap_.bt != Bt::ConnectedOut || !serialBt.connected()) return false;
    vTaskDelay(pdMS_TO_TICKS(10));
  }
  return false;
}

void LinkService::sendFile(const String& path) {
  auto progress = [&](const String& t, bool busy) {
    xSemaphoreTake(mtx_, portMAX_DELAY);
    snap_.sendText = t;
    snap_.sending = busy;
    xSemaphoreGive(mtx_);
    touch();
  };
  if (snap_.bt != Bt::ConnectedOut) return progress("No hay ningún dispositivo conectado", false);
  uint32_t size = 0;
  if (sd_->stat(path, size) != 1) return progress("No existe " + path, false);
  String fname = Path::name(path);
  JsonDocument d;
  String req, rep;
  auto ok = [&](const String& r, const char* key) {
    JsonDocument j;
    if (deserializeJson(j, r)) return false;
    return (bool)(j[key] | false);
  };

  progress("Esperando a que acepte...", true);
  d["cmd"] = "hello";
  d["client"] = btName();
  serializeJson(d, req);
  if (!clientRequest(serialBt, req, rep, 70000) || !ok(rep, "ok"))
    return progress("No aceptó la conexión", false);

  d.clear();
  req = "";
  d["cmd"] = "confirm";
  d["title"] = "Recibir archivo";
  JsonArray ls = d["lines"].to<JsonArray>();
  ls.add("De: " + btName());
  ls.add("Archivo: " + fname);
  ls.add("Tamaño: " + humanSize(size));
  ls.add("Se guardará en /scripts");
  serializeJson(d, req);
  if (!clientRequest(serialBt, req, rep, 70000) || !ok(rep, "accepted"))
    return progress("No aceptó el archivo", false);

  uint8_t* buf = (uint8_t*)malloc(SEND_CHUNK);
  if (!buf) return progress("Sin memoria", false);
  uint32_t off = 0;
  bool good = true;
  do {
    size_t n = sd_->readAt(path, off, buf, SEND_CHUNK);
    d.clear();
    req = "";
    d["cmd"] = "put";
    d["path"] = "/scripts/" + fname;
    d["data"] = b64encode(buf, n);
    d["append"] = off > 0;
    serializeJson(d, req);
    if (!clientRequest(serialBt, req, rep, 15000) || !ok(rep, "ok")) {
      good = false;
      break;
    }
    off += n;
    progress("Enviando " + fname + "  " + String(size ? off * 100 / size : 100) + " %", true);
    if (!n) break;
  } while (off < size);
  free(buf);
  clientRequest(serialBt, "{\"cmd\":\"done\"}", rep, 5000);
  progress(good ? "Enviado: " + fname : "Se cortó el envío", false);
}
