// =============================================================================
//  Storage.h  —  Acceso a la MicroSD (FAT32) — API de SOLO LECTURA
// -----------------------------------------------------------------------------
//  Las apps solo LEEN. Las funciones de escritura existen únicamente para el
//  sandbox de Python (PySandbox), que antes de llamarlas pregunta al usuario
//  con un diálogo de permiso. Todo pasa por aquí: nadie más toca la SD.
//
//  Modo PC (SCICALC_REMOTE_SD = 1): la "tarjeta" es una carpeta del PC
//  (RemoteFS); el resto del código no nota la diferencia.
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
  // En modo PC la "tarjeta" está montada mientras el programa del PC esté
  // conectado; con MicroSD física, si begin() la encontró.
  bool mounted() const;
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

  // 0 = no existe, 1 = archivo, 2 = carpeta (y su tamaño)
  int stat(const String& path, uint32_t& size);

  // ---- ESCRITURA ---------------------------------------------------------------
  // SOLO las usa el sandbox de Python, y SOLO después de que el usuario haya
  // dicho que sí en el diálogo de permiso. Devuelven bytes / 0, o -errno.
  int writeAt(const String& path, uint32_t off, const uint8_t* data, size_t len, bool trunc);
  int removeFile(const String& path);
  int renamePath(const String& from, const String& to);
  int makeDir(const String& path);
  int removeDir(const String& path);

 private:
  bool mounted_ = false;
  fs::FS* fs_ = nullptr;         // &SD o &pcFS (modo PC)
  uint64_t cardSize_ = 0;
  uint8_t cardType_ = 0;
  int64_t free_ = -1;            // caché de freeBytes()
};
