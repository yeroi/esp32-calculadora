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
#      "partes":  ["Steve Legs2", ...]   objetos que forman al jugador (y sus clones:
#                                         el brazo y la pierna de detrás lo son)
#      "espejo":  [{"objeto": "Cursor", "prefijo": "dig"},
#                  {"objeto": "Tiles", "var": "CloneAsID", "valores": [-1], "mayor": 0}]
#                 más cosas que los demás ven "como en Minecraft": la grieta al
#                 picar, el bloque en la mano (-1) y los objetos tirados (> 0)
#      "nueva_partida": [{"si": "Objeto:disfraz", "clic": [x, y]}, ...]
#                     clics (ratón virtual) que empiezan un mundo desde el título:
#                     cada uno cuando se ve ese objeto con ese disfraz (el botón)
#
#      "boton_titulo": {"si": "Objeto:disfraz", "x", "y", "w", "h"}
#                 botón "Multijugador" en el título del juego (coordenadas de Scratch)
#      "icono": ["Tiles", "grass", "soil"]   disfraces para la pantalla (icono, fondo)
#
#  En el juego: botón "Multijugador" del título, o menú SciCalc > Multijugador:
#  pantalla al estilo de Minecraft (scratch_red_ui.py). Si te unes desde el
#  título, el juego empieza un mundo cualquiera y se cambia por el de la partida.
#
#  Cómo funciona (todo con scicalc.red, en la sala del juego):
#    * El primero que se conecta ABRE la partida: sube las listas del mundo
#      en trozos ("m:lista:n") y después la variable "mundo".
#    * Los demás la DESCARGAN: sustituyen sus listas por las del anfitrión
#      y aparecen donde está él.
#    * Cada cambio en la lista de bloques es la variable "b:índice" (el
#      servidor la guarda: quien entra tarde también la recibe).
#    * ~10 veces por segundo cada uno manda su "espejo": la pose de cada objeto
#      que forma su personaje (también los clones, en su orden de capas y con
#      su tamaño), el bloque que lleva en la mano, sus objetos tirados y la
#      grieta del bloque que pica, todo relativo a su posición. Los demás lo
#      dibujan igual, con su nombre encima.
#  Lo que NO se comparte: criaturas, inventario, luz de los cambios en directo.
#  Los objetos tirados se ven en todas las pantallas, pero solo los recoge
#  quien rompió el bloque.
# =============================================================================
import math
from scicalc import pantalla as P, teclas as K
try:
    from scicalc import red
except ImportError:
    red = None

TROZO = 2000           # elementos de lista por variable (mensajes de ~10 KB)
POS_CADA = 3           # enviar la posición cada 3 fotogramas (~10 por segundo)
GIROS = {"all around": 0, "left-right": 1, "don't rotate": 2}   # estilo de giro -> número
GIROS_INV = ("all around", "left-right", "don't rotate")
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
        # variables del mundo que se copian al unirse (hora del día...)
        self.mundo_vars = {n: var(n, st.vars) for n in cfg.get("mundo_vars", [])}
        # el que se une NO simula su propio mundo: fuera sus mobs (aldeanos que solo
        # existían en su mundo generado), sin generar más; ve los del anfitrión
        inv = cfg.get("invitado") or {}
        self.inv_borrar = inv.get("borrar_clones", [])
        self.inv_vaciar = [var(n, st.lists) for n in inv.get("vaciar", [])]
        self.inv_poner = [(var(n, st.vars), v) for n, v in (inv.get("poner") or {}).items()]
        self.invitado = False       # me he unido a la partida de otro
        self.inv_t = 0
        self.vx, self.vy = var(cfg.get("x"), st.vars), var(cfg.get("y"), st.vars)
        cam = cfg.get("camara") or [None, None]
        self.cx, self.cy = var(cam[0], st.vars), var(cam[1], st.vars)
        self.k = float(cfg.get("casilla", 1))
        self.partes = [proj.by_name[n] for n in cfg.get("partes", []) if n in proj.by_name]
        # Reglas del espejo: qué objetos (y clones) se mandan a los demás
        self.reglas = [{"objeto": sp.name, "cuerpo": True} for sp in self.partes]
        for r in cfg.get("espejo", []):
            if r.get("objeto") in proj.by_name:
                r = dict(r)
                if r.get("var"):
                    r["vid"] = var(r["var"], proj.by_name[r["objeto"]].vars)
                self.reglas.append(r)
        self.regla_de = {}
        for i, r in enumerate(self.reglas):
            self.regla_de.setdefault(r["objeto"], []).append(i)
        self.on = False          # conectado a la sala
        self.listo = False       # mundo compartido (ya se sincronizan los bloques)
        self.otros = {}          # id -> último mensaje de posición
        self.rects = {}          # id -> rectángulo de pantalla donde se dibujó
        self.frame = 0
        self.enviado = None
        self.nueva = cfg.get("nueva_partida") or []
        self.modo_auto = None    # "unirse" / "hostear": esperando a estar en un mundo
        self.destino = {}        # {"host", "puerto", "hostear"} de la partida elegida
        self.pasos = []          # clics pendientes para empezar un mundo
        self.clic_t = 0
        self.largo, self.largo_t = -1, 0
        # pantalla Multijugador (scratch_red_ui.py) y botón del título
        self.ui = None
        self.nombre_cfg = "Jugador"
        self.cfg_icono = cfg.get("icono")
        self.btn_titulo = cfg.get("boton_titulo")

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

    def en_mundo(self):
        """¿Está el jugador dentro de un mundo (no en el título ni generándolo)?"""
        lst = self.p.stage.lists.get(self.bloques)
        n = len(lst) if lst is not None else 0
        ahora = K.ms()
        if n != self.largo:                        # la lista aún cambia de tamaño: generando
            self.largo, self.largo_t = n, ahora
        quieto = ahora - self.largo_t > 1500
        return n > 0 and quieto and any(sp.visible for sp in self.partes)

    def auto(self, modo, destino=None):
        """Entrar en la partida en cuanto el jugador esté en un mundo."""
        self.modo_auto, self.destino = modo, destino or {}
        if not self.en_mundo():        # desde el título: el juego empieza un mundo nuevo
            self.pasos = [dict(p) for p in self.nueva]

    def visible(self, cond):
        nombre, _, disfraz = cond.partition(":")
        for sp in self.p.layers:
            if sp.visible and sp.name == nombre and (not disfraz or sp.costumes[sp.costume][0] == disfraz):
                return True
        return False

    def paso_auto(self):
        ahora = K.ms()
        if self.pasos:
            paso = self.pasos[0]
            if len(self.pasos) > 1 and self.visible(self.pasos[1]["si"]):
                self.pasos.pop(0)                      # el clic anterior ya funcionó
            elif self.visible(paso["si"]) and ahora - self.clic_t > 1500:
                self.p.mouse[:] = [float(paso["clic"][0]), float(paso["clic"][1])]
                self.p.clic_hasta = self.p.frame + 8   # botón pulsado unos fotogramas
                self.p.click()
                self.clic_t = ahora
            elif len(self.pasos) == 1 and not self.visible(paso["si"]) and self.clic_t:
                self.pasos = []                        # el último botón ya no está: hecho
        if self.en_mundo():
            self.modo_auto = None
            self.conectar()
        elif self.p.toast is None or ahora > self.p.toast[1] - 500:
            self.aviso("Creando el mundo para hostear..." if self.modo_auto == "hostear"
                       else "Entrando en la partida...")

    # ---- conectar / salir --------------------------------------------------------
    def conectar(self):
        P.rect(int(self.p.ox) + 60, int(self.p.oy) + 95, 200, 22, 0x203020)
        P.texto("Conectando...", int(self.p.ox) + 120, int(self.p.oy) + 102, 0x80FF80)
        P.mostrar()
        d = self.destino
        red.conectar(self.p.room, None, d.get("host"), d.get("puerto"), d.get("hostear", False))
        if not red.esperar():
            self.aviso("Sin conexión: " + red.error())
            return
        self.on = True
        vs = red.vars()
        if "mundo" not in vs and red.anfitrion() != red.mi_id():
            # otro jugador está abriendo la partida: esperar a que suba el mundo
            vs = self.esperar_vars(lambda v: "mundo" in v, ESPERA_MUNDO)
        if d.get("subir"):                          # hostear: TU mundo es el de la partida
            self.publicar()
        elif "mundo" in vs:
            self.descargar(vs)
        else:
            self.publicar()
        self.listo = True
        self.p.dirty_all = True

    # ---- pantalla Multijugador y botón del título -------------------------------------
    def abrir_menu(self):
        if self.ui is None:
            from scratch_red_ui import PantallaRed
            self.ui = PantallaRed(self)
        c = red.config()
        if isinstance(c, dict) and "nombre" in c:
            self.nombre_cfg = c["nombre"]
        self.p.menu = [0, "red"]
        self.ui.abrir()

    def titulo_rect(self):
        """Rectángulo de pantalla del botón "Multijugador" (o None si no hay título)."""
        b = self.btn_titulo
        if not b or self.p.menu or self.on or self.modo_auto or not self.visible(b["si"]):
            return None
        x, y = self.p.to_screen(b["x"], b["y"])
        w, h = b["w"] * self.p.fx, b["h"] * self.p.fy
        return (int(x - w / 2), int(y - h / 2), int(w), int(h))

    def dibujar_titulo(self):
        r = self.titulo_rect()
        if r:
            x, y, w, h = r
            P.rect(x, y, w, h, 0x000000)
            P.rect(x + 1, y + 1, w - 2, h - 2, 0x6E6E6E)
            P.rect(x + 1, y + 1, w - 2, 1, 0xA9A9A9)
            P.rect(x + 1, y + h - 2, w - 2, 1, 0x373737)
            t = "Multijugador"
            P.texto(t, x + (w - len(t) * 6) // 2 + 1, y + (h - 8) // 2 + 1, 0x2A2A2A)
            P.texto(t, x + (w - len(t) * 6) // 2, y + (h - 8) // 2, 0xE0E0E0)

    def clic_titulo(self):
        """True si el clic del ratón fue en el botón "Multijugador" del título."""
        r = self.titulo_rect()
        if not r:
            return False
        mx, my = self.p.mouse_screen()
        if r[0] <= mx < r[0] + r[2] and r[1] <= my < r[1] + r[3]:
            self.abrir_menu()
            self.p.dirty_all = True
            return True
        return False

    def unirse(self, destino):
        self.p.menu = None
        if self.en_mundo():
            self.destino = destino
            self.conectar()                       # tu mundo se cambia por el de la partida
        else:
            self.auto("unirse", destino)          # desde el título: empieza uno y se cambia

    def hostear(self, destino):
        self.p.menu = None
        if self.en_mundo():
            self.destino = destino
            self.conectar()
        else:
            self.auto("hostear", destino)         # empieza un mundo nuevo y lo abre

    def salir(self):
        self.p.menu = None
        red.desconectar()
        self.on = self.listo = self.invitado = False
        self.otros = {}                             # (zonas() borra lo que se dibujó)
        self.aviso("Multijugador desconectado")

    def publicar(self):
        st = self.p.stage
        info = {}
        red.vaciar()                                # fuera lo de un mundo anterior
        for nombre, lid in self.listas.items():
            items = st.lists[lid]
            n = (len(items) + TROZO - 1) // TROZO
            for i in range(n):
                red.var("m:%s:%d" % (nombre, i), items[i * TROZO:(i + 1) * TROZO])
                P.mostrar()
            info[nombre] = n
        vs = {n: st.vars.get(vid) for n, vid in self.mundo_vars.items() if vid}
        red.var("mundo", {"listas": info, "vars": vs})   # al final: el mundo ya está completo
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
        for nombre, v in (vs["mundo"].get("vars") or {}).items():
            vid = self.mundo_vars.get(nombre)
            if vid:
                st.vars[vid] = v
        self.invitado = True
        self.solo_anfitrion()
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

    def solo_anfitrion(self):
        """Invitado: borra mis mobs y no deja generar más (los simula el anfitrión)."""
        st = self.p.stage
        for sp in list(self.p.layers):
            if sp.is_clone and sp.name in self.inv_borrar:
                if sp.drawn:
                    self.p.dirty.append(sp.drawn)
                self.p.layers.remove(sp)
                sp.alive = False
                self.p.clones -= 1
                for t in self.p.threads:
                    if t.sp is sp:
                        t.done = True
        for lid in self.inv_vaciar:
            if lid:
                st.lists[lid][:] = []
        for vid, v in self.inv_poner:
            if vid:
                st.vars[vid] = v

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
                self.enviado = None                 # que el nuevo reciba ya mi posición
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
        if self.modo_auto and not self.on:
            self.paso_auto()
            return
        if not self.on:
            return
        self.leer()
        if not self.listo:
            return
        if self.invitado and K.ms() - self.inv_t > 1000:   # por si el juego genera otro
            self.inv_t = K.ms()
            self.solo_anfitrion()
        # mi posición y la pose de cada parte (relativa al jugador)
        self.frame += 1
        visible = any(sp.visible for sp in self.partes)
        if self.frame % POS_CADA == 0 and visible:
            x, y = self.num(self.vx), self.num(self.vy)
            d = {"x": round(x, 3), "y": round(y, 3), "e": self.espejo(x, y)}
            if d != self.enviado:
                red.enviar(d)
                self.enviado = d

    def zonas(self):
        """Zonas de pantalla que cambian (los demás se mueven o se mueve la cámara).
        Se llama justo antes de dibujar: la cámara ya está donde se va a dibujar."""
        nuevos = {}
        if self.listo and any(sp.visible for sp in self.partes):
            for pid in self.otros:
                nuevos[pid] = self.rect(pid)
        for pid in set(self.rects) | set(nuevos):
            a, b = self.rects.get(pid) or [], nuevos.get(pid) or []
            if a != b:
                self.p.dirty.extend(a)
                self.p.dirty.extend(b)
        self.rects = nuevos

    # ---- el espejo: lo que los demás ven de mí ---------------------------------------
    def coincide(self, sp, r):
        if r.get("clon") and not sp.is_clone:
            return False
        if r.get("prefijo") and not sp.costumes[sp.costume][0].startswith(r["prefijo"]):
            return False
        if r.get("vid"):
            try:
                v = float(sp.vars.get(r["vid"], 0))
            except (TypeError, ValueError):
                return False
            if v not in r.get("valores", ()) and not ("mayor" in r and v > r["mayor"]):
                return False
        return True

    def espejo(self, x, y):
        """[regla, disfraz, dx, dy, dirección, tamaño] de lo que se ve de mí, en orden
        de capas (de atrás adelante) y relativo a mi posición."""
        bx, by = self.base(x, y)
        out = []
        for sp in self.p.layers:
            idx = self.regla_de.get(sp.name)
            if not idx or not sp.visible or sp.ghost >= 100:
                continue
            for i in idx:
                r = self.reglas[i]
                if r.get("cerca") and max(abs(sp.x - bx), abs(sp.y - by)) > r["cerca"]:
                    continue                      # (p. ej. iconos del inventario, lejos de mí)
                if self.coincide(sp, r):
                    out.append([i, sp.costume, round(sp.x - bx, 1), round(sp.y - by, 1),
                                round(sp.dir), round(sp.size), GIROS.get(sp.rot, 0)])
                    break
        return out

    # ---- dibujar a los demás --------------------------------------------------------
    def poses(self, pid):
        """(objeto, disfraz, x, y, dirección, tamaño, ¿cuerpo?, estilo de giro) de lo
        que se ve de otro."""
        d = self.otros[pid]
        bx, by = self.base(d["x"], d["y"])
        out = []
        for e in d.get("e", []):
            if len(e) < 6 or not (0 <= e[0] < len(self.reglas)):
                continue
            r = self.reglas[e[0]]
            sp = self.p.by_name.get(r["objeto"])
            if sp and 0 <= e[1] < len(sp.costumes):
                rot = GIROS_INV[e[6]] if len(e) > 6 and 0 <= e[6] < 3 else sp.rot
                out.append((sp, e[1], bx + e[2], by + e[3], e[4], e[5], r.get("cuerpo", False), rot))
        return out

    def con_pose(self, sp, c, x, y, dr, tam, rot, fn):
        # Pone el objeto en la pose del otro jugador, llama a fn y lo deja como estaba
        # (el estilo de giro también: un clon puede tener otro distinto al original)
        old = (sp.costume, sp.x, sp.y, sp.dir, sp.size, sp.visible, sp.ghost, sp.rot)
        sp.costume, sp.x, sp.y, sp.dir, sp.size, sp.visible, sp.ghost, sp.rot = c, x, y, dr, tam, True, 0, rot
        try:
            return fn()
        finally:
            sp.costume, sp.x, sp.y, sp.dir, sp.size, sp.visible, sp.ghost, sp.rot = old

    def rect(self, pid):
        """Rectángulos de pantalla que ocupa otro jugador (cuerpo + etiqueta, y cada
        objeto suelto por separado: un objeto tirado puede estar lejos)."""
        rects = []
        x0 = y0 = 9999
        x1 = y1 = -9999
        for sp, c, x, y, dr, tam, cuerpo, rot in self.poses(pid):
            r = self.con_pose(sp, c, x, y, dr, tam, rot, sp.screen_rect)
            if not r:
                continue
            if cuerpo:
                x0, y0 = min(x0, r[0]), min(y0, r[1])
                x1, y1 = max(x1, r[0] + r[2]), max(y1, r[1] + r[3])
            else:
                rects.append(r)
        if x1 >= x0:
            w = len(self.nombre(pid)) * 6 + 6
            cx = (x0 + x1) // 2
            x0, x1 = min(x0, cx - w // 2), max(x1, cx + w // 2)
            rects.insert(0, (x0, y0 - 14, x1 - x0, y1 - y0 + 14))   # con la etiqueta del nombre
        return rects

    def nombre(self, pid):
        return str(red.jugadores().get(pid, "?"))[:12]

    def dibujar(self):
        """Cuerpo, objeto en la mano, grieta y objetos soltados de los demás (a la
        altura de mi jugador: delante de troncos y hojas, como en Minecraft)."""
        if not self.listo or not any(sp.visible for sp in self.partes):
            return                                # en menús del juego: no se dibuja a nadie
        for pid in list(self.otros):
            for sp, c, x, y, dr, tam, _, rot in self.poses(pid):
                self.con_pose(sp, c, x, y, dr, tam, rot, sp.draw)

    def dibujar_nombres(self):
        """Etiqueta con el nombre encima de cada jugador, por delante de todo."""
        if not self.listo or not any(sp.visible for sp in self.partes):
            return
        for pid in list(self.otros):
            rs = self.rects.get(pid)
            r = rs[0] if rs else None
            if r and any(e[6] for e in self.poses(pid)):
                n = self.nombre(pid)
                tx = r[0] + (r[2] - len(n) * 6) // 2
                P.rect(tx - 2, r[1], len(n) * 6 + 4, 11, 0x202020)
                P.texto(n, tx, r[1] + 2, 0xFFFFFF)
