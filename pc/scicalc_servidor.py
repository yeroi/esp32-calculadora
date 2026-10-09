#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 scicalc_servidor.py — Servidor multijugador de ESP32 SciCalc
===============================================================================
 Un servidor dedicado al que se conectan las calculadoras (y el simulador)
 para jugar juntas. Se puede ejecutar en cualquier PC o en un servidor de
 internet:

     python scicalc_servidor.py              (puerto 8267)
     python scicalc_servidor.py 9000         (otro puerto)

 Protocolo: un JSON por línea sobre TCP.
   Calculadora -> servidor
     {"t":"hola", "sala":"clonaria", "nombre":"Yerai"}   entrar en una sala
     {"t":"todos", "d":{...}}                            mensaje a los demás de la sala
     {"t":"var", "n":"nombre", "v":valor}                variable compartida (se guarda)
   Servidor -> calculadora
     {"t":"bienvenido", "id":3, "jugadores":{"1":"Ana",...}, "vars":{...}, "anfitrion":1}
     {"t":"entra", "id":4, "nombre":"Luis"}  /  {"t":"sale", "id":4}
     {"t":"de", "id":1, "d":{...}}           mensaje de otro jugador
     {"t":"var", "id":1, "n":..., "v":...}   variable cambiada por otro jugador
   Las variables se guardan en la sala: quien entra después las recibe todas
   (así un jugador nuevo ve los bloques que otros ya cambiaron).
===============================================================================
"""
import json
import socket
import sys
import threading

PUERTO = 8267
MAX_LINEA = 64 * 1024        # bytes por mensaje
MAX_VARS = 20000             # variables por sala
MAX_JUGADORES = 16           # por sala


class Servidor:
    def __init__(self, host="0.0.0.0", puerto=PUERTO, log=print):
        self.host, self.puerto, self.log = host, puerto, log
        self.salas = {}                      # nombre -> {"clientes": {id: cli}, "vars": {}}
        self.lock = threading.Lock()
        self.next_id = 1
        self.sock = None

    # ---- arranque -----------------------------------------------------------------
    def iniciar(self):
        """Abre el puerto y atiende en segundo plano. Lanza OSError si está ocupado."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self.host, self.puerto))
        s.listen(16)
        self.sock = s
        threading.Thread(target=self._aceptar, daemon=True).start()
        self.log(f"Servidor SciCalc escuchando en el puerto {self.puerto}")

    def parar(self):
        try:
            self.sock.close()
        except Exception:
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
            elif t == "var":
                n = str(msg.get("n", ""))[:64]
                if n in sala["vars"] or len(sala["vars"]) < MAX_VARS:
                    sala["vars"][n] = msg.get("v")
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
            else:
                del self.salas[cli["sala"]]          # sala vacía: se olvida


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
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else PUERTO
    srv = Servidor(puerto=puerto)
    srv.iniciar()
    print(f"Los jugadores deben poner como servidor:  {ip_local()}:{puerto}")
    print("Ctrl+C para cerrar.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.parar()
