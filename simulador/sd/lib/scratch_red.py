# =============================================================================
#  scratch_red.py — multijugador para juegos de Scratch que no lo traen
# -----------------------------------------------------------------------------
#  Lo usa /lib/scratch.py cuando el controles.json del juego tiene una sección
#  "multijugador" (la pone el convertidor a partir de pc/perfiles/). Ejemplo,
#  Paper Minecraft:
#      "mundo":   ["_Level", "_Light"]   listas que se le envían al que se une
#      "bloques": "_Level"               lista que se sincroniza casilla a casilla
#      "x", "y":  "_x", "_y"             posición del jugador (variables del escenario)
#      "camara":  ["_ScrX", "_ScrY"]     desplazamiento de la cámara (si lo hay)
#      "casilla": 40                     unidades de Scratch por casilla
#      "partes":  ["Steve Legs2", ...]   objetos que forman al jugador
#
#  Cómo funciona (todo con scicalc.red, en la sala del juego):
#    * El primero que se conecta ABRE la partida: sube las listas del mundo
#      en trozos ("m:lista:n") y después la variable "mundo".
#    * Los demás la DESCARGAN: sustituyen sus listas por las del anfitrión
#      y aparecen donde está él.
#    * Cada cambio en la lista de bloques es la variable "b:índice" (el
#      servidor la guarda: quien entra tarde también la recibe).
#    * La posición y el disfraz de cada parte del jugador van ~10 veces por
#      segundo; los demás jugadores se dibujan con su nombre encima.
#  Lo que NO se comparte: criaturas, objetos tirados, inventario, luz de los
#  cambios en directo (cada uno ve la luz que calcula su juego).
# =============================================================================
import math
from scicalc import pantalla as P, teclas as K
try:
    from scicalc import red
except ImportError:
    red = None

TROZO = 2000           # elementos de lista por variable (mensajes de ~10 KB)
POS_CADA = 3           # enviar la posición cada 3 fotogramas (~10 por segundo)
ESPERA_MUNDO = 10000   # ms esperando a que el anfitrión suba el mundo


class Multijugador:
    def __init__(self, proj, cfg):
        self.p = proj
        st = proj.stage

        def var(nombre, dic):
            for vid, n in proj.names.items():
                if n == nombre and vid in dic:
                    return vid
            return None
        self.listas = {n: var(n, st.lists) for n in cfg.get("mundo", [])}
        self.bloques = var(cfg.get("bloques"), st.lists)
        self.vx, self.vy = var(cfg.get("x"), st.vars), var(cfg.get("y"), st.vars)
        cam = cfg.get("camara") or [None, None]
        self.cx, self.cy = var(cam[0], st.vars), var(cam[1], st.vars)
        self.k = float(cfg.get("casilla", 1))
        self.partes = [proj.by_name[n] for n in cfg.get("partes", []) if n in proj.by_name]
        self.on = False          # conectado a la sala
        self.listo = False       # mundo compartido (ya se sincronizan los bloques)
        self.otros = {}          # id -> último mensaje de posición
        self.rects = {}          # id -> rectángulo de pantalla donde se dibujó
        self.frame = 0
        self.enviado = None

    def disponible(self):
        return (red is not None and self.vx is not None and self.vy is not None
                and all(v is not None for v in self.listas.values()))

    # ---- utilidades -------------------------------------------------------------
    def num(self, vid):
        try:
            return float(self.p.stage.vars.get(vid, 0))
        except (TypeError, ValueError):
            return 0.0

    def base(self, x, y):
        """Posición en el escenario (unidades de Scratch) de la casilla (x, y) del mundo."""
        if self.cx is None:
            return x, y
        return (math.floor((x - self.num(self.cx)) * self.k),
                math.floor((y - self.num(self.cy)) * self.k))

    def esperar_vars(self, cond, ms):
        fin = K.ms() + ms
        while not cond(red.vars()) and K.ms() < fin:
            P.mostrar()                      # mantiene vivo el watchdog
        return red.vars()

    def aviso(self, texto):
        self.p.toast = [texto[:48], K.ms() + 3500]
        self.p.dirty_all = True

    # ---- conectar / salir --------------------------------------------------------
    def conectar(self):
        P.rect(int(self.p.ox) + 60, int(self.p.oy) + 95, 200, 22, 0x203020)
        P.texto("Conectando...", int(self.p.ox) + 120, int(self.p.oy) + 102, 0x80FF80)
        P.mostrar()
        red.conectar(self.p.room)
        if not red.esperar():
            self.aviso("Sin conexión: " + red.error())
            return
        self.on = True
        vs = red.vars()
        if "mundo" not in vs and red.anfitrion() != red.mi_id():
            # otro jugador está abriendo la partida: esperar a que suba el mundo
            vs = self.esperar_vars(lambda v: "mundo" in v, ESPERA_MUNDO)
        if "mundo" in vs:
            self.descargar(vs)
        else:
            self.publicar()
        self.listo = True
        self.p.dirty_all = True

    def salir(self):
        red.desconectar()
        self.on = self.listo = False
        self.otros, self.rects = {}, {}
        self.aviso("Multijugador desconectado")

    def publicar(self):
        st = self.p.stage
        info = {}
        for nombre, lid in self.listas.items():
            items = st.lists[lid]
            n = (len(items) + TROZO - 1) // TROZO
            for i in range(n):
                red.var("m:%s:%d" % (nombre, i), items[i * TROZO:(i + 1) * TROZO])
                P.mostrar()
            info[nombre] = n
        red.var("mundo", {"listas": info})          # al final: el mundo ya está completo
        self.aviso("Partida abierta: ya se pueden unir")

    def descargar(self, vs):
        st = self.p.stage
        info = vs["mundo"].get("listas", {})
        for nombre, n in info.items():
            lid = self.listas.get(nombre)
            if lid is None:
                continue
            items = []
            for i in range(n):
                items.extend(vs.get("m:%s:%d" % (nombre, i)) or [])
            st.lists[lid][:] = items
        # aparecer junto al anfitrión (su posición llega en unos instantes)
        anf = red.anfitrion()
        fin = K.ms() + 1500
        while anf not in self.otros and K.ms() < fin:
            self.leer()
            P.mostrar()
        self.aplicar_bloques(red.vars())            # también lo cambiado mientras tanto
        pos = self.otros.get(anf)
        if pos:
            self.ir_a(pos["x"] - 1.5, pos["y"] + 1)      # a su lado (cae al suelo)
        nombre = red.jugadores().get(anf, "anfitrión")
        self.aviso("Unido a la partida de %s" % nombre)

    def aplicar_bloques(self, vs):
        lst = self.p.stage.lists.get(self.bloques)
        if lst is None:
            return
        for n, v in vs.items():
            if n.startswith("b:"):
                i = int(n[2:])
                if 0 <= i < len(lst):
                    lst[i] = v

    def ir_a(self, x, y):
        st = self.p.stage.vars
        if self.cx is not None:                     # la cámara se mueve con el jugador
            st[self.cx] = x - (self.num(self.vx) - self.num(self.cx))
            st[self.cy] = y - (self.num(self.vy) - self.num(self.cy))
        st[self.vx], st[self.vy] = x, y

    # ---- durante el juego ---------------------------------------------------------
    def bloque(self, lid, i, v):
        """Lo llama el intérprete al cambiar un elemento de una lista."""
        if self.listo and lid == self.bloques:
            red.var("b:%d" % i, v)

    def leer(self):
        """Procesa lo recibido. Devuelve False si no llegó nada."""
        msgs = red.recibir()
        lst = self.p.stage.lists.get(self.bloques)
        for m in msgs:
            t = m.get("t")
            if t == "var" and self.listo and str(m.get("n", "")).startswith("b:") and lst is not None:
                i = int(m["n"][2:])
                if 0 <= i < len(lst):
                    lst[i] = m.get("v")
            elif t == "de" and isinstance(m.get("d"), dict) and "x" in m["d"]:
                self.otros[m.get("id")] = m["d"]
            elif t == "entra":
                self.aviso("%s se ha unido" % m.get("nombre", "?"))
            elif t == "sale":
                self.otros.pop(m.get("id"), None)
                self.aviso("%s se ha ido" % red.jugadores().get(m.get("id"), "Un jugador"))
            elif t == "estado" and m.get("e") != "conectado":
                self.on = self.listo = False
                self.otros = {}
                self.aviso("Multijugador: " + (m.get("msg") or "desconectado"))
        return bool(msgs)

    def paso(self):
        if not self.on:
            return
        self.leer()
        if not self.listo:
            return
        # mi posición y la pose de cada parte (relativa al jugador)
        self.frame += 1
        if self.frame % POS_CADA == 0:
            x, y = self.num(self.vx), self.num(self.vy)
            bx, by = self.base(x, y)
            partes = [[sp.costume, round(sp.x - bx, 1), round(sp.y - by, 1), round(sp.dir), sp.visible]
                      for sp in self.partes]
            d = {"x": round(x, 3), "y": round(y, 3), "p": partes}
            if d != self.enviado:
                red.enviar(d)
                self.enviado = d
        # zonas de pantalla que cambian (los demás se mueven o se mueve la cámara)
        nuevos = {}
        for pid in self.otros:
            nuevos[pid] = self.rect(pid)
        for pid in set(self.rects) | set(nuevos):
            a, b = self.rects.get(pid), nuevos.get(pid)
            if a != b:
                if a:
                    self.p.dirty.append(a)
                if b:
                    self.p.dirty.append(b)
        self.rects = nuevos

    # ---- dibujar a los demás --------------------------------------------------------
    def poses(self, pid):
        """(objeto, disfraz, x, y, dirección) de cada parte de otro jugador."""
        d = self.otros[pid]
        bx, by = self.base(d["x"], d["y"])
        out = []
        for sp, pp in zip(self.partes, d.get("p", [])):
            c, dx, dy, dr, vis = pp
            if vis and 0 <= c < len(sp.costumes):
                out.append((sp, c, bx + dx, by + dy, dr))
        return out

    def con_pose(self, sp, c, x, y, dr, fn):
        # Pone la parte en la pose del otro jugador, llama a fn y la deja como estaba
        old = (sp.costume, sp.x, sp.y, sp.dir, sp.visible)
        sp.costume, sp.x, sp.y, sp.dir, sp.visible = c, x, y, dr, True
        try:
            return fn()
        finally:
            sp.costume, sp.x, sp.y, sp.dir, sp.visible = old

    def rect(self, pid):
        x0 = y0 = 9999
        x1 = y1 = -9999
        for sp, c, x, y, dr in self.poses(pid):
            r = self.con_pose(sp, c, x, y, dr, sp.screen_rect)
            if r:
                x0, y0 = min(x0, r[0]), min(y0, r[1])
                x1, y1 = max(x1, r[0] + r[2]), max(y1, r[1] + r[3])
        if x1 < x0:
            return None
        w = len(self.nombre(pid)) * 6 + 6
        cx = (x0 + x1) // 2
        x0, x1 = min(x0, cx - w // 2), max(x1, cx + w // 2)
        return (x0, y0 - 14, x1 - x0, y1 - y0 + 14)          # con la etiqueta del nombre

    def nombre(self, pid):
        return str(red.jugadores().get(pid, "?"))[:12]

    def dibujar(self):
        if not self.listo:
            return
        for pid in list(self.otros):
            poses = self.poses(pid)
            for sp, c, x, y, dr in poses:
                self.con_pose(sp, c, x, y, dr, sp.draw)
            r = self.rects.get(pid)
            if r and poses:
                n = self.nombre(pid)
                tx = r[0] + (r[2] - len(n) * 6) // 2
                P.rect(tx - 2, r[1], len(n) * 6 + 4, 11, 0x202020)
                P.texto(n, tx, r[1] + 2, 0xFFFFFF)
