// =============================================================================
//  ScrollList.h  —  Lógica de una lista con selección y desplazamiento
// -----------------------------------------------------------------------------
//  No dibuja nada: solo lleva la cuenta de qué elemento está seleccionado y
//  cuál es el primero visible. Lo usan el menú, el explorador y los Ajustes
//  para decidir si basta con repintar 2 filas o hay que repintar la lista.
// =============================================================================
#pragma once
#include <stdint.h>

struct ScrollList {
  uint16_t count = 0;      // nº de elementos
  uint16_t sel = 0;        // seleccionado
  uint16_t top = 0;        // primero visible
  uint8_t  rows = 7;       // filas visibles

  void reset(uint16_t n, uint8_t visible) {
    count = n;
    rows = visible;
    if (sel >= n) sel = n ? n - 1 : 0;
    fix();
  }

  // Ajusta 'top' para que 'sel' sea visible. true si 'top' cambió.
  bool fix() {
    uint16_t old = top;
    if (sel < top) top = sel;
    else if (sel >= top + rows) top = sel - rows + 1;
    if (count <= rows) top = 0;
    return top != old;
  }

  // Mueve la selección (con vuelta al principio/final).
  // Devuelve true si cambió 'top' (hay que repintar toda la lista).
  bool move(int delta) {
    if (!count) return false;
    sel = static_cast<uint16_t>((sel + count + (delta % (int)count)) % count);
    return fix();
  }

  bool select(uint16_t i) {
    if (i >= count) return false;
    sel = i;
    return fix();
  }

  bool visible(uint16_t i) const { return i >= top && i < top + rows; }
};
