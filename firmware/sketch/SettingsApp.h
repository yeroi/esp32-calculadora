// =============================================================================
//  SettingsApp.h  —  Ajustes: Wi-Fi, Bluetooth, USB, modo examen, paquetes
// -----------------------------------------------------------------------------
//  Páginas (igual que el simulador):
//    main    -> Wi-Fi · Bluetooth · USB · Modo examen · Paquetes · Acerca de
//    wifi    -> interruptor, buscar, detalles, IP y las redes cercanas REALES
//               (barras de señal, candado, ✓ la conectada). EXE en una red:
//               conectar (pide la contraseña con T9 si no la sabe).
//    winfo   -> IP, máscara, puerta de enlace, DNS, MAC, señal, canal,
//               probar DNS, desconectar, olvidar
//    ip      -> DHCP / IP fija (IP, máscara, puerta de enlace, DNS 1 y 2)
//    bt      -> interruptor, nombre, estado, buscar, dispositivos cercanos,
//               enviar archivo, desconectar
//    btsend  -> elegir el archivo que se envía (explorador de la SD)
//    usb / pkgs / about
//  Mientras se escribe un valor (T9Input) el panel de edición ocupa la zona de
//  información de abajo y las teclas van a él.
// =============================================================================
#pragma once
#include <vector>
#include "App.h"
#include "FolderBrowser.h"
#include "PackageManifest.h"
#include "ScrollList.h"
#include "T9Input.h"
#include "WifiService.h"

class SettingsApp : public App {
 public:
  explicit SettingsApp(AppManager& m) : App(m), browser_(m.gfx(), m.storage(), false) {}

  const char* title() const override { return "Ajustes"; }
  void onEnter() override;
  void draw() override;
  void onKey(const KeyEvent& ev) override;
  void onTick(uint32_t nowMs) override;

 private:
  enum class Page : uint8_t { Main, Wifi, WifiInfo, Ip, Bt, BtSend, Usb, Pkgs, About, Count };
  enum class Action : uint8_t {
    None, GoWifi, GoBt, GoUsb, GoPkgs, GoAbout, GoWifiInfo, GoIp, GoBtSend,
    ToggleExam, ToggleWifi, ToggleBt, WifiScan, WifiNet, WifiDisconnect, WifiForget, DnsTest,
    IpMode, IpField, IpApply, BtScan, BtDevice, BtDisconnect, InfoMsc, Package
  };
  enum class Edit : uint8_t { None, Password, IpField };
  struct Row {
    String label;
    String value;
    Action action = Action::None;
    String arg;                 // red, paquete, dirección BT...
    uint16_t color = 0;         // 0 = color por defecto
    int8_t bars = -1;           // 0..4: barras de señal (-1 = sin barras)
    bool lock = false;          // red con contraseña
    bool check = false;         // conectada
  };

  void buildRows();
  std::vector<String> infoLines();
  void drawRow(uint16_t i);
  void drawRows();
  void drawInfo();
  void drawEdit();
  void goPage(Page p);
  void doAction(const Row& r);
  void startEdit(Edit e, const String& title, const String& text, T9Input::Mode m, uint8_t max);
  void finishEdit();
  IPAddress& ipField(uint8_t i);

  Page page_ = Page::Main;
  std::vector<Row> rows_;
  std::vector<PackageInfo> pkgs_;
  ScrollList list_;
  uint16_t selMemo_[static_cast<uint8_t>(Page::Count)] = {};   // selección por página
  FolderBrowser browser_;

  // edición con T9
  Edit edit_ = Edit::None;
  T9Input t9_;
  String editTitle_, editArg_;
  uint8_t editField_ = 0;
  WifiService::IpCfg ipEdit_;   // copia que se edita en la página IP

  // para repintar solo cuando cambia algo
  uint32_t wifiSeen_ = 0, linkSeen_ = 0;
  uint8_t statusSeen_ = 255;
  String dnsResult_;
};
