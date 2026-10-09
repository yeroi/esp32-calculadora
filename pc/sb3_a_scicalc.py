#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 sb3_a_scicalc.py — Prepara un proyecto de Scratch 3 (.sb3) para la calculadora
===============================================================================
 La calculadora no puede abrir un .sb3 directamente (es un ZIP con disfraces
 SVG/PNG grandes y un project.json pensado para un PC). Este programa, en el PC:

   1. Pasa cada disfraz (SVG, PNG, JPG) a un PNG pequeño, ya escalado a la
      pantalla de la calculadora (el escenario de 480x360 se ve a 288x216).
   2. Simplifica project.json: quita lo que la calculadora no usa (sonidos,
      comentarios, posiciones de bloques...) y numera los bloques.
   3. Asigna las teclas de Scratch a teclas de la calculadora.
   4. Escribe un lanzador <nombre>.py: se abre desde el modo Python.

 Uso (desde la raíz del proyecto o desde la carpeta pc, da igual):
     python sb3_a_scicalc.py juego.sb3                 -> simulador/sd/scratch/<nombre>/
     python sb3_a_scicalc.py juego.sb3 RUTA_DE_LA_SD   -> RUTA/scratch/<nombre>/

 Después copia la carpeta a la MicroSD (o usa la carpeta sd/ del simulador).
 El intérprete es /lib/scratch.py (va incluido en la carpeta sd/ del simulador).

 Requisitos: pip install pygame-ce resvg-py
   resvg-py dibuja los SVG completos (muchos disfraces de Scratch llevan
   imágenes PNG incrustadas, que el lector SVG de pygame ignora).
===============================================================================
"""
import io
import json
import os
import re
import sys
import zipfile
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")      # sin ventana
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")      # sin sonido
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
try:
    import pygame
except ImportError:
    print("Falta pygame. Instálalo con:  pip install pygame-ce")
    sys.exit(1)

try:
    import resvg_py                    # SVG completos (con imágenes incrustadas)
except ImportError:
    resvg_py = None

HERE = Path(__file__).resolve().parent         # carpeta pc/
REPO = HERE.parent                             # raíz del proyecto
STAGE_SCALE = 0.6           # 480x360 -> 288x216 (cabe en los 320x218 del script)
MAX_COSTUME_PX = 288        # ningún disfraz más grande que el escenario
FORMAT_VERSION = 1

HATS = {"event_whenflagclicked", "event_whenkeypressed", "event_whenbroadcastreceived",
        "event_whenbackdropswitchesto", "control_start_as_clone",
        "event_whenthisspriteclicked", "event_whenstageclicked", "event_whengreaterthan"}

# Teclas de Scratch -> teclas de la calculadora (las flechas y el espacio,
# fijas; WASD también van a las flechas si el juego no usa las flechas).
FIXED_KEYS = {
    "up arrow": ["UP"], "down arrow": ["DOWN"], "left arrow": ["LEFT"], "right arrow": ["RIGHT"],
    "space": ["EXE"], "enter": ["EXE"],
}
FREE_KEYS = ["SIN", "COS", "TAN", "POW", "LN", "SQRT", "LP", "RP", "MUL", "DIV", "ADD", "SUB",
             ".", "DEL"]
KEY_LABELS = {"UP": "▲", "DOWN": "▼", "LEFT": "◄", "RIGHT": "►", "EXE": "EXE", "DEL": "DEL",
              "SIN": "sin", "COS": "cos", "TAN": "tan", "POW": "xʸ", "LN": "ln", "SQRT": "√",
              "LP": "(", "RP": ")", "MUL": "×", "DIV": "÷", "ADD": "+", "SUB": "−", ".": "."}


def slug(text):
    s = re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_").lower()
    return s[:24] or "proyecto"


# -----------------------------------------------------------------------------
#  Disfraces
# -----------------------------------------------------------------------------
def load_costume(data, fmt, w_hint, h_hint):
    """Devuelve una Surface de pygame (con alfa) a la resolución pedida."""
    if fmt == "svg":
        if w_hint and h_hint and hasattr(pygame.image, "load_sized_svg"):
            return pygame.image.load_sized_svg(io.BytesIO(data), (w_hint, h_hint))
        return pygame.image.load(io.BytesIO(data), "x.svg")
    return pygame.image.load(io.BytesIO(data), "x." + fmt)


def convert_costume(zf, c, out_png):
    """Convierte un disfraz. Devuelve (ancho, alto, centro_x, centro_y) en px de salida."""
    fmt = c.get("dataFormat", "png").lower()
    name = c.get("md5ext") or (c["assetId"] + "." + fmt)
    data = zf.read(name)
    res = c.get("bitmapResolution", 1) or 1
    k = STAGE_SCALE / res                      # px del disfraz -> px de pantalla
    if fmt == "svg" and resvg_py is not None:
        return convert_svg_resvg(data, c, k, out_png)
    base = load_costume(data, fmt, 0, 0)
    w, h = base.get_size()
    tw, th = max(1, round(w * k)), max(1, round(h * k))
    if max(tw, th) > MAX_COSTUME_PX:            # demasiado grande: se reduce más
        f = MAX_COSTUME_PX / max(tw, th)
        tw, th, k = max(1, round(tw * f)), max(1, round(th * f)), k * f
    if fmt == "svg":                           # vector: se rasteriza ya al tamaño final
        img = load_costume(data, fmt, tw, th)
    else:
        img = pygame.transform.smoothscale(base.convert_alpha(), (tw, th))
    pygame.image.save(img, str(out_png))
    return tw, th, round(c.get("rotationCenterX", w / 2) * k, 2), round(c.get("rotationCenterY", h / 2) * k, 2)


def _resvg(svg_text, zoom):
    out = resvg_py.svg_to_bytes(svg_string=svg_text, zoom=zoom)
    return pygame.image.load(io.BytesIO(bytes(out)), "x.png")


def convert_svg_resvg(data, c, k, out_png):
    """SVG con resvg: respeta degradados, textos e imágenes incrustadas."""
    svg = data.decode("utf-8", "replace")
    img = _resvg(svg, k)
    tw, th = img.get_size()
    if max(tw, th) > MAX_COSTUME_PX:           # demasiado grande: se reduce más
        f = MAX_COSTUME_PX / max(tw, th)
        k *= f
        img = _resvg(svg, k)
        tw, th = img.get_size()
    pygame.image.save(img, str(out_png))
    w, h = tw / k, th / k
    return tw, th, round(c.get("rotationCenterX", w / 2) * k, 2), round(c.get("rotationCenterY", h / 2) * k, 2)


def find_path(p, must_exist=True):
    """Acepta rutas relativas a la carpeta actual, a pc/ o a la raíz del proyecto."""
    p = Path(p)
    if p.is_absolute() or p.exists():
        return p
    for base in (HERE, REPO):
        for cand in (base / p, base / Path(*p.parts[1:]) if len(p.parts) > 1 else None):
            if cand is not None and cand.exists():
                return cand
    if must_exist:
        print(f"No encuentro '{p}'. Pon la ruta completa al .sb3 (entre comillas si tiene espacios).")
        sys.exit(1)
    return REPO / p


# -----------------------------------------------------------------------------
#  Bloques
# -----------------------------------------------------------------------------
class TargetConverter:
    def __init__(self, target, keys_used):
        self.t = target
        self.blocks = {k: v for k, v in target.get("blocks", {}).items() if isinstance(v, dict)}
        self.index = {}
        self.out = []
        self.keys_used = keys_used
        self.procs = {}
        self.hats = []

    def literal_of_shadow(self, bid):
        """Bloque 'sombra' (menús y números): su valor como literal."""
        b = self.blocks.get(bid)
        if not b:
            return None
        for name, val in b.get("fields", {}).items():
            return val[0]
        return None

    def conv_input(self, value):
        v = value[1] if len(value) > 1 else None
        if v is None:
            return None
        if isinstance(v, list):
            kind = v[0]
            if kind in (4, 5, 6, 7, 8, 9, 10, 11):
                return ["l", v[1]]
            if kind == 12:
                return ["v", v[2]]
            if kind == 13:
                return ["L", v[2]]
            return None
        b = self.blocks.get(v)
        if b is None:
            return None
        if b.get("shadow"):
            return ["l", self.literal_of_shadow(v)]
        return ["b", self.idx(v)]

    def idx(self, bid):
        if bid not in self.index:
            self.index[bid] = len(self.out)
            self.out.append(None)
            self.out[self.index[bid]] = self.conv_block(bid)
        return self.index[bid]

    def conv_block(self, bid):
        b = self.blocks[bid]
        op = b["opcode"]
        nxt = b.get("next")
        inputs = {}
        for name, val in b.get("inputs", {}).items():
            if op == "procedures_definition" or name == "custom_block":
                continue
            c = self.conv_input(val)
            if c is not None:
                inputs[name] = c
        fields = {}
        for name, val in b.get("fields", {}).items():
            fields[name] = val[1] if (name in ("VARIABLE", "LIST") and len(val) > 1 and val[1]) else val[0]
        if op in ("event_whenkeypressed",):
            self.keys_used.add(str(fields.get("KEY_OPTION", "")).lower())
        if op == "sensing_keypressed":
            k = inputs.get("KEY_OPTION")
            if k and k[0] == "l":
                self.keys_used.add(str(k[1]).lower())
        extra = None
        if op == "procedures_call":
            extra = b.get("mutation", {}).get("proccode")
        # El siguiente bloque se numera después (cola, sin recursión profunda)
        block = [op, -1, inputs, fields, extra]
        if nxt:
            block[1] = self.idx(nxt)
        return block

    def convert(self):
        for bid, b in self.blocks.items():
            if not b.get("topLevel"):
                continue
            op = b["opcode"]
            if op == "procedures_definition":
                proto_id = b.get("inputs", {}).get("custom_block", [None, None])[1]
                proto = self.blocks.get(proto_id, {})
                m = proto.get("mutation", {})
                ids = json.loads(m.get("argumentids", "[]") or "[]")
                names = json.loads(m.get("argumentnames", "[]") or "[]")
                body = self.idx(b["next"]) if b.get("next") else -1
                self.procs[m.get("proccode", "")] = [body, ids, names, str(m.get("warp")) == "true"]
            elif op in HATS:
                fields = b.get("fields", {})
                key = None
                for f in ("KEY_OPTION", "BROADCAST_OPTION", "BACKDROP", "WHENGREATERTHANMENU"):
                    if f in fields:
                        key = fields[f][0]
                if op == "event_whenkeypressed":
                    self.keys_used.add(str(key).lower())
                body = self.idx(b["next"]) if b.get("next") else -1
                if body >= 0:
                    self.hats.append([op, key, body])
        return self.out


# 8 4 6 2 mueven el ratón virtual y 5 es el clic: no se usan como teclas de Scratch
MOUSE_KEYS = ("8", "4", "6", "2", "5")


def build_keymap(keys_used, preset=None):
    """Teclas de Scratch -> teclas de la calculadora.
    Si se acaban las teclas libres se usan combinaciones SHIFT+tecla ("S:x").
    'preset' (de un perfil) fija algunas teclas antes de repartir el resto."""
    used = {k for k in keys_used if k and k != "any"}
    km = {}
    taken = set(MOUSE_KEYS) | {"S:EXE"}            # SHIFT+EXE: menú de la calculadora
    for k, ck in (preset or {}).items():
        km[k] = list(ck)
        taken.update(ck)
    for k in used:
        if k in km:
            continue
        if k in FIXED_KEYS:
            km[k] = FIXED_KEYS[k]
            taken.update(FIXED_KEYS[k])
        elif len(k) == 1 and k.isdigit() and k not in MOUSE_KEYS:
            km[k] = [k]
            taken.add(k)
    wasd = {"w": "UP", "a": "LEFT", "s": "DOWN", "d": "RIGHT"}
    free = [f for f in FREE_KEYS if f not in taken]
    combos = [c for c in ["S:" + d for d in "0123456789"] + ["S:" + f for f in FREE_KEYS]
              if c not in taken]
    # Primero los dígitos del ratón (SHIFT+ese dígito, fácil de recordar)
    for k in sorted(used):
        if k in MOUSE_KEYS and k not in km:
            km[k] = ["S:" + k]
            if "S:" + k in combos:
                combos.remove("S:" + k)
    for k in sorted(used):
        if k in km:
            continue
        if k in wasd:                       # WASD = flechas (en Scratch suelen ser lo mismo)
            km[k] = [wasd[k]]
        elif free:
            km[k] = [free.pop(0)]
        elif combos:
            km[k] = [combos.pop(0)]
    return km


def key_label(c):
    if c.startswith("S:"):
        return "SHIFT+" + KEY_LABELS.get(c[2:], c[2:])
    return KEY_LABELS.get(c, c)


# -----------------------------------------------------------------------------
def convert(sb3_path, sd_root):
    sys.setrecursionlimit(20000)               # guiones muy largos
    pygame.display.init()
    pygame.display.set_mode((1, 1))            # necesario para convert_alpha()
    sb3_path = find_path(sb3_path)
    sd_root = find_path(sd_root, must_exist=False)
    if resvg_py is None:
        print("  aviso: falta resvg-py; los SVG con imágenes incrustadas saldrán incompletos.")
        print("         Instálalo con:  pip install resvg-py")
    zf = zipfile.ZipFile(sb3_path)
    project = json.loads(zf.read("project.json").decode("utf-8"))
    name = slug(Path(sb3_path).stem)
    root = Path(sd_root)
    # Vale tanto la raíz de la SD como su carpeta "scratch"
    out_dir = (root if root.name.lower() == "scratch" else root / "scratch") / name
    img_dir = out_dir / "img"
    img_dir.mkdir(parents=True, exist_ok=True)

    keys_used = set()
    targets_out = []
    total_blocks = 0
    for ti, t in enumerate(project["targets"]):
        tc = TargetConverter(t, keys_used)
        blocks = tc.convert()
        total_blocks += len(blocks)
        costumes = []
        for ci, c in enumerate(t.get("costumes", [])):
            png = img_dir / f"{ti}_{ci}.png"
            try:
                w, h, cx, cy = convert_costume(zf, c, png)
            except Exception as e:            # disfraz vacío o ilegible: transparente
                print(f"  aviso: disfraz '{c.get('name')}' de '{t['name']}' vacío o ilegible "
                      f"({e}): se deja transparente")
                surf = pygame.Surface((2, 2), pygame.SRCALPHA)
                surf.fill((0, 0, 0, 0))
                pygame.image.save(surf, str(png))
                w, h, cx, cy = 2, 2, 1, 1
            costumes.append([c.get("name", str(ci)), f"img/{png.name}", w, h, cx, cy])
        targets_out.append({
            "nombre": t["name"],
            "escenario": bool(t.get("isStage")),
            "vars": {vid: [v[0], v[1]] for vid, v in t.get("variables", {}).items()},
            "listas": {lid: [l[0], l[1]] for lid, l in t.get("lists", {}).items()},
            "difusiones": list(t.get("broadcasts", {}).values()),
            "disfraces": costumes,
            "disfraz": t.get("currentCostume", 0),
            "x": t.get("x", 0), "y": t.get("y", 0),
            "dir": t.get("direction", 90), "tam": t.get("size", 100),
            "visible": t.get("visible", True),
            "giro": t.get("rotationStyle", "all around"),
            "capa": t.get("layerOrder", 0),
            "bloques": blocks,
            "guiones": tc.hats,
            "procs": tc.procs,
        })
    monitors = []
    for m in project.get("monitors", []):
        if m.get("visible") and m.get("opcode") == "data_variable":
            monitors.append([m.get("id"), m["params"]["VARIABLE"], m.get("spriteName"),
                             m.get("x", 0), m.get("y", 0), m.get("mode", "default")])

    # Perfil de controles para este juego (pc/perfiles/*.json), si lo hay
    profile = {}
    for pf in sorted((HERE / "perfiles").glob("*.json")):
        try:
            data_pf = json.loads(pf.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if name.startswith(data_pf.get("coincide", "\0")):
            profile = data_pf
            print(f"  perfil de controles: {pf.name}")
    keymap = build_keymap(keys_used, profile.get("teclas"))
    data = {"v": FORMAT_VERSION, "nombre": Path(sb3_path).stem, "escala": STAGE_SCALE,
            "teclas": keymap, "objetos": targets_out, "monitores": monitors}
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    (out_dir / "proyecto.json").write_text(text, encoding="utf-8")

    # controles.json: editable a mano; el intérprete lo lee al arrancar
    controls = {
        "teclas": keymap,
        "menu": profile.get("menu", []),
        "guardar": profile.get("guardar"),
        "tras_guardar": profile.get("tras_guardar"),
        "correr": profile.get("correr") or ({"tecla": "", "doble_toque": True} if "" in keys_used else None),
        "pantalla": profile.get("pantalla", "estirar"),
        "rendimiento": profile.get("rendimiento", "normal"),
    }
    (out_dir / "controles.json").write_text(json.dumps(controls, ensure_ascii=False, indent=1),
                                           encoding="utf-8")

    launcher = out_dir / f"{name}.py"
    launcher.write_text(
        f"# {Path(sb3_path).stem} — proyecto de Scratch (generado por sb3_a_scicalc.py)\n"
        "# Necesita el intérprete /lib/scratch.py.  AC sale.\n"
        "from scratch import ejecutar\n"
        "ejecutar(\"proyecto.json\")\n", encoding="utf-8")

    lines = [f"{Path(sb3_path).stem} (Scratch)", "", "Teclas:"]
    for sk, ck in sorted(keymap.items()):
        lines.append(f"  {sk:<12} -> {', '.join(key_label(c) for c in ck)}")
    if controls["correr"]:
        lines.append("  correr       -> doble toque rápido en ◄ o ►")
    lines.append("  ratón        -> 8 4 6 2 mueven el puntero · 5 = clic")
    lines.append("  menú         -> SHIFT+EXE" + (" o " + ", ".join(key_label(c) for k in controls["menu"]
                                                                  for c in keymap.get(k, []))
                                                if controls["menu"] else "")
                 + " (guardar, pantalla, rendimiento...)")
    lines.append("  AC           -> salir")
    (out_dir / "LEEME.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    kb = len(text.encode("utf-8")) / 1024
    print(f"Listo: {out_dir}")
    print(f"  {len(targets_out)} objetos · {total_blocks} bloques · proyecto.json {kb:.1f} KB")
    for line in lines[2:]:
        print(line)
    if kb > 40:
        print("  aviso: proyecto grande; en el ESP32 sin PSRAM puede no caber en la RAM de MicroPython")
    return out_dir


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else REPO / "simulador" / "sd")
