#!/usr/bin/env python3
# =============================================================================
#  parches_scratch.py  —  Cambios al código de un juego Scratch ya convertido
# -----------------------------------------------------------------------------
#  Los perfiles (pc/perfiles/*.json) traen una lista "parches". Hay dos tipos:
#
#   · Datos de una lista:  {"lista", "indice" (desde 1), "era", "valor", "motivo"}
#     Solo se aplica si el valor actual es "era".
#
#   · Código: parar un guion si una variable vale > 0
#       {"objeto": "Mob", "guion": ["event_whenbroadcastreceived", "animate"],
#        "parar_si": "_RedInvitado", "motivo": "..."}
#     Mete al principio del guion   si (_RedInvitado > 0) entonces parar este guion
#     La variable se crea en el escenario (vale 0) si no existe. Es lo que usa el
#     multijugador: el que se une pone _RedInvitado = 1 y su juego deja de simular
#     lo que ya simula el anfitrión (los mobs).
#
#  Se aplica al convertir (sb3_a_scicalc.py) y también a un juego ya convertido:
#     python pc/parches_scratch.py simulador/sd/scratch/paper_minecraft_v11_7_mi
#  (vuelve a leer el perfil y pone al día proyecto.json y controles.json).
#  Aplicarlo dos veces no hace nada la segunda.
# =============================================================================
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _var_escenario(targets, nombre):
    """Id de la variable del escenario llamada así (la crea si no existe)."""
    stage = next(t for t in targets if t.get("escenario"))
    for vid, (n, _) in stage["vars"].items():
        if n == nombre:
            return vid
    vid = "parche-" + nombre
    stage["vars"][vid] = [nombre, 0]
    return vid


def _parar_si(targets, pt):
    t = next((t for t in targets if t["nombre"] == pt.get("objeto")), None)
    if t is None:
        return False
    vid = _var_escenario(targets, pt["parar_si"])
    op, clave = pt["guion"]
    bl = t["bloques"]
    hecho = False
    for h in t["guiones"]:
        if h[0] != op or str(h[1]) != str(clave):
            continue
        cuerpo = h[2]
        b0 = bl[cuerpo] if cuerpo >= 0 else None
        if b0 and b0[0] == "control_if" and b0[2].get("CONDITION", [None, -1])[1] >= 0:
            cond = bl[b0[2]["CONDITION"][1]]
            if cond[0] == "operator_gt" and cond[2].get("OPERAND1") == ["v", vid]:
                hecho = True                       # ya estaba
                continue
        n = len(bl)
        bl.append(["control_if", cuerpo, {"CONDITION": ["b", n + 1], "SUBSTACK": ["b", n + 2]}, {}, None])
        bl.append(["operator_gt", -1, {"OPERAND1": ["v", vid], "OPERAND2": ["l", "0"]}, {}, None])
        bl.append(["control_stop", -1, {}, {"STOP_OPTION": "this script"}, None])
        h[2] = n
        hecho = True
    return hecho


def aplicar(targets, patches):
    for pt in patches:
        if "parar_si" in pt:
            if _parar_si(targets, pt):
                print(f"  parche: {pt.get('motivo', pt['objeto'])}")
            continue
        for t in targets:
            for lid, (lname, items) in t["listas"].items():
                if lname != pt.get("lista"):
                    continue
                i = int(pt.get("indice", 0)) - 1
                if 0 <= i < len(items) and str(items[i]) == str(pt.get("era")):
                    items[i] = pt.get("valor")
                    print(f"  parche: {pt.get('motivo', lname)}")


def perfil_de(nombre):
    for pf in sorted((HERE / "perfiles").glob("*.json")):
        try:
            data = json.loads(pf.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if nombre.startswith(data.get("coincide", "\0")):
            return data
    return {}


def main():
    if len(sys.argv) != 2:
        print("uso: python pc/parches_scratch.py <carpeta del juego convertido>")
        return 1
    carpeta = Path(sys.argv[1])
    pj = carpeta / "proyecto.json"
    data = json.loads(pj.read_text(encoding="utf-8"))
    perfil = perfil_de(carpeta.name) or perfil_de(data.get("nombre", ""))
    if not perfil:
        print("No hay perfil para", data.get("nombre"))
        return 1
    aplicar(data["objetos"], perfil.get("parches", []))
    pj.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    cj = carpeta / "controles.json"
    if cj.exists():                                # el multijugador del perfil, al día
        ctl = json.loads(cj.read_text(encoding="utf-8"))
        ctl["multijugador"] = perfil.get("multijugador")
        cj.write_text(json.dumps(ctl, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Hecho:", carpeta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
