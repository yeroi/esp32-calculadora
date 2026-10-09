// =============================================================================
//  Storage.h  —  Acceso a la MicroSD (FAT32) — API de SOLO LECTURA
// -----------------------------------------------------------------------------
//  Esta clase no tiene, a propósito, ninguna función para escribir, renombrar
//  o borrar. Es la primera capa de seguridad del sandbox de Python: las apps
//  y el intérprete solo llegan a la SD a través de aquí. Las escrituras
//  pasarán por el gestor de permisos (Paso 5), que pregunta al usuario.
//
//  Rutas: siempre absolutas dentro de la SD ("/scripts/hola.py"). Cualquier
//  ruta con ".." se rechaza: no se puede salir de la SD.
// =============================================================================
#pragma once
#include <Arduino.h>
#include <FS.h>
#include <vector>

// Tipo de archivo, según la extensión (igual que file_kind() del simulador)
enum class FileKind : uint8_t { Up, Dir, Py, Img, Txt, Bin };

struct DirEntry {
  String   name;     // solo el nombre, sin ruta
  uint32_t size;     // bytes (0 en carpetas)
  bool     dir;
};

// ---- Utilidades de rutas (sin acceso a la SD) -------------------------------
namespace Path {
  String join(const String& dir, const String& name);   // "/a" + "b" -> "/a/b"
  String parent(const String& path);                     // "/a/b" -> "/a"; "/" -> "/"
  String name(const String& path);                       // "/a/b.py" -> "b.py"
  String ext(const String& path);                        // ".py" en minúsculas, o ""
  bool   isSafe(const String& path);                     // absoluta y sin ".."
  FileKind kind(const String& name, bool isDir);
}

// Tamaño legible: "512 B", "12 KB", "3.4 MB"
String humanSize(uint64_t bytes);

class Storage {
 public:
  static constexpr size_t MAX_DIR_ENTRIES = 300;   // tope de RAM por carpeta

  bool begin();
  bool mounted() const { return mounted_; }
  uint64_t cardSizeBytes() const { return cardSize_; }
  const char* cardTypeName() const;
  // Espacio libre. La primera llamada puede tardar (FAT grande): se cachea.
  uint64_t freeBytes();

  // Lista una carpeta: carpetas primero, luego archivos, orden alfabético sin
  // distinguir mayúsculas. Oculta los nombres que empiezan por "." (y "__" en
  // carpetas, p. ej. __pycache__). onlyPy = solo archivos .py (y carpetas).
  // Devuelve false si la carpeta no existe. 'truncated' = había más entradas.
  bool listDir(const String& dir, std::vector<DirEntry>& out, bool onlyPy,
               bool* truncated = nullptr);

  bool exists(const String& path);
  bool isDir(const String& path);
  uint32_t fileSize(const String& path);

  // Abre en modo LECTURA. Devuelve un File inválido si la ruta no es segura.
  fs::File openRead(const String& path);

  // Lee hasta 'len' bytes desde 'offset'. Devuelve los bytes leídos.
  size_t readAt(const String& path, uint32_t offset, uint8_t* buf, size_t len);

  // Lee un archivo de texto entero (máx. maxBytes). false si es mayor o no existe.
  bool readText(const String& path, String& out, size_t maxBytes = 16 * 1024);

 private:
  bool mounted_ = false;
  uint64_t cardSize_ = 0;
  uint8_t cardType_ = 0;
  int64_t free_ = -1;            // caché de freeBytes()
};
