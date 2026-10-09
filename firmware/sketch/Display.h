// =============================================================================
//  Display.h  —  Capa gráfica (HAL de pantalla)
// -----------------------------------------------------------------------------
//  Las apps NUNCA usan la librería de la pantalla directamente: solo esta
//  clase. Tiene dos "motores", elegidos con SCICALC_REMOTE en config.h:
//    * TFT  (0): Adafruit_ILI9341 (la que soporta Wokwi); en el hardware real
//                se cambiará por TFT_eSPI + DMA sin tocar las apps.
//    * PC   (1): cada primitiva se manda como una orden por USB al programa
//                pc/scicalc_pantalla.py, que la dibuja. El texto viaja como
//                códigos de glifo: cada glifo (5x8) se envía una sola vez.
//
//  Sin PSRAM no cabe un framebuffer de 320x240x2 = 150 KB, así que TODO se
//  dibuja directamente en la pantalla y cada app redibuja solo lo que cambia.
//
//  Texto: acepta UTF-8 (á, é, ñ, π, √, ², ▲ ...) y lo traduce a la fuente
//  CP437 integrada (6x8 px). Los pocos símbolos que CP437 no tiene
//  (×, −, ʸ, …) se dibujan con glifos propios definidos en Display.cpp.
// =============================================================================
#pragma once
#include <Arduino.h>
#include <Adafruit_GFX.h>
#include "Theme.h"
#include "config.h"
#if !SCICALC_REMOTE
#include <Adafruit_ILI9341.h>
#endif

enum class Align : uint8_t { Left, Center, Right };

class Display {
 public:
  static constexpr int16_t W = 320;
  static constexpr int16_t H = 240;
  static constexpr int16_t HEADER_H = 22;            // barra de estado
  static constexpr int16_t BODY_Y = HEADER_H;
  static constexpr int16_t BODY_H = H - HEADER_H;
  static constexpr int16_t FOOTER_Y = H - 12;        // línea de ayuda inferior

  Display();
  bool begin();

  // true (una vez) si hay que repintar TODA la pantalla: el programa del PC
  // se acaba de (re)conectar y no sabe lo que había. Lo consulta el AppManager.
  bool takeFullRedraw();

  // ---- Primitivas -----------------------------------------------------------
  void clear(uint16_t color = Theme::BG);
  void clearBody(uint16_t color = Theme::BG);
  void fillRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t c);
  void drawRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t c);
  void fillRoundRect(int16_t x, int16_t y, int16_t w, int16_t h, int16_t r, uint16_t c);
  void drawRoundRect(int16_t x, int16_t y, int16_t w, int16_t h, int16_t r, uint16_t c);
  void fillTriangle(int16_t x0, int16_t y0, int16_t x1, int16_t y1,
                    int16_t x2, int16_t y2, uint16_t c);
  void hLine(int16_t x, int16_t y, int16_t w, uint16_t c);
  void vLine(int16_t x, int16_t y, int16_t h, uint16_t c);

  // Vuelca un bloque de píxeles RGB565 (orden nativo del ESP32). Se recorta
  // a la pantalla. Lo usan los decodificadores de imagen.
  void pushPixels(int16_t x, int16_t y, int16_t w, int16_t h, const uint16_t* px);

  // ---- Texto (fuente 6x8 escalada; size 1 = 6x8, 2 = 12x16, 3 = 18x24) ----
  // Pinta con fondo opaco: reescribir encima no deja "restos".
  //  boxW > 0  -> alinea dentro de una caja de ese ancho
  //  maxW > 0  -> recorta el texto para que no pase de maxW píxeles
  //  bold      -> negrita "falsa" (segunda pasada desplazada 1 px)
  void text(int16_t x, int16_t y, const char* utf8, uint8_t size,
            uint16_t fg, uint16_t bg, Align align = Align::Left, int16_t boxW = 0,
            bool bold = false, int16_t maxW = 0);
  // Atajo para negrita alineada a la izquierda con recorte opcional
  void textBold(int16_t x, int16_t y, const char* utf8, uint8_t size,
                uint16_t fg, uint16_t bg, int16_t maxW = 0) {
    text(x, y, utf8, size, fg, bg, Align::Left, 0, true, maxW);
  }
  // Línea de ayuda centrada en la parte inferior de la pantalla
  void footer(const char* utf8);

  static int16_t textWidth(const char* utf8, uint8_t size);
  static size_t  utf8Length(const char* utf8);        // nº de caracteres
  static int16_t charW(uint8_t size) { return 6 * size; }
  static int16_t charH(uint8_t size) { return 8 * size; }

  // Decodifica un carácter UTF-8 y avanza el puntero (devuelve code point)
  static uint16_t decodeUtf8(const char*& p);

 private:
  void drawGlyph(int16_t x, int16_t y, uint16_t cp, uint8_t size,
                 uint16_t fg, uint16_t bg, bool bold);
  static uint8_t toCp437(uint16_t cp);
  static const uint8_t* customGlyph(uint16_t cp);

#if SCICALC_REMOTE
  // ---- Motor PC -------------------------------------------------------------
  uint16_t glyphId(uint16_t cp);                 // asegura que el PC lo tiene
  void sendShape(uint8_t type, const int16_t* v, uint8_t nv, uint16_t c);
  void sendPixelRows(int16_t x, int16_t y, int16_t w, int16_t h, const uint16_t* px,
                     int16_t stride);
  uint32_t session_ = 0;                         // sesión del PC de la caché de glifos
  uint32_t redrawSession_ = 0;                   // sesión ya repintada
  uint32_t glyphSent_[(256 + 8 + 31) / 32] = {}; // bit = glifo ya enviado
  GFXcanvas1 glyphCanvas_{6, 8};                 // para sacar los glifos de la fuente
  uint8_t* scratch_ = nullptr;                   // búfer de trama (PIXELS)
#else
  Adafruit_ILI9341 tft_;
#endif
};
