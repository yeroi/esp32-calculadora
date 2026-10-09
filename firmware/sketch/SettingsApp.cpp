// =============================================================================
//  SettingsApp.cpp
// =============================================================================
#include "SettingsApp.h"
#include "config.h"

namespace {
  constexpr int16_t ROW_X = 6, ROW_W = Display::W - 12;
  constexpr int16_t ROW_Y0 = Display::BODY_Y + 5;
  constexpr int16_t ROW_STEP = 27, ROW_H = 23;
  constexpr uint8_t VISIBLE = 6;
  constexpr int16_t INFO_LINE_H = 11;

  const char* const PAGE_TITLES[] = {"Ajustes", "Ajustes › Wi-Fi", "Ajustes › Bluetooth",
                                     "Ajustes › USB", "Ajustes › Paquetes", "Ajustes › Acerca de"};
}

void SettingsApp::onEnter() {
  page_ = Page::Main;
  pkgs_ = PackageManifest::read(sd());
  list_.sel = selMemo_[0];
  list_.top = 0;
}

String SettingsApp::btName() const {
  // "SciCalc-XXXX" con los 2 últimos bytes de la MAC: único por placa
  uint64_t mac = ESP.getEfuseMac();
  char buf[16];
  snprintf(buf, sizeof buf, "SciCalc-%02X%02X", (unsigned)((mac >> 32) & 0xFF),
           (unsigned)((mac >> 40) & 0xFF));
  return String(buf);
}

// ---- Modelo de cada página ------------------------------------------------------
void SettingsApp::buildRows() {
  SystemState& s = st();
  rows_.clear();
  auto add = [&](const String& label, const String& value, Action a, uint16_t color = 0,
                 const String& arg = "") {
    Row r;
    r.label = label;
    r.value = value;
    r.action = a;
    r.color = color;
    r.arg = arg;
    rows_.push_back(r);
  };
  switch (page_) {
    case Page::Main: {
      String wv = s.wifiConnected ? String(s.wifiSsid) : String(s.wifiOn ? "Encendido" : "Apagado");
      add("Wi-Fi", wv, Action::GoWifi, s.wifiConnected ? Theme::OK : 0);
      add("Bluetooth", s.btOn ? "Visible" : "Apagado", Action::GoBt, s.btOn ? Theme::OK : 0);
      add("USB", "Serie · SciCalc Link", Action::GoUsb);
      add("Modo examen", s.exam ? "ACTIVADO" : "Desactivado", Action::ToggleExam,
          s.exam ? Theme::WARN : 0);
      add("Paquetes Python", String(pkgs_.size()) + " instalados", Action::GoPkgs);
      add("Acerca de", "v" FW_VERSION_STR, Action::GoAbout);
      break;
    }
    case Page::Wifi:
      add("Wi-Fi", s.wifiOn ? "Encendido" : "Apagado", Action::ToggleWifi, s.wifiOn ? Theme::OK : 0);
      break;
    case Page::Bt:
      add("Bluetooth", s.btOn ? "Encendido" : "Apagado", Action::ToggleBt, s.btOn ? Theme::OK : 0);
      add("Nombre", btName(), Action::None);
      add("Estado", s.btOn ? "visible, esperando PC" : "-", Action::None);
      break;
    case Page::Usb:
      add("Modo USB", "Serie (SciCalc Link)", Action::None, Theme::OK);
      add("Velocidad", "115200 baudios", Action::None);
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
      if (!s.wifiOn) return {"Enciende el Wi-Fi para buscar redes."};
      return {"Buscar redes, conectar y guardar", "contraseñas (NVS) llega en el paso",
              "\"Ajustes reales\" con WiFi.h.", "",
              "SciCalc Link escuchará en TCP 8266."};
    case Page::Bt:
      return {"En el PC: Bluetooth > Agregar dispositivo >",
              btName() + ". Windows crea un puerto COM:",
              "elígelo en SciCalc Link (Bluetooth).",
              "(aún no enciende la radio: paso Ajustes)"};
    case Page::Usb:
      return {"Conecta el cable USB-C y elige el puerto COM",
              "en SciCalc Link (USB). Mismo protocolo que",
              "Bluetooth y Wi-Fi."};
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
  int16_t vw = Display::textWidth(r.value.c_str(), 1) + 1;
  int16_t vx = ROW_X + ROW_W - 9 - vw;
  gfx().textBold(vx, y + 8, r.value.c_str(), 1, col, bg);
  gfx().textBold(ROW_X + 9, y + 8, r.label.c_str(), 1, Theme::TEXT, bg, vx - ROW_X - 20);
}

void SettingsApp::drawRows() {
  gfx().fillRect(0, ROW_Y0, Display::W, VISIBLE * ROW_STEP, Theme::BG);
  for (uint16_t i = list_.top; i < rows_.size() && i < list_.top + VISIBLE; ++i) drawRow(i);
}

void SettingsApp::drawInfo() {
  uint16_t shown = min<uint16_t>(rows_.size(), VISIBLE);
  int16_t y = ROW_Y0 + shown * ROW_STEP + 6;
  gfx().fillRect(0, y, Display::W, Display::FOOTER_Y - 2 - y, Theme::BG);
  for (const String& ln : infoLines()) {
    if (y + 8 > Display::FOOTER_Y - 4) break;
    gfx().text(12, y, ln.c_str(), 1, Theme::MUTED, Theme::BG, Align::Left, 0, false,
               Display::W - 20);
    y += INFO_LINE_H;
  }
}

void SettingsApp::draw() {
  buildRows();
  drawRows();
  drawInfo();
  gfx().footer(page_ == Page::Main ? "▲▼ mover   EXE elegir   MENU salir"
                                   : "▲▼ mover   EXE elegir   ◄/AC volver");
}

// ---- Teclas ----------------------------------------------------------------------
void SettingsApp::goPage(Page p) {
  selMemo_[static_cast<uint8_t>(page_)] = list_.sel;
  page_ = p;
  list_.sel = selMemo_[static_cast<uint8_t>(p)];
  list_.top = 0;
  if (p == Page::Pkgs || p == Page::Main) pkgs_ = PackageManifest::read(sd());
  setTitle(PAGE_TITLES[static_cast<uint8_t>(p)]);
  requestRedraw();
}

void SettingsApp::onKey(const KeyEvent& ev) {
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
      if (page_ != Page::Main) goPage(Page::Main);
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
  switch (r.action) {
    case Action::GoWifi:  goPage(Page::Wifi); break;
    case Action::GoBt:    goPage(Page::Bt); break;
    case Action::GoUsb:   goPage(Page::Usb); break;
    case Action::GoPkgs:  goPage(Page::Pkgs); break;
    case Action::GoAbout: goPage(Page::About); break;

    case Action::ToggleExam:
      if (!s.exam) {
        dialogs().ask("Modo examen", {"Se APAGAN Wi-Fi y Bluetooth", "y se BLOQUEA Python.", "",
                                      "Aparecerá EXAMEN en la barra.", "", "¿Activar?"},
                      [this](DlgAnswer a) { if (a != DlgAnswer::No) st().setExam(true); });
      } else {
        dialogs().ask("Modo examen", {"¿Salir del modo examen?"},
                      [this](DlgAnswer a) { if (a != DlgAnswer::No) st().setExam(false); });
      }
      break;

    case Action::ToggleWifi:
    case Action::ToggleBt:
      if (s.exam) {
        dialogs().info("Modo examen", {"No disponible durante", "el modo examen."});
        break;
      }
      if (r.action == Action::ToggleWifi) {
        s.wifiOn = !s.wifiOn;
        if (!s.wifiOn) { s.wifiConnected = false; s.wifiSsid[0] = '\0'; }
      } else {
        s.btOn = !s.btOn;
      }
      requestRedraw();
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
                                   String(p.files) + " archivos en /lib", "",
                                   "Desinstalar necesita el gestor de", "permisos (Paso 5)."});
        break;
      }
      break;

    default:
      break;
  }
}
