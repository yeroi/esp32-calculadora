// =============================================================================
//  Storage.cpp
// =============================================================================
#include "Storage.h"
#include <SD.h>
#include <SPI.h>
#include <algorithm>
#include <errno.h>
#include "config.h"
#include "RemoteFS.h"
#include "RemoteLink.h"

// ---- Rutas --------------------------------------------------------------------
namespace Path {

String join(const String& dir, const String& name) {
  if (dir.length() == 0 || dir == "/") return "/" + name;
  return dir.endsWith("/") ? dir + name : dir + "/" + name;
}

String parent(const String& path) {
  int slash = path.lastIndexOf('/');
  if (slash <= 0) return "/";
  return path.substring(0, slash);
}

String name(const String& path) {
  int slash = path.lastIndexOf('/');
  return slash < 0 ? path : path.substring(slash + 1);
}

String ext(const String& path) {
  String n = name(path);
  int dot = n.lastIndexOf('.');
  if (dot <= 0) return "";                 // ".bashrc" no tiene extensión
  String e = n.substring(dot);
  e.toLowerCase();
  return e;
}

bool isSafe(const String& path) {
  if (!path.startsWith("/")) return false;
  // Rechaza cualquier componente ".." (no se puede salir de la SD)
  int start = 0;
  while (start <= (int)path.length()) {
    int end = path.indexOf('/', start);
    if (end < 0) end = path.length();
    if (end - start == 2 && path[start] == '.' && path[start + 1] == '.') return false;
    start = end + 1;
  }
  return true;
}

FileKind kind(const String& n, bool isDir) {
  if (isDir) return FileKind::Dir;
  String e = ext(n);
  if (e == ".py") return FileKind::Py;
  if (e == ".png" || e == ".jpg" || e == ".jpeg" || e == ".bmp" || e == ".gif")
    return FileKind::Img;
  static const char* const TXT[] = {".txt", ".md", ".csv", ".json", ".ini", ".cfg",
                                    ".log", ".html", ".xml", ".toml"};
  for (const char* t : TXT) if (e == t) return FileKind::Txt;
  return FileKind::Bin;
}

}  // namespace Path

String humanSize(uint64_t b) {
  char buf[16];
  if (b < 1024) snprintf(buf, sizeof buf, "%u B", (unsigned)b);
  else if (b < (1ULL << 20)) snprintf(buf, sizeof buf, "%u KB", (unsigned)((b + 512) / 1024));
  else if (b < (1ULL << 30)) snprintf(buf, sizeof buf, "%.1f MB", b / 1048576.0);
  else snprintf(buf, sizeof buf, "%.1f GB", b / 1073741824.0);
  return String(buf);
}

// ---- Tarjeta ----------------------------------------------------------------
bool Storage::begin() {
#if SCICALC_REMOTE_SD
  fs_ = &pcFS;
  mounted_ = pcFS.begin("/pc");
  cardType_ = 0xFE;                        // "PC"
  return mounted();
#else
  fs_ = &SD;
#if SCICALC_REMOTE
  SPI.begin(PIN_SPI_SCK, PIN_SPI_MISO, PIN_SPI_MOSI);   // sin TFT nadie lo abrió
#endif
  // El bus SPI ya lo inicializa Display::begin(); aquí solo añadimos el CS.
  pinMode(PIN_SD_CS, OUTPUT);
  digitalWrite(PIN_SD_CS, HIGH);
  mounted_ = SD.begin(PIN_SD_CS, SPI, SD_SPI_HZ, "/sd", 5);
  if (mounted_) {
    cardType_ = SD.cardType();
    cardSize_ = SD.cardSize();
    if (cardType_ == CARD_NONE) mounted_ = false;
  }
  return mounted_;
#endif
}

bool Storage::mounted() const {
#if SCICALC_REMOTE_SD
  return mounted_ && remoteLink.connected();
#else
  return mounted_;
#endif
}

const char* Storage::cardTypeName() const {
  switch (cardType_) {
    case 0xFE:      return "PC";
    case CARD_MMC:  return "MMC";
    case CARD_SD:   return "SDSC";
    case CARD_SDHC: return "SDHC";
    default:        return "?";
  }
}

uint64_t Storage::freeBytes() {
  if (!mounted()) return 0;
#if SCICALC_REMOTE_SD
  if (free_ < 0) {
    uint64_t total, freeB;
    if (pcFS.info(total, freeB)) { cardSize_ = total; free_ = (int64_t)freeB; }
    else return 0;
  }
#else
  if (free_ < 0) free_ = (int64_t)(SD.totalBytes() - SD.usedBytes());
#endif
  return (uint64_t)free_;
}

// ---- Lectura ----------------------------------------------------------------
static bool lessNoCase(const DirEntry& a, const DirEntry& b) {
  if (a.dir != b.dir) return a.dir;                         // carpetas primero
  return strcasecmp(a.name.c_str(), b.name.c_str()) < 0;
}

bool Storage::listDir(const String& dir, std::vector<DirEntry>& out, bool onlyPy,
                      bool* truncated) {
  out.clear();
  if (truncated) *truncated = false;
  if (!mounted() || !Path::isSafe(dir)) return false;
  fs::File root = fs_->open(dir);
  if (!root || !root.isDirectory()) return false;

  for (fs::File f = root.openNextFile(); f; f = root.openNextFile()) {
    String n = Path::name(String(f.name()));   // en core 1.x name() traía la ruta
    bool d = f.isDirectory();
    uint32_t sz = d ? 0 : (uint32_t)f.size();
    f.close();
    if (n.length() == 0 || n.startsWith(".")) continue;
    if (d && n.startsWith("__")) continue;      // __pycache__ y similares
    if (!d && onlyPy && Path::ext(n) != ".py") continue;
    if (out.size() >= MAX_DIR_ENTRIES) { if (truncated) *truncated = true; break; }
    out.push_back({n, sz, d});
  }
  root.close();
  std::sort(out.begin(), out.end(), lessNoCase);
  return true;
}

bool Storage::exists(const String& path) {
  return mounted() && Path::isSafe(path) && fs_->exists(path);
}

bool Storage::isDir(const String& path) {
  if (!exists(path)) return false;
  fs::File f = fs_->open(path);
  bool d = f && f.isDirectory();
  f.close();
  return d;
}

uint32_t Storage::fileSize(const String& path) {
  fs::File f = openRead(path);
  uint32_t s = f ? (uint32_t)f.size() : 0;
  f.close();
  return s;
}

fs::File Storage::openRead(const String& path) {
  if (!mounted() || !Path::isSafe(path)) return fs::File();
  return fs_->open(path, FILE_READ);                  // SOLO lectura
}

size_t Storage::readAt(const String& path, uint32_t offset, uint8_t* buf, size_t len) {
  fs::File f = openRead(path);
  if (!f || f.isDirectory()) return 0;
  size_t n = 0;
  if (f.seek(offset)) n = f.read(buf, len);
  f.close();
  return n;
}

bool Storage::readText(const String& path, String& out, size_t maxBytes) {
  fs::File f = openRead(path);
  if (!f || f.isDirectory()) return false;
  if (f.size() > maxBytes) { f.close(); return false; }
  out = "";
  out.reserve(f.size() + 1);
  uint8_t buf[256];
  while (f.available()) {
    size_t n = f.read(buf, sizeof buf);
    if (n == 0) break;
    out.concat(reinterpret_cast<const char*>(buf), n);
  }
  f.close();
  return true;
}

int Storage::stat(const String& path, uint32_t& size) {
  size = 0;
  if (!mounted() || !Path::isSafe(path)) return 0;
  if (path == "/") return 2;
  fs::File f = fs_->open(path);
  if (!f) return 0;
  int t = f.isDirectory() ? 2 : 1;
  if (t == 1) size = (uint32_t)f.size();
  f.close();
  return t;
}

// ---- Escritura (solo para el sandbox, tras el permiso) ---------------------------
int Storage::writeAt(const String& path, uint32_t off, const uint8_t* data, size_t len, bool trunc) {
  if (!mounted()) return -EIO;
  if (!Path::isSafe(path) || path == "/") return -EACCES;
  free_ = -1;
#if SCICALC_REMOTE_SD
  return pcFS.writeAt(path.c_str(), off, data, len, trunc);
#else
  uint32_t size;
  int t = stat(path, size);
  if (t == 2) return -EISDIR;
  fs::File f = fs_->open(path, (trunc || t == 0) ? "w" : "r+");
  if (!f) return -EIO;
  if (off && !f.seek(off)) { f.close(); return -EIO; }
  size_t n = len ? f.write(data, len) : 0;
  f.close();
  return n == len ? (int)n : -EIO;
#endif
}

int Storage::removeFile(const String& path) {
  if (!mounted()) return -EIO;
  if (!Path::isSafe(path) || path == "/") return -EACCES;
  free_ = -1;
#if SCICALC_REMOTE_SD
  return pcFS.remove(path.c_str());
#else
  return fs_->remove(path) ? 0 : -EIO;
#endif
}

int Storage::renamePath(const String& from, const String& to) {
  if (!mounted()) return -EIO;
  if (!Path::isSafe(from) || !Path::isSafe(to) || from == "/" || to == "/") return -EACCES;
#if SCICALC_REMOTE_SD
  return pcFS.rename(from.c_str(), to.c_str());
#else
  return fs_->rename(from, to) ? 0 : -EIO;
#endif
}

int Storage::makeDir(const String& path) {
  if (!mounted()) return -EIO;
  if (!Path::isSafe(path) || path == "/") return -EACCES;
#if SCICALC_REMOTE_SD
  return pcFS.mkdir(path.c_str());
#else
  return fs_->mkdir(path) ? 0 : -EIO;
#endif
}

int Storage::removeDir(const String& path) {
  if (!mounted()) return -EIO;
  if (!Path::isSafe(path) || path == "/") return -EACCES;
#if SCICALC_REMOTE_SD
  return pcFS.rmdir(path.c_str());
#else
  return fs_->rmdir(path) ? 0 : -EIO;
#endif
}
