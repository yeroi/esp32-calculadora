# =============================================================================
#  scratch.py — Intérprete de proyectos de Scratch 3 para ESP32 SciCalc
# -----------------------------------------------------------------------------
#  Ejecuta los proyectos que prepara pc/sb3_a_scicalc.py (proyecto.json + img/).
#  Compatible con MicroPython: generadores para los hilos, nada de CPython.
#
#  Cómo funciona:
#   * Cada guion es un "hilo" (un generador). En cada fotograma cada hilo
#     avanza hasta su siguiente pausa: el final de una vuelta de bucle, un
#     "esperar"... como en Scratch.
#   * El escenario de 480x360 se dibuja a 288x216 y solo se redibuja la zona
#     que cambia (scicalc.pantalla.recorte), porque no hay framebuffer.
#
#  Soportado: eventos (bandera, teclas, mensajes, clones, cambio de fondo),
#  movimiento, apariencia (disfraces, tamaño, mostrar/ocultar, decir, capas,
#  efecto fantasma), control (esperar, repetir, por siempre, si, hasta,
#  detener, clones), sensores (tecla, tocando objeto/borde, temporizador,
#  distancia, "de", preguntar con números), operadores, variables, listas y
#  bloques propios (también "sin refrescar pantalla").
#  No soportado: sonido, lápiz, ratón, colores al tocar, efectos de color.
# =============================================================================
import json
import math
import random
from scicalc import pantalla as P, teclas as K

STAGE_W, STAGE_H = 480, 360
MAX_CLONES = 300                    # el mismo límite que Scratch
WORK_MS = 25                        # tiempo de CPU por fotograma (75 % de 33 ms, como Scratch)
WARP_LIMIT = 200000                 # pasos máximos de un bloque "sin refrescar"


# ---- Conversión de valores (reglas de Scratch) --------------------------------
def num(v):
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        return 0 if v != v else v          # NaN -> 0
    try:
        s = str(v).strip()
        if not s:
            return 0
        f = float(s)
        if f != f:
            return 0
        return int(f) if ("." not in s and "e" not in s.lower() and abs(f) < 1e15) else f
    except (ValueError, TypeError):
        return 0


def is_num(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return True
    try:
        s = str(v).strip()
        if not s:
            return False
        float(s)
        return True
    except (ValueError, TypeError):
        return False


def text(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e16:
            return str(int(v))
        return str(v)
    return str(v)


def truth(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    s = str(v).lower()
    return s not in ("", "0", "false")


def compare(a, b):
    if is_num(a) and is_num(b):
        x, y = float(num(a)), float(num(b))
        return (x > y) - (x < y)
    x, y = text(a).lower(), text(b).lower()
    return (x > y) - (x < y)


# ---- Objetos (sprites, escenario y clones) ------------------------------------
class Sprite:
    COPY = ("proj", "name", "stage", "blocks", "hats", "procs", "costumes", "imgs", "costume",
            "x", "y", "dir", "size", "visible", "rot", "ghost", "original")

    def __init__(self, data, proj):
        self.changed = False
        self.had_bubble = False
        if data is None:                        # clon: lo rellena clone()
            return
        self.proj = proj
        self.name = data["nombre"]
        self.stage = data["escenario"]
        self.blocks = data["bloques"]
        self.hats = data["guiones"]
        self.procs = data["procs"]
        self.costumes = data["disfraces"]       # [nombre, ruta, w, h, cx, cy]
        self.imgs = [None] * len(self.costumes)
        self.vars = {k: v[1] for k, v in data["vars"].items()}
        self.lists = {k: list(v[1]) for k, v in data["listas"].items()}
        self.costume = data["disfraz"] % max(1, len(self.costumes))
        self.x, self.y = float(data["x"]), float(data["y"])
        self.dir = float(data["dir"])
        self.size = float(data["tam"])
        self.visible = data["visible"]
        self.rot = data["giro"]
        self.ghost = 0.0
        self.say_text = ""
        self.is_clone = False
        self.original = self
        self.alive = True
        self.drawn = None                       # rectángulo dibujado la última vez

    def clone(self):
        c = Sprite(None, None)
        for a in Sprite.COPY:                   # sin __dict__: vale en MicroPython
            setattr(c, a, getattr(self, a))
        c.alive = True
        c.vars = dict(self.vars)
        c.lists = {k: list(v) for k, v in self.lists.items()}
        c.is_clone, c.say_text, c.drawn = True, "", None
        c.original = self.original
        return c

    def img(self):
        if self.imgs[self.costume] is None:
            self.imgs[self.costume] = P.sprite(self.costumes[self.costume][1])
        return self.imgs[self.costume]

    # Caja en coordenadas de Scratch (sin tener en cuenta el giro)
    def bbox(self):
        _, _, w, h, cx, cy = self.costumes[self.costume]
        k = self.size / 100 / self.proj.scale
        left = self.x - cx * k
        top = self.y + cy * k
        return left, top - h * k, left + w * k, top     # x0, y0, x1, y1

    def screen_rect(self):
        """Rectángulo de pantalla que puede ocupar (contando el giro)."""
        if not self.visible or self.ghost >= 100:
            return None
        _, _, w, h, cx, cy = self.costumes[self.costume]
        s = self.size / 100
        sx, sy = self.proj.to_screen(self.x, self.y)
        if self.rot == "all around" and (self.dir - 90) % 360:
            r = max(math.sqrt(cx * cx + cy * cy), math.sqrt((w - cx) ** 2 + cy * cy),
                    math.sqrt(cx * cx + (h - cy) ** 2), math.sqrt((w - cx) ** 2 + (h - cy) ** 2)) * s
            return (int(sx - r) - 1, int(sy - r) - 1, int(2 * r) + 3, int(2 * r) + 3)
        x0, y0 = sx - cx * s, sy - cy * s
        if self.rot == "left-right" and self.dir < 0:
            x0 = sx - (w - cx) * s
        return (int(x0) - 1, int(y0) - 1, int(w * s) + 3, int(h * s) + 3)

    def draw(self):
        if not self.visible or self.ghost >= 100:
            return
        _, _, w, h, cx, cy = self.costumes[self.costume]
        sx, sy = self.proj.to_screen(self.x, self.y)
        ang, flip = 0, False
        if self.rot == "all around":
            ang = self.dir - 90
        elif self.rot == "left-right":
            flip = self.dir < 0
        P.dibujar(self.img(), sx, sy, self.size / 100, flip, ang, (cx, cy))

    def set_costume(self, v):
        n = len(self.costumes)
        if not n:
            return
        if isinstance(v, str):
            for i, c in enumerate(self.costumes):
                if c[0] == v:
                    self.costume = i
                    return
            if self.stage:
                if v == "next backdrop":
                    self.costume = (self.costume + 1) % n
                    return
                if v == "previous backdrop":
                    self.costume = (self.costume - 1) % n
                    return
                if v == "random backdrop":
                    self.costume = random.randint(0, n - 1)
                    return
            elif v == "next costume":
                self.costume = (self.costume + 1) % n
                return
            elif v == "previous costume":
                self.costume = (self.costume - 1) % n
                return
            if not is_num(v):
                return
        i = int(round(num(v))) - 1
        self.costume = i % n

    def fence(self):
        # Como Scratch: el objeto no puede salirse del todo del escenario
        x0, y0, x1, y1 = self.bbox()
        inset = min(15, (x1 - x0) / 2, (y1 - y0) / 2)
        dx = dy = 0
        if x1 < -240 + inset:
            dx = -240 + inset - x1
        elif x0 > 240 - inset:
            dx = 240 - inset - x0
        if y1 < -180 + inset:
            dy = -180 + inset - y1
        elif y0 > 180 - inset:
            dy = 180 - inset - y0
        self.x += dx
        self.y += dy


class Ctx:
    """Contexto de un hilo: objeto que lo ejecuta y argumentos de bloques propios."""
    def __init__(self, sp, thread):
        self.sp = sp
        self.thread = thread
        self.args = [{}]
        self.warp = 0


class Thread:
    def __init__(self, proj, sp, hat, body):
        self.sp, self.hat, self.done = sp, hat, False
        self.ctx = Ctx(sp, self)
        self.gen = proj.run(self.ctx, body)


class StopAll(Exception):
    pass


class StopScript(Exception):
    """'detener este programa': dentro de un bloque propio solo sale de él (return)."""
    pass


class StopThread(Exception):
    """Acaba el hilo entero (p. ej. 'eliminar este clon')."""
    pass


# ---- Proyecto -------------------------------------------------------------------
class Project:
    def __init__(self, path):
        with open(path) as f:
            data = json.load(f)
        self.scale = data["escala"]
        self.keymap = data.get("teclas", {})
        self.ox = (P.ANCHO - STAGE_W * self.scale) / 2
        self.oy = (P.ALTO - STAGE_H * self.scale) / 2
        self.sprites = [Sprite(d, self) for d in data["objetos"]]
        self.names = {}                          # id de variable -> nombre
        for d in data["objetos"]:
            for vid, v in d["vars"].items():
                self.names[vid] = v[0]
        self.stage = [s for s in self.sprites if s.stage][0]
        order = sorted([(d["capa"], i) for i, d in enumerate(data["objetos"]) if not d["escenario"]])
        self.layers = [self.sprites[i] for _, i in order]      # de atrás adelante
        self.by_name = {s.name: s for s in self.sprites}
        self.monitors = data.get("monitores", [])
        self.threads = []
        self.timer0 = K.ms()
        self.now = K.ms()
        self.clones = 0
        self.answer = ""
        self.asking = None
        self.dirty_all = True
        self.dirty = []
        self.mon_text = {}
        self.held = set()
        self.redraw = False                      # algo visible cambió en esta vuelta
        # Ratón virtual: 8 4 6 2 lo mueven, 5 es el botón
        self.mouse = [0.0, 0.0]
        self.mouse_down = False
        self.mouse_t = 0                         # ms que lleva moviéndose (acelera)
        self.mouse_drawn = None
        self.taps = {}                           # "S:x" (SHIFT+tecla) -> válido hasta (ms)
        self.uses_mouse = self._uses_mouse()
        self.unsupported = set()
        self.S = {}
        self.R = {}
        self._register()

    def _uses_mouse(self):
        ops = ("sensing_mousex", "sensing_mousey", "sensing_mousedown",
               "event_whenthisspriteclicked", "event_whenstageclicked")
        for sp in self.sprites:
            for h in sp.hats:
                if h[0] in ops:
                    return True
            for b in sp.blocks:
                if b[0] in ops:
                    return True
                for inp in b[2].values():
                    if inp[0] == "l" and inp[1] == "_mouse_":
                        return True
        return False

    # ---- coordenadas ------------------------------------------------------------
    def to_screen(self, x, y):
        return self.ox + (x + 240) * self.scale, self.oy + (180 - y) * self.scale

    # ---- variables ---------------------------------------------------------------
    def var_get(self, sp, vid):
        if vid in sp.vars:
            return sp.vars[vid]
        return self.stage.vars.get(vid, 0)

    def var_set(self, sp, vid, value):
        if vid in sp.vars:
            sp.vars[vid] = value
        else:
            self.stage.vars[vid] = value

    def lst(self, sp, lid):
        if lid in sp.lists:
            return sp.lists[lid]
        return self.stage.lists.setdefault(lid, [])

    # ---- evaluación ------------------------------------------------------------------
    def ev(self, ctx, b, name, default=0):
        inp = b[2].get(name)
        if inp is None:
            return default
        kind, v = inp
        if kind == "l":
            return v
        if kind == "v":
            return self.var_get(ctx.sp, v)
        if kind == "L":
            items = self.lst(ctx.sp, v)
            sep = "" if all(len(text(i)) == 1 for i in items) else " "
            return sep.join(text(i) for i in items)
        rb = ctx.sp.blocks[v]
        f = self.R.get(rb[0])
        if f is None:
            self.unsupported.add(rb[0])
            return 0
        return f(ctx, rb)

    def field(self, b, name, default=""):
        return b[3].get(name, default)

    # ---- hilos ------------------------------------------------------------------------
    def start_hats(self, op, key=None, sprites=None, restart=True):
        started = []
        for sp in (sprites or self.all_sprites()):
            for h_op, h_key, body in sp.hats:
                if h_op != op:
                    continue
                if key is not None and str(h_key).lower() != str(key).lower():
                    continue
                running = [t for t in self.threads if t.sp is sp and t.hat == (h_op, h_key, body)
                           and not t.done]
                if running:
                    if not restart:
                        continue
                    for t in running:
                        t.done = True
                t = Thread(self, sp, (h_op, h_key, body), body)
                self.threads.append(t)
                started.append(t)
        return started

    def all_sprites(self):
        return [self.stage] + [s for s in self.layers]

    def run(self, ctx, bid):
        """Generador que ejecuta una pila de bloques."""
        blocks = ctx.sp.blocks
        while bid is not None and bid >= 0:
            b = blocks[bid]
            f = self.S.get(b[0])
            if f is None:
                self.unsupported.add(b[0])
            else:
                g = f(ctx, b)
                if g is not None:          # bloque que espera: generador
                    yield from g
            bid = b[1]

    def sub(self, ctx, b, name):
        inp = b[2].get(name)
        if inp and inp[0] == "b":
            return self.run(ctx, inp[1])
        return None

    def loop_yield(self, ctx):
        # Dentro de un bloque "sin refrescar" no se cede el turno
        return not ctx.warp

    # =============================================================================
    #  Bloques
    # =============================================================================
    def _register(self):
        S, R = self.S, self.R

        # ---------- eventos ----------
        def broadcast(ctx, b):
            self.start_hats("event_whenbroadcastreceived", text(self.ev(ctx, b, "BROADCAST_INPUT")))
        S["event_broadcast"] = broadcast

        def broadcast_wait(ctx, b):
            ts = self.start_hats("event_whenbroadcastreceived", text(self.ev(ctx, b, "BROADCAST_INPUT")))

            def g():
                while any(not t.done for t in ts):
                    yield
            return g()
        S["event_broadcastandwait"] = broadcast_wait

        # ---------- movimiento ----------
        def moved(sp):
            sp.fence()
            self.mark(sp)

        def move(ctx, b):
            sp = ctx.sp
            n = num(self.ev(ctx, b, "STEPS"))
            r = math.radians(90 - sp.dir)
            sp.x += n * math.cos(r)
            sp.y += n * math.sin(r)
            moved(sp)
        S["motion_movesteps"] = move

        def set_dir(sp, d):
            d = ((d + 179) % 360) - 179
            sp.dir = d
            self.mark(sp)
        S["motion_turnright"] = lambda ctx, b: set_dir(ctx.sp, ctx.sp.dir + num(self.ev(ctx, b, "DEGREES")))
        S["motion_turnleft"] = lambda ctx, b: set_dir(ctx.sp, ctx.sp.dir - num(self.ev(ctx, b, "DEGREES")))
        S["motion_pointindirection"] = lambda ctx, b: set_dir(ctx.sp, num(self.ev(ctx, b, "DIRECTION")))

        def target_xy(ctx, name):
            if name == "_random_":
                return random.randint(-240, 240), random.randint(-180, 180)
            if name == "_mouse_":
                return self.mouse[0], self.mouse[1]
            o = self.by_name.get(name)
            return (o.x, o.y) if o else (ctx.sp.x, ctx.sp.y)

        def goto(ctx, b):
            ctx.sp.x, ctx.sp.y = target_xy(ctx, text(self.ev(ctx, b, "TO")))
            moved(ctx.sp)
        S["motion_goto"] = goto

        def gotoxy(ctx, b):
            ctx.sp.x, ctx.sp.y = float(num(self.ev(ctx, b, "X"))), float(num(self.ev(ctx, b, "Y")))
            moved(ctx.sp)
        S["motion_gotoxy"] = gotoxy

        def setxy(ctx, b, attr, name, delta):
            v = float(num(self.ev(ctx, b, name)))
            setattr(ctx.sp, attr, getattr(ctx.sp, attr) + v if delta else v)
            moved(ctx.sp)
        S["motion_changexby"] = lambda ctx, b: setxy(ctx, b, "x", "DX", True)
        S["motion_setx"] = lambda ctx, b: setxy(ctx, b, "x", "X", False)
        S["motion_changeyby"] = lambda ctx, b: setxy(ctx, b, "y", "DY", True)
        S["motion_sety"] = lambda ctx, b: setxy(ctx, b, "y", "Y", False)

        def glide_to(ctx, x1, y1, secs):
            sp = ctx.sp
            x0, y0 = sp.x, sp.y
            t0 = self.now
            dur = max(0.0, secs) * 1000

            def g():
                while True:
                    k = 1.0 if dur <= 0 else min(1.0, (self.now - t0) / dur)
                    sp.x, sp.y = x0 + (x1 - x0) * k, y0 + (y1 - y0) * k
                    moved(sp)
                    if k >= 1:
                        return
                    yield
            return g()
        S["motion_glidesecstoxy"] = lambda ctx, b: glide_to(
            ctx, float(num(self.ev(ctx, b, "X"))), float(num(self.ev(ctx, b, "Y"))),
            num(self.ev(ctx, b, "SECS")))

        def glide_obj(ctx, b):
            x, y = target_xy(ctx, text(self.ev(ctx, b, "TO")))
            return glide_to(ctx, x, y, num(self.ev(ctx, b, "SECS")))
        S["motion_glideto"] = glide_obj

        def point_towards(ctx, b):
            name = text(self.ev(ctx, b, "TOWARDS"))
            if name == "_random_":
                set_dir(ctx.sp, random.randint(-180, 180))
                return
            x, y = target_xy(ctx, name)
            dx, dy = x - ctx.sp.x, y - ctx.sp.y
            if dx or dy:
                set_dir(ctx.sp, 90 - math.degrees(math.atan2(dy, dx)))
        S["motion_pointtowards"] = point_towards

        def bounce(ctx, b):
            sp = ctx.sp
            x0, y0, x1, y1 = sp.bbox()
            hit = False
            if x0 < -240 or x1 > 240:
                sp.dir = -sp.dir
                sp.x += (-240 - x0) if x0 < -240 else (240 - x1)
                hit = True
            if y0 < -180 or y1 > 180:
                sp.dir = 180 - sp.dir
                sp.y += (-180 - y0) if y0 < -180 else (180 - y1)
                hit = True
            if hit:
                set_dir(sp, sp.dir)
                moved(sp)
        S["motion_ifonedgebounce"] = bounce

        def rot_style(ctx, b):
            ctx.sp.rot = self.field(b, "STYLE", "all around")
            self.mark(ctx.sp)
        S["motion_setrotationstyle"] = rot_style
        R["motion_xposition"] = lambda ctx, b: round(ctx.sp.x, 8)
        R["motion_yposition"] = lambda ctx, b: round(ctx.sp.y, 8)
        R["motion_direction"] = lambda ctx, b: ctx.sp.dir

        # ---------- apariencia ----------
        def say(ctx, b, secs_name=None):
            sp = ctx.sp
            sp.say_text = text(self.ev(ctx, b, "MESSAGE"))
            self.mark(sp)
            if secs_name is None:
                return None
            end = self.now + num(self.ev(ctx, b, secs_name)) * 1000

            def g():
                while self.now < end:
                    yield
                sp.say_text = ""
                self.mark(sp)
            return g()
        S["looks_say"] = lambda ctx, b: say(ctx, b)
        S["looks_think"] = lambda ctx, b: say(ctx, b)
        S["looks_sayforsecs"] = lambda ctx, b: say(ctx, b, "SECS")
        S["looks_thinkforsecs"] = lambda ctx, b: say(ctx, b, "SECS")

        def costume(ctx, b):
            ctx.sp.set_costume(self.ev(ctx, b, "COSTUME"))
            self.mark(ctx.sp)
        S["looks_switchcostumeto"] = costume

        def next_costume(ctx, b):
            ctx.sp.set_costume("next costume")
            self.mark(ctx.sp)
        S["looks_nextcostume"] = next_costume

        def backdrop(ctx, b, value=None):
            st = self.stage
            st.set_costume(value if value is not None else self.ev(ctx, b, "BACKDROP"))
            self.dirty_all = True
            self.start_hats("event_whenbackdropswitchesto", st.costumes[st.costume][0])
        S["looks_switchbackdropto"] = backdrop
        S["looks_nextbackdrop"] = lambda ctx, b: backdrop(ctx, b, "next backdrop")

        def size(ctx, b, delta):
            v = float(num(self.ev(ctx, b, "CHANGE" if delta else "SIZE")))
            ctx.sp.size = max(5.0, min(500.0, ctx.sp.size + v if delta else v))
            self.mark(ctx.sp)
        S["looks_changesizeby"] = lambda ctx, b: size(ctx, b, True)
        S["looks_setsizeto"] = lambda ctx, b: size(ctx, b, False)

        def effect(ctx, b, delta):
            if str(self.field(b, "EFFECT", "")).lower() != "ghost":
                return                          # solo el efecto fantasma
            v = float(num(self.ev(ctx, b, "CHANGE" if delta else "VALUE")))
            ctx.sp.ghost = max(0.0, min(100.0, ctx.sp.ghost + v if delta else v))
            self.mark(ctx.sp)
        S["looks_changeeffectby"] = lambda ctx, b: effect(ctx, b, True)
        S["looks_seteffectto"] = lambda ctx, b: effect(ctx, b, False)

        def clear_fx(ctx, b):
            ctx.sp.ghost = 0
            self.mark(ctx.sp)
        S["looks_cleargraphiceffects"] = clear_fx

        def show(ctx, b, v):
            ctx.sp.visible = v
            self.mark(ctx.sp)
        S["looks_show"] = lambda ctx, b: show(ctx, b, True)
        S["looks_hide"] = lambda ctx, b: show(ctx, b, False)

        def front_back(ctx, b):
            sp = ctx.sp
            if sp in self.layers:
                self.layers.remove(sp)
                if self.field(b, "FRONT_BACK", "front") == "front":
                    self.layers.append(sp)
                else:
                    self.layers.insert(0, sp)
                self.mark(sp)
        S["looks_gotofrontback"] = front_back

        def layers(ctx, b):
            sp = ctx.sp
            if sp not in self.layers:
                return
            n = int(num(self.ev(ctx, b, "NUM")))
            if self.field(b, "FORWARD_BACKWARD", "forward") == "backward":
                n = -n
            i = self.layers.index(sp)
            self.layers.remove(sp)
            self.layers.insert(max(0, min(len(self.layers), i + n)), sp)
            self.mark(sp)
        S["looks_goforwardbackwardlayers"] = layers

        def cos_num(ctx, b):
            sp = ctx.sp
            if self.field(b, "NUMBER_NAME", "number") == "name":
                return sp.costumes[sp.costume][0]
            return sp.costume + 1
        R["looks_costumenumbername"] = cos_num

        def bd_num(ctx, b):
            st = self.stage
            if self.field(b, "NUMBER_NAME", "number") == "name":
                return st.costumes[st.costume][0]
            return st.costume + 1
        R["looks_backdropnumbername"] = bd_num
        R["looks_size"] = lambda ctx, b: round(ctx.sp.size)

        # ---------- sonido (sin altavoz por ahora: no hace nada) ----------
        for op in ("sound_play", "sound_stopallsounds", "sound_changevolumeby", "sound_setvolumeto",
                   "sound_seteffectto", "sound_changeeffectby", "sound_cleareffects"):
            S[op] = lambda ctx, b: None
        S["sound_playuntildone"] = lambda ctx, b: None
        R["sound_volume"] = lambda ctx, b: 100

        # ---------- control ----------
        def wait(ctx, b):
            end = self.now + num(self.ev(ctx, b, "DURATION")) * 1000

            def g():
                yield
                while self.now < end:
                    yield
            return g()
        S["control_wait"] = wait

        def repeat(ctx, b):
            n = int(round(num(self.ev(ctx, b, "TIMES"))))

            def g():
                for _ in range(n):
                    s = self.sub(ctx, b, "SUBSTACK")
                    if s:
                        yield from s
                    if self.loop_yield(ctx):
                        yield
            return g()
        S["control_repeat"] = repeat

        def forever(ctx, b):
            def g():
                while True:
                    s = self.sub(ctx, b, "SUBSTACK")
                    if s:
                        yield from s
                    if self.loop_yield(ctx):
                        yield
            return g()
        S["control_forever"] = forever

        def if_(ctx, b):
            if truth(self.ev(ctx, b, "CONDITION", False)):
                return self.sub(ctx, b, "SUBSTACK")
            return None
        S["control_if"] = if_

        def if_else(ctx, b):
            name = "SUBSTACK" if truth(self.ev(ctx, b, "CONDITION", False)) else "SUBSTACK2"
            return self.sub(ctx, b, name)
        S["control_if_else"] = if_else

        def wait_until(ctx, b):
            def g():
                while not truth(self.ev(ctx, b, "CONDITION", False)):
                    yield
            return g()
        S["control_wait_until"] = wait_until

        def repeat_until(ctx, b, until=True):
            def g():
                while truth(self.ev(ctx, b, "CONDITION", False)) != until:
                    s = self.sub(ctx, b, "SUBSTACK")
                    if s:
                        yield from s
                    if self.loop_yield(ctx):
                        yield
            return g()
        S["control_repeat_until"] = repeat_until
        S["control_while"] = lambda ctx, b: repeat_until(ctx, b, False)

        def stop(ctx, b):
            opt = self.field(b, "STOP_OPTION", "all")
            if opt == "all":
                raise StopAll()
            if opt == "this script":
                raise StopScript()
            for t in self.threads:                      # "otros guiones del objeto"
                if t.sp is ctx.sp and t is not ctx.thread:
                    t.done = True
        S["control_stop"] = stop

        def create_clone(ctx, b):
            name = text(self.ev(ctx, b, "CLONE_OPTION"))
            src = ctx.sp if name == "_myself_" else self.by_name.get(name)
            if not src or src.stage or self.clones >= MAX_CLONES:
                return
            c = src.clone()
            self.clones += 1
            i = self.layers.index(src) if src in self.layers else len(self.layers) - 1
            self.layers.insert(i, c)                    # justo detrás del original
            self.mark(c)
            self.start_hats("control_start_as_clone", sprites=[c])
        S["control_create_clone_of"] = create_clone

        def delete_clone(ctx, b):
            sp = ctx.sp
            if not sp.is_clone:
                return
            if sp.drawn:
                self.dirty.append(sp.drawn)
            if sp in self.layers:
                self.layers.remove(sp)
            sp.alive = False
            self.clones -= 1
            for t in self.threads:
                if t.sp is sp:
                    t.done = True
            raise StopThread()
        S["control_delete_this_clone"] = delete_clone

        # ---------- sensores ----------
        def down(k):
            if k.startswith("S:"):                  # SHIFT+tecla: vale unos ms tras pulsarla
                return self.taps.get(k, 0) > self.now
            return k in self.held

        def key_pressed(name):
            name = str(name).lower()
            if name == "any":
                return bool(self.held - self.mouse_keys()) or any(t > self.now for t in self.taps.values())
            return any(down(k) for k in self.keymap.get(name, ()))
        R["sensing_keypressed"] = lambda ctx, b: key_pressed(self.ev(ctx, b, "KEY_OPTION"))

        def overlap(a, c):
            return a[0] < c[2] and a[2] > c[0] and a[1] < c[3] and a[3] > c[1]

        def touching(ctx, b):
            sp = ctx.sp
            if not sp.visible:
                return False
            name = text(self.ev(ctx, b, "TOUCHINGOBJECTMENU"))
            box = sp.bbox()
            if name == "_edge_":
                return box[0] < -240 or box[2] > 240 or box[1] < -180 or box[3] > 180
            if name == "_mouse_":
                mx, my = self.mouse
                return box[0] <= mx <= box[2] and box[1] <= my <= box[3]
            for o in self.layers:
                if o.original.name == name and o is not sp and o.visible and o.ghost < 100 \
                        and overlap(box, o.bbox()):
                    return True
            return False
        R["sensing_touchingobject"] = touching
        R["sensing_touchingcolor"] = lambda ctx, b: False
        R["sensing_coloristouchingcolor"] = lambda ctx, b: False
        R["sensing_timer"] = lambda ctx, b: round((self.now - self.timer0) / 1000, 3)

        def reset_timer(ctx, b):
            self.timer0 = self.now
        S["sensing_resettimer"] = reset_timer
        R["sensing_mousex"] = lambda ctx, b: round(self.mouse[0])
        R["sensing_mousey"] = lambda ctx, b: round(self.mouse[1])
        R["sensing_mousedown"] = lambda ctx, b: self.mouse_down
        R["sensing_answer"] = lambda ctx, b: self.answer
        R["sensing_username"] = lambda ctx, b: ""
        R["sensing_loudness"] = lambda ctx, b: 0

        def distance(ctx, b):
            x, y = target_xy(ctx, text(self.ev(ctx, b, "DISTANCETOMENU")))
            return math.sqrt((x - ctx.sp.x) ** 2 + (y - ctx.sp.y) ** 2)
        R["sensing_distanceto"] = distance

        def of(ctx, b):
            o = self.by_name.get(text(self.ev(ctx, b, "OBJECT")))
            prop = self.field(b, "PROPERTY", "")
            if o is None:
                return 0
            table = {"x position": o.x, "y position": o.y, "direction": o.dir,
                     "costume #": o.costume + 1, "costume name": o.costumes[o.costume][0],
                     "size": o.size, "volume": 100, "backdrop #": o.costume + 1,
                     "backdrop name": o.costumes[o.costume][0]}
            if prop in table:
                return table[prop]
            for vid, v in o.vars.items():          # variable local de ese objeto
                if vid == prop or self.var_name(o, vid) == prop:
                    return v
            return 0
        R["sensing_of"] = of

        def current(ctx, b):
            import time
            t = time.localtime()
            m = {"YEAR": 0, "MONTH": 1, "DATE": 2, "HOUR": 3, "MINUTE": 4, "SECOND": 5}
            return t[m.get(str(self.field(b, "CURRENTMENU", "YEAR")).upper(), 0)]
        R["sensing_current"] = current

        def ask(ctx, b):
            q = text(self.ev(ctx, b, "QUESTION"))
            self.asking = [q, "", False]
            self.dirty_all = True

            def g():
                while not self.asking[2]:
                    yield
                self.answer = self.asking[1]
                self.asking = None
                self.dirty_all = True
            return g()
        S["sensing_askandwait"] = ask

        # ---------- operadores ----------
        def arith(fn):
            return lambda ctx, b: fn(num(self.ev(ctx, b, "NUM1")), num(self.ev(ctx, b, "NUM2")))
        R["operator_add"] = arith(lambda a, c: a + c)
        R["operator_subtract"] = arith(lambda a, c: a - c)
        R["operator_multiply"] = arith(lambda a, c: a * c)
        R["operator_divide"] = arith(lambda a, c: (a / c) if c else (float("inf") if a > 0 else
                                                                      float("-inf") if a < 0 else 0))

        def mod(ctx, b):
            a, c = num(self.ev(ctx, b, "NUM1")), num(self.ev(ctx, b, "NUM2"))
            return 0 if c == 0 else a - c * math.floor(a / c)
        R["operator_mod"] = mod

        def rnd(ctx, b):
            f, t = self.ev(ctx, b, "FROM"), self.ev(ctx, b, "TO")
            a, c = num(f), num(t)
            if a > c:
                a, c = c, a
            if isinstance(a, int) and isinstance(c, int) and "." not in text(f) + text(t):
                return random.randint(a, c)
            return a + random.random() * (c - a)
        R["operator_random"] = rnd
        R["operator_gt"] = lambda ctx, b: compare(self.ev(ctx, b, "OPERAND1"), self.ev(ctx, b, "OPERAND2")) > 0
        R["operator_lt"] = lambda ctx, b: compare(self.ev(ctx, b, "OPERAND1"), self.ev(ctx, b, "OPERAND2")) < 0
        R["operator_equals"] = lambda ctx, b: compare(self.ev(ctx, b, "OPERAND1"), self.ev(ctx, b, "OPERAND2")) == 0
        R["operator_and"] = lambda ctx, b: truth(self.ev(ctx, b, "OPERAND1", False)) and \
            truth(self.ev(ctx, b, "OPERAND2", False))
        R["operator_or"] = lambda ctx, b: truth(self.ev(ctx, b, "OPERAND1", False)) or \
            truth(self.ev(ctx, b, "OPERAND2", False))
        R["operator_not"] = lambda ctx, b: not truth(self.ev(ctx, b, "OPERAND", False))
        R["operator_join"] = lambda ctx, b: text(self.ev(ctx, b, "STRING1", "")) + text(self.ev(ctx, b, "STRING2", ""))

        def letter(ctx, b):
            s = text(self.ev(ctx, b, "STRING", ""))
            i = int(num(self.ev(ctx, b, "LETTER"))) - 1
            return s[i] if 0 <= i < len(s) else ""
        R["operator_letter_of"] = letter
        R["operator_length"] = lambda ctx, b: len(text(self.ev(ctx, b, "STRING", "")))
        R["operator_contains"] = lambda ctx, b: text(self.ev(ctx, b, "STRING2", "")).lower() in \
            text(self.ev(ctx, b, "STRING1", "")).lower()
        R["operator_round"] = lambda ctx, b: int(math.floor(num(self.ev(ctx, b, "NUM")) + 0.5))

        def mathop(ctx, b):
            op = self.field(b, "OPERATOR", "abs")
            n = num(self.ev(ctx, b, "NUM"))
            try:
                if op == "abs": return abs(n)
                if op == "floor": return math.floor(n)
                if op == "ceiling": return math.ceil(n)
                if op == "sqrt": return math.sqrt(n)
                if op == "sin": return round(math.sin(math.radians(n)), 10)
                if op == "cos": return round(math.cos(math.radians(n)), 10)
                if op == "tan": return round(math.tan(math.radians(n)), 10)
                if op == "asin": return math.degrees(math.asin(n))
                if op == "acos": return math.degrees(math.acos(n))
                if op == "atan": return math.degrees(math.atan(n))
                if op == "ln": return math.log(n)
                if op == "log": return math.log(n) / math.log(10)
                if op == "e ^": return math.exp(n)
                if op == "10 ^": return 10 ** n
            except (ValueError, OverflowError):
                return 0
            return 0
        R["operator_mathop"] = mathop

        # ---------- variables y listas ----------
        def setvar(ctx, b):
            self.var_set(ctx.sp, self.field(b, "VARIABLE"), self.ev(ctx, b, "VALUE", ""))
        S["data_setvariableto"] = setvar

        def changevar(ctx, b):
            vid = self.field(b, "VARIABLE")
            self.var_set(ctx.sp, vid, num(self.var_get(ctx.sp, vid)) + num(self.ev(ctx, b, "VALUE")))
        S["data_changevariableby"] = changevar
        S["data_showvariable"] = lambda ctx, b: None
        S["data_hidevariable"] = lambda ctx, b: None
        S["data_showlist"] = lambda ctx, b: None
        S["data_hidelist"] = lambda ctx, b: None

        def L(ctx, b):
            return self.lst(ctx.sp, self.field(b, "LIST"))

        def index(ctx, b, items, name="INDEX", add=0):
            v = self.ev(ctx, b, name)
            s = text(v).lower()
            if s == "last":
                return len(items) - 1 + add
            if s in ("random", "any"):
                return random.randint(0, max(0, len(items) - 1))
            return int(num(v)) - 1

        def add(ctx, b):
            items = L(ctx, b)
            if len(items) < 200000:
                items.append(self.ev(ctx, b, "ITEM", ""))
        S["data_addtolist"] = add

        def delete(ctx, b):
            items = L(ctx, b)
            if text(self.ev(ctx, b, "INDEX")).lower() == "all":
                del items[:]
                return
            i = index(ctx, b, items)
            if 0 <= i < len(items):
                del items[i]
        S["data_deleteoflist"] = delete

        def delete_all(ctx, b):
            del L(ctx, b)[:]
        S["data_deletealloflist"] = delete_all

        def insert(ctx, b):
            items = L(ctx, b)
            i = index(ctx, b, items, add=1)
            if 0 <= i <= len(items):
                items.insert(i, self.ev(ctx, b, "ITEM", ""))
        S["data_insertatlist"] = insert

        def replace(ctx, b):
            items = L(ctx, b)
            i = index(ctx, b, items)
            if 0 <= i < len(items):
                items[i] = self.ev(ctx, b, "ITEM", "")
        S["data_replaceitemoflist"] = replace

        def item(ctx, b):
            items = L(ctx, b)
            i = index(ctx, b, items)
            return items[i] if 0 <= i < len(items) else ""
        R["data_itemoflist"] = item

        def itemnum(ctx, b):
            items = L(ctx, b)
            x = self.ev(ctx, b, "ITEM", "")
            for i, v in enumerate(items):
                if compare(v, x) == 0:
                    return i + 1
            return 0
        R["data_itemnumoflist"] = itemnum
        R["data_lengthoflist"] = lambda ctx, b: len(L(ctx, b))
        R["data_listcontainsitem"] = lambda ctx, b: any(
            compare(v, self.ev(ctx, b, "ITEM", "")) == 0 for v in L(ctx, b))

        # ---------- bloques propios ----------
        def call(ctx, b):
            proc = ctx.sp.procs.get(b[4])
            if not proc:
                return None
            body, ids, names, warp = proc
            args = {}
            for aid, aname in zip(ids, names):
                args[aname] = self.ev(ctx, b, aid, "")
            if body < 0:
                return None

            def g():
                ctx.args.append(args)
                try:
                    if warp or ctx.warp:
                        ctx.warp += 1
                        try:
                            gen = self.run(ctx, body)
                            steps = 0
                            for _ in gen:                 # sin ceder el turno
                                steps += 1
                                if steps > WARP_LIMIT:
                                    break
                        finally:
                            ctx.warp -= 1
                    else:
                        yield from self.run(ctx, body)
                except StopScript:
                    pass                    # "detener este programa" = salir del bloque propio
                finally:
                    ctx.args.pop()
            return g()
        S["procedures_call"] = call
        R["argument_reporter_string_number"] = lambda ctx, b: ctx.args[-1].get(self.field(b, "VALUE"), 0)
        R["argument_reporter_boolean"] = lambda ctx, b: ctx.args[-1].get(self.field(b, "VALUE"), False)

    def var_name(self, sp, vid):
        return self.names.get(vid, vid)

    # =============================================================================
    #  Dibujo (solo lo que cambia)
    # =============================================================================
    def mark(self, sp):
        sp.changed = True
        self.redraw = True

    def draw_all(self, clip=None):
        if clip:
            P.recorte(*clip)
        st = self.stage
        sx, sy = self.to_screen(0, 0)
        _, _, w, h, cx, cy = st.costumes[st.costume]
        P.dibujar(st.img(), sx, sy, 1, False, 0, (cx, cy))
        for sp in self.layers:
            sp.draw()
        for sp in self.layers:
            if sp.say_text and sp.visible:
                self.draw_bubble(sp)
        self.draw_monitors()
        if self.uses_mouse:
            self.draw_cursor()
        if self.asking:
            self.draw_ask()
        if clip:
            P.recorte()

    def bubble_rect(self, sp):
        r = sp.screen_rect() or (0, 0, 0, 0)
        t = sp.say_text[:30]
        w = len(t) * 6 + 8
        x = min(P.ANCHO - w - 2, max(2, r[0] + r[2] - 4))
        y = max(2, r[1] - 16)
        return (x, y, w, 14)

    def draw_bubble(self, sp):
        x, y, w, h = self.bubble_rect(sp)
        P.rect(x, y, w, h, 0xFFFFFF)
        P.marco(x, y, w, h, 0x888888)
        P.texto(sp.say_text[:30], x + 4, y + 3, 0x202020)

    def draw_monitors(self):
        for vid, label, sprite, mx, my, mode in self.monitors:
            sp = self.by_name.get(sprite, self.stage) if sprite else self.stage
            val = text(self.var_get(sp, vid))
            if sprite:
                label = sprite + ": " + label
            t = (val if mode == "large" else label + ": " + val)[:24]
            x, y = self.to_screen(mx - 240, 180 - my)
            P.rect(int(x), int(y), len(t) * 6 + 6, 12, 0xE6F0FF)
            P.texto(t, int(x) + 3, int(y) + 2, 0x202060)

    def monitor_values(self):
        out = []
        for m in self.monitors:
            sp = self.by_name.get(m[2], self.stage) if m[2] else self.stage
            out.append(text(self.var_get(sp, m[0])))
        return out

    def cursor_rect(self):
        sx, sy = self.to_screen(self.mouse[0], self.mouse[1])
        return (int(sx) - 6, int(sy) - 6, 13, 13)

    def draw_cursor(self):
        sx, sy = self.to_screen(self.mouse[0], self.mouse[1])
        sx, sy = int(sx), int(sy)
        P.rect(sx - 5, sy - 1, 11, 3, 0x000000)        # cruz negra con centro blanco
        P.rect(sx - 1, sy - 5, 3, 11, 0x000000)
        P.rect(sx - 4, sy, 9, 1, 0xFFFFFF)
        P.rect(sx, sy - 4, 1, 9, 0xFFFFFF)
        if self.mouse_down:
            P.rect(sx - 1, sy - 1, 3, 3, 0xFF3030)

    def draw_ask(self):
        q, a, _ = self.asking
        y = P.ALTO - 34
        P.rect(int(self.ox) + 4, y, int(STAGE_W * self.scale) - 8, 30, 0xFFFFFF)
        P.marco(int(self.ox) + 4, y, int(STAGE_W * self.scale) - 8, 30, 0x855CD6)
        P.texto(q[:44], int(self.ox) + 8, y + 3, 0x202020)
        P.texto("> " + a + "_   (EXE)", int(self.ox) + 8, y + 16, 0x855CD6)

    def render(self):
        # Zonas que cambian: rectángulo anterior y nuevo de cada objeto cambiado
        rects = list(self.dirty)
        self.dirty = []
        for sp in self.layers:
            if getattr(sp, "changed", False):
                sp.changed = False
                new = sp.screen_rect()
                if sp.drawn:
                    rects.append(sp.drawn)
                if new:
                    rects.append(new)
                if sp.say_text or getattr(sp, "had_bubble", False):
                    self.dirty_all = True
                sp.had_bubble = bool(sp.say_text)
                sp.drawn = new
        if self.uses_mouse:
            state = (round(self.mouse[0]), round(self.mouse[1]), self.mouse_down)
            if state != self.mouse_drawn:
                if self.mouse_drawn:
                    rects.append(self.mouse_drawn[3])
                cr = self.cursor_rect()
                rects.append(cr)
                self.mouse_drawn = state + (cr,)
        mon = self.monitor_values()
        if mon != getattr(self, "_mon", None):
            self._mon = mon
            self.dirty_all = True
        if self.dirty_all:
            self.dirty_all = False
            self.draw_all((int(self.ox), int(self.oy), int(STAGE_W * self.scale), int(STAGE_H * self.scale)))
            for sp in self.layers:
                sp.drawn = sp.screen_rect()
            return
        if not rects:
            return
        x0 = max(int(self.ox), min(r[0] for r in rects))
        y0 = max(int(self.oy), min(r[1] for r in rects))
        x1 = min(int(self.ox + STAGE_W * self.scale), max(r[0] + r[2] for r in rects))
        y1 = min(int(self.oy + STAGE_H * self.scale), max(r[1] + r[3] for r in rects))
        if x1 > x0 and y1 > y0:
            self.draw_all((x0, y0, x1 - x0, y1 - y0))

    # =============================================================================
    #  Bucle principal
    # =============================================================================
    def mouse_keys(self):
        return {"8", "4", "6", "2", "5"} if self.uses_mouse else set()

    def move_mouse(self, events):
        keys = self.held
        dx = (1 if "6" in keys else 0) - (1 if "4" in keys else 0)
        dy = (1 if "8" in keys else 0) - (1 if "2" in keys else 0)
        if dx or dy:
            self.mouse_t += 33
            # 4 px por fotograma (un toque = 4 px); manteniendo, acelera hasta 10
            speed = 4 if self.mouse_t < 500 else min(10, 4 + (self.mouse_t - 500) // 100)
            self.mouse[0] = max(-240.0, min(240.0, self.mouse[0] + dx * speed))
            self.mouse[1] = max(-180.0, min(180.0, self.mouse[1] + dy * speed))
        else:
            self.mouse_t = 0
        self.mouse_down = "5" in keys
        if any(k == "5" and not sh for k, sh in events):
            self.click()

    def click(self):
        mx, my = self.mouse
        for sp in reversed(self.layers):              # el de más arriba primero
            if sp.visible and sp.ghost < 100:
                x0, y0, x1, y1 = sp.bbox()
                if x0 <= mx <= x1 and y0 <= my <= y1:
                    self.start_hats("event_whenthisspriteclicked", sprites=[sp])
                    return
        self.start_hats("event_whenstageclicked", sprites=[self.stage])

    def input(self):
        events = K.eventos()
        self.held = set(K.pulsadas())
        for k, shift in events:
            if shift:
                self.taps["S:" + k] = self.now + 150   # SHIFT+tecla: pulsación corta
            else:
                self.held.add(k)               # un toque cuenta como pulsada este fotograma
        if self.uses_mouse and not self.asking:
            self.move_mouse(events)
        for k, shift in events:
            if self.asking:
                q = self.asking
                if k.isdigit() and len(q[1]) < 20:
                    q[1] += k
                elif k == "." and "." not in q[1]:
                    q[1] += "."
                elif k == "SUB" and not q[1]:
                    q[1] = "-"
                elif k == "DEL":
                    q[1] = q[1][:-1]
                elif k == "EXE":
                    q[2] = True
                self.dirty_all = True
                continue
            name = ("S:" + k) if shift else k
            if not shift and k in self.mouse_keys():
                continue                       # teclas del ratón: no son teclas de Scratch
            for sk, calc_keys in self.keymap.items():
                if name in calc_keys:
                    self.start_hats("event_whenkeypressed", sk, restart=False)
            self.start_hats("event_whenkeypressed", "any", restart=False)

    def step(self):
        # Como el planificador de Scratch: dentro de un fotograma se dan vueltas
        # a todos los hilos hasta que alguno cambia algo visible o se acaba el
        # tiempo (WORK_MS). Así los bucles de cálculo puro van a toda velocidad.
        self.now = K.ms()
        self.input()
        start = K.ms()
        while True:
            self.redraw = False
            for t in list(self.threads):
                if t.done:
                    continue
                try:
                    next(t.gen)
                except StopIteration:
                    t.done = True
                except (StopScript, StopThread):
                    t.done = True
            self.threads = [t for t in self.threads if not t.done]
            if self.redraw or self.dirty_all or not self.threads or K.ms() - start >= WORK_MS:
                break
            self.now = K.ms()
        self.render()
        P.mostrar()


def ejecutar(ruta):
    P.limpiar(0)
    P.texto("Cargando proyecto de Scratch...", 70, 100, 0xFFFFFF)
    P.mostrar()
    proj = Project(ruta)
    P.limpiar(0)
    proj.start_hats("event_whenflagclicked")
    try:
        while True:
            proj.step()
    except StopAll:
        pass
    if proj.unsupported:
        print("Bloques no soportados:", ", ".join(sorted(proj.unsupported)))
    P.texto("Fin del programa (AC para salir)", 70, 205, 0xFFFFFF, 0)
    while True:
        P.mostrar()
