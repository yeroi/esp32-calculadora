#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 ESP32 SciCalc — Simulador de escritorio del producto final
===============================================================================
 Reproduce en tu PC cómo se verá y se comportará la calculadora terminada:

   * Carcasa, pantalla TFT 320x240 y las 32 teclas (clic con el ratón o
     usando el teclado del PC).
   * Menú principal con cambio de modo instantáneo (teclas 1-4).
   * Calculadora científica: sin/cos/tan (+ inversas), ln/log, raíces,
     potencias, factorial, π, e, Ans, modo DEG/RAD, multiplicación implícita.
   * Sandbox de Python: ejecuta los .py de la carpeta "sd/" con
       - SD de SOLO LECTURA (open en escritura bloqueado),
       - módulos peligrosos bloqueados (os, sys, shutil, subprocess...),
       - WATCHDOG: si el script tarda más de 5 s se detiene y se vuelve
         al menú sin colgar la calculadora.
   * Explorador de la SD con visor de código y diagnóstico de teclado.

 Requisitos:   pip install pygame-ce   (funciona en Python 3.14)
 Ejecutar:     python scicalc_sim.py

 Teclado del PC:
   0-9 . + - * / ^ ( )    →  teclas equivalentes
   Enter = EXE   Retroceso = DEL   Esc = AC   Tab = SHIFT   M / Inicio = MENU
   Flechas = cursor     s c t = sin cos tan    l = ln    r = √
   p = π   e = e   a = Ans   ! = factorial   d = DEG/RAD
===============================================================================
"""
import json
import math
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

try:
    import pygame
except ImportError:
    print("Falta pygame. Instálalo con:  pip install pygame-ce")
    sys.exit(1)

# =============================================================================
#  Constantes
# =============================================================================
BASE_W, BASE_H = 720, 1372               # tamaño "real" del dibujo de la calculadora
SCR_X, SCR_Y, SCR_W, SCR_H = 40, 96, 640, 480   # pantalla (= TFT 320x240 a 2x)
HEADER_H = 44
SD_DIR = Path(__file__).resolve().parent / "sd"
WATCHDOG_S = 5.0
MAX_OUTPUT_LINES = 2000

# Paleta de la interfaz (la misma que el firmware)
BG = (10, 12, 18)
PANEL = (30, 34, 44)
TEXT = (238, 241, 245)
MUTED = (135, 142, 158)
ACCENT = (40, 168, 250)
OK = (70, 205, 120)
WARN = (255, 170, 40)
ERR = (255, 90, 90)
SHIFT_C = (255, 200, 40)

# =============================================================================
#  Fuentes
# =============================================================================
_font_cache = {}
MONO = "dejavusansmono,consolas,menlo,monaco,couriernew"
SANS = "segoeui,helveticaneue,helvetica,dejavusans,arial"


def font(size, bold=False, mono=True):
    key = (size, bold, mono)
    if key not in _font_cache:
        _font_cache[key] = pygame.font.SysFont(MONO if mono else SANS, size, bold=bold)
    return _font_cache[key]


def draw_text(surf, s, f, color, pos, align="left", width=0):
    img = f.render(s, True, color)
    x, y = pos
    if align == "center":
        x += (width - img.get_width()) // 2
    elif align == "right":
        x += width - img.get_width()
    surf.blit(img, (x, y))
    return img.get_width()


# =============================================================================
#  Teclas
# =============================================================================
#  id, etiqueta, etiqueta SHIFT (amarilla), estilo
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
# Orden lógico (igual que el enum Key del firmware) — para el diagnóstico
KEY_ORDER = ["SHIFT", "MENU", "UP", "DOWN", "LEFT", "RIGHT", "DEL", "AC",
             "SIN", "COS", "TAN", "POW", "LN", "SQRT", "LP", "RP",
             "7", "8", "9", "DIV", "4", "5", "6", "MUL",
             "1", "2", "3", "SUB", "0", ".", "EXE", "ADD"]

KEY_STYLE = {   # cara, texto
    "num": ((232, 229, 222), (30, 30, 34)),
    "func": ((58, 63, 73), (242, 242, 245)),
    "op": ((88, 95, 108), (255, 255, 255)),
    "shift": ((242, 178, 52), (35, 28, 10)),
    "menu": ((52, 120, 214), (255, 255, 255)),
    "red": ((222, 92, 62), (255, 255, 255)),
    "exe": ((40, 156, 104), (255, 255, 255)),
    "nav": ((58, 63, 73), (242, 242, 245)),
}

DPAD_C = (360, 696)
DPAD_R = 80
DPAD_R_IN = 28


def build_layout():
    """Devuelve {id: pygame.Rect} con la posición de cada tecla rectangular."""
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


# =============================================================================
#  Motor matemático (mismo diseño que tendrá el parser C++ del Paso 4)
# =============================================================================
class CalcError(Exception):
    def __init__(self, kind):
        super().__init__(kind)
        self.kind = kind          # "Syntax" o "Math"


DIGITS = "0123456789"   # ojo: "²".isdigit() es True en Python
FUNC_NAMES = ["asin", "acos", "atan", "sin", "cos", "tan", "ln", "log", "√"]


def tokenize(s):
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c == " ":
            i += 1
            continue
        if c in DIGITS or c == ".":
            j = i
            while j < n and (s[j] in DIGITS or s[j] == "."):
                j += 1
            if j < n and s[j] == "E":
                j += 1
                if j < n and s[j] in "−-":
                    j += 1
                k = j
                while j < n and s[j] in DIGITS:
                    j += 1
                if j == k:
                    raise CalcError("Syntax")
            txt = s[i:j].replace("E", "e").replace("−", "-")
            try:
                out.append(("num", float(txt)))
            except ValueError:
                raise CalcError("Syntax")
            i = j
            continue
        hit = False
        for name in FUNC_NAMES:
            if s.startswith(name + "(", i):
                out.append(("func", name))
                out.append(("(", None))
                i += len(name) + 1
                hit = True
                break
        if hit:
            continue
        for const in ("Ans", "π", "e"):
            if s.startswith(const, i):
                out.append(("const", const))
                i += len(const)
                hit = True
                break
        if hit:
            continue
        mapping = {"-": "−", "*": "×", "/": "÷"}
        if c in "+−-×÷*/^()²!":
            out.append((mapping.get(c, c), None))
            i += 1
            continue
        raise CalcError("Syntax")
    return out


class Parser:
    """Descenso recursivo:
         expr    := term (('+'|'−') term)*
         term    := unary (('×'|'÷'|implícita) unary)*
         unary   := ('−'|'+') unary | power
         power   := postfix ('^' unary)?
         postfix := primary ('²'|'!')*
         primary := número | constante | func '(' expr ')' | '(' expr ')'
       Los paréntesis finales se pueden omitir (como en las Casio)."""

    def __init__(self, tokens, ans, degrees):
        self.t, self.p, self.ans, self.deg = tokens, 0, ans, degrees

    def peek(self):
        return self.t[self.p][0] if self.p < len(self.t) else None

    def next(self):
        tok = self.t[self.p] if self.p < len(self.t) else (None, None)
        self.p += 1
        return tok

    def parse(self):
        if not self.t:
            raise CalcError("Syntax")
        v = self.expr()
        if self.p != len(self.t):
            raise CalcError("Syntax")
        return check(v)

    def expr(self):
        v = self.term()
        while self.peek() in ("+", "−"):
            op = self.next()[0]
            r = self.term()
            v = v + r if op == "+" else v - r
        return v

    def term(self):
        v = self.unary()
        while True:
            k = self.peek()
            if k in ("×", "÷"):
                self.next()
                r = self.unary()
                if k == "÷":
                    if r == 0:
                        raise CalcError("Math")
                    v /= r
                else:
                    v *= r
            elif k in ("num", "const", "func", "("):     # multiplicación implícita: 2π, 3(4)
                v *= self.power()
            else:
                return v

    def unary(self):
        if self.peek() == "−":
            self.next()
            return -self.unary()
        if self.peek() == "+":
            self.next()
            return self.unary()
        return self.power()

    def power(self):
        b = self.postfix()
        if self.peek() == "^":
            self.next()
            e = self.unary()
            try:
                return math.pow(b, e)
            except (ValueError, OverflowError, ZeroDivisionError):
                raise CalcError("Math")
        return b

    def postfix(self):
        v = self.primary()
        while self.peek() in ("²", "!"):
            if self.next()[0] == "²":
                v = v * v
            else:
                if v < 0 or v != int(v) or v > 170:
                    raise CalcError("Math")
                v = float(math.factorial(int(v)))
        return v

    def primary(self):
        kind, val = self.next()
        if kind == "num":
            return val
        if kind == "const":
            return {"π": math.pi, "e": math.e, "Ans": self.ans}[val]
        if kind == "(":
            v = self.expr()
            self.close_paren()
            return v
        if kind == "func":
            if self.next()[0] != "(":
                raise CalcError("Syntax")
            x = self.expr()
            self.close_paren()
            return self.apply(val, x)
        raise CalcError("Syntax")

    def close_paren(self):
        if self.peek() == ")":
            self.next()
        elif self.peek() is not None:
            raise CalcError("Syntax")

    def apply(self, f, x):
        try:
            if f in ("sin", "cos", "tan"):
                a = math.radians(x) if self.deg else x
                if f == "tan" and abs(math.cos(a)) < 1e-15:
                    raise CalcError("Math")
                return round({"sin": math.sin, "cos": math.cos, "tan": math.tan}[f](a), 14)
            if f in ("asin", "acos", "atan"):
                r = {"asin": math.asin, "acos": math.acos, "atan": math.atan}[f](x)
                return math.degrees(r) if self.deg else r
            if f == "ln":
                return math.log(x)
            if f == "log":
                return math.log10(x)
            if f == "√":
                return math.sqrt(x)
        except ValueError:
            raise CalcError("Math")
        raise CalcError("Syntax")


def check(v):
    if isinstance(v, complex) or math.isnan(v) or math.isinf(v):
        raise CalcError("Math")
    return v


def fmt_number(v):
    if v == 0:
        return "0"
    if abs(v) < 1e15 and v == int(v):
        s = str(int(v))
    else:
        s = f"{v:.10g}"
        if "e" in s:
            mant, ex = s.split("e")
            s = f"{mant}E{int(ex)}"
    return s.replace("-", "−")


def evaluate(expr, ans=0.0, degrees=True):
    return Parser(tokenize(expr), ans, degrees).parse()


# =============================================================================
#  Marco de aplicaciones (igual que App / AppManager del firmware)
# =============================================================================
class App:
    title = "App"

    def __init__(self, sim):
        self.sim = sim

    def on_enter(self):
        pass

    def on_key(self, key, shift):
        pass

    def update(self, dt):
        pass

    def draw(self, s):
        pass

    def footer(self, s, txt):
        draw_text(s, txt, font(16), MUTED, (0, SCR_H - 24), "center", SCR_W)


# ----------------------------------------------------------------- Menú -----
class MenuApp(App):
    title = "Menú principal"

    def __init__(self, sim, items):
        super().__init__(sim)
        self.items = items          # (etiqueta, pista, app)
        self.sel = 0

    def on_key(self, key, shift):
        if key == "UP":
            self.sel = (self.sel - 1) % len(self.items)
        elif key == "DOWN":
            self.sel = (self.sel + 1) % len(self.items)
        elif key in ("EXE", "RIGHT"):
            self.sim.launch(self.items[self.sel][2])
        elif key.isdigit() and 1 <= int(key) <= len(self.items):
            self.sel = int(key) - 1
            self.sim.launch(self.items[self.sel][2])

    def draw(self, s):
        for i, (label, hint, _) in enumerate(self.items):
            y = HEADER_H + 10 + i * 66
            sel = i == self.sel
            bg = ACCENT if sel else PANEL
            pygame.draw.rect(s, bg, (20, y, SCR_W - 40, 58), border_radius=12)
            badge = BG if sel else ACCENT
            pygame.draw.rect(s, badge, (32, y + 10, 38, 38), border_radius=8)
            draw_text(s, str(i + 1), font(24, True), TEXT, (32, y + 14), "center", 38)
            draw_text(s, label, font(26, True), TEXT, (86, y + 13))
            draw_text(s, hint, font(16), TEXT if sel else MUTED, (20, y + 20), "right", SCR_W - 60)
        self.footer(s, f"↑↓ mover    EXE abrir    1-{len(self.items)} acceso directo")


# ---------------------------------------------------------- Calculadora -----
class CalcApp(App):
    title = "Calculadora"

    KEY_TOKENS = {
        "ADD": "+", "SUB": "−", "MUL": "×", "DIV": "÷", "POW": "^",
        "LP": "(", "RP": ")", "SIN": "sin(", "COS": "cos(", "TAN": "tan(",
        "LN": "ln(", "SQRT": "√(", ".": ".",
    }
    SHIFT_TOKENS = {
        "SIN": "asin(", "COS": "acos(", "TAN": "atan(", "POW": "²", "LN": "log(",
        "SQRT": "π", "LP": "e", "RP": "Ans", "DIV": "!", ".": "E",
    }
    OPS = {"+", "−", "×", "÷", "^", "²", "!"}

    def __init__(self, sim):
        super().__init__(sim)
        self.tokens, self.cur = [], 0
        self.history = []            # (lista de tokens, texto resultado, es_error)
        self.ans = 0.0
        self.recall = -1
        self.blink = 0.0

    def insert(self, tok):
        if not self.tokens and tok in self.OPS and self.history:
            self.tokens, self.cur = ["Ans"], 1          # 5 EXE  + 3  →  Ans+3
        self.tokens.insert(self.cur, tok)
        self.cur += 1
        self.blink = 0
        self.recall = -1

    def run(self):
        if not self.tokens:
            if not self.history:
                return
            self.tokens = list(self.history[-1][0])
        expr = "".join(self.tokens)
        try:
            v = evaluate(expr, self.ans, self.sim.degrees)
            self.ans = v
            self.history.append((list(self.tokens), fmt_number(v), False))
        except CalcError as e:
            self.history.append((list(self.tokens), f"{e.kind} ERROR", True))
        self.history = self.history[-30:]
        self.tokens, self.cur, self.recall = [], 0, -1

    def on_key(self, key, shift):
        if key.isdigit():
            self.insert(key)
        elif shift and key == "AC":
            self.sim.degrees = not self.sim.degrees
        elif shift and key in self.SHIFT_TOKENS:
            self.insert(self.SHIFT_TOKENS[key])
        elif key in self.KEY_TOKENS:
            self.insert(self.KEY_TOKENS[key])
        elif key == "EXE":
            self.run()
        elif key == "DEL":
            if self.cur > 0:
                self.cur -= 1
                del self.tokens[self.cur]
        elif key == "AC":
            if self.tokens:
                self.tokens, self.cur = [], 0
            else:
                self.history.clear()
        elif key == "LEFT":
            self.cur = max(0, self.cur - 1)
        elif key == "RIGHT":
            self.cur = min(len(self.tokens), self.cur + 1)
        elif key == "UP" and self.history:
            self.recall = len(self.history) - 1 if self.recall < 0 else max(0, self.recall - 1)
            self.tokens = list(self.history[self.recall][0])
            self.cur = len(self.tokens)
        elif key == "DOWN" and self.recall >= 0:
            self.recall += 1
            if self.recall >= len(self.history):
                self.recall, self.tokens = -1, []
            else:
                self.tokens = list(self.history[self.recall][0])
            self.cur = len(self.tokens)
        self.blink = 0

    def update(self, dt):
        self.blink += dt

    def draw(self, s):
        # Estilo "pantalla de calculadora": sin recuadros.
        #   - Abajo, la operación actual (expresión arriba, resultado debajo a la derecha).
        #   - Encima, las operaciones anteriores en gris, más pequeñas.
        typing = bool(self.tokens) or self.recall >= 0 or not self.history
        past = self.history if typing else self.history[:-1]

        y = 262
        for toks, res, err in reversed(past):
            if y < HEADER_H + 4:
                break
            draw_text(s, "".join(toks), font(20), MUTED, (20, y))
            draw_text(s, res, font(24, True), (205, 90, 90) if err else (175, 182, 196),
                      (0, y + 26), "right", SCR_W - 20)
            y -= 66

        pygame.draw.line(s, PANEL, (20, 322), (SCR_W - 20, 322), 1)
        f = font(34)
        clip = s.get_clip()
        s.set_clip(pygame.Rect(16, 330, SCR_W - 32, 52))
        if typing:
            before = "".join(self.tokens[:self.cur])
            full = "".join(self.tokens)
            cx = f.size(before)[0]
            off = max(0, cx - (SCR_W - 60))           # desplaza si la expresión es larga
            draw_text(s, full, f, TEXT, (22 - off, 336))
            if int(self.blink * 2) % 2 == 0:
                pygame.draw.rect(s, ACCENT, (22 - off + cx, 334, 3, 42))
        else:
            toks, res, err = self.history[-1]
            draw_text(s, "".join(toks), f, TEXT, (22, 336))
        s.set_clip(clip)

        if not typing:
            toks, res, err = self.history[-1]
            draw_text(s, res, font(46, True), ERR if err else TEXT, (0, 386), "right", SCR_W - 22)
        elif not self.history and not self.tokens:
            draw_text(s, "Escribe una operación y pulsa EXE", font(18), MUTED, (0, 150), "center", SCR_W)
            draw_text(s, "ej.  2sin(30)+√(16)     SHIFT = funciones amarillas",
                      font(15), MUTED, (0, 180), "center", SCR_W)
        self.footer(s, "SHIFT+AC: DEG/RAD   ↑ recuperar   DEL borra   AC limpia")


# ------------------------------------------------------- Sandbox Python -----
#  El script corre en un proceso aparte con:
#   * open()/os limitados a la SD; escribir, borrar, renombrar o crear carpetas
#     PIDE PERMISO al usuario (Sí / Sí a todo / No) a través del núcleo.
#   * import solo de una lista blanca + los paquetes instalados en /lib.
#   * os y sys "de mentira" con las funciones seguras (como en MicroPython).
#  Protocolo con el núcleo: el script escribe "\x02{json}" y espera "y", "a" o "n".
SANDBOX_WRAPPER = r"""
import sys, builtins, os, json, types, posixpath
try:
    sys.stdout.reconfigure(encoding="utf-8")   # -I ignora PYTHONIOENCODING
except Exception:
    pass
SD = os.path.realpath(sys.argv[1]); PATH = sys.argv[2]; CWD = sys.argv[3]; ARGS = sys.argv[4:]
LIB = os.path.join(SD, "lib")
sys.path.insert(0, LIB)
ALLOWED = ("math", "cmath", "random", "time", "gc", "array", "collections", "struct",
           "json", "re", "binascii", "hashlib", "heapq", "bisect", "itertools", "functools",
           "__future__", "abc", "string", "operator", "enum", "typing", "copy", "warnings",
           "numbers", "decimal", "fractions", "statistics", "textwrap", "datetime", "calendar",
           "base64", "keyword", "types", "dataclasses")
sys.dont_write_bytecode = True
for _m in ALLOWED:
    __import__(_m)                       # se precargan ANTES de cerrar el acceso
_real_import, _real_open, _stdin = builtins.__import__, builtins.open, sys.stdin
_granted, _all = set(), [False]

def _real(p):
    p = str(p)
    base = SD if p.startswith(("/", "\\")) else os.path.join(SD, CWD.lstrip("/"))
    q = os.path.realpath(os.path.join(base, p.lstrip("/\\")))
    if q != SD and os.path.commonpath([q, SD]) != SD:
        raise PermissionError("acceso fuera de la SD bloqueado")
    return q

def _show(q):
    rel = os.path.relpath(q, SD).replace("\\", "/")
    return "/" if rel == "." else "/" + rel

def _ask(op, q, extra=""):
    if _all[0] or (op, q) in _granted:
        return
    sys.stdout.write("\x02" + json.dumps({"op": op, "path": _show(q), "extra": extra}) + "\n")
    sys.stdout.flush()
    ans = _stdin.readline().strip()
    if ans == "a":
        _all[0] = True
    elif ans == "y":
        _granted.add((op, q))
    else:
        raise PermissionError("permiso denegado por el usuario")

def _open(file, mode="r", *a, **k):
    q = _real(file)
    if any(c in mode for c in "wax+"):
        _ask("write", q)
    return _real_open(q, mode, *a, **k)

# --- os seguro (mismas funciones que el 'os' de MicroPython) ---------------
_os = types.ModuleType("os")
_os.sep = "/"
_os.listdir = lambda p="/": sorted(os.listdir(_real(p)))
_os.stat = lambda p: os.stat(_real(p))
_os.getcwd = lambda: CWD
def _remove(p):
    q = _real(p); _ask("remove", q); os.remove(q)
def _rename(a, b):
    qa, qb = _real(a), _real(b); _ask("rename", qa, _show(qb)); os.rename(qa, qb)
def _mkdir(p):
    q = _real(p); _ask("mkdir", q); os.mkdir(q)
def _rmdir(p):
    q = _real(p); _ask("rmdir", q); os.rmdir(q)
_os.remove, _os.unlink, _os.rename, _os.mkdir, _os.rmdir = _remove, _remove, _rename, _mkdir, _rmdir
_path = types.ModuleType("os.path")
_path.exists = lambda p: os.path.exists(_real(p))
_path.isfile = lambda p: os.path.isfile(_real(p))
_path.isdir = lambda p: os.path.isdir(_real(p))
_path.getsize = lambda p: os.path.getsize(_real(p))
for _n in ("join", "basename", "dirname", "split", "splitext"):
    setattr(_path, _n, getattr(posixpath, _n))
_os.path = _path

# --- sys reducido ---------------------------------------------------------------
_sys = types.ModuleType("sys")
_sys.platform, _sys.version, _sys.maxsize = "esp32", sys.version, sys.maxsize
_sys.version_info, _sys.byteorder, _sys.stdout = sys.version_info, sys.byteorder, sys.stdout
_sys.path = ["", "/lib"]
_sys.argv = [os.path.basename(PATH)] + ARGS

def _sandboxed(g):
    if not g:
        return False
    if g.get("__name__") == "__main__":
        return True
    f = g.get("__file__") or ""
    try:
        return os.path.commonpath([os.path.realpath(f), SD]) == SD
    except Exception:
        return False

def _in_lib(root):
    return (os.path.isfile(os.path.join(LIB, root + ".py")) or
            os.path.isdir(os.path.join(LIB, root)))

def _import(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and _sandboxed(globals):
        root = name.split(".")[0]
        if root == "os":
            return _os
        if root == "sys":
            return _sys
        if root not in ALLOWED and not _in_lib(root):
            raise ImportError("módulo '%s' bloqueado por el sandbox" % name)
    return _real_import(name, globals, locals, fromlist, level)

def _blocked(n):
    def f(*a, **k):
        raise PermissionError("'%s' no está permitido en el sandbox" % n)
    return f

src = _real_open(PATH, encoding="utf-8").read()
builtins.__import__, builtins.open = _import, _open      # también para paquetes de /lib
safe = dict(vars(builtins))
for n in ("eval", "exec", "compile", "input", "breakpoint", "help", "exit", "quit"):
    safe[n] = _blocked(n)

name = os.path.basename(PATH)
try:
    exec(compile(src, name, "exec"), {"__name__": "__main__", "__file__": PATH, "__builtins__": safe})
except SystemExit:
    pass
except BaseException as ex:
    line = getattr(ex, "lineno", None) if isinstance(ex, SyntaxError) else None
    tb = ex.__traceback__
    while tb:
        if tb.tb_frame.f_code.co_filename == name:
            line = tb.tb_lineno
        tb = tb.tb_next
    sys.stdout.write("\x01%s: %s%s\n" % (type(ex).__name__, ex, " (línea %d)" % line if line else ""))
    sys.stdout.flush()
    sys.exit(1)
"""


def _limit_memory():          # solo Linux/macOS: tope de RAM para el script
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    except Exception:
        pass


PERM_TEXT = {
    "write": "quiere ESCRIBIR en el archivo",
    "remove": "quiere BORRAR el archivo",
    "rename": "quiere RENOMBRAR el archivo",
    "mkdir": "quiere CREAR la carpeta",
    "rmdir": "quiere BORRAR la carpeta",
}


class ScriptRunner:
    """Ejecuta un .py en un proceso aparte = aislado del 'núcleo' de la calculadora.
    En el ESP32 real esto será una tarea FreeRTOS con heap propio de MicroPython.
    El watchdog se PAUSA mientras la calculadora espera tu respuesta a un permiso."""

    def __init__(self, path, cwd=None, args=()):
        path = Path(path)
        if cwd is None:
            cwd = "/" + path.parent.relative_to(SD_DIR).as_posix() if path.parent != SD_DIR else "/"
        self.name = path.name
        self.lines, self.q = [], queue.Queue()
        self.state, self.t0, self.elapsed = "running", time.time(), 0.0
        self.perm_request = None          # dict pendiente de mostrar
        self.ask_since = 0.0
        kw = {}
        if os.name == "nt":
            kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            kw["preexec_fn"] = _limit_memory
        self.proc = subprocess.Popen(
            [sys.executable, "-I", "-u", "-c", SANDBOX_WRAPPER, str(SD_DIR), str(path), cwd.replace("/.", "/"),
             *map(str, args)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=str(SD_DIR), **kw)
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        for raw in self.proc.stdout:
            self.q.put(raw.decode("utf-8", "replace").rstrip("\r\n"))
        self.q.put(None)

    def poll(self):
        if self.state != "running":
            return
        self.elapsed = time.time() - self.t0
        try:
            while True:
                line = self.q.get_nowait()
                if line is None:
                    self.proc.wait()
                    self.state = "error" if self.proc.returncode else "ok"
                    return
                if line.startswith("\x02"):
                    try:
                        self.perm_request = json.loads(line[1:])
                    except ValueError:
                        self.perm_request = {"op": "write", "path": "?", "extra": ""}
                    self.state = "asking"
                    self.ask_since = time.time()
                    return
                self.lines.append(line)
                if len(self.lines) > MAX_OUTPUT_LINES:
                    self._kill("overflow")
                    return
        except queue.Empty:
            pass
        if self.elapsed > WATCHDOG_S:
            self._kill("watchdog")

    def answer(self, code):
        """code: 'y' (sí), 'a' (sí a todo) o 'n' (no)."""
        if self.state != "asking":
            return
        self.t0 += time.time() - self.ask_since          # no cuenta para el watchdog
        p = self.perm_request
        verdict = {"y": "permitido", "a": "permitido (todo)", "n": "DENEGADO"}[code]
        self.lines.append(f"\x03[permiso {verdict}: {p.get('op')} {p.get('path')}]")
        self.perm_request = None
        self.state = "running"
        try:
            self.proc.stdin.write((code + "\n").encode())
            self.proc.stdin.flush()
        except Exception:
            pass

    def _kill(self, state):
        try:
            self.proc.kill()
        except Exception:
            pass
        self.state = state

    def stop(self):
        if self.state in ("running", "asking"):
            self._kill("stopped")


def sd_name(p):
    p = Path(p)
    return "/" if p == SD_DIR else "/" + p.relative_to(SD_DIR).as_posix()


IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif"}
TXT_EXT = {".py", ".txt", ".md", ".csv", ".json", ".ini", ".cfg", ".log", ".html", ".xml", ".toml"}


def file_kind(p):
    if p.is_dir():
        return "dir"
    e = p.suffix.lower()
    if e == ".py":
        return "py"
    if e in IMG_EXT:
        return "img"
    if e in TXT_EXT:
        return "txt"
    return "bin"


def human_size(b):
    return f"{b} B" if b < 1024 else f"{(b + 512) // 1024} KB" if b < 2**20 else f"{b / 2**20:.1f} MB"


def pump_runner(sim, r):
    """Avanza un script y, si pide permiso, muestra el diálogo en la calculadora."""
    r.poll()
    if r.state == "asking" and r.perm_request and not getattr(r, "dialog_open", False):
        p = r.perm_request
        r.dialog_open = True
        lines = [f"El script {r.name}", PERM_TEXT.get(p.get("op"), p.get("op", "?")) + ":", "  " + p.get("path", "?")]
        if p.get("extra"):
            lines.append("  → " + p["extra"])
        lines += ["", "¿Lo permites?"]

        def done(ans, r=r):
            r.dialog_open = False
            r.answer(ans)
        sim.ask("PERMISO", lines, done, allow_all=True)


class Browser:
    """Explorador de carpetas de la SD: carpetas primero, '..' para subir."""
    ROWS = 7

    def __init__(self, only_py=False):
        self.only_py = only_py
        self.cwd = SD_DIR
        self.sel, self.top, self.items = 0, 0, []

    def refresh(self):
        if not self.cwd.is_dir():
            self.cwd = SD_DIR
        try:
            entries = list(self.cwd.iterdir())
        except OSError:
            entries = []
        dirs = sorted((e for e in entries if e.is_dir() and not e.name.startswith((".", "__"))),
                      key=lambda e: e.name.lower())
        files = sorted((e for e in entries if e.is_file() and not e.name.startswith(".")),
                       key=lambda e: e.name.lower())
        if self.only_py:
            files = [f for f in files if f.suffix.lower() == ".py"]
        self.items = ([None] if self.cwd != SD_DIR else []) + dirs + files      # None = ".."
        self.sel = min(self.sel, max(0, len(self.items) - 1))
        self._scroll()

    def _scroll(self):
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + self.ROWS:
            self.top = self.sel - self.ROWS + 1

    def go_up(self):
        if self.cwd != SD_DIR:
            old = self.cwd
            self.cwd = self.cwd.parent
            self.sel = 0
            self.refresh()
            if old in self.items:
                self.sel = self.items.index(old)
                self._scroll()
            return True
        return False

    def key(self, key):
        """Devuelve el archivo elegido (Path) o None."""
        n = len(self.items)
        if key == "UP" and n:
            self.sel = (self.sel - 1) % n
        elif key == "DOWN" and n:
            self.sel = (self.sel + 1) % n
        elif key in ("LEFT", "DEL"):
            self.go_up()
        elif key in ("EXE", "RIGHT") and n:
            it = self.items[self.sel]
            if it is None:
                self.go_up()
            elif it.is_dir():
                self.cwd, self.sel, self.top = it, 0, 0
                self.refresh()
            else:
                return it
        self._scroll()
        return None

    def draw(self, s, empty_msg="Carpeta vacía"):
        # Ruta actual
        pygame.draw.rect(s, (20, 23, 31), (0, HEADER_H, SCR_W, 30))
        draw_text(s, sd_name(self.cwd), font(17, True), ACCENT, (14, HEADER_H + 6))
        draw_text(s, f"{len([i for i in self.items if i is not None])} elementos", font(15), MUTED,
                  (0, HEADER_H + 8), "right", SCR_W - 14)
        if not self.items:
            draw_text(s, empty_msg, font(22), MUTED, (0, 200), "center", SCR_W)
            return
        for v in range(self.ROWS):
            i = self.top + v
            if i >= len(self.items):
                break
            it = self.items[i]
            y = HEADER_H + 36 + v * 50
            hi = i == self.sel
            pygame.draw.rect(s, ACCENT if hi else PANEL, (12, y, SCR_W - 24, 44), border_radius=8)
            kind = "up" if it is None else file_kind(it)
            draw_icon(s, kind, 24, y + 9)
            name = ".." if it is None else it.name + ("/" if it.is_dir() else "")
            draw_text(s, name[:34], font(21, True), TEXT, (66, y + 10))
            if it is not None and it.is_file():
                draw_text(s, human_size(it.stat().st_size), font(15), TEXT if hi else MUTED,
                          (12, y + 14), "right", SCR_W - 40)


def draw_icon(s, kind, x, y):
    if kind in ("dir", "up"):
        pygame.draw.rect(s, (240, 190, 60), (x, y + 4, 30, 21), border_radius=3)
        pygame.draw.rect(s, (240, 190, 60), (x, y, 13, 7), border_radius=2)
        if kind == "up":
            pygame.draw.polygon(s, BG, [(x + 15, y + 8), (x + 8, y + 17), (x + 22, y + 17)])
        return
    col, tag = {"py": ((70, 140, 230), "PY"), "img": ((60, 190, 120), "IMG"),
                "txt": ((150, 155, 170), "TXT")}.get(kind, ((120, 110, 160), "BIN"))
    pygame.draw.rect(s, col, (x + 2, y, 26, 26), border_radius=4)
    draw_text(s, tag, font(11, True), (255, 255, 255), (x + 2, y + 7), "center", 26)


# ------------------------------------------------------------- Python -------
class PythonApp(App):
    title = "Python"

    def __init__(self, sim):
        super().__init__(sim)
        self.browser = Browser(only_py=True)
        self.runner, self.scroll_off, self.script = None, 0, None

    def on_enter(self):
        self.browser.refresh()
        self.runner = None

    def on_key(self, key, shift):
        if self.runner:
            if self.runner.state in ("running", "asking"):
                if key in ("AC", "DEL"):
                    self.runner.stop()
                return
            if key in ("AC", "DEL", "LEFT"):
                self.runner = None
                self.sim.set_title(self.title)
            elif key == "EXE":
                self.start(self.script)
            elif key == "UP":
                self.scroll_off += 1
            elif key == "DOWN":
                self.scroll_off = max(0, self.scroll_off - 1)
            return
        if key == "AC":
            self.browser.go_up()
            return
        f = self.browser.key(key)
        if f:
            self.start(f)

    def start(self, path):
        if self.sim.exam:
            self.sim.ask("Modo examen", ["Python está bloqueado durante", "el modo examen.", "",
                                         "Desactívalo en Ajustes."], None, info=True)
            return
        self.script = path
        self.scroll_off = 0
        self.runner = ScriptRunner(path)
        self.sim.set_title("► " + path.name)

    def update(self, dt):
        if self.runner:
            pump_runner(self.sim, self.runner)

    def on_exit(self):
        if self.runner:
            self.runner.stop()

    def draw(self, s):
        if not self.runner:
            self.browser.draw(s, "No hay scripts .py aquí")
            self.footer(s, "↑↓ mover   EXE abrir/ejecutar   ◄ subir carpeta")
            return
        r = self.runner
        st = {
            "running": (f"Ejecutando… {r.elapsed:4.1f} s   (AC detiene)", WARN),
            "asking": ("Esperando tu permiso… (watchdog en pausa)", SHIFT_C),
            "ok": (f"OK - terminado en {r.elapsed:.2f} s", OK),
            "error": ("ERROR - el script terminó con una excepción", ERR),
            "watchdog": (f"WATCHDOG: detenido tras {WATCHDOG_S:.0f} s", ERR),
            "stopped": ("Detenido por el usuario (AC)", WARN),
            "overflow": ("ERROR - demasiada salida, script detenido", ERR),
        }[r.state]
        pygame.draw.rect(s, PANEL, (0, HEADER_H, SCR_W, 34))
        draw_text(s, st[0], font(18, True), st[1], (14, HEADER_H + 7))
        y = draw_console(s, r.lines, HEADER_H + 42, 15, self.scroll_off)
        if r.state == "running" and int(time.time() * 2) % 2 == 0:
            pygame.draw.rect(s, TEXT, (12, y + 3, 10, 16))
        if r.state not in ("running", "asking"):
            self.footer(s, "EXE repetir   ↑↓ desplazar   ◄/AC volver")


def draw_console(s, lines, y, rows, scroll_off=0, x=12, cols=58):
    f = font(18)
    end = max(0, len(lines) - scroll_off)
    for line in lines[max(0, end - rows):end]:
        col = TEXT
        if line.startswith("\x01"):
            line, col = line[1:], ERR
        elif line.startswith("\x03"):
            line, col = line[1:], SHIFT_C
        elif line.startswith("\x04"):
            line, col = line[1:], ACCENT
        elif line.startswith("\x05"):
            line, col = line[1:], MUTED
        draw_text(s, line[:cols], f, col, (x, y))
        y += 22
    return y


# ----------------------------------------------------------- Archivos SD ----
PY_KEYWORDS = {"def", "return", "for", "in", "while", "if", "elif", "else", "import", "from",
               "print", "range", "True", "False", "None", "and", "or", "not", "try", "except",
               "class", "with", "as", "break", "continue", "pass", "lambda"}


class FilesApp(App):
    """Explorador completo: carpetas, texto/código, fotos y archivos binarios."""
    title = "Archivos SD"

    def __init__(self, sim):
        super().__init__(sim)
        self.browser = Browser()
        self.view, self.file = None, None          # None | "text" | "img" | "bin"
        self.lines, self.vtop, self.img, self.raw = None, 0, None, b""

    def on_enter(self):
        self.browser.refresh()
        self.view = None

    def open(self, p):
        self.file, self.vtop = p, 0
        kind = file_kind(p)
        self.sim.set_title(p.name)
        if kind == "img":
            try:
                self.img = pygame.image.load(str(p))
                self.view = "img"
                return
            except Exception:
                pass
        raw = p.read_bytes()[:256 * 1024]
        text = None
        if b"\x00" not in raw[:4096]:
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = None
        if text is not None:
            self.lines = text.replace("\t", "    ").replace("\r", "").split("\n")
            self.view = "text"
        else:
            self.raw, self.view = raw[:16 * 18], "bin"

    def on_key(self, key, shift):
        if self.view:
            if self.view == "text":
                maxtop = max(0, len(self.lines) - 18)
                if key == "UP":
                    self.vtop = max(0, self.vtop - 1)
                elif key == "DOWN":
                    self.vtop = min(maxtop, self.vtop + 1)
                elif key == "RIGHT":
                    self.vtop = min(maxtop, self.vtop + 18)
            if key in ("LEFT", "DEL", "AC"):
                self.view, self.img = None, None
                self.sim.set_title(self.title)
                self.browser.refresh()
            return
        if key == "AC":
            self.browser.go_up()
            return
        if shift and key == "EXE":
            self.browser.refresh()
            return
        f = self.browser.key(key)
        if f:
            self.open(f)

    def draw(self, s):
        if not self.view:
            self.browser.draw(s)
            self.footer(s, "↑↓ mover   EXE abrir   ◄ subir carpeta   SHIFT+EXE recargar")
            return
        if self.view == "img":
            area = pygame.Rect(10, HEADER_H + 8, SCR_W - 20, SCR_H - HEADER_H - 40)
            iw, ih = self.img.get_size()
            k = min(area.w / iw, area.h / ih, 4)
            img = pygame.transform.smoothscale(self.img, (max(1, int(iw * k)), max(1, int(ih * k))))
            s.blit(img, (area.centerx - img.get_width() // 2, area.centery - img.get_height() // 2))
            self.footer(s, f"{iw}×{ih} px  ·  {human_size(self.file.stat().st_size)}   ◄ volver")
            return
        if self.view == "bin":
            draw_text(s, f"Archivo binario · {human_size(self.file.stat().st_size)}", font(18, True), WARN,
                      (14, HEADER_H + 10))
            f = font(16)
            for r in range(0, len(self.raw), 16):
                chunk = self.raw[r:r + 16]
                hx = " ".join(f"{b:02X}" for b in chunk)
                asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                draw_text(s, f"{r:04X}  {hx:<47}  {asc}", f, TEXT, (10, HEADER_H + 40 + (r // 16) * 20))
            self.footer(s, "vista hexadecimal (solo lectura)   ◄ volver")
            return
        f = font(17)
        for r in range(18):
            i = self.vtop + r
            if i >= len(self.lines):
                break
            y = HEADER_H + 8 + r * 21
            draw_text(s, f"{i + 1:3}", f, MUTED, (6, y))
            if self.file.suffix.lower() == ".py":
                self.draw_code(s, self.lines[i][:52], f, 52, y)
            else:
                draw_text(s, self.lines[i][:52], f, TEXT, (52, y))
        n = len(self.lines)
        self.footer(s, f"líneas {self.vtop + 1}-{min(self.vtop + 18, n)} de {n}   (solo lectura)   ◄ volver")

    @staticmethod
    def draw_code(s, line, f, x, y):
        """Resaltado de sintaxis mínimo: comentarios, cadenas y palabras clave."""
        if line.strip().startswith("#"):
            draw_text(s, line, f, OK, (x, y))
            return
        cw = f.size("M")[0]
        i, n = 0, len(line)
        while i < n:
            c = line[i]
            if c in "\"'":
                j = line.find(c, i + 1)
                j = n if j < 0 else j + 1
                draw_text(s, line[i:j], f, WARN, (x + i * cw, y))
                i = j
            elif c == "#":
                draw_text(s, line[i:], f, OK, (x + i * cw, y))
                return
            elif c.isalpha() or c == "_":
                j = i
                while j < n and (line[j].isalnum() or line[j] == "_"):
                    j += 1
                w = line[i:j]
                draw_text(s, w, f, ACCENT if w in PY_KEYWORDS else TEXT, (x + i * cw, y))
                i = j
            else:
                draw_text(s, c, f, TEXT, (x + i * cw, y))
                i += 1


# ------------------------------------------------------------- Consola ------
class ConsoleApp(App):
    """Consola tipo cmd sobre la SD. En el simulador se escribe con el teclado
    del PC; en la calculadora real se usará el modo ALPHA (letras en las teclas)."""
    title = "Consola"
    accepts_text = True
    HELP = [
        "\x04Comandos:",
        "  ls / dir [ruta]        listar carpeta",
        "  cd <carpeta>  · cd ..  cambiar de carpeta",
        "  pwd                    carpeta actual",
        "  cat / type <archivo>   mostrar archivo",
        "  python <x.py> [args]   ejecutar (o: x.py args)",
        "  mkdir <nombre>         crear carpeta (pregunta)",
        "  rm / del <archivo>     borrar (pregunta)",
        "  tree                   árbol de carpetas",
        "  clear / cls            limpiar pantalla",
        "  exit                   volver al menú",
    ]

    def __init__(self, sim):
        super().__init__(sim)
        self.cwd = SD_DIR
        self.out = ["\x04SciCalc shell — escribe 'help'", ""]
        self.line, self.hist, self.hpos = "", [], -1
        self.runner, self.blink = None, 0.0

    def prompt(self):
        return sd_name(self.cwd) + "> "

    def emit(self, *lines):
        self.out.extend(lines)
        self.out = self.out[-400:]

    # -- entrada ----------------------------------------------------------------
    def type_char(self, ch):
        if not self.runner:
            self.line += ch
            self.blink = 0

    def on_key(self, key, shift):
        if self.runner:
            if key in ("AC", "DEL"):
                self.runner.stop()
            return
        chars = {"ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/", "POW": "^", "LP": "(", "RP": ")", ".": "."}
        if key.isdigit():
            self.type_char(key)
        elif key in chars:
            self.type_char(chars[key])
        elif key == "DEL":
            self.line = self.line[:-1]
        elif key == "AC":
            self.line = ""
        elif key == "EXE":
            cmd, self.line = self.line.strip(), ""
            self.emit(self.prompt() + cmd)
            if cmd:
                self.hist.append(cmd)
            self.hpos = -1
            self.run_command(cmd)
        elif key == "UP" and self.hist:
            self.hpos = len(self.hist) - 1 if self.hpos < 0 else max(0, self.hpos - 1)
            self.line = self.hist[self.hpos]
        elif key == "DOWN" and self.hpos >= 0:
            self.hpos += 1
            if self.hpos >= len(self.hist):
                self.hpos, self.line = -1, ""
            else:
                self.line = self.hist[self.hpos]

    # -- comandos ------------------------------------------------------------
    def resolve(self, arg):
        arg = arg.replace("\\", "/")
        base = SD_DIR if arg.startswith("/") else self.cwd
        q = (base / arg.lstrip("/")).resolve()
        sd = SD_DIR.resolve()
        if q != sd and sd not in q.parents:
            raise PermissionError("fuera de la SD")
        return q

    def run_command(self, cmd):
        if not cmd:
            return
        parts = cmd.split()
        c, args = parts[0].lower(), parts[1:]
        try:
            if c == "help":
                self.emit(*self.HELP)
            elif c in ("clear", "cls"):
                self.out = []
            elif c == "exit":
                self.sim.launch(self.sim.menu)
            elif c == "pwd":
                self.emit(sd_name(self.cwd))
            elif c in ("ls", "dir"):
                d = self.resolve(args[0]) if args else self.cwd
                if not d.is_dir():
                    self.emit("\x01no es una carpeta: " + (args[0] if args else ""))
                    return
                items = sorted(d.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
                for e in items:
                    if e.is_dir():
                        self.emit("\x04  " + e.name + "/")
                    else:
                        self.emit(f"  {e.name:<34}{human_size(e.stat().st_size):>9}")
                self.emit(f"\x05  {len(items)} elementos")
            elif c == "cd":
                d = self.resolve(args[0] if args else "/")
                if not d.is_dir():
                    self.emit("\x01no existe la carpeta: " + (args[0] if args else ""))
                else:
                    self.cwd = d
            elif c in ("cat", "type"):
                f = self.resolve(args[0])
                data = f.read_bytes()[:8000]
                if b"\x00" in data:
                    self.emit("\x01archivo binario (usa Archivos SD para verlo)")
                else:
                    self.emit(*data.decode("utf-8", "replace").replace("\t", "    ").splitlines())
            elif c == "tree":
                self.tree(self.cwd, "")
            elif c == "mkdir":
                d = self.resolve(args[0])
                self.sim.ask("Consola", ["¿Crear la carpeta?", "  " + sd_name(d)],
                             lambda a: a in "ya" and (d.mkdir(parents=True, exist_ok=True) or
                                                      self.emit("\x05carpeta creada")) or True)
            elif c in ("rm", "del"):
                f = self.resolve(args[0])
                if not f.exists():
                    self.emit("\x01no existe: " + args[0])
                    return
                what = "la carpeta (y su contenido)" if f.is_dir() else "el archivo"
                self.sim.ask("PERMISO", [f"¿Borrar {what}?", "  " + sd_name(f)],
                             lambda a: a in "ya" and self._rm(f))
            elif c == "python" or c.endswith(".py"):
                if c == "python":
                    if not args:
                        self.emit("\x01uso: python archivo.py [argumentos]")
                        return
                    script, sargs = args[0], args[1:]
                else:
                    script, sargs = parts[0], args
                f = self.resolve(script)
                if not f.is_file():
                    self.emit("\x01no existe: " + script)
                    return
                if self.sim.exam:
                    self.emit("\x01Python bloqueado: modo examen")
                    return
                self.runner = ScriptRunner(f, cwd=sd_name(self.cwd), args=sargs)
                self.shown = 0
            else:
                self.emit(f"\x01comando desconocido: {c}  (escribe 'help')")
        except IndexError:
            self.emit("\x01faltan argumentos (escribe 'help')")
        except Exception as e:
            self.emit(f"\x01{type(e).__name__}: {e}")

    def _rm(self, f):
        shutil.rmtree(f) if f.is_dir() else f.unlink()
        self.emit("\x05borrado")
        return True

    def tree(self, d, pre, depth=0):
        if depth > 3:
            return
        items = sorted(d.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        for i, e in enumerate(items):
            last = i == len(items) - 1
            self.emit(("\x04" if e.is_dir() else "") + pre + ("└─ " if last else "├─ ") + e.name)
            if e.is_dir() and not e.name.startswith("__"):
                self.tree(e, pre + ("   " if last else "│  "), depth + 1)

    def update(self, dt):
        self.blink += dt
        r = self.runner
        if not r:
            return
        pump_runner(self.sim, r)
        if len(r.lines) > self.shown:
            self.emit(*r.lines[self.shown:])
            self.shown = len(r.lines)
        if r.state not in ("running", "asking"):
            msg = {"ok": f"\x05[terminado en {r.elapsed:.2f} s]", "error": "\x01[terminó con error]",
                   "watchdog": f"\x01[WATCHDOG: detenido tras {WATCHDOG_S:.0f} s]",
                   "stopped": "\x03[detenido con AC]", "overflow": "\x01[demasiada salida]"}[r.state]
            self.emit(msg)
            self.runner = None

    def on_exit(self):
        if self.runner:
            self.runner.stop()

    def draw(self, s):
        rows = 18
        lines = self.out + ([] if self.runner else [self.prompt() + self.line])
        y = draw_console(s, lines, HEADER_H + 6, rows)
        if not self.runner and int(self.blink * 2) % 2 == 0:
            last = (self.prompt() + self.line)[:58]
            pygame.draw.rect(s, ACCENT, (12 + font(18).size(last)[0], y - 20, 9, 18))
        self.footer(s, "AC detiene el script" if self.runner else
                    "escribe con el teclado del PC · EXE ejecuta · ↑↓ historial")


# ----------------------------------------------------------- Diagnóstico ----
class DiagApp(App):
    title = "Diagnóstico"

    def __init__(self, sim):
        super().__init__(sim)
        self.last, self.count = None, 0

    def on_key(self, key, shift):
        self.last = (key, shift)
        self.count += 1

    def draw(self, s):
        f = font(17)
        heap = 238 + int(6 * math.sin(time.time()))
        info = [
            ("Chip: ESP32-D0WD rev3  ·  240 MHz  ·  2 núcleos", TEXT),
            ("Flash: 4 MB  ·  PSRAM: no (WROOM)", WARN),
            (f"MicroSD: SDHC  ·  {sum(1 for _ in SD_DIR.rglob('*.py'))} scripts .py", OK if SD_DIR.is_dir() else ERR),
            (f"Heap libre: {heap} KB  ·  bloque máx: 110 KB", TEXT),
        ]
        for i, (t, c) in enumerate(info):
            draw_text(s, t, f, c, (16, HEADER_H + 10 + i * 22))
        pygame.draw.line(s, PANEL, (16, 150), (SCR_W - 16, 150), 2)
        draw_text(s, "Última tecla:", f, MUTED, (16, 160))
        if self.last:
            k, sh = self.last
            txt = ("SHIFT+" if sh else "") + KEY_DEFS[k][0] + f"   #{self.count}"
            draw_text(s, txt, font(30, True), SHIFT_C if sh else TEXT, (16, 184))
        else:
            draw_text(s, "(pulsa cualquier tecla)", font(26), MUTED, (16, 186))
        for idx, k in enumerate(KEY_ORDER):
            block, r, c = idx // 16, (idx % 16) // 4, idx % 4
            x = 16 + block * 312 + c * 76
            y = 236 + r * 50
            hi = self.last and self.last[0] == k
            pygame.draw.rect(s, ACCENT if hi else PANEL, (x, y, 70, 44), border_radius=7)
            draw_text(s, KEY_DEFS[k][0], font(18, True), TEXT, (x, y + 11), "center", 70)
        self.footer(s, "MENU vuelve  ·  SHIFT aparece en la barra superior")


# =============================================================================
#  Paquetes instalados en /lib  (manifiesto  /lib/paquetes.json)
# =============================================================================
FW_VERSION = "0.3"
LIB_DIR = SD_DIR / "lib"
MANIFEST = LIB_DIR / "paquetes.json"


def read_manifest():
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_manifest(m):
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding="utf-8")


def uninstall_package(name):
    m = read_manifest()
    info = m.pop(name, None)
    if not info:
        return 0
    n = 0
    dirs = set()
    for rel in info.get("files", []):
        f = (LIB_DIR / rel).resolve()
        if LIB_DIR.resolve() in f.parents and f.is_file():
            f.unlink()
            n += 1
            dirs.update(f.parents)
    for d in sorted(dirs, key=lambda x: len(x.parts), reverse=True):   # carpetas vacías
        if LIB_DIR.resolve() in d.parents:
            try:
                for pc in d.glob("__pycache__"):
                    shutil.rmtree(pc, ignore_errors=True)
                d.rmdir()
            except OSError:
                pass
    write_manifest(m)
    return n


# =============================================================================
#  SciCalc Link — protocolo de conexión con el PC  (USB / Bluetooth / Wi-Fi)
# -----------------------------------------------------------------------------
#  Una petición JSON por línea, una respuesta JSON por línea. Igual por los tres
#  medios: USB-serie, Bluetooth (puerto serie SPP) y Wi-Fi (TCP, puerto 8266).
#    hello   {client}                 -> la calculadora PREGUNTA si aceptas
#    info / ls {path} / get {path}
#    confirm {title, lines}           -> la calculadora PREGUNTA (instalar, borrar...)
#    put {path, data(b64), append} / mkdir {path} / rm {path, recursive}
#                                     -> solo en /lib y /scripts y tras un confirm
#    done                             -> cierra la operación confirmada
#    wifi {ssid, password}            -> guarda una red (la calculadora PREGUNTA)
#  En el simulador solo funciona el Wi-Fi (127.0.0.1:8266); USB y Bluetooth son
#  el mismo protocolo sobre un puerto COM en la calculadora real.
# =============================================================================
LINK_PORT = 8266


def link_path(p, write=False):
    sd = SD_DIR.resolve()
    q = (sd / str(p or "/").replace("\\", "/").lstrip("/")).resolve()
    if q != sd and sd not in q.parents:
        raise PermissionError("ruta fuera de la SD")
    if write:
        parts = q.relative_to(sd).parts
        if not parts or parts[0] not in ("lib", "scripts"):
            raise PermissionError("solo se puede escribir en /lib y /scripts")
    return q


def link_handle(sim, req, session, transport):
    import base64
    cmd = req.get("cmd")
    if sim.exam:
        return {"ok": False, "error": "la calculadora está en MODO EXAMEN"}
    if cmd == "hello":
        name = str(req.get("client", "PC"))[:24]
        ans = sim.ask_blocking("SciCalc Link", [
            f"'{name}' quiere conectarse", f"por {transport}.", "",
            "Podrá instalar paquetes y scripts.", "Cada operación te la preguntaré.", "",
            "¿Aceptar la conexión?"])
        if ans not in ("y", "a"):
            return {"ok": False, "error": "conexión rechazada en la calculadora"}
        session.update(ok=True, name=name)
        sim.link_clients += 1
        sim.link_name = name
        return {"ok": True, "device": "ESP32 SciCalc", "fw": FW_VERSION, "transport": transport}
    if not session.get("ok"):
        return {"ok": False, "error": "no autorizado (falta hello)"}

    if cmd == "info":
        return {"ok": True, "device": "ESP32 SciCalc", "fw": FW_VERSION,
                "free_kb": shutil.disk_usage(SD_DIR).free // 1024,
                "packages": len(read_manifest()), "wifi": sim.wifi_net}
    if cmd == "ls":
        q = link_path(req.get("path"))
        if not q.exists():
            return {"ok": True, "entries": []}
        return {"ok": True, "entries": [
            {"name": e.name, "dir": e.is_dir(), "size": e.stat().st_size if e.is_file() else 0}
            for e in sorted(q.iterdir())]}
    if cmd == "get":
        q = link_path(req.get("path"))
        if not q.is_file():
            return {"ok": False, "error": "no existe"}
        return {"ok": True, "data": base64.b64encode(q.read_bytes()).decode()}
    if cmd == "confirm":
        lines = [str(x)[:40] for x in req.get("lines", [])][:8]
        ans = sim.ask_blocking(str(req.get("title", "SciCalc Link"))[:24], lines + ["", "¿Aceptar?"])
        session["op"] = ans in ("y", "a")
        return {"ok": True, "accepted": session["op"]}
    if cmd == "done":
        session["op"] = False
        return {"ok": True}
    if cmd == "wifi":
        ssid = str(req.get("ssid", ""))[:32]
        ans = sim.ask_blocking("Red Wi-Fi", [f"'{session['name']}' quiere guardar", "la red Wi-Fi:", f"  {ssid}",
                                             "", "¿Guardarla?"])
        if ans in ("y", "a"):
            sim.wifi_known[ssid] = str(req.get("password", ""))
            if ssid not in [n[0] for n in sim.networks]:
                sim.networks.insert(0, (ssid, -50, "WPA2"))
        return {"ok": True, "accepted": ans in ("y", "a")}
    if cmd in ("put", "mkdir", "rm"):
        if not session.get("op"):
            return {"ok": False, "error": "operación no confirmada en la calculadora"}
        q = link_path(req.get("path"), write=True)
        if cmd == "put":
            q.parent.mkdir(parents=True, exist_ok=True)
            with open(q, "ab" if req.get("append") else "wb") as f:
                f.write(base64.b64decode(req.get("data", "")))
        elif cmd == "mkdir":
            q.mkdir(parents=True, exist_ok=True)
        else:
            if q.is_dir():
                shutil.rmtree(q) if req.get("recursive") else q.rmdir()
            elif q.exists():
                q.unlink()
        return {"ok": True}
    return {"ok": False, "error": f"comando desconocido: {cmd}"}


class LinkServer:
    """Servidor TCP del simulador (= SciCalc Link por Wi-Fi)."""

    def __init__(self, sim):
        self.sim, self.sock, self.error = sim, None, None

    def start(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", LINK_PORT))
            s.listen(2)
            s.settimeout(0.5)
        except OSError as e:
            self.error = f"puerto {LINK_PORT} ocupado"
            print("SciCalc Link:", e)
            return
        self.sock, self.error = s, None
        threading.Thread(target=self._accept, args=(s,), daemon=True).start()

    def stop(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def _accept(self, s):
        while self.sock is s:
            try:
                conn, _ = s.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn):
        session = {"ok": False, "op": False, "name": "PC"}
        conn.settimeout(None)
        f = conn.makefile("rwb")
        try:
            for raw in f:
                try:
                    req = json.loads(raw.decode("utf-8"))
                    rep = link_handle(self.sim, req, session, "Wi-Fi")
                except Exception as e:
                    req, rep = {}, {"ok": False, "error": str(e)}
                rep["id"] = req.get("id")
                f.write((json.dumps(rep) + "\n").encode("utf-8"))
                f.flush()
                if self.sock is None:
                    break
        except OSError:
            pass
        finally:
            if session.get("ok"):
                self.sim.link_clients = max(0, self.sim.link_clients - 1)
            try:
                conn.close()
            except OSError:
                pass


# =============================================================================
#  Ajustes: Wi-Fi, Bluetooth, USB, modo examen, paquetes
# =============================================================================
class SettingsApp(App):
    title = "Ajustes"

    def __init__(self, sim):
        super().__init__(sim)
        self.page, self.sel, self.connecting = "main", {}, None

    def on_enter(self):
        self.page = "main"

    # ---- filas de cada página: dict(label, value, action, signal, color) ----
    def rows(self):
        sim = self.sim
        if self.page == "main":
            wv = sim.wifi_net or ("Encendido" if sim.wifi_on else "Apagado")
            return [
                dict(label="Wi-Fi", value=wv, action="page:wifi", color=OK if sim.wifi_net else None),
                dict(label="Bluetooth", value="Visible" if sim.bt_on else "Apagado", action="page:bt",
                     color=OK if sim.bt_on else None),
                dict(label="USB", value="Serie · SciCalc Link", action="page:usb"),
                dict(label="Modo examen", value="ACTIVADO" if sim.exam else "Desactivado",
                     action="toggle:exam", color=WARN if sim.exam else None),
                dict(label="Paquetes Python", value=f"{len(read_manifest())} instalados", action="page:pkgs"),
                dict(label="Acerca de", value=f"v{FW_VERSION}", action="page:about"),
            ]
        if self.page == "wifi":
            r = [dict(label="Wi-Fi", value="Encendido" if sim.wifi_on else "Apagado", action="toggle:wifi",
                      color=OK if sim.wifi_on else None)]
            if sim.wifi_on:
                for ssid, rssi, sec in sim.networks:
                    if self.connecting and self.connecting[0] == ssid:
                        v, c = "conectando…", WARN
                    elif sim.wifi_net == ssid:
                        v, c = "conectada", OK
                    elif ssid in sim.wifi_known:
                        v, c = "guardada", None
                    else:
                        v, c = sec, None
                    r.append(dict(label=ssid, value=v, action="net:" + ssid, signal=rssi, color=c))
            return r
        if self.page == "bt":
            return [dict(label="Bluetooth", value="Encendido" if sim.bt_on else "Apagado", action="toggle:bt",
                         color=OK if sim.bt_on else None),
                    dict(label="Nombre", value="SciCalc-7F3A", action=None),
                    dict(label="Estado", value="visible, esperando PC" if sim.bt_on else "-", action=None)]
        if self.page == "usb":
            return [dict(label="Modo USB", value="Serie (SciCalc Link)", action=None, color=OK),
                    dict(label="Velocidad", value="115200 baudios", action=None),
                    dict(label="Disco USB (MSC)", value="requiere ESP32-S3", action="info:msc")]
        if self.page == "pkgs":
            return [dict(label=n, value=f"{i.get('version', '?')} · {i.get('source', '?')}", action="pkg:" + n)
                    for n, i in sorted(read_manifest().items())]
        return []

    def info_lines(self):
        sim = self.sim
        if self.page == "wifi":
            if sim.wifi_net:
                st = f"SciCalc Link escuchando en 127.0.0.1:{LINK_PORT}" if sim.link.sock else \
                     f"SciCalc Link: {sim.link.error or 'iniciando…'}"
                return ["IP 192.168.1.57  (simulado)", st]
            return ["Elige una red y pulsa EXE."]
        if self.page == "bt":
            return ["En el PC: Bluetooth > Agregar dispositivo >",
                    "SciCalc-7F3A. Windows crea un puerto COM:",
                    "elígelo en SciCalc Link (Bluetooth).",
                    "(en el simulador el Bluetooth es solo visual)"]
        if self.page == "usb":
            return ["Conecta el cable USB-C y elige el puerto COM",
                    "en SciCalc Link (USB). Mismo protocolo que",
                    "Bluetooth y Wi-Fi."]
        if self.page == "pkgs" and not read_manifest():
            return ["No hay paquetes instalados.", "", "Instálalos desde el PC con SciCalc Link:",
                    "se guardan en /lib de la MicroSD."]
        if self.page == "pkgs":
            return ["EXE sobre un paquete para desinstalarlo."]
        if self.page == "about":
            return [f"ESP32 SciCalc  v{FW_VERSION}", "Núcleo: C++ (FreeRTOS)  ·  Scripts: MicroPython",
                    "Chip: ESP32-WROOM-32  ·  Flash 4 MB", f"SD libre: {shutil.disk_usage(SD_DIR).free // 2**20} MB",
                    f"Paquetes: {len(read_manifest())} en /lib", f"Conexiones activas: {sim.link_clients}"]
        return []

    # ---- teclas ------------------------------------------------------------
    def on_key(self, key, shift):
        rows = self.rows()
        sel = self.sel.get(self.page, 0)
        if rows:
            sel = min(sel, len(rows) - 1)
        if key == "UP" and rows:
            sel = (sel - 1) % len(rows)
        elif key == "DOWN" and rows:
            sel = (sel + 1) % len(rows)
        elif key in ("LEFT", "AC", "DEL"):
            if self.page != "main":
                self.page = "main"
                self.sim.set_title(self.title)
            return
        elif key in ("EXE", "RIGHT") and rows and rows[sel].get("action"):
            self.do(rows[sel]["action"])
        self.sel[self.page] = sel

    def do(self, action):
        sim = self.sim
        kind, _, arg = action.partition(":")
        titles = {"wifi": "Wi-Fi", "bt": "Bluetooth", "usb": "USB", "pkgs": "Paquetes", "about": "Acerca de"}
        if kind == "page":
            self.page = arg
            sim.set_title("Ajustes › " + titles[arg])
        elif kind == "toggle" and arg == "exam":
            if not sim.exam:
                sim.ask("Modo examen", ["Se APAGAN Wi-Fi y Bluetooth", "y se BLOQUEA Python.", "",
                                        "Aparecerá EXAMEN en la barra.", "", "¿Activar?"],
                        lambda a: a in "ya" and sim.set_exam(True))
            else:
                sim.ask("Modo examen", ["¿Salir del modo examen?"], lambda a: a in "ya" and sim.set_exam(False))
        elif kind == "toggle":
            if sim.exam:
                sim.ask("Modo examen", ["No disponible durante", "el modo examen."], None, info=True)
            elif arg == "wifi":
                sim.wifi_on = not sim.wifi_on
                if not sim.wifi_on:
                    sim.wifi_net, self.connecting = None, None
            elif arg == "bt":
                sim.bt_on = not sim.bt_on
        elif kind == "net":
            if sim.wifi_net == arg:
                sim.ask("Wi-Fi", [f"¿Desconectar de {arg}?"], lambda a: a in "ya" and sim.disconnect_wifi())
                return
            sec = dict((n, s_) for n, _, s_ in sim.networks).get(arg)
            if sec != "abierta" and arg not in sim.wifi_known:
                sim.ask("Contraseña", [f"{arg} tiene contraseña.", "",
                                       "Envíala desde SciCalc Link por USB",
                                       "(pestaña Wi-Fi) y luego conecta.", "",
                                       "Simulador: ¿conectar igualmente?"],
                        lambda a: a in "ya" and self.start_connect(arg))
            else:
                self.start_connect(arg)
        elif kind == "info" and arg == "msc":
            sim.ask("Disco USB", ["Que el PC vea la MicroSD como un", "pendrive necesita USB nativo",
                                  "(ESP32-S3). Con tu ESP32 usa el", "modo Serie, o saca la MicroSD",
                                  "y conéctala al PC."], None, info=True)
        elif kind == "pkg":
            n = len(read_manifest().get(arg, {}).get("files", []))
            sim.ask("Desinstalar", [f"Paquete: {arg}", f"Se borrarán {n} archivos de /lib.", "", "¿Desinstalar?"],
                    lambda a: a in "ya" and uninstall_package(arg))

    def start_connect(self, ssid):
        self.connecting = (ssid, time.time())

    def update(self, dt):
        if self.connecting and time.time() - self.connecting[1] > 1.2:
            self.sim.wifi_net = self.connecting[0]
            self.sim.wifi_known.setdefault(self.connecting[0], "")
            self.connecting = None

    # ---- dibujo ------------------------------------------------------------
    def draw(self, s):
        rows = self.rows()
        sel = min(self.sel.get(self.page, 0), max(0, len(rows) - 1))
        top = max(0, sel - 5)
        y = HEADER_H + 10
        for i in range(top, min(len(rows), top + 6)):
            r = rows[i]
            hi = i == sel
            pygame.draw.rect(s, ACCENT if hi else PANEL, (12, y, SCR_W - 24, 46), border_radius=8)
            draw_text(s, r["label"], font(22, True), TEXT, (26, y + 11))
            vx = SCR_W - 30
            if "signal" in r:
                bars = 4 if r["signal"] > -55 else 3 if r["signal"] > -65 else 2 if r["signal"] > -75 else 1
                for b in range(4):
                    h = 6 + b * 5
                    pygame.draw.rect(s, TEXT if b < bars else (90, 96, 110),
                                     (vx - 32 + b * 8, y + 34 - h, 5, h))
                vx -= 44
            col = r.get("color") or (TEXT if hi else MUTED)
            if hi and r.get("color"):
                col = TEXT
            draw_text(s, r["value"], font(17, True), col, (12, y + 14), "right", vx - 12)
            y += 54
        yy = y + 6
        for line in self.info_lines():
            draw_text(s, line, font(16), MUTED, (20, yy))
            yy += 21
        self.footer(s, "↑↓ mover   EXE elegir   ◄/AC volver" if self.page != "main"
                    else "↑↓ mover   EXE elegir   MENU salir")


# =============================================================================
#  Simulador: carcasa + pantalla + gestor de apps
# =============================================================================
class Simulator:
    def __init__(self):
        self.screen = pygame.Surface((SCR_W, SCR_H))
        self.rects = build_layout()
        self.shift = False
        self.degrees = True
        self.pressed = {}            # id -> instante de pulsación (animación)
        self.hover = None
        self.boot_t = 0.0
        self.booting = True
        self.title = ""
        self.calc = CalcApp(self)
        self.py = PythonApp(self)
        self.files = FilesApp(self)
        self.diag = DiagApp(self)
        # Conectividad (simulada) y modo examen
        self.wifi_on, self.wifi_net, self.bt_on, self.exam = False, None, False, False
        self.wifi_known = {}
        self.networks = [("MiCasa_WiFi", -48, "WPA2"), ("iPhone de Yerai", -56, "WPA2"),
                         ("MOVISTAR_5A2C", -67, "WPA2"), ("Biblioteca_Libre", -78, "abierta")]
        self.link = LinkServer(self)
        self.link_clients, self.link_name = 0, ""
        self.modals = []                       # diálogos en pantalla (el primero es el visible)
        self.pending = queue.Queue()           # diálogos pedidos desde otros hilos
        self.settings = SettingsApp(self)
        self.console = ConsoleApp(self)
        self.menu = MenuApp(self, [
            ("Calculadora", "C++ nativo", self.calc),
            ("Python", "sandbox .py", self.py),
            ("Archivos SD", "fotos · texto · todo", self.files),
            ("Consola", "tipo cmd", self.console),
            ("Ajustes", "Wi-Fi · BT · USB", self.settings),
            ("Diagnóstico", "HW y teclado", self.diag),
        ])
        self.current = None
        self.body = self._render_body()

    # ---- gestor de apps ----------------------------------------------------
    def launch(self, app):
        if self.current and hasattr(self.current, "on_exit"):
            self.current.on_exit()
        self.current = app
        self.shift = False
        self.title = app.title
        app.on_enter()

    def set_title(self, t):
        self.title = t

    # ---- diálogos (permisos, confirmaciones) -------------------------------
    def ask(self, title, lines, callback, allow_all=False, info=False):
        self.modals.append(dict(title=title, lines=lines, cb=callback, all=allow_all, info=info))

    def ask_blocking(self, title, lines, timeout=60):
        """Desde otro hilo (SciCalc Link): espera la respuesta del usuario."""
        ev, box = threading.Event(), {}
        self.pending.put((title, lines, ev, box))
        if not ev.wait(timeout):
            box["expired"] = True
            return "n"
        return box.get("ans", "n")

    def _modal_key(self, key):
        m = self.modals[0]
        if key == "SHIFT":
            self.shift = not self.shift
            return
        if m["info"] and key in ("EXE", "AC", "DEL", "LEFT"):
            ans = "y"
        elif key == "EXE":
            ans = "a" if (self.shift and m["all"]) else "y"
        elif key in ("AC", "DEL"):
            ans = "n"
        else:
            return
        self.shift = False
        self.modals.pop(0)
        if m["cb"]:
            m["cb"](ans)

    def set_exam(self, on):
        self.exam = on
        if on:
            self.wifi_on, self.wifi_net, self.bt_on = False, None, False
        return True

    def disconnect_wifi(self):
        self.wifi_net = None
        return True

    def press(self, key, force_shift=None):
        self.pressed[key] = time.time()
        if self.booting:
            return
        if self.modals:
            self._modal_key(key)
            return
        if force_shift is not None:
            self.shift = force_shift
        if key == "SHIFT":
            self.shift = not self.shift
            return
        if key == "MENU":
            if self.current is not self.menu:
                self.launch(self.menu)
            return
        sh = self.shift
        self.shift = False
        self.current.on_key(key, sh)

    def update(self, dt):
        if self.booting:
            self.boot_t += dt
            if self.boot_t > 2.2:
                self.booting = False
                self.launch(self.menu)
            return
        # diálogos pedidos por SciCalc Link (otro hilo)
        while True:
            try:
                title, lines, ev, box = self.pending.get_nowait()
            except queue.Empty:
                break

            def cb(ans, ev=ev, box=box):
                box["ans"] = ans
                ev.set()
            self.ask(title, lines, cb)
            self.modals[-1]["box"] = box
        self.modals = [m for m in self.modals if not m.get("box", {}).get("expired")]
        # el servidor de enlace vive mientras haya Wi-Fi conectado
        want = bool(self.wifi_net) and not self.exam
        if want and not self.link.sock and not self.link.error:
            self.link.start()
        elif not want and self.link.sock:
            self.link.stop()
        if not want:
            self.link.error = None
        self.current.update(dt)
        if self.current is not self.settings:
            self.settings.update(dt)

    # ---- pantalla ------------------------------------------------------------
    def draw_screen(self):
        s = self.screen
        s.fill(BG)
        if self.booting:
            self.draw_boot(s)
            return
        self.current.draw(s)
        if self.modals:
            self.draw_modal(s, self.modals[0])
        # Barra de estado
        pygame.draw.rect(s, PANEL, (0, 0, SCR_W, HEADER_H))
        pygame.draw.line(s, ACCENT, (0, HEADER_H - 2), (SCR_W, HEADER_H - 2), 2)
        draw_text(s, self.title, font(24, True), TEXT, (12, 9))
        x = SCR_W - 12
        # batería
        x -= 40
        pygame.draw.rect(s, TEXT, (x, 13, 34, 18), 2, border_radius=3)
        pygame.draw.rect(s, TEXT, (x + 34, 18, 4, 8))
        pygame.draw.rect(s, OK, (x + 4, 17, 22, 10))
        x -= 66
        draw_text(s, datetime.now().strftime("%H:%M"), font(18, True), TEXT, (x, 12))
        x -= 34
        draw_text(s, "SD", font(16, True), OK if SD_DIR.is_dir() else MUTED, (x, 14))
        if self.current is self.calc:
            x -= 50
            draw_text(s, "DEG" if self.degrees else "RAD", font(16, True), ACCENT, (x, 14))
        for txt, col, show in (("WiFi", ACCENT, self.wifi_net), ("BT", ACCENT, self.bt_on),
                               ("LINK", OK, self.link_clients > 0)):
            if show:
                x -= font(16, True).size(txt)[0] + 14
                draw_text(s, txt, font(16, True), col, (x, 14))
        if self.exam:
            x -= 92
            pygame.draw.rect(s, WARN, (x, 9, 84, 26), border_radius=5)
            draw_text(s, "EXAMEN", font(16, True), BG, (x, 13), "center", 84)
        if self.shift:
            x -= 82
            pygame.draw.rect(s, SHIFT_C, (x, 9, 74, 26), border_radius=5)
            draw_text(s, "SHIFT", font(16, True), BG, (x, 13), "center", 74)

    def draw_modal(self, s, m):
        veil = pygame.Surface((SCR_W, SCR_H - HEADER_H), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 160))
        s.blit(veil, (0, HEADER_H))
        lines = m["lines"]
        h = 120 + 25 * len(lines)
        box = pygame.Rect(36, HEADER_H + max(8, (SCR_H - HEADER_H - h) // 2), SCR_W - 72, h)
        col = WARN if m["title"] in ("PERMISO", "Desinstalar", "Modo examen") else ACCENT
        pygame.draw.rect(s, (22, 25, 33), box, border_radius=12)
        pygame.draw.rect(s, col, box, 3, border_radius=12)
        pygame.draw.rect(s, col, (box.x, box.y, box.w, 40), border_top_left_radius=12, border_top_right_radius=12)
        draw_text(s, m["title"], font(22, True), BG, (box.x + 16, box.y + 8))
        y = box.y + 52
        for ln in lines:
            draw_text(s, ln, font(19, ln.startswith("  ")), TEXT, (box.x + 18, y))
            y += 25
        opts = [("EXE", "Aceptar", OK), ] if m["info"] else \
            [("EXE", "Sí", OK)] + ([("SHIFT+EXE", "Sí a todo", SHIFT_C)] if m["all"] else []) + [("AC", "No", ERR)]
        x = box.x + 16
        for k, label, c in opts:
            txt = f"{k}  {label}"
            w = font(17, True).size(txt)[0] + 20
            pygame.draw.rect(s, c, (x, box.bottom - 46, w, 32), border_radius=7)
            draw_text(s, txt, font(17, True), BG, (x, box.bottom - 40), "center", w)
            x += w + 10

    def draw_boot(self, s):
        t = self.boot_t
        draw_text(s, "ESP32 SciCalc", font(52, True), TEXT, (0, 90), "center", SCR_W)
        draw_text(s, "v0.2  ·  C++ nativo + MicroPython", font(18), MUTED, (0, 158), "center", SCR_W)
        pygame.draw.line(s, ACCENT, (150, 200), (490, 200), 2)
        checks = [("Pantalla", "OK", OK), ("Teclado", "OK", OK),
                  ("MicroSD", "OK" if SD_DIR.is_dir() else "NO", OK if SD_DIR.is_dir() else ERR),
                  ("PSRAM", "no (WROOM)", WARN), ("Sandbox Python", "listo", OK)]
        for i, (name, res, col) in enumerate(checks):
            if t < 0.3 + i * 0.3:
                break
            y = 224 + i * 30
            draw_text(s, name, font(20), TEXT, (150, y))
            draw_text(s, res, font(20, True), col, (150, y), "right", 340)
        w = int(min(1, t / 2.0) * 340)
        pygame.draw.rect(s, PANEL, (150, 400, 340, 8), border_radius=4)
        pygame.draw.rect(s, ACCENT, (150, 400, w, 8), border_radius=4)

    # ---- carcasa (estática, se dibuja una vez) -------------------------------
    def _render_body(self):
        surf = pygame.Surface((BASE_W, BASE_H), pygame.SRCALPHA)
        body = pygame.Rect(10, 10, BASE_W - 20, BASE_H - 20)
        # sombra
        sh = pygame.Surface((BASE_W, BASE_H), pygame.SRCALPHA)
        pygame.draw.rect(sh, (0, 0, 0, 90), body.move(0, 6), border_radius=56)
        surf.blit(sh, (0, 0))
        # degradado vertical recortado a esquinas redondeadas
        grad = pygame.Surface(body.size, pygame.SRCALPHA)
        top, bot = (52, 57, 66), (28, 31, 37)
        for y in range(body.h):
            k = y / body.h
            c = [int(top[i] + (bot[i] - top[i]) * k) for i in range(3)]
            pygame.draw.line(grad, c, (0, y), (body.w, y))
        mask = pygame.Surface(body.size, pygame.SRCALPHA)
        pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=56)
        grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        surf.blit(grad, body.topleft)
        pygame.draw.rect(surf, (85, 92, 104), body, 2, border_radius=56)
        pygame.draw.rect(surf, (20, 22, 26), body.inflate(-14, -14), 1, border_radius=50)
        # marca
        draw_text(surf, "ESP32", font(28, True, False), (240, 242, 246), (48, 36))
        draw_text(surf, "SciCalc", font(28, False, False), ACCENT, (140, 36))
        draw_text(surf, "MicroPython Edition", font(15, False, False), (150, 158, 172),
                  (0, 46), "right", BASE_W - 90)
        pygame.draw.circle(surf, (60, 220, 120), (BASE_W - 60, 56), 5)        # LED encendido
        # bisel de la pantalla
        bez = pygame.Rect(SCR_X - 14, SCR_Y - 14, SCR_W + 28, SCR_H + 28)
        pygame.draw.rect(surf, (6, 7, 9), bez, border_radius=20)
        pygame.draw.rect(surf, (70, 76, 88), bez, 2, border_radius=20)
        draw_text(surf, "320×240 TFT  ·  ESP32-WROOM-32  ·  Wi-Fi", font(14, False, False),
                  (120, 128, 142), (0, 598), "center", BASE_W)
        # zona del teclado
        pygame.draw.line(surf, (24, 26, 31), (40, 790), (BASE_W - 40, 790), 2)
        pygame.draw.line(surf, (24, 26, 31), (40, 972), (BASE_W - 40, 972), 2)
        draw_text(surf, "PC:  0-9 + - * / ^ ( )  ·  Enter=EXE  ·  Retroceso=DEL  ·  Esc=AC  ·  "
                  "Tab=SHIFT  ·  M=MENU", font(13, False, False), (110, 118, 132), (0, 1326),
                  "center", BASE_W)
        return surf

    # ---- teclas --------------------------------------------------------------
    def key_at(self, pos):
        x, y = pos
        dx, dy = x - DPAD_C[0], y - DPAD_C[1]
        d = math.hypot(dx, dy)
        if DPAD_R_IN < d <= DPAD_R:
            if abs(dx) > abs(dy):
                return "RIGHT" if dx > 0 else "LEFT"
            return "DOWN" if dy > 0 else "UP"
        for k, r in self.rects.items():
            if r.collidepoint(pos):
                return k
        return None

    def is_down(self, k):
        return time.time() - self.pressed.get(k, 0) < 0.13

    def draw_key(self, surf, k):
        r = self.rects[k]
        label, shl, style = KEY_DEFS[k]
        face, fg = KEY_STYLE[style]
        down = self.is_down(k)
        if self.hover == k and not down:
            face = tuple(min(255, c + 14) for c in face)
        if k == "SHIFT" and self.shift:
            face = (255, 214, 90)
        dy = 4 if down else 0
        shadow = tuple(max(0, int(c * 0.55)) for c in face)
        pygame.draw.rect(surf, (12, 13, 16), r.move(0, 7), border_radius=12)
        pygame.draw.rect(surf, shadow, r.move(0, 4), border_radius=12)
        fr = r.move(0, dy)
        pygame.draw.rect(surf, face, fr, border_radius=12)
        hl = tuple(min(255, c + 30) for c in face)
        pygame.draw.line(surf, hl, (fr.x + 10, fr.y + 2), (fr.right - 10, fr.y + 2), 2)
        big = style == "num" or k in ("ADD", "SUB", "MUL", "DIV")
        f = font(34 if big else 24, True, False)
        if label == "xʸ":
            w1 = f.size("x")[0]
            fs = font(16, True, False)
            x0 = fr.x + (fr.w - w1 - fs.size("y")[0]) // 2
            draw_text(surf, "x", f, fg, (x0, fr.y + (fr.h - f.get_height()) // 2))
            draw_text(surf, "y", fs, fg, (x0 + w1, fr.y + 8))
        else:
            draw_text(surf, label, f, fg, (fr.x, fr.y + (fr.h - f.get_height()) // 2),
                      "center", fr.w)
        if shl:
            draw_text(surf, shl, font(15, True, False), SHIFT_C, (r.x, r.y - 21), "center", r.w)

    def draw_dpad(self, surf):
        cx, cy = DPAD_C
        pygame.draw.circle(surf, (12, 13, 16), (cx, cy + 7), DPAD_R)
        pygame.draw.circle(surf, (30, 33, 39), (cx, cy + 4), DPAD_R)
        pygame.draw.circle(surf, (58, 63, 73), (cx, cy), DPAD_R)
        pygame.draw.circle(surf, (80, 86, 98), (cx, cy), DPAD_R, 2)
        dirs = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}
        for k, (ux, uy) in dirs.items():
            if self.is_down(k) or self.hover == k:
                col = ACCENT if self.is_down(k) else (78, 84, 96)
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

    # ---- frame completo ----------------------------------------------------
    def render(self):
        base = pygame.Surface((BASE_W, BASE_H), pygame.SRCALPHA)
        base.blit(self.body, (0, 0))
        self.draw_screen()
        base.blit(self.screen, (SCR_X, SCR_Y))
        # reflejo del cristal
        glare = pygame.Surface((SCR_W, SCR_H), pygame.SRCALPHA)
        pygame.draw.polygon(glare, (255, 255, 255, 10), [(0, 0), (SCR_W * 0.55, 0), (SCR_W * 0.25, SCR_H), (0, SCR_H)])
        base.blit(glare, (SCR_X, SCR_Y))
        for k in self.rects:
            self.draw_key(base, k)
        self.draw_dpad(base)
        return base


# =============================================================================
#  Scripts de ejemplo para la SD simulada
# =============================================================================
DEMO_SCRIPTS = {
    "hola.py": '''# hola.py - primer script del sandbox
import math

print("Hola desde el sandbox de Python!")
for n in range(1, 6):
    print(n, "->", round(math.sqrt(n), 4))
''',
    "primos.py": '''# primos.py - criba de Eratostenes
def primos(limite):
    es_primo = [True] * (limite + 1)
    es_primo[0] = es_primo[1] = False
    for i in range(2, int(limite ** 0.5) + 1):
        if es_primo[i]:
            for j in range(i * i, limite + 1, i):
                es_primo[j] = False
    return [n for n, p in enumerate(es_primo) if p]

p = primos(200)
print(len(p), "primos menores que 200:")
for i in range(0, len(p), 10):
    print(" ".join("%3d" % x for x in p[i:i + 10]))
''',
    "tabla_seno.py": '''# tabla_seno.py - tabla trigonometrica con barras
import math

print(" grados   seno     grafica")
for g in range(0, 181, 15):
    s = math.sin(math.radians(g))
    print("%5d   %6.3f   %s" % (g, s, "#" * int(s * 20)))
''',
    "fibonacci.py": '''# fibonacci.py
a, b = 0, 1
for i in range(1, 31):
    print("F(%2d) = %d" % (i, b))
    a, b = b, a + b
''',
    "bucle_infinito.py": '''# bucle_infinito.py - DEMO DEL WATCHDOG
# Este script nunca termina. El nucleo de la calculadora
# lo detendra a los 5 segundos sin colgarse.
print("Entrando en un bucle infinito...")
i = 0
while True:
    i += 1
''',
    "permisos.py": '''# permisos.py - DEMO DE PERMISOS
# Leer es libre. Escribir, borrar o renombrar te lo PREGUNTA la calculadora.
import os

print("Archivos en esta carpeta:", os.listdir("."))

with open("notas.txt", "w") as f:          # -> pide permiso
    f.write("Hola desde el sandbox\\n")
print("1) notas.txt escrito")

os.rename("notas.txt", "notas_old.txt")     # -> pide permiso
print("2) renombrado a notas_old.txt")

os.remove("notas_old.txt")                  # -> pide permiso
print("3) borrado")

try:
    import subprocess
except ImportError as e:
    print("4) subprocess ->", e)

try:
    open("../../secreto.txt").read()
except Exception as e:
    print("5) salir de la SD ->", e)
''',
    "error.py": '''# error.py - DEMO DE EXCEPCIONES
# El error se muestra con su numero de linea y la
# calculadora sigue funcionando.
def dividir(a, b):
    return a / b

print("10 / 2 =", dividir(10, 2))
print("10 / 0 =", dividir(10, 0))
''',
}


def ensure_sd():
    d = SD_DIR / "scripts"
    d.mkdir(parents=True, exist_ok=True)
    for name, content in DEMO_SCRIPTS.items():
        p = d / name
        if not p.exists():
            p.write_text(content, encoding="utf-8")
    extra = {
        "scripts/mates/derivada.py": '''# derivada.py - derivada numérica
# Úsalo desde la Consola con argumentos:   python derivada.py 2
import sys, math

x = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
f = lambda t: t ** 3 - 2 * t
h = 1e-6
print("f(x) = x^3 - 2x")
print("f'(%g) = %.6f" % (x, (f(x + h) - f(x - h)) / (2 * h)))
''',
        "scripts/mates/ecuacion2.py": '''# ecuacion2.py - resuelve ax^2 + bx + c = 0
# Consola:  python ecuacion2.py 1 -3 2
import sys, cmath

a, b, c = (float(v) for v in (sys.argv[1:4] if len(sys.argv) >= 4 else ("1", "-3", "2")))
d = cmath.sqrt(b * b - 4 * a * c)
print("x1 =", (-b + d) / (2 * a))
print("x2 =", (-b - d) / (2 * a))
''',
        "docs/leeme.txt": "ESP32 SciCalc - MicroSD\n\n/scripts  tus programas .py\n/lib      paquetes instalados con SciCalc Link\n"
                          "/fotos    imágenes (PNG/JPG)\n/docs     documentos\n",
        "docs/notas.md": "# Fórmulas\n\n- Área círculo: π·r²\n- Pitágoras: a² + b² = c²\n- Derivada de x^n: n·x^(n-1)\n",
    }
    for rel, content in extra.items():
        p = SD_DIR / rel
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
    (SD_DIR / "lib").mkdir(exist_ok=True)
    fotos = SD_DIR / "fotos"
    fotos.mkdir(exist_ok=True)
    try:
        if not (fotos / "grafica_seno.png").exists():
            img = pygame.Surface((320, 240))
            img.fill((250, 250, 252))
            for gx in range(0, 320, 40):
                pygame.draw.line(img, (220, 224, 230), (gx, 0), (gx, 240))
            for gy in range(0, 240, 40):
                pygame.draw.line(img, (220, 224, 230), (0, gy), (320, gy))
            pygame.draw.line(img, (90, 90, 100), (0, 120), (320, 120), 2)
            pts = [(x, 120 - 90 * math.sin(x / 320 * 4 * math.pi)) for x in range(320)]
            pygame.draw.lines(img, (40, 120, 230), False, pts, 3)
            pts = [(x, 120 - 90 * math.cos(x / 320 * 4 * math.pi)) for x in range(320)]
            pygame.draw.lines(img, (230, 90, 60), False, pts, 3)
            pygame.image.save(img, str(fotos / "grafica_seno.png"))
        if not (fotos / "mandelbrot.png").exists():
            w, h = 240, 180
            img = pygame.Surface((w, h))
            for py_ in range(h):
                for px in range(w):
                    c = complex(-2.2 + 3.0 * px / w, -1.1 + 2.2 * py_ / h)
                    z, n = 0j, 0
                    while abs(z) <= 2 and n < 40:
                        z, n = z * z + c, n + 1
                    k = n / 40
                    img.set_at((px, py_), (int(255 * k ** 0.5), int(140 * k), int(80 + 175 * (1 - k)) if n < 40 else 0))
            pygame.image.save(img, str(fotos / "mandelbrot.png"))
    except Exception as e:
        print("No se pudieron crear las fotos de ejemplo:", e)


# =============================================================================
#  Bucle principal
# =============================================================================
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


def main():
    pygame.init()
    ensure_sd()
    pygame.display.set_caption("ESP32 SciCalc — simulador")
    info = pygame.display.Info()
    scale = min(1.0, (info.current_h - 100) / BASE_H, (info.current_w - 40) / BASE_W)
    win = pygame.display.set_mode((int(BASE_W * scale), int(BASE_H * scale)), pygame.RESIZABLE)
    sim = Simulator()
    clock = pygame.time.Clock()
    mouse_key = None

    def to_base(pos):
        w, h = win.get_size()
        sc = min(w / BASE_W, h / BASE_H)
        ox, oy = (w - BASE_W * sc) / 2, (h - BASE_H * sc) / 2
        return ((pos[0] - ox) / sc, (pos[1] - oy) / sc)

    running = True
    while running:
        dt = clock.tick(30) / 1000.0
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.VIDEORESIZE:
                win = pygame.display.set_mode(ev.size, pygame.RESIZABLE)
            elif ev.type == pygame.MOUSEMOTION:
                sim.hover = sim.key_at(to_base(ev.pos))
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                mouse_key = sim.key_at(to_base(ev.pos))
                if mouse_key:
                    sim.press(mouse_key)
            elif ev.type == pygame.KEYDOWN:
                hit = PC_KEYS.get(ev.key)
                # La consola recibe letras del teclado del PC directamente
                if (not hit and getattr(sim.current, "accepts_text", False) and not sim.modals
                        and not sim.booting and ev.unicode and ev.unicode.isprintable()):
                    sim.current.type_char(ev.unicode)
                    continue
                if not hit and ev.unicode:
                    ch = ev.unicode.lower() if ev.unicode not in "!" else ev.unicode
                    hit = (ch, None) if ch.isdigit() else PC_CHARS.get(ch)
                if hit:
                    k, sh = hit
                    if sh:
                        sim.press(k, force_shift=True)
                    else:
                        sim.press(k)
        sim.update(dt)
        frame = sim.render()
        w, h = win.get_size()
        sc = min(w / BASE_W, h / BASE_H)
        img = pygame.transform.smoothscale(frame, (int(BASE_W * sc), int(BASE_H * sc)))
        win.fill((18, 20, 24))
        win.blit(img, ((w - img.get_width()) // 2, (h - img.get_height()) // 2))
        pygame.display.flip()

    if sim.current and hasattr(sim.current, "on_exit"):
        sim.current.on_exit()
    pygame.quit()


if __name__ == "__main__":
    main()
