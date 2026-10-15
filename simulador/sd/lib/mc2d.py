# =============================================================================
#  mc2d.py — Minecraft 2D: Paper Minecraft hecho para caber en el ESP32
# -----------------------------------------------------------------------------
#  Paper Minecraft (griffpatch) entero no cabe en los ~70 KB de Python del ESP32
#  sin PSRAM. Esta es su versión ligera: NO se inventa nada, usa las imágenes y
#  las tablas del propio juego, sacadas de tu .sb3 con
#      python pc/pm_a_mc2d.py "Paper Minecraft v11.7.sb3"
#  (que escribe /juegos/minecraft2d/pm/):
#    - bloques y objetos: _BLOCK_DATA (sólido, dureza, herramienta y nivel,
#      lo que suelta, en qué se funde, cuánto arde, daño, durabilidad, raíz)
#    - picar: el tiempo de 'Get Dig Speed' (dureza, herramienta y nivel)
#    - lo que cae: 'Add To Harvest' (nivel de herramienta, pedernal en la grava,
#      1/10 de retoño en las hojas, 4-5 de redstone, semillas del trigo)
#    - fabricar: _Recipes (rejilla 3x3, ingredientes por su objeto raíz, las
#      herramientas salen con su durabilidad) y el horno (fundir con combustible)
#    - comida: _FOOD_DATA (hambre, saturación, veneno, lo que queda)
#    - criaturas: _MOB_DATA (tamaño, vida, comida que les gusta, bando) con sus
#      dibujos de verdad y su botín ('Death Harvest')
#    - Steve, corazones, comida y grietas: los dibujos del juego
#    - biomas: BIOME_DATA (llanura, colinas, desierto, islas, bosque, taiga, nieve)
#  El mundo es un bytearray de 200 x 64 (un número por casilla: la tabla
#  "en_mundo" lo traduce al id de Paper Minecraft) y solo se redibuja lo que
#  cambia. Multijugador con scicalc.red (el anfitrión simula los mobs).
#
#  Controles (calculadora / teclado del PC):
#    ◄ ►  andar          ▲  saltar / nadar / subir escaleras
#    8 4 6 2  mover el cursor     5  picar / golpear (mantén)
#    EXE  poner bloque, comer, usar mesa, horno o cofre
#    1 3 o ( )  objeto anterior / siguiente      teclas 1-9 del PC: hueco
#    7 (o E)  inventario y fabricar      9 (o Q)  tirar uno
#    DEL  pausa (guardar)
#
#  Este archivo vive en /lib y en el ESP32 va CONGELADO en el firmware (el
#  código está en la flash). Se arranca con /juegos/minecraft2d/minecraft2d.py.
# =============================================================================
import math
import random
import json
import os
import struct
import gc
from array import array
from scicalc import pantalla as P, teclas as K
try:
    from scicalc import red
except ImportError:
    red = None

# ---- Datos de Paper Minecraft (pm/) -------------------------------------------------
PMD = "pm/"
FICHA = "<BHBBBBbbhHHbbHHHH"
FT = struct.calcsize(FICHA)
# campos de cada ficha de bloque/objeto
F_SOL, F_DUR, F_HERR, F_NIV, F_LIQ, F_CAE, F_LUZ, F_GRUPO, F_SUELTA, F_FUNDE, F_QUEMA, \
    F_DANO, F_CREAT, F_TILE, F_INV, F_DURAB, F_RAIZ = range(17)
CERO = (0,) * 17

# En el ESP32 la memoria no da para tener las tablas enteras: las fichas de
# bloques.bin y las recetas se leen del archivo cuando hacen falta (con una caché
# pequeña); del mundo solo se guardan arrays de bytes.
_bl = None                  # bloques.bin abierto
NB = 0                      # cuántos ids
L2PM = array("H")           # número del mundo -> id de Paper Minecraft (0 = aire)
PM2L = bytearray(0)         # id -> número del mundo (0 si no se puede poner)
SOL = TRANSP = NOSUELO = LIQ = CAE = bytearray(0)
TEXL = array("H")           # textura de cada número del mundo
NREC = 0                    # recetas en recetas.bin
_fichas = {}
COMIDA = {}
MOBS = {}                   # tipo -> datos de la criatura
BIOMAS = []
STEVE = {}

# Algunos ids de Paper Minecraft que usa el juego
AIRE_PM, HIERBA_PM, TIERRA_PM, PIEDRA_PM, GRAVA_PM, LECHO_PM, ARENA_PM = 1, 2, 3, 4, 5, 6, 7
TRONCO_PM, HOJAS_PM, CACTUS_PM, COFRE_PM = 8, 9, 11, 12
CARBON_M, DIAMANTE_M, ORO_M, HIERRO_M, ROCA_PM = 13, 14, 15, 16, 41
ESCALERA_PM, ANTORCHA_PM, AGUA_PM, LAVA_PM = 19, 20, 38, 81
MESA_PM, HORNO_PM, HORNO_ON_PM = 47, 48, 49
CUBO, CUBO_AGUA, CUBO_LAVA = 92, 95, 82
REDSTONE_M, ESMERALDA_M, ARCILLA_PM, AREN_PIEDRA = 217, 271, 53, 58
NIEVE_HIERBA, NIEVE_CAPA, HIELO, ROSA, FLOR, HIERBA_ALTA = 284, 283, 287, 43, 44, 133
SETA_R, SETA_M, CALABAZA, CANA, RETONO = 45, 46, 54, 61, 55
ABEDUL, ABETO, JUNGLA = 179, 178, 180
HOJAS_ABEDUL, HOJAS_ABETO, HOJAS_JUNGLA = 181, 184, 187
FLECHA = 131


def ficha(i):
    if not 0 < i < NB:
        return CERO
    f = _fichas.get(i)
    if f is None:
        _bl.seek(8 + i * FT)
        f = struct.unpack(FICHA, _bl.read(FT))
        if len(_fichas) > 24:
            _fichas.clear()
        _fichas[i] = f
    return f


def B(pm):
    """Número del mundo de un bloque de Paper Minecraft."""
    return PM2L[pm] if 0 <= pm < len(PM2L) else 0


def cargar_datos():
    """Lee pm/. Devuelve un texto de error si no está (hay que convertir el .sb3)."""
    global _bl, NB, L2PM, PM2L, SOL, TRANSP, NOSUELO, LIQ, CAE, TEXL, NREC
    global COMIDA, MOBS, BIOMAS, STEVE
    try:
        _bl = open(PMD + "bloques.bin", "rb")
        cab = _bl.read(8)
        NREC = (os.stat(PMD + "recetas.bin")[6] - 4) // 22
        with open(PMD + "datos.json") as f:
            d = json.loads(f.read())
    except OSError:
        return "Falta Paper Minecraft"
    if cab[:4] != b"PMB1":
        return "pm/bloques.bin no valido"
    NB = struct.unpack("<H", cab[4:6])[0]
    L2PM = array("H", d["en_mundo"])
    L2PM[0] = 0
    PM2L = bytearray(NB)
    n = len(L2PM)
    SOL, TRANSP, NOSUELO, LIQ, CAE = (bytearray(n) for _ in range(5))
    TEXL = array("H", bytes(2 * n))
    for L in range(1, n):
        pm = L2PM[L]
        PM2L[pm] = L
        f = ficha(pm)
        SOL[L] = 1 if f[F_SOL] else 0
        TRANSP[L] = 1 if (not f[F_SOL] or f[F_LUZ] < 3) else 0
        NOSUELO[L] = 1 if (not f[F_SOL] or f[F_GRUPO] in (6, 10)) else 0
        LIQ[L] = f[F_LIQ]
        CAE[L] = 1 if f[F_CAE] == 89 else 0          # 'Y'
        TEXL[L] = f[F_TILE]
    TRANSP[0] = NOSUELO[0] = 1
    COMIDA = {int(k): v for k, v in d["comida"].items()}
    MOBS = {int(k): v for k, v in d["mobs"].items()}
    BIOMAS = d["biomas"]
    STEVE = d["steve"]
    _fichas.clear()
    d = None
    gc.collect()
    return None


_nombres = {}


def nombre(it):
    """Nombre de un objeto (pm/nombres.txt, leído cuando hace falta)."""
    if not it:
        return ""
    s = _nombres.get(it)
    if s is None:
        s = ""
        try:
            with open(PMD + "nombres.txt") as f:
                for i, linea in enumerate(f):
                    if i == it:
                        s = linea.strip()
                        break
        except OSError:
            pass
        if len(_nombres) > 40:
            _nombres.clear()
        _nombres[it] = s
    return s


def es_herramienta(it):
    f = ficha(it)
    return f[F_GRUPO] == 1 or f[F_DURAB] > 0


def max_pila(it):
    """'Get Stack Limit': 1 para herramientas, objetos grandes o con durabilidad."""
    f = ficha(it)
    return 1 if (f[F_GRUPO] in (1, 8) or f[F_DURAB] > 0) else 64


def raiz(it):
    r = ficha(it)[F_RAIZ]
    return r or it


# ---- Mundo y pantalla -------------------------------------------------------------
W, H = 200, 64
MAR = 30
T = 16                                  # píxeles por bloque
VIEW_H = 184                            # zona del mundo; debajo, vida y barra de objetos
VW, VH = P.ANCHO // T + 1, VIEW_H // T + 1
CIELO_DIA, CIELO_NOCHE, FONDO_CUEVA, OSCURO = 0x78A8F0, 0x101830, 0x3A3530, 0x0C0C0C
DIA_S = 600                             # un día dura 10 minutos (7 de día y 3 de noche)
SALA = "minecraft2d-pm"
mundo = bytearray(W * H)
alto = bytearray(W)                     # primer bloque de terreno desde arriba de cada columna

# ---- Física (en bloques y segundos) -------------------------------------------------
PW, PH = 0.6, 1.8
GRAV, MAX_CAIDA = 32.0, 24.0
ANDAR, SALTO = 4.3, 9.0
ALCANCE = 4


def g(x, y):
    if 0 <= x < W and 0 <= y < H:
        return mundo[x + y * W]
    return B(LECHO_PM) if y < 0 else 0


def sp(x, y, b):
    mundo[x + y * W] = b


def solido(b):
    return SOL[b]


def es_agua(b):
    return LIQ[b] and 21 <= L2PM[b] <= 38


def es_lava(b):
    return LIQ[b] and 64 <= L2PM[b] <= 81


def calc_alto(x):
    # la superficie: el primer bloque de "terreno" desde arriba (los árboles y
    # las plantas no cuentan: debajo de las hojas sigue siendo cielo)
    y = H - 1
    while y > 0 and NOSUELO[mundo[x + y * W]]:
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


def sonar(nombre_s, vol=0.7):
    r = SND.get(nombre_s)
    if r:
        P.sonar(r, vol)


def sonar_bloque(b, vol=0.5):
    f = ficha(L2PM[b] if b < len(L2PM) else 0)
    letra = f[F_HERR]
    pm = L2PM[b] if b < len(L2PM) else 0
    m = ("sand" if pm in (ARENA_PM, AREN_PIEDRA) else "gravel" if pm == GRAVA_PM else
         "wood" if letra == 65 else "stone" if letra == 80 else "grass")     # A, P
    sonar("%s%d" % (m, random.randint(1, 4)), vol)


# ---- Generación del mundo (con BIOME_DATA) ----------------------------------------------
def progreso(texto, frac):
    P.rect(60, 140, 200, 8, 0x303440)
    P.rect(60, 140, int(200 * frac), 8, 0x5CBF3A)
    P.rect(0, 156, P.ANCHO, 12, 0)
    P.texto(texto, 60, 156, 0xA0A0A0)
    P.mostrar()                                  # además mantiene vivo el watchdog


def generar(semilla):
    random.seed(semilla)
    for i in range(W * H):
        mundo[i] = 0
    # biomas: trozos de 30-60 columnas, como los chunks de Paper Minecraft
    bioma = bytearray(W)
    x = 0
    while x < W:
        n = random.randint(30, 60)
        b = random.randrange(len(BIOMAS))
        for i in range(x, min(W, x + n)):
            bioma[i] = b
        x += n
    ondas = [(random.uniform(8, 20), random.uniform(1, 3), random.uniform(0, 6)),
             (random.uniform(25, 50), random.uniform(3, 7), random.uniform(0, 6))]
    hierba, tierra, piedra, arena = B(HIERBA_PM), B(TIERRA_PM), B(PIEDRA_PM), B(ARENA_PM)
    agua, lecho = B(AGUA_PM), B(LECHO_PM)
    progreso("Generando el terreno...", 0.1)
    for x in range(W):
        bi = BIOMAS[bioma[x]]
        tipo = bi[1]
        h = 32.0 + bi[3] * 0.5
        for per, amp, fase in ondas:
            h += math.sin(x / per + fase) * amp * bi[2]
        h = int(max(18, min(H - 10, h)))
        capa = random.randint(3, 4)
        arriba = (arena if tipo == "D" or h <= MAR + 1 else
                  B(NIEVE_HIERBA) if tipo == "S" else hierba)
        for y in range(1, h + 1):
            if y > h - capa:
                b = arriba if y == h else (arena if tipo == "D" else tierra)
                if tipo == "D" and y < h - 1:
                    b = B(AREN_PIEDRA)
            else:
                b = piedra
            mundo[x + y * W] = b
        mundo[x] = lecho
        if random.random() < 0.5:
            mundo[x + W] = lecho
        for y in range(h + 1, MAR + 1):          # mar
            mundo[x + y * W] = agua
        if tipo == "S" and h < MAR:
            mundo[x + MAR * W] = B(HIELO)        # agua helada
    progreso("Cavando cuevas...", 0.35)
    cueva = (piedra, tierra, B(GRAVA_PM), B(AREN_PIEDRA))
    lava = B(LAVA_PM)
    for _ in range(W // 18):
        cx, cy = random.uniform(0, W), random.uniform(6, 30)
        ang, r = random.uniform(0, 6.28), random.uniform(1.0, 1.8)
        for _ in range(random.randint(25, 60)):
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    xx, yy = int(cx + dx), int(cy + dy)
                    if dx * dx + dy * dy <= r * r * 1.4 and 0 <= xx < W and 2 <= yy < H:
                        if mundo[xx + yy * W] in cueva:
                            mundo[xx + yy * W] = lava if yy < 6 else 0
            ang += random.uniform(-0.6, 0.6)
            cx += math.cos(ang) * 1.5
            cy += math.sin(ang) * 0.8
            cy = max(4, min(40, cy))
    progreso("Escondiendo menas...", 0.55)
    # las vetas de 'Init Seams' (carbón, hierro, oro, diamante, redstone, esmeralda)
    for pm, n, ymax, tam in ((CARBON_M, W // 3, 48, 5), (HIERRO_M, W // 5, 32, 4),
                             (ORO_M, W // 12, 18, 3), (DIAMANTE_M, W // 20, 11, 3),
                             (REDSTONE_M, W // 14, 14, 4), (ESMERALDA_M, W // 60, 20, 1),
                             (GRAVA_PM, W // 8, 40, 5), (ARCILLA_PM, W // 25, 30, 4)):
        b = B(pm)
        for _ in range(n):
            x, y = random.randrange(W), random.randint(2, ymax)
            for _ in range(tam):
                if mundo[x + y * W] == piedra:
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
        bi = BIOMAS[bioma[x]]
        arboles, frec = bi[5], bi[6]
        if top in (hierba, B(NIEVE_HIERBA)) and random.random() < frec / 60:
            t = random.choice(arboles) if arboles else "O"
            if t != "C":
                arbol(x, y + 1, t)
                x += 4
                continue
        if top == arena and "C" in arboles and y > MAR and random.random() < 0.07:
            for i in range(random.randint(1, 3)):
                if y + 1 + i < H:
                    mundo[x + (y + 1 + i) * W] = B(CACTUS_PM)
            x += 3
            continue
        if y + 1 < H and mundo[x + (y + 1) * W] == 0:
            r = random.random()
            if top == hierba:
                if r < 0.15:
                    mundo[x + (y + 1) * W] = B(HIERBA_ALTA)
                elif r < 0.2:
                    mundo[x + (y + 1) * W] = B(random.choice((ROSA, FLOR)))
                elif r < 0.205:
                    mundo[x + (y + 1) * W] = B(CALABAZA)
            elif top == B(NIEVE_HIERBA) and r < 0.5:
                mundo[x + (y + 1) * W] = B(NIEVE_CAPA)
            if top in (hierba, arena) and r > 0.9 and (g(x - 1, y) == agua or g(x + 1, y) == agua):
                for i in range(random.randint(1, 3)):     # caña de azúcar junto al agua
                    if y + 1 + i < H:
                        mundo[x + (y + 1 + i) * W] = B(CANA)
        x += 1
    for x in range(W):
        calc_alto(x)
    progreso("Listo", 1.0)


ARBOLES = {"O": (TRONCO_PM, HOJAS_PM), "B": (ABEDUL, HOJAS_ABEDUL),
           "S": (ABETO, HOJAS_ABETO), "J": (JUNGLA, HOJAS_JUNGLA)}


def arbol(x, y, tipo):
    tronco, hojas = ARBOLES.get(tipo, ARBOLES["O"])
    tronco, hojas = B(tronco), B(hojas)
    alto_t = random.randint(4, 6) + (2 if tipo == "S" else 0)
    for i in range(alto_t):
        if y + i < H:
            mundo[x + (y + i) * W] = tronco
    top = y + alto_t
    filas = ((-3, 2), (-2, 2), (-1, 1), (0, 1), (1, 0)) if tipo == "S" else \
        ((-2, 2), (-1, 2), (0, 1), (1, 1))
    for dy, r in filas:
        for dx in range(-r, r + 1):
            xx, yy = x + dx, top + dy
            if 0 <= xx < W and 0 <= yy < H and mundo[xx + yy * W] == 0:
                mundo[xx + yy * W] = hojas


# ---- Inventario (ids de Paper Minecraft; en las herramientas, n = durabilidad) ----------
NHUECOS = 27
inv_id = [0] * NHUECOS
inv_n = [0] * NHUECOS


def dar(it, n=1):
    """Mete n objetos; devuelve los que no caben. Las herramientas salen nuevas."""
    if es_herramienta(it):
        dur = ficha(it)[F_DURAB] or 1
        for _ in range(n):
            for i in range(NHUECOS):
                if not inv_id[i]:
                    inv_id[i], inv_n[i] = it, dur
                    break
            else:
                return n
            n -= 1
        return 0
    mp = max_pila(it)
    for i in range(NHUECOS):                         # primero, donde ya hay
        if inv_id[i] == it and inv_n[i] < mp:
            k = min(n, mp - inv_n[i])
            inv_n[i] += k
            n -= k
            if not n:
                return 0
    for i in range(NHUECOS):
        if not inv_id[i]:
            k = min(n, mp)
            inv_id[i], inv_n[i] = it, k
            n -= k
            if not n:
                return 0
    return n


def cuantos_raiz(r):
    """Cuántos hay de un ingrediente (las recetas van por objeto raíz: la roca vale
    como piedra, cualquier tablón como tablón...)."""
    n = 0
    for i in range(NHUECOS):
        if inv_id[i] and not es_herramienta(inv_id[i]) and raiz(inv_id[i]) == r:
            n += inv_n[i]
    return n


def quitar_raiz(r, n=1):
    for i in range(NHUECOS - 1, -1, -1):
        if inv_id[i] and not es_herramienta(inv_id[i]) and raiz(inv_id[i]) == r:
            k = min(n, inv_n[i])
            inv_n[i] -= k
            n -= k
            if not inv_n[i]:
                inv_id[i] = 0
            if not n:
                return


def quitar_hueco(i, n=1):
    inv_n[i] -= n
    if inv_n[i] <= 0:
        inv_id[i] = inv_n[i] = 0


def receta(k):
    """(producto, cantidad, {raíz: cuántos}, ¿necesita mesa?) de la receta k."""
    with open(PMD + "recetas.bin", "rb") as f:
        f.seek(4 + k * 22)
        v = struct.unpack("<HH9H", f.read(22))
    ing = {}
    xs, ys = [], []
    for c in range(9):
        it = v[2 + c]
        if it:
            ing[it] = ing.get(it, 0) + 1
            xs.append(c % 3)
            ys.append(c // 3)
    mesa = (max(xs) - min(xs) > 1 or max(ys) - min(ys) > 1) if xs else False
    return v[0], v[1], ing, mesa


def n_recetas():
    return NREC


# ---- Sprites ---------------------------------------------------------------------------------
SPR = {}


def spr(ruta):
    s = SPR.get(ruta)
    if s is None:
        if len(SPR) > 120:                       # (en el ESP32 cada sprite ocupa memoria)
            SPR.clear()
        s = SPR[ruta] = P.sprite(PMD + ruta)
    return s


def tex(n):
    return spr("tex/t%d.png" % n)


def icono(it, x, y, n=0):
    if not it:
        return
    P.dibujar(tex(ficha(it)[F_INV]), x, y)
    if es_herramienta(it):                       # barra de durabilidad, como en Minecraft
        dur = ficha(it)[F_DURAB]
        if dur and n < dur:
            w = max(1, n * 13 // dur)
            P.rect(x + 1, y + 13, 14, 2, 0x000000)
            P.rect(x + 1, y + 13, w, 1, 0x40E040 if n * 2 > dur else (0xE0E040 if n * 5 > dur else 0xE04040))
    elif n > 1:
        P.texto(str(n), x + 16 - 6 * len(str(n)), y + 9, 0xFFFFFF)


# ---- Juego ---------------------------------------------------------------------------------
class Juego:
    def __init__(self, nombre_m, online=False):
        self.nombre = nombre_m
        self.online = online
        self.x, self.y = W / 2, 0.0
        self.vx = self.vy = 0.0
        self.suelo = False
        self.cara = 1
        self.vida, self.hambre = 20, 20
        self.sat = 5.0                            # saturación (_FoodSaturation)
        self.ticks = 0.0
        self.caida_y = None
        self.cdx, self.cdy = 1, -1                # cursor: el bloque de delante, a los pies
        self.sel = 0
        self.tiempo = 60.0                        # segundos del día (empieza por la mañana)
        self.pico = (-1, -1, 0.0)                 # bloque que se está picando y cuánto
        self.anda_t = 0.0
        self.paso_t = 0.0
        self.golpe_t = 0.0                        # animación del brazo
        self.dano_t = 0.0
        self.lava_t = 0.0
        self.horno = 0.0                          # segundos de combustible que quedan
        self.mobs = []                            # [tipo, x, y, vx, vy, vida, cara, t, id, mecha]
        self.flechas = []                         # [x, y, vx, vy] de los esqueletos
        self.mob_id = 0
        self.muerto = False
        self.era_cliente = False
        self.otros = {}                           # id -> [x, y, cara, anim, objeto, nombre, muerto, tx, ty]
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
            if TRANSP[g(tx + dx, ty + dy)]:
                return False
        return True

    def bloque(self, tx, ty):
        sx, sy = self.pant(tx, ty + 1)
        if sy >= VIEW_H or sx >= P.ANCHO or sx + T <= 0 or sy + T <= 0:
            return
        b = g(tx, ty)
        if TRANSP[b]:
            P.rect(sx, sy, T, T, self.fondo(tx, ty))
            if b:
                P.dibujar(tex(TEXL[b]), sx, sy)
        elif self.encerrado(tx, ty):
            P.rect(sx, sy, T, T, OSCURO)
        else:
            P.dibujar(tex(TEXL[b]), sx, sy)

    def zona(self, x0, y0, x1, y1):
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                self.bloque(tx, ty)

    def objetivo(self):
        return int(self.x + PW / 2) + self.cdx, int(self.y + 0.01) + self.cdy

    def dibujar_hud(self):
        estado = (self.vida, self.hambre, self.sel, tuple(inv_id[:9]), tuple(inv_n[:9]), self.aviso)
        if estado == self.hud:
            return
        self.hud = estado
        P.recorte()
        P.rect(0, VIEW_H, P.ANCHO, P.ALTO - VIEW_H, 0x1A1A1A)
        # corazones y comida: los dibujos de Paper Minecraft
        P.dibujar(spr("vida%d.png" % max(0, min(20, self.vida))), 70, VIEW_H + 2)
        P.dibujar(spr("hambre%d.png" % max(0, min(20, self.hambre))), 170, VIEW_H + 2)
        x0 = 70
        for i in range(9):
            x = x0 + i * 20
            P.rect(x, VIEW_H + 12, 20, 22, 0x8B8B8B if i == self.sel else 0x4A4A4A)
            P.rect(x + 1, VIEW_H + 13, 18, 20, 0x2A2A2A)
            icono(inv_id[i], x + 2, VIEW_H + 15, inv_n[i])
        nom = nombre(inv_id[self.sel])
        P.texto((self.aviso or nom)[:11], 2, VIEW_H + 20, 0xFFFFA0 if self.aviso else 0xC0C0C0)
        if self.online and red:
            P.texto("%d jug" % len(red.jugadores()), 278, VIEW_H + 20, 0x50DC78)

    def caja_jugador(self, x, y):
        sx, sy = self.pant(x + PW / 2, y)
        return sx - 9, sy - STEVE["alto"], sx + 9, sy + 1     # px

    def a_bloques(self, x0, y0, x1, y1):
        # rectángulo de pantalla -> bloques que lo cubren
        tx0 = self.cam_x + x0 // T
        tx1 = self.cam_x + x1 // T
        ty1 = self.cam_top - y0 // T
        ty0 = self.cam_top - (y1 - 1) // T - 1
        return (tx0 - 1, ty0, tx1 + 1, ty1)

    def dibujar_steve(self, x, y, cara, anda_t, andar, it):
        """Steve de Paper Minecraft (sus partes en las poses del juego al andar)."""
        sx, sy = self.pant(x + PW / 2, y)
        k = 1 + int(anda_t * 10) % (STEVE["marcos"] - 1) if andar else 0
        ancho, alto_s, bx = STEVE["ancho"], STEVE["alto"], STEVE["base_x"]
        x0 = sx - (bx if cara > 0 else ancho - bx)
        P.dibujar(spr("steve%d.png" % k), x0, sy - alto_s, 1, cara < 0)
        if it:                                    # lo que lleva en la mano
            off = 2 if self.golpe_t > 0 and int(self.golpe_t * 20) % 2 else 0
            P.dibujar(tex(ficha(it)[F_INV]), (sx + 1 + off) if cara > 0 else (sx - 13 - off),
                      sy - alto_s + 11, 0.75)
        return self.a_bloques(sx - 14, sy - alto_s, sx + 14, sy)

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
        # criaturas (sus dibujos de Paper Minecraft)
        for m in self.mobs:
            d = MOBS.get(m[0])
            if not d or not d["marcos"]:
                continue
            ax, ay = self.pant(m[1] + d["w"] / 2, m[2])
            if ax < -40 or ax > P.ANCHO + 40:
                continue
            fr = d["marcos"]                      # de pie + ciclo de andar
            k = 1 + int(self.tiempo * 8 + m[8]) % (len(fr) - 1) if len(fr) > 1 else 0
            s = spr("mob/%d.png" % fr[k])
            P.dibujar(s, ax - s.ancho // 2, ay - s.alto, 1, m[6] < 0)
            self.pintado.append(self.a_bloques(ax - s.ancho // 2 - 2, ay - s.alto, ax + s.ancho // 2 + 2, ay))
        for f in self.flechas:
            ax, ay = self.pant(f[0], f[1])
            P.dibujar(tex(ficha(FLECHA)[F_INV]), ax - 8, ay - 8, 0.75)
            self.pintado.append(self.a_bloques(ax - 8, ay - 8, ax + 8, ay + 8))
        # otros jugadores
        for o in self.otros.values():
            x0, y0, x1, y1 = self.caja_jugador(o[0], o[1])
            if x1 < 0 or x0 > P.ANCHO or o[6]:
                continue
            self.pintado.append(self.dibujar_steve(o[0], o[1], o[2], self.tiempo, o[3], o[4]))
            w = len(o[5]) * 6
            P.texto(o[5], (x0 + x1) // 2 - w // 2, y0 - 10, 0xFFFFFF, 0x202020)
            self.pintado.append(self.a_bloques((x0 + x1) // 2 - w // 2, y0 - 10, (x0 + x1) // 2 + w // 2, y0))
        # yo
        andar = abs(self.vx) > 0.5 and self.suelo
        self.pintado.append(self.dibujar_steve(self.x, self.y, self.cara, self.anda_t, andar, inv_id[self.sel]))
        # cursor y grieta
        tx, ty = self.objetivo()
        cx, cy = self.pant(tx, ty + 1)
        bx, by, prog = self.pico
        if (bx, by) == (tx, ty) and prog > 0:
            P.dibujar(spr("tex/grieta%d.png" % max(1, min(10, int(prog * 10) + 1))), cx, cy)
        P.marco(cx, cy, T, T, 0x000000)
        self.pintado.append((tx, ty, tx, ty))
        P.recorte()
        self.dibujar_hud()

    # ---- bloques ------------------------------------------------------------------
    def poner(self, x, y, b, red_tambien=True):
        if not (0 <= x < W and 0 <= y < H):
            return
        antes = g(x, y)
        sp(x, y, b)
        calc_alto(x)
        for dx in (-1, 0, 1):                       # los vecinos pueden pasar a verse
            for dy in (-1, 0, 1):
                self.sucios.append((x + dx, y + dy))
        if red_tambien and self.online:
            try:                                    # si otro lo cambió antes, me corrigen
                red.var("b:%d" % (x + y * W), b, antes)
            except TypeError:
                red.var("b:%d" % (x + y * W), b)

    def asentar(self, x, y):
        """Arena y grava caen (columna 'Can Fall' = Y)."""
        while y < H and CAE[g(x, y)]:
            yy = y
            while yy > 1 and not solido(g(x, yy - 1)) and not CAE[g(x, yy - 1)]:
                self.poner(x, yy - 1, g(x, yy))
                self.poner(x, yy, 0)
                yy -= 1
            y += 1

    def toca_jugador(self, tx, ty):
        return tx + 1 > self.x and tx < self.x + PW and ty + 1 > self.y and ty < self.y + PH

    def gastar_herramienta(self):
        """'Damage Tool': cada uso le quita 1 de durabilidad; a 0 se rompe."""
        it = inv_id[self.sel]
        if it and ficha(it)[F_GRUPO] == 1 and ficha(it)[F_DURAB]:
            quitar_hueco(self.sel)
            if not inv_id[self.sel]:
                sonar("break", 0.7)

    def tiempo_picar(self, b):
        """'Get Dig Speed' de Paper Minecraft, en segundos (None: no se puede)."""
        f = ficha(L2PM[b])
        d = f[F_DUR]
        if d == 0 or d == 65535:
            return None
        dig = 0.001 if d == 1 else d / 100
        if f[F_HERR]:
            h = ficha(inv_id[self.sel])
            if h[F_GRUPO] == 1 and h[F_HERR] == f[F_HERR]:
                if f[F_NIV] and h[F_NIV] < f[F_NIV]:
                    dig *= 3.33
                elif h[F_NIV]:
                    dig /= 3 * h[F_NIV]
            elif f[F_NIV]:
                dig *= 3.33
        return dig * 1.5

    def suelta(self, b):
        """'Add To Harvest' + 'Add To Harvest Now': [(objeto, cuántos)]."""
        pm = L2PM[b]
        f = ficha(pm)
        if f[F_HERR] and f[F_NIV]:                 # hace falta la herramienta y su nivel
            h = ficha(inv_id[self.sel])
            if not (h[F_GRUPO] == 1 and h[F_HERR] == f[F_HERR] and h[F_NIV] >= f[F_NIV]):
                return []
        dato = f[F_SUELTA]
        if pm == GRAVA_PM and random.random() < 0.111:
            dato = 101                             # pedernal
        if dato == 0:
            dato = pm
        elif dato < -1:
            dato = -dato if random.random() < 0.1 else 0
        if dato <= 0:
            return []
        out = [(dato, random.randint(4, 5) if pm == REDSTONE_M else 1)]
        if dato == 143:                            # trigo: también semillas
            out.append((142, random.randint(0, 3)))
        return out

    def picar(self, dt):
        tx, ty = self.objetivo()
        b = g(tx, ty)
        seg = self.tiempo_picar(b) if b else None
        if seg is None:
            self.pico = (-1, -1, 0.0)
            return
        bx, by, prog = self.pico
        if (bx, by) != (tx, ty):
            prog = 0.0
        prog += dt / max(0.05, seg)
        self.golpe_t = 0.25
        if int(prog * 9) != int(self.pico[2] * 9) or (bx, by) != (tx, ty):
            sonar_bloque(b, 0.25)
            self.sucios.append((tx, ty))
        if prog >= 1.0:
            self.poner(tx, ty, 0)
            for it, n in self.suelta(b):
                if n:
                    dar(it, n)
            self.gastar_herramienta()
            sonar_bloque(b, 0.7)
            self.asentar(tx, ty + 1)
            arriba = g(tx, ty + 1)                  # lo que no se aguanta solo (flores, antorchas)
            if arriba and not solido(arriba) and not LIQ[arriba]:
                self.poner(tx, ty + 1, 0)
            prog = 0.0
        self.pico = (tx, ty, prog)

    def usar(self):
        tx, ty = self.objetivo()
        b = g(tx, ty)
        pm = L2PM[b] if b else 0
        if pm == MESA_PM:
            self.abrir_inventario("mesa")
            return
        if pm in (HORNO_PM, HORNO_ON_PM):
            self.abrir_inventario("horno")
            return
        it = inv_id[self.sel]
        if not it:
            return
        if it in COMIDA:                           # _FOOD_DATA: hambre, saturación, veneno
            if self.hambre < 20:
                c = COMIDA[it]
                self.hambre = min(20, self.hambre + int(c[0]))
                self.sat = min(self.hambre, self.sat + c[1])
                if random.random() < c[2]:
                    self.hambre = max(0, self.hambre - 4)  # intoxicación
                quitar_hueco(self.sel)
                if c[3]:
                    dar(c[3])                       # lo que queda (el cubo de la leche)
                sonar("eat%d" % random.randint(1, 3))
            return
        if it == CUBO and es_agua(b):              # cubos
            self.poner(tx, ty, 0)
            quitar_hueco(self.sel)
            dar(CUBO_AGUA)
            return
        if it in (CUBO_AGUA, CUBO_LAVA) and not solido(b):
            self.poner(tx, ty, B(AGUA_PM if it == CUBO_AGUA else LAVA_PM))
            quitar_hueco(self.sel)
            dar(CUBO)
            return
        f = ficha(it)
        if f[F_GRUPO] == 12 and f[F_SUELTA] in MOBS and self.manda_mobs():   # huevo
            self.mob_id += 1
            self.mobs.append(self.nuevo_mob(f[F_SUELTA], tx + 0.1, float(ty), 1))
            quitar_hueco(self.sel)
            return
        nb = B(it)
        if not nb:
            return
        if b and solido(b):
            return                                # (sí sobre agua, flores, hierba alta...)
        if solido(nb) and (self.toca_jugador(tx, ty) or self.mob_en(tx, ty)):
            return
        apoyo = False                             # como en Minecraft: junto a otro bloque
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            v = g(tx + dx, ty + dy)
            if v and not LIQ[v]:
                apoyo = True
        if not apoyo:
            return
        quitar_hueco(self.sel)
        self.poner(tx, ty, nb)
        sonar_bloque(nb, 0.6)
        self.asentar(tx, ty)
        self.golpe_t = 0.2

    def mob_en(self, tx, ty):
        for m in self.mobs:
            d = MOBS.get(m[0], {})
            if m[1] - 0.2 <= tx + 0.5 <= m[1] + d.get("w", 1) + 0.2 and \
                    m[2] - 0.2 <= ty + 0.5 <= m[2] + d.get("h", 1) + 0.2:
                return m
        return None

    def dano_arma(self):
        """Daño del objeto de la mano (columna 'Damage inflicted' si es herramienta)."""
        f = ficha(inv_id[self.sel])
        return max(1, f[F_DANO]) if f[F_GRUPO] == 1 else 1

    def golpear(self):
        tx, ty = self.objetivo()
        dano = self.dano_arma()
        m = self.mob_en(tx, ty) or self.mob_en(tx - 1 if self.cara < 0 else tx + 1, ty)
        if m:
            self.golpe_t = 0.25
            self.gastar_herramienta()
            if self.manda_mobs():
                self.dano_mob(m, dano, self.cara)
            else:                                 # el mob es del anfitrión: se lo digo
                red.enviar({"golpe": [m[8], dano, self.cara]})
            return True
        # otro jugador (PvP, como en Minecraft)
        for pid, o in self.otros.items():
            if not o[6] and int(o[0] + PW / 2) in (tx, tx - self.cara) and int(o[1]) <= ty <= int(o[1] + 1.8):
                red.enviar({"dano": [pid, dano, self.cara]})
                self.golpe_t = 0.25
                sonar("hurt", 0.5)
                return True
        return False

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
        dentro = g(int(self.x + PW / 2), int(self.y + 0.5))
        agua = LIQ[dentro]
        escalera = L2PM[dentro] == ESCALERA_PM
        obj = ANDAR * (0.6 if agua else 1.0)
        if izq and not der:
            self.vx, self.cara = -obj, -1
        elif der and not izq:
            self.vx, self.cara = obj, 1
        else:
            self.vx = 0.0
        if escalera:                              # escaleras de mano (tile 19)
            self.vy = 3.0 if arriba else -1.5
            self.caida_y = None
        elif agua:
            self.vy = max(-3.0, self.vy - GRAV * 0.25 * dt)
            if arriba:
                self.vy = 3.5
            self.caida_y = None
        else:
            if arriba and self.suelo:
                self.vy = SALTO
                self.suelo = False
                self.sat -= 0.2                   # saltar gasta saturación
            self.vy = max(-MAX_CAIDA, self.vy - GRAV * dt)
        e = [self.x, self.y, self.vx, self.suelo, PW, PH]
        self.mover_x(e, self.vx * dt)
        estaba = self.suelo
        golpe = self.mover_y(e, self.vy * dt)
        self.x, self.y, self.vx, self.suelo = e[0], e[1], e[2], e[3]
        if golpe:
            self.vy = 0.0
        # caídas: daño = altura - 3 (como en Paper Minecraft)
        if not self.suelo and not agua and not escalera:
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
            self.sat -= 0.045 * dt                # andar gasta saturación (0.0015 por tick)
            if self.paso_t <= 0:
                self.paso_t = 0.38
                sonar_bloque(g(int(self.x + PW / 2), int(self.y - 0.5)), 0.25)
        if es_lava(dentro):                        # 'In Lava'
            self.lava_t -= dt
            if self.lava_t <= 0:
                self.lava_t = 0.5
                self.herir(4, "hurt")
        if self.x < 0:
            self.x = 0.0
        if self.x > W - PW:
            self.x = W - PW
        if self.y < -5:
            self.herir(20, "hurt")

    def herir(self, n, sonido="hurt"):
        if n <= 0 or self.dano_t > 0:             # invulnerable 0,5 s tras un golpe
            return False
        self.vida = max(0, self.vida - n)
        self.dano_t = 0.5
        sonar(sonido, 0.8)
        return True

    # ---- criaturas (_MOB_DATA) ------------------------------------------------------
    def es_noche(self):
        return self.tiempo % DIA_S > DIA_S * 0.7

    def manda_mobs(self):
        """Los mobs los lleva el anfitrión (o tú si juegas solo)."""
        return not self.online or red.anfitrion() == red.mi_id()

    def jugadores(self):
        """[(id o None si soy yo, x, y)] de todos los jugadores de la partida."""
        out = [] if self.muerto else [(None, self.x, self.y)]
        for pid, o in self.otros.items():
            if not o[6]:
                out.append((pid, o[0], o[1]))
        return out

    def herir_a(self, pid, n, cara):
        if pid is None:
            if self.herir(n):
                self.vx = 6.0 * cara
        else:                                     # otro jugador: se lo digo a él
            red.enviar({"dano": [pid, n, cara]})

    def oye(self, m):
        """Solo se oyen los mobs que tienes cerca (no los del otro jugador)."""
        return abs(m[1] - self.x) < 14 and abs(m[2] - self.y) < 10

    def ruido_mob(self, m, dt):
        nom = {1: "pig", 2: "sheep", 3: "cow", 4: "chicken", 100: "zombie", 102: "spider",
               103: "skeleton"}.get(m[0])
        if nom and random.random() < dt * (0.3 if m[0] >= 100 else 0.05) and self.oye(m):
            sonar("%s%d" % (nom, random.randint(1, 3)), 0.4)

    def nuevo_mob(self, tipo, x, y, cara):
        d = MOBS[tipo]
        return [tipo, x, y, 0.0, 0.0, d["vida"], cara, 0.0, self.mob_id, 0.0]

    def mobs_paso(self, dt):
        for o in self.otros.values():             # los demás, moviéndose suave
            o[0], o[1] = acercar(o[0], o[7]), acercar(o[1], o[8])
        if not self.manda_mobs():                 # los mobs llegan del anfitrión
            for m in self.mobs:
                self.ruido_mob(m, dt)
                m[1], m[2] = acercar(m[1], m[3]), acercar(m[2], m[4])
            self.era_cliente = True
            return
        if self.era_cliente:                      # el anfitrión se fue y ahora mando yo:
            self.era_cliente = False              # [3], [4] vuelven a ser velocidades
            for m in self.mobs:
                m[3] = m[4] = 0.0
        jug = self.jugadores()
        if not jug:
            return
        self.flechas_paso(dt, jug)
        # aparecer alrededor de algún jugador, fuera de su pantalla (como Paper
        # Minecraft: de día animales sobre hierba; de noche, 44 % zombi, 20 %
        # esqueleto, 14 % araña, 13 % creeper)
        malos = sum(1 for m in self.mobs if m[0] >= 100)
        if len(self.mobs) < 6 + 2 * len(self.otros) and random.random() < dt * 0.25:
            _, jx, jy = random.choice(jug)
            lado = random.choice((-1, 1))
            x = int(jx) + lado * random.randint(12, 18)
            if 0 <= x < W:
                y = alto[x] + 1
                top = L2PM[g(x, alto[x])]
                self.mob_id += 1
                if self.es_noche():
                    if malos < 3 + len(self.otros):
                        r = random.random()
                        t = 100 if r < 0.44 else 103 if r < 0.64 else 102 if r < 0.78 else 101
                        if t in MOBS:
                            self.mobs.append(self.nuevo_mob(t, x + 0.2, float(y), -lado))
                elif top == HIERBA_PM:
                    t = random.choice((1, 2, 3, 4))
                    if t in MOBS:
                        self.mobs.append(self.nuevo_mob(t, x + 0.2, float(y), 1))
        for m in list(self.mobs):
            d = MOBS.get(m[0])
            if not d:
                self.mobs.remove(m)
                continue
            # el jugador más cercano (yo o cualquiera de los demás)
            cerca, dist = None, 1e9
            for pj in jug:
                dd = abs(pj[1] - m[1]) + abs(pj[2] - m[2]) * 0.5
                if dd < dist:
                    cerca, dist = pj, dd
            if dist > (60 if m[0] < 100 else 45):  # los animales no se van (como en Minecraft)
                self.mobs.remove(m)
                continue
            col = min(W - 1, max(0, int(m[1])))
            if m[0] in (100, 103) and not self.es_noche() and m[2] >= alto[col]:
                m[5] -= dt                        # se queman al sol
                if m[5] <= 0:
                    self.mobs.remove(m)
                    continue
            m[7] -= dt
            pid, px, py = cerca
            vx = 0.0
            if m[0] >= 100 and dist < 16:         # malos: hacia el jugador más cercano
                dx = px - m[1]
                m[6] = 1 if dx > 0 else -1
                if m[0] == 103:                   # esqueleto: guarda distancia y dispara
                    vx = 2.0 * m[6] if abs(dx) > 7 else (-2.0 * m[6] if abs(dx) < 5 else 0.0)
                    if m[7] <= 0 and abs(dx) < 10 and abs(py - m[2]) < 4:
                        m[7] = 2.0
                        self.flechas.append([m[1] + d["w"] / 2, m[2] + 1.4, 9.0 * m[6], 3.0 + (py - m[2])])
                elif m[0] == 101:                 # creeper: mecha de 1,5 s y explota
                    vx = 2.0 * m[6] if abs(dx) > 1.2 else 0.0
                    if abs(dx) < 1.5 and abs(py - m[2]) < 1.8:
                        m[9] += dt
                        if m[9] > 1.5:
                            self.explotar(m[1] + 0.3, m[2] + 0.8, 3)
                            self.mobs.remove(m)
                            continue
                    else:
                        m[9] = 0.0
                else:                             # zombi, araña, enderman: cuerpo a cuerpo
                    vx = (2.6 if m[0] == 102 else 2.2) * m[6] if abs(dx) > 0.5 else 0.0
                    if abs(dx) < 0.9 and abs(py - m[2]) < 1.5 and m[7] <= 0:
                        self.herir_a(pid, 3, m[6])        # -3 cada 1,5 s ('Attack?')
                        m[7] = 1.5
            else:                                 # animales: pasean (y siguen su comida)
                h = None
                if pid is None:
                    h = inv_id[self.sel]
                elif pid in self.otros:
                    h = self.otros[pid][4]
                if d["comida"] and h == d["comida"] and dist < 6:
                    m[6] = 1 if px > m[1] else -1
                    vx = 1.4 * m[6] if abs(px - m[1]) > 1.2 else 0.0
                else:
                    if m[7] <= 0:
                        m[7] = random.uniform(1.5, 4.0)
                        m[6] = random.choice((-1, 0, 1))
                    vx = 1.2 * m[6]
            self.ruido_mob(m, dt)
            if abs(m[3]) > 0.1:                   # empujón al golpearlo
                vx = m[3]
                m[3] *= 0.85
            suelo = abs(m[4]) < 0.01              # (se mira antes de la gravedad)
            e = [m[1], m[2], vx, suelo, d["w"], d["h"]]
            m[4] = max(-MAX_CAIDA, m[4] - GRAV * dt)
            self.mover_x(e, vx * dt)              # en el suelo sube escalones solo
            if e[2] == 0.0 and vx and suelo:
                m[4] = SALTO                      # saltar un obstáculo
            golpe = self.mover_y(e, m[4] * dt)
            if golpe:
                m[4] = 0.0
            m[1], m[2] = e[0], e[1]
            if m[6] == 0:
                m[6] = 1

    def flechas_paso(self, dt, jug):
        for f in list(self.flechas):
            f[3] -= GRAV * 0.4 * dt
            f[0] += f[2] * dt
            f[1] += f[3] * dt
            if solido(g(int(f[0]), int(f[1]))) or f[1] < 0:
                self.flechas.remove(f)
                continue
            for pid, px, py in jug:
                if px - 0.1 <= f[0] <= px + PW + 0.1 and py <= f[1] <= py + PH:
                    self.herir_a(pid, 3, 1 if f[2] > 0 else -1)
                    self.flechas.remove(f)
                    break

    def explotar(self, x, y, r):
        """'Explode Circle_pr': rompe los bloques del círculo y daña según la
        distancia (r - distancia) * 16."""
        lecho = B(LECHO_PM)
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy <= r * r:
                    bx, by = int(x) + dx, int(y) + dy
                    if g(bx, by) and g(bx, by) != lecho:
                        self.poner(bx, by, 0)
        sonar("explode%d" % random.randint(1, 4), 0.9)
        for pid, px, py in self.jugadores():
            dist = max(1.0, math.sqrt((px - x) ** 2 + (py - y) ** 2))
            if dist < r:
                self.herir_a(pid, int((r - dist) * 16), 1 if px > x else -1)
        for x2 in range(W):
            calc_alto(x2)

    def dano_mob(self, m, dano, cara, quien=None):
        """Golpe a un mob (lo aplica quien lleva los mobs). quien = id del que pega."""
        m[5] -= dano
        m[3] = 5.0 * cara
        m[4] = 5.0
        if m[0] < 100:                            # los animales huyen
            m[6], m[7] = cara, 3.0
        oigo = self.oye(m)
        nom = {1: "pig", 100: "zombiehurt", 102: "spider", 103: "skeletonhurt"}.get(m[0])
        if oigo and nom:
            sonar("%s%d" % (nom, random.randint(1, 2)), 0.6)
        if m[5] <= 0:
            self.mobs.remove(m)
            for it, a, b in MOBS[m[0]]["botin"]:  # 'Death Harvest'
                n = random.randint(a, b)
                if n:
                    if quien is None:
                        dar(it, n)
                    else:
                        red.enviar({"dar": [quien, it, n]})

    # ---- red --------------------------------------------------------------------------
    def red_paso(self):
        if not self.online:
            return
        self.cuadro += 1
        if self.cuadro % 3 == 0:
            d = {"p": [round(self.x, 2), round(self.y, 2), self.cara,
                       1 if abs(self.vx) > 0.5 else 0, inv_id[self.sel], 1 if self.muerto else 0]}
            if d != self.enviado:
                red.enviar(d)
                self.enviado = d
            if self.manda_mobs() and self.otros:   # el anfitrión cuenta dónde están los mobs
                red.enviar({"m": [[m[8], m[0], round(m[1], 2), round(m[2], 2), m[6]]
                                  for m in self.mobs], "t": round(self.tiempo, 1)})
        yo = red.mi_id()
        for m in red.recibir():
            t = m.get("t")
            d = m.get("d") or {}
            if t == "de" and "p" in d:
                p = d["p"]
                nombre_j = str(red.jugadores().get(m["id"], "?"))[:10]
                o = self.otros.get(m["id"])
                x, y = (o[0], o[1]) if o else (p[0], p[1])   # se dibuja yendo hacia p
                self.otros[m["id"]] = [x, y, p[2], p[3], p[4], nombre_j,
                                       p[5] if len(p) > 5 else 0, p[0], p[1]]
            elif t == "de" and "m" in d and not self.manda_mobs():
                # mobs del anfitrión: [id, tipo, x, y, cara]. En [3], [4] va adónde
                # van: se dibujan acercándose poco a poco (como Minecraft)
                antes = {m2[8]: m2 for m2 in self.mobs}
                nuevos = []
                for e in d["m"]:
                    v = antes.get(e[0])
                    x, y = (v[1], v[2]) if v else (e[2], e[3])
                    nuevos.append([e[1], x, y, e[2], e[3], 10, e[4], 0.0, e[0], 0.0])
                self.mobs = nuevos
                if "t" in d:                      # la hora del día es la del anfitrión
                    self.tiempo = d["t"]
            elif t == "de" and "golpe" in d and self.manda_mobs():
                mid, dano, cara = d["golpe"]
                for mob in self.mobs:
                    if mob[8] == mid:
                        self.dano_mob(mob, dano, cara, m["id"])
                        break
            elif t == "de" and "dano" in d and d["dano"][0] == yo and not self.muerto:
                if self.herir(d["dano"][1]):
                    self.vx = 6.0 * d["dano"][2]
            elif t == "de" and "dar" in d and d["dar"][0] == yo:
                dar(d["dar"][1], d["dar"][2])
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

    # ---- inventario, fabricar y horno ---------------------------------------------------------
    def cerca(self, pm):
        cx, cy = int(self.x), int(self.y)
        for dx in range(-4, 5):
            for dy in range(-3, 4):
                if L2PM[g(cx + dx, cy + dy)] == pm:
                    return True
        return False

    def opciones(self, sitio):
        """Lo que se puede hacer aquí: recetas (con o sin mesa) o fundir en el horno."""
        if sitio == "horno":
            out = []
            vistos = set()
            for it in inv_id:
                if it and it not in vistos and ficha(it)[F_FUNDE]:
                    vistos.add(it)
                    out.append(("horno", it, ficha(it)[F_FUNDE]))
            return out
        mesa = sitio == "mesa" or self.cerca(MESA_PM)
        out = []
        for k in range(n_recetas()):
            prod, cant, ing, necesita = receta(k)
            if mesa or not necesita:
                out.append(("receta", k, prod))
        return out

    def combustible(self, menos=0):
        """El combustible que más dura del inventario (columna 'Burn in furnace
        duration'), sin contar lo que se va a fundir."""
        mejor, dura = -1, 0
        for i in range(NHUECOS):
            it = inv_id[i]
            if it and it != menos and ficha(it)[F_QUEMA] > dura:
                mejor, dura = i, ficha(it)[F_QUEMA]
        return mejor

    def hacer(self, op):
        if op[0] == "horno":                      # 10 s de fuego por objeto
            it = op[1]
            if self.horno < 10:
                i = self.combustible(it)
                if i < 0:
                    self.aviso, self.aviso_t = "Sin combustible", 2.0
                    return
                c = inv_id[i]
                self.horno += ficha(c)[F_QUEMA]
                quitar_hueco(i)
                if c == CUBO_LAVA:
                    dar(CUBO)
            for i in range(NHUECOS):
                if inv_id[i] == it:
                    quitar_hueco(i)
                    break
            self.horno -= 10
            dar(op[2])
            sonar("fire", 0.4)
            return
        prod, cant, ing, _ = receta(op[1])
        if all(cuantos_raiz(r) >= n for r, n in ing.items()):
            for r, n in ing.items():
                quitar_raiz(r, n)
            if es_herramienta(prod):
                dar(prod)                         # nueva, con toda su durabilidad
            else:
                dar(prod, cant)
            sonar("wood%d" % random.randint(1, 4), 0.4)

    def abrir_inventario(self, sitio=None):
        if sitio is None:
            sitio = "mesa" if self.cerca(MESA_PM) else ""
        ops = self.opciones(sitio)
        sel, coger = 0, None
        n_op = len(ops)
        self.fondo_t = K.ms()
        while True:
            self.fondo_paso()
            P.recorte()
            P.rect(10, 6, 300, 206, 0xC6C6C6)
            P.marco(10, 6, 300, 206, 0x000000)
            P.texto("Inventario", 18, 12, 0x404040)
            P.texto({"": "Fabricar (2x2)", "mesa": "Mesa de trabajo", "horno": "Horno"}[sitio],
                    170, 12, 0x404040)
            for i in range(NHUECOS):
                x = 18 + (i % 9) * 20
                y = 26 + 2 * 22 + 10 if i < 9 else 26 + (i // 9 - 1) * 22   # barra abajo
                P.rect(x, y, 19, 21, 0x8B8B8B)
                P.rect(x + 1, y + 1, 17, 19, 0x6E6E6E if coger != i else 0xA0A050)
                icono(inv_id[i], x + 1, y + 2, inv_n[i])
                if sel == i:
                    P.marco(x - 1, y - 1, 21, 23, 0xFFFFFF)
            y0 = 112
            P.texto("Fundir (EXE):" if sitio == "horno" else "Recetas (EXE fabrica):", 18, y0 - 10, 0x404040)
            if sitio == "horno":
                P.texto("fuego: %ds" % int(self.horno), 230, y0 - 10, 0x804000)
            top = max(0, sel - NHUECOS - 3) if sel >= NHUECOS else 0
            for j in range(top, min(n_op, top + 5)):
                op = ops[j]
                y = y0 + (j - top) * 18
                if op[0] == "horno":
                    ok = op[1] in inv_id
                    txt = "%s  <-  %s" % (nombre(op[2])[:16], nombre(op[1])[:16])
                    prod = op[2]
                else:
                    prod, cant, ing, _ = receta(op[1])
                    ok = all(cuantos_raiz(r) >= n for r, n in ing.items())
                    txt = "%s%s <- " % (nombre(prod)[:14], "" if es_herramienta(prod) or cant == 1
                                        else " x%d" % cant) + \
                        ", ".join("%d %s" % (n, nombre(r)[:8]) for r, n in ing.items())
                P.rect(18, y, 284, 16, 0xFFFFFF if sel == NHUECOS + j else 0xB0B0B0)
                icono(prod, 20, y)
                P.texto(txt[:43], 38, y + 4, 0x206020 if ok else 0x802020)
            nom = nombre(inv_id[sel]) if sel < NHUECOS else ""
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
                        sel = min(NHUECOS + n_op - 1, sel + 1)
                    elif 9 <= sel < 18:
                        sel += 9
                    elif sel >= 18:
                        sel -= 18
                    else:
                        sel = NHUECOS if n_op else sel
                elif k == "EXE":
                    if sel >= NHUECOS:
                        self.hacer(ops[sel - NHUECOS])
                        if sitio == "horno":
                            ops = self.opciones(sitio)
                            n_op = len(ops)
                            sel = min(sel, NHUECOS + n_op - 1) if n_op else 0
                    elif coger is None:
                        coger = sel
                    else:
                        a, b = coger, sel                 # juntar pilas iguales o cambiar
                        if inv_id[a] == inv_id[b] and a != b and not es_herramienta(inv_id[a]):
                            k2 = min(inv_n[a], max_pila(inv_id[b]) - inv_n[b])
                            inv_n[b] += k2
                            quitar_hueco(a, k2)
                        else:
                            inv_id[a], inv_id[b] = inv_id[b], inv_id[a]
                            inv_n[a], inv_n[b] = inv_n[b], inv_n[a]
                        coger = None
                elif k in ("9", "CH:q") and sel < NHUECOS and inv_id[sel]:
                    quitar_hueco(sel)
            if fin:
                break
        self.completo = True
        self.hud = None

    # ---- pausa ---------------------------------------------------------------------------
    def pausa(self):
        ops = ["Volver al juego", "Guardar", "Guardar y salir", "Salir sin guardar"]
        sel = 0
        self.fondo_t = K.ms()
        while True:
            self.fondo_paso()
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
                if inv_id[self.sel]:
                    quitar_hueco(self.sel)
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
        self.dano_t = max(0.0, self.dano_t - dt)
        self.tiempo += dt
        # hambre como en Paper Minecraft: la saturación se gasta antes que el hambre;
        # cada 4 s (120 ticks) +1 de vida con hambre > 17.5 y -1 sin comida
        if self.sat < 0:
            self.hambre = max(0, self.hambre - 1)
            self.sat += 4
        self.ticks += dt
        if self.ticks >= 4:
            self.ticks -= 4
            if self.hambre > 17 and self.vida < 20:
                self.vida += 1
            elif self.hambre == 0 and self.vida > 1:
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

    def fondo_paso(self):
        """Con un menú abierto (o muerto) la partida online sigue: mobs, red y hora."""
        if not self.online:
            return
        ahora = K.ms()
        dt = min(0.1, max(0.0, (ahora - self.fondo_t) / 1000))
        self.fondo_t = ahora
        self.tiempo += dt
        self.mobs_paso(dt)
        self.red_paso()
        self.completo = True                      # al volver se repinta todo

    def morir(self):
        P.recorte()
        P.rect(0, 0, P.ANCHO, P.ALTO, 0x601010)
        P.texto("Has muerto", 100, 70, 0xFFFFFF, None, 2)
        P.texto("EXE: reaparecer", 110, 120, 0xFFC0C0)
        P.mostrar()
        self.muerto = True
        self.fondo_t = K.ms()
        while True:
            self.fondo_paso()
            for k, sh in K.eventos():
                if k == "EXE":
                    self.muerto = False
                    self.vida, self.hambre, self.sat = 20, 20, 5.0
                    for i in range(NHUECOS):          # como en Minecraft: lo pierdes todo
                        inv_id[i] = inv_n[i] = 0
                    self.aparecer()
                    self.hud = None
                    return
            P.mostrar()


def acercar(a, b):
    """Interpolación: un poco más cerca de b (de golpe si está lejos)."""
    return b if abs(b - a) > 3 else a + (b - a) * 0.45


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
    cab = {"v": 2, "nombre": j.nombre, "x": j.x, "y": j.y, "vida": j.vida, "hambre": j.hambre,
           "t": j.tiempo, "inv": [[inv_id[i], inv_n[i]] for i in range(NHUECOS) if inv_id[i]],
           "pos": [i for i in range(NHUECOS) if inv_id[i]], "ids": list(L2PM)}
    with open("%s/%s.mc2d" % (CARPETA, j.nombre), "wb") as f:
        f.write(b"MC2D2\n")
        f.write(json.dumps(cab).encode())
        f.write(b"\n")
        f.write(mundo)


def cargar(nombre_m):
    with open("%s/%s.mc2d" % (CARPETA, nombre_m), "rb") as f:
        datos = f.read()
    if not datos.startswith(b"MC2D2"):
        raise ValueError("mundo de la version anterior")
    a = datos.find(b"\n")
    b = datos.find(b"\n", a + 1)
    cab = json.loads(datos[a + 1:b].decode())
    mundo[:] = datos[b + 1:b + 1 + W * H]
    ids = cab.get("ids")
    if ids and ids != list(L2PM):                 # otra conversión: se traduce
        tabla = bytearray(B(pm) for pm in ids)
        for i in range(W * H):
            mundo[i] = tabla[mundo[i]] if mundo[i] < len(tabla) else 0
    for x in range(W):
        calc_alto(x)
    for i in range(NHUECOS):
        inv_id[i] = inv_n[i] = 0
    for p, (it, n) in zip(cab.get("pos", []), cab.get("inv", [])):
        inv_id[p], inv_n[p] = it, n
    j = Juego(nombre_m)
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
    red.var("mundo", {"n": n, "t": j.tiempo, "ids": list(L2PM)})


def recibir_mundo():
    fin = K.ms() + 15000
    while K.ms() < fin:
        vs = red.vars()
        info = vs.get("mundo")
        if info:
            if info.get("ids") != list(L2PM):
                return {"error": "ids"}           # convertido con otra versión
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
    if NB:
        s = tex(ficha(TIERRA_PM)[F_TILE])
        for y in range(0, P.ALTO, 32):
            for x in range(0, P.ANCHO, 32):
                P.dibujar(s, x, y, 2)
    else:
        P.limpiar(0x3A2A1E)


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


def nuevo_mundo(nombre_m):
    generar(random.getrandbits(30))
    for i in range(NHUECOS):
        inv_id[i] = inv_n[i] = 0
    j = Juego(nombre_m)
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
            nombre_m = preguntar("Nombre del mundo:", "Mundo %d" % n)
            if nombre_m:
                return nuevo_mundo(nombre_m.strip()[:16] or "Mundo")
        else:
            accion = menu(ops[r], ["Jugar", "Borrar", "Atras"])
            if accion == 0:
                mensaje(["Cargando %s..." % ops[r]])
                try:
                    return cargar(ops[r])
                except (ValueError, OSError):
                    menu("No se puede abrir", ["Atras"], "Es de la version anterior")
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
        if not info or "error" in info:
            menu("No se pudo unir", ["Atras"], "El anfitrion no mando el mundo" if not info
                 else "Convertid Paper Minecraft con el mismo pm_a_mc2d.py")
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


def preparar_mobs():
    """Tamaño de cada criatura (en bloques) según su dibujo de Paper Minecraft."""
    for t, d in MOBS.items():
        if d["marcos"]:
            s = spr("mob/%d.png" % d["marcos"][0])
            d["w"] = max(0.5, s.ancho / T * 0.8)
            d["h"] = max(0.5, s.alto / T)
        else:
            d["w"] = d["h"] = 1.0


def main():
    err = cargar_datos()
    if err:
        P.limpiar(0x3A2A1E)
        lineas = [err, "", "Minecraft 2D usa las imagenes y las tablas", "de Paper Minecraft. En el PC:", "",
                  "python pc/pm_a_mc2d.py \"Paper Minecraft.sb3\"", "",
                  "y copia juegos/minecraft2d/pm a la SD.", "", "DEL: salir"]
        for i, l in enumerate(lineas):
            P.texto(l, 14, 30 + i * 14, 0xFFFFFF)
        P.mostrar()
        while True:
            for k, sh in K.eventos():
                if k in ("DEL", "AC", "EXE"):
                    return
            P.mostrar()
    preparar_mobs()
    buscar_sonidos()
    while True:
        r = menu("MINECRAFT 2D", ["Un jugador", "Multijugador", "Controles", "Salir"],
                 "Paper Minecraft para calculadora")
        if r in (3, -1):
            break
        if r == 2:
            mensaje(["Controles:", "", "<- ->  andar     ^ saltar/nadar/subir",
                     "8 4 6 2  mover el cursor", "5  picar / golpear (mantener)",
                     "EXE  poner, comer, mesa / horno, cubos", "1 3  cambiar de objeto",
                     "7  inventario y fabricar   9  tirar", "DEL  menu (guardar)",
                     "PC: WASD, E inventario, Q tirar, 1-9"])
            menu("Controles", ["Atras"])
            continue
        j = un_jugador() if r == 0 else multijugador()
        if j:
            jugar(j)
