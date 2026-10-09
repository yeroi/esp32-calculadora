// =============================================================================
//  RemoteFS.h  —  La "MicroSD" del modo PC: una carpeta del ordenador
// -----------------------------------------------------------------------------
//  Se registra en el VFS de ESP-IDF bajo "/pc" y se envuelve en un fs::FS
//  (igual que hace la librería SD con "/sd"). Así Storage, el visor de
//  archivos y los decodificadores de imagen usan fs::File como siempre y no
//  saben que los bytes vienen por el cable USB.
//
//  Por el VFS solo se LEE (abrir en escritura falla con EROFS). Las escrituras
//  van por los métodos de abajo, que solo usa Storage para el sandbox de
//  Python DESPUÉS de que el usuario haya dado permiso.
//  Cada lectura es una petición al PC (~4 KB); la librería FS ya pone un
//  búfer de 4 KB delante, así que hay pocas idas y vueltas.
// =============================================================================
#pragma once
#include <Arduino.h>
#include <FS.h>

class RemoteFS : public fs::FS {
 public:
  RemoteFS();
  bool begin(const char* mountpoint = "/pc");
  // Capacidad y espacio libre del disco del PC (0 si no hay respuesta)
  bool info(uint64_t& total, uint64_t& freeB);

  // Escritura (devuelven 0 / bytes escritos, o -errno)
  int writeAt(const char* path, uint32_t off, const uint8_t* data, size_t len, bool trunc);
  int remove(const char* path);
  int rename(const char* from, const char* to);
  int mkdir(const char* path);
  int rmdir(const char* path);
};

extern RemoteFS pcFS;
