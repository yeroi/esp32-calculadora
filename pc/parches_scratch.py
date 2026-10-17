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
#   · Código: cambiar una entrada de un bloque
#       {"objeto": "snow", "buscar": {"op": "operator_equals",
#                                    "OPERAND1": ["v", "weather time"], "OPERAND2": ["l", "1"]},
#        "poner": {"OPERAND1": ["v", "Weather Type"]}, "motivo": "..."}
#     En los bloques del objeto que tengan ese opcode y esas entradas, cambia las de
#     "poner". En ["v", nombre] el nombre es el de la variable (del objeto o del
#     escenario): se traduce a su id.
#
#   · Código: cambiar variables por otras en todo un objeto
#       {"objeto": "Mob", "renombrar_var": {"_x": "_ObjX"}}
#     Toda lectura de _x en los bloques de Mob pasa a leer _ObjX (se crea si no existe).
#
#   · Código: un bloque nuevo al principio de un bloque propio
#       {"objeto": "Mob", "al_principio_de": "Process Mob",
#        "bloque": ["scicalc_objetivo", {"MODO": "cerca"}]}
#     (opcode, campos). Los "scicalc_*" son bloques del intérprete de la calculadora.
#
#   · Código: cambiar el opcode de bloques
#       {"objeto": "Mob", "cambiar_op": "data_changevariableby", "a": "scicalc_cambiar_jugador",
#        "si_var": ["_Health_s", "_KnockBack"]}
#     Solo los que cambian esas variables (campo VARIABLE).
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


def _id_var(targets, t, nombre):
    for o in (t, next(x for x in targets if x.get("escenario"))):
        for vid, (n, _) in o["vars"].items():
            if n == nombre:
                return vid
    return None


def _entrada(targets, t, e):
    if isinstance(e, list) and len(e) == 2 and e[0] == "v":
        return ["v", _id_var(targets, t, e[1])]
    return e


def _cambiar(targets, pt):
    t = next((t for t in targets if t["nombre"] == pt.get("objeto")), None)
    if t is None:
        return False
    busca = dict(pt["buscar"])
    op = busca.pop("op")
    busca = {k: _entrada(targets, t, v) for k, v in busca.items()}
    poner = {k: _entrada(targets, t, v) for k, v in pt["poner"].items()}
    hecho = False
    for b in t["bloques"]:
        if b[0] != op:
            continue
        if all(b[2].get(k) == v for k, v in poner.items()):
            hecho = True                           # ya estaba
            continue
        if all(b[2].get(k) == v for k, v in busca.items()):
            b[2].update(poner)
            hecho = True
    return hecho


def _objeto(targets, pt):
    return next((t for t in targets if t["nombre"] == pt.get("objeto")), None)


def _renombrar(targets, pt):
    t = _objeto(targets, pt)
    if t is None:
        return False
    cambios = {}
    for de, a in pt["renombrar_var"].items():
        vd = _id_var(targets, t, de)
        if vd:
            cambios[vd] = _var_escenario(targets, a)
    n = 0
    for b in t["bloques"]:
        for k, e in b[2].items():
            if isinstance(e, list) and len(e) == 2 and e[0] == "v" and e[1] in cambios:
                b[2][k] = ["v", cambios[e[1]]]
                n += 1
    return n > 0


def _al_principio(targets, pt):
    t = _objeto(targets, pt)
    if t is None or pt["al_principio_de"] not in t["procs"]:
        return False
    proc = t["procs"][pt["al_principio_de"]]
    op, campos = pt["bloque"]
    b0 = t["bloques"][proc[0]] if proc[0] >= 0 else None
    if b0 and b0[0] == op and b0[3] == campos:
        return True                                # ya estaba
    t["bloques"].append([op, proc[0], {}, dict(campos), None])
    proc[0] = len(t["bloques"]) - 1
    return True


def _cambiar_op(targets, pt):
    t = _objeto(targets, pt)
    if t is None:
        return False
    vids = set(filter(None, (_id_var(targets, t, n) for n in pt.get("si_var", []))))
    hecho = False
    for b in t["bloques"]:
        if b[0] in (pt["cambiar_op"], pt["a"]) and (not vids or b[3].get("VARIABLE") in vids):
            b[0] = pt["a"]
            hecho = True
    return hecho


def aplicar(targets, patches):
    for pt in patches:
        for clave, fn in (("renombrar_var", _renombrar), ("al_principio_de", _al_principio),
                          ("cambiar_op", _cambiar_op)):
            if clave in pt:
                if fn(targets, pt):
                    print(f"  parche: {pt.get('motivo', pt['objeto'])}")
                break
        else:
            _aplicar_uno(targets, pt)


def _aplicar_uno(targets, pt):
    if "buscar" in pt:
        if _cambiar(targets, pt):
            print(f"  parche: {pt.get('motivo', pt['objeto'])}")
    elif "parar_si" in pt:
        if _parar_si(targets, pt):
            print(f"  parche: {pt.get('motivo', pt['objeto'])}")
    else:
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
