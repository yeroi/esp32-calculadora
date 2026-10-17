#!/usr/bin/env python3
# Descompila el proyecto.json de un juego de Scratch convertido a texto legible:
#   python pc/descompilar_scratch.py simulador/sd/scratch/<juego>/proyecto.json [Objeto] > juego.txt
# Cada linea es un bloque; #N es su indice (el que usan los parches de pc/parches_scratch.py).
import json, sys
d = json.load(open(sys.argv[1]))
names = {}
for o in d["objetos"]:
    for k, v in list(o["vars"].items()) + list(o["listas"].items()):
        names[k] = v[0]
def val(o, inp):
    k, v = inp
    if k == "l": return repr(v)
    if k in ("v",): return "(" + names.get(v, v) + ")"
    if k == "L": return "[" + names.get(v, v) + "]"
    if isinstance(v, int) and v >= 0: return expr(o, v)
    return "?"
def expr(o, i):
    b = o["bloques"][i]
    args = ", ".join("%s=%s" % (n, val(o, x)) for n, x in b[2].items() if x[0] != "b" or True)
    f = ", ".join("%s:%s" % kv for kv in b[3].items())
    extra = (" " + b[4]) if len(b) > 4 and b[4] else ""
    return "%s%s{%s%s}" % (b[0].replace("operator_", "op.").replace("data_", ""), extra, args, (" | " + f) if f else "")
def stack(o, i, ind):
    out = []
    while i is not None and i >= 0:
        b = o["bloques"][i]
        subs = {n: x for n, x in b[2].items() if x[0] == "b" and n.startswith("SUBSTACK")}
        args = ", ".join("%s=%s" % (n, val(o, x)) for n, x in b[2].items() if n not in subs)
        f = ", ".join("%s:%s" % kv for kv in b[3].items())
        extra = (" '" + b[4] + "'") if len(b) > 4 and b[4] else ""
        out.append("  " * ind + "%s%s %s %s  #%d" % (b[0], extra, args, f, i))
        for n in sorted(subs):
            out.append("  " * ind + " " + n + ":")
            out += stack(o, subs[n][1], ind + 2)
        i = b[1]
    return out
for o in d["objetos"]:
    if len(sys.argv) > 2 and o["nombre"] != sys.argv[2]: continue
    print("=" * 20, o["nombre"])
    for h in o["guiones"]:
        print("WHEN", h[0], h[1])
        print("\n".join(stack(o, h[2], 1)))
    for p, v in o["procs"].items():
        print("DEFINE", p, v[1:])
        print("\n".join(stack(o, v[0], 1)))
