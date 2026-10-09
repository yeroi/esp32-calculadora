# =============================================================================
#  Clonaria para ESP32 SciCalc
# -----------------------------------------------------------------------------
#  Conversión de Clonaria (Sean Rettig, licencia MIT, ver LICENSE.txt), un
#  plataformas de bloques al estilo Terraria, a MicroPython:
#    * Sin pyglet/OpenGL: se dibuja con scicalc.pantalla.
#    * Sin Box2D: física propia con colisiones contra la cuadrícula.
#    * Sin numpy ni YAML: el mundo son dos bytearray (8 KB cada uno).
#  Se conserva la generación "NORMAL" del original (piedra/tierra, manchas de
#  arena y grava, máscara senoidal, cuevas, hierba) y sus sprites.
#
#  Controles:
#    ◄ ►        andar             ▲          saltar (mantén para más alto)
#    8 2 4 6    mover el cursor    5          cursor delante del jugador
#    DEL        picar bloque       EXE        poner bloque
#    ( )        elegir bloque      + −        zoom
#    ▼          bajar de una plataforma       AC  salir
# =============================================================================
import math
import random
from scicalc import pantalla as P, teclas as K

# ---- Mundo -----------------------------------------------------------------
W, H = 128, 64                      # en bloques (y hacia ARRIBA, como el original)
AIR, STONE, DIRT, GRASS, SAND, GRAVEL, PLATFORM, TORCH, CONE, BGDIRT = range(10)
NAMES = ("", "stone", "dirt", "grass", "sand", "gravel", "platform", "torch", "cone",
         "background_dirt")
SOLID = (STONE, DIRT, GRASS, SAND, GRAVEL, CONE)
OPAQUE = (STONE, DIRT, GRASS, SAND, GRAVEL)        # tapan el fondo por completo
FALLS = (SAND, GRAVEL)                              # bloques con gravedad
HOTBAR = (DIRT, STONE, GRASS, SAND, GRAVEL, PLATFORM, CONE, TORCH)
SKY = 0x78A8F0

fg = bytearray(W * H)               # capa principal
bg = bytearray(W * H)               # capa de fondo (tierra de fondo en cuevas)

# ---- Pantalla --------------------------------------------------------------
HUD_H = 20                          # barra superior con los bloques
VIEW_Y = HUD_H
VIEW_H = P.ALTO - HUD_H

# ---- Jugador (física en bloques/segundo) -------------------------------------
PW, PH = 1.75, 2.875                # caja de colisión (el sprite es 2x3 bloques)
GRAV, MAX_FALL = 50.0, 20.0
WALK_ACC, MAX_RUN, FRICTION = 60.0, 6.0, 40.0
JUMP_V, JUMP_HOLD, JUMP_TIME = 11.0, 32.0, 0.25
DT = 1 / 30
REACH = 4                           # alcance del cursor, en bloques


def idx(x, y):
    return x + y * W


def get(x, y):
    if 0 <= x < W and 0 <= y < H:
        return fg[x + y * W]
    return AIR


# ---- Generación (port de WorldGen) ----------------------------------------------
def progress(text, frac):
    P.rect(60, 120, 200, 8, 0x303440)
    P.rect(60, 120, int(200 * frac), 8, 0x28A8FA)
    P.rect(0, 140, P.ANCHO, 12, 0)
    P.texto(text, 60, 140, 0x878E9E)
    P.mostrar()                     # además mantiene vivo el watchdog


def circle(cx, cy, r):
    r2 = r * r
    for x in range(int(cx - r), int(cx + r) + 1):
        for y in range(int(cy - r), int(cy + r) + 1):
            if (x - cx) ** 2 + (y - cy) ** 2 < r2 and 0 <= x < W and 0 <= y < H:
                yield x, y


def splotches(layer, n, block, rmin, rmax):
    for _ in range(n):
        x, y = random.randint(0, W - 1), random.randint(0, H - 1)
        for px, py in circle(x, y, random.uniform(rmin, rmax)):
            layer[px + py * W] = block


def sine_mask(layer, sines):
    # Suma de senos aleatorios; por encima de esa altura todo es aire
    for x in range(W):
        h = H / 2
        for period, amp, off in sines:
            h += math.sin(x / period) * amp + off
        for y in range(max(0, int(h) + 1), H):
            layer[x + y * W] = AIR


def line(x0, y0, x1, y1):
    # Bresenham (como Util.line del original)
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x1 > x0 else -1), (1 if y1 > y0 else -1)
    err = dx + dy
    while True:
        yield x0, y0
        if x0 == x1 and y0 == y1:
            return
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def cave():
    # Línea aleatoria que se va ensanchando. Con una máscara y una lista de
    # índices en vez de conjuntos de tuplas: cabe en el heap de MicroPython.
    # El original usa triangular(3, 10, 3) expansiones en un mundo 8 veces más
    # grande; aquí, triangular(1, 4, 1) para que las cuevas no se coman el mapa.
    expansions = int(4 - 3 * math.sqrt(1 - random.random()))
    chance = random.uniform(0.5, 0.8)
    mark = bytearray(W * H)
    cells = []
    x0, y0 = random.randint(0, W - 1), random.randint(0, H // 2)
    for x, y in line(x0, y0, max(0, min(W - 1, x0 + random.randint(-30, 30))),
                     random.randint(0, H // 2)):
        if not mark[x + y * W]:
            mark[x + y * W] = 1
            cells.append(x + y * W)
    for _ in range(expansions):
        new = []
        for i in cells:
            x, y = i % W, i // W
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < W and 0 <= ny < H and not mark[nx + ny * W] and random.random() < chance:
                    mark[nx + ny * W] = 1
                    new.append(nx + ny * W)
        cells += new
        if len(cells) > 700:        # tope de tamaño (y de memoria)
            break
    for i in cells:
        fg[i] = AIR


def grow_grass(min_y):
    for x in range(W):
        for y in range(min_y, H):
            if fg[x + y * W] == DIRT:
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < W and 0 <= ny < H and fg[nx + ny * W] == AIR:
                        fg[x + y * W] = GRASS
                        break


def generate(seed):
    random.seed(seed)
    sines = [(random.randint(4, 20), random.randint(1, 3), random.randint(-1, 1)) for _ in range(6)]
    progress("Piedra y tierra...", 0.05)
    stone_top = int(H * 0.40)
    for i in range(W * H):
        bg[i] = BGDIRT
        fg[i] = STONE if i // W < stone_top else DIRT
    progress("Arena y grava...", 0.2)
    # Cantidades del original escaladas al tamaño del mundo (256x256 -> 128x64)
    splotches(fg, 38, SAND, 3, 10)
    splotches(fg, 38, GRAVEL, 3, 6)
    progress("Vetas...", 0.4)
    splotches(fg, 250, STONE, 0, 3)
    splotches(fg, 250, DIRT, 0, 3)
    progress("Superficie...", 0.55)
    sine_mask(bg, sines)
    sine_mask(fg, sines)
    progress("Cuevas...", 0.7)
    for _ in range(4):
        cave()
    progress("Hierba...", 0.9)
    grow_grass(stone_top)
    progress("Listo", 1.0)


# ---- Juego ---------------------------------------------------------------------
class Game:
    def __init__(self):
        self.spr = {b: P.sprite("img/%s.png" % NAMES[b]) for b in range(1, 10)}
        self.spr_player = P.sprite("img/player.png")
        self.spr_jump = P.sprite("img/player_jump.png")
        self.zoom = 2
        self.sel = 0
        # Aparece en el centro, encima del suelo
        x = W // 2
        y = H - 1
        while y > 0 and get(x, y) not in SOLID and get(x + 1, y) not in SOLID:
            y -= 1
        self.x, self.y = float(x), float(y + 1)
        self.vx = self.vy = 0.0
        self.ground = False
        self.facing = 1
        self.jump_t = 0.0
        self.walk_t, self.walk_dir = 0.0, 0
        self.drop_t = 0.0
        self.cdx, self.cdy = 2, -1               # cursor relativo al jugador
        self.drawn = None                        # lo último dibujado (para borrar)
        self.dirty = []                          # bloques cambiados
        self.set_zoom(2)

    # ---- vista -----------------------------------------------------------------
    def set_zoom(self, z):
        self.zoom = z
        self.t = 8 * z
        self.vw = (P.ANCHO + self.t - 1) // self.t
        self.vh = (VIEW_H + self.t - 1) // self.t
        self.center_camera()

    def center_camera(self):
        self.cam_x = int(self.x + PW / 2) - self.vw // 2
        self.cam_top = int(self.y + PH / 2) + self.vh // 2
        self.full = True

    def to_screen(self, wx, wy):
        # (x, y) del mundo (y hacia arriba) -> píxel de pantalla
        return int((wx - self.cam_x) * self.t), int(VIEW_Y + (self.cam_top + 1 - wy) * self.t)

    def draw_tile(self, tx, ty):
        sx, sy = self.to_screen(tx, ty + 1)
        if sy >= P.ALTO or sx >= P.ANCHO or sx + self.t <= 0 or sy + self.t <= VIEW_Y:
            return
        b = get(tx, ty)
        if b not in OPAQUE:
            back = bg[tx + ty * W] if 0 <= tx < W and 0 <= ty < H else AIR
            if back:
                P.dibujar(self.spr[back], sx, sy, self.zoom)
            else:
                P.rect(sx, sy, self.t, self.t, SKY)
        if b:
            P.dibujar(self.spr[b], sx, sy, self.zoom)

    def draw_area(self, x0, y0, x1, y1):
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                self.draw_tile(tx, ty)

    def draw_hud(self):
        P.rect(0, 0, P.ANCHO, HUD_H, 0x1E222C)
        for i, b in enumerate(HOTBAR):
            x = 4 + i * 20
            P.dibujar(self.spr[b], x, 2, 2)
            if i == self.sel:
                P.marco(x - 2, 0, 20, 20, 0xFFC828)
        P.texto("zoom x%d" % self.zoom, 268, 6, 0x878E9E)

    def target(self):
        return int(self.x + PW / 2) + self.cdx, int(self.y) + 1 + self.cdy

    def render(self):
        t = self.t
        # ¿hay que mover la cámara? (el jugador sale de la zona central)
        sx, sy = self.to_screen(self.x, self.y + PH)
        if sx < P.ANCHO * 0.25 or sx + PW * t > P.ANCHO * 0.75 or \
                sy < VIEW_Y + VIEW_H * 0.2 or sy + PH * t > VIEW_Y + VIEW_H * 0.8:
            self.center_camera()
        if self.full:
            self.full = False
            self.dirty = []
            self.drawn = None
            self.draw_area(self.cam_x, self.cam_top - self.vh, self.cam_x + self.vw, self.cam_top)
            self.draw_hud()
        tx, ty = self.target()
        state = (self.x, self.y, self.facing, self.ground, tx, ty)
        if state == self.drawn and not self.dirty:
            return
        # 1) restaurar lo que tapaban el jugador y el cursor, y los bloques cambiados
        if self.drawn:
            ox, oy, _, _, otx, oty = self.drawn
            self.draw_area(int(ox) - 1, int(oy), int(ox + PW) + 1, int(oy + PH) + 1)
            self.draw_tile(otx, oty)
        for bx, by in self.dirty:
            self.draw_tile(bx, by)
        self.dirty = []
        # 2) jugador (sprite 16x24 = 2x3 bloques, centrado en la caja)
        px, py = self.to_screen(self.x - (2 - PW) / 2, self.y + 3)
        P.dibujar(self.spr_player if self.ground else self.spr_jump, px, py, self.zoom,
                  self.facing < 0)
        # 3) cursor
        cx, cy = self.to_screen(tx, ty + 1)
        P.marco(cx, cy, t, t, 0xFF5050)
        self.drawn = state

    # ---- bloques ---------------------------------------------------------------
    def settle(self, x, y):
        # arena y grava caen si no tienen nada debajo
        while y < H and get(x, y) in FALLS:
            yy = y
            while yy > 0 and get(x, yy - 1) == AIR:
                fg[idx(x, yy - 1)], fg[idx(x, yy)] = fg[idx(x, yy)], AIR
                self.dirty += [(x, yy), (x, yy - 1)]
                yy -= 1
            y += 1

    def overlaps_player(self, tx, ty):
        return (tx + 1 > self.x and tx < self.x + PW and ty + 1 > self.y and ty < self.y + PH)

    def dig(self):
        tx, ty = self.target()
        if 0 <= tx < W and 0 < ty < H and get(tx, ty):
            fg[idx(tx, ty)] = AIR
            self.dirty.append((tx, ty))
            self.settle(tx, ty + 1)

    def place(self):
        tx, ty = self.target()
        b = HOTBAR[self.sel]
        if 0 <= tx < W and 0 <= ty < H and get(tx, ty) == AIR and \
                not (b in SOLID and self.overlaps_player(tx, ty)):
            fg[idx(tx, ty)] = b
            self.dirty.append((tx, ty))
            self.settle(tx, ty)

    # ---- física ------------------------------------------------------------------
    def solid(self, tx, ty):
        if tx < 0 or tx >= W or ty < 0:
            return True                       # bordes del mundo
        return get(tx, ty) in SOLID

    def free_column(self, tx, y0, y1):
        for ty in range(y0, y1 + 1):
            if self.solid(tx, ty):
                return False
        return True

    def move_x(self, dx):
        self.x += dx
        if dx > 0:
            tx = int(self.x + PW - 1e-6)
        elif dx < 0:
            tx = math.floor(self.x)
        else:
            return
        y0, y1 = int(self.y), int(self.y + PH - 1e-6)
        if self.free_column(tx, y0, y1):
            return
        # Subir escalones de 1 bloque andando (como Terraria)
        if self.ground and self.free_column(tx, y0 + 1, y1 + 1) and \
                self.free_column(int(self.x), y1 + 1, y1 + 1) and \
                self.free_column(int(self.x + PW - 1e-6), y1 + 1, y1 + 1):
            self.y = y0 + 1.0
            return
        self.x = (tx - PW) if dx > 0 else (tx + 1.0)
        self.vx = 0.0

    def move_y(self, dy):
        old = self.y
        self.y += dy
        x0, x1 = int(self.x), int(self.x + PW - 1e-6)
        if dy < 0:
            ty = math.floor(self.y)
            for tx in range(x0, x1 + 1):
                b = get(tx, ty)
                hit = self.solid(tx, ty) or (b == PLATFORM and old >= ty + 1 - 1e-6
                                             and self.drop_t <= 0)
                if hit:
                    self.y, self.vy, self.ground = ty + 1.0, 0.0, True
                    return
        elif dy > 0:
            ty = int(self.y + PH - 1e-6)
            for tx in range(x0, x1 + 1):
                if self.solid(tx, ty):
                    self.y, self.vy = ty - PH, 0.0
                    self.jump_t = 0
                    return
        self.ground = False

    def physics(self, left, right, jump_held, jump_pressed):
        want = (1 if right else 0) - (1 if left else 0)
        if want:
            self.facing = want
            self.vx += want * WALK_ACC * DT * (1 if self.ground else 0.6)
            self.vx = max(-MAX_RUN, min(MAX_RUN, self.vx))
        elif self.ground:                     # rozamiento del suelo
            slow = FRICTION * DT
            self.vx = 0.0 if abs(self.vx) <= slow else self.vx - slow * (1 if self.vx > 0 else -1)
        if jump_pressed and self.ground:
            self.vy, self.jump_t = JUMP_V, JUMP_TIME
        elif jump_held and self.jump_t > 0 and self.vy > 0:
            self.vy += JUMP_HOLD * DT             # mantener ▲ salta más (como el original)
        self.jump_t -= DT
        self.vy = max(-MAX_FALL, self.vy - GRAV * DT)
        self.move_x(self.vx * DT)
        self.move_y(self.vy * DT)

    # ---- bucle ---------------------------------------------------------------------
    def step(self):
        jump_pressed = False
        for key, shift in K.eventos():
            if key in ("LEFT", "RIGHT"):
                self.walk_dir = -1 if key == "LEFT" else 1
                self.walk_t = 0.2                 # un toque suelto también anda
            elif key == "UP":
                jump_pressed = True
            elif key == "DOWN":
                self.drop_t = 0.25
            elif key in ("8", "2", "4", "6"):
                dx = {"4": -1, "6": 1}.get(key, 0)
                dy = {"8": 1, "2": -1}.get(key, 0)
                self.cdx = max(-REACH, min(REACH, self.cdx + dx))
                self.cdy = max(-REACH, min(REACH, self.cdy + dy))
            elif key == "5":
                self.cdx, self.cdy = 2 * self.facing, -1
            elif key == "DEL":
                self.dig()
            elif key == "EXE":
                self.place()
            elif key in ("LP", "RP"):
                self.sel = (self.sel + (1 if key == "RP" else -1)) % len(HOTBAR)
                self.draw_hud()
            elif key in ("ADD", "SUB"):
                self.set_zoom(2 if key == "ADD" else 1)
        held = K.pulsadas()
        self.walk_t -= DT
        self.drop_t -= DT
        tap = self.walk_t > 0
        left = "LEFT" in held or (tap and self.walk_dir < 0)
        right = "RIGHT" in held or (tap and self.walk_dir > 0)
        self.physics(left, right, "UP" in held, jump_pressed)
        self.render()
        P.mostrar()


def main():
    P.limpiar(0)
    P.texto("CLONARIA", 112, 80, 0xFFFFFF, None, 2)
    generate(K.ms())
    game = Game()
    while True:                               # AC (sistema) cierra el juego
        game.step()


main()
