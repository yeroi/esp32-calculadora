# =============================================================================
#  mc2d.py — Minecraft 2D para ESP32 SciCalc (MicroPython)
# -----------------------------------------------------------------------------
#  Un Minecraft de lado hecho para caber en el ESP32 sin PSRAM (~70 KB de
#  Python): el mundo es un bytearray de 200 x 64 bloques (12,5 KB) y solo se
#  redibuja lo que cambia (no hay framebuffer).
#
#  Qué tiene: generación con biomas (llanura, desierto, nieve, mar), cuevas,
#  menas (carbón, hierro, oro, diamante), árboles, picar con grietas y
#  herramientas, poner bloques, inventario de 27 huecos, fabricar (a mano, en
#  la mesa de trabajo y en el horno), comida y hambre, vida y caídas, día y
#  noche, cerdos y zombis, guardar y cargar mundos, y multijugador con
#  scicalc.red (el anfitrión manda su mundo; los bloques se sincronizan).
#  Sonidos: si tienes Paper Minecraft convertido, usa sus sonidos.
#
#  Controles (calculadora / teclado del PC):
#    ◄ ►  andar          ▲  saltar / nadar       ▼  (nada)
#    8 4 6 2  mover el cursor (teclado numérico)   5  picar / golpear (mantén)
#    EXE  poner bloque, comer, usar mesa u horno
#    1 3 o ( )  bloque anterior / siguiente      teclas 1-9 del PC: hueco
#    7 (o E)  inventario y fabricar      9 (o Q)  tirar uno
#    DEL  pausa (guardar)                AC  salir
#  Texturas propias (pc/mc2d_texturas.py), no son las de Mojang.
#
#  Este archivo vive en /lib y en el ESP32 va CONGELADO en el firmware (el
#  código está en la flash, no en los ~70 KB de RAM de Python). Se arranca con
#  /juegos/minecraft2d/minecraft2d.py, que solo hace "import mc2d; mc2d.main()"
#  (las texturas y los mundos van en esa carpeta).
# =============================================================================
import math
import random
import json
import os
from scicalc import pantalla as P, teclas as K
try:
    from scicalc import red
except ImportError:
    red = None

# ---- Bloques y objetos ----------------------------------------------------------
(AIRE, HIERBA, TIERRA, PIEDRA, ROCA, TRONCO, HOJAS, TABLONES, ARENA, GRAVA, CARBON_M,
 HIERRO_M, ORO_M, DIAMANTE_M, LECHO, AGUA, MESA, HORNO, CRISTAL, LADRILLOS, NIEVE,
 CACTUS, FLOR_R, FLOR_A, HIERBA_A, ANTORCHA) = range(26)
PALO, CARBON, LING_HIERRO, LING_ORO, DIAMANTE, MANZANA, CARNE, CARNE_ASADA, CARNE_POD = range(64, 73)
HERR = 80                    # herramientas: 80 + tipo * 4 + material
PICO, HACHA, PALA, ESPADA = 0, 1, 2, 3
TEX = {AIRE: "", HIERBA: "hierba", TIERRA: "tierra", PIEDRA: "piedra", ROCA: "roca",
       TRONCO: "tronco", HOJAS: "hojas", TABLONES: "tablones", ARENA: "arena", GRAVA: "grava",
       CARBON_M: "carbon_mena", HIERRO_M: "hierro_mena", ORO_M: "oro_mena",
       DIAMANTE_M: "diamante_mena", LECHO: "lecho", AGUA: "agua", MESA: "mesa", HORNO: "horno",
       CRISTAL: "cristal", LADRILLOS: "ladrillos", NIEVE: "nieve", CACTUS: "cactus",
       FLOR_R: "flor_roja", FLOR_A: "flor_amarilla", HIERBA_A: "hierba_alta",
       ANTORCHA: "antorcha", PALO: "palo", CARBON: "carbon", LING_HIERRO: "lingote_hierro",
       LING_ORO: "lingote_oro", DIAMANTE: "diamante", MANZANA: "manzana", CARNE: "carne",
       CARNE_ASADA: "carne_asada", CARNE_POD: "carne_podrida"}
NOMBRE = {HIERBA: "Hierba", TIERRA: "Tierra", PIEDRA: "Piedra", ROCA: "Roca", TRONCO: "Tronco",
          HOJAS: "Hojas", TABLONES: "Tablones", ARENA: "Arena", GRAVA: "Grava",
          CARBON_M: "Mena de carbon", HIERRO_M: "Mena de hierro", ORO_M: "Mena de oro",
          DIAMANTE_M: "Mena de diamante", MESA: "Mesa de trabajo", HORNO: "Horno",
          CRISTAL: "Cristal", LADRILLOS: "Ladrillos", NIEVE: "Nieve", CACTUS: "Cactus",
          FLOR_R: "Amapola", FLOR_A: "Diente de leon", ANTORCHA: "Antorcha", PALO: "Palo",
          CARBON: "Carbon", LING_HIERRO: "Lingote de hierro", LING_ORO: "Lingote de oro",
          DIAMANTE: "Diamante", MANZANA: "Manzana", CARNE: "Chuleta cruda",
          CARNE_ASADA: "Chuleta asada", CARNE_POD: "Carne podrida"}
MATS = ("madera", "piedra", "hierro", "diamante")
TIPOS = ("pico", "hacha", "pala", "espada")
for _t in range(4):
    for _m in range(4):
        TEX[HERR + _t * 4 + _m] = "%s_%s" % (TIPOS[_t], MATS[_m])
        NOMBRE[HERR + _t * 4 + _m] = "%s de %s" % (TIPOS[_t][0].upper() + TIPOS[_t][1:], MATS[_m])

NO_SOLIDO = (AIRE, AGUA, FLOR_R, FLOR_A, HIERBA_A, ANTORCHA)
TRANSP = (AIRE, AGUA, FLOR_R, FLOR_A, HIERBA_A, ANTORCHA, HOJAS, CRISTAL, CACTUS)
CAEN = (ARENA, GRAVA)
# dureza en ms con la mano, herramienta que acelera, nivel de pico necesario
# (-1 = se rompe con cualquier cosa; 0 = cualquier pico; 1 = piedra; 2 = hierro)
DUREZA = {HIERBA: (900, PALA, -1), TIERRA: (750, PALA, -1), ARENA: (750, PALA, -1),
          GRAVA: (900, PALA, -1), NIEVE: (500, PALA, -1), PIEDRA: (2200, PICO, 0),
          ROCA: (2600, PICO, 0), CARBON_M: (3000, PICO, 0), HIERRO_M: (3600, PICO, 1),
          ORO_M: (3600, PICO, 2), DIAMANTE_M: (4000, PICO, 2), LADRILLOS: (2600, PICO, 0),
          HORNO: (2600, PICO, 0), TRONCO: (2000, HACHA, -1), TABLONES: (1800, HACHA, -1),
          MESA: (1800, HACHA, -1), HOJAS: (300, -1, -1), CRISTAL: (400, -1, -1),
          CACTUS: (600, -1, -1), FLOR_R: (50, -1, -1), FLOR_A: (50, -1, -1),
          HIERBA_A: (50, -1, -1), ANTORCHA: (50, -1, -1)}
SUELTA = {HIERBA: TIERRA, PIEDRA: ROCA, CARBON_M: CARBON, DIAMANTE_M: DIAMANTE,
          HIERBA_A: AIRE, CRISTAL: AIRE, HOJAS: AIRE, NIEVE: NIEVE}
COMIDA = {MANZANA: 4, CARNE: 3, CARNE_ASADA: 8, CARNE_POD: 2}
DANO = {ESPADA: (4, 5, 6, 7)}                       # daño por material

# Recetas: (resultado, cantidad, {ingrediente: n}, sitio)   sitio: "" mano, "mesa", "horno"
RECETAS = [
    (TABLONES, 4, {TRONCO: 1}, ""), (PALO, 4, {TABLONES: 2}, ""), (MESA, 1, {TABLONES: 4}, ""),
    (ANTORCHA, 4, {PALO: 1, CARBON: 1}, ""),
    (HORNO, 1, {ROCA: 8}, "mesa"), (LADRILLOS, 1, {ROCA: 4}, "mesa"),
    (LING_HIERRO, 1, {HIERRO_M: 1, CARBON: 1}, "horno"), (LING_ORO, 1, {ORO_M: 1, CARBON: 1}, "horno"),
    (CARNE_ASADA, 1, {CARNE: 1, CARBON: 1}, "horno"), (CRISTAL, 1, {ARENA: 1, CARBON: 1}, "horno"),
]
for _m, _mat in enumerate((TABLONES, ROCA, LING_HIERRO, DIAMANTE)):
    RECETAS.append((HERR + PICO * 4 + _m, 1, {_mat: 3, PALO: 2}, "mesa"))
    RECETAS.append((HERR + HACHA * 4 + _m, 1, {_mat: 3, PALO: 2}, "mesa"))
    RECETAS.append((HERR + PALA * 4 + _m, 1, {_mat: 1, PALO: 2}, "mesa"))
    RECETAS.append((HERR + ESPADA * 4 + _m, 1, {_mat: 2, PALO: 1}, "mesa"))

# ---- Mundo y pantalla -------------------------------------------------------------
W, H = 200, 64
MAR = 30
T = 16                                  # píxeles por bloque
VIEW_H = 184                            # zona del mundo; debajo, vida y barra de objetos
VW, VH = P.ANCHO // T + 1, VIEW_H // T + 1
CIELO_DIA, CIELO_NOCHE, FONDO_CUEVA, OSCURO = 0x78A8F0, 0x101830, 0x3A3530, 0x0C0C0C
DIA_S = 600                             # un día dura 10 minutos (7 de día y 3 de noche)
SALA = "minecraft2d"
mundo = bytearray(W * H)
alto = bytearray(W)                     # primer bloque sólido desde arriba de cada columna

# ---- Física (en bloques y segundos) -------------------------------------------------
PW, PH = 0.6, 1.8
GRAV, MAX_CAIDA = 32.0, 24.0
ANDAR, SALTO = 4.3, 9.0
DT = 1 / 30
ALCANCE = 4


def g(x, y):
    if 0 <= x < W and 0 <= y < H:
        return mundo[x + y * W]
    return LECHO if y < 0 else AIRE


def sp(x, y, b):
    mundo[x + y * W] = b


def solido(b):
    return b not in NO_SOLIDO


NO_SUELO = (AIRE, AGUA, FLOR_R, FLOR_A, HIERBA_A, ANTORCHA, HOJAS, TRONCO, CACTUS)


def calc_alto(x):
    # la superficie: el primer bloque de "terreno" desde arriba (los árboles no
    # cuentan: debajo de las hojas sigue siendo cielo)
    y = H - 1
    while y > 0 and mundo[x + y * W] in NO_SUELO:
        y -= 1
    alto[x] = y


# ---- Sonido (los de Paper Minecraft convertido, si están) ----------------------------
SND = {}


def buscar_sonidos():
    if not hasattr(P, "sonar"):
        return                                   # (en el ESP32 aún no hay altavoz)
    try:
        for d in os.listdir("/scratch"):
            ruta = "/scratch/%s/snd/indice.json" % d
            try:
                with open(ruta) as f:
                    idx = json.loads(f.read())
            except OSError:
                continue
            if "grass1" in idx or "grass1.wav" in idx:
                for k, v in idx.items():
                    SND[k] = "/scratch/%s/%s" % (d, v)
                return
    except OSError:
        pass


def sonar(nombre, vol=0.7):
    r = SND.get(nombre)
    if r:
        P.sonar(r, vol)


def sonar_bloque(b, vol=0.5):
    m = ("grass" if b in (HIERBA, TIERRA, HOJAS, HIERBA_A, FLOR_R, FLOR_A, NIEVE, CACTUS) else
         "sand" if b == ARENA else "gravel" if b == GRAVA else
         "wood" if b in (TRONCO, TABLONES, MESA) else "stone")
    sonar("%s%d" % (m, random.randint(1, 4)), vol)


# ---- Generación del mundo --------------------------------------------------------------
def progreso(texto, frac):
    P.rect(60, 140, 200, 8, 0x303440)
    P.rect(60, 140, int(200 * frac), 8, 0x5CBF3A)
    P.rect(0, 156, P.ANCHO, 12, 0)
    P.texto(texto, 60, 156, 0xA0A0A0)
    P.mostrar()                                  # además mantiene vivo el watchdog


def generar(semilla):
    random.seed(semilla)
    for i in range(W * H):
        mundo[i] = AIRE
    # biomas: trozos de 30-60 columnas
    bioma = bytearray(W)
    x = 0
    while x < W:
        n = random.randint(30, 60)
        b = random.choice((0, 0, 0, 1, 2))       # 0 llanura, 1 desierto, 2 nieve
        for i in range(x, min(W, x + n)):
            bioma[i] = b
        x += n
    ondas = [(random.uniform(8, 20), random.uniform(1, 3), random.uniform(0, 6)),
             (random.uniform(25, 50), random.uniform(3, 7), random.uniform(0, 6))]
    progreso("Generando el terreno...", 0.1)
    for x in range(W):
        h = 34.0
        for per, amp, fase in ondas:
            h += math.sin(x / per + fase) * amp
        if bioma[x] == 2:
            h += 4
        h = int(max(18, min(H - 10, h)))
        tierra = random.randint(3, 4)
        for y in range(1, h + 1):
            if y > h - tierra:
                b = ARENA if bioma[x] == 1 else TIERRA
                if y == h:
                    b = ARENA if (bioma[x] == 1 or h <= MAR + 1) else (NIEVE if bioma[x] == 2 else HIERBA)
            else:
                b = PIEDRA
            mundo[x + y * W] = b
        mundo[x] = LECHO
        if random.random() < 0.5:
            mundo[x + W] = LECHO
        for y in range(h + 1, MAR + 1):          # mar
            mundo[x + y * W] = AGUA
    progreso("Cavando cuevas...", 0.35)
    for _ in range(W // 18):
        cx, cy = random.uniform(0, W), random.uniform(6, 30)
        ang, r = random.uniform(0, 6.28), random.uniform(1.0, 1.8)
        for _ in range(random.randint(25, 60)):
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    xx, yy = int(cx + dx), int(cy + dy)
                    if dx * dx + dy * dy <= r * r * 1.4 and 0 <= xx < W and 2 <= yy < H:
                        if mundo[xx + yy * W] in (PIEDRA, TIERRA, GRAVA):
                            mundo[xx + yy * W] = AIRE
            ang += random.uniform(-0.6, 0.6)
            cx += math.cos(ang) * 1.5
            cy += math.sin(ang) * 0.8
            cy = max(4, min(40, cy))
    progreso("Escondiendo menas...", 0.55)
    for b, n, ymax, tam in ((CARBON_M, W // 3, 48, 5), (HIERRO_M, W // 5, 32, 4),
                            (ORO_M, W // 12, 18, 3), (DIAMANTE_M, W // 20, 11, 3),
                            (GRAVA, W // 8, 40, 5)):
        for _ in range(n):
            x, y = random.randrange(W), random.randint(2, ymax)
            for _ in range(tam):
                if mundo[x + y * W] == PIEDRA:
                    mundo[x + y * W] = b
                x = max(0, min(W - 1, x + random.randint(-1, 1)))
                y = max(2, min(H - 1, y + random.randint(-1, 1)))
    progreso("Plantando arboles...", 0.75)
    for x in range(W):
        calc_alto(x)
    x = 3
    while x < W - 3:
        y = alto[x]
        top = mundo[x + y * W]
        if top == HIERBA and random.random() < 0.13:
            arbol(x, y + 1, bioma[x] == 2)
            x += 4
            continue
        if top == ARENA and bioma[x] == 1 and y > MAR and random.random() < 0.07:
            for i in range(random.randint(1, 3)):
                if y + 1 + i < H:
                    mundo[x + (y + 1 + i) * W] = CACTUS
            x += 3
            continue
        if top == HIERBA and y + 1 < H:
            r = random.random()
            if r < 0.15:
                mundo[x + (y + 1) * W] = HIERBA_A
            elif r < 0.2:
                mundo[x + (y + 1) * W] = random.choice((FLOR_R, FLOR_A))
        x += 1
    for x in range(W):
        calc_alto(x)
    progreso("Listo", 1.0)


def arbol(x, y, nieve):
    alto_t = random.randint(4, 6)
    for i in range(alto_t):
        if y + i < H:
            mundo[x + (y + i) * W] = TRONCO
    top = y + alto_t
    for dy in range(-2, 2):
        r = 2 if dy < 0 else 1
        for dx in range(-r, r + 1):
            xx, yy = x + dx, top + dy
            if 0 <= xx < W and 0 <= yy < H and mundo[xx + yy * W] == AIRE:
                mundo[xx + yy * W] = HOJAS


# ---- Inventario -------------------------------------------------------------------------
NHUECOS = 27
inv_id = bytearray(NHUECOS)
inv_n = bytearray(NHUECOS)


def max_pila(it):
    return 1 if it >= HERR else 64


def dar(it, n=1):
    """Mete n objetos; devuelve los que no caben."""
    for i in range(NHUECOS):                         # primero, donde ya hay
        if inv_id[i] == it and inv_n[i] < max_pila(it):
            k = min(n, max_pila(it) - inv_n[i])
            inv_n[i] += k
            n -= k
            if not n:
                return 0
    for i in range(NHUECOS):
        if not inv_id[i]:
            k = min(n, max_pila(it))
            inv_id[i], inv_n[i] = it, k
            n -= k
            if not n:
                return 0
    return n


def cuantos(it):
    n = 0
    for i in range(NHUECOS):
        if inv_id[i] == it:
            n += inv_n[i]
    return n


def quitar(it, n=1):
    for i in range(NHUECOS - 1, -1, -1):
        if inv_id[i] == it:
            k = min(n, inv_n[i])
            inv_n[i] -= k
            n -= k
            if not inv_n[i]:
                inv_id[i] = 0
            if not n:
                return


# ---- Sprites ---------------------------------------------------------------------------------
SPR = {}


def spr(nombre):
    s = SPR.get(nombre)
    if s is None:
        s = SPR[nombre] = P.sprite("tex/%s.png" % nombre)
    return s


def icono(it, x, y, n=0):
    if it:
        P.dibujar(spr(TEX[it]), x, y)
        if n > 1:
            P.texto(str(n), x + 16 - 6 * len(str(n)), y + 9, 0xFFFFFF)


# ---- Juego ---------------------------------------------------------------------------------
class Juego:
    def __init__(self, nombre, online=False):
        self.nombre = nombre
        self.online = online
        self.x, self.y = W / 2, 0.0
        self.vx = self.vy = 0.0
        self.suelo = False
        self.cara = 1
        self.vida, self.hambre = 20, 20
        self.hambre_t = 0.0
        self.caida_y = None
        self.cdx, self.cdy = 1, -1                # cursor: el bloque de delante, a los pies
        self.sel = 0
        self.tiempo = 60.0                        # segundos del día (empieza por la mañana)
        self.pico = (-1, -1, 0.0)                 # bloque que se está picando y cuánto
        self.anda_t = 0.0
        self.paso_t = 0.0
        self.golpe_t = 0.0                        # animación del brazo
        self.dano_t = 0.0
        self.mobs = []                            # [tipo, x, y, vx, vy, vida, cara, t]
        self.otros = {}                           # id -> [x, y, cara, anim, objeto, nombre]
        self.enviado = None
        self.cuadro = 0
        self.completo = True
        self.sucios = []                          # bloques cambiados
        self.pintado = []                         # zonas (x0, y0, x1, y1) tapadas el fotograma pasado
        self.hud = None
        self.aviso = None
        self.cielo = CIELO_DIA
        self.tap = {}                             # teclas tocadas en el PC (WASD): hasta cuándo
        self.salir = False

    # ---- aparecer --------------------------------------------------------------
    def aparecer(self):
        x = W // 2                                # en tierra firme, no en el mar ni en un árbol
        for d in range(W // 2):
            for c in (W // 2 + d, W // 2 - d):
                if 0 <= c < W and alto[c] > MAR and not solido(g(c, alto[c] + 1)) \
                        and not solido(g(c, alto[c] + 2)):
                    x = c
                    break
            else:
                continue
            break
        self.x, self.y = x + 0.2, alto[x] + 1.0
        self.vx = self.vy = 0.0
        self.centrar()

    # ---- cámara y dibujo -------------------------------------------------------
    def centrar(self):
        self.cam_x = int(self.x) - VW // 2
        self.cam_top = int(self.y) + VH // 2 + 1
        self.completo = True

    def pant(self, wx, wy):
        return int((wx - self.cam_x) * T), int((self.cam_top - wy) * T)

    def fondo(self, tx, ty):
        if ty > alto[tx] if 0 <= tx < W else True:
            return self.cielo
        return FONDO_CUEVA

    def encerrado(self, tx, ty):
        # bloque sólido sin aire alrededor y bajo la superficie: oscuro (como en las cuevas)
        if ty >= (alto[tx] if 0 <= tx < W else 0) - 5:
            return False                          # cerca de la superficie se ve todo
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if g(tx + dx, ty + dy) in TRANSP:
                return False
        return True

    def bloque(self, tx, ty):
        sx, sy = self.pant(tx, ty + 1)
        if sy >= VIEW_H or sx >= P.ANCHO or sx + T <= 0 or sy + T <= 0:
            return
        b = g(tx, ty)
        if b in TRANSP:
            P.rect(sx, sy, T, T, self.fondo(tx, ty))
            if b:
                P.dibujar(spr(TEX[b]), sx, sy)
        elif self.encerrado(tx, ty):
            P.rect(sx, sy, T, T, OSCURO)
        else:
            P.dibujar(spr(TEX[b]), sx, sy)

    def zona(self, x0, y0, x1, y1):
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                self.bloque(tx, ty)

    def objetivo(self):
        return int(self.x + PW / 2) + self.cdx, int(self.y + 0.01) + self.cdy

    def dibujar_hud(self):
        estado = (self.vida, self.hambre, self.sel, bytes(inv_id[:9]), bytes(inv_n[:9]), self.aviso)
        if estado == self.hud:
            return
        self.hud = estado
        P.recorte()
        P.rect(0, VIEW_H, P.ANCHO, P.ALTO - VIEW_H, 0x1A1A1A)
        for i in range(10):                       # corazones y comida, como en Minecraft
            P.dibujar(spr("corazon" + medio(self.vida, i)), 70 + i * 9, VIEW_H + 2)
            P.dibujar(spr("comida" + medio(self.hambre, i)), 242 - i * 9, VIEW_H + 2)
        x0 = 70
        for i in range(9):
            x = x0 + i * 20
            P.rect(x, VIEW_H + 12, 20, 22, 0x8B8B8B if i == self.sel else 0x4A4A4A)
            P.rect(x + 1, VIEW_H + 13, 18, 20, 0x2A2A2A)
            icono(inv_id[i], x + 2, VIEW_H + 15, inv_n[i])
        nom = NOMBRE.get(inv_id[self.sel], "")
        P.texto((self.aviso or nom)[:10], 2, VIEW_H + 20, 0xFFFFA0 if self.aviso else 0xC0C0C0)
        if self.online and red:
            P.texto("%d jug" % len(red.jugadores()), 278, VIEW_H + 20, 0x50DC78)

    def caja_jugador(self, x, y):
        sx, sy = self.pant(x + PW / 2, y)
        return sx - 7, sy - 29, sx + 7, sy + 1     # px

    def a_bloques(self, x0, y0, x1, y1):
        # rectángulo de pantalla -> bloques que lo cubren
        tx0 = self.cam_x + x0 // T
        tx1 = self.cam_x + x1 // T
        ty1 = self.cam_top - y0 // T
        ty0 = self.cam_top - (y1 - 1) // T - 1
        return (tx0 - 1, ty0, tx1 + 1, ty1)

    def pintar(self):
        sx, sy = self.pant(self.x, self.y + PH)
        if sx < P.ANCHO * 0.25 or sx > P.ANCHO * 0.7 or sy < VIEW_H * 0.15 or sy + PH * T > VIEW_H * 0.85:
            self.centrar()
        P.recorte(0, 0, P.ANCHO, VIEW_H)
        if self.completo:
            self.completo = False
            self.sucios = []
            self.pintado = []
            self.zona(self.cam_x, self.cam_top - VH, self.cam_x + VW, self.cam_top)
        else:
            for z in self.pintado:
                self.zona(*z)
            for bx, by in self.sucios:
                self.bloque(bx, by)
            self.sucios = []
        self.pintado = []
        # mobs
        for m in self.mobs:
            nom = "cerdo" if m[0] == 0 else "zombi"
            if m[0] == 0:
                ax, ay = self.pant(m[1], m[2] + 0.75)
                P.dibujar(spr(nom), ax - 8, ay, 1, m[6] < 0)
                self.pintado.append(self.a_bloques(ax - 8, ay, ax + 8, ay + 12))
            else:
                x0, y0, x1, y1 = self.caja_jugador(m[1], m[2])
                P.dibujar(spr(nom), x0 + 1, y0 + 1, 1, m[6] < 0)
                self.pintado.append(self.a_bloques(x0, y0, x1, y1))
        # otros jugadores
        for o in self.otros.values():
            x0, y0, x1, y1 = self.caja_jugador(o[0], o[1])
            if x1 < 0 or x0 > P.ANCHO:
                continue
            P.dibujar(spr("jugador_andar" if o[3] else "jugador"), x0 + 1, y0 + 1, 1, o[2] < 0)
            if o[4]:
                P.dibujar(spr(TEX[o[4]]), (x0 + 8) if o[2] > 0 else (x0 - 8), y0 + 12, 0.75)
            w = len(o[5]) * 6
            P.texto(o[5], (x0 + x1) // 2 - w // 2, y0 - 10, 0xFFFFFF, 0x202020)
            self.pintado.append(self.a_bloques(min(x0 - 8, (x0 + x1) // 2 - w // 2), y0 - 10,
                                               max(x1 + 8, (x0 + x1) // 2 + w // 2), y1))
        # yo
        x0, y0, x1, y1 = self.caja_jugador(self.x, self.y)
        andar = abs(self.vx) > 0.5 and self.suelo and int(self.anda_t * 6) % 2
        P.dibujar(spr("jugador_andar" if andar else "jugador"), x0 + 1, y0 + 1, 1, self.cara < 0)
        it = inv_id[self.sel]
        if it:
            off = 2 if self.golpe_t > 0 and int(self.golpe_t * 20) % 2 else 0
            P.dibujar(spr(TEX[it]), (x0 + 8 + off) if self.cara > 0 else (x0 - 8 - off), y0 + 12, 0.75)
        self.pintado.append(self.a_bloques(x0 - 10, y0, x1 + 10, y1))
        # cursor y grieta
        tx, ty = self.objetivo()
        cx, cy = self.pant(tx, ty + 1)
        bx, by, prog = self.pico
        if (bx, by) == (tx, ty) and prog > 0:
            P.dibujar(spr("grieta%d" % max(1, min(8, int(prog * 8) + 1))), cx, cy)
        P.marco(cx, cy, T, T, 0x000000)
        self.pintado.append((tx, ty, tx, ty))
        P.recorte()
        self.dibujar_hud()

    # ---- bloques ------------------------------------------------------------------
    def poner(self, x, y, b, red_tambien=True):
        if not (0 <= x < W and 0 <= y < H):
            return
        sp(x, y, b)
        calc_alto(x)
        for dx in (-1, 0, 1):                       # los vecinos pueden pasar a verse
            for dy in (-1, 0, 1):
                self.sucios.append((x + dx, y + dy))
        if red_tambien and self.online:
            red.var("b:%d" % (x + y * W), b)

    def asentar(self, x, y):
        while y < H and g(x, y) in CAEN:
            yy = y
            while yy > 1 and g(x, yy - 1) in (AIRE, AGUA, HIERBA_A):
                self.poner(x, yy - 1, g(x, yy))
                self.poner(x, yy, AIRE)
                yy -= 1
            y += 1

    def toca_jugador(self, tx, ty):
        return tx + 1 > self.x and tx < self.x + PW and ty + 1 > self.y and ty < self.y + PH

    def herramienta(self):
        it = inv_id[self.sel]
        if it >= HERR:
            return (it - HERR) // 4, (it - HERR) % 4
        return -1, -1

    def picar(self, dt):
        tx, ty = self.objetivo()
        b = g(tx, ty)
        if not b or b in (AGUA, LECHO) or b not in DUREZA:
            self.pico = (-1, -1, 0.0)
            return
        tipo, mat = self.herramienta()
        ms, buena, nivel = DUREZA[b]
        if tipo == buena and tipo >= 0:
            ms = ms / (2 + mat * 2)
        bx, by, prog = self.pico
        if (bx, by) != (tx, ty):
            prog = 0.0
        prog += dt * 1000 / ms
        self.golpe_t = 0.25
        if int(prog * 8) != int(self.pico[2] * 8) or (bx, by) != (tx, ty):
            sonar_bloque(b, 0.25)
            self.sucios.append((tx, ty))
        if prog >= 1.0:
            self.poner(tx, ty, AIRE)
            ok = nivel < 0 or (tipo == PICO and mat >= nivel)
            if ok:
                it = SUELTA.get(b, b)
                if b == HOJAS and random.random() < 0.08:
                    it = MANZANA
                if it:
                    dar(it)
            sonar_bloque(b, 0.7)
            self.asentar(tx, ty + 1)
            if g(tx, ty + 1) in (FLOR_R, FLOR_A, HIERBA_A, ANTORCHA, CACTUS) and b != CACTUS:
                pass
            if g(tx, ty + 1) in (FLOR_R, FLOR_A, HIERBA_A, ANTORCHA):
                self.poner(tx, ty + 1, AIRE)
            prog = 0.0
        self.pico = (tx, ty, prog)

    def usar(self):
        tx, ty = self.objetivo()
        b = g(tx, ty)
        if b in (MESA, HORNO):
            self.abrir_inventario("mesa" if b == MESA else "horno")
            return
        it = inv_id[self.sel]
        if it in COMIDA and self.hambre < 20:
            self.hambre = min(20, self.hambre + COMIDA[it])
            quitar(it)
            sonar("eat%d" % random.randint(1, 3))
            return
        if not it or it >= 64 or it == AGUA:
            return
        if b not in (AIRE, AGUA, HIERBA_A):
            return
        if solido(it) and (self.toca_jugador(tx, ty) or self.mob_en(tx, ty)):
            return
        apoyo = False                             # como en Minecraft: junto a otro bloque
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if g(tx + dx, ty + dy) not in (AIRE, AGUA):
                apoyo = True
        if not apoyo:
            return
        quitar(it)
        self.poner(tx, ty, it)
        sonar_bloque(it, 0.6)
        self.asentar(tx, ty)
        self.golpe_t = 0.2

    def mob_en(self, tx, ty):
        for m in self.mobs:
            if int(m[1]) == tx and int(m[2]) <= ty <= int(m[2] + 1):
                return m
        return None

    def golpear(self):
        tx, ty = self.objetivo()
        m = self.mob_en(tx, ty) or self.mob_en(tx - 1 if self.cara < 0 else tx + 1, ty)
        if not m:
            return False
        tipo, mat = self.herramienta()
        dano = DANO[ESPADA][mat] if tipo == ESPADA else (2 if tipo >= 0 else 1)
        m[5] -= dano
        m[3] = 5.0 * self.cara
        m[4] = 5.0
        self.golpe_t = 0.25
        sonar(("pig%d" if m[0] == 0 else "zombiehurt%d") % random.randint(1, 2), 0.6)
        if m[5] <= 0:
            self.mobs.remove(m)
            sonar("pigdeath" if m[0] == 0 else "zombiedeath", 0.7)
            dar(CARNE if m[0] == 0 else CARNE_POD, random.randint(1, 2))
        return True

    # ---- física --------------------------------------------------------------------
    def libre_col(self, tx, y0, y1):
        for ty in range(y0, y1 + 1):
            if solido(g(tx, ty)):
                return False
        return True

    def mover_x(self, e, dx):
        e[0] += dx
        x, y = e[0], e[1]
        w, h = e[4], e[5]
        if dx > 0:
            tx = int(x + w - 1e-6)
        elif dx < 0:
            tx = math.floor(x)
        else:
            return
        y0, y1 = int(y), int(y + h - 1e-6)
        if self.libre_col(tx, y0, y1):
            return
        if e[3] and self.libre_col(tx, y0 + 1, y1 + 1) and self.libre_col(int(x), y1 + 1, y1 + 1) \
                and self.libre_col(int(x + w - 1e-6), y1 + 1, y1 + 1):
            e[1] = y0 + 1.0                       # subir escalones de un bloque
            return
        e[0] = (tx - w) if dx > 0 else (tx + 1.0)
        e[2] = 0.0

    def mover_y(self, e, dy):
        e[1] += dy
        x, w, h = e[0], e[4], e[5]
        x0, x1 = int(x), int(x + w - 1e-6)
        if dy < 0:
            ty = math.floor(e[1])
            for tx in range(x0, x1 + 1):
                if solido(g(tx, ty)):
                    e[1], e[3] = ty + 1.0, True
                    return True
        elif dy > 0:
            ty = int(e[1] + h - 1e-6)
            for tx in range(x0, x1 + 1):
                if solido(g(tx, ty)):
                    e[1] = ty - h
                    return True
        e[3] = False
        return False

    def fisica(self, dt):
        izq = K.pulsada("LEFT") or self.tap.get("a", 0) > 0
        der = K.pulsada("RIGHT") or self.tap.get("d", 0) > 0
        arriba = K.pulsada("UP") or self.tap.get("w", 0) > 0 or self.tap.get(" ", 0) > 0
        agua = g(int(self.x + PW / 2), int(self.y + 0.5)) == AGUA
        obj = ANDAR * (0.6 if agua else 1.0)
        if izq and not der:
            self.vx, self.cara = -obj, -1
        elif der and not izq:
            self.vx, self.cara = obj, 1
        else:
            self.vx = 0.0
        if agua:
            self.vy = max(-3.0, self.vy - GRAV * 0.25 * dt)
            if arriba:
                self.vy = 3.5
            self.caida_y = None
        else:
            if arriba and self.suelo:
                self.vy = SALTO
                self.suelo = False
            self.vy = max(-MAX_CAIDA, self.vy - GRAV * dt)
        e = [self.x, self.y, self.vx, self.suelo, PW, PH]
        self.mover_x(e, self.vx * dt)
        estaba = self.suelo
        golpe = self.mover_y(e, self.vy * dt)
        self.x, self.y, self.vx, self.suelo = e[0], e[1], e[2], e[3]
        if golpe:
            self.vy = 0.0
        # caídas
        if not self.suelo and not agua:
            if self.caida_y is None or self.y > self.caida_y:
                self.caida_y = self.y
        if self.suelo and not estaba and self.caida_y is not None:
            caida = self.caida_y - self.y
            if caida > 3.5:
                self.herir(int(caida - 3), "fallbig1" if caida > 6 else "fallsmall")
            self.caida_y = None
        if self.suelo and abs(self.vx) > 0.1:
            self.anda_t += dt
            self.paso_t -= dt
            if self.paso_t <= 0:
                self.paso_t = 0.38
                sonar_bloque(g(int(self.x + PW / 2), int(self.y - 0.5)), 0.25)
        if self.x < 0:
            self.x = 0.0
        if self.x > W - PW:
            self.x = W - PW
        if self.y < -5:
            self.herir(20, "hurt")

    def herir(self, n, sonido="hurt"):
        if n <= 0:
            return
        self.vida = max(0, self.vida - n)
        self.dano_t = 0.5
        sonar(sonido, 0.8)

    # ---- mobs ---------------------------------------------------------------------
    def es_noche(self):
        return self.tiempo % DIA_S > DIA_S * 0.7

    def mobs_paso(self, dt):
        # aparecer (cerca del jugador, fuera de la pantalla)
        zombis = sum(1 for m in self.mobs if m[0] == 1)
        if len(self.mobs) < 5 and random.random() < dt * (0.12 if self.es_noche() else 0.25):
            lado = random.choice((-1, 1))
            x = int(self.x) + lado * random.randint(12, 18)
            if 0 <= x < W:
                y = alto[x] + 1
                top = g(x, alto[x])
                if self.es_noche():
                    if zombis < 3:
                        self.mobs.append([1, x + 0.2, float(y), 0.0, 0.0, 20, -lado, 0.0])
                elif top == HIERBA:
                    self.mobs.append([0, x + 0.2, float(y), 0.0, 0.0, 10, 1, 0.0])
        for m in list(self.mobs):
            if abs(m[1] - self.x) > 40:
                self.mobs.remove(m)
                continue
            if m[0] == 1 and not self.es_noche() and m[2] >= alto[min(W - 1, max(0, int(m[1])))]:
                self.mobs.remove(m)               # los zombis se van al amanecer
                continue
            m[7] -= dt
            if m[0] == 1:                         # zombi: hacia el jugador
                d = self.x - m[1]
                m[6] = 1 if d > 0 else -1
                vx = 2.2 * m[6] if abs(d) > 0.5 else 0.0
                if abs(d) < 0.8 and abs(self.y - m[2]) < 1.5 and m[7] <= 0:
                    self.herir(2)
                    self.vx = 6.0 * m[6]
                    m[7] = 1.2
                if random.random() < dt * 0.3:
                    sonar("zombie%d" % random.randint(1, 3), 0.4)
            else:                                 # cerdo: pasea
                if m[7] <= 0:
                    m[7] = random.uniform(1.5, 4.0)
                    m[6] = random.choice((-1, 0, 1))
                vx = 1.2 * m[6]
                if random.random() < dt * 0.05:
                    sonar("pig%d" % random.randint(1, 3), 0.3)
            if abs(m[3]) > 0.1:                   # empujón al golpearlo
                vx = m[3]
                m[3] *= 0.85
            alto_m = 0.75 if m[0] == 0 else PH
            e = [m[1], m[2], vx, False, 0.8 if m[0] == 0 else PW, alto_m]
            m[4] = max(-MAX_CAIDA, m[4] - GRAV * dt)
            self.mover_x(e, vx * dt)
            if e[2] == 0.0 and vx and abs(m[4]) < 0.01:
                m[4] = SALTO * 0.8                  # saltar un obstáculo
            golpe = self.mover_y(e, m[4] * dt)
            if golpe:
                m[4] = 0.0
            m[1], m[2] = e[0], e[1]
            if m[6] == 0:
                m[6] = 1

    # ---- red --------------------------------------------------------------------------
    def red_paso(self):
        if not self.online:
            return
        self.cuadro += 1
        if self.cuadro % 3 == 0:
            d = {"p": [round(self.x, 2), round(self.y, 2), self.cara,
                       1 if abs(self.vx) > 0.5 else 0, inv_id[self.sel]]}
            if d != self.enviado:
                red.enviar(d)
                self.enviado = d
        for m in red.recibir():
            t = m.get("t")
            if t == "de" and "p" in m.get("d", {}):
                p = m["d"]["p"]
                o = self.otros.get(m["id"])
                nombre = str(red.jugadores().get(m["id"], "?"))[:10]
                self.otros[m["id"]] = [p[0], p[1], p[2], p[3], p[4], nombre]
            elif t == "var" and str(m.get("n", "")).startswith("b:"):
                i = int(m["n"][2:])
                if 0 <= i < W * H and m["id"] != red.mi_id():
                    self.poner(i % W, i // W, int(m["v"]), False)
            elif t == "entra":
                self.enviado = None
                self.aviso = "%s entra" % m.get("nombre", "?")
                self.aviso_t = 3.0
            elif t == "sale":
                self.otros.pop(m.get("id"), None)
                self.completo = True
            elif t == "estado" and m.get("e") != "conectado":
                self.online = False
                self.otros = {}
                self.aviso = "Sin conexion"
                self.aviso_t = 3.0

    # ---- inventario y fabricar ---------------------------------------------------------
    def cerca(self, b):
        cx, cy = int(self.x), int(self.y)
        for dx in range(-4, 5):
            for dy in range(-3, 4):
                if g(cx + dx, cy + dy) == b:
                    return True
        return False

    def abrir_inventario(self, sitio=None):
        if sitio is None:
            sitio = "horno" if self.cerca(HORNO) else ("mesa" if self.cerca(MESA) else "")
        sitios = ("", "mesa") if sitio == "mesa" else (("", "mesa", "horno") if sitio == "horno" and self.cerca(MESA)
                                                      else ("", sitio))
        recetas = [r for r in RECETAS if r[3] in sitios]
        sel, coger = 0, None
        n_rec = len(recetas)
        while True:
            P.recorte()
            P.rect(10, 6, 300, 206, 0xC6C6C6)
            P.marco(10, 6, 300, 206, 0x000000)
            P.texto("Inventario", 18, 12, 0x404040)
            P.texto({"": "Fabricar (a mano)", "mesa": "Mesa de trabajo", "horno": "Horno"}[sitio],
                    170, 12, 0x404040)
            for i in range(NHUECOS):
                x, y = 18 + (i % 9) * 20, 26 + (i // 9) * 22 + (6 if i < 9 else 0)
                if i < 9:
                    y = 26 + 2 * 22 + 10           # la barra, abajo como en Minecraft
                else:
                    y = 26 + (i // 9 - 1) * 22
                P.rect(x, y, 19, 21, 0x8B8B8B)
                P.rect(x + 1, y + 1, 17, 19, 0x6E6E6E if coger != i else 0xA0A050)
                icono(inv_id[i], x + 1, y + 2, inv_n[i])
                if sel == i:
                    P.marco(x - 1, y - 1, 21, 23, 0xFFFFFF)
            # recetas
            y0 = 112
            P.texto("Recetas (EXE fabrica):", 18, y0 - 10, 0x404040)
            top = max(0, sel - NHUECOS - 3) if sel >= NHUECOS else 0
            for j in range(top, min(n_rec, top + 5)):
                r = recetas[j]
                y = y0 + (j - top) * 18
                ok = all(cuantos(k) >= v for k, v in r[2].items())
                P.rect(18, y, 284, 16, 0xFFFFFF if sel == NHUECOS + j else 0xB0B0B0)
                icono(r[0], 20, y)
                txt = "%s x%d  <-  " % (NOMBRE[r[0]][:16], r[1]) + ", ".join(
                    "%d %s" % (v, NOMBRE[k][:9]) for k, v in r[2].items())
                P.texto(txt[:44], 38, y + 4, 0x206020 if ok else 0x802020)
            nom = NOMBRE.get(inv_id[sel], "") if sel < NHUECOS else ""
            P.rect(18, 202, 284, 9, 0xC6C6C6)
            P.texto(nom or "EXE: coger/soltar · 9: tirar · 7/DEL: cerrar", 18, 202, 0x404040)
            P.mostrar()
            fin = False
            for k, sh in K.eventos():
                if k in ("7", "DEL", "CH:e", "CH:E"):
                    fin = True
                elif k == "RIGHT" and sel < NHUECOS:
                    sel = (sel + 1) % NHUECOS
                elif k == "LEFT" and sel < NHUECOS:
                    sel = (sel - 1) % NHUECOS
                elif k == "UP":
                    if sel >= NHUECOS:
                        sel = sel - 1 if sel > NHUECOS else 0
                    elif sel >= 18:
                        sel -= 9
                    elif sel < 9:
                        sel += 18
                elif k == "DOWN":
                    if sel >= NHUECOS:
                        sel = min(NHUECOS + n_rec - 1, sel + 1)
                    elif 9 <= sel < 18:
                        sel += 9
                    elif sel >= 18:
                        sel -= 18
                    else:
                        sel = NHUECOS if n_rec else sel
                elif k == "EXE":
                    if sel >= NHUECOS:
                        r = recetas[sel - NHUECOS]
                        if all(cuantos(a) >= b for a, b in r[2].items()):
                            for a, b in r[2].items():
                                quitar(a, b)
                            dar(r[0], r[1])
                            sonar("wood%d" % random.randint(1, 4), 0.4)
                    elif coger is None:
                        coger = sel
                    else:
                        inv_id[coger], inv_id[sel] = inv_id[sel], inv_id[coger]
                        inv_n[coger], inv_n[sel] = inv_n[sel], inv_n[coger]
                        coger = None
                elif k in ("9", "CH:q") and sel < NHUECOS and inv_id[sel]:
                    inv_n[sel] -= 1
                    if not inv_n[sel]:
                        inv_id[sel] = 0
            if fin:
                break
        self.completo = True
        self.hud = None

    # ---- pausa ---------------------------------------------------------------------------
    def pausa(self):
        ops = ["Volver al juego", "Guardar", "Guardar y salir", "Salir sin guardar"]
        sel = 0
        while True:
            P.recorte()
            P.rect(60, 40, 200, 140, 0x202020)
            P.marco(60, 40, 200, 140, 0xFFFFFF)
            P.texto("Menu del juego", 112, 50, 0xFFFFFF)
            for i, o in enumerate(ops):
                boton(o, 80, 70 + i * 26, 160, i == sel)
            P.mostrar()
            for k, sh in K.eventos():
                if k in ("UP", "DOWN"):
                    sel = (sel + (1 if k == "DOWN" else -1)) % len(ops)
                elif k == "DEL":
                    sel, k = 0, "EXE"
                if k == "EXE":
                    self.completo = True
                    self.hud = None
                    if sel == 0:
                        return
                    if sel in (1, 2):
                        guardar(self)
                        if sel == 1:
                            self.aviso, self.aviso_t = "Guardado", 2.0
                            return
                    self.salir = True
                    return

    # ---- bucle -------------------------------------------------------------------------------
    def teclas(self):
        for k, sh in K.eventos():
            if k.startswith("CH:"):                # teclado del PC
                c = k[3:].lower()
                if c in "wasd ":
                    self.tap[c] = 0.18
                elif c in "123456789":
                    self.sel = int(c) - 1
                elif c == "e":
                    self.abrir_inventario()
                elif c == "q":
                    k = "9"
                if not k.startswith("9"):
                    continue
            if k == "8":
                self.cdy = min(ALCANCE, self.cdy + 1)
            elif k == "2":
                self.cdy = max(-ALCANCE, self.cdy - 1)
            elif k == "4":
                self.cdx = max(-ALCANCE, self.cdx - 1)
            elif k == "6":
                self.cdx = min(ALCANCE, self.cdx + 1)
            elif k == "5":
                self.golpear()
            elif k == "EXE":
                self.usar()
            elif k in ("1", "LP"):
                self.sel = (self.sel - 1) % 9
            elif k in ("3", "RP"):
                self.sel = (self.sel + 1) % 9
            elif k == "7":
                self.abrir_inventario()
            elif k == "9":
                it = inv_id[self.sel]
                if it:
                    quitar(it)
            elif k == "DEL":
                self.pausa()
            elif k == "SQRT" and sh:              # truco: adelantar el reloj del día
                self.tiempo += DIA_S / 10
                self.aviso, self.aviso_t = "+1 hora", 1.5

    def paso(self, dt):
        self.teclas()
        for c in list(self.tap):
            self.tap[c] -= dt
        if K.pulsada("5"):
            self.picar(dt)
        elif self.pico[2]:
            self.sucios.append((self.pico[0], self.pico[1]))
            self.pico = (-1, -1, 0.0)
        self.fisica(dt)
        self.mobs_paso(dt)
        self.red_paso()
        self.golpe_t = max(0.0, self.golpe_t - dt)
        self.tiempo += dt
        # hambre y vida
        self.hambre_t += dt * (1.5 if abs(self.vx) > 0.1 else 1.0)
        if self.hambre_t > 40:
            self.hambre_t = 0
            self.hambre = max(0, self.hambre - 1)
        if self.hambre >= 18 and self.vida < 20 and int(self.tiempo * 2) % 8 == 0 and \
                int((self.tiempo - dt) * 2) % 8 != 0:
            self.vida += 1
        if self.hambre == 0 and int(self.tiempo) % 4 == 0 and int(self.tiempo - dt) % 4 != 0:
            self.herir(1)
        if getattr(self, "aviso_t", 0) > 0:
            self.aviso_t -= dt
            if self.aviso_t <= 0:
                self.aviso = None
        # el cielo cambia con la hora
        f = (self.tiempo % DIA_S) / DIA_S
        noche = 1.0 if 0.75 < f < 0.95 else (0.0 if f < 0.65 else
                                              ((f - 0.65) / 0.1 if f < 0.75 else (1 - f) / 0.05))
        c = mezcla(CIELO_DIA, CIELO_NOCHE, min(1.0, max(0.0, noche)))
        if c != self.cielo and abs(noche * 8 - round(noche * 8)) < 0.05:
            self.cielo = c
            self.completo = True

    def morir(self):
        P.recorte()
        P.rect(0, 0, P.ANCHO, P.ALTO, 0x601010)
        P.texto("Has muerto", 100, 70, 0xFFFFFF, None, 2)
        P.texto("EXE: reaparecer", 110, 120, 0xFFC0C0)
        P.mostrar()
        while True:
            for k, sh in K.eventos():
                if k == "EXE":
                    self.vida, self.hambre = 20, 20
                    for i in range(NHUECOS):          # como en Minecraft: lo pierdes todo
                        inv_id[i] = inv_n[i] = 0
                    self.aparecer()
                    self.hud = None
                    return
            P.mostrar()


def medio(valor, i):
    return "" if valor >= (i + 1) * 2 else ("_medio" if valor > i * 2 else "_vacio")


def mezcla(a, b, f):
    r = int(((a >> 16) & 255) * (1 - f) + ((b >> 16) & 255) * f)
    gg = int(((a >> 8) & 255) * (1 - f) + ((b >> 8) & 255) * f)
    bb = int((a & 255) * (1 - f) + (b & 255) * f)
    return (r << 16) | (gg << 8) | bb


# ---- Guardar y cargar -------------------------------------------------------------------
CARPETA = "mundos"


def guardar(j):
    try:
        os.mkdir(CARPETA)
    except OSError:
        pass
    cab = {"v": 1, "nombre": j.nombre, "x": j.x, "y": j.y, "vida": j.vida, "hambre": j.hambre,
           "t": j.tiempo, "inv": [[inv_id[i], inv_n[i]] for i in range(NHUECOS) if inv_id[i]],
           "pos": [i for i in range(NHUECOS) if inv_id[i]]}
    with open("%s/%s.mc2d" % (CARPETA, j.nombre), "wb") as f:
        f.write(b"MC2D1\n")
        f.write(json.dumps(cab).encode())
        f.write(b"\n")
        f.write(mundo)


def cargar(nombre):
    with open("%s/%s.mc2d" % (CARPETA, nombre), "rb") as f:
        datos = f.read()
    a = datos.find(b"\n")
    b = datos.find(b"\n", a + 1)
    cab = json.loads(datos[a + 1:b].decode())
    mundo[:] = datos[b + 1:b + 1 + W * H]
    for x in range(W):
        calc_alto(x)
    for i in range(NHUECOS):
        inv_id[i] = inv_n[i] = 0
    for p, (it, n) in zip(cab.get("pos", []), cab.get("inv", [])):
        inv_id[p], inv_n[p] = it, n
    j = Juego(nombre)
    j.x, j.y, j.vida, j.hambre, j.tiempo = cab["x"], cab["y"], cab["vida"], cab["hambre"], cab["t"]
    j.centrar()
    return j


def lista_mundos():
    try:
        return [n[:-5] for n in os.listdir(CARPETA) if n.endswith(".mc2d")]
    except OSError:
        return []


# ---- Multijugador: el mundo viaja comprimido (tramos iguales) ---------------------------
def comprimir():
    out = []
    i = 0
    while i < W * H:
        b = mundo[i]
        n = 1
        while i + n < W * H and mundo[i + n] == b and n < 255:
            n += 1
        out.append(b)
        out.append(n)
        i += n
    return out


def descomprimir(lst):
    i = 0
    for k in range(0, len(lst), 2):
        b, n = lst[k], lst[k + 1]
        for _ in range(n):
            if i < W * H:
                mundo[i] = b
            i += 1


def publicar(j):
    red.vaciar()
    datos = comprimir()
    trozo = 1200
    n = (len(datos) + trozo - 1) // trozo
    for k in range(n):
        red.var("m:%d" % k, datos[k * trozo:(k + 1) * trozo])
        if k % 4 == 0:
            P.mostrar()
    red.var("mundo", {"n": n, "t": j.tiempo})


def recibir_mundo():
    fin = K.ms() + 15000
    while K.ms() < fin:
        vs = red.vars()
        info = vs.get("mundo")
        if info:
            datos = []
            for k in range(info["n"]):
                datos.extend(vs.get("m:%d" % k) or [])
            descomprimir(datos)
            for n, v in vs.items():
                if n.startswith("b:"):
                    i = int(n[2:])
                    if 0 <= i < W * H:
                        mundo[i] = int(v)
            for x in range(W):
                calc_alto(x)
            return info
        progreso("Descargando el mundo...", 0.5)
        red.recibir()
    return None


# ---- Menús ------------------------------------------------------------------------------------
def boton(t, x, y, w, foco, ok=True):
    P.rect(x, y, w, 20, 0x000000)
    P.rect(x + 1, y + 1, w - 2, 18, 0x6E6E6E if ok else 0x2C2C2C)
    P.rect(x + 1, y + 1, w - 2, 1, 0xA9A9A9)
    P.rect(x + 1, y + 18, w - 2, 1, 0x373737)
    if foco:
        P.marco(x, y, w, 20, 0xFFFFFF)
    c = (0xFFFFA0 if foco else 0xE0E0E0) if ok else 0xA0A0A0
    P.texto(t, x + w // 2 - len(t) * 3 + 1, y + 7, 0x2A2A2A)
    P.texto(t, x + w // 2 - len(t) * 3, y + 6, c)


def fondo_tierra():
    s = spr("tierra")
    for y in range(0, P.ALTO, 32):
        for x in range(0, P.ANCHO, 32):
            P.dibujar(s, x, y, 2)


def menu(titulo, ops, sub=""):
    """Menú al estilo de Minecraft. Devuelve el índice elegido (o -1 con DEL)."""
    sel = 0
    fondo_tierra()
    while True:
        P.texto(titulo, P.ANCHO // 2 - len(titulo) * 6 + 2, 16, 0x3A3A3A, None, 2)
        P.texto(titulo, P.ANCHO // 2 - len(titulo) * 6, 14, 0xFFFFFF, None, 2)
        if sub:
            P.texto(sub, P.ANCHO // 2 - len(sub) * 3, 38, 0xFFFF60)
        top = max(0, sel - 5)
        for i in range(top, min(len(ops), top + 6)):
            boton(ops[i], 60, 56 + (i - top) * 26, 200, i == sel)
        P.mostrar()
        for k, sh in K.eventos():
            if k in ("UP", "DOWN"):
                sel = (sel + (1 if k == "DOWN" else -1)) % len(ops)
                fondo_tierra()
            elif k == "EXE":
                return sel
            elif k == "DEL":
                return -1


def mensaje(lineas):
    fondo_tierra()
    for i, l in enumerate(lineas):
        P.texto(l, 20, 60 + i * 14, 0xFFFFFF)
    P.mostrar()


def preguntar(titulo, inicial=""):
    try:
        from t9 import T9
    except ImportError:
        return inicial
    t = T9(inicial, "texto", 20)
    while True:
        fondo_tierra()
        P.texto(titulo, 20, 60, 0xFFFFFF)
        P.rect(20, 80, 280, 20, 0x000000)
        P.texto(t.mostrar(), 24, 86, 0xFFFFFF)
        P.texto("2abc..9wxyz, teclado del PC · EXE ok · DEL borrar", 20, 110, 0xA0A0A0)
        P.mostrar()
        for k, sh in K.eventos():
            r = t.tecla(k, sh)
            if r == "ok":
                return t.texto
            if r == "cancelar":
                return None


def nuevo_mundo(nombre):
    generar(random.getrandbits(30))
    for i in range(NHUECOS):
        inv_id[i] = inv_n[i] = 0
    j = Juego(nombre)
    j.aparecer()
    return j


def un_jugador():
    while True:
        mundos = lista_mundos()
        ops = ["Crear mundo nuevo"] + mundos + ["Atras"]
        r = menu("Un jugador", ops, "Elige un mundo")
        if r < 0 or r == len(ops) - 1:
            return None
        if r == 0:
            n = 1
            while ("Mundo %d" % n) in mundos:
                n += 1
            nombre = preguntar("Nombre del mundo:", "Mundo %d" % n)
            if nombre:
                return nuevo_mundo(nombre.strip()[:16] or "Mundo")
        else:
            accion = menu(ops[r], ["Jugar", "Borrar", "Atras"])
            if accion == 0:
                mensaje(["Cargando %s..." % ops[r]])
                return cargar(ops[r])
            if accion == 1:
                try:
                    os.remove("%s/%s.mc2d" % (CARPETA, ops[r]))
                except OSError:
                    pass


def multijugador():
    if red is None:
        mensaje(["Esta calculadora no tiene red todavia.", "", "DEL: volver"])
        menu("Sin red", ["Atras"])
        return None
    r = menu("Multijugador", ["Hostear un mundo", "Unirse a una partida", "Conexion directa (IP)", "Atras"])
    if r == 0:
        j = un_jugador()
        if not j:
            return None
        mensaje(["Abriendo la partida..."])
        red.conectar(SALA, None, None, None, True)
        if not red.esperar():
            mensaje(["No se pudo abrir: " + str(red.error()), "", "EXE: seguir solo"])
            menu("Error", ["Seguir solo"])
            return j
        publicar(j)
        j.online = True
        return j
    if r in (1, 2):
        destino = None
        if r == 1:
            mensaje(["Buscando partidas en tu red..."])
            res = red.buscar()
            filas = []
            if isinstance(res, list):
                for s in res:
                    for sala in s.get("salas", []):
                        if sala.get("sala") == SALA:
                            filas.append((s.get("nombre", s["ip"]), s["ip"], s["puerto"]))
            if not filas:
                menu("Multijugador", ["Atras"], "No hay partidas abiertas")
                return None
            k = menu("Partidas", [f[0][:26] for f in filas] + ["Atras"])
            if k < 0 or k >= len(filas):
                return None
            destino = filas[k][1:]
        else:
            t = preguntar("IP del anfitrion (ip:puerto):", "")
            if not t:
                return None
            ip, _, pu = t.strip().partition(":")
            destino = (ip, int(pu) if pu.isdigit() else 8267)
        mensaje(["Conectando con %s..." % destino[0]])
        red.conectar(SALA, None, destino[0], destino[1], False)
        if not red.esperar():
            menu("No se pudo conectar", ["Atras"], str(red.error())[:40])
            return None
        info = recibir_mundo()
        if not info:
            menu("El anfitrion no mando el mundo", ["Atras"])
            red.desconectar()
            return None
        for i in range(NHUECOS):
            inv_id[i] = inv_n[i] = 0
        j = Juego("Partida online", True)
        j.tiempo = info.get("t", 60.0)
        j.aparecer()
        fin = K.ms() + 2000                       # aparecer junto al anfitrión
        while K.ms() < fin and red.anfitrion() not in j.otros:
            j.red_paso()
            P.mostrar()
        o = j.otros.get(red.anfitrion())
        if o:
            j.x, j.y = o[0], o[1] + 0.1
            j.centrar()
        return j
    return None


def jugar(j):
    sonar("click", 0.3)
    ultimo = K.ms()
    while not j.salir:
        ahora = K.ms()
        dt = min(0.1, max(0.001, (ahora - ultimo) / 1000))
        ultimo = ahora
        j.paso(dt)
        if j.vida <= 0:
            j.morir()
        j.pintar()
        P.mostrar()
    if j.online:
        red.desconectar()


def main():
    buscar_sonidos()
    while True:
        r = menu("MINECRAFT 2D", ["Un jugador", "Multijugador", "Controles", "Salir"],
                 "Edicion calculadora")
        if r in (3, -1):
            break
        if r == 2:
            mensaje(["Controles:", "", "<- ->  andar     ^ saltar/nadar",
                     "8 4 6 2  mover el cursor", "5  picar / golpear (mantener)",
                     "EXE  poner, comer, usar mesa/horno", "1 3  cambiar de objeto",
                     "7  inventario y fabricar   9  tirar", "DEL  menu (guardar)",
                     "PC: WASD, E inventario, Q tirar, 1-9"])
            menu("Controles", ["Atras"])
            continue
        j = un_jugador() if r == 0 else multijugador()
        if j:
            jugar(j)
