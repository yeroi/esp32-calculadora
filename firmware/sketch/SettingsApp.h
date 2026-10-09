// =============================================================================
//  SettingsApp.h  —  Ajustes: Wi-Fi, Bluetooth, USB, modo examen, paquetes
// -----------------------------------------------------------------------------
//  Páginas (igual que el simulador):
//    main  -> Wi-Fi · Bluetooth · USB · Modo examen · Paquetes · Acerca de
//    wifi  -> interruptor + redes (con barras de señal)
//    bt    -> interruptor, nombre "SciCalc-XXXX", estado
//    usb   -> modo Serie (SciCalc Link 115200) · Disco USB (requiere S3)
//    pkgs  -> paquetes de /lib/paquetes.json
//    about -> versión, chip, SD libre, paquetes, conexiones
//
//  PASO 3: la INTERFAZ completa y el modo examen funcionando. Encender la
//  radio, buscar/conectar redes (WiFi.h), Bluetooth SPP y NVS llegan en el
//  paso "Ajustes reales": de momento los interruptores solo cambian el estado.
// =============================================================================
#pragma once
#include <vector>
#include "App.h"
#include "PackageManifest.h"
#include "ScrollList.h"

class SettingsApp : public App {
 public:
  explicit SettingsApp(AppManager& m) : App(m) {}

  const char* title() const override { return "Ajustes"; }
  void onEnter() override;
  void draw() override;
  void onKey(const KeyEvent& ev) override;

 private:
  enum class Page : uint8_t { Main, Wifi, Bt, Usb, Pkgs, About, Count };
  enum class Action : uint8_t {
    None, GoWifi, GoBt, GoUsb, GoPkgs, GoAbout,
    ToggleExam, ToggleWifi, ToggleBt, InfoMsc, Package
  };
  struct Row {
    String label;
    String value;
    Action action = Action::None;
    String arg;                 // nombre del paquete
    uint16_t color = 0;         // 0 = color por defecto
  };

  void buildRows();
  std::vector<String> infoLines();
  void drawRow(uint16_t i);
  void drawRows();
  void drawInfo();
  void goPage(Page p);
  void doAction(const Row& r);
  String btName() const;

  Page page_ = Page::Main;
  std::vector<Row> rows_;
  std::vector<PackageInfo> pkgs_;
  ScrollList list_;
  uint16_t selMemo_[static_cast<uint8_t>(Page::Count)] = {};   // selección por página
};
