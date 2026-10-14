# -*- coding: utf-8 -*-
"""
===============================================================================
 scicalc_media.py — Reproductor de vídeo y audio (simulador y modo PC)
===============================================================================
 Decodifica con ffmpeg, así que vale casi cualquier formato:
   vídeo: mp4, mkv, webm, avi, mov, 3gp...   audio: mp3, wav, ogg, m4a, aac, flac, opus...
 ffmpeg viene con el paquete de pip "imageio-ffmpeg" (está en requirements.txt);
 si no, se usa el ffmpeg del PATH.

 Cómo funciona (sin cargar el archivo entero en memoria):
   * audio: ffmpeg -> PCM 44.1 kHz estéreo por una tubería -> trozos de 0,25 s
     encolados en un canal de pygame.mixer (uno sonando y otro en cola).
   * vídeo: otro ffmpeg -> fotogramas RGB del tamaño de la pantalla, a 20 fps,
     por una tubería; un hilo los va dejando en una cola corta.
   * El reloj es el del audio: se enseña el fotograma que toca y se saltan los
     que llegan tarde. Avanzar/retroceder = volver a lanzar ffmpeg con -ss.

 Teclas (las aplica quien lo usa, con tecla()):
   ▲ (o EXE) pausa/sigue · ▼ velocidad x2 (otra vez: normal)
   ▼ mantenida + ► : el doble de rápido hacia delante (x2, x4, x8, x16)
   ▼ mantenida + ◄ : rebobinar, cada vez el doble (x2, x4, x8, x16)
   ◄ ► solas: -10 s / +10 s (SHIFT: 1 min) · + − volumen · AC/DEL salir
===============================================================================
"""
import os
import queue
import re
import shutil
import subprocess
import threading
import time

import pygame

EXTS_VIDEO = (".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".3gp", ".mpg", ".mpeg", ".wmv", ".flv")
EXTS_AUDIO = (".mp3", ".wav", ".ogg", ".oga", ".m4a", ".aac", ".flac", ".opus", ".wma", ".aiff", ".mid")
EXTS = EXTS_VIDEO + EXTS_AUDIO

RATE, CH = 44100, 2
CHUNK_S = 0.25
FPS = 20
_NOWIN = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {}


def es_medio(nombre):
    return str(nombre).lower().endswith(EXTS)


def ffmpeg_exe():
    try:
        import imageio_ffmpeg            # pip install imageio-ffmpeg (trae su propio ffmpeg)
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def fmt_t(s):
    s = max(0, int(s))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


class MediaPlayer:
    def __init__(self, path, size):
        self.path, self.size = str(path), size          # size = (ancho, alto) del vídeo
        self.name = os.path.basename(self.path)
        self.error = None
        self.dur, self.has_video, self.has_audio, self.meta = 0.0, False, False, {}
        self.vol = 0.8
        self.speed = 1                                  # >1 rápido, <0 rebobinando
        self.rew_t = 0.0                                # último fotograma al rebobinar
        self.rew_busy = False
        self.paused = False
        self.pos0, self.t0, self.paused_at = 0.0, 0.0, 0.0
        self.frame = None                               # último fotograma (Surface)
        self.frame_t = -1.0
        self.procs, self.threads = [], []
        self.gen = 0                                    # cambia con cada búsqueda (-ss)
        self.vq = queue.Queue(maxsize=8)
        self.aq = queue.Queue(maxsize=8)
        self.chan = None
        self.ended = False
        self.exe = ffmpeg_exe()
        if not self.exe:
            self.error = "Falta ffmpeg: pip install imageio-ffmpeg"
            return
        self._probe()
        if self.error:
            return
        self.rate, self.ch = RATE, CH
        if self.has_audio:
            try:
                # Se usa el mezclador tal como esté (el modo PC ya lo tiene abierto
                # para los pitidos): ffmpeg saca el audio en su mismo formato.
                ini = pygame.mixer.get_init()
                if not ini or ini[1] != -16:
                    if ini:
                        pygame.mixer.quit()
                    pygame.mixer.init(RATE, -16, CH, 1024)
                    ini = pygame.mixer.get_init()
                self.rate, self.ch = ini[0], ini[2]
                self.chan = pygame.mixer.Channel(pygame.mixer.get_num_channels() - 1)   # el último: libre
                self.chan.set_volume(self.vol)
            except pygame.error as e:
                self.has_audio = False
                self.meta["aviso"] = f"sin sonido ({e})"
        self._start(0.0)

    # ---- información del archivo ------------------------------------------------------
    def _probe(self):
        try:
            r = subprocess.run([self.exe, "-hide_banner", "-i", self.path], capture_output=True,
                               text=True, errors="replace", timeout=15, **_NOWIN)
        except (OSError, subprocess.TimeoutExpired) as e:
            self.error = f"ffmpeg no arranca: {e}"
            return
        info = r.stderr
        m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", info)
        if m:
            self.dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        self.has_video = bool(re.search(r"Stream #.*Video:", info)) and not re.search(
            r"Stream #.*Video:.*(attached pic|png|mjpeg.*\(attached)", info)
        self.has_audio = bool(re.search(r"Stream #.*Audio:", info))
        for k in ("title", "artist", "album"):
            mm = re.search(rf"^\s+{k}\s*:\s*(.+)$", info, re.M | re.I)
            if mm:
                self.meta[k] = mm.group(1).strip()
        if not (self.has_video or self.has_audio):
            self.error = "No es un vídeo ni un audio que ffmpeg entienda"

    # ---- arrancar / parar los ffmpeg ---------------------------------------------------
    def _start(self, pos):
        self._stop_procs()
        self.gen += 1
        gen = self.gen
        self.pos0 = max(0.0, min(pos, max(0.0, self.dur - 0.5))) if self.dur else max(0.0, pos)
        self.vq = queue.Queue(maxsize=8)
        self.aq = queue.Queue(maxsize=8)
        self.ended = False
        if self.chan:
            self.chan.stop()
        self.t0 = time.monotonic()
        if self.speed < 0:                              # rebobinando: lo hace update()
            self.rew_t = 0.0
            if self.paused:
                self.paused_at = self.t0
            return
        sp = self.speed
        if self.has_audio:
            af = ["-af", f"atempo={sp}"] if sp != 1 else []      # más rápido sin voz de pito
            p = subprocess.Popen([self.exe, "-v", "error", "-ss", f"{self.pos0:.2f}", "-i", self.path,
                                  "-vn", *af, "-f", "s16le", "-ac", str(self.ch), "-ar", str(self.rate), "-"],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **_NOWIN)
            self.procs.append(p)
            t = threading.Thread(target=self._audio_reader, args=(p, gen, self.aq), daemon=True)
            t.start()
        if self.has_video:
            w, h = self.size
            vf = (f"setpts=PTS/{sp}," if sp != 1 else "") + \
                f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={FPS}"
            p = subprocess.Popen([self.exe, "-v", "error", "-ss", f"{self.pos0:.2f}", "-i", self.path,
                                  "-an", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **_NOWIN)
            self.procs.append(p)
            t = threading.Thread(target=self._video_reader, args=(p, gen, self.vq), daemon=True)
            t.start()
        self.t0 = time.monotonic()
        self.frame_t = -1.0
        if self.paused:
            self.paused_at = self.t0

    def _stop_procs(self):
        for p in self.procs:
            try:
                p.kill()
            except OSError:
                pass
        self.procs = []

    def _audio_reader(self, p, gen, q):
        n = int(self.rate * CHUNK_S) * self.ch * 2
        while gen == self.gen:
            data = p.stdout.read(n)
            if not data:
                q.put(None)
                return
            q.put(data)

    def _video_reader(self, p, gen, q):
        w, h = self.size
        n = w * h * 3
        i = 0
        while gen == self.gen:
            data = p.stdout.read(n)
            if len(data) < n:
                q.put(None)
                return
            q.put((self.pos0 + i / FPS * self.speed, data))   # tiempo del archivo
            i += 1

    # ---- reloj -------------------------------------------------------------------------
    def now(self):
        t = (self.paused_at if self.paused else time.monotonic()) - self.t0
        t = self.pos0 + max(0.0, t) * self.speed
        t = max(0.0, t)
        return min(t, self.dur) if self.dur else t

    def update(self):
        """Llamar en cada fotograma. Devuelve True si hay un fotograma nuevo."""
        if self.error or self.paused:
            return False
        if self.speed < 0:                              # rebobinando: un fotograma cada poco
            if self.now() <= 0.0:
                self.set_speed(1)
                return False
            if self.has_video and not self.rew_busy and time.monotonic() - self.rew_t > 0.15:
                self.rew_t = time.monotonic()
                self.rew_busy = True
                threading.Thread(target=self._grab, args=(self.now(), self.gen), daemon=True).start()
            return False
        # audio: que siempre haya uno sonando y otro en cola
        if self.chan:
            while self.chan.get_queue() is None:
                try:
                    data = self.aq.get_nowait()
                except queue.Empty:
                    break
                if data is None:
                    if not self.has_video:
                        self.ended = not self.chan.get_busy()
                    self.aq.put(None)
                    break
                snd = pygame.mixer.Sound(buffer=data)
                if self.chan.get_busy():
                    self.chan.queue(snd)
                else:
                    self.chan.play(snd)
        elif not self.has_video and self.dur and self.now() >= self.dur:
            self.ended = True
        # vídeo: el fotograma que toca según el reloj
        nuevo = False
        if self.has_video:
            t = self.now()
            while True:
                try:
                    item = self.vq.queue[0]
                except IndexError:
                    break
                if item is None:
                    self.ended = True
                    break
                ft, data = item
                if ft > t:
                    break
                self.vq.get_nowait()
                if t - ft < 1.0 / FPS or self.vq.empty():   # los que llegan tarde se saltan
                    self.frame = pygame.image.frombuffer(data, self.size, "RGB")
                    self.frame_t = ft
                    nuevo = True
        return nuevo

    def _grab(self, pos, gen):
        """Un solo fotograma en 'pos' (para rebobinar)."""
        try:
            w, h = self.size
            vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
            r = subprocess.run([self.exe, "-v", "error", "-ss", f"{pos:.2f}", "-i", self.path, "-an",
                                "-frames:v", "1", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                               capture_output=True, timeout=5, **_NOWIN)
            if gen == self.gen and len(r.stdout) >= w * h * 3:
                self.frame = pygame.image.frombuffer(r.stdout[:w * h * 3], self.size, "RGB")
                self.frame_t = pos
        except (OSError, subprocess.TimeoutExpired):
            pass
        self.rew_busy = False

    def set_speed(self, s):
        pos = self.now()
        self.speed = s
        self._start(pos)

    # ---- mandos ------------------------------------------------------------------------
    def toggle(self):
        if self.paused:
            self.t0 += time.monotonic() - self.paused_at
            self.paused = False
            if self.chan:
                self.chan.unpause()
        else:
            self.paused_at = time.monotonic()
            self.paused = True
            if self.chan:
                self.chan.pause()

    def seek(self, delta):
        self._start(self.now() + delta)
        if self.paused:
            self.paused_at = self.t0

    def volume(self, d):
        self.vol = max(0.0, min(1.0, self.vol + d))
        if self.chan:
            self.chan.set_volume(self.vol)

    def tecla(self, k, shift=False, held=()):
        """Devuelve True si hay que salir. 'held' = teclas mantenidas (para ▼ + ◄/►)."""
        if k in ("AC", "DEL", "MENU"):
            return True
        if k in ("UP", "EXE"):
            if self.ended:                               # al acabar: otra vez desde el principio
                self.paused = False
                self.speed = 1
                self._start(0.0)
            else:
                self.toggle()
        elif k == "DOWN":
            self.set_speed(2 if self.speed == 1 else 1)  # x2 / normal
        elif k == "RIGHT" and "DOWN" in held:            # ▼ + ►: el doble hacia delante
            self.set_speed(2 if self.speed <= 1 else min(16, self.speed * 2))
        elif k == "LEFT" and "DOWN" in held:             # ▼ + ◄: rebobinar, el doble cada vez
            self.set_speed(-2 if self.speed >= 1 else max(-16, self.speed * 2))
        elif k in ("LEFT", "RIGHT"):
            self.seek((60 if shift else 10) * (1 if k == "RIGHT" else -1))
        elif k in ("ADD", "SUB"):
            self.volume(0.1 if k == "ADD" else -0.1)
        return False

    def close(self):
        self.gen += 1
        self._stop_procs()
        if self.chan:
            self.chan.stop()

    # ---- dibujo (lo usan el simulador y el modo PC) ----------------------------------------
    def draw(self, surf, font_fn):
        """Dibuja el reproductor en 'surf' (del tamaño de la pantalla del juego).
        font_fn(tamaño, negrita) -> pygame.font.Font"""
        W, H = surf.get_size()
        surf.fill((0, 0, 0))
        k = H / 218                                      # 1 en modo PC, 2 en el simulador
        if self.error:
            f = font_fn(int(9 * k), True)
            surf.blit(f.render("No se puede reproducir", True, (255, 90, 90)), (int(10 * k), int(20 * k)))
            f2 = font_fn(int(8 * k), False)
            y = int(40 * k)
            for ln in _wrap(self.error, 44):
                surf.blit(f2.render(ln, True, (220, 220, 220)), (int(10 * k), y))
                y += int(12 * k)
            surf.blit(f2.render("AC volver", True, (135, 142, 158)), (int(10 * k), H - int(16 * k)))
            return
        if self.has_video and self.frame is not None:
            fw, fh = self.size
            img = self.frame if (fw, fh) == (W, H) else pygame.transform.smoothscale(self.frame, (W, H))
            surf.blit(img, (0, 0))
        elif not self.has_video:
            # Solo audio: carátula de nota musical + título + barras que se mueven
            cx = W // 2
            pygame.draw.circle(surf, (40, 168, 250), (cx, int(70 * k)), int(38 * k))
            pygame.draw.rect(surf, (255, 255, 255), (cx + int(4 * k), int(44 * k), int(5 * k), int(38 * k)))
            pygame.draw.ellipse(surf, (255, 255, 255), (cx - int(12 * k), int(74 * k), int(18 * k), int(13 * k)))
            pygame.draw.polygon(surf, (255, 255, 255), [(cx + int(9 * k), int(44 * k)),
                                                       (cx + int(22 * k), int(52 * k)),
                                                       (cx + int(9 * k), int(56 * k))])
            title = self.meta.get("title") or os.path.splitext(self.name)[0]
            f = font_fn(int(10 * k), True)
            t = f.render(title[:34], True, (238, 241, 245))
            surf.blit(t, (cx - t.get_width() // 2, int(118 * k)))
            if self.meta.get("artist"):
                f2 = font_fn(int(8 * k), False)
                a = f2.render(self.meta["artist"][:40], True, (135, 142, 158))
                surf.blit(a, (cx - a.get_width() // 2, int(134 * k)))
            if not self.paused:
                ph = time.monotonic() * 6
                for i in range(12):
                    import math
                    hgt = int((6 + 14 * abs(math.sin(ph + i * 0.7))) * k)
                    surf.fill((70, 205, 120), (cx - int(48 * k) + i * int(8 * k), int(170 * k) - hgt,
                                               int(5 * k), hgt))
        else:
            f = font_fn(int(9 * k), False)
            t = f.render("Cargando...", True, (135, 142, 158))
            surf.blit(t, (W // 2 - t.get_width() // 2, H // 2))
        # barra inferior: estado, tiempo, progreso y volumen
        bar_h = int(24 * k)
        ov = pygame.Surface((W, bar_h), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 170))
        surf.blit(ov, (0, H - bar_h))
        y = H - bar_h
        f = font_fn(int(8 * k), True)
        icon = ">" if self.paused else ("<<" if self.speed < 0 else (">>" if self.speed > 1 else "II"))
        surf.blit(f.render(icon, True, (255, 255, 255)), (int(5 * k), y + int(8 * k)))
        now = self.now()
        tt = f.render(f"{fmt_t(now)} / {fmt_t(self.dur)}", True, (238, 241, 245))
        surf.blit(tt, (int(20 * k), y + int(8 * k)))
        x0 = int(20 * k) + tt.get_width() + int(8 * k)
        x1 = W - int(48 * k)
        surf.fill((90, 96, 110), (x0, y + int(11 * k), x1 - x0, max(2, int(3 * k))))
        if self.dur:
            fx = x0 + int((x1 - x0) * min(1.0, now / self.dur))
            surf.fill((40, 168, 250), (x0, y + int(11 * k), fx - x0, max(2, int(3 * k))))
            pygame.draw.circle(surf, (255, 255, 255), (fx, y + int(12 * k)), max(2, int(3 * k)))
        if self.speed != 1:                              # velocidad, arriba a la derecha
            txt = ("◄◄ x" if self.speed < 0 else "►► x") + str(abs(self.speed))
            b = font_fn(int(10 * k), True).render(txt, True, (255, 255, 255))
            box = pygame.Rect(W - b.get_width() - int(14 * k), int(6 * k), b.get_width() + int(8 * k),
                              b.get_height() + int(2 * k))
            pygame.draw.rect(surf, (40, 168, 250), box, border_radius=int(4 * k))
            surf.blit(b, (box.x + int(4 * k), box.y + int(1 * k)))
        v = f.render(f"{int(self.vol * 100)}%", True, (135, 142, 158))
        surf.blit(v, (W - v.get_width() - int(5 * k), y + int(8 * k)))
        if self.ended:
            e = font_fn(int(9 * k), True).render("Fin · ▲ repetir · AC salir", True, (255, 200, 40))
            surf.blit(e, (W // 2 - e.get_width() // 2, int(6 * k)))


def _wrap(s, n):
    out, line = [], ""
    for w in str(s).split():
        if len(line) + len(w) + 1 > n:
            out.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        out.append(line)
    return out
