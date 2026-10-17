# =============================================================================
#  Empaqueta MicroPython en firmware/sketch/src/mpy con includes RELATIVOS
#  (el IDE de Arduino no deja añadir rutas de include). Ver README.md.
# =============================================================================
import os, re, shutil, sys
# Uso:  python package.py <repo micropython> <salida>
TOP = os.path.abspath(sys.argv[1])
GEN = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(sys.argv[2])
shutil.rmtree(OUT, ignore_errors=True)
files = {}                                  # destino relativo -> origen
for f in os.listdir(f"{TOP}/py"):
    if f.endswith((".c", ".h")):
        files[f"py/{f}"] = f"{TOP}/py/{f}"
for f in ("modjson.c", "modre.c", "modheapq.c", "modbinascii.c", "modrandom.c", "modplatform.h"):
    files[f"extmod/{f}"] = f"{TOP}/extmod/{f}"
for f in os.listdir(f"{TOP}/lib/re1.5"):
    files[f"lib/re1.5/{f}"] = f"{TOP}/lib/re1.5/{f}"
for f in ("moduledefs.h", "mpversion.h", "qstrdefs.generated.h", "root_pointers.h"):
    files[f"genhdr/{f}"] = f"{GEN}/build-embed/genhdr/{f}"
for f in ("mphalport.h", "scicalc_py.h", "scicalc_port.c", "scicalc_gfx.c"):
    files[f"port/{f}"] = f"{GEN}/port/{f}"
# Módulos congelados (manifest.py), generados por el Makefile
files["port/frozen_content.c"] = f"{GEN}/build-embed/frozen_content.c"
files["mpconfigport.h"] = f"{GEN}/mpconfigport.h"

# Los .c de re1.5 los incluye modre.c: con otra extensión el IDE no los compila sueltos
rename = {k: k[:-2] + "_c.h" for k in files if k.startswith("lib/re1.5/") and k.endswith(".c")}
inc = re.compile(r'^(\s*#\s*include\s*)([<"])([^>"]+)([>"])', re.M)
missing = set()
for dst, src in files.items():
    text = open(src, encoding="utf-8", errors="surrogateescape").read()
    d = os.path.dirname(dst)
    def fix(m):
        name = m.group(3)
        if name in files:                    # ruta desde la raíz del paquete
            rel = os.path.relpath(rename.get(name, name), d or ".").replace(os.sep, "/")
            return f'{m.group(1)}"{rel}"'
        if m.group(2) == '"' and not os.path.exists(os.path.join(os.path.dirname(src), name)):
            missing.add((dst, name))
        return m.group(0)
    text = inc.sub(fix, text)
    if dst == "mpconfigport.h":
        text = text.replace('"port/mphalport.h"', '"../port/mphalport.h"')
    os.makedirs(os.path.join(OUT, d), exist_ok=True)
    open(os.path.join(OUT, rename.get(dst, dst)), "w", encoding="utf-8", errors="surrogateescape").write(text)
# re1.5: modre.c incluye los .c de re1.5; si el IDE los compilase sueltos darían
# símbolos duplicados -> se renombran a .h-like (no compilables)
print("ficheros:", len(files))
for m in sorted(missing):
    print("include sin resolver:", m)
