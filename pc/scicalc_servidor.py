#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 scicalc_servidor.py — Servidor multijugador de ESP32 SciCalc
===============================================================================
 Un servidor dedicado al que se conectan las calculadoras (y el simulador)
 para jugar juntas. Se puede ejecutar en cualquier PC o en un servidor de
 internet:

     python scicalc_servidor.py                      (puerto 8267)
     python scicalc_servidor.py 9000                 (otro puerto)
     python scicalc_servidor.py --nombre "Casa de Yerai"

 Los mundos se guardan en la carpeta mundos_servidor/ (junto a este archivo):
 aunque se vayan todos o se cierre el servidor, al volver siguen ahí.
 Las calculadoras de la misma red lo encuentran solas (Multijugador › Buscar).

 Protocolo: un JSON por línea sobre TCP.
   Calculadora -> servidor
     {"t":"hola", "sala":"clonaria", "nombre":"Yerai"}   entrar en una sala
     {"t":"todos", "d":{...}}                            mensaje a los demás de la sala
     {"t":"var", "n":"nombre", "v":valor}                variable compartida (se guarda)
     {"t":"vaciar"}                                      borra las variables (mundo nuevo)
     {"t":"salas"}                                       (sin entrar) lista de salas
   Servidor -> calculadora
     {"t":"salas", "nombre":"...", "salas":[{"sala":..., "jugadores":[...], "mundo":true}]}
     {"t":"bienvenido", "id":3, "jugadores":{"1":"Ana",...}, "vars":{...}, "anfitrion":1}
     {"t":"entra", "id":4, "nombre":"Luis"}  /  {"t":"sale", "id":4}
     {"t":"de", "id":1, "d":{...}}           mensaje de otro jugador
     {"t":"var", "id":1, "n":..., "v":...}   variable cambiada por otro jugador
   Las variables se guardan en la sala: quien entra después las recibe todas
   (así un jugador nuevo ve los bloques que otros ya cambiaron).
 Búsqueda en la red local: UDP al puerto 8268. La calculadora envía
 "SCICALC?" por difusión y cada servidor contesta con {"t":"salas",...,"puerto":N}.
===============================================================================
"""
import json
import os
import socket
import sys
import threading
import time

PUERTO = 8267
PUERTO_BUSCAR = 8268         # UDP: búsqueda de servidores en la red local
MAX_LINEA = 64 * 1024        # bytes por mensaje
MAX_VARS = 60000             # variables por sala (un mundo de Paper Minecraft usa ~25 600)
MAX_JUGADORES = 16           # por sala


class Servidor:
    def __init__(self, host="0.0.0.0", puerto=PUERTO, log=print, nombre="Servidor SciCalc",
                 carpeta=None):
        self.host, self.puerto, self.log = host, puerto, log
        self.nombre = nombre
        self.carpeta = carpeta               # dónde se guardan los mundos (None: no se guardan)
        self.salas = {}                      # nombre -> {"clientes": {id: cli}, "vars": {}}
        self.lock = threading.Lock()
        self.next_id = 1
        self.sock = None
        self.udp = None
        self.cambios = False                 # hay algo sin guardar

    # ---- arranque -----------------------------------------------------------------
    def iniciar(self):
        """Abre el puerto y atiende en segundo plano. Lanza OSError si está ocupado."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self.host, self.puerto))
        s.listen(16)
        self.sock = s
        self._cargar()
        threading.Thread(target=self._aceptar, daemon=True).start()
        try:                                 # búsqueda en la red local (si el puerto está libre)
            u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            u.bind(("", PUERTO_BUSCAR))
            self.udp = u
            threading.Thread(target=self._buscar, daemon=True).start()
        except OSError:
            pass
        if self.carpeta:
            threading.Thread(target=self._autoguardar, daemon=True).start()
        self.log(f"Servidor SciCalc escuchando en el puerto {self.puerto}")

    def parar(self):
        self.guardar()
        for s in (self.sock, self.udp):
            try:
                s.close()
            except Exception:
                pass

    # ---- mundos guardados en disco ---------------------------------------------------
    def _archivo(self, sala):
        seguro = "".join(c if c.isalnum() or c in "-_" else "_" for c in sala)
        return os.path.join(self.carpeta, seguro + ".json")

    def _cargar(self):
        if not self.carpeta or not os.path.isdir(self.carpeta):
            return
        for n in os.listdir(self.carpeta):
            if n.endswith(".json"):
                try:
                    with open(os.path.join(self.carpeta, n), encoding="utf-8") as f:
                        d = json.load(f)
                    self.salas[d["sala"]] = {"clientes": {}, "vars": d["vars"]}
                    self.log(f"Mundo cargado: {d['sala']} ({len(d['vars'])} variables)")
                except (OSError, ValueError, KeyError):
                    pass

    def guardar(self):
        if not self.carpeta or not self.cambios:
            return
        with self.lock:
            copia = {n: dict(s["vars"]) for n, s in self.salas.items() if s["vars"]}
            self.cambios = False
        os.makedirs(self.carpeta, exist_ok=True)
        for n, v in copia.items():
            tmp = self._archivo(n) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"sala": n, "vars": v}, f, separators=(",", ":"))
            os.replace(tmp, self._archivo(n))

    def _autoguardar(self):
        while self.sock:
            time.sleep(30)
            try:
                self.guardar()
            except OSError as e:
                self.log(f"No se pudo guardar: {e}")

    # ---- búsqueda en la red local --------------------------------------------------
    def info(self):
        with self.lock:
            salas = [{"sala": n, "jugadores": [c["nombre"] for c in s["clientes"].values()],
                      "mundo": "mundo" in s["vars"] or "semilla" in s["vars"]}
                     for n, s in self.salas.items()]
        return {"t": "salas", "nombre": self.nombre, "puerto": self.puerto, "salas": salas}

    def _buscar(self):
        while True:
            try:
                data, addr = self.udp.recvfrom(512)
            except OSError:
                return
            if data.startswith(b"SCICALC?"):
                try:
                    self.udp.sendto(json.dumps(self.info()).encode("utf-8")[:8000], addr)
                except OSError:
                    pass

    def _aceptar(self):
        while True:
            try:
                conn, addr = self.sock.accept()
            except OSError:
                return
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            threading.Thread(target=self._cliente, args=(conn, addr), daemon=True).start()

    # ---- un cliente -----------------------------------------------------------------
    def _enviar(self, cli, obj):
        data = (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            with cli["wlock"]:
                cli["conn"].sendall(data)
        except OSError:
            pass

    def _difundir(self, sala, obj, menos=None):
        for cid, cli in list(sala["clientes"].items()):
            if cid != menos:
                self._enviar(cli, obj)

    def _cliente(self, conn, addr):
        cli = {"conn": conn, "wlock": threading.Lock(), "id": None, "sala": None, "nombre": "?"}
        buf = b""
        try:
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
                if len(buf) > MAX_LINEA and b"\n" not in buf:
                    break                                # mensaje demasiado largo
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        msg = json.loads(line.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if isinstance(msg, dict):
                        self._mensaje(cli, msg, addr)
        except OSError:
            pass
        finally:
            self._salir(cli)
            try:
                conn.close()
            except OSError:
                pass

    def _mensaje(self, cli, msg, addr):
        t = msg.get("t")
        if t == "salas":                             # consulta sin entrar en ninguna sala
            self._enviar(cli, self.info())
            return
        with self.lock:
            if t == "hola" and cli["id"] is None:
                nombre_sala = str(msg.get("sala", "general"))[:32]
                sala = self.salas.setdefault(nombre_sala, {"clientes": {}, "vars": {}})
                if len(sala["clientes"]) >= MAX_JUGADORES:
                    self._enviar(cli, {"t": "error", "msg": "sala llena"})
                    return
                cli["id"] = self.next_id
                self.next_id += 1
                cli["sala"] = nombre_sala
                cli["nombre"] = str(msg.get("nombre", "Jugador"))[:16]
                sala["clientes"][cli["id"]] = cli
                jugadores = {str(i): c["nombre"] for i, c in sala["clientes"].items()}
                self._enviar(cli, {"t": "bienvenido", "id": cli["id"], "jugadores": jugadores,
                                   "vars": sala["vars"], "anfitrion": min(sala["clientes"])})
                self._difundir(sala, {"t": "entra", "id": cli["id"], "nombre": cli["nombre"]},
                               menos=cli["id"])
                self.log(f"[{nombre_sala}] entra {cli['nombre']} (id {cli['id']}, {addr[0]})")
                return
            if cli["id"] is None:
                return
            sala = self.salas.get(cli["sala"])
            if sala is None:
                return
            if t == "todos":
                self._difundir(sala, {"t": "de", "id": cli["id"], "d": msg.get("d")}, menos=cli["id"])
            elif t == "vaciar":                      # alguien abre un mundo nuevo en la sala
                sala["vars"] = {}
                self.cambios = True
            elif t == "var":
                n = str(msg.get("n", ""))[:64]
                if n in sala["vars"] or len(sala["vars"]) < MAX_VARS:
                    sala["vars"][n] = msg.get("v")
                    self.cambios = True
                    self._difundir(sala, {"t": "var", "id": cli["id"], "n": n, "v": msg.get("v")},
                                   menos=cli["id"])

    def _salir(self, cli):
        with self.lock:
            sala = self.salas.get(cli["sala"])
            if sala is None or cli["id"] not in sala["clientes"]:
                return
            del sala["clientes"][cli["id"]]
            self.log(f"[{cli['sala']}] sale {cli['nombre']} (id {cli['id']})")
            if sala["clientes"]:
                self._difundir(sala, {"t": "sale", "id": cli["id"],
                                      "anfitrion": min(sala["clientes"])})
            elif not sala["vars"]:
                del self.salas[cli["sala"]]          # sala vacía y sin mundo: se olvida
            # con mundo, la sala se queda: quien entre después sigue jugando en él


def ip_local():
    """IP de este equipo en la red local (la que tienen que poner los demás)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


if __name__ == "__main__":
    args = sys.argv[1:]
    nombre = "Servidor SciCalc"
    if "--nombre" in args:
        i = args.index("--nombre")
        nombre = args[i + 1] if i + 1 < len(args) else nombre
        del args[i:i + 2]
    puerto = int(args[0]) if args else PUERTO
    carpeta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mundos_servidor")
    srv = Servidor(puerto=puerto, nombre=nombre, carpeta=carpeta)
    srv.iniciar()
    print(f"Nombre: {nombre}   ·   mundos guardados en {carpeta}")
    print(f"En la misma red lo encuentran solos (Multijugador › Buscar partidas).")
    print(f"Desde fuera, añadid el servidor:  {ip_local()}  puerto {puerto}")
    print("Ctrl+C para cerrar (se guardan los mundos).")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.parar()
