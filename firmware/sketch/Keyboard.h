// =============================================================================
//  Keyboard.h  —  Capa de entrada: códigos de tecla, eventos y drivers
// -----------------------------------------------------------------------------
//  Diseño:
//   * Las apps solo ven "Key" (qué tecla lógica) y "KeyEvent" (pulsación).
//   * IKeyboard es la interfaz; hoy usamos MatrixKeyboard (GPIO directos, para
//     Wokwi) y en el hardware real Mcp23017Keyboard (I2C) sin tocar las apps.
//   * El escaneo corre en una tarea FreeRTOS en el CORE 0 y entrega eventos
//     por una cola: la UI (core 1) nunca pierde pulsaciones aunque esté
//     ocupada dibujando.
// =============================================================================
#pragma once
#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>

// Teclas lógicas (independientes del cableado). El orden es el mismo que
// KEY_ORDER en el simulador: lo usa la rejilla de Diagnóstico.
enum class Key : uint8_t {
  None = 0,
  // Bloque A — navegación y funciones
  Shift, Menu, Up, Down,
  Left, Right, Del, AC,
  Sin, Cos, Tan, Pow,
  Ln, Sqrt, LParen, RParen,
  // Bloque B — numérico
  N7, N8, N9, Div,
  N4, N5, N6, Mul,
  N1, N2, N3, Sub,
  N0, Dot, Exe, Add,
  Count
};

constexpr uint8_t KEY_COUNT = static_cast<uint8_t>(Key::Count) - 1;  // 32

struct KeyEvent {
  Key  key    = Key::None;
  bool shift  = false;   // lo rellena el AppManager (SHIFT es de un solo uso)
  bool repeat = false;   // true si es autorrepetición por mantener pulsado
};

// Nombre corto ASCII (para el monitor serie)
const char* keyName(Key k);
// Etiqueta impresa en la tecla (UTF-8, p. ej. "▲", "√", "xʸ")
const char* keyLabel(Key k);
// Función SHIFT (amarilla) de la tecla, o "" si no tiene
const char* keyShiftLabel(Key k);
// Dígito '0'..'9' si la tecla es numérica; 0 en otro caso
char keyDigit(Key k);

// ---------------------------------------------------------------------------
class IKeyboard {
 public:
  virtual ~IKeyboard() = default;
  virtual bool begin() = 0;
  // Espera hasta 'waitMs' a que llegue un evento. true si hay evento.
  virtual bool poll(KeyEvent& ev, uint32_t waitMs = 0) = 0;
  // Descarta los eventos pendientes (p. ej. teclas pulsadas durante el arranque)
  virtual void flush() = 0;
};

// ---------------------------------------------------------------------------
//  Matriz 8x4 en GPIO directos (Wokwi: 2 teclados de membrana 4x4)
// ---------------------------------------------------------------------------
class MatrixKeyboard : public IKeyboard {
 public:
  bool begin() override;
  bool poll(KeyEvent& ev, uint32_t waitMs = 0) override;
  void flush() override;

 private:
  static void taskEntry(void* arg);
  void scanLoop();
  uint32_t readMatrix();               // bit (fila*4+col) = 1 si pulsada
  static bool isRepeatable(Key k);

  QueueHandle_t queue_ = nullptr;
  TaskHandle_t  task_  = nullptr;
};
