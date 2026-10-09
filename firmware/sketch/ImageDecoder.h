// =============================================================================
//  ImageDecoder.h  —  Visor de imágenes de la SD sin framebuffer
// -----------------------------------------------------------------------------
//  Formatos:
//    PNG  -> PNGdec (bitbank2)       ~45 KB de RAM mientras se decodifica
//    JPG  -> TJpg_Decoder (Bodmer)   ~4 KB  (baseline; el JPG progresivo NO)
//    GIF  -> AnimatedGIF (bitbank2)  ~25 KB (solo el primer fotograma)
//    BMP  -> propio (8, 24 y 32 bits sin comprimir)
//
//  Como no hay PSRAM, la imagen nunca está entera en memoria: se decodifica
//  línea a línea (o por bloques en JPG) y cada línea se escala al vuelo
//  (vecino más próximo) y se envía a la pantalla. Toda la RAM se pide al
//  empezar y se devuelve al acabar.
//
//  Escalado igual que el simulador: se ajusta al área conservando la
//  proporción, con un aumento máximo de x4.
//
//  Límites (ESP32 sin PSRAM):
//    * PNG: ancho máximo ~320 px en RGBA o ~426 px en RGB con la
//      configuración por defecto de PNGdec. En PlatformIO se amplía con
//      -DPNG_MAX_BUFFERED_PIXELS (ver platformio.ini).
//    * GIF: ancho máximo 480 px (límite de AnimatedGIF en ESP32).
// =============================================================================
#pragma once
#include <Arduino.h>
#include "Display.h"
#include "Storage.h"

namespace ImageDecoder {

struct Rect { int16_t x, y, w, h; };

struct Info {
  uint16_t w = 0, h = 0;
  const char* format = "?";      // "PNG", "JPG", "GIF", "BMP"
};

// Lee solo la cabecera (por los "bytes mágicos", no por la extensión).
// false si el formato no se reconoce.
bool probe(Storage& sd, const String& path, Info& info);

// Dibuja la imagen escalada y centrada en 'area'. Si falla devuelve false y
// deja en 'err' un mensaje para el usuario.
bool draw(Display& gfx, Storage& sd, const String& path, const Rect& area, String& err);

}  // namespace ImageDecoder
