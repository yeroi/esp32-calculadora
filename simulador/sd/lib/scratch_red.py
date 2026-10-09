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
#      "nueva_partida": [{"si": "Objeto:disfraz", "clic": [x, y]}, ...]
#                     clics (ratón virtual) que empiezan un mundo desde el título:
#                     cada uno cuando se ve ese objeto con ese disfraz (el botón)
#
#  En el juego: menú SciCalc (SHIFT+EXE) > Multijugador...
#    Buscar partidas en la red · Hostear este mundo · servidores añadidos por IP
#    (con sus partidas, o "Nueva partida aquí") · + Añadir servidor · Tu nombre
#  Si te unes desde el título, el juego empieza un mundo cualquiera y se cambia
#  por el de la partida al terminar.
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
        self.nueva = cfg.get("nueva_partida") or []
        self.modo_auto = None    # "unirse" / "hostear": esperando a estar en un mundo
        self.destino = {}        # {"host", "puerto", "hostear"} de la partida elegida
        self.pasos = []          # clics pendientes para empezar un mundo
        self.clic_t = 0
        self.largo, self.largo_t = -1, 0
        # submenú Multijugador
        self.pagina, self.titulo, self.nota = "red", "Multijugador", ""
        self.encontradas, self.servidores, self.srv_sel = [], [], None
        self.nombre_cfg = "Jugador"

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

    # ---- submenú Multijugador (menú SciCalc del juego) -----------------------------------
    def items(self):
        """[(texto, función)] de la página actual del submenú."""
        if self.pagina == "lista":
            out = []
            for ip, puerto, srv, sala in self.encontradas:
                out.append(("Unirse: %s · %d jug." % (srv[:16], len(sala.get("jugadores", []))),
                            lambda d={"host": ip, "puerto": puerto}: self.unirse(d)))
            out.append(("Volver", self.atras))
            return out
        if self.pagina == "servidor":
            sv = self.servidores[self.srv_sel]
            d = {"host": sv["ip"], "puerto": sv["puerto"]}
            out = [(t, f) for t, f in self.salas_servidor]
            out += [("Nueva partida aquí (sube tu mundo)",
                     lambda: self.hostear(dict(d, subir=True))),
                    ("Quitar este servidor", self.quitar), ("Volver", self.atras)]
            return out
        if self.on:
            return [("Jugadores: " + ", ".join(red.jugadores().values())[:30], lambda: None),
                    ("Salir de la partida", self.salir), ("Volver", self.atras)]
        out = [("Buscar partidas en la red", self.buscar),
               ("Hostear este mundo", lambda: self.hostear({"hostear": True, "subir": True}))]
        for i, sv in enumerate(self.servidores):
            out.append(("Servidor: %s" % sv.get("nombre", sv["ip"])[:22], lambda i=i: self.ver_servidor(i)))
        out += [("+ Añadir servidor (IP)", self.anadir),
                ("Tu nombre: " + self.nombre_cfg, self.cambiar_nombre),
                ("Volver", self.atras)]
        return out

    def abrir_menu(self):
        self.pagina, self.titulo, self.nota = "red", "Multijugador", ""
        r = red.servidores()
        self.servidores = r if isinstance(r, list) else []
        c = red.config()
        if isinstance(c, dict) and "nombre" in c:
            self.nombre_cfg = c["nombre"]
        if self.on:
            self.nota = "Conectado a la partida"

    def atras(self):
        if self.pagina != "red":
            self.abrir_menu()
            self.p.menu = [0, "red"]
        else:
            self.p.menu = [0, None]               # vuelve al menú SciCalc

    def buscar(self):
        self.nota = "Buscando..."
        self.p.render()
        P.mostrar()
        r = red.buscar()
        self.encontradas = []
        if isinstance(r, dict):
            self.nota = r.get("error", "")
            return
        for srv in r:
            for sala in srv.get("salas", []):
                if sala.get("sala") == self.p.room:          # partidas de ESTE juego
                    self.encontradas.append((srv["ip"], srv["puerto"], srv.get("nombre", srv["ip"]), sala))
        self.pagina, self.titulo = "lista", "Partidas en tu red"
        self.nota = "" if self.encontradas else "No hay partidas abiertas de este juego"
        self.p.menu = [0, "red"]

    def ver_servidor(self, i):
        self.srv_sel = i
        sv = self.servidores[i]
        self.pagina, self.titulo = "servidor", "Servidor " + sv.get("nombre", sv["ip"])[:20]
        self.nota = "Preguntando..."
        self.salas_servidor = []
        self.p.render()
        P.mostrar()
        r = red.salas(sv["ip"], sv["puerto"])
        if not isinstance(r, dict) or "error" in r:
            self.nota = "No responde: %s" % (r.get("error", "") if isinstance(r, dict) else "")
            return
        d = {"host": sv["ip"], "puerto": sv["puerto"]}
        for sala in r.get("salas", []):
            if sala.get("sala") == self.p.room:
                n = len(sala.get("jugadores", []))
                self.salas_servidor.append(("Unirse a la partida · %d jug." % n, lambda: self.unirse(d)))
        self.nota = "%s:%d" % (sv["ip"], sv["puerto"])
        self.p.menu = [0, "red"]

    def anadir(self):
        def hecho(t):
            t = t.strip()
            if t:
                ip, _, puerto = t.partition(":")
                red.guardar_servidor(ip, int(puerto) if puerto.isdigit() else 8267)
                self.aviso("Servidor %s añadido" % ip)
            self.abrir_menu()
            self.p.menu = [0, "red"]
        self.p.preguntar("IP del servidor (:puerto)", "", hecho)

    def cambiar_nombre(self):
        def hecho(t):
            if t.strip():
                self.nombre_cfg = red.poner_nombre(t.strip()) or self.nombre_cfg
            self.abrir_menu()
            self.p.menu = [0, "red"]
        self.p.preguntar("Tu nombre", self.nombre_cfg, hecho)

    def quitar(self):
        red.quitar_servidor(self.srv_sel)
        self.abrir_menu()
        self.p.menu = [0, "red"]

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
        self.on = self.listo = False
        self.otros, self.rects = {}, {}
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
        # mi posición y la pose de cada parte (relativa al jugador)
        self.frame += 1
        visible = any(sp.visible for sp in self.partes)
        if self.frame % POS_CADA == 0 and visible:
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
        if not self.listo or not any(sp.visible for sp in self.partes):
            return                                # en menús del juego: no se dibuja a nadie
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
