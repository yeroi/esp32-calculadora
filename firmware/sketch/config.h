// =============================================================================
//  config.h  —  Pines y constantes globales del sistema
// -----------------------------------------------------------------------------
//  Placa: ELEGOO ESP32 DevKit (ESP32-WROOM-32, 4 MB flash, SIN PSRAM) / Wokwi.
//  TODO el cableado está aquí: si cambias un pin, solo tocas este archivo.
//
//  GPIO prohibidos o delicados en el WROOM-32:
//    6-11  -> flash interna (NUNCA usar)
//    1, 3  -> UART0 (USB-serie: monitor y SciCalc Link por USB)
//    0, 2, 15, 12 -> pines de arranque (strapping): solo con cuidado
//    34-39 -> solo entrada y SIN pull-up interna
// =============================================================================
#pragma once
#include <Arduino.h>
#include <freertos/FreeRTOS.h>

// ---------------- Bus SPI compartido (VSPI): pantalla + MicroSD --------------
constexpr int PIN_SPI_SCK  = 18;
constexpr int PIN_SPI_MOSI = 23;
constexpr int PIN_SPI_MISO = 19;

// ---------------- Pantalla TFT ILI9341 320x240 -------------------------------
constexpr int PIN_TFT_CS  = 5;
constexpr int PIN_TFT_DC  = 4;
constexpr int PIN_TFT_RST = -1;           // RST cableado a 3V3
constexpr uint32_t TFT_SPI_HZ = 40000000; // 40 MHz

// ---------------- MicroSD ----------------------------------------------------
constexpr int PIN_SD_CS = 15;             // GPIO15: en alto al arrancar, buen CS
constexpr uint32_t SD_SPI_HZ = 4000000;   // 4 MHz (seguro en Wokwi y en real)

// ---------------- Teclado matricial 8 filas x 4 columnas (Wokwi) -------------
// Filas = entradas con pull-up interna. Columnas = salidas activas a nivel bajo.
// Teclado A (funciones) usa las filas 0-3; teclado B (numérico) las filas 4-7.
// En el hardware real la matriz va en un MCP23017 (ver más abajo) y solo
// cambia la clase de teclado: las apps no se enteran.
constexpr uint8_t KB_ROWS = 8;
constexpr uint8_t KB_COLS = 4;
constexpr int PIN_KB_ROWS[KB_ROWS] = {32, 33, 25, 26, 27, 14, 12, 13};
constexpr int PIN_KB_COLS[KB_COLS] = {16, 17, 21, 22};

constexpr uint32_t KB_SCAN_MS        = 5;    // periodo de escaneo
constexpr uint8_t  KB_DEBOUNCE_SCANS = 4;    // 4 x 5 ms = 20 ms de antirrebote
constexpr uint32_t KB_REPEAT_DELAY   = 450;  // ms hasta la autorrepetición
constexpr uint32_t KB_REPEAT_RATE    = 110;  // ms entre repeticiones

// ---------------- Hardware real (aún no usado en Wokwi) ----------------------
constexpr int PIN_I2C_SDA   = 21;            // MCP23017
constexpr int PIN_I2C_SCL   = 22;
constexpr int PIN_MCP_INTA  = 39;            // pull-up EXTERNA de 10k
constexpr int PIN_BATTERY   = 34;            // ADC1, divisor 100k + 100k
constexpr int PIN_BUZZER    = 2;             // LEDC (definitivo en el mapa final)

// ---------------- Sistema ----------------------------------------------------
#define FW_VERSION_STR "0.3"
constexpr const char* FW_NAME    = "ESP32 SciCalc";
constexpr const char* FW_VERSION = FW_VERSION_STR;

// Núcleos FreeRTOS: core 0 = servicios (teclado, enlaces); core 1 = UI
constexpr BaseType_t CORE_SERVICES = 0;
constexpr BaseType_t CORE_UI       = 1;
