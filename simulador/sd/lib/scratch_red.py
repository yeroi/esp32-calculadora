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
#      "mobs": {"objeto": "Mob", "lista": "_Mob", "datos": "_MOB_DATA", ...}
#                 el anfitrión manda sus mobs desde la lista del juego (todos, no
#                 solo los que tiene en pantalla) y los demás los dibujan donde
#                 estén; además no borra los que están lejos de él pero cerca de
#                 otro jugador ("area": variable de la distancia a la que los borra)
#
#      "chunk": "_CHUNK_SEED"   variable con el chunk en el que está el jugador (mundos
#                 infinitos por trozos): los cambios de bloque van como "b:chunk:i"
#                 y solo se aplican en ese chunk; a quien está en otro no se le dibuja
#      "sin_enviar": ["load chunk", ...]   mensajes de Scratch cuyos guiones cambian la
#                 lista de bloques sin ser el jugador (cargar/generar un chunk)
#
#      "cofres": {"lista": "_Inside", "abierto": "_InsideIdx", "inv": "_Inv", "inv_base": 80}
#                 contenedores compartidos: registros [casilla, huecos, nombre, (id, n)...]
#                 que se mandan enteros ("c:chunk:casilla") cuando cambian
#      "sincronizar": [["snow", "Weather Type"], ["", "_Time"], ...]
#                 variables (objeto, o "" = escenario) que manda el anfitrión cada 2 s
#
#      "unirse_con_partida": true
#                 el que se une no crea ningún mundo: el anfitrión guarda su partida
#                 con el propio guardado del juego (tecla "guardar") y el invitado
#                 la abre con el botón de cargar ("cargar_partida"), contestando él
#                 solo a "pega el código". El juego arranca como al cargar una partida.
#
#  En el juego: botón "Multijugador" del título, o menú SciCalc > Multijugador:
#  pantalla al estilo de Minecraft (scratch_red_ui.py). Sin "unirse_con_partida",
#  si te unes desde el título el juego empieza un mundo y se cambia por el de la partida.
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
import random
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
ESPERA_PARTIDA = 60000  # ms esperando a que el anfitrión guarde y suba su partida


# Inventario vacío (registro 202: "0" = huecos vacíos seguidos, 40 de ellos)
INV_VACIO = "3202" + "15" + "10" + "240"


def sin_inventario(txt):
    """Cambia el inventario (registros 200-202) de un código de partida de Paper
    Minecraft por uno vacío: el que se une no se lleva una copia del del anfitrión.
    Formato: número de formato y registros [tipo][largo][datos]; cada número va
    como 1 cifra con cuántas cifras tiene y luego el número ("0" es el 1)."""
    def num(i):
        c = txt[i]
        if c == "0":
            return 1, i + 1
        k = int(c)
        return int(txt[i + 1:i + 1 + k]), i + 1 + k
    try:
        _, i = num(0)
        out = [txt[:i]]
        puesto = False
        while i < len(txt):
            if not ("0" <= txt[i] <= "9"):
                out.append(txt[i])
                i += 1
                continue
            ini = i
            tipo, i = num(i)
            largo, i = num(i)
            fin = i + largo
            if not 200 <= tipo <= 202:
                out.append(txt[ini:fin])
            elif not puesto:
                out.append(INV_VACIO)
                puesto = True
            i = fin
        return "".join(out)
    except (ValueError, IndexError):
        return txt                                  # formato raro: tal cual


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
        self.vchunk = var(cfg.get("chunk"), st.vars)
        cf = cfg.get("cofres") or {}
        self.lcofres = var(cf.get("lista"), st.lists)
        self.vabierto = var(cf.get("abierto"), st.vars)
        self.linv = var(cf.get("inv"), st.lists)
        self.inv_base = int(cf.get("inv_base", 80))
        self.cofres_vistos = None            # {casilla: registro} ya mandado/recibido
        self.cofres_t = 0
        self.sinc = []                       # [(objeto, id de variable, nombre)]
        for obj, nombre in cfg.get("sincronizar", []):
            dueno = proj.by_name.get(obj) if obj else st
            if dueno is not None:
                vid = var(nombre, dueno.vars)
                if vid:
                    self.sinc.append((dueno, vid, nombre))
        self.sinc_t = 0
        self.sin_enviar = set(str(n).lower() for n in cfg.get("sin_enviar", []))
        self.chunk_visto, self.chunk_t = None, 0
        self.obj_pid = None                  # a quién va el mob que se está procesando
        self.vobj = (var("_ObjX", st.vars), var("_ObjY", st.vars))
        self.vtiempo = var("_TimeReal", st.vars)
        self.lbotin = var(cfg.get("botin"), st.lists)   # lista donde el juego pone lo que cae
        self.golpeado = {}                   # anfitrión: mob -> (quién le pegó, cuándo)
        self.objs_vistos = {}                # objeto del suelo -> cuándo lo vi por primera vez
        self.chat = []                       # [(texto, color, hasta)] últimos mensajes
        self.bocadillo = {}                  # id -> (texto, hasta): lo que acaba de decir
        self.suave = {}                      # id o (id, mob) -> [x, y] dibujados (interpolados)
        self.vvida = var(cfg.get("vida"), st.vars)
        self.datos_t = 0                     # invitado: cuándo guardé mis datos en el servidor
        self.vivo = True
        self.vid_clon = None
        mb = cfg.get("mobs") or {}
        self.mob_sp = proj.by_name.get(mb.get("objeto"))
        if self.mob_sp:
            self.mob_lista = var(mb.get("lista"), st.lists)
            self.mob_datos = var(mb.get("datos"), st.lists)
            self.mob_vars = [var(mb.get(k), st.vars) for k in ("paso", "mdmul", "mob100", "area")]
            self.mob_area = mb.get("area_base", 45)
        # el que se une NO simula su propio mundo: fuera sus mobs (aldeanos que solo
        # existían en su mundo generado), sin generar más; ve los del anfitrión
        inv = cfg.get("invitado") or {}
        self.inv_borrar = inv.get("borrar_clones", [])
        self.inv_vaciar = [var(n, st.lists) for n in inv.get("vaciar", [])]
        self.inv_poner = [(var(n, st.vars), v) for n, v in (inv.get("poner") or {}).items()]
        self.invitado = False       # me he unido a la partida de otro
        self.con_partida = bool(cfg.get("unirse_con_partida"))
        self.capturar = False       # anfitrión: el próximo guardado es para la red
        self.partida_txt = None     # invitado: código de partida que contestar al juego
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
        self.cargar = cfg.get("cargar_partida") or []   # clics para cargar un mundo guardado
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
        self.ver_espejo = cfg.get("ver_espejo", False)   # depuración: mi espejo a mi lado
        if self.ver_espejo:
            self.listo = True

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

    # ---- chat y mensajes de sistema (como en Minecraft) ------------------------------
    def mensaje(self, texto, color=0xFFFFFF):
        self.chat.append((texto[:52], color, K.ms() + 10000))
        del self.chat[:-5]
        self.p.dirty_all = True

    def chat_local(self, texto):
        """Lo que escribo en el cuadro de texto del juego (sin "/"): a todos."""
        if self.on and self.listo and texto:
            red.enviar({"chat": texto[:80]})
            self.mensaje("<%s> %s" % (self.nombre(red.mi_id()), texto))

    def dibujar_chat(self):
        ahora = K.ms()
        if self.chat and self.chat[0][2] < ahora:
            self.chat = [c for c in self.chat if c[2] >= ahora]
            self.p.dirty_all = True
        x, y = int(self.p.ox) + 4, int(self.p.oy + self.p.sh) - 60 - 11 * len(self.chat)
        for texto, color, _ in self.chat:
            P.rect(x, y, len(texto) * 6 + 6, 11, 0x202020)
            P.texto(texto, x + 3, y + 2, color)
            y += 11

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
        self.p.dirty_all = True
        if not self.en_mundo():        # desde el título: el juego empieza un mundo nuevo
            pasos = self.cargar if self.destino.get("cargar") and self.cargar else self.nueva
            self.pasos = [dict(p) for p in pasos]     # (o abre "Load Game": tú eliges cuál)

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
            modo, self.modo_auto = self.modo_auto, None
            self.p.dirty_all = True
            if modo == "cargando":
                self.unido()                           # ya estoy en el mundo del anfitrión
            else:
                self.conectar()
        elif self.modo_auto in ("unirse", "cargando"):
            pass                                       # ya lo dice tapar()
        elif self.p.toast is None or ahora > self.p.toast[1] - 500:
            self.aviso("Elige el mundo guardado..." if self.destino.get("cargar") else
                       "Creando el mundo para hostear..." if self.modo_auto == "hostear"
                       else "Entrando en la partida...")

    def mudo(self, sp):
        """Sonidos que no deben oírse: los del mundo provisional mientras te unes y
        los de mis mobs de invitado (los de verdad los simula el anfitrión)."""
        if self.modo_auto in ("unirse", "cargando"):
            return True
        return self.invitado and sp.is_clone and sp.name in self.inv_borrar

    def tapar(self):
        """Al unirte desde el título el juego de Scratch tiene que arrancar un mundo
        (es su forma de empezar), pero no es el tuyo: se tapa hasta recibir el del
        anfitrión."""
        x, y = int(self.p.ox), int(self.p.oy)
        w, h = int(self.p.sw), int(self.p.sh)
        P.rect(x, y, w, h, 0x3B2A1E)
        for i in range(0, w, 16):
            P.rect(x + i, y, 8, h, 0x45321F)
        t = "Conectando a la partida..."
        P.texto(t, x + (w - len(t) * 6) // 2, y + h // 2 - 12, 0xFFFFFF)
        t = "(abriendo el mundo del anfitrion)" if self.modo_auto == "cargando" else \
            "(descargando el mundo del anfitrion)"
        P.texto(t, x + (w - len(t) * 6) // 2, y + h // 2 + 4, 0xA0A0A0)

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
        # Antes de crear el mundo: ¿el servidor contesta? (si no, se dice aquí mismo)
        host = destino.get("host")
        if host and not destino.get("hostear"):
            info = red.salas(host, destino.get("puerto") or 8267)
            if not isinstance(info, dict) or "error" in info:
                err = info.get("error", "") if isinstance(info, dict) else ""
                if "Wi-Fi" in err:
                    msg = "Sin Wi-Fi: conéctate en Ajustes"
                else:
                    msg = "%s no responde (¿servidor apagado?)" % host
                if self.ui and self.p.menu:
                    self.ui.nota = msg
                    self.p.dirty_all = True
                else:
                    self.aviso(msg)
                return
        self.p.menu = None
        if self.con_partida and self.cargar and not self.en_mundo():
            self.unirse_cargando(destino)         # abre la partida del anfitrión, sin crear nada
        elif self.en_mundo():
            self.destino = destino
            self.conectar()                       # tu mundo se cambia por el de la partida
        else:
            self.auto("unirse", destino)          # desde el título: empieza uno y se cambia

    def unirse_cargando(self, destino):
        self.destino = destino
        self.aviso("Conectando...")
        P.mostrar()
        red.conectar(self.p.room, None, destino.get("host"), destino.get("puerto"), False)
        if not red.esperar():
            self.aviso("Sin conexión: " + red.error())
            return
        self.on = True
        self.modo_auto = "cargando"               # (tapa la pantalla mientras)
        self.tapar()
        P.mostrar()
        vs = self.esperar_vars(lambda v: "partida" in (v.get("mundo") or {}), ESPERA_PARTIDA)
        self.modo_auto = None
        info = vs.get("mundo") or {}
        if "partida" not in info:
            red.desconectar()
            self.on = False
            self.aviso("El anfitrión no ha mandado su partida")
            return
        trozos = [vs.get("g:%d" % i) or "" for i in range(info["partida"])]
        self.partida_txt = "".join(trozos)
        for vid, v in self.inv_poner:              # _RedInvitado = 1 ya: el juego no simula mobs
            if vid:
                self.p.stage.vars[vid] = v
        self.modo_auto = "cargando"               # clic en "Load Game"; el código lo pongo yo
        self.pasos = [dict(p) for p in self.cargar]
        self.p.dirty_all = True

    def hostear(self, destino):
        self.p.menu = None
        if self.en_mundo():
            self.destino = destino
            self.conectar()
        else:
            self.auto("hostear", destino)         # empieza un mundo nuevo y lo abre

    def salir(self):
        self.p.menu = None
        if self.invitado and self.on and self.vivo:
            self.guardar_jugador()
        red.desconectar()
        if self.invitado:                           # vuelves a jugar solo: tus mobs, otra vez
            for vid, v in self.inv_poner:
                if vid and self.p.names.get(vid) == "_RedInvitado":
                    self.p.stage.vars[vid] = 0
        self.on = self.listo = self.invitado = False
        self.capturar, self.partida_txt = False, None
        if self.mob_sp and self.mob_vars[3]:
            self.p.stage.vars[self.mob_vars[3]] = self.mob_area
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
        self.info_listas = info
        if self.con_partida and self.p.save_key:
            # y la partida guardada por el propio juego, para quien se una desde el
            # título (la abre con "Load Game" en vez de crear un mundo)
            self.capturar = True                    # el juego guarda y guardado() lo sube
            self.p.inject(self.p.save_key)
        self.aviso("Partida abierta: ya se pueden unir")

    def guardado(self, txt):
        """Anfitrión: el juego acaba de guardar la partida (su código): se sube."""
        self.capturar = False
        txt = sin_inventario(txt)
        n = (len(txt) + 3999) // 4000
        for i in range(n):
            red.var("g:%d" % i, txt[i * 4000:(i + 1) * 4000])
        st = self.p.stage
        vs = {nm: st.vars.get(vid) for nm, vid in self.mundo_vars.items() if vid}
        red.var("mundo", {"listas": getattr(self, "info_listas", {}), "vars": vs, "partida": n})
        self.aviso("Partida abierta: ya se pueden unir")

    def respuesta(self):
        """Invitado: el código de partida con el que contestar a "pega el código"."""
        t, self.partida_txt = self.partida_txt, None
        return t

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
        self.unido()

    def clave_jugador(self):
        return "j:" + self.nombre(red.mi_id())

    def guardar_jugador(self):
        """Invitado: mi posición, vida e inventario, guardados en el servidor por mi
        nombre (como el playerdata de Minecraft): al volver, sigo donde estaba."""
        st = self.p.stage
        d = {"x": self.num(self.vx), "y": self.num(self.vy), "c": self.chunk()}
        if self.vvida:
            d["vida"] = self.num(self.vvida)
        inv = st.lists.get(self.linv) if self.linv else None
        if inv is not None:
            d["inv"] = list(inv[:80])
        red.var(self.clave_jugador(), d)

    def recuperar_jugador(self, vs):
        d = vs.get(self.clave_jugador())
        if not isinstance(d, dict):
            return False
        st = self.p.stage
        inv = st.lists.get(self.linv) if self.linv else None
        if inv is not None and isinstance(d.get("inv"), list):
            inv[:len(d["inv"])] = d["inv"]
        if self.vvida and d.get("vida", 0) > 0:
            st.vars[self.vvida] = d["vida"]
        if d.get("c", self.chunk()) == self.chunk():
            self.ir_a(d["x"], d["y"])
            return True
        return False

    def unido(self):
        """Ya estoy en el mundo del anfitrión: sin mis mobs, junto a él."""
        self.invitado = True
        self.listo = True
        self.solo_anfitrion()
        # aparecer junto al anfitrión (su posición llega en unos instantes)
        anf = red.anfitrion()
        fin = K.ms() + 1500
        while anf not in self.otros and K.ms() < fin:
            self.leer()
            P.mostrar()
        self.aplicar_bloques(red.vars())            # también lo cambiado mientras tanto
        if self.lcofres:
            self.aplicar_cofres(red.vars())
        self.cofres_vistos = None
        nombre = red.jugadores().get(anf, "anfitrión")
        if self.recuperar_jugador(red.vars()):       # ya había jugado aquí: donde lo dejé
            self.aviso("De vuelta en la partida de %s" % nombre)
            return
        pos = self.otros.get(anf)
        if pos:
            self.ir_a(pos["x"], pos["y"] + 0.1)      # justo donde está él (sobre suelo libre)
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

    def chunk(self):
        return int(self.num(self.vchunk)) if self.vchunk else 0

    def clave_bloque(self, n):
        """"b:chunk:i" (o "b:i") -> índice si es de MI chunk, si no None."""
        partes = n.split(":")
        try:
            if len(partes) == 3:
                return int(partes[2]) if int(partes[1]) == self.chunk() else None
            return int(partes[1])
        except ValueError:
            return None

    def aplicar_bloques(self, vs):
        lst = self.p.stage.lists.get(self.bloques)
        if lst is None:
            return
        for n, v in vs.items():
            if n.startswith("b:"):
                i = self.clave_bloque(n)
                if i is not None and 0 <= i < len(lst):
                    lst[i] = v

    # ---- cofres compartidos -------------------------------------------------------
    def registros(self):
        """{casilla: registro} de la lista de contenedores, y su orden."""
        lst = self.p.stage.lists.get(self.lcofres) or []
        out, orden, i = {}, [], 0
        while i + 2 < len(lst):
            try:
                n = 3 + 2 * int(float(lst[i + 1]))
            except (TypeError, ValueError):
                break
            k = str(lst[i])
            out[k] = list(lst[i:i + n])
            orden.append(k)
            i += n
        return out, orden

    def mandar_cofres(self):
        """Manda los cofres que han cambiado desde la última vez."""
        regs, _ = self.registros()
        if self.cofres_vistos is None:
            self.cofres_vistos = regs
            return
        c = self.chunk()
        for k, r in regs.items():
            if self.cofres_vistos.get(k) != r:
                red.var("c:%d:%s" % (c, k), r)
        for k in self.cofres_vistos:
            if k not in regs:
                red.var("c:%d:%s" % (c, k), None)     # roto
        self.cofres_vistos = regs

    def poner_cofre(self, k, r):
        """Cambio de otro jugador en el contenedor de la casilla k (r None = roto)."""
        lst = self.p.stage.lists.get(self.lcofres)
        if lst is None:
            return
        regs, orden = self.registros()
        st = self.p.stage.vars
        abierto = None                              # el que tengo abierto (si lo hay)
        idx = int(self.num(self.vabierto)) if self.vabierto else 0
        if idx > 0 and idx <= len(lst):
            abierto = str(lst[idx - 1])
        if r is None:
            regs.pop(k, None)
        else:
            if k not in regs:
                orden.append(k)
            regs[k] = list(r)
        nueva = []
        for kk in orden:
            if kk in regs:
                if kk == abierto:
                    st[self.vabierto] = len(nueva) + 1
                nueva.extend(regs[kk])
        lst[:] = nueva
        if abierto is not None and abierto not in regs:
            st[self.vabierto] = 0
        if r is not None and k == abierto and self.linv:   # lo tengo abierto: lo veo cambiar
            inv = self.p.stage.lists.get(self.linv)
            for j in range(len(r) - 3):
                if 0 <= self.inv_base + j < len(inv):
                    inv[self.inv_base + j] = r[3 + j]
        if self.cofres_vistos is not None:
            self.cofres_vistos = regs

    def aplicar_cofres(self, vs):
        c = "c:%d:" % self.chunk()
        for n, v in vs.items():
            if n.startswith(c):
                self.poner_cofre(n[len(c):], v)

    def ir_a(self, x, y):
        st = self.p.stage.vars
        if self.cx is not None:                     # la cámara se mueve con el jugador
            st[self.cx] = x - (self.num(self.vx) - self.num(self.cx))
            st[self.cy] = y - (self.num(self.vy) - self.num(self.cy))
        st[self.vx], st[self.vy] = x, y

    # ---- durante el juego ---------------------------------------------------------
    def bloque(self, lid, i, v, ctx=None):
        """Lo llama el intérprete al cambiar un elemento de una lista."""
        if not (self.listo and lid == self.bloques):
            return
        if ctx is not None and self.sin_enviar and \
                str(ctx.thread.hat[1]).lower() in self.sin_enviar:
            return                                  # el juego cargando/generando un chunk
        if self.vchunk:
            red.var("b:%d:%d" % (self.chunk(), i), v)
        else:
            red.var("b:%d" % i, v)

    def leer(self):
        """Procesa lo recibido. Devuelve False si no llegó nada."""
        msgs = red.recibir()
        lst = self.p.stage.lists.get(self.bloques)
        for m in msgs:
            t = m.get("t")
            if t == "var" and self.listo and str(m.get("n", "")).startswith("b:") and lst is not None:
                i = self.clave_bloque(m["n"])
                if i is not None and 0 <= i < len(lst):
                    lst[i] = m.get("v")
            elif t == "var" and self.listo and self.lcofres and str(m.get("n", "")).startswith("c:"):
                partes = m["n"].split(":", 2)
                if len(partes) == 3 and partes[1] == str(self.chunk()):
                    self.poner_cofre(partes[2], m.get("v"))
            elif t == "de" and isinstance(m.get("d"), dict) and "sinc" in m["d"]:
                if m.get("id") == red.anfitrion():
                    for dueno, vid, nombre in self.sinc:
                        if nombre in m["d"]["sinc"]:
                            dueno.vars[vid] = m["d"]["sinc"][nombre]
            elif t == "de" and isinstance(m.get("d"), dict) and "chat" in m["d"]:
                self.mensaje("<%s> %s" % (self.nombre(m.get("id")), m["d"]["chat"]))
                self.bocadillo[m.get("id")] = (str(m["d"]["chat"])[:30], K.ms() + 5000)
            elif t == "de" and isinstance(m.get("d"), dict) and "sistema" in m["d"]:
                self.mensaje(str(m["d"]["sistema"]), 0xFFFF55)
            elif t == "de" and isinstance(m.get("d"), dict) and "cambia" in m["d"]:
                c = m["d"]["cambia"]
                if c[0] == red.mi_id() and self.listo:
                    self.recibir_cambio(c[1], c[2], len(c) > 3 and c[3])
            elif t == "de" and isinstance(m.get("d"), dict) and "explota" in m["d"]:
                if self.listo and m["d"].get("c", self.chunk()) == self.chunk():
                    self.me_explota(*m["d"]["explota"][:3])
            elif t == "de" and isinstance(m.get("d"), dict) and "golpe" in m["d"]:
                if self.listo and red.anfitrion() == red.mi_id() and self.mob_sp:
                    self.aplicar_golpe(*m["d"]["golpe"][:3], quien=m.get("id"))
            elif t == "de" and isinstance(m.get("d"), dict) and "dar_obj" in m["d"]:
                pid, item, n = m["d"]["dar_obj"]
                if pid == red.mi_id() and self.listo:   # me lo he quedado: a mis pies
                    self.recibir_botin(self.num(self.vx), self.num(self.vy), item, n)
            elif t == "de" and isinstance(m.get("d"), dict) and "botin" in m["d"]:
                pid, x, y, item, n = m["d"]["botin"]
                if pid == red.mi_id() and self.listo:
                    self.recibir_botin(x, y, item, n)
            elif t == "de" and isinstance(m.get("d"), dict) and "x" in m["d"]:
                self.otros[m.get("id")] = m["d"]
                if self.invitado and self.mob_sp and "mobs" in m["d"] and m.get("id") == red.anfitrion():
                    self.copiar_mobs(m["d"]["mobs"])
            elif t == "entra":
                self.enviado = None                 # que el nuevo reciba ya mi posición
                self.mensaje("%s se ha unido a la partida" % m.get("nombre", "?"), 0xFFFF55)
            elif t == "sale":
                self.otros.pop(m.get("id"), None)
                self.mensaje("%s ha salido de la partida" % red.jugadores().get(m.get("id"), "Un jugador"),
                             0xFFFF55)
            elif t == "estado" and m.get("e") != "conectado":
                self.on = self.listo = False
                self.otros = {}
                self.aviso("Multijugador: " + (m.get("msg") or "desconectado"))
        return bool(msgs)

    def paso(self):
        if self.modo_auto == "cargando":              # conectado, abriendo su partida
            self.leer()
            self.paso_auto()
            return
        if self.modo_auto and not self.on:
            self.paso_auto()
            return
        if not self.on:
            return
        self.leer()
        if not self.listo:
            return
        if self.vchunk:
            c = self.chunk()
            if c != self.chunk_visto:               # he cambiado de chunk: cuando acabe
                self.chunk_visto, self.chunk_t = c, K.ms() + 1000   # de cargar, lo de los demás
                self.cofres_vistos = None
            elif self.chunk_t and K.ms() > self.chunk_t:
                self.chunk_t = 0
                vs = red.vars()
                self.aplicar_bloques(vs)
                if self.lcofres:
                    self.aplicar_cofres(vs)
        if self.lcofres and not self.chunk_t and K.ms() > self.cofres_t:
            self.cofres_t = K.ms() + 300            # ~3 veces por segundo
            self.mandar_cofres()
        if self.sinc and self.otros and red.anfitrion() == red.mi_id() and K.ms() > self.sinc_t:
            self.sinc_t = K.ms() + 2000
            red.enviar({"sinc": {nombre: dueno.vars.get(vid) for dueno, vid, nombre in self.sinc}})
        if self.invitado and K.ms() > self.datos_t and self.vivo:
            self.datos_t = K.ms() + 10000           # cada 10 s
            self.guardar_jugador()
        if self.vvida:                              # "Ana ha muerto"
            vivo = self.num(self.vvida) > 0
            if self.vivo and not vivo:
                texto = "%s ha muerto" % self.nombre(red.mi_id())
                red.enviar({"sistema": texto})
                self.mensaje(texto, 0xFFFF55)
            self.vivo = vivo
        if self.mob_sp and self.otros:
            self.area_mobs()
        if self.invitado and K.ms() - self.inv_t > 1000:   # por si el juego genera otro
            self.inv_t = K.ms()
            self.solo_anfitrion()

    def enviar_pose(self):
        """Mi posición y la pose de cada parte, relativa al jugador. Se toma justo
        antes de dibujar: todas las piezas ya están en el mismo fotograma (si no,
        al mover el ratón cada pieza iba de un fotograma distinto)."""
        if not (self.on and self.listo):
            return
        self.frame += 1
        if self.frame % POS_CADA:
            return
        x, y = self.num(self.vx), self.num(self.vy)
        e = self.espejo(x, y)
        cuerpo = [p for p in e if self.reglas[p[0]].get("cuerpo")]
        if cuerpo:
            self.cuerpo_visto = cuerpo
        elif getattr(self, "cuerpo_visto", None) and self.en_partida():
            e = self.cuerpo_visto + e              # inventario abierto: sigo ahí para los demás
        else:
            return                                 # en menús del juego: nada que mandar
        d = {"x": round(x, 3), "y": round(y, 3), "e": e}
        if self.vchunk:
            d["c"] = self.chunk()
        if self.mob_sp and red.anfitrion() == red.mi_id() and self.otros:
            d["mobs"] = self.mobs()
        if d != self.enviado:
            red.enviar(d)
            self.enviado = d

    def mobs(self):
        """Anfitrión: [disfraz, x, y, dirección, tamaño] de cada mob (casillas del
        mundo, y ya con su desplazamiento de dibujo). De la lista del juego: el juego
        solo tiene el objeto (clon) de los que caben en MI pantalla."""
        st = self.p.stage
        lst = st.lists.get(self.mob_lista) or []
        dat = st.lists.get(self.mob_datos) or []
        paso, mdmul, m100, _ = [self.num(v) for v in self.mob_vars]
        paso = int(paso) or 20
        clones = {}
        for sp in self.p.layers:                    # los que tienen clon: su disfraz real
            if sp.is_clone and sp is not self.mob_sp and sp.name == self.mob_sp.name and sp.visible:
                for vid, v in sp.vars.items():
                    if self.p.names.get(vid) == "cloneAsID":
                        clones[int(self.num_de(v))] = sp
        out = []
        for i in range(0, len(lst) - paso + 1, paso):
            try:
                typ = int(float(lst[i]))
                if typ <= 0:
                    continue
                mx, my = float(lst[i + 3]), float(lst[i + 4])
                cara = float(lst[i + 5])
                estado = float(lst[i + 6])
                off = int(mdmul * typ - (m100 if typ >= 100 else 0))
                tam = float(dat[off + 2])
                ofy = float(dat[off + 4])
                raiz = int(float(dat[off + 5]))
                andar = int(float(dat[off + 6]))
            except (ValueError, IndexError, TypeError):
                continue
            sp = clones.get(i + 1)
            if sp is not None:
                c = sp.costume
            else:                                   # sin clon: de pie o andando
                c = raiz - 1 + (int(round(andar / 2)) if estado == 1 else 0)
            try:
                tile, vida = lst[i + 2], float(lst[i + 10])
            except (ValueError, IndexError, TypeError):
                tile, vida = 0, 1
            # [disfraz, x, y de dibujo, dirección, tamaño, índice, tipo, casilla, y, vida]
            out.append([c, round(mx, 2), round(my + ofy / self.k, 2), round(90 * cara), round(tam),
                        i + 1, typ, tile, round(my, 2), vida])
        return out

    # ---- combate: el anfitrión simula; los demás mandan lo que hacen -----------------
    def jugadores(self):
        """[(id o None = yo, x, y)] de los jugadores en mi chunk (como Minecraft:
        los mobs miran a todos)."""
        out = [(None, self.num(self.vx), self.num(self.vy))]
        if self.on and self.listo:
            c = self.chunk()
            for pid, d in self.otros.items():
                if pid != "yo" and d.get("c", c) == c and not d.get("muerto"):
                    out.append((pid, self.num_de(d.get("x")), self.num_de(d.get("y"))))
        return out

    def objetivo(self, ctx, modo):
        """Bloque scicalc_objetivo: _ObjX/_ObjY = el jugador más cercano al mob (o uno
        al azar, para que aparezcan mobs alrededor de todos)."""
        jug = self.jugadores()
        if modo == "azar":
            elegido = random.choice(jug)
        else:
            mx = my = None
            if self.mob_sp:
                if self.vid_clon is None:
                    self.vid_clon = next((v for v in ctx.sp.vars if self.p.names.get(v) == "cloneAsID"), "")
                lst = self.p.stage.lists.get(self.mob_lista) or []
                try:
                    i = int(float(ctx.sp.vars.get(self.vid_clon, 0))) - 1
                    mx, my = float(lst[i + 3]), float(lst[i + 4])
                except (ValueError, IndexError, TypeError):
                    pass
            if mx is None:
                elegido = jug[0]
            else:
                elegido = min(jug, key=lambda j: abs(j[1] - mx) + abs(j[2] - my) * 0.5)
        self.obj_pid = elegido[0]
        ox, oy = self.vobj
        if ox:
            self.p.stage.vars[ox], self.p.stage.vars[oy] = elegido[1], elegido[2]

    def cambio_remoto(self, nombre, v, pid=None, armadura=False):
        """Un mob le hace algo (daño, desgaste de armadura, empujón) a otro jugador."""
        if nombre and v:
            red.enviar({"cambia": [self.obj_pid if pid is None else pid, nombre, v, armadura]})

    def recibir_cambio(self, nombre, v, armadura=False):
        st = self.p.stage
        vid = self.p.var_id(nombre)
        if not vid:
            return
        v = self.num_de(v)
        if armadura:                                # daño "en bruto": con MI armadura
            v = math.floor(v * (self.num(self.p.var_id("_DefenseMul")) or 1))
        st.vars[vid] = self.num_de(st.vars.get(vid)) + v
        if nombre == "_Health_s":                   # como si te hubiera dado en tu juego
            self.p.start_hats("event_whenbroadcastreceived", "update health")

    def copiar_mobs(self, mobs):
        """Invitado: los mobs del anfitrión, también en MI lista del juego (sin
        simularlos): así mi código de pegar los encuentra. Lo que les haga se le
        manda al anfitrión."""
        lst = self.p.stage.lists.get(self.mob_lista)
        if lst is None:
            return
        paso = int(self.num(self.mob_vars[0])) or 20
        self.golpes(lst, paso)
        nueva = []
        for e in mobs:
            if len(e) < 10:
                continue
            i = int(e[5]) - 1
            while len(nueva) < i + paso:
                nueva.append("0")
            nueva[i:i + paso] = [e[6], 1, e[7], e[1], e[8], 1 if e[3] > 0 else -1, 0, 0, 0, 0,
                                 e[9], 0, 0, "", 0, 999999999, 0, 0, 0, 0][:paso]
        lst[:] = nueva

    def golpes(self, lst, paso):
        """Invitado: mi juego le ha pegado a un mob (daño en +9): se lo digo al anfitrión."""
        for i in range(0, len(lst) - paso + 1, paso):
            try:
                dano = float(lst[i + 9])
            except (ValueError, TypeError):
                continue
            if dano > 0:
                red.enviar({"golpe": [i + 1, dano, lst[i + 18]]})
                lst[i + 9] = 0

    def soltar_remoto(self, ctx):
        """Anfitrión: el mob que suelta botín lo ha matado otro jugador hace poco? Se
        lo mando a él (aparece en su mundo y lo recoge él, como en Minecraft)."""
        a = ctx.args[-1]
        try:
            mid = int(float(a.get("mobID", 0)))
        except (TypeError, ValueError):
            return False
        quien = self.golpeado.get(mid)
        if not quien or K.ms() - quien[1] > 3000 or not self.on:
            return False
        lst = self.p.stage.lists.get(self.mob_lista) or []
        try:
            x, y = lst[mid + 2], lst[mid + 3]
        except IndexError:
            return False
        red.enviar({"botin": [quien[0], x, y, a.get("blockID"), a.get("quantity")]})
        return True

    def flecha(self, ctx):
        """Anfitrión: ¿la flecha (clon de Tiles) toca a otro jugador? Como en el juego:
        a menos de 0.5 en x y 0.9 en y, daño según su velocidad."""
        if not (self.on and self.listo):
            return False
        sp = ctx.sp
        v = {self.p.names.get(k): k for k in sp.vars}
        try:
            x, y = float(sp.vars[v["x"]]), float(sp.vars[v["y"]])
            sx, sy = float(sp.vars[v["sx"]]), float(sp.vars[v["sy"]])
        except (KeyError, TypeError, ValueError):
            return False
        for pid, px, py in self.jugadores()[1:]:
            if abs(x - px) < 0.5 and abs(y - py) < 0.9:
                dano = math.ceil(-9 * math.sqrt(sx * sx + sy * sy))
                self.cambio_remoto("_Health_s", dano, pid, True)
                return True
        return False

    def explosion(self, x, y, r):
        """Una explosión en mi juego (creeper, TNT): los demás calculan su daño."""
        if self.on and self.listo:
            red.enviar({"explota": [self.num_de(x), self.num_de(y), self.num_de(r)], "c": self.chunk()})

    def me_explota(self, x, y, r):
        """La misma cuenta que 'Explode Circle_pr' del juego, para mí."""
        dx, dy = x - self.num(self.vx), y - self.num(self.vy)
        dist = max(math.sqrt(dx * dx + dy * dy), 1)
        if dist < r:
            self.recibir_cambio("_Health_s", (r - dist) * -16, True)
            self.recibir_cambio("_DamageArmor", 1)

    def recoger_remoto(self, ctx):
        """¿Toca otro jugador este objeto del suelo (clon de Tiles)? Entonces es suyo:
        le aparece a sus pies y aquí desaparece."""
        if not (self.on and self.listo):
            return False
        sp = ctx.sp
        v = {self.p.names.get(k): k for k in sp.vars}
        try:
            x, y = float(sp.vars[v["x"]]), float(sp.vars[v["y"]])
            c, n = sp.vars[v["c"]], sp.vars[v["count"]]
        except (KeyError, TypeError, ValueError):
            return False
        visto = self.objs_vistos.setdefault(id(sp), K.ms())
        if K.ms() - visto < 1500:                   # recién tirado: aún no (como Minecraft)
            return False
        if len(self.objs_vistos) > 400:
            self.objs_vistos.clear()
        mx, my = self.num(self.vx), self.num(self.vy)
        if abs(mx - x) + abs(my - y) < 1:
            return False                            # yo también lo toco: para mí
        for pid, px, py in self.jugadores()[1:]:
            if abs(px - x) + abs(py - y) < 1:
                red.enviar({"dar_obj": [pid, c, n]})
                return True
        return False

    def recibir_botin(self, x, y, item, n):
        lst = self.p.stage.lists.get(self.lbotin)
        if lst is not None:
            lst.extend([x, y, item, n, round(random.uniform(-0.1, 0.1), 3), "-999"])

    def aplicar_golpe(self, idx, dano, cara, quien=None):
        """Anfitrión: otro jugador ha pegado al mob idx (como si fuera yo, con su daño)."""
        lst = self.p.stage.lists.get(self.mob_lista) or []
        i = int(idx) - 1
        try:
            if float(lst[i]) <= 0 or float(lst[i + 12]) >= self.num(self.vtiempo):
                return                              # muerto o aún invulnerable
        except (ValueError, IndexError, TypeError):
            return
        lst[i + 9] = dano
        lst[i + 18] = cara
        self.golpeado[int(idx)] = (quien, K.ms())

    def num_de(self, v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def area_mobs(self):
        """Anfitrión: que el juego no borre los mobs cerca de los demás jugadores
        (los borra a más de "area" casillas de MI posición)."""
        vid = self.mob_vars[3]
        if not vid or red.anfitrion() != red.mi_id():
            return
        x = self.num(self.vx)
        c = self.chunk()
        lejos = max([abs(self.num_de(d.get("x")) - x) for d in self.otros.values()
                     if d.get("c", c) == c] or [0])
        self.p.stage.vars[vid] = self.mob_area + math.ceil(lejos)

    def en_partida(self):
        lst = self.p.stage.lists.get(self.bloques)
        return bool(lst)

    def zonas(self):
        """Zonas de pantalla que cambian (los demás se mueven o se mueve la cámara).
        Se llama justo antes de dibujar: la cámara ya está donde se va a dibujar."""
        self.enviar_pose()
        self.interpolar()
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
        # Reglas del espejo (perfil): "clon" solo clones, "original" solo el objeto
        # original, "tam_max" tamaño máximo, y con "var": "valores" (lista exacta),
        # "mayor" / "menor" (umbral) del valor de esa variable del objeto.
        if r.get("clon") and not sp.is_clone:
            return False
        if r.get("original") and sp.is_clone:
            return False
        if "tam_max" in r and sp.size > r["tam_max"]:
            return False
        if r.get("prefijo") and not sp.costumes[sp.costume][0].startswith(r["prefijo"]):
            return False
        if r.get("vid"):
            try:
                v = float(sp.vars.get(r["vid"], 0))
            except (TypeError, ValueError):
                return False
            if v not in r.get("valores", ()) and not ("mayor" in r and v > r["mayor"]) \
                    and not ("menor" in r and v < r["menor"]):
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
    def interpolar(self):
        """Como Minecraft: lo que llega ~10 veces por segundo se dibuja yendo poco a
        poco hacia la posición nueva (si el salto es grande, de golpe)."""
        vivos = set()
        for pid, d in self.otros.items():
            pares = [(pid, d.get("x", 0), d.get("y", 0))]
            for e in d.get("mobs") or ():
                if len(e) > 5:
                    pares.append(((pid, e[5]), e[1], e[2]))
            for k, x, y in pares:
                vivos.add(k)
                cur = self.suave.get(k)
                if cur is None or abs(cur[0] - x) > 3 or abs(cur[1] - y) > 3:
                    self.suave[k] = [x, y]
                else:
                    cur[0] += (x - cur[0]) * 0.45
                    cur[1] += (y - cur[1]) * 0.45
        for k in list(self.suave):
            if k not in vivos:
                del self.suave[k]

    def poses(self, pid):
        """(objeto, disfraz, x, y, dirección, tamaño, ¿cuerpo?, estilo de giro) de lo
        que se ve de otro."""
        d = self.otros[pid]
        sx, sy = self.suave.get(pid) or (d["x"], d["y"])
        bx, by = self.base(sx, sy)
        out = []
        if self.vchunk and d.get("c", self.chunk()) != self.chunk():
            return out                              # está en otro trozo del mundo
        for e in d.get("e", []):
            if len(e) < 6 or not (0 <= e[0] < len(self.reglas)):
                continue
            r = self.reglas[e[0]]
            sp = self.p.by_name.get(r["objeto"])
            if sp and 0 <= e[1] < len(sp.costumes):
                rot = GIROS_INV[e[6]] if len(e) > 6 and 0 <= e[6] < 3 else sp.rot
                out.append((sp, e[1], bx + e[2], by + e[3], e[4], e[5], r.get("cuerpo", False), rot))
        if self.mob_sp and d.get("mobs"):           # mobs del anfitrión, donde estén
            sp = self.mob_sp
            for e in d["mobs"]:
                c, mx, my, dr, tam = e[:5]
                if len(e) > 5 and (pid, e[5]) in self.suave:
                    mx, my = self.suave[(pid, e[5])]
                sx, sy = self.base(mx, my)
                if abs(sx) < 300 and abs(sy) < 240 and 0 <= c < len(sp.costumes):
                    out.append((sp, c, sx, sy, dr, tam, False, sp.rot))
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
            b = self.bocadillo.get(pid)
            if b:                                   # y su bocadillo, si acaba de hablar
                rects.append(((x0 + x1) // 2 + 4, y0 - 28, len(b[0]) * 6 + 8, 13))
        return rects

    def nombre(self, pid):
        return str(red.jugadores().get(pid, "?"))[:12]

    def dibujar(self):
        """Cuerpo, objeto en la mano, grieta y objetos soltados de los demás (a la
        altura de mi jugador: delante de troncos y hojas, como en Minecraft)."""
        if self.ver_espejo and any(sp.visible for sp in self.partes):
            x, y = self.num(self.vx), self.num(self.vy)
            self.otros["yo"] = {"x": x + 2, "y": y, "e": self.espejo(x, y)}
        if not self.listo or not any(sp.visible for sp in self.partes):
            return                                # en menús del juego: no se dibuja a nadie
        for pid in list(self.otros):
            for sp, c, x, y, dr, tam, _, rot in self.poses(pid):
                self.con_pose(sp, c, x, y, dr, tam, rot, sp.draw)

    def dibujar_nombres(self):
        """Etiqueta con el nombre encima de cada jugador, por delante de todo (y el chat)."""
        if self.chat:
            self.dibujar_chat()
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
                b = self.bocadillo.get(pid)
                if b and b[1] > K.ms():               # lo que acaba de decir, como el del juego
                    bx = r[0] + r[2] // 2 + 4
                    P.rect(bx, r[1] - 14, len(b[0]) * 6 + 8, 13, 0x808080)
                    P.rect(bx + 1, r[1] - 13, len(b[0]) * 6 + 6, 11, 0xFFFFFF)
                    P.texto(b[0], bx + 4, r[1] - 11, 0x000000)
                elif b:
                    del self.bocadillo[pid]
                    self.p.dirty_all = True
