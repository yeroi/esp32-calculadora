// =============================================================================
//  Theme.h  —  Paleta de la interfaz (RGB565)
// -----------------------------------------------------------------------------
//  Son exactamente los colores del simulador (scicalc_sim.py), convertidos a
//  RGB565 en tiempo de compilación con rgb().
// =============================================================================
#pragma once
#include <stdint.h>

namespace Theme {

constexpr uint16_t rgb(uint8_t r, uint8_t g, uint8_t b) {
  return static_cast<uint16_t>(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
}

// --- Interfaz general ---------------------------------------------------------
constexpr uint16_t BG       = rgb(10, 12, 18);     // fondo casi negro
constexpr uint16_t PANEL    = rgb(30, 34, 44);     // paneles / filas
constexpr uint16_t PATH_BG  = rgb(20, 23, 31);     // barra de ruta del explorador
constexpr uint16_t MODAL_BG = rgb(22, 25, 33);     // fondo de los diálogos
constexpr uint16_t TEXT     = rgb(238, 241, 245);
constexpr uint16_t MUTED    = rgb(135, 142, 158);
constexpr uint16_t DIM      = rgb(90, 96, 110);    // barras de señal apagadas
constexpr uint16_t ACCENT   = rgb(40, 168, 250);   // azul
constexpr uint16_t OK       = rgb(70, 205, 120);   // verde
constexpr uint16_t WARN     = rgb(255, 170, 40);   // naranja
constexpr uint16_t ERR      = rgb(255, 90, 90);    // rojo
constexpr uint16_t SHIFT    = rgb(255, 200, 40);   // amarillo (SHIFT / permisos)

// --- Historial de la calculadora ---------------------------------------------
constexpr uint16_t HIST     = rgb(175, 182, 196);
constexpr uint16_t HIST_ERR = rgb(205, 90, 90);

// --- Iconos de archivo ---------------------------------------------------------
constexpr uint16_t ICON_DIR = rgb(240, 190, 60);
constexpr uint16_t ICON_PY  = rgb(70, 140, 230);
constexpr uint16_t ICON_IMG = rgb(60, 190, 120);
constexpr uint16_t ICON_TXT = rgb(150, 155, 170);
constexpr uint16_t ICON_BIN = rgb(120, 110, 160);
constexpr uint16_t WHITE    = 0xFFFF;

}  // namespace Theme
