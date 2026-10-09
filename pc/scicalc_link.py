#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 SciCalc Link — programa del PC para la calculadora ESP32 SciCalc
===============================================================================
 Conecta con la calculadora de 4 formas:
   * USB        → puerto COM del cable (necesita:  pip install pyserial)
   * Bluetooth  → puerto COM que crea Windows al emparejar "SciCalc-XXXX"
   * Wi-Fi      → IP de la calculadora, puerto 8266
                  (el simulador escucha en 127.0.0.1 cuando conectas su Wi-Fi)
   * MicroSD    → la tarjeta metida en el PC (o la carpeta "sd" del simulador)

 Qué hace:
   * Instala paquetes de Python en /lib de la MicroSD:
       - micropython-lib (recomendado: son los que funcionan en el ESP32)
       - PyPI con pip (solo Python puro; se rechazan los que traen código en C)
   * Desinstala paquetes, sube/descarga/borra scripts de /scripts.
   * Envía la contraseña del Wi-Fi a la calculadora (así no la tecleas en ella).
 La calculadora te PREGUNTA en su pantalla antes de cada operación.

 Ejecutar:  python scicalc_link.py
===============================================================================
"""
import base64
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

try:
    import serial                      # pyserial (opcional: USB y Bluetooth)
    import serial.tools.list_ports
except ImportError:
    serial = None

MIP_INDEX = "https://micropython.org/pi/v2"
DEFAULT_PORT = 8266
CHUNK = 3 * 1024                       # bytes por mensaje "put"
NATIVE_EXT = (".pyd", ".so", ".dll", ".dylib")


class LinkError(Exception):
    pass


# =============================================================================
#  Transportes: todos hablan el mismo protocolo (JSON por líneas)
# =============================================================================
class JsonLink:
    name = "?"

    def __init__(self):
        self._id = 0

    def request(self, cmd, timeout=10, **kw):
        self._id += 1
        msg = dict(kw, cmd=cmd, id=self._id)
        self._write((json.dumps(msg) + "\n").encode("utf-8"))
        while True:
            line = self._readline(timeout)
            if not line:
                raise LinkError("la calculadora no responde")
            try:
                rep = json.loads(line.decode("utf-8", "replace"))
            except ValueError:
                continue                     # texto de arranque/depuración: se ignora
            if rep.get("id") not in (None, self._id):
                continue
            if not rep.get("ok"):
                raise LinkError(rep.get("error", "error desconocido"))
            return rep

    # Operaciones de alto nivel ----------------------------------------------
    def hello(self):
        return self.request("hello", timeout=70, client=socket.gethostname()[:24])

    def ls(self, path):
        return self.request("ls", path=path)["entries"]

    def get(self, path):
        return base64.b64decode(self.request("get", timeout=30, path=path)["data"])

    def put(self, path, data, progress=None):
        if not data:
            self.request("put", path=path, data="", append=False)
        for i in range(0, len(data), CHUNK):
            self.request("put", timeout=20, path=path, append=i > 0,
                         data=base64.b64encode(data[i:i + CHUNK]).decode())
            if progress:
                progress(min(len(data), i + CHUNK), len(data))

    def mkdir(self, path):
        self.request("mkdir", path=path)

    def rm(self, path, recursive=False):
        self.request("rm", path=path, recursive=recursive)

    def confirm(self, title, lines):
        return self.request("confirm", timeout=70, title=title, lines=lines).get("accepted", False)

    def done(self):
        try:
            self.request("done")
        except LinkError:
            pass

    def wifi(self, ssid, password):
        return self.request("wifi", timeout=70, ssid=ssid, password=password).get("accepted", False)

    def close(self):
        pass


class TcpLink(JsonLink):
    def __init__(self, host, port=DEFAULT_PORT):
        super().__init__()
        self.name = f"Wi-Fi {host}:{port}"
        try:
            self.sock = socket.create_connection((host, port), timeout=5)
        except OSError as e:
            raise LinkError(f"no se pudo conectar a {host}:{port} ({e}). "
                            "¿Está el Wi-Fi de la calculadora conectado?")
        self.f = self.sock.makefile("rwb")

    def _write(self, b):
        self.f.write(b)
        self.f.flush()

    def _readline(self, timeout):
        self.sock.settimeout(timeout)
        try:
            return self.f.readline()
        except socket.timeout:
            return b""

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class SerialLink(JsonLink):
    """USB o Bluetooth (en Windows ambos son un puerto COM)."""

    def __init__(self, port, kind="USB"):
        super().__init__()
        if serial is None:
            raise LinkError("falta pyserial:  pip install pyserial")
        self.name = f"{kind} {port}"
        self.ser = serial.Serial()
        self.ser.port, self.ser.baudrate, self.ser.timeout = port, 115200, 1
        self.ser.dtr = False            # evita que el ESP32 se reinicie al abrir el puerto
        self.ser.rts = False
        try:
            self.ser.open()
        except Exception as e:
            raise LinkError(f"no se pudo abrir {port}: {e}")

    def _write(self, b):
        self.ser.write(b)

    def _readline(self, timeout):
        self.ser.timeout = timeout
        return self.ser.readline()

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


class FolderLink(JsonLink):
    """MicroSD metida en el PC (o carpeta 'sd' del simulador): sin calculadora."""

    def __init__(self, folder):
        super().__init__()
        self.root = Path(folder).resolve()
        if not self.root.is_dir():
            raise LinkError("la carpeta no existe")
        self.name = f"MicroSD {self.root}"

    def _p(self, path, write=False):
        q = (self.root / str(path).lstrip("/")).resolve()
        if q != self.root and self.root not in q.parents:
            raise LinkError("ruta fuera de la tarjeta")
        if write and q.relative_to(self.root).parts[:1] not in (("lib",), ("scripts",)):
            raise LinkError("solo se escribe en /lib y /scripts")
        return q

    def hello(self):
        return {"ok": True, "device": "MicroSD (directa)", "fw": "-"}

    def ls(self, path):
        q = self._p(path)
        if not q.is_dir():
            return []
        return [{"name": e.name, "dir": e.is_dir(), "size": e.stat().st_size if e.is_file() else 0}
                for e in sorted(q.iterdir())]

    def get(self, path):
        q = self._p(path)
        if not q.is_file():
            raise LinkError("no existe")
        return q.read_bytes()

    def put(self, path, data, progress=None):
        q = self._p(path, True)
        q.parent.mkdir(parents=True, exist_ok=True)
        q.write_bytes(data)
        if progress:
            progress(len(data), len(data))

    def mkdir(self, path):
        self._p(path, True).mkdir(parents=True, exist_ok=True)

    def rm(self, path, recursive=False):
        q = self._p(path, True)
        if q.is_dir():
            shutil.rmtree(q) if recursive else q.rmdir()
        elif q.exists():
            q.unlink()

    def confirm(self, title, lines):
        return True                     # no hay pantalla: confirma el propio PC

    def done(self):
        pass

    def wifi(self, ssid, password):
        raise LinkError("con la MicroSD directa no se puede configurar el Wi-Fi")


# =============================================================================
#  Descarga de paquetes
# =============================================================================
def _http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "SciCalc-Link"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def fetch_mip(name, log, seen=None):
    """Paquete de micropython-lib (índice oficial de 'mip'). Devuelve (version, {ruta: bytes})."""
    seen = set() if seen is None else seen
    if name in seen:
        return None, {}
    seen.add(name)
    log(f"  micropython-lib: buscando '{name}'…")
    try:
        meta = json.loads(_http_get(f"{MIP_INDEX}/package/py/{name}/latest.json"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise LinkError(f"'{name}' no existe en micropython-lib (prueba con PyPI)")
        raise LinkError(f"error descargando {name}: {e}")
    except urllib.error.URLError as e:
        raise LinkError(f"sin conexión a internet: {e.reason}")
    files = {}
    for path, h in meta.get("hashes", []):
        files[path] = _http_get(f"{MIP_INDEX}/file/{h[:2]}/{h}")
    for path, url in meta.get("urls", []):
        if url.startswith("http"):
            files[path] = _http_get(url)
    for dep in meta.get("deps", []):
        dname = dep[0] if isinstance(dep, (list, tuple)) else dep
        if ":" in dname or "/" in dname:
            log(f"  (dependencia externa omitida: {dname})")
            continue
        _, dfiles = fetch_mip(dname, log, seen)
        files.update(dfiles)
    return meta.get("version", "?"), files


def fetch_pypi(name, log):
    """Paquete de PyPI con pip. Solo se aceptan paquetes de Python puro."""
    tmp = Path(tempfile.mkdtemp(prefix="scicalc_"))
    try:
        log(f"  pip: descargando '{name}' (y dependencias)…")
        cmd = [sys.executable, "-m", "pip", "install", "--target", str(tmp), "--no-compile",
               "--disable-pip-version-check", "--no-warn-script-location", name]
        kw = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {}
        r = subprocess.run(cmd, capture_output=True, text=True, **kw)
        if r.returncode != 0:
            last = (r.stderr or r.stdout).strip().splitlines()[-3:]
            raise LinkError("pip falló:\n    " + "\n    ".join(last))
        version = "?"
        native = []
        files = {}
        for p in tmp.rglob("*"):
            rel = p.relative_to(tmp).as_posix()
            top = rel.split("/")[0]
            if top.endswith(".dist-info"):
                if p.name == "METADATA" and top.lower().startswith(name.lower().replace("-", "_")):
                    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                        if line.startswith("Version:"):
                            version = line.split(":", 1)[1].strip()
                continue
            if top in ("bin", "Scripts") or "__pycache__" in rel or not p.is_file():
                continue
            if p.suffix.lower() in NATIVE_EXT:
                native.append(rel)
                continue
            files[rel] = p.read_bytes()
        if native:
            raise LinkError(f"'{name}' trae código nativo en C ({native[0]}…): "
                            "no puede funcionar en el ESP32. Busca una alternativa en micropython-lib.")
        return version, files
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def read_manifest(link):
    try:
        return json.loads(link.get("/lib/paquetes.json").decode("utf-8"))
    except Exception:
        return {}


def install(link, name, source, log, progress):
    fetch = fetch_mip if source == "mip" else fetch_pypi
    version, files = fetch(name, log)
    if not files:
        raise LinkError("el paquete no contiene archivos")
    total = sum(len(b) for b in files.values())
    log(f"  {len(files)} archivos · {total / 1024:.1f} KB")
    if total > 1024 * 1024:
        log("  ⚠ más de 1 MB: puede no caber en la RAM del ESP32 al importarlo")
    src = "micropython-lib" if source == "mip" else "PyPI"
    if not link.confirm("Instalar paquete", [f"{name} {version}", f"{len(files)} archivos, {total // 1024 + 1} KB",
                                             f"origen: {src}", "destino: /lib"]):
        raise LinkError("cancelado en la calculadora")
    try:
        done = 0
        for i, (rel, data) in enumerate(sorted(files.items()), 1):
            log(f"  [{i}/{len(files)}] /lib/{rel}")
            link.put(f"/lib/{rel}", data, lambda a, b, d=done: progress(d + a, total))
            done += len(data)
        m = read_manifest(link)
        m[name] = {"version": version, "source": src, "files": sorted(files)}
        link.put("/lib/paquetes.json", json.dumps(m, indent=1, ensure_ascii=False).encode("utf-8"))
    finally:
        link.done()
    return version


def uninstall(link, name, log):
    m = read_manifest(link)
    info = m.get(name)
    if not info:
        raise LinkError(f"'{name}' no está instalado")
    files = info.get("files", [])
    if not link.confirm("Desinstalar", [f"Paquete: {name}", f"Se borrarán {len(files)} archivos"]):
        raise LinkError("cancelado en la calculadora")
    try:
        for rel in files:
            log(f"  borrando /lib/{rel}")
            link.rm(f"/lib/{rel}")
        tops = {rel.split("/")[0] for rel in files if "/" in rel}
        others = {r.split("/")[0] for n, i in m.items() if n != name for r in i.get("files", [])}
        for top in tops - others:
            link.rm(f"/lib/{top}", recursive=True)
        del m[name]
        link.put("/lib/paquetes.json", json.dumps(m, indent=1, ensure_ascii=False).encode("utf-8"))
    finally:
        link.done()


# =============================================================================
#  Interfaz gráfica
# =============================================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SciCalc Link")
        self.geometry("760x620")
        self.minsize(680, 540)
        self.link = None
        self.q = queue.Queue()
        self.busy = False
        self._build()
        self.after(80, self._pump)
        self.log("SciCalc Link listo. Elige cómo conectar y pulsa Conectar.")
        if serial is None:
            self.log("ℹ USB y Bluetooth necesitan pyserial:  python -m pip install pyserial")

    # ---- construcción --------------------------------------------------------
    def _build(self):
        pad = {"padx": 8, "pady": 4}
        top = ttk.LabelFrame(self, text="Conexión")
        top.pack(fill="x", **pad)

        self.mode = tk.StringVar(value="wifi")
        modes = ttk.Frame(top)
        modes.pack(fill="x", padx=6, pady=4)
        for val, txt in (("usb", "USB"), ("bt", "Bluetooth"), ("wifi", "Wi-Fi"), ("sd", "MicroSD en el PC")):
            ttk.Radiobutton(modes, text=txt, value=val, variable=self.mode,
                            command=self._mode_changed).pack(side="left", padx=8)

        self.opts = ttk.Frame(top)
        self.opts.pack(fill="x", padx=6, pady=4)
        self.port = tk.StringVar()
        self.host = tk.StringVar(value="127.0.0.1")
        self.folder = tk.StringVar(value=str(Path(__file__).resolve().parent / "sd"))

        row = ttk.Frame(top)
        row.pack(fill="x", padx=6, pady=(0, 6))
        self.btn = ttk.Button(row, text="Conectar", command=self.toggle_connect)
        self.btn.pack(side="left")
        self.status = ttk.Label(row, text="● Desconectado", foreground="#b33")
        self.status.pack(side="left", padx=12)
        self.bar = ttk.Progressbar(row, length=180, mode="determinate")
        self.bar.pack(side="right")
        self._mode_changed()

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, **pad)

        # Paquetes
        pk = ttk.Frame(nb)
        nb.add(pk, text="Paquetes Python")
        r1 = ttk.Frame(pk)
        r1.pack(fill="x", padx=6, pady=6)
        ttk.Label(r1, text="Paquete:").pack(side="left")
        self.pkg = tk.StringVar()
        e = ttk.Entry(r1, textvariable=self.pkg, width=24)
        e.pack(side="left", padx=4)
        e.bind("<Return>", lambda _e: self.do_install())
        self.source = tk.StringVar(value="micropython-lib (recomendado)")
        ttk.Combobox(r1, textvariable=self.source, state="readonly", width=30,
                     values=["micropython-lib (recomendado)", "PyPI / pip (solo Python puro)"]).pack(side="left", padx=4)
        ttk.Button(r1, text="Instalar", command=self.do_install).pack(side="left", padx=4)
        ttk.Label(pk, foreground="#666", text="Ej. micropython-lib: datetime, base64, collections-defaultdict · "
                                              "PyPI: más paquetes, pero muchos no funcionan en MicroPython").pack(anchor="w", padx=8)
        self.tree = ttk.Treeview(pk, columns=("ver", "src", "n"), height=8)
        for col, txt, w in (("#0", "Paquete", 200), ("ver", "Versión", 90), ("src", "Origen", 130), ("n", "Archivos", 80)):
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=w)
        self.tree.pack(fill="both", expand=True, padx=6, pady=6)
        r2 = ttk.Frame(pk)
        r2.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(r2, text="Desinstalar", command=self.do_uninstall).pack(side="left")
        ttk.Button(r2, text="Actualizar lista", command=self.refresh_pkgs).pack(side="left", padx=6)

        # Scripts
        sc = ttk.Frame(nb)
        nb.add(sc, text="Scripts")
        self.scripts = tk.Listbox(sc, height=10)
        self.scripts.pack(fill="both", expand=True, padx=6, pady=6)
        r3 = ttk.Frame(sc)
        r3.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(r3, text="Subir .py…", command=self.do_upload).pack(side="left")
        ttk.Button(r3, text="Descargar…", command=self.do_download).pack(side="left", padx=6)
        ttk.Button(r3, text="Borrar", command=self.do_delete).pack(side="left")
        ttk.Button(r3, text="Actualizar", command=self.refresh_scripts).pack(side="left", padx=6)

        # Wi-Fi
        wf = ttk.Frame(nb)
        nb.add(wf, text="Wi-Fi de la calculadora")
        ttk.Label(wf, text="Envía la red Wi-Fi a la calculadora (útil por USB: así no tecleas\n"
                           "la contraseña en ella). La calculadora te pedirá confirmación.").pack(anchor="w", padx=8, pady=8)
        g = ttk.Frame(wf)
        g.pack(anchor="w", padx=8)
        self.ssid, self.pwd = tk.StringVar(), tk.StringVar()
        ttk.Label(g, text="Red (SSID):").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(g, textvariable=self.ssid, width=30).grid(row=0, column=1, pady=3)
        ttk.Label(g, text="Contraseña:").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(g, textvariable=self.pwd, width=30, show="•").grid(row=1, column=1, pady=3)
        ttk.Button(g, text="Enviar a la calculadora", command=self.do_wifi).grid(row=2, column=1, sticky="e", pady=6)

        # Registro
        self.logbox = ScrolledText(self, height=9, state="disabled", font=("Consolas", 9))
        self.logbox.pack(fill="both", padx=8, pady=(0, 8))

    def _mode_changed(self):
        for w in self.opts.winfo_children():
            w.destroy()
        m = self.mode.get()
        if m in ("usb", "bt"):
            ttk.Label(self.opts, text="Puerto:").pack(side="left")
            self.port_box = ttk.Combobox(self.opts, textvariable=self.port, width=48)
            self.port_box.pack(side="left", padx=4)
            ttk.Button(self.opts, text="↻", width=3, command=self._scan_ports).pack(side="left")
            self._scan_ports()
            hint = "cable USB-C · 115200 baudios" if m == "usb" else "empareja antes 'SciCalc-XXXX' en Windows"
            ttk.Label(self.opts, text=hint, foreground="#666").pack(side="left", padx=8)
        elif m == "wifi":
            ttk.Label(self.opts, text="IP de la calculadora:").pack(side="left")
            ttk.Entry(self.opts, textvariable=self.host, width=18).pack(side="left", padx=4)
            ttk.Label(self.opts, text=f"puerto {DEFAULT_PORT}   (simulador: 127.0.0.1)", foreground="#666").pack(side="left")
        else:
            ttk.Label(self.opts, text="Carpeta / unidad:").pack(side="left")
            ttk.Entry(self.opts, textvariable=self.folder, width=46).pack(side="left", padx=4)
            ttk.Button(self.opts, text="Examinar…", command=self._pick_folder).pack(side="left")

    def _scan_ports(self):
        if serial is None:
            self.port_box["values"] = ["(instala pyserial)"]
            return
        ports = list(serial.tools.list_ports.comports())
        bt = self.mode.get() == "bt"

        def is_bt(p):
            d = f"{p.description} {p.hwid}".lower()
            return "bluetooth" in d or "bthenum" in d
        vals = [f"{p.device} — {p.description}" for p in ports if is_bt(p) == bt]
        self.port_box["values"] = vals or ["(no se encontró ningún puerto)"]
        if vals:
            self.port.set(vals[0])

    def _pick_folder(self):
        d = filedialog.askdirectory(title="Elige la MicroSD o la carpeta 'sd' del simulador")
        if d:
            self.folder.set(d)

    # ---- hilos de trabajo -----------------------------------------------------
    def log(self, msg):
        self.q.put(("log", msg))

    def _pump(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.logbox.configure(state="normal")
                    self.logbox.insert("end", val + "\n")
                    self.logbox.see("end")
                    self.logbox.configure(state="disabled")
                elif kind == "progress":
                    self.bar["value"] = val
                elif kind == "call":
                    val()
        except queue.Empty:
            pass
        self.after(80, self._pump)

    def run_bg(self, title, fn, need_link=True):
        if need_link and not self.link:
            messagebox.showinfo("SciCalc Link", "Primero conecta con la calculadora.")
            return
        if self.busy:
            messagebox.showinfo("SciCalc Link", "Espera a que termine la operación actual.")
            return
        self.busy = True
        self.log(f"▶ {title}")

        def worker():
            try:
                fn()
            except LinkError as e:
                self.log(f"✖ {e}")
            except Exception as e:
                self.log(f"✖ {type(e).__name__}: {e}")
            finally:
                self.busy = False
                self.q.put(("progress", 0))
        threading.Thread(target=worker, daemon=True).start()

    def progress(self, a, b):
        self.q.put(("progress", 100 * a / max(1, b)))

    # ---- acciones ----------------------------------------------------------
    def toggle_connect(self):
        if self.link:
            self.link.close()
            self.link = None
            self.status.configure(text="● Desconectado", foreground="#b33")
            self.btn.configure(text="Conectar")
            self.log("Desconectado.")
            return

        def go():
            m = self.mode.get()
            if m in ("usb", "bt"):
                port = self.port.get().split(" ")[0]
                if not port or port.startswith("("):
                    raise LinkError("elige un puerto COM")
                link = SerialLink(port, "USB" if m == "usb" else "Bluetooth")
            elif m == "wifi":
                link = TcpLink(self.host.get().strip())
            else:
                link = FolderLink(self.folder.get())
            if not isinstance(link, FolderLink):
                self.log("  Acepta la conexión en la pantalla de la calculadora (EXE)…")
            try:
                info = link.hello()
            except Exception:
                link.close()
                raise
            self.link = link
            self.log(f"✔ Conectado: {info.get('device')} fw {info.get('fw')} · {link.name}")

            def ui():
                self.status.configure(text=f"● {link.name}", foreground="#1a7f37")
                self.btn.configure(text="Desconectar")
                self.refresh_pkgs()
                self.refresh_scripts()
            self.q.put(("call", ui))
        self.run_bg("Conectando…", go, need_link=False)

    def refresh_pkgs(self):
        if not self.link:
            return

        def go():
            m = read_manifest(self.link)

            def ui():
                self.tree.delete(*self.tree.get_children())
                for n, i in sorted(m.items()):
                    self.tree.insert("", "end", iid=n, text=n,
                                     values=(i.get("version"), i.get("source"), len(i.get("files", []))))
            self.q.put(("call", ui))
            self.log(f"  {len(m)} paquetes en /lib")
        self.run_bg("Leyendo paquetes instalados", go)

    def do_install(self):
        name = self.pkg.get().strip()
        if not name:
            return
        src = "mip" if self.source.get().startswith("micropython") else "pypi"

        def go():
            v = install(self.link, name, src, self.log, self.progress)
            self.log(f"✔ {name} {v} instalado en /lib")
            self.q.put(("call", self.refresh_pkgs_later))
        self.run_bg(f"Instalar {name} desde {'micropython-lib' if src == 'mip' else 'PyPI'}", go)

    def refresh_pkgs_later(self):
        self.after(300, self.refresh_pkgs)

    def do_uninstall(self):
        sel = self.tree.selection()
        if not sel:
            return
        name = sel[0]

        def go():
            uninstall(self.link, name, self.log)
            self.log(f"✔ {name} desinstalado")
            self.q.put(("call", self.refresh_pkgs_later))
        self.run_bg(f"Desinstalar {name}", go)

    def refresh_scripts(self):
        if not self.link:
            return

        def go():
            out = []

            def walk(path, depth=0):
                for e in self.link.ls(path):
                    p = f"{path.rstrip('/')}/{e['name']}"
                    if e["dir"] and depth < 3:
                        walk(p, depth + 1)
                    elif not e["dir"]:
                        out.append((p, e["size"]))
            walk("/scripts")

            def ui():
                self.scripts.delete(0, "end")
                for p, size in out:
                    self.scripts.insert("end", f"{p}    ({size} B)")
            self.q.put(("call", ui))
        self.run_bg("Leyendo /scripts", go)

    def _sel_script(self):
        s = self.scripts.curselection()
        return self.scripts.get(s[0]).split("    (")[0] if s else None

    def do_upload(self):
        paths = filedialog.askopenfilenames(title="Scripts para la calculadora",
                                            filetypes=[("Python", "*.py"), ("Todos", "*.*")])
        if not paths:
            return

        def go():
            names = [Path(p).name for p in paths]
            if not self.link.confirm("Subir scripts", [f"{len(names)} archivo(s) a /scripts:"] + names[:5]):
                raise LinkError("cancelado en la calculadora")
            try:
                for p in paths:
                    self.link.put(f"/scripts/{Path(p).name}", Path(p).read_bytes(), self.progress)
                    self.log(f"  ✔ /scripts/{Path(p).name}")
            finally:
                self.link.done()
            self.q.put(("call", self.refresh_scripts))
        self.run_bg("Subir scripts", go)

    def do_download(self):
        p = self._sel_script()
        if not p:
            return
        dest = filedialog.asksaveasfilename(initialfile=p.split("/")[-1])
        if not dest:
            return

        def go():
            Path(dest).write_bytes(self.link.get(p))
            self.log(f"✔ guardado en {dest}")
        self.run_bg(f"Descargar {p}", go)

    def do_delete(self):
        p = self._sel_script()
        if not p:
            return

        def go():
            if not self.link.confirm("Borrar script", [p]):
                raise LinkError("cancelado en la calculadora")
            try:
                self.link.rm(p)
            finally:
                self.link.done()
            self.log(f"✔ borrado {p}")
            self.q.put(("call", self.refresh_scripts))
        self.run_bg(f"Borrar {p}", go)

    def do_wifi(self):
        ssid = self.ssid.get().strip()
        if not ssid:
            return

        def go():
            ok = self.link.wifi(ssid, self.pwd.get())
            self.log("✔ red guardada en la calculadora" if ok else "✖ rechazado en la calculadora")
        self.run_bg(f"Enviar Wi-Fi '{ssid}'", go)


if __name__ == "__main__":
    App().mainloop()
