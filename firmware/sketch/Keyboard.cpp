// =============================================================================
//  Keyboard.cpp
// =============================================================================
#include "Keyboard.h"
#include "config.h"

// Mapa físico -> lógico. Orden = filas 0..7, columnas 0..3.
// Debe coincidir con las etiquetas "keys" de los teclados en diagram.json.
static const Key KEYMAP[KB_ROWS][KB_COLS] = {
  {Key::Shift, Key::Menu,  Key::Up,     Key::Down  },  // A fila 1
  {Key::Left,  Key::Right, Key::Del,    Key::AC    },  // A fila 2
  {Key::Sin,   Key::Cos,   Key::Tan,    Key::Pow   },  // A fila 3
  {Key::Ln,    Key::Sqrt,  Key::LParen, Key::RParen},  // A fila 4
  {Key::N7,    Key::N8,    Key::N9,     Key::Div   },  // B fila 1
  {Key::N4,    Key::N5,    Key::N6,     Key::Mul   },  // B fila 2
  {Key::N1,    Key::N2,    Key::N3,     Key::Sub   },  // B fila 3
  {Key::N0,    Key::Dot,   Key::Exe,    Key::Add   },  // B fila 4
};

// Tablas indexadas por el valor del enum (0 = None)
static const char* const NAMES[] = {
  "-",
  "SHIFT", "MENU", "UP", "DOWN", "LEFT", "RIGHT", "DEL", "AC",
  "sin", "cos", "tan", "^", "ln", "sqrt", "(", ")",
  "7", "8", "9", "/", "4", "5", "6", "*",
  "1", "2", "3", "-", "0", ".", "EXE", "+",
};
static const char* const LABELS[] = {
  "",
  "SHIFT", "MENU", "▲", "▼", "◄", "►", "DEL", "AC",
  "sin", "cos", "tan", "xʸ", "ln", "√", "(", ")",
  "7", "8", "9", "÷", "4", "5", "6", "×",
  "1", "2", "3", "−", "0", ".", "EXE", "+",
};
static const char* const SHIFT_LABELS[] = {
  "",
  "", "", "", "", "", "", "", "DRG",
  "asin", "acos", "atan", "x²", "log", "π", "e", "Ans",
  "", "", "", "x!", "", "", "", "",
  "", "", "", "", "", "EXP", "", "",
};

static inline uint8_t idx(Key k) {
  uint8_t i = static_cast<uint8_t>(k);
  return i < static_cast<uint8_t>(Key::Count) ? i : 0;
}

const char* keyName(Key k)       { return NAMES[idx(k)]; }
const char* keyLabel(Key k)      { return LABELS[idx(k)]; }
const char* keyShiftLabel(Key k) { return SHIFT_LABELS[idx(k)]; }

char keyDigit(Key k) {
  switch (k) {
    case Key::N0: return '0'; case Key::N1: return '1'; case Key::N2: return '2';
    case Key::N3: return '3'; case Key::N4: return '4'; case Key::N5: return '5';
    case Key::N6: return '6'; case Key::N7: return '7'; case Key::N8: return '8';
    case Key::N9: return '9';
    default: return 0;
  }
}

// ---------------------------------------------------------------------------
bool MatrixKeyboard::begin() {
  for (int p : PIN_KB_ROWS) pinMode(p, INPUT_PULLUP);
  for (int p : PIN_KB_COLS) { pinMode(p, OUTPUT); digitalWrite(p, HIGH); }

  queue_ = xQueueCreate(16, sizeof(KeyEvent));
  if (!queue_) return false;

  // Core 0, prioridad 2: la UI corre en el core 1 (loop de Arduino).
  BaseType_t ok = xTaskCreatePinnedToCore(taskEntry, "kbd", 3072, this, 2, &task_,
                                          CORE_SERVICES);
  return ok == pdPASS;
}

bool MatrixKeyboard::poll(KeyEvent& ev, uint32_t waitMs) {
  if (!queue_) return false;
  return xQueueReceive(queue_, &ev, pdMS_TO_TICKS(waitMs)) == pdTRUE;
}

void MatrixKeyboard::flush() {
  if (queue_) xQueueReset(queue_);
}

void MatrixKeyboard::taskEntry(void* arg) {
  static_cast<MatrixKeyboard*>(arg)->scanLoop();
}

uint32_t MatrixKeyboard::readMatrix() {
  uint32_t state = 0;
  for (uint8_t c = 0; c < KB_COLS; ++c) {
    digitalWrite(PIN_KB_COLS[c], LOW);
    delayMicroseconds(5);                       // deja estabilizar la línea
    for (uint8_t r = 0; r < KB_ROWS; ++r) {
      if (digitalRead(PIN_KB_ROWS[r]) == LOW) state |= (1UL << (r * KB_COLS + c));
    }
    digitalWrite(PIN_KB_COLS[c], HIGH);
  }
  return state;
}

bool MatrixKeyboard::isRepeatable(Key k) {
  return k == Key::Up || k == Key::Down || k == Key::Left ||
         k == Key::Right || k == Key::Del;
}

void MatrixKeyboard::scanLoop() {
  uint32_t lastRaw = 0, stable = 0;
  uint8_t  sameCount = 0;
  int      heldBit = -1;         // tecla que se está autorrepitiendo
  uint32_t nextRepeatAt = 0;

  TickType_t wake = xTaskGetTickCount();
  for (;;) {
    vTaskDelayUntil(&wake, pdMS_TO_TICKS(KB_SCAN_MS));
    uint32_t raw = readMatrix();

    // --- Antirrebote: el estado debe repetirse N escaneos seguidos ---------
    if (raw == lastRaw) {
      if (sameCount < KB_DEBOUNCE_SCANS) ++sameCount;
    } else {
      sameCount = 0;
      lastRaw = raw;
    }
    uint32_t now = millis();

    if (sameCount == KB_DEBOUNCE_SCANS && raw != stable) {
      uint32_t pressed = raw & ~stable;          // flancos de bajada (nuevas)
      stable = raw;
      for (int bit = 0; bit < KB_ROWS * KB_COLS; ++bit) {
        if (!(pressed & (1UL << bit))) continue;
        KeyEvent ev;
        ev.key = KEYMAP[bit / KB_COLS][bit % KB_COLS];
        xQueueSend(queue_, &ev, 0);              // si la cola está llena, se descarta
        if (isRepeatable(ev.key)) { heldBit = bit; nextRepeatAt = now + KB_REPEAT_DELAY; }
      }
    }

    // --- Autorrepetición (flechas y DEL) ------------------------------------
    if (heldBit >= 0) {
      if (!(stable & (1UL << heldBit))) {
        heldBit = -1;                            // soltada
      } else if ((int32_t)(now - nextRepeatAt) >= 0) {
        KeyEvent ev;
        ev.key = KEYMAP[heldBit / KB_COLS][heldBit % KB_COLS];
        ev.repeat = true;
        xQueueSend(queue_, &ev, 0);
        nextRepeatAt = now + KB_REPEAT_RATE;
      }
    }
  }
}
