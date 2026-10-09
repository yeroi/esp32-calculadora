// =============================================================================
//  PackageManifest.h  —  Lectura de /lib/paquetes.json
// -----------------------------------------------------------------------------
//  Formato (lo escribe SciCalc Link en el PC):
//    { "nombre": { "version": "1.0", "source": "micropython-lib",
//                  "files": ["/lib/nombre.py", ...] }, ... }
//  Solo LECTURA: desinstalar implica borrar archivos y eso pasará por el
//  gestor de permisos (Paso 5).
// =============================================================================
#pragma once
#include <Arduino.h>
#include <vector>
#include "Storage.h"

struct PackageInfo {
  String name;
  String version;
  String source;
  uint16_t files = 0;
};

namespace PackageManifest {
constexpr const char* PATH = "/lib/paquetes.json";
// Devuelve la lista ordenada por nombre (vacía si no hay manifiesto).
std::vector<PackageInfo> read(Storage& sd);
}
