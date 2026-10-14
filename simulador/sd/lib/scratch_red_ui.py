# =============================================================================
#  scratch_red_ui.py — Pantalla "Multijugador" al estilo de Minecraft
# -----------------------------------------------------------------------------
#  La abre el botón "Multijugador" del título del juego o el menú SciCalc
#  (SHIFT+EXE). Como la de Minecraft Java:
#
#      ┌──────────── Multijugador ────────────┐   fondo de tierra
#      │ [▦] Calculadora de Ana       1/16 ▂▄▆ │   lista: partidas de la red
#      │     Paper Minecraft · red local      │   local y servidores guardados
#      │ [▦] Casa de Yerai            0/16 ▂▄▆ │
#      └──────────────────────────────────────┘
#      [ Unirse ] [ Conexión directa ] [ Añadir servidor ]
#      [Hostear] [Borrar] [Recargar] [Nombre] [ Atrás ]
#
#  Teclas: ▲▼ lista/botones · ◄► botones · EXE pulsar · DEL atrás.
#  Ratón virtual (8 4 6 2 y 5): clic en la lista o en un botón; un segundo
#  clic sobre una partida ya elegida es "Unirse".
# =============================================================================
from scicalc import pantalla as P
try:
    from scicalc import red
except ImportError:
    red = None

W, H = 320, 218
LIST_Y, LIST_H, ROW_H = 24, 126, 30
ROW1_Y, ROW2_Y, BTN_H = 156, 182, 20
FILAS = LIST_H // ROW_H                        # partidas visibles a la vez

# Colores de los botones de Minecraft
BTN, BTN_LUZ, BTN_SOMBRA, BTN_OFF = 0x6E6E6E, 0xA9A9A9, 0x373737, 0x2C2C2C
TXT, TXT_SEL, TXT_GRIS = 0xE0E0E0, 0xFFFFA0, 0xA0A0A0


class PantallaRed:
    def __init__(self, multi):
        self.m = multi
        self.p = multi.p
        self.filas = []          # dict(nombre, detalle, jug, estado, destino, guardado)
        self.foco = ("lista", 0)
        self.scroll = 0
        self.nota = ""
        self.eleccion = None     # (título, [(texto, acción)]): pantalla de elegir (Hostear)
        self.sel_e = 0
        self.tierra = None       # sprite del bloque de tierra (fondo)
        self.icono = None        # sprite del bloque de hierba (icono de servidor)
        tiles = self.p.by_name.get(multi.cfg_icono[0]) if multi.cfg_icono else None
        if tiles:
            for c in tiles.costumes:
                if c[0] == multi.cfg_icono[1]:
                    self.icono = c[1]
                if c[0] == multi.cfg_icono[2]:
                    self.tierra = c[1]

    # ---- botones ----------------------------------------------------------------
    def botones(self):
        """[(texto, acción, x, y, ancho, ¿activo?)] según el estado."""
        if self.m.on:
            return [("Desconectar", self.desconectar, 10, ROW2_Y, 145, True),
                    ("Atrás", self.atras, 165, ROW2_Y, 145, True)]
        sel = self.fila_sel()
        b1 = [("Unirse", self.unirse, 96, sel is not None and sel.get("destino") is not None),
              ("Conexión directa", self.directa, 108, True),
              ("Añadir servidor", self.anadir, 96, True)]
        b2 = [("Hostear", self.hostear, 56, True),
              ("Borrar", self.borrar, 56, sel is not None and sel.get("guardado") is not None),
              ("Recargar", self.recargar, 56, True),
              ("Nombre", self.nombre, 56, True),
              ("Atrás", self.atras, 56, True)]
        out = []
        for fila, y, gap in ((b1, ROW1_Y, 0), (b2, ROW2_Y, 0)):
            total = sum(b[2] for b in fila)
            gap = (300 - total) // max(1, len(fila) - 1)
            x = 10
            for t, f, w, ok in fila:
                out.append((t, f, x, y, w, ok))
                x += w + gap
        return out

    def fila_sel(self):
        if self.foco[0] == "lista" and 0 <= self.foco[1] < len(self.filas):
            return self.filas[self.foco[1]]
        return None

    # ---- datos ---------------------------------------------------------------------
    def abrir(self):
        self.foco, self.scroll = ("lista", 0), 0
        if self.m.on:
            self.jugadores()
        else:
            self.recargar()

    def jugadores(self):
        self.filas = [dict(nombre=str(n), detalle="en esta partida", jug="", estado="ok",
                           destino=None, guardado=None)
                      for n in red.jugadores().values()]
        self.nota = "Conectado. Tu mundo es el de la partida."

    def recargar(self):
        self.nota = "Buscando partidas..."
        self.p.dirty_all = True
        self.p.render()
        P.mostrar()
        filas = []
        r = red.buscar()
        if isinstance(r, dict):
            self.nota = r.get("error", "")
        else:
            for srv in r:
                for sala in srv.get("salas", []):
                    if sala.get("sala") == self.p.room:          # partidas de ESTE juego
                        n = len(sala.get("jugadores", []))
                        filas.append(dict(nombre=srv.get("nombre", srv["ip"])[:26],
                                          detalle="Red local · " + srv["ip"], jug="%d/16" % n,
                                          estado="ok", guardado=None,
                                          destino={"host": srv["ip"], "puerto": srv["puerto"]}))
        guardados = red.servidores()
        for i, sv in enumerate(guardados if isinstance(guardados, list) else []):
            d = {"host": sv["ip"], "puerto": sv["puerto"]}
            info = red.salas(sv["ip"], sv["puerto"])
            fila = dict(nombre=sv.get("nombre", sv["ip"])[:26], guardado=i, destino=d,
                        detalle="%s:%d" % (sv["ip"], sv["puerto"]), jug="", estado="ok")
            if not isinstance(info, dict) or "error" in info:
                fila.update(estado="mal", detalle="No responde · %s" % sv["ip"])
            else:
                sala = [s for s in info.get("salas", []) if s.get("sala") == self.p.room]
                fila["jug"] = "%d/16" % (len(sala[0].get("jugadores", [])) if sala else 0)
                if not sala:
                    fila["detalle"] = "Sin partida · se crea al unirte"
                    d["subir"] = True                  # no hay mundo: sube el tuyo
            filas.append(fila)
        self.filas = filas
        if not isinstance(r, dict):
            self.nota = "" if filas else "No hay partidas. Hostea una o añade un servidor."
        self.foco = ("lista", 0) if filas else ("boton", 0)
        self.scroll = 0
        self.p.dirty_all = True

    # ---- acciones ------------------------------------------------------------------
    def unirse(self):
        f = self.fila_sel()
        if f and f.get("destino"):
            d = dict(f["destino"])
            if d.pop("subir", False):
                self.m.hostear(dict(d, subir=True))
            else:
                self.m.unirse(d)

    def directa(self):
        def hecho(t):
            t = t.strip()
            if t:
                ip, _, puerto = t.partition(":")
                self.m.unirse({"host": ip, "puerto": int(puerto) if puerto.isdigit() else 8267})
            else:
                self.volver()
        self.p.preguntar("Conexión directa: IP(:puerto)", "", hecho)

    def anadir(self):
        def hecho(t):
            t = t.strip()
            if t:
                ip, _, puerto = t.partition(":")
                red.guardar_servidor(ip, int(puerto) if puerto.isdigit() else 8267)
            self.volver()
            self.recargar()
        self.p.preguntar("Añadir servidor: IP(:puerto)", "", hecho)

    def hostear(self):
        if self.m.en_mundo():                      # ya estás en un mundo: se abre ese
            self.m.hostear({"hostear": True, "subir": True})
            return
        opciones = [("Mundo nuevo", lambda: self.m.hostear({"hostear": True, "subir": True}))]
        if self.m.cargar:
            opciones.append(("Cargar mundo guardado",
                             lambda: self.m.hostear({"hostear": True, "subir": True, "cargar": True})))
        opciones.append(("Cancelar", self.cancelar))
        self.eleccion, self.sel_e = ("Hostear partida", opciones), 0
        self.p.dirty_all = True

    def cancelar(self):
        self.eleccion = None
        self.p.dirty_all = True

    def botones_e(self):
        """Botones grandes uno debajo de otro, como 'Crear mundo' de Minecraft."""
        ops = self.eleccion[1]
        y0 = 70 if len(ops) < 3 else 56
        return [(t, f, 60, y0 + i * 30, 200) for i, (t, f) in enumerate(ops)]

    def borrar(self):
        f = self.fila_sel()
        if f and f.get("guardado") is not None:
            red.quitar_servidor(f["guardado"])
            self.recargar()

    def nombre(self):
        def hecho(t):
            if t.strip():
                self.m.nombre_cfg = red.poner_nombre(t.strip()) or self.m.nombre_cfg
            self.volver()
        self.p.preguntar("Tu nombre", self.m.nombre_cfg, hecho)

    def desconectar(self):
        self.m.salir()

    def atras(self):
        self.p.menu = None
        self.p.dirty_all = True

    def volver(self):
        self.p.menu = [0, "red"]
        self.p.dirty_all = True

    # ---- teclas y ratón -----------------------------------------------------------
    def tecla(self, k):
        if self.eleccion:
            bot = self.botones_e()
            if k in ("UP", "DOWN"):
                self.sel_e = (self.sel_e + (1 if k == "DOWN" else -1)) % len(bot)
            elif k == "EXE":
                f = bot[self.sel_e][1]
                self.eleccion = None
                f()
            elif k in ("DEL", "S:EXE", "AC"):
                self.cancelar()
            self.p.dirty_all = True
            return
        bot = self.botones()
        tipo, i = self.foco
        if k in ("DEL", "S:EXE"):
            self.atras()
        elif k == "UP":
            if tipo == "lista":
                self.foco = ("lista", max(0, i - 1))
            elif bot[i][3] == ROW2_Y:
                self.foco = ("boton", 0)
            elif self.filas:
                self.foco = ("lista", len(self.filas) - 1)
        elif k == "DOWN":
            if tipo == "lista" and i + 1 < len(self.filas):
                self.foco = ("lista", i + 1)
            elif tipo == "lista":
                self.foco = ("boton", 0)
            elif bot[i][3] == ROW1_Y:
                fila2 = [j for j, b in enumerate(bot) if b[3] == ROW2_Y]
                self.foco = ("boton", fila2[0] if fila2 else i)
        elif k in ("LEFT", "RIGHT") and tipo == "boton":
            self.foco = ("boton", (i + (1 if k == "RIGHT" else -1)) % len(bot))
        elif k == "EXE":
            if tipo == "lista":
                self.unirse()
            elif bot[i][5]:
                bot[i][1]()
        # que la partida elegida se vea
        if self.foco[0] == "lista":
            j = self.foco[1]
            if j < self.scroll:
                self.scroll = j
            elif j >= self.scroll + FILAS:
                self.scroll = j - FILAS + 1
        self.p.dirty_all = True

    def clic(self, mx, my):
        if self.eleccion:
            for i, (t, f, x, y, w) in enumerate(self.botones_e()):
                if x <= mx < x + w and y <= my < y + BTN_H:
                    self.eleccion = None
                    f()
                    break
            self.p.dirty_all = True
            return
        for i, b in enumerate(self.botones()):
            if b[2] <= mx < b[2] + b[4] and b[3] <= my < b[3] + BTN_H:
                self.foco = ("boton", i)
                if b[5]:
                    b[1]()
                self.p.dirty_all = True
                return
        if 10 <= mx < 310 and LIST_Y <= my < LIST_Y + LIST_H:
            j = self.scroll + (my - LIST_Y) // ROW_H
            if j < len(self.filas):
                if self.foco == ("lista", j):
                    self.unirse()                       # segundo clic: unirse
                self.foco = ("lista", j)
                self.p.dirty_all = True

    # ---- dibujo ------------------------------------------------------------------------
    def sombra(self, t, x, y, c=TXT, centro=False):
        if centro:
            x -= len(t) * 3
        P.texto(t, x + 1, y + 1, 0x2A2A2A)          # sombra, como el texto de Minecraft
        P.texto(t, x, y, c)

    def boton(self, t, x, y, w, foco, ok):
        P.rect(x, y, w, BTN_H, 0x000000)
        P.rect(x + 1, y + 1, w - 2, BTN_H - 2, BTN if ok else BTN_OFF)
        if ok:
            P.rect(x + 1, y + 1, w - 2, 1, BTN_LUZ)
            P.rect(x + 1, y + 1, 1, BTN_H - 2, BTN_LUZ)
            P.rect(x + 1, y + BTN_H - 2, w - 2, 1, BTN_SOMBRA)
            P.rect(x + w - 2, y + 1, 1, BTN_H - 2, BTN_SOMBRA)
        if foco:
            P.marco(x, y, w, BTN_H, 0xFFFFFF)
        t = t if len(t) * 6 <= w - 4 else t[:(w - 4) // 6]
        self.sombra(t, x + w // 2, y + 6, (TXT_SEL if foco else TXT) if ok else TXT_GRIS, True)

    def fondo(self):
        if self.tierra:                               # tierra como el menú de Minecraft
            s = P.sprite(self.tierra)
            esc = 32.0 / max(1, s.ancho)
            for y in range(0, H, 32):
                for x in range(0, W, 32):
                    P.dibujar(s, x, y, esc)
        else:
            P.rect(0, 0, W, H, 0x3B2A1E)
        P.rect(8, LIST_Y - 2, W - 16, LIST_H + 4, 0x120D09)   # la lista, más oscura

    def barras(self, x, y, estado):
        for i in range(5):
            h = 2 + i * 2
            c = (0x3CD23C if estado == "ok" else 0x5A5A5A)
            P.rect(x + i * 3, y + 10 - h, 2, h, c)
        if estado == "mal":
            P.texto("x", x + 4, y + 1, 0xFF5050)

    def dibujar(self):
        if self.eleccion:
            self.fondo()
            P.rect(8, LIST_Y - 2, W - 16, LIST_H + 4, 0x120D09)
            self.sombra(self.eleccion[0], W // 2, 7, 0xFFFFFF, True)
            self.sombra("Los demás se unirán a este mundo", W // 2, 32, TXT_GRIS, True)
            for i, (t, f, x, y, w) in enumerate(self.botones_e()):
                self.boton(t, x, y, w, i == self.sel_e, True)
            return
        self.fondo()
        titulo = "Jugadores" if self.m.on else "Multijugador"
        self.sombra(titulo, W // 2, 7, 0xFFFFFF, True)
        self.sombra("Tú: " + self.m.nombre_cfg[:12], W - 92, 7, TXT_GRIS)
        icono = P.sprite(self.icono) if self.icono else None
        for n in range(FILAS):
            j = self.scroll + n
            if j >= len(self.filas):
                break
            f = self.filas[j]
            y = LIST_Y + n * ROW_H
            if self.foco == ("lista", j):
                P.marco(10, y, W - 20, ROW_H - 2, 0xFFFFFF)
            if icono:
                P.dibujar(icono, 14, y + 3, 22.0 / max(1, icono.ancho))
            self.sombra(f["nombre"], 42, y + 4, 0xFFFFFF)
            self.sombra(f["detalle"][:38], 42, y + 16, TXT_GRIS)
            if f.get("jug"):
                P.texto(f["jug"], W - 70, y + 4, TXT_GRIS)
            if not self.m.on:
                self.barras(W - 30, y + 3, f.get("estado"))
        if len(self.filas) > FILAS:
            P.texto("%d-%d de %d" % (self.scroll + 1, min(len(self.filas), self.scroll + FILAS),
                                      len(self.filas)), W - 70, LIST_Y + LIST_H - 10, TXT_GRIS)
        if self.nota and not self.filas:
            self.sombra(self.nota[:48], W // 2, LIST_Y + LIST_H // 2 - 4, TXT_GRIS, True)
        elif self.nota:
            self.sombra(self.nota[:48], 14, LIST_Y + LIST_H - 10, TXT_GRIS)
        for i, (t, _, x, y, w, ok) in enumerate(self.botones()):
            self.boton(t, x, y, w, self.foco == ("boton", i), ok)
