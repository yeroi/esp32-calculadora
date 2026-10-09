// =============================================================================
//  RemoteFS.cpp  —  Sistema de archivos virtual "/pc" (ver RemoteFS.h)
// =============================================================================
#include "RemoteFS.h"
#include <dirent.h>
#include <errno.h>
#include <esp_vfs.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <vector>
#include <vfs_api.h>
#include "RemoteLink.h"

RemoteFS pcFS;

namespace {

constexpr size_t READ_CHUNK = Proto::MAX_PAYLOAD - 96;   // bytes por petición de lectura
constexpr size_t MAX_ENTRIES = 400;        // tope por carpeta
constexpr uint32_t CACHE_MS = 3000;        // validez de la caché de "stat"
constexpr int MAX_FILES = 8;

struct Ent {
  String name;
  uint32_t size;
  bool dir;
};

// ---- Utilidades -----------------------------------------------------------------
String norm(const char* p) {
  String s = (p && *p) ? String(p) : String("/");
  if (!s.startsWith("/")) s = "/" + s;
  while (s.length() > 1 && s.endsWith("/")) s.remove(s.length() - 1);
  return s;
}

void put16(uint8_t*& p, uint32_t v) { *p++ = v & 0xFF; *p++ = (v >> 8) & 0xFF; }
void put32(uint8_t*& p, uint32_t v) { put16(p, v & 0xFFFF); put16(p, v >> 16); }
uint32_t get32(const uint8_t* p) { return p[0] | (p[1] << 8) | (p[2] << 16) | ((uint32_t)p[3] << 24); }

int fail(int e) { errno = e; return -1; }

// ---- Caché del último listado (evita una petición por cada archivo) -----------
String cacheDir;
std::vector<Ent> cacheEnts;
uint32_t cacheAt = 0;

bool cacheLookup(const String& path, uint32_t& size, bool& dir) {
  if (cacheDir.length() == 0 || millis() - cacheAt > CACHE_MS) return false;
  int slash = path.lastIndexOf('/');
  String parent = slash <= 0 ? String("/") : path.substring(0, slash);
  if (parent != cacheDir) return false;
  String name = path.substring(slash + 1);
  for (const Ent& e : cacheEnts) {
    if (e.name == name) { size = e.size; dir = e.dir; return true; }
  }
  return false;
}

// 0 = no existe, 1 = archivo, 2 = carpeta; <0 = error del enlace
int remoteStat(const String& path, uint32_t& size) {
  bool dir;
  if (path == "/") { size = 0; return 2; }
  if (cacheLookup(path, size, dir)) return dir ? 2 : 1;
  uint8_t resp[5];
  int n = remoteLink.request(Proto::FS_STAT, reinterpret_cast<const uint8_t*>(path.c_str()),
                             path.length(), resp, sizeof resp);
  if (n < 0) return n;
  if (n < 5) return -EIO;
  size = get32(resp + 1);
  return resp[0];
}

bool remoteList(const String& path, std::vector<Ent>& out) {
  out.clear();
  static uint8_t resp[Proto::MAX_PAYLOAD];   // solo la UI lista carpetas
  uint8_t req[2 + 300];
  if (path.length() > 300) return false;
  for (;;) {
    uint8_t* p = req;
    put16(p, out.size());
    memcpy(p, path.c_str(), path.length());
    int n = remoteLink.request(Proto::FS_LIST, req, 2 + path.length(), resp, sizeof resp);
    if (n < 1) return false;
    bool more = resp[0];
    size_t i = 1;
    size_t before = out.size();
    while (i + 6 <= (size_t)n && out.size() < MAX_ENTRIES) {
      uint8_t type = resp[i];
      uint32_t size = get32(resp + i + 1);
      uint8_t len = resp[i + 5];
      if (i + 6 + len > (size_t)n) break;
      String name;
      name.concat(reinterpret_cast<const char*>(resp + i + 6), len);
      out.push_back({name, size, type == 2});
      i += 6 + len;
    }
    if (!more || out.size() >= MAX_ENTRIES || out.size() == before) break;
  }
  cacheDir = path;
  cacheEnts = out;
  cacheAt = millis();
  return true;
}

// ---- Archivos abiertos ------------------------------------------------------------
struct RFile {
  bool used = false;
  String path;
  uint32_t size = 0;
  uint32_t pos = 0;
};
RFile files[MAX_FILES];

struct RDir {
  DIR base;                        // DEBE ir primero (lo rellena el VFS)
  struct dirent de;
  String path;
  std::vector<Ent>* ents;          // se pide al PC en el primer readdir()
  size_t idx;
};

// Abrir una carpeta solo para ver si lo es (como hace FS al listar) no
// cuesta nada: el contenido se pide la primera vez que se lee.
bool ensureListed(RDir* d) {
  if (d->ents) return true;
  d->ents = new (std::nothrow) std::vector<Ent>();
  if (!d->ents) return false;
  if (!remoteList(d->path, *d->ents)) d->ents->clear();
  return true;
}

// ---- Funciones del VFS ---------------------------------------------------------------
int rf_open(const char* path, int flags, int /*mode*/) {
  if ((flags & O_ACCMODE) != O_RDONLY || (flags & (O_CREAT | O_TRUNC | O_APPEND)))
    return fail(EROFS);
  String p = norm(path);
  uint32_t size = 0;
  int t = remoteStat(p, size);
  if (t < 0) return fail(-t);
  if (t == 0) return fail(ENOENT);
  if (t == 2) return fail(EISDIR);
  for (int fd = 0; fd < MAX_FILES; ++fd) {
    if (files[fd].used) continue;
    files[fd].used = true;
    files[fd].path = p;
    files[fd].size = size;
    files[fd].pos = 0;
    return fd;
  }
  return fail(ENFILE);
}

ssize_t rf_read(int fd, void* dst, size_t size) {
  if (fd < 0 || fd >= MAX_FILES || !files[fd].used) return fail(EBADF);
  RFile& f = files[fd];
  if (f.path.length() > 300) return fail(ENAMETOOLONG);
  uint8_t* out = static_cast<uint8_t*>(dst);
  size_t done = 0;
  uint8_t req[6 + 300];
  while (done < size && f.pos < f.size) {
    size_t want = size - done;
    if (want > READ_CHUNK) want = READ_CHUNK;
    if (want > f.size - f.pos) want = f.size - f.pos;
    uint8_t* p = req;
    put32(p, f.pos);
    put16(p, want);
    memcpy(p, f.path.c_str(), f.path.length());
    int n = remoteLink.request(Proto::FS_READ, req, 6 + f.path.length(), out + done, want);
    if (n < 0) {
      if (done) break;
      return fail(-n);
    }
    if (n == 0) break;                     // el archivo encogió en el PC
    done += n;
    f.pos += n;
  }
  return done;
}

ssize_t rf_write(int, const void*, size_t) { return fail(EROFS); }

off_t rf_lseek(int fd, off_t off, int whence) {
  if (fd < 0 || fd >= MAX_FILES || !files[fd].used) return fail(EBADF);
  RFile& f = files[fd];
  off_t base = whence == SEEK_SET ? 0 : whence == SEEK_CUR ? (off_t)f.pos : (off_t)f.size;
  off_t np = base + off;
  if (np < 0) return fail(EINVAL);
  f.pos = (uint32_t)np;
  return np;
}

int rf_close(int fd) {
  if (fd < 0 || fd >= MAX_FILES || !files[fd].used) return fail(EBADF);
  files[fd].used = false;
  files[fd].path = String();
  return 0;
}

void fillStat(struct stat* st, bool dir, uint32_t size) {
  memset(st, 0, sizeof *st);
  st->st_mode = dir ? (S_IFDIR | 0555) : (S_IFREG | 0444);
  st->st_size = size;
  st->st_blksize = 4096;              // newlib pide bloques de este tamaño
}

int rf_fstat(int fd, struct stat* st) {
  if (fd < 0 || fd >= MAX_FILES || !files[fd].used) return fail(EBADF);
  fillStat(st, false, files[fd].size);
  return 0;
}

int rf_stat(const char* path, struct stat* st) {
  uint32_t size = 0;
  int t = remoteStat(norm(path), size);
  if (t < 0) return fail(-t);
  if (t == 0) return fail(ENOENT);
  fillStat(st, t == 2, size);
  return 0;
}

DIR* rf_opendir(const char* name) {
  String p = norm(name);
  uint32_t sz;
  int t = remoteStat(p, sz);
  if (t != 2) { errno = t < 0 ? -t : (t == 1 ? ENOTDIR : ENOENT); return nullptr; }
  auto* d = new (std::nothrow) RDir();
  if (!d) { errno = ENOMEM; return nullptr; }
  d->path = p;
  d->ents = nullptr;
  d->idx = 0;
  return reinterpret_cast<DIR*>(d);
}

struct dirent* rf_readdir(DIR* pdir) {
  RDir* d = reinterpret_cast<RDir*>(pdir);
  if (!d || !ensureListed(d) || d->idx >= d->ents->size()) return nullptr;
  const Ent& e = (*d->ents)[d->idx++];
  memset(&d->de, 0, sizeof d->de);
  d->de.d_ino = d->idx;
  d->de.d_type = e.dir ? DT_DIR : DT_REG;
  strlcpy(d->de.d_name, e.name.c_str(), sizeof d->de.d_name);
  return &d->de;
}

long rf_telldir(DIR* pdir) { return reinterpret_cast<RDir*>(pdir)->idx; }

void rf_seekdir(DIR* pdir, long off) {
  RDir* d = reinterpret_cast<RDir*>(pdir);
  if (off >= 0) d->idx = off;            // readdir() comprueba el final
}

int rf_closedir(DIR* pdir) {
  RDir* d = reinterpret_cast<RDir*>(pdir);
  if (!d) return fail(EBADF);
  delete d->ents;
  delete d;
  return 0;
}

int rf_readonly_path(const char*) { return fail(EROFS); }
int rf_mkdir(const char*, mode_t) { return fail(EROFS); }
int rf_rename(const char*, const char*) { return fail(EROFS); }

}  // namespace

// ---- RemoteFS -------------------------------------------------------------------
RemoteFS::RemoteFS() : fs::FS(fs::FSImplPtr(new VFSImpl())) {}

bool RemoteFS::begin(const char* mountpoint) {
  esp_vfs_t vfs;
  memset(&vfs, 0, sizeof vfs);
  vfs.flags = ESP_VFS_FLAG_DEFAULT;
  vfs.open = &rf_open;
  vfs.read = &rf_read;
  vfs.write = &rf_write;
  vfs.lseek = &rf_lseek;
  vfs.close = &rf_close;
  vfs.fstat = &rf_fstat;
  vfs.stat = &rf_stat;
  vfs.opendir = &rf_opendir;
  vfs.readdir = &rf_readdir;
  vfs.telldir = &rf_telldir;
  vfs.seekdir = &rf_seekdir;
  vfs.closedir = &rf_closedir;
  vfs.unlink = &rf_readonly_path;
  vfs.rmdir = &rf_readonly_path;
  vfs.mkdir = &rf_mkdir;
  vfs.rename = &rf_rename;
  if (esp_vfs_register(mountpoint, &vfs, nullptr) != ESP_OK) return false;
  _impl->mountpoint(mountpoint);
  return true;
}

// ---- Escritura ---------------------------------------------------------------------
static void invalidateCache() { cacheDir = ""; cacheAt = 0; }

static int pathOp(uint8_t op, const char* path) {
  size_t n = strlen(path);
  if (n > 300) return -ENAMETOOLONG;
  uint8_t resp[4];
  invalidateCache();
  int r = remoteLink.request(op, reinterpret_cast<const uint8_t*>(path), n, resp, sizeof resp, 5000);
  return r < 0 ? r : 0;
}

int RemoteFS::writeAt(const char* path, uint32_t off, const uint8_t* data, size_t len, bool trunc) {
  static uint8_t req[Proto::MAX_PAYLOAD];
  size_t pn = strlen(path);
  if (pn > 300) return -ENAMETOOLONG;
  const size_t room = Proto::MAX_PAYLOAD - 16 - pn;        // datos por trama
  invalidateCache();
  size_t done = 0;
  do {
    size_t n = len - done;
    if (n > room) n = room;
    uint8_t* p = req;
    put32(p, off + done);
    *p++ = (trunc && done == 0) ? 1 : 0;
    put16(p, pn);
    memcpy(p, path, pn); p += pn;
    if (n) { memcpy(p, data + done, n); p += n; }
    uint8_t resp[4];
    int r = remoteLink.request(Proto::FS_WRITE, req, p - req, resp, sizeof resp, 5000);
    if (r < 0) return r;
    done += n;
  } while (done < len);
  return (int)len;
}

int RemoteFS::remove(const char* path) { return pathOp(Proto::FS_REMOVE, path); }
int RemoteFS::mkdir(const char* path) { return pathOp(Proto::FS_MKDIR, path); }
int RemoteFS::rmdir(const char* path) { return pathOp(Proto::FS_RMDIR, path); }

int RemoteFS::rename(const char* from, const char* to) {
  uint8_t req[2 + 300 + 300];
  size_t a = strlen(from), b = strlen(to);
  if (a > 300 || b > 300) return -ENAMETOOLONG;
  uint8_t* p = req;
  put16(p, a);
  memcpy(p, from, a); p += a;
  memcpy(p, to, b); p += b;
  uint8_t resp[4];
  invalidateCache();
  int r = remoteLink.request(Proto::FS_RENAME, req, p - req, resp, sizeof resp, 5000);
  return r < 0 ? r : 0;
}

bool RemoteFS::info(uint64_t& total, uint64_t& freeB) {
  uint8_t resp[16];
  total = freeB = 0;
  if (remoteLink.request(Proto::FS_INFO, nullptr, 0, resp, sizeof resp) < 16) return false;
  total = (uint64_t)get32(resp) | ((uint64_t)get32(resp + 4) << 32);
  freeB = (uint64_t)get32(resp + 8) | ((uint64_t)get32(resp + 12) << 32);
  return true;
}
