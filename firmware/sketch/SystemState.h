// =============================================================================
//  SystemState.h  —  Estado global que comparten las apps y la barra de estado
// -----------------------------------------------------------------------------
//  Es un "modelo" puro: nadie dibuja aquí. La barra de estado compara este
//  estado con lo que dibujó la última vez y solo se repinta si algo cambió.
//
//  Paso 3: Wi-Fi y Bluetooth son solo estado de la interfaz. Los servicios
//  reales (WiFi.h, BluetoothSerial, NVS) se conectan en el paso de Ajustes.
// =============================================================================
#pragma once
#include <Arduino.h>

struct SystemState {
  // --- Calculadora --------------------------------------------------------
  bool degrees = true;            // DEG / RAD (SHIFT+AC lo cambia)

  // --- Conectividad -------------------------------------------------------
  bool wifiOn = false;
  bool wifiConnected = false;
  char wifiSsid[33] = "";         // red conectada (máx. 32 caracteres + '\0')
  bool btOn = false;
  uint8_t linkClients = 0;        // conexiones SciCalc Link activas

  // --- Seguridad ------------------------------------------------------------
  bool exam = false;              // modo examen: sin radio y sin Python

  // --- Hardware ---------------------------------------------------------------
  bool sdMounted = false;
  int8_t batteryPct = -1;         // -1 = desconocido (lectura ADC en el Paso 8)
  bool charging = false;

  // Activa/desactiva el modo examen aplicando sus reglas
  void setExam(bool on) {
    exam = on;
    if (on) {
      wifiOn = false;
      wifiConnected = false;
      wifiSsid[0] = '\0';
      btOn = false;
      linkClients = 0;
    }
  }
};
