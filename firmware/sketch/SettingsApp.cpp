// =============================================================================
//  SettingsApp.cpp
// =============================================================================
#include "SettingsApp.h"
#include "LinkService.h"
#include "config.h"

namespace {
  constexpr int16_t ROW_X = 6, ROW_W = Display::W - 12;
  constexpr int16_t ROW_Y0 = Display::BODY_Y + 5;
  constexpr int16_t ROW_STEP = 27, ROW_H = 23;
  constexpr uint8_t VISIBLE = 6;
  constexpr int16_t INFO_LINE_H = 11;

  const char* const PAGE_TITLES[] = {"Ajustes", "Ajustes › Wi-Fi", "Wi-Fi › Conexión",
                                     "Wi-Fi › IP y DNS", "Ajustes › Bluetooth",
                                     "Bluetooth › Enviar", "Ajustes › USB",
                                     "Ajustes › Paquetes", "Ajustes › Acerca de"};
  const char* const IP_NAMES[] = {"IP", "Máscara", "Puerta de enlace", "DNS 1", "DNS 2"};

  String ipOrDash(const IPAddress& a) { return a == IPAddress() ? String("-") : a.toString(); }
}

void SettingsApp::onEnter() {
  page_ = Page::Main;
  edit_ = Edit::None;
  pkgs_ = PackageManifest::read(sd());
  list_.sel = selMemo_[0];
  list_.top = 0;
}

IPAddress& SettingsApp::ipField(uint8_t i) {
  switch (i) {
    case 0: return ipEdit_.ip;
    case 1: return ipEdit_.mask;
    case 2: return ipEdit_.gw;
    case 3: return ipEdit_.dns1;
    default: return ipEdit_.dns2;
  }
}

// ---- Modelo de cada página ------------------------------------------------------
void SettingsApp::buildRows() {
  SystemState& s = st();
  rows_.clear();
  auto add = [&](const String& label, const String& value, Action a, uint16_t color = 0,
                 const String& arg = "") -> Row& {
    Row r;
    r.label = label;
    r.value = value;
    r.action = a;
    r.color = color;
    r.arg = arg;
    rows_.push_back(r);
    return rows_.back();
  };
  LinkService::Snapshot ln = linkService.snapshot();
  switch (page_) {
    case Page::Main: {
      String wv = s.wifiConnected ? String(s.wifiSsid) : String(s.wifiOn ? "Encendido" : "Apagado");
      add("Wi-Fi", wv, Action::GoWifi, s.wifiConnected ? Theme::OK : 0);
      String bv = ln.bt == LinkService::Bt::Off ? "Apagado"
                  : ln.peer.length()            ? "Conectado"
                                                : "Visible";
      add("Bluetooth", bv, Action::GoBt, s.btOn ? Theme::OK : 0);
      add("USB", "Serie · SciCalc Link", Action::GoUsb);
      add("Modo examen", s.exam ? "ACTIVADO" : "Desactivado", Action::ToggleExam,
          s.exam ? Theme::WARN : 0);
      add("Paquetes Python", String(pkgs_.size()) + " instalados", Action::GoPkgs);
      add("Acerca de", "v" FW_VERSION_STR, Action::GoAbout);
      break;
    }
    case Page::Wifi:
      add("Wi-Fi", s.wifiOn ? "Encendido" : "Apagado", Action::ToggleWifi, s.wifiOn ? Theme::OK : 0);
      if (!s.wifiOn) break;
      add("Buscar redes", wifi.status() == WifiService::Status::Scanning ? "buscando..." : "EXE",
          Action::WifiScan);
      add("Conexión", s.wifiConnected ? wifi.localIp() : String("-"), Action::GoWifiInfo,
          s.wifiConnected ? Theme::OK : 0);
      add("IP y DNS", wifi.ipCfg().dhcp ? "Automática (DHCP)" : "Fija", Action::GoIp);
      for (const WifiService::Net& n : wifi.nets()) {
        bool conn = s.wifiConnected && n.ssid == s.wifiSsid;
        Row& r = add(n.ssid, n.saved && !conn ? "guardada" : "", Action::WifiNet, 0, n.ssid);
        r.bars = WifiService::bars(n.rssi);
        r.lock = n.secure;
        r.check = conn;
      }
      break;
    case Page::WifiInfo:
      add("Red", s.wifiConnected ? String(s.wifiSsid) : "-", Action::None);
      add("IP local", wifi.localIp(), Action::None);
      add("Máscara de subred", wifi.mask(), Action::None);
      add("Puerta de enlace", wifi.gateway(), Action::None);
      add("DNS 1", wifi.dns(0), Action::None);
      add("DNS 2", wifi.dns(1), Action::None);
      add("MAC", wifi.mac(), Action::None);
      add("Señal", s.wifiConnected ? String(wifi.rssi()) + " dBm" : "-", Action::None);
      add("Canal", s.wifiConnected ? String(wifi.channel()) : "-", Action::None);
      add("Probar DNS (google.com)", dnsResult_.length() ? dnsResult_ : "EXE", Action::DnsTest);
      if (s.wifiConnected) {
        add("Desconectar", "", Action::WifiDisconnect, Theme::WARN);
        add("Olvidar esta red", "", Action::WifiForget, Theme::ERR, s.wifiSsid);
      }
      break;
    case Page::Ip:
      add("Modo", ipEdit_.dhcp ? "Automática (DHCP)" : "IP fija", Action::IpMode);
      if (!ipEdit_.dhcp)
        for (uint8_t i = 0; i < 5; i++) add(IP_NAMES[i], ipOrDash(ipField(i)), Action::IpField, 0, String(i));
      add("Guardar y aplicar", "", Action::IpApply, Theme::OK);
      break;
    case Page::Bt: {
      bool on = ln.bt != LinkService::Bt::Off;
      add("Bluetooth", on ? "Encendido" : "Apagado", Action::ToggleBt, on ? Theme::OK : 0);
      add("Nombre", linkService.btName(), Action::None);
      add("Estado", ln.btText, Action::None, ln.peer.length() ? Theme::OK : 0);
      if (!on) break;
      if (ln.bt == LinkService::Bt::ConnectedOut) {
        add("Enviar un archivo", ln.sending ? "enviando..." : "EXE", Action::GoBtSend);
        add("Desconectar", ln.peer, Action::BtDisconnect, Theme::WARN);
      } else if (ln.bt == LinkService::Bt::ClientIn) {
        add("Desconectar", ln.peer, Action::BtDisconnect, Theme::WARN);
      } else {
        add("Buscar dispositivos",
            ln.bt == LinkService::Bt::Scanning ? "buscando..." : "EXE", Action::BtScan);
        for (const LinkService::Device& d : ln.devices) {
          Row& r = add(d.name, d.name == d.addr ? "" : d.addr, Action::BtDevice, 0, d.addr);
          r.bars = WifiService::bars(d.rssi);
        }
      }
      break;
    }
    case Page::Usb:
      add("Modo USB", "Serie (SciCalc Link)", Action::None, Theme::OK);
      add("Velocidad", SCICALC_REMOTE ? "921600 (modo PC)" : "115200 baudios", Action::None);
      add("Disco USB (MSC)", "requiere ESP32-S3", Action::InfoMsc);
      break;
    case Page::Pkgs:
      for (const PackageInfo& p : pkgs_)
        add(p.name, p.version + " · " + p.source, Action::Package, 0, p.name);
      break;
    default:
      break;
  }
  list_.reset(rows_.size(), VISIBLE);
}

std::vector<String> SettingsApp::infoLines() {
  SystemState& s = st();
  switch (page_) {
    case Page::Wifi:
      if (!s.wifiOn) return {"Enciende el Wi-Fi para ver las redes cercanas."};
      if (wifi.nets().empty() && wifi.status() != WifiService::Status::Scanning)
        return {wifi.statusText(), "No se ven redes: pulsa Buscar redes."};
      return {wifi.statusText()};
    case Page::WifiInfo:
      return {};
    case Page::Ip:
      return {"Con IP fija pon también la puerta de enlace", "y los DNS de tu router."};
    case Page::Bt: {
      LinkService::Snapshot ln = linkService.snapshot();
      if (ln.bt == LinkService::Bt::Off)
        return {"Encendido: el PC u otra calculadora te ve como",
                linkService.btName() + ". También puedes conectarte tú."};
      if (ln.bt == LinkService::Bt::ConnectedOut)
        return {ln.sendText.length() ? ln.sendText : String("Conectado: puedes enviarle archivos.")};
      return {"PC: Bluetooth > Agregar > " + linkService.btName() + " -> COM",
              "-> SciCalc Link (Bluetooth). EXE en un", "dispositivo de la lista para conectarte."};
    }
    case Page::Usb:
      return {"Conecta el cable USB y elige el puerto COM",
              "en SciCalc Link (USB). Mismo protocolo que",
              "Bluetooth y Wi-Fi (TCP 8266)."};
    case Page::Pkgs:
      if (pkgs_.empty())
        return {"No hay paquetes instalados.", "", "Instálalos desde el PC con SciCalc Link:",
                "se guardan en /lib de la MicroSD."};
      return {"EXE sobre un paquete para ver sus datos."};
    case Page::About: {
      char l[5][56];
      snprintf(l[0], sizeof l[0], "ESP32 SciCalc  v%s", FW_VERSION);
      snprintf(l[1], sizeof l[1], "Chip: %s rev %d · Flash %lu MB", ESP.getChipModel(),
               (int)ESP.getChipRevision(), (unsigned long)(ESP.getFlashChipSize() >> 20));
      snprintf(l[2], sizeof l[2], "Heap libre: %lu KB · PSRAM: %s",
               (unsigned long)(ESP.getFreeHeap() / 1024), ESP.getPsramSize() ? "sí" : "no");
      if (s.sdMounted) snprintf(l[3], sizeof l[3], "SD libre: %s", humanSize(sd().freeBytes()).c_str());
      else snprintf(l[3], sizeof l[3], "SD: no detectada");
      snprintf(l[4], sizeof l[4], "Paquetes: %u en /lib · Conexiones: %u",
               (unsigned)pkgs_.size(), (unsigned)s.linkClients);
      return {l[0], "Núcleo: C++ (FreeRTOS) · Scripts: MicroPython", l[1], l[2], l[3], l[4]};
    }
    default:
      return {};
  }
}

// ---- Dibujo ---------------------------------------------------------------------
void SettingsApp::drawRow(uint16_t i) {
  if (!list_.visible(i) || i >= rows_.size()) return;
  const Row& r = rows_[i];
  const int16_t y = ROW_Y0 + (i - list_.top) * ROW_STEP;
  const bool hi = i == list_.sel;
  const uint16_t bg = hi ? Theme::ACCENT : Theme::PANEL;
  gfx().fillRoundRect(ROW_X, y, ROW_W, ROW_H, 4, bg);
  uint16_t col = r.color ? r.color : (hi ? Theme::TEXT : Theme::MUTED);
  if (hi && r.color) col = Theme::TEXT;

  // A la derecha: barras de señal y candado (redes), o el valor
  int16_t right = ROW_X + ROW_W - 9;
  if (r.bars >= 0) {
    for (int8_t b = 0; b < 4; b++) {
      int16_t h = 4 + b * 3;
      gfx().fillRect(right - 22 + b * 6, y + 18 - h, 4, h,
                     b < r.bars ? (hi ? Theme::TEXT : Theme::OK) : Theme::DIM);
    }
    right -= 28;
    if (r.lock) {                                    // candado: arco + cuerpo
      gfx().drawRect(right - 6, y + 6, 6, 6, col);
      gfx().fillRect(right - 8, y + 10, 10, 7, col);
      right -= 14;
    }
  }
  int16_t vw = r.value.length() ? Display::textWidth(r.value.c_str(), 1) + 1 : 0;
  int16_t vx = right - vw;
  if (vw) gfx().textBold(vx, y + 8, r.value.c_str(), 1, col, bg);
  int16_t lx = ROW_X + 9;
  if (r.check) {
    gfx().textBold(lx, y + 8, "✓", 1, hi ? Theme::TEXT : Theme::OK, bg);
    lx += 12;
  }
  gfx().textBold(lx, y + 8, r.label.c_str(), 1, Theme::TEXT, bg, vx - lx - 8);
}

void SettingsApp::drawRows() {
  gfx().fillRect(0, ROW_Y0, Display::W, VISIBLE * ROW_STEP, Theme::BG);
  for (uint16_t i = list_.top; i < rows_.size() && i < list_.top + VISIBLE; ++i) drawRow(i);
}

void SettingsApp::drawInfo() {
  uint16_t shown = min<uint16_t>(rows_.size(), VISIBLE);
  int16_t y = ROW_Y0 + shown * ROW_STEP + 6;
  gfx().fillRect(0, y, Display::W, Display::FOOTER_Y - 2 - y, Theme::BG);
  if (edit_ != Edit::None) return drawEdit();
  for (const String& ln : infoLines()) {
    if (y + 8 > Display::FOOTER_Y - 4) break;
    gfx().text(12, y, ln.c_str(), 1, Theme::MUTED, Theme::BG, Align::Left, 0, false,
               Display::W - 20);
    y += INFO_LINE_H;
  }
}

// Panel de edición (T9) sobre la parte de abajo
void SettingsApp::drawEdit() {
  const int16_t y = Display::FOOTER_Y - 62;
  gfx().fillRoundRect(4, y, Display::W - 8, 58, 6, Theme::MODAL_BG);
  gfx().drawRoundRect(4, y, Display::W - 8, 58, 6, Theme::ACCENT);
  gfx().textBold(12, y + 5, editTitle_.c_str(), 1, Theme::ACCENT, Theme::MODAL_BG, Display::W - 24);
  gfx().fillRect(10, y + 17, Display::W - 20, 20, Theme::BG);
  String shown = t9_.shown();
  // si no cabe, se ve el final (lo que se está escribiendo)
  size_t maxChars = (Display::W - 28) / 12;
  size_t n = Display::utf8Length(shown.c_str());
  const char* p = shown.c_str();
  while (n > maxChars) {
    p++;
    while ((*p & 0xC0) == 0x80) p++;
    n--;
  }
  gfx().text(14, y + 19, p, 2, Theme::TEXT, Theme::BG);
  gfx().text(12, y + 43, t9_.help(), 1, Theme::MUTED, Theme::MODAL_BG, Align::Left, 0, false,
             Display::W - 24);
}

void SettingsApp::draw() {
  if (page_ == Page::BtSend) {
    browser_.draw("Carpeta vacía");
    gfx().footer("EXE enviar este archivo   ◄/AC volver");
    return;
  }
  buildRows();
  drawRows();
  drawInfo();
  if (edit_ != Edit::None) gfx().footer("EXE aceptar   AC cancelar   DEL borrar");
  else gfx().footer(page_ == Page::Main ? "▲▼ mover   EXE elegir   MENU salir"
                                        : "▲▼ mover   EXE elegir   ◄/AC volver");
}

// ---- Edición ---------------------------------------------------------------------
void SettingsApp::startEdit(Edit e, const String& title, const String& text, T9Input::Mode m,
                            uint8_t max) {
  edit_ = e;
  editTitle_ = title;
  t9_.begin(text, m, max);
  requestRedraw();
}

void SettingsApp::finishEdit() {
  Edit e = edit_;
  edit_ = Edit::None;
  if (e == Edit::Password) {
    wifi.connect(editArg_, t9_.value());
  } else if (e == Edit::IpField) {
    IPAddress a;
    if (a.fromString(t9_.value())) ipField(editField_) = a;
    else dialogs().info("IP no válida", {"Escribe 4 números del 0 al 255", "separados por puntos:",
                                         "  192.168.1.50"});
  }
  requestRedraw();
}

// ---- Teclas ----------------------------------------------------------------------
void SettingsApp::goPage(Page p) {
  selMemo_[static_cast<uint8_t>(page_)] = list_.sel;
  page_ = p;
  list_.sel = selMemo_[static_cast<uint8_t>(p)];
  list_.top = 0;
  if (p == Page::Pkgs || p == Page::Main) pkgs_ = PackageManifest::read(sd());
  if (p == Page::Ip) ipEdit_ = wifi.ipCfg();
  if (p == Page::WifiInfo) dnsResult_ = "";
  if (p == Page::BtSend) browser_.refresh();
  setTitle(PAGE_TITLES[static_cast<uint8_t>(p)]);
  requestRedraw();
}

void SettingsApp::onKey(const KeyEvent& ev) {
  if (edit_ != Edit::None) {
    T9Input::Result r = t9_.key(ev);
    if (r == T9Input::Result::Ok) finishEdit();
    else if (r == T9Input::Result::Cancel) { edit_ = Edit::None; requestRedraw(); }
    else drawEdit();
    return;
  }
  if (page_ == Page::BtSend) {
    if (ev.key == Key::AC || (ev.key == Key::Left && browser_.cwd() == "/")) {
      goPage(Page::Bt);
      return;
    }
    if (browser_.key(ev) == FolderBrowser::Result::OpenFile) {
      linkService.requestSend(browser_.selectedPath());
      goPage(Page::Bt);
    }
    return;
  }
  switch (ev.key) {
    case Key::Up:
    case Key::Down: {
      if (!list_.count) return;
      uint16_t old = list_.sel;
      if (list_.move(ev.key == Key::Up ? -1 : 1)) drawRows();
      else { drawRow(old); drawRow(list_.sel); }
      return;
    }
    case Key::Left:
    case Key::AC:
    case Key::Del:
      if (page_ == Page::WifiInfo || page_ == Page::Ip) goPage(Page::Wifi);
      else if (page_ != Page::Main) goPage(Page::Main);
      return;
    case Key::Exe:
    case Key::Right:
      if (list_.count) doAction(rows_[list_.sel]);
      return;
    default:
      return;
  }
}

void SettingsApp::doAction(const Row& r) {
  SystemState& s = st();
  auto examBlock = [&]() {
    if (!s.exam) return false;
    dialogs().info("Modo examen", {"No disponible durante", "el modo examen."});
    return true;
  };
  switch (r.action) {
    case Action::GoWifi:     goPage(Page::Wifi); break;
    case Action::GoBt:       goPage(Page::Bt); break;
    case Action::GoUsb:      goPage(Page::Usb); break;
    case Action::GoPkgs:     goPage(Page::Pkgs); break;
    case Action::GoAbout:    goPage(Page::About); break;
    case Action::GoWifiInfo: goPage(Page::WifiInfo); break;
    case Action::GoIp:       goPage(Page::Ip); break;
    case Action::GoBtSend:   goPage(Page::BtSend); break;

    case Action::ToggleExam:
      if (!s.exam) {
        dialogs().ask("Modo examen", {"Se APAGAN Wi-Fi y Bluetooth", "y se BLOQUEA Python.", "",
                                      "Aparecerá EXAMEN en la barra.", "", "¿Activar?"},
                      [this](DlgAnswer a) {
                        if (a == DlgAnswer::No) return;
                        wifi.setOn(false);
                        linkService.requestBt(false);
                        st().setExam(true);
                      });
      } else {
        dialogs().ask("Modo examen", {"¿Salir del modo examen?"},
                      [this](DlgAnswer a) { if (a != DlgAnswer::No) st().setExam(false); });
      }
      break;

    case Action::ToggleWifi:
      if (examBlock()) break;
      wifi.setOn(!s.wifiOn);
      requestRedraw();
      break;
    case Action::WifiScan:
      wifi.startScan();
      requestRedraw();
      break;
    case Action::WifiNet: {
      if (s.wifiConnected && r.arg == s.wifiSsid) { goPage(Page::WifiInfo); break; }
      String pass;
      bool secure = r.lock;
      if (!secure || wifi.savedPass(r.arg, pass)) {
        wifi.connect(r.arg, "");
        requestRedraw();
      } else {
        editArg_ = r.arg;
        startEdit(Edit::Password, "Contraseña de " + r.arg, "", T9Input::Mode::Pass, 63);
      }
      break;
    }
    case Action::WifiDisconnect:
      wifi.disconnect();
      goPage(Page::Wifi);
      break;
    case Action::WifiForget: {
      String ssid = r.arg;
      dialogs().ask("Olvidar red", {"¿Olvidar " + ssid + "?", "Habrá que volver a poner", "la contraseña."},
                    [this, ssid](DlgAnswer a) {
                      if (a == DlgAnswer::No) return;
                      wifi.forget(ssid);
                      goPage(Page::Wifi);
                    });
      break;
    }
    case Action::DnsTest:
      dnsResult_ = "probando...";
      drawRow(list_.sel);
      dnsResult_ = wifi.dnsTest("google.com");
      requestRedraw();
      break;

    case Action::IpMode:
      ipEdit_.dhcp = !ipEdit_.dhcp;
      if (!ipEdit_.dhcp && ipEdit_.ip == IPAddress() && s.wifiConnected) {
        // se rellena con lo que da el router: solo hay que cambiar la IP
        ipEdit_.ip.fromString(wifi.localIp());
        ipEdit_.mask.fromString(wifi.mask());
        ipEdit_.gw.fromString(wifi.gateway());
      }
      requestRedraw();
      break;
    case Action::IpField:
      editField_ = r.arg.toInt();
      startEdit(Edit::IpField, IP_NAMES[editField_],
                ipField(editField_) == IPAddress() ? String("") : ipField(editField_).toString(),
                T9Input::Mode::Ip, 15);
      break;
    case Action::IpApply:
      wifi.setIpCfg(ipEdit_);
      dialogs().info("IP y DNS", {"Guardado.", s.wifiConnected ? "Reconectando con los nuevos datos..."
                                                               : "Se usará al conectar."});
      goPage(Page::Wifi);
      break;

    case Action::ToggleBt:
      if (examBlock()) break;
      linkService.requestBt(!s.btOn);
      break;
    case Action::BtScan:
      linkService.requestScan();
      break;
    case Action::BtDevice:
      linkService.requestConnect(r.arg, r.label);
      break;
    case Action::BtDisconnect:
      linkService.requestDisconnect();
      break;

    case Action::InfoMsc:
      dialogs().info("Disco USB", {"Que el PC vea la MicroSD como un", "pendrive necesita USB nativo",
                                   "(ESP32-S3). Con tu ESP32 usa el", "modo Serie, o saca la MicroSD",
                                   "y conéctala al PC."});
      break;

    case Action::Package:
      for (const PackageInfo& p : pkgs_) {
        if (p.name != r.arg) continue;
        dialogs().info("Paquete", {"  " + p.name, "Versión: " + p.version, "Origen: " + p.source,
                                   String(p.files) + " archivos en /lib"});
        break;
      }
      break;

    default:
      break;
  }
}

// ---- Cambios que llegan solos (búsquedas, conexiones, T9) ---------------------------
void SettingsApp::onTick(uint32_t nowMs) {
  if (!canDraw()) return;
  if (edit_ != Edit::None) {
    if (t9_.tick(nowMs)) drawEdit();               // la letra se confirma: cursor
    return;
  }
  bool wifiPage = page_ == Page::Main || page_ == Page::Wifi || page_ == Page::WifiInfo;
  bool btPage = page_ == Page::Main || page_ == Page::Bt;
  uint8_t stt = static_cast<uint8_t>(wifi.status());
  if (wifiPage && (wifi.scanStamp() != wifiSeen_ || stt != statusSeen_)) {
    wifiSeen_ = wifi.scanStamp();
    statusSeen_ = stt;
    requestRedraw();
  }
  if (btPage && linkService.stamp() != linkSeen_) {
    linkSeen_ = linkService.stamp();
    requestRedraw();
  }
}
