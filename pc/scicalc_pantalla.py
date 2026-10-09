#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 SciCalc Pantalla — el PC hace de pantalla, teclado, MicroSD y altavoz
===============================================================================
 El firmware corre ENTERO en el ESP32 (menú, apps, diálogos, archivos...).
 Este programa solo hace de periféricos, por el cable USB:

   ESP32 -> PC   órdenes de dibujo (rectángulos, texto, píxeles), tonos,
                 estado del sistema y peticiones de archivos (leer; escribir
                 solo si en la calculadora le diste permiso al script)
   PC -> ESP32   teclas (pulsar/soltar), archivos de la "MicroSD" (una
                 carpeta del PC, por defecto ../simulador/sd), batería simulada

 Requisitos:   pip install pygame-ce pyserial
 Firmware:     config.h con SCICALC_REMOTE 1 (viene así por defecto)

 Ejecutar:
   python scicalc_pantalla.py                    # busca el puerto solo
   python scicalc_pantalla.py --puerto COM5      # Windows
   python scicalc_pantalla.py --puerto /dev/ttyUSB0 --baudios 460800
   python scicalc_pantalla.py --sd E:\\           # otra carpeta como "SD"
   python scicalc_pantalla.py --lista            # ver puertos disponibles

 Teclado del PC (igual que el simulador):
   0-9 . + - * / ^ ( )    →  teclas equivalentes
   Enter = EXE   Retroceso = DEL   Esc = AC   Tab = SHIFT   M / Inicio = MENU
   Flechas = cursor     s c t = sin cos tan    l = ln    r = √
   p = π   e = e   a = Ans   ! = factorial   d = DEG/RAD
   F2 = sonido sí/no   F5/F6 = batería −/+   F7 = cargando   F12 = captura
   F9 = reiniciar el ESP32
 Los mensajes del ESP32 (Serial.printf) salen en esta consola.
===============================================================================
"""
import argparse
import array
import errno
import math
import os
import queue
import shutil
import struct
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

try:
    import pygame
except ImportError:
    print("Falta pygame. Instálalo con:  pip install pygame-ce")
    sys.exit(1)
try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("Falta pyserial. Instálalo con:  pip install pyserial")
    sys.exit(1)

# =============================================================================
#  Protocolo (igual que firmware/sketch/RemoteLink.h)
# =============================================================================
SYNC = b"\xA5\x5A"
PROTO_VERSION = 1
MAX_PAYLOAD = 4096

# ESP32 -> PC
HELLO, STATE = 0x01, 0x03
FILL, RECT, FILL_RR, RECT_RR, TRI = 0x10, 0x11, 0x12, 0x13, 0x14
PIXELS, PIXELS_RLE, GLYPH, TEXT = 0x15, 0x16, 0x17, 0x18
TONE = 0x20
FS_REQ = 0x40
# PC -> ESP32
PC_HELLO, PC_KEY, PC_SET, PC_PING, FS_RESP = 0x81, 0x82, 0x83, 0x84, 0xC0
# Archivos
FS_STAT, FS_LIST, FS_READ, FS_INFO = 1, 2, 3, 4
FS_WRITE, FS_REMOVE, FS_RENAME, FS_MKDIR, FS_RMDIR = 5, 6, 7, 8, 9   # solo tras el permiso en la calculadora

TFT_W, TFT_H = 320, 240
DRAW_TYPES = {FILL, RECT, FILL_RR, RECT_RR, TRI, PIXELS, PIXELS_RLE, GLYPH, TEXT}

# Chips USB-serie habituales en placas ESP32 (VID)
USB_VIDS = {0x10C4: "CP210x", 0x1A86: "CH340", 0x0403: "FTDI", 0x303A: "ESP32 USB"}


def frame(t, payload=b""):
    n = len(payload)
    head = bytes((t, n & 0xFF, n >> 8))
    return SYNC + head + payload + bytes(((sum(head) + sum(payload)) & 0xFF,))


# RGB565 -> (r, g, b)
def rgb565(c):
    r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
    return ((r * 527 + 23) >> 6, (g * 259 + 33) >> 6, (b * 527 + 23) >> 6)


RGB_TABLE = None          # 65536 entradas de 3 bytes (se crea al arrancar)


def build_rgb_table():
    global RGB_TABLE
    RGB_TABLE = [bytes(rgb565(c)) for c in range(65536)]


# =============================================================================
#  La "MicroSD": una carpeta del PC. Las escrituras solo llegan cuando el
#  usuario ha dicho que sí en el diálogo de PERMISO de la calculadora.
# =============================================================================
class SdFolder:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def real(self, p):
        p = (p or "/").replace("\\", "/")
        q = (self.root / p.lstrip("/")).resolve()
        if q != self.root and self.root not in q.parents:
            raise PermissionError(errno.EACCES, "fuera de la SD")
        return q

    def show(self, q):
        rel = q.relative_to(self.root).as_posix()
        return "/" + rel if rel != "." else "/"

    def handle(self, op, data):
        """Devuelve (estado, bytes). estado = 0 OK o un errno."""
        try:
            if op == FS_STAT:
                q = self.real(data.decode("utf-8", "replace"))
                if q.is_dir():
                    return 0, struct.pack("<BI", 2, 0)
                if q.is_file():
                    return 0, struct.pack("<BI", 1, min(q.stat().st_size, 0xFFFFFFFF))
                return 0, struct.pack("<BI", 0, 0)
            if op == FS_LIST:
                start = struct.unpack_from("<H", data)[0]
                q = self.real(data[2:].decode("utf-8", "replace"))
                if not q.is_dir():
                    return (errno.ENOTDIR if q.exists() else errno.ENOENT), b""
                names = sorted(os.listdir(q), key=str.lower)
                out = bytearray(b"\x00")
                i = start
                while i < len(names):
                    n = names[i]
                    raw = n.encode("utf-8")
                    if len(raw) > 255:
                        i += 1
                        continue
                    if len(out) + 6 + len(raw) > MAX_PAYLOAD - 8:
                        out[0] = 1                    # hay más: el ESP32 pide otra página
                        break
                    f = q / n
                    d = f.is_dir()
                    size = 0 if d else min(f.stat().st_size, 0xFFFFFFFF)
                    out += struct.pack("<BIB", 2 if d else 1, size, len(raw)) + raw
                    i += 1
                return 0, bytes(out)
            if op == FS_READ:
                off, ln = struct.unpack_from("<IH", data)
                q = self.real(data[6:].decode("utf-8", "replace"))
                if q.is_dir():
                    return errno.EISDIR, b""
                with open(q, "rb") as fh:
                    fh.seek(off)
                    return 0, fh.read(min(ln, MAX_PAYLOAD - 8))
            if op == FS_INFO:
                du = shutil.disk_usage(self.root)
                return 0, struct.pack("<QQ", du.total, du.free)
            if op == FS_WRITE:
                off, trunc, pn = struct.unpack_from("<IBH", data)
                q = self.real(data[7:7 + pn].decode("utf-8", "replace"))
                if q == self.root or q.is_dir():
                    return errno.EISDIR, b""
                chunk = data[7 + pn:]
                mode = "wb" if trunc or not q.exists() else "r+b"
                with open(q, mode) as fh:
                    fh.seek(off)
                    fh.write(chunk)
                print(f"[PC] SD: escrito {self.show(q)} ({len(chunk)} B en {off})", flush=True)
                return 0, b""
            if op in (FS_REMOVE, FS_MKDIR, FS_RMDIR):
                q = self.real(data.decode("utf-8", "replace"))
                if q == self.root:
                    return errno.EACCES, b""
                if op == FS_REMOVE:
                    if q.is_dir():
                        return errno.EISDIR, b""
                    q.unlink()
                elif op == FS_MKDIR:
                    q.mkdir()
                else:
                    q.rmdir()
                print(f"[PC] SD: {('borrado', 'carpeta creada', 'carpeta borrada')[(FS_REMOVE, FS_MKDIR, FS_RMDIR).index(op)]} {self.show(q)}", flush=True)
                return 0, b""
            if op == FS_RENAME:
                n = struct.unpack_from("<H", data)[0]
                a = self.real(data[2:2 + n].decode("utf-8", "replace"))
                b = self.real(data[2 + n:].decode("utf-8", "replace"))
                if self.root in (a, b):
                    return errno.EACCES, b""
                if b.exists():
                    return errno.EEXIST, b""
                a.rename(b)
                print(f"[PC] SD: renombrado {self.show(a)} -> {self.show(b)}", flush=True)
                return 0, b""
            return errno.ENOSYS, b""
        except FileNotFoundError:
            return errno.ENOENT, b""
        except FileExistsError:
            return errno.EEXIST, b""
        except IsADirectoryError:
            return errno.EISDIR, b""
        except NotADirectoryError:
            return errno.ENOTDIR, b""
        except PermissionError:
            return errno.EACCES, b""
        except OSError as e:
            return (e.errno or errno.EIO) & 0xFF, b""
        except (struct.error, ValueError):
            return errno.EINVAL, b""


# =============================================================================
#  Enlace serie (hilo propio): tramas, archivos, latido y reconexión
# =============================================================================
class Link(threading.Thread):
    def __init__(self, port, baud, sd, reset=True):
        super().__init__(daemon=True)
        self.port_arg, self.baud, self.sd, self.reset = port, baud, sd, reset
        self.ser = None
        self.port = None
        self.wlock = threading.Lock()
        self.draw = queue.Queue()            # tramas de dibujo/sonido -> hilo de pygame
        self.status = "buscando el ESP32…"
        self.connected = False               # el ESP32 respondió al saludo
        self.fw = ""
        self.state = {}
        self.stats = {"rx": 0, "frames": 0, "bad": 0}
        self.stop = False
        self.want_reset = False
        self._log = bytearray()
        self.last_rx = 0.0

    # ---- utilidades ----------------------------------------------------------
    def send(self, t, payload=b""):
        ser = self.ser
        if not ser:
            return
        try:
            with self.wlock:
                ser.write(frame(t, payload))
        except Exception:
            pass

    def key(self, key_id, down):
        self.send(PC_KEY, bytes((key_id, 1 if down else 0)))

    def log_bytes(self, b):
        self._log += b
        while b"\n" in self._log:
            line, _, rest = self._log.partition(b"\n")
            self._log = bytearray(rest)
            txt = line.decode("utf-8", "replace").rstrip("\r")
            if txt.strip():
                print(f"[ESP32] {txt}", flush=True)
        if len(self._log) > 2000:
            self._log.clear()

    def pick_port(self):
        if self.port_arg:
            return self.port_arg
        ports = list(serial.tools.list_ports.comports())
        known = [p for p in ports if p.vid in USB_VIDS]
        cand = known or [p for p in ports if "bluetooth" not in (p.description or "").lower()]
        return cand[0].device if cand else None

    def open(self):
        port = self.pick_port()
        if not port:
            self.status = "no hay ningún puerto serie (¿cable USB?)"
            return False
        self.status = f"abriendo {port}…"
        if "://" in port:
            ser = serial.serial_for_url(port, baudrate=self.baud, timeout=0.02)
        else:
            ser = serial.Serial()
            ser.port, ser.baudrate, ser.timeout = port, self.baud, 0.02
            ser.dtr = False                     # no tocar GPIO0 (modo de arranque)
            ser.rts = False
            ser.open()
        self.ser, self.port = ser, port
        if self.reset and "://" not in port:
            self.reset_esp()
        return True

    def reset_esp(self):
        """Reinicia el ESP32 como esptool (RTS -> EN), así se ve el arranque."""
        ser = self.ser
        if not ser or "://" in (self.port or ""):
            return
        try:
            ser.dtr = False
            ser.rts = True
            time.sleep(0.12)
            ser.rts = False
        except Exception:
            pass
        self.connected = False

    # ---- bucle -------------------------------------------------------------------
    def run(self):
        while not self.stop:
            try:
                if not self.open():
                    time.sleep(1)
                    continue
                self.serve()
            except Exception as e:
                self.status = f"error: {e}"
            self.connected = False
            if self.ser:
                try:
                    self.ser.close()
                except Exception:
                    pass
            self.ser = None
            self.draw.put((None, b""))           # aviso: pantalla desconectada
            time.sleep(1)

    def serve(self):
        buf = bytearray()
        next_hello = 0.0
        next_ping = 0.0
        self.last_rx = time.time()
        self.status = f"{self.port} · esperando al ESP32…"
        while not self.stop:
            now = time.time()
            if self.want_reset:
                self.want_reset = False
                self.reset_esp()
            if not self.connected and now >= next_hello:
                self.send(PC_HELLO, bytes((PROTO_VERSION,)))
                next_hello = now + 0.5
            if now >= next_ping:
                self.send(PC_PING)
                next_ping = now + 1.0
            # ESP32 mudo: quizá se reinició -> volver a saludar
            if self.connected and now - self.last_rx > 3.0:
                self.connected = False
                self.status = f"{self.port} · el ESP32 no responde…"
            data = self.ser.read(max(1, self.ser.in_waiting or 1))
            if not data:
                continue
            self.stats["rx"] += len(data)
            buf += data
            self.parse(buf)

    def parse(self, buf):
        while True:
            i = buf.find(SYNC)
            if i < 0:
                keep = 1 if buf[-1:] == b"\xA5" else 0
                if len(buf) > keep:
                    self.log_bytes(bytes(buf[:len(buf) - keep]))
                    del buf[:len(buf) - keep]
                return
            if i > 0:
                self.log_bytes(bytes(buf[:i]))
                del buf[:i]
            if len(buf) < 5:
                return
            t, n = buf[2], buf[3] | (buf[4] << 8)
            if n > MAX_PAYLOAD:
                self.log_bytes(bytes(buf[:1]))
                del buf[:1]
                continue
            if len(buf) < 6 + n:
                return
            payload = bytes(buf[5:5 + n])
            if (sum(buf[2:5 + n]) & 0xFF) != buf[5 + n]:
                self.stats["bad"] += 1
                self.log_bytes(bytes(buf[:1]))
                del buf[:1]
                continue
            del buf[:6 + n]
            self.stats["frames"] += 1
            self.last_rx = time.time()
            self.handle(t, payload)

    def handle(self, t, p):
        if t in DRAW_TYPES or t == TONE:
            self.draw.put((t, p))
        elif t == FS_REQ and len(p) >= 2:
            rid, op = p[0], p[1]
            st, data = self.sd.handle(op, p[2:])
            self.send(FS_RESP, bytes((rid, st)) + data)
        elif t == HELLO:
            w, h = struct.unpack_from("<HH", p, 1) if len(p) >= 5 else (TFT_W, TFT_H)
            self.fw = p[5:].decode("utf-8", "replace")
            if not self.connected:
                print(f"[PC] Conectado: {self.fw} ({w}x{h}) en {self.port}", flush=True)
            self.connected = True
            self.status = f"{self.port} · {self.fw}"
            self.draw.put((HELLO, p))
        elif t == STATE:
            import json
            try:
                self.state = json.loads(p.decode("utf-8", "replace"))
            except ValueError:
                pass


# =============================================================================
#  Pantalla TFT virtual (320x240): ejecuta las órdenes de dibujo
# =============================================================================
class Tft:
    def __init__(self):
        self.surf = pygame.Surface((TFT_W, TFT_H))
        self.surf.fill((0, 0, 0))
        self.glyphs = {}            # id -> 5 columnas
        self.cache = {}             # (id, size, fg, bg, bold) -> Surface
        self.dirty = True

    def reset(self):
        self.glyphs.clear()
        self.cache.clear()

    def glyph_surface(self, gid, size, fg, bg, bold):
        key = (gid, size, fg, bg, bold)
        s = self.cache.get(key)
        if s is not None:
            return s
        s = pygame.Surface((6 * size, 8 * size))
        s.fill(rgb565(bg))
        col = rgb565(fg)
        cols = self.glyphs.get(gid, (0x7F, 0x41, 0x41, 0x41, 0x7F))   # cuadro si falta
        for cx, bits in enumerate(cols):
            for ry in range(8):
                if bits >> ry & 1:
                    s.fill(col, (cx * size, ry * size, size * (2 if bold else 1), size))
        if len(self.cache) > 6000:
            self.cache.clear()
        self.cache[key] = s
        return s

    def apply(self, t, p):
        s = self.surf
        self.dirty = True
        if t == FILL:
            x, y, w, h, c = struct.unpack_from("<hhhhH", p)
            s.fill(rgb565(c), (x, y, w, h))
        elif t == RECT:
            x, y, w, h, c = struct.unpack_from("<hhhhH", p)
            pygame.draw.rect(s, rgb565(c), (x, y, w, h), 1)
        elif t in (FILL_RR, RECT_RR):
            x, y, w, h, r, c = struct.unpack_from("<hhhhhH", p)
            r = max(0, min(r, min(w, h) // 2))
            pygame.draw.rect(s, rgb565(c), (x, y, w, h), 0 if t == FILL_RR else 1, border_radius=r)
        elif t == TRI:
            x0, y0, x1, y1, x2, y2, c = struct.unpack_from("<hhhhhhH", p)
            pygame.draw.polygon(s, rgb565(c), [(x0, y0), (x1, y1), (x2, y2)])
        elif t == PIXELS:
            x, y, w, h = struct.unpack_from("<hhhh", p)
            px = array.array("H")
            px.frombytes(p[8:8 + w * h * 2])
            if sys.byteorder == "big":
                px.byteswap()
            T = RGB_TABLE
            img = pygame.image.frombuffer(b"".join([T[v] for v in px]), (w, h), "RGB")
            s.blit(img, (x, y))
        elif t == PIXELS_RLE:
            x, y, w, h = struct.unpack_from("<hhhh", p)
            T = RGB_TABLE
            parts = []
            for i in range(8, len(p) - 2, 3):
                parts.append(T[p[i + 1] | (p[i + 2] << 8)] * p[i])
            raw = b"".join(parts)
            if len(raw) == w * h * 3:
                s.blit(pygame.image.frombuffer(raw, (w, h), "RGB"), (x, y))
        elif t == GLYPH:
            gid = p[0] | (p[1] << 8)
            self.glyphs[gid] = tuple(p[2:7])
            self.cache = {k: v for k, v in self.cache.items() if k[0] != gid}
        elif t == TEXT:
            x, y, size, fg, bg, bold, n = struct.unpack_from("<hhBHHBB", p)
            ids = struct.unpack_from(f"<{n}H", p, 11)
            cw = 6 * size
            for gid in ids:
                s.blit(self.glyph_surface(gid, size, fg, bg, bool(bold)), (x, y))
                x += cw


# =============================================================================
#  Sonido: cola de tonos (onda cuadrada)
# =============================================================================
class Sound:
    def __init__(self):
        self.ok = False
        self.on = True
        self.q = deque()
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
            self.rate, _, self.ch = pygame.mixer.get_init()
            self.chan = pygame.mixer.Channel(0)
            self.ok = True
        except Exception as e:
            print(f"[PC] Sin sonido: {e}")
        self.cache = {}

    def tone(self, hz, ms):
        if not self.ok:
            return
        if ms == 0:                          # parar
            self.q.clear()
            self.chan.stop()
            return
        if not self.on or len(self.q) > 40:
            return
        key = (hz, ms)
        snd = self.cache.get(key)
        if snd is None:
            n = max(1, int(self.rate * ms / 1000))
            a = array.array("h", bytes(2 * n * self.ch))
            if hz > 0:
                period = self.rate / hz
                amp = 2600
                fade = min(n, int(self.rate * 0.003))
                for i in range(n):
                    v = amp if (i % period) < period / 2 else -amp
                    if i > n - fade:
                        v = int(v * (n - i) / fade)
                    for c in range(self.ch):
                        a[i * self.ch + c] = v
            snd = pygame.mixer.Sound(buffer=a.tobytes())
            if len(self.cache) > 64:
                self.cache.clear()
            self.cache[key] = snd
        self.q.append(snd)

    def pump(self):
        if not self.ok:
            return
        if not self.chan.get_busy() and self.q:
            self.chan.play(self.q.popleft())
        if self.q and self.chan.get_queue() is None:
            self.chan.queue(self.q.popleft())


# =============================================================================
#  Carcasa y teclas (mismo aspecto que simulador/scicalc_sim.py)
# =============================================================================
BASE_W, BASE_H = 720, 1372
SCR_X, SCR_Y, SCR_W, SCR_H = 40, 96, 640, 480
ACCENT = (40, 168, 250)
SHIFT_C = (255, 200, 40)
OK_C = (70, 205, 120)
ERR_C = (255, 90, 90)
TEXT_C = (238, 241, 245)
MUTED_C = (135, 142, 158)

_fonts = {}


def font(size, bold=False):
    k = (size, bold)
    if k not in _fonts:
        _fonts[k] = pygame.font.SysFont("segoeui,helveticaneue,helvetica,dejavusans,arial", size, bold=bold)
    return _fonts[k]


def draw_text(surf, s, f, color, pos, align="left", width=0):
    img = f.render(s, True, color)
    x, y = pos
    if align == "center":
        x += (width - img.get_width()) // 2
    elif align == "right":
        x += width - img.get_width()
    surf.blit(img, (x, y))
    return img.get_width()


KEY_DEFS = {
    "SHIFT": ("SHIFT", "", "shift"), "MENU": ("MENU", "", "menu"),
    "DEL": ("DEL", "", "red"), "AC": ("AC", "DRG", "red"),
    "UP": ("▲", "", "nav"), "DOWN": ("▼", "", "nav"),
    "LEFT": ("◄", "", "nav"), "RIGHT": ("►", "", "nav"),
    "SIN": ("sin", "asin", "func"), "COS": ("cos", "acos", "func"),
    "TAN": ("tan", "atan", "func"), "POW": ("xʸ", "x²", "func"),
    "LN": ("ln", "log", "func"), "SQRT": ("√", "π", "func"),
    "LP": ("(", "e", "func"), "RP": (")", "Ans", "func"),
    "7": ("7", "", "num"), "8": ("8", "", "num"), "9": ("9", "", "num"), "DIV": ("÷", "x!", "op"),
    "4": ("4", "", "num"), "5": ("5", "", "num"), "6": ("6", "", "num"), "MUL": ("×", "", "op"),
    "1": ("1", "", "num"), "2": ("2", "", "num"), "3": ("3", "", "num"), "SUB": ("−", "", "op"),
    "0": ("0", "", "num"), ".": (".", "EXP", "num"), "EXE": ("EXE", "", "exe"), "ADD": ("+", "", "op"),
}
# Orden = enum Key del firmware (Keyboard.h): id = posición + 1
KEY_ORDER = ["SHIFT", "MENU", "UP", "DOWN", "LEFT", "RIGHT", "DEL", "AC",
             "SIN", "COS", "TAN", "POW", "LN", "SQRT", "LP", "RP",
             "7", "8", "9", "DIV", "4", "5", "6", "MUL",
             "1", "2", "3", "SUB", "0", ".", "EXE", "ADD"]
KEY_ID = {k: i + 1 for i, k in enumerate(KEY_ORDER)}
KEY_STYLE = {
    "num": ((232, 229, 222), (30, 30, 34)), "func": ((58, 63, 73), (242, 242, 245)),
    "op": ((88, 95, 108), (255, 255, 255)), "shift": ((242, 178, 52), (35, 28, 10)),
    "menu": ((52, 120, 214), (255, 255, 255)), "red": ((222, 92, 62), (255, 255, 255)),
    "exe": ((40, 156, 104), (255, 255, 255)), "nav": ((58, 63, 73), (242, 242, 245)),
}
DPAD_C, DPAD_R, DPAD_R_IN = (360, 696), 80, 28

PC_KEYS = {
    pygame.K_RETURN: ("EXE", None), pygame.K_KP_ENTER: ("EXE", None),
    pygame.K_BACKSPACE: ("DEL", None), pygame.K_ESCAPE: ("AC", None),
    pygame.K_TAB: ("SHIFT", None), pygame.K_HOME: ("MENU", None),
    pygame.K_UP: ("UP", None), pygame.K_DOWN: ("DOWN", None),
    pygame.K_LEFT: ("LEFT", None), pygame.K_RIGHT: ("RIGHT", None),
}
PC_CHARS = {
    "+": ("ADD", None), "-": ("SUB", None), "*": ("MUL", None), "x": ("MUL", None),
    "/": ("DIV", None), "^": ("POW", None), "(": ("LP", None), ")": ("RP", None),
    ".": (".", None), ",": (".", None), "s": ("SIN", None), "c": ("COS", None),
    "t": ("TAN", None), "l": ("LN", None), "r": ("SQRT", None), "m": ("MENU", None),
    "p": ("SQRT", True), "e": ("LP", True), "a": ("RP", True), "!": ("DIV", True),
    "d": ("AC", True),
}


def build_layout():
    rects = {
        "SHIFT": pygame.Rect(50, 630, 130, 56), "MENU": pygame.Rect(50, 708, 130, 56),
        "DEL": pygame.Rect(540, 630, 130, 56), "AC": pygame.Rect(540, 708, 130, 56),
    }
    xs = [50, 210, 370, 530]
    for row, y in ((["SIN", "COS", "TAN", "POW"], 815), (["LN", "SQRT", "LP", "RP"], 900)):
        for k, x in zip(row, xs):
            rects[k] = pygame.Rect(x, y, 140, 56)
    num_rows = [["7", "8", "9", "DIV"], ["4", "5", "6", "MUL"],
                ["1", "2", "3", "SUB"], ["0", ".", "EXE", "ADD"]]
    for r, row in enumerate(num_rows):
        for k, x in zip(row, xs):
            rects[k] = pygame.Rect(x, 990 + r * 86, 140, 66)
    return rects


class Case:
    """Dibuja la calculadora y traduce clics a teclas."""

    def __init__(self):
        self.rects = build_layout()
        self.held = set()           # teclas pulsadas ahora (ratón o teclado)
        self.hover = None
        self.body = self._render_body()

    def _render_body(self):
        surf = pygame.Surface((BASE_W, BASE_H), pygame.SRCALPHA)
        body = pygame.Rect(10, 10, BASE_W - 20, BASE_H - 20)
        sh = pygame.Surface((BASE_W, BASE_H), pygame.SRCALPHA)
        pygame.draw.rect(sh, (0, 0, 0, 90), body.move(0, 6), border_radius=56)
        surf.blit(sh, (0, 0))
        grad = pygame.Surface(body.size, pygame.SRCALPHA)
        top, bot = (52, 57, 66), (28, 31, 37)
        for y in range(body.h):
            k = y / body.h
            pygame.draw.line(grad, [int(top[i] + (bot[i] - top[i]) * k) for i in range(3)], (0, y), (body.w, y))
        mask = pygame.Surface(body.size, pygame.SRCALPHA)
        pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=56)
        grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        surf.blit(grad, body.topleft)
        pygame.draw.rect(surf, (85, 92, 104), body, 2, border_radius=56)
        pygame.draw.rect(surf, (20, 22, 26), body.inflate(-14, -14), 1, border_radius=50)
        draw_text(surf, "ESP32", font(28, True), (240, 242, 246), (48, 36))
        draw_text(surf, "SciCalc", font(28), ACCENT, (140, 36))
        draw_text(surf, "modo PC · el ESP32 hace todo", font(15), (150, 158, 172), (0, 46), "right", BASE_W - 90)
        bez = pygame.Rect(SCR_X - 14, SCR_Y - 14, SCR_W + 28, SCR_H + 28)
        pygame.draw.rect(surf, (6, 7, 9), bez, border_radius=20)
        pygame.draw.rect(surf, (70, 76, 88), bez, 2, border_radius=20)
        pygame.draw.line(surf, (24, 26, 31), (40, 790), (BASE_W - 40, 790), 2)
        pygame.draw.line(surf, (24, 26, 31), (40, 972), (BASE_W - 40, 972), 2)
        draw_text(surf, "Enter=EXE · Retroceso=DEL · Esc=AC · Tab=SHIFT · M=MENU · F2 sonido · "
                  "F5/F6 batería · F9 reiniciar · F12 captura", font(13), (110, 118, 132), (0, 1326),
                  "center", BASE_W)
        return surf

    def key_at(self, pos):
        x, y = pos
        dx, dy = x - DPAD_C[0], y - DPAD_C[1]
        if DPAD_R_IN < math.hypot(dx, dy) <= DPAD_R:
            if abs(dx) > abs(dy):
                return "RIGHT" if dx > 0 else "LEFT"
            return "DOWN" if dy > 0 else "UP"
        for k, r in self.rects.items():
            if r.collidepoint(pos):
                return k
        return None

    def draw_key(self, surf, k):
        r = self.rects[k]
        label, shl, style = KEY_DEFS[k]
        face, fg = KEY_STYLE[style]
        down = k in self.held
        if self.hover == k and not down:
            face = tuple(min(255, c + 14) for c in face)
        dy = 4 if down else 0
        shadow = tuple(max(0, int(c * 0.55)) for c in face)
        pygame.draw.rect(surf, (12, 13, 16), r.move(0, 7), border_radius=12)
        pygame.draw.rect(surf, shadow, r.move(0, 4), border_radius=12)
        fr = r.move(0, dy)
        pygame.draw.rect(surf, face, fr, border_radius=12)
        hl = tuple(min(255, c + 30) for c in face)
        pygame.draw.line(surf, hl, (fr.x + 10, fr.y + 2), (fr.right - 10, fr.y + 2), 2)
        big = style == "num" or k in ("ADD", "SUB", "MUL", "DIV")
        f = font(34 if big else 24, True)
        if label == "xʸ":
            w1 = f.size("x")[0]
            fs = font(16, True)
            x0 = fr.x + (fr.w - w1 - fs.size("y")[0]) // 2
            draw_text(surf, "x", f, fg, (x0, fr.y + (fr.h - f.get_height()) // 2))
            draw_text(surf, "y", fs, fg, (x0 + w1, fr.y + 8))
        else:
            draw_text(surf, label, f, fg, (fr.x, fr.y + (fr.h - f.get_height()) // 2), "center", fr.w)
        if shl:
            draw_text(surf, shl, font(15, True), SHIFT_C, (r.x, r.y - 21), "center", r.w)

    def draw_dpad(self, surf):
        cx, cy = DPAD_C
        pygame.draw.circle(surf, (12, 13, 16), (cx, cy + 7), DPAD_R)
        pygame.draw.circle(surf, (30, 33, 39), (cx, cy + 4), DPAD_R)
        pygame.draw.circle(surf, (58, 63, 73), (cx, cy), DPAD_R)
        pygame.draw.circle(surf, (80, 86, 98), (cx, cy), DPAD_R, 2)
        for k, (ux, uy) in {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}.items():
            if k in self.held or self.hover == k:
                col = ACCENT if k in self.held else (78, 84, 96)
                ang = math.atan2(uy, ux)
                pts = [(cx + math.cos(ang + a) * rr, cy + math.sin(ang + a) * rr)
                       for rr, a in ((DPAD_R_IN, -0.78), (DPAD_R - 3, -0.78), (DPAD_R - 3, -0.4),
                                     (DPAD_R - 3, 0), (DPAD_R - 3, 0.4), (DPAD_R - 3, 0.78),
                                     (DPAD_R_IN, 0.78))]
                pygame.draw.polygon(surf, col, pts)
            px, py = cx + ux * 52, cy + uy * 52
            tri = [(px + ux * 12, py + uy * 12), (px - ux * 6 + uy * 12, py - uy * 6 + ux * 12),
                   (px - ux * 6 - uy * 12, py - uy * 6 - ux * 12)]
            pygame.draw.polygon(surf, (235, 238, 242), tri)
        for a in (0.785, 2.356, 3.927, 5.498):
            pygame.draw.line(surf, (40, 44, 51), (cx + math.cos(a) * DPAD_R_IN, cy + math.sin(a) * DPAD_R_IN),
                             (cx + math.cos(a) * DPAD_R, cy + math.sin(a) * DPAD_R), 2)
        pygame.draw.circle(surf, (40, 44, 51), (cx, cy), DPAD_R_IN)
        pygame.draw.circle(surf, (90, 96, 108), (cx, cy), DPAD_R_IN, 2)

    def render(self, tft_surf, link, sound, battery):
        base = pygame.Surface((BASE_W, BASE_H), pygame.SRCALPHA)
        base.blit(self.body, (0, 0))
        # pantalla: píxeles nítidos a x2
        base.blit(pygame.transform.scale(tft_surf, (SCR_W, SCR_H)), (SCR_X, SCR_Y))
        if not link.connected:
            veil = pygame.Surface((SCR_W, SCR_H), pygame.SRCALPHA)
            veil.fill((0, 0, 0, 170))
            base.blit(veil, (SCR_X, SCR_Y))
            draw_text(base, "Esperando al ESP32", font(30, True), TEXT_C, (SCR_X, SCR_Y + 180), "center", SCR_W)
            draw_text(base, link.status, font(18), MUTED_C, (SCR_X, SCR_Y + 228), "center", SCR_W)
            draw_text(base, "¿Firmware con SCICALC_REMOTE 1? ¿Monitor serie del IDE cerrado?",
                      font(15), MUTED_C, (SCR_X, SCR_Y + 262), "center", SCR_W)
        # LED: verde conectado, rojo no
        pygame.draw.circle(base, OK_C if link.connected else ERR_C, (BASE_W - 60, 56), 5)
        # línea de estado bajo la pantalla
        st = link.state
        bits = [link.port or "sin puerto"]
        if link.connected and st:
            bits.append(f"heap {st.get('heap', 0) // 1024} KB")
            bits.append(f"encendido {st.get('up', 0)} s")
        bits.append(f"batería {battery[0]}%{'+' if battery[1] else ''}")
        bits.append("sonido" if sound.on else "SILENCIO")
        draw_text(base, "  ·  ".join(bits), font(14), (120, 128, 142), (0, 598), "center", BASE_W)
        for k in self.rects:
            self.draw_key(base, k)
        self.draw_dpad(base)
        return base


# =============================================================================
#  Programa principal
# =============================================================================
def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description="Pantalla, teclado, SD y sonido del ESP32 SciCalc en el PC")
    ap.add_argument("--puerto", help="COM5, /dev/ttyUSB0... (por defecto, el primero que parezca un ESP32)")
    ap.add_argument("--baudios", type=int, default=921600, help="igual que REMOTE_BAUD en config.h")
    ap.add_argument("--sd", default=str(here.parent / "simulador" / "sd"), help="carpeta que hace de MicroSD")
    ap.add_argument("--sin-reset", action="store_true", help="no reiniciar el ESP32 al conectar")
    ap.add_argument("--lista", action="store_true", help="muestra los puertos serie y sale")
    args = ap.parse_args()

    if args.lista:
        for p in serial.tools.list_ports.comports():
            chip = USB_VIDS.get(p.vid, "")
            print(f"{p.device:16} {p.description} {('[' + chip + ']') if chip else ''}")
        return

    sd = SdFolder(args.sd)
    if not sd.root.is_dir():
        print(f"[PC] Aviso: la carpeta SD no existe: {sd.root}")
    print(f"[PC] MicroSD = {sd.root}")

    pygame.init()
    build_rgb_table()
    pygame.display.set_caption("ESP32 SciCalc — pantalla en el PC")
    info = pygame.display.Info()
    scale = min(1.0, (info.current_h - 100) / BASE_H, (info.current_w - 40) / BASE_W)
    win = pygame.display.set_mode((int(BASE_W * scale), int(BASE_H * scale)), pygame.RESIZABLE)

    tft = Tft()
    case = Case()
    sound = Sound()
    link = Link(args.puerto, args.baudios, sd, reset=not args.sin_reset)
    link.start()
    battery = [100, False]

    def send_battery():
        link.send(PC_SET, struct.pack("<bB", battery[0], 1 if battery[1] else 0))

    def to_base(pos):
        w, h = win.get_size()
        sc = min(w / BASE_W, h / BASE_H)
        ox, oy = (w - BASE_W * sc) / 2, (h - BASE_H * sc) / 2
        return ((pos[0] - ox) / sc, (pos[1] - oy) / sc)

    def press(k, down):
        if k not in KEY_ID:
            return
        if down:
            case.held.add(k)
        else:
            case.held.discard(k)
        link.key(KEY_ID[k], down)

    clock = pygame.time.Clock()
    mouse_key = None
    pc_held = {}                     # tecla del PC -> tecla de la calculadora
    was_connected = False
    running = True
    while running:
        clock.tick(60)
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.VIDEORESIZE:
                win = pygame.display.set_mode(ev.size, pygame.RESIZABLE)
            elif ev.type == pygame.MOUSEMOTION:
                case.hover = case.key_at(to_base(ev.pos))
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                mouse_key = case.key_at(to_base(ev.pos))
                if mouse_key:
                    press(mouse_key, True)
            elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                if mouse_key:
                    press(mouse_key, False)
                mouse_key = None
            elif ev.type == pygame.KEYUP:
                k = pc_held.pop(ev.key, None)
                if k:
                    press(k, False)
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_F2:
                    sound.on = not sound.on
                    continue
                if ev.key in (pygame.K_F5, pygame.K_F6):
                    battery[0] = max(0, min(100, battery[0] + (5 if ev.key == pygame.K_F6 else -5)))
                    send_battery()
                    continue
                if ev.key == pygame.K_F7:
                    battery[1] = not battery[1]
                    send_battery()
                    continue
                if ev.key == pygame.K_F9:
                    link.want_reset = True
                    continue
                if ev.key == pygame.K_F12:
                    name = f"captura_{datetime.now():%Y%m%d_%H%M%S}.png"
                    pygame.image.save(tft.surf, name)
                    print(f"[PC] Captura guardada: {name}")
                    continue
                hit = PC_KEYS.get(ev.key)
                if not hit and ev.unicode:
                    ch = ev.unicode.lower() if ev.unicode != "!" else ev.unicode
                    hit = (ch, None) if ch.isdigit() else PC_CHARS.get(ch)
                if hit and ev.key not in pc_held:
                    k, sh = hit
                    if sh:                      # atajo con SHIFT: SHIFT y luego la tecla
                        press("SHIFT", True)
                        press("SHIFT", False)
                    pc_held[ev.key] = k
                    press(k, True)

        if link.connected and not was_connected:
            send_battery()
        was_connected = link.connected

        # Órdenes del ESP32 (como mucho ~40 ms de trabajo por fotograma)
        t0 = time.time()
        while time.time() - t0 < 0.04:
            try:
                t, p = link.draw.get_nowait()
            except queue.Empty:
                break
            if t is None:
                continue
            if t == HELLO:
                tft.reset()                  # el ESP32 reenviará glifos y lo repinta todo
            elif t == TONE:
                hz, ms = struct.unpack_from("<HH", p)
                sound.tone(hz, ms)
            else:
                try:
                    tft.apply(t, p)
                except (struct.error, ValueError) as e:
                    print(f"[PC] Trama 0x{t:02X} mal formada: {e}")
        sound.pump()

        frame_img = case.render(tft.surf, link, sound, battery)
        w, h = win.get_size()
        sc = min(w / BASE_W, h / BASE_H)
        img = pygame.transform.smoothscale(frame_img, (int(BASE_W * sc), int(BASE_H * sc)))
        win.fill((18, 20, 24))
        win.blit(img, ((w - img.get_width()) // 2, (h - img.get_height()) // 2))
        pygame.display.flip()

    link.stop = True
    pygame.quit()


if __name__ == "__main__":
    main()
