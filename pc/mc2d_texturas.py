#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 mc2d_texturas.py — Genera las texturas de Minecraft 2D (simulador/sd/juegos/minecraft2d/tex)
===============================================================================
 Pixel art PROPIO de 16x16 (no son las texturas de Mojang): cada bloque se
 pinta con su paleta y ruido determinista, al estilo de Minecraft.
 También el jugador (12x28), los mobs, los objetos y las grietas al picar.

   python pc/mc2d_texturas.py
===============================================================================
"""
import os
import random
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame

OUT = Path(__file__).resolve().parent.parent / "simulador" / "sd" / "juegos" / "minecraft2d" / "tex"
T = 16
CLEAR = (0, 0, 0, 0)


def surf(w=T, h=T):
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    s.fill(CLEAR)
    return s


def noise(s, pal, seed, x0=0, y0=0, w=T, h=T, weights=None):
    rnd = random.Random(seed)
    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            s.set_at((x, y), rnd.choices(pal, weights)[0] if weights else rnd.choice(pal))
    return s


def speckle(s, pal, n, seed, size=1):
    rnd = random.Random(seed)
    for _ in range(n):
        x, y = rnd.randrange(T - size + 1), rnd.randrange(T - size + 1)
        c = rnd.choice(pal)
        for dy in range(size):
            for dx in range(size):
                s.set_at((x + dx, y + dy), c)
    return s


def ore(base_seed, spots):
    s = stone(base_seed)
    rnd = random.Random(base_seed + 7)
    for _ in range(5):
        x, y = rnd.randrange(1, T - 3), rnd.randrange(1, T - 3)
        for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1), (2, 1)):
            s.set_at((x + dx, y + dy), spots[(dx + dy) % len(spots)])
    return s


def stone(seed=1):
    return noise(surf(), [(125, 125, 125), (115, 115, 115), (135, 135, 135), (105, 105, 105)], seed)


def dirt(seed=2):
    return noise(surf(), [(134, 96, 67), (121, 85, 58), (150, 108, 74), (108, 76, 52)], seed)


def textures():
    tx = {}
    tx["piedra"] = stone()
    tx["tierra"] = dirt()
    g = dirt(3)
    noise(g, [(106, 170, 64), (93, 155, 52), (120, 186, 72)], 4, 0, 0, T, 4)
    rnd = random.Random(5)
    for x in range(T):                                    # hierba que cuelga
        for y in range(4, 4 + rnd.randint(0, 2)):
            g.set_at((x, y), (93, 155, 52))
    tx["hierba"] = g
    c = noise(surf(), [(122, 122, 122), (100, 100, 100), (140, 140, 140)], 6)
    for y in (3, 8, 13):                                  # juntas de la roca
        for x in range(T):
            if (x + y) % 5 == 0:
                c.set_at((x, y), (70, 70, 70))
    tx["roca"] = c
    lg = noise(surf(), [(104, 82, 50), (92, 71, 43), (116, 92, 58)], 8)
    for x in (2, 7, 12):
        for y in range(T):
            lg.set_at((x, y), (72, 56, 33))
    tx["tronco"] = lg
    lv = surf()
    noise(lv, [(60, 130, 40), (45, 110, 30), (75, 150, 50), CLEAR], 9, weights=[4, 4, 3, 1])
    tx["hojas"] = lv
    pl = noise(surf(), [(180, 144, 90), (166, 132, 82), (192, 154, 98)], 10)
    for y in (3, 7, 11, 15):
        for x in range(T):
            pl.set_at((x, y), (120, 92, 56))
    for y0, x in ((0, 5), (4, 12), (8, 3), (12, 10)):
        for y in range(y0, y0 + 3):
            pl.set_at((x, y), (120, 92, 56))
    tx["tablones"] = pl
    tx["arena"] = noise(surf(), [(219, 207, 163), (206, 194, 150), (228, 218, 176)], 11)
    tx["grava"] = noise(surf(), [(136, 126, 126), (110, 104, 104), (160, 150, 150), (90, 86, 86)], 12)
    tx["carbon_mena"] = ore(13, [(30, 30, 30), (50, 50, 50)])
    tx["hierro_mena"] = ore(14, [(216, 175, 147), (190, 150, 120)])
    tx["oro_mena"] = ore(15, [(250, 220, 70), (230, 190, 40)])
    tx["diamante_mena"] = ore(16, [(90, 230, 220), (60, 200, 200)])
    tx["lecho"] = noise(surf(), [(40, 40, 40), (80, 80, 80), (20, 20, 20), (110, 110, 110)], 17)
    w = surf()
    noise(w, [(48, 92, 210, 190), (40, 82, 200, 190), (60, 104, 220, 190)], 18)
    tx["agua"] = w
    ct = tx["tablones"].copy()
    noise(ct, [(150, 100, 60), (130, 86, 50)], 19, 0, 0, T, 4)
    for x in range(T):
        ct.set_at((x, 4), (90, 60, 35))
    for (x, y) in ((4, 8), (5, 8), (4, 9), (10, 9), (11, 9), (11, 10)):
        ct.set_at((x, y), (70, 70, 70))                   # herramientas colgadas
    tx["mesa"] = ct
    fu = stone(20)
    pygame.draw.rect(fu, (60, 60, 60), (4, 8, 8, 6))
    pygame.draw.rect(fu, (240, 120, 30), (5, 11, 6, 2))
    pygame.draw.rect(fu, (90, 90, 90), (0, 0, T, T), 1)
    tx["horno"] = fu
    gl = surf()
    pygame.draw.rect(gl, (200, 230, 240), (0, 0, T, T), 1)
    for i in range(3, 7):
        gl.set_at((i, 10 - i), (230, 245, 250))
    tx["cristal"] = gl
    br = surf()
    br.fill((150, 70, 55))
    for y in (3, 7, 11, 15):
        pygame.draw.line(br, (200, 190, 180), (0, y), (15, y))
    for y0, off in ((0, 0), (4, 4), (8, 0), (12, 4)):
        for x in range(off, T, 8):
            pygame.draw.line(br, (200, 190, 180), (x, y0), (x, y0 + 2))
    tx["ladrillos"] = br
    sn = dirt(21)
    noise(sn, [(245, 250, 252), (230, 238, 245)], 22, 0, 0, T, 5)
    tx["nieve"] = sn
    ca = surf()
    noise(ca, [(70, 140, 50), (55, 120, 40), (85, 160, 60)], 23, 2, 0, 12, T)
    for y in range(1, T, 3):
        ca.set_at((1, y), (30, 60, 20))
        ca.set_at((14, y + 1), (30, 60, 20))
    tx["cactus"] = ca
    for nom, col in (("flor_roja", (220, 30, 30)), ("flor_amarilla", (250, 220, 40))):
        f = surf()
        pygame.draw.line(f, (40, 120, 30), (8, 15), (8, 8))
        pygame.draw.line(f, (40, 120, 30), (8, 12), (10, 10))
        pygame.draw.circle(f, col, (8, 6), 3)
        f.set_at((8, 6), (250, 230, 120))
        tx[nom] = f
    hb = surf()
    rnd = random.Random(24)
    for x in range(1, 15, 2):
        hgt = rnd.randint(5, 11)
        pygame.draw.line(hb, (80, 160, 50), (x, 15), (x + rnd.choice((-1, 0, 1)), 15 - hgt))
    tx["hierba_alta"] = hb
    to = surf()
    pygame.draw.rect(to, (120, 90, 50), (7, 6, 2, 10))
    pygame.draw.rect(to, (255, 200, 60), (6, 3, 4, 4))
    pygame.draw.rect(to, (255, 250, 200), (7, 4, 2, 2))
    tx["antorcha"] = to
    return tx


def item(draw):
    s = surf()
    draw(s)
    return s


def tool(head_col, kind):
    s = surf()
    pygame.draw.line(s, (120, 90, 50), (3, 13), (11, 5), 2)            # mango
    if kind == "pico":
        pygame.draw.line(s, head_col, (5, 2), (13, 10), 3)
    elif kind == "hacha":
        pygame.draw.polygon(s, head_col, [(9, 2), (14, 4), (13, 8), (10, 7)])
    elif kind == "pala":
        pygame.draw.circle(s, head_col, (12, 4), 3)
    elif kind == "espada":
        s.fill(CLEAR)
        pygame.draw.line(s, head_col, (4, 12), (13, 3), 3)
        pygame.draw.line(s, (120, 90, 50), (2, 14), (5, 11), 2)
        pygame.draw.line(s, (80, 60, 30), (3, 9), (7, 13), 2)
    return s


def items():
    it = {}
    it["palo"] = item(lambda s: pygame.draw.line(s, (120, 90, 50), (4, 13), (12, 3), 2))
    it["carbon"] = item(lambda s: pygame.draw.circle(s, (30, 30, 30), (8, 9), 5))
    it["lingote_hierro"] = item(lambda s: pygame.draw.polygon(s, (220, 220, 220), [(2, 10), (5, 6), (14, 6), (11, 10)]))
    it["lingote_oro"] = item(lambda s: pygame.draw.polygon(s, (250, 215, 60), [(2, 10), (5, 6), (14, 6), (11, 10)]))
    it["diamante"] = item(lambda s: pygame.draw.polygon(s, (90, 230, 220), [(8, 2), (14, 7), (8, 14), (2, 7)]))
    it["manzana"] = item(lambda s: (pygame.draw.circle(s, (220, 30, 30), (8, 9), 5),
                                    pygame.draw.line(s, (90, 60, 30), (8, 4), (9, 2))))
    it["carne"] = item(lambda s: (pygame.draw.ellipse(s, (230, 120, 120), (2, 4, 12, 9)),
                                  pygame.draw.ellipse(s, (250, 240, 230), (10, 6, 4, 4))))
    it["carne_asada"] = item(lambda s: (pygame.draw.ellipse(s, (150, 80, 40), (2, 4, 12, 9)),
                                        pygame.draw.ellipse(s, (250, 240, 230), (10, 6, 4, 4))))
    it["carne_podrida"] = item(lambda s: pygame.draw.ellipse(s, (120, 140, 60), (2, 4, 12, 9)))
    for mat, col in (("madera", (160, 125, 80)), ("piedra", (130, 130, 130)),
                     ("hierro", (225, 225, 225)), ("diamante", (90, 230, 220))):
        for kind in ("pico", "hacha", "pala", "espada"):
            it["%s_%s" % (kind, mat)] = tool(col, kind)
    return it


def player():
    """Jugador 12x28 de pie y andando (2 fotogramas). Mirando a la derecha."""
    frames = {}
    skin, hair, shirt, pants, shoe = (200, 150, 110), (60, 40, 20), (40, 170, 170), (60, 60, 160), (70, 70, 70)
    for name, legs in (("jugador", 0), ("jugador_andar", 1)):
        s = surf(12, 28)
        pygame.draw.rect(s, skin, (2, 0, 8, 8))           # cabeza
        pygame.draw.rect(s, hair, (2, 0, 8, 3))
        pygame.draw.rect(s, hair, (2, 0, 2, 6))
        s.set_at((8, 4), (255, 255, 255))
        s.set_at((9, 4), (40, 40, 120))
        pygame.draw.rect(s, shirt, (3, 8, 6, 10))         # cuerpo
        pygame.draw.rect(s, skin, (5, 9, 3, 9))           # brazo
        pygame.draw.rect(s, shirt, (5, 8, 3, 3))
        if legs:
            pygame.draw.rect(s, pants, (2, 18, 3, 8))
            pygame.draw.rect(s, pants, (7, 18, 3, 8))
            pygame.draw.rect(s, shoe, (1, 26, 4, 2))
            pygame.draw.rect(s, shoe, (7, 26, 4, 2))
        else:
            pygame.draw.rect(s, pants, (3, 18, 6, 8))
            pygame.draw.line(s, (45, 45, 130), (6, 19), (6, 25))
            pygame.draw.rect(s, shoe, (3, 26, 6, 2))
        frames[name] = s
    return frames


def mobs():
    m = {}
    pig = surf(16, 12)
    pygame.draw.rect(pig, (240, 160, 160), (0, 2, 14, 7))
    pygame.draw.rect(pig, (240, 160, 160), (10, 0, 6, 7))
    pygame.draw.rect(pig, (220, 120, 130), (14, 3, 2, 3))
    pig.set_at((12, 2), (0, 0, 0))
    for x in (1, 4, 8, 11):
        pygame.draw.rect(pig, (220, 130, 130), (x, 9, 2, 3))
    m["cerdo"] = pig
    zb = surf(12, 28)
    pygame.draw.rect(zb, (90, 150, 80), (2, 0, 8, 8))
    zb.set_at((8, 3), (0, 0, 0))
    pygame.draw.rect(zb, (40, 170, 170), (3, 8, 6, 10))
    pygame.draw.rect(zb, (90, 150, 80), (4, 9, 8, 3))     # brazos hacia delante
    pygame.draw.rect(zb, (60, 60, 160), (3, 18, 6, 10))
    m["zombi"] = zb
    return m


def cracks():
    out = {}
    rnd = random.Random(30)
    pts = [(rnd.randrange(T), rnd.randrange(T)) for _ in range(40)]
    for st in range(1, 9):
        s = surf()
        for i in range(st * 5):
            x, y = pts[i]
            s.set_at((x, y), (0, 0, 0, 200))
            if i % 2:
                s.set_at(((x + 1) % T, y), (0, 0, 0, 160))
        out["grieta%d" % st] = s
    return out


def hud():
    """Corazones y muslos de comida (8x8), llenos, a medias y vacíos."""
    out = {}
    corazon = ["01100110", "11111111", "11111111", "11111111", "01111110", "00111100", "00011000", "00000000"]
    muslo = ["00000110", "00001111", "00011111", "00111110", "01111100", "11011000", "11000000", "01100000"]
    for nombre, forma, lleno, vacio in (("corazon", corazon, (220, 20, 20), (50, 20, 20)),
                                        ("comida", muslo, (200, 130, 60), (60, 40, 25))):
        for estado in ("", "_medio", "_vacio"):
            s = surf(8, 8)
            for y, fila in enumerate(forma):
                for x, c in enumerate(fila):
                    if c == "1":
                        col = vacio if estado == "_vacio" or (estado == "_medio" and x >= 4) else lleno
                        s.set_at((x, y), col)
            out[nombre + estado] = s
    return out


def main():
    pygame.init()
    OUT.mkdir(parents=True, exist_ok=True)
    allt = {}
    allt.update(textures())
    allt.update(items())
    allt.update(player())
    allt.update(mobs())
    allt.update(cracks())
    allt.update(hud())
    for name, s in allt.items():
        pygame.image.save(s, str(OUT / (name + ".png")))
    print("%d texturas en %s" % (len(allt), OUT))


if __name__ == "__main__":
    main()
