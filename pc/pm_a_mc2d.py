#!/usr/bin/env python3
# =============================================================================
#  pm_a_mc2d.py  —  Saca de Paper Minecraft (.sb3) lo que usa Minecraft 2D
# -----------------------------------------------------------------------------
#  Minecraft 2D (/lib/mc2d.py) es la versión de Paper Minecraft que cabe en el
#  ESP32. No se inventa nada: usa las imágenes y las tablas del propio juego de
#  griffpatch, sacadas de tu .sb3 con este programa:
#
#     python pc/pm_a_mc2d.py "Paper Minecraft v11.7.sb3"
#
#  Escribe simulador/sd/juegos/minecraft2d/pm/ (no se sube al repositorio: es
#  contenido de Paper Minecraft y de Mojang):
#    tex/t<n>.png      disfraz n del objeto Tiles a 16x16 (bloques e iconos)
#    tex/grieta1..9    las grietas al picar (objeto Cursor)
#    mob/<n>.png       disfraz n del objeto Mob al tamaño de cada criatura
#    steve<k>.png      Steve montado con sus partes en las poses del juego
#    vida<n>, hambre<n>, armadura<n>  las barras de corazones, comida y armadura
#    bloques.bin       _BLOCK_DATA (una ficha de tamaño fijo por bloque)
#    nombres.txt       nombres de los bloques y objetos
#    recetas.bin       _Recipes (resultado, cantidad -o durabilidad- y la rejilla 3x3)
#    datos.json        _FOOD_DATA, _MOB_DATA, BIOME_DATA, botín y lo demás
#  En el ESP32 todo esto ocupa poco en memoria: las tablas son bytes que se leen
#  ficha a ficha (struct), no listas de Python.
# =============================================================================
import io
import json
import struct
import sys
import zipfile
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
SALIDA = HERE.parent / "simulador" / "sd" / "juegos" / "minecraft2d" / "pm"
VERSION = 2

# Ficha de cada bloque en bloques.bin (ver mc2d.py, que la lee igual)
FICHA = struct.Struct("<BHBBBBbbhHHbbHHHH")

# Píxeles por unidad de Scratch: en Paper Minecraft una casilla mide 40 y en
# Minecraft 2D 16 píxeles
PX = 16 / 40

# Botín de cada criatura (procedimiento 'Death Harvest' del objeto Mob):
# tipo -> [(objeto, mínimo, máximo)]
BOTIN = {1: [(113, 1, 3)], 2: [(122, 1, 3)], 3: [(163, 0, 2), (171, 1, 3)],
         4: [(164, 1, 1), (167, 0, 2)], 100: [(119, 0, 2)], 101: [(125, 0, 2)],
         102: [(170, 0, 2)], 103: [(194, 0, 2), (131, 0, 2)], 105: [(84, 0, 1), (119, 0, 1)],
         106: [(84, 0, 1), (119, 0, 1)]}

# Las que salen en Minecraft 2D: animales y lobo (de día), perro (lobo domado),
# monstruos (de noche), lobo enfadado, porquero zombi (Nether; 106 = enfadado)
# y enderman
CRIATURAS = (1, 2, 3, 4, 5, 6, 100, 101, 102, 103, 104, 105, 106, 107)

# Bloques que van en el mundo aunque su grupo diga que no (el portal del Nether)
SIEMPRE = (266,)

# Poses de Steve: las de verdad, sacadas del juego andando (scratch_red.py, el
# "espejo"): (objeto, disfraz, dx, dy, tamaño) y la dirección según el paso.
# Orden de capas: pierna de atrás, brazo de atrás, cuerpo, pierna, cabeza, brazo.
PASOS = [0, 15, 30, 45, 30, 15, 0, -15, -30, -45, -30, -15]
BRAZO = {0: 0, 15: 22, 30: 22, 45: 45}


def lista(listas, nombre):
    for n, v in listas:
        if n == nombre:
            return v
    raise SystemExit("No encuentro la lista %s en el proyecto" % nombre)


def filas(datos, ancho):
    """Las tablas de Paper Minecraft: una cabecera y filas de 'ancho' elementos
    (el último vacío, de separador; a la última fila le puede faltar)."""
    return [datos[i:i + ancho] for i in range(ancho, len(datos) - ancho + 2, ancho)]


def num(v, defecto=0):
    try:
        return float(str(v).strip())
    except ValueError:
        return defecto


def cargar_png(zf, costume):
    """Imagen del disfraz y su resolución (px del dibujo por unidad de Scratch).
    Los SVG se pasan a imagen al doble, como los PNG del juego."""
    data = zf.read(costume["md5ext"])
    if costume.get("dataFormat") == "svg":
        try:
            import resvg_py
            data = bytes(resvg_py.svg_to_bytes(svg_string=data.decode("utf-8", "replace"), zoom=2))
        except ImportError:
            import pygame
            sup = pygame.image.load(io.BytesIO(data), "x.svg")
            sup = pygame.transform.scale2x(sup)
            data = io.BytesIO()
            pygame.image.save(sup, data, "x.png")
            data = data.getvalue()
        return Image.open(io.BytesIO(data)).convert("RGBA"), 2
    return Image.open(io.BytesIO(data)).convert("RGBA"), costume.get("bitmapResolution", 1)


CIELO_PM = (203, 215, 254)             # el azul claro del cielo de Paper Minecraft


def a_16(im):
    """Los bloques del .sb3 son 16x16 ampliados x5 (80x80): se toma el centro de
    cada cuadro de 5x5, así sale el pixel art original exacto. Las plantas traen
    pintado el cielo de Paper Minecraft de fondo: se hace transparente (aquí el
    cielo cambia con la hora)."""
    im = im.resize((16, 16), Image.NEAREST)
    px = im.load()
    for y in range(16):
        for x in range(16):
            r, g, b, a = px[x, y]
            if abs(r - CIELO_PM[0]) < 6 and abs(g - CIELO_PM[1]) < 6 and abs(b - CIELO_PM[2]) < 6:
                px[x, y] = (0, 0, 0, 0)
    return im


def pieza(zf, costume, dx, dy, tam, direccion, girar=True):
    """Una parte de Steve como la dibuja Scratch: centro de giro en (dx, dy),
    girada (dirección - 90) grados y al tamaño tam. Devuelve (imagen, x, y) con
    (x, y) la esquina en píxeles finales respecto a la base del jugador."""
    im, res = cargar_png(zf, costume)
    f = tam / 100 * PX / res                         # px finales por px del PNG
    w, h = max(1, round(im.width * f)), max(1, round(im.height * f))
    im = im.resize((w, h), Image.NEAREST)
    cx, cy = costume["rotationCenterX"] * f, costume["rotationCenterY"] * f   # (en px del PNG)
    lado = int(2 * max(w, h) + 4)
    lienzo = Image.new("RGBA", (lado, lado))
    lienzo.paste(im, (round(lado / 2 - cx), round(lado / 2 - cy)))
    if girar and direccion != 90:
        lienzo = lienzo.rotate(-(direccion - 90), Image.NEAREST)
    return lienzo, dx * PX - lado / 2, -dy * PX - lado / 2


def montar_steve(zf, objetos):
    def disfraz(obj, nombre):
        return next(c for c in objetos[obj]["costumes"] if c["name"] == nombre)
    marcos = []
    for a in PASOS[:7]:
        b = BRAZO[abs(a)] * (1 if a >= 0 else -1)
        partes = [("Steve Legs2", "leg", 0, -5, 210, 90 + a), ("Steve Arm", "Arm4", 0, 15, 210, 180 + b),
                  ("Steve", "Body4", 0, 0, 220, 90), ("Steve Legs2", "leg", 0, -5, 210, 90 - a),
                  ("Steves Head", "Right", 0, 19, 200, 180), ("Steve Arm", "Arm4", 0, 15, 210, 180 - b)]
        marcos.append([pieza(zf, disfraz(o, c), dx, dy, t, d) for o, c, dx, dy, t, d in partes])
    # Todos los fotogramas con el mismo recuadro: los pies abajo del todo
    x0 = min(x for m in marcos for _, x, _ in m)
    y0 = min(y for m in marcos for _, _, y in m)
    x1 = max(x + im.width for m in marcos for im, x, _ in m)
    y1 = max(y + im.height for m in marcos for im, _, y in m)
    lado = (int(x1 - x0) + 2, int(y1 - y0) + 2)
    imgs = []
    for m in marcos:
        lienzo = Image.new("RGBA", lado)
        for im, x, y in m:
            lienzo.alpha_composite(im, (round(x - x0), round(y - y0)))
        imgs.append(lienzo)
    caja = None
    for im in imgs:
        b = im.getbbox()
        caja = b if caja is None else (min(caja[0], b[0]), min(caja[1], b[1]),
                                        max(caja[2], b[2]), max(caja[3], b[3]))
    imgs = [im.crop(caja) for im in imgs]
    base_x = round(-x0 - caja[0])                   # dónde cae la base del jugador
    return imgs, base_x


def convertir(sb3):
    zf = zipfile.ZipFile(sb3)
    proj = json.loads(zf.read("project.json"))
    objetos = {t["name"]: t for t in proj["targets"]}
    listas = [(v[0], v[1]) for t in proj["targets"] for v in t.get("lists", {}).values()]
    SALIDA.mkdir(parents=True, exist_ok=True)
    (SALIDA / "tex").mkdir(exist_ok=True)
    (SALIDA / "mob").mkdir(exist_ok=True)

    # ---- bloques -------------------------------------------------------------------
    bloques = {}
    for f in filas(lista(listas, "_BLOCK_DATA"), 21):
        if str(f[0]).strip().isdigit():
            bloques[int(f[0])] = f
    maxid = max(bloques)
    fichas, nombres, tiles = [], [], set()
    for i in range(maxid + 1):
        f = bloques.get(i)
        if f is None:
            fichas.append(FICHA.pack(*([0] * 17)))
            nombres.append("")
            continue
        d = num(f[3])
        dureza = 0 if d == 0 else (1 if d < 0 else (65535 if d >= 600 else min(65534, round(d * 100))))
        herr = str(f[4]).strip() or "N"
        letra = 0 if herr[0] == "N" else ord(herr[0])
        nivel = int(herr[1:]) if herr[1:].isdigit() else 0
        solido = {"Y": 1, "P": 2}.get(str(f[2]).strip(), 0)
        tile, inv = int(num(f[15])), int(num(f[16]))
        tiles.update((tile, inv))
        fichas.append(FICHA.pack(solido, dureza, letra, nivel, int(num(f[5])), ord((str(f[7]).strip() or "N")[0]),
                                 int(num(f[8])), int(num(f[9])), int(num(f[10])), max(0, int(num(f[11]))),
                                 min(65535, max(0, int(num(f[12])))), int(num(f[13])), int(num(f[14])),
                                 tile, inv, int(num(f[17])), int(num(f[18]))))
        nombres.append(str(f[1]).strip())
    (SALIDA / "bloques.bin").write_bytes(b"PMB1" + struct.pack("<HH", maxid + 1, FICHA.size) + b"".join(fichas))
    (SALIDA / "nombres.txt").write_text("\n".join(nombres), encoding="utf-8")

    # Bloques que pueden estar en el mundo (el mundo es un byte por casilla): todo
    # menos herramientas, comida, materiales, huevos y armadura
    en_mundo = [i for i, f in sorted(bloques.items())
                if int(num(f[9])) not in (0, 1, -1, 12, 13, 14, 15, 16) or i in SIEMPRE]
    if 1 in en_mundo:
        en_mundo.remove(1)
    en_mundo = [1] + en_mundo                       # 0 = aire
    assert len(en_mundo) < 256, len(en_mundo)

    # ---- texturas de Tiles ---------------------------------------------------------------
    tcs = objetos["Tiles"]["costumes"]
    for n in sorted(tiles):
        if 1 <= n <= len(tcs):
            im, _ = cargar_png(zf, tcs[n - 1])
            a_16(im).save(SALIDA / "tex" / ("t%d.png" % n))
    for k, c in enumerate(objetos["Cursor"]["costumes"]):
        if c["name"].startswith("dig") and c["name"][3:].isdigit():
            im, _ = cargar_png(zf, c)
            im.resize((16, 16), Image.NEAREST).save(SALIDA / "tex" / ("grieta%s.png" % c["name"][3:]))

    # ---- criaturas -------------------------------------------------------------------------
    mobs = {}
    mcs = objetos["Mob"]["costumes"]
    for f in filas(lista(listas, "_MOB_DATA"), 13):
        if not str(f[0]).strip().isdigit():
            continue
        tipo, tam = int(f[0]), num(f[2], 100)
        if tipo not in CRIATURAS:
            continue
        raiz, paso = int(num(f[5])), int(num(f[6]))
        marcos = []
        for n in range(raiz, raiz + max(1, paso) + 1):
            if not 1 <= n <= len(mcs):
                continue
            im, res = cargar_png(zf, mcs[n - 1])
            fac = tam / 100 * PX / res
            im = im.resize((max(1, round(im.width * fac)), max(1, round(im.height * fac))), Image.NEAREST)
            b = im.getbbox()
            if b:
                im = im.crop((b[0], b[1], b[2], b[3]))
            im.save(SALIDA / "mob" / ("%d.png" % n))
            marcos.append(n)
        mobs[tipo] = {"marcos": marcos, "vida": int(num(f[8], 10)),          # (lo justo: en el
                      "comida": int(num(f[9])), "botin": BOTIN.get(tipo, []),  # ESP32 cada byte cuenta)
                      "tam": list(Image.open(SALIDA / "mob" / ("%d.png" % marcos[0])).size) if marcos else [16, 16]}

    # ---- Steve ---------------------------------------------------------------------------
    imgs, base_x = montar_steve(zf, objetos)
    for k, im in enumerate(imgs):
        im.save(SALIDA / ("steve%d.png" % k))

    # ---- corazones y comida (los de Paper Minecraft) -------------------------------------
    for obj, nombre in (("Health", "vida"), ("Hunger", "hambre"), ("Armor", "armadura")):
        for c in objetos[obj]["costumes"]:
            dig = "".join(ch for ch in c["name"] if ch.isdigit())
            if dig:
                im, res = cargar_png(zf, c)
                # media unidad de Scratch por píxel, al tamaño del objeto (la comida
                # está al 200 %)
                fac = 0.5 / res * objetos[obj].get("size", 100) / 100
                im.resize((round(im.width * fac), round(im.height * fac)), Image.NEAREST) \
                    .save(SALIDA / ("%s%s.png" % (nombre, dig)))

    # ---- recetas ---------------------------------------------------------------------------
    recetas = []
    rl = lista(listas, "_Recipes")                  # "-- nombre", producto, cantidad, 3x3
    for i in range(len(rl) - 3):
        f = rl[i:i + 4]
        if not (str(f[0]).startswith("--") and str(f[1]).strip().isdigit()):
            continue
        celdas = str(f[3])
        rej = [celdas[i:i + 3].strip() for i in range(0, 27, 3)]
        rej = [int(c) if c.isdigit() else 0 for c in rej]
        cant = int(num(f[2], 1))                    # (en las herramientas: su durabilidad)
        if not 1 <= cant <= 65535 or not any(rej):
            continue
        recetas.append(struct.pack("<HH9H", int(f[1]), cant, *rej))
    (SALIDA / "recetas.bin").write_bytes(b"PMR1" + b"".join(recetas))

    comida = {}
    for f in filas(lista(listas, "_FOOD_DATA"), 7):
        if str(f[0]).strip().isdigit():
            comida[int(f[0])] = [num(f[2]), num(f[3]), num(f[4]), int(num(f[5]))]
    biomas = []
    for f in filas(lista(listas, "BIOME_DATA"), 9):
        if str(f[0]).strip().isdigit():
            biomas.append([str(f[1]), str(f[2]), num(f[3], 1), num(f[4]), num(f[5], 1),
                           str(f[6]), num(f[7])])
    datos = {"version": VERSION, "en_mundo": en_mundo, "comida": comida, "mobs": mobs,
             "biomas": biomas, "steve": {"marcos": len(imgs), "base_x": base_x,
                                         "ancho": imgs[0].width, "alto": imgs[0].height}}
    (SALIDA / "datos.json").write_text(json.dumps(datos, separators=(",", ":")), encoding="utf-8")
    print("Hecho:", SALIDA)
    print("  %d bloques (%d pueden estar en el mundo), %d recetas, %d criaturas, %d texturas"
          % (len(bloques), len(en_mundo), len(recetas), len(mobs), len(tiles)))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("uso: python pc/pm_a_mc2d.py <Paper Minecraft.sb3>")
        sys.exit(1)
    convertir(sys.argv[1])
