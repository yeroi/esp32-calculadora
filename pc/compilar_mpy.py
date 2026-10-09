#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 compilar_mpy.py — Precompila juegos .py para el ESP32 (juego.py -> juego.mpy)
===============================================================================
 Compilar un script grande en el ESP32 sin PSRAM necesita más RAM de la que
 hay (el código fuente entero + el árbol de análisis). Precompilado en el PC,
 la calculadora solo carga el bytecode: Clonaria pasa de no caber a usar ~45 KB.

 Si junto a juego.py hay un juego.mpy, el ESP32 ejecuta el .mpy (el
 simulador sigue usando el .py). Vuelve a compilar si cambias el .py.

   pip install mpy-cross==1.24.1          (la MISMA versión que el firmware)
   python pc/compilar_mpy.py simulador/sd/juegos/clonaria/clonaria.py
   python pc/compilar_mpy.py carpeta/      (todos los .py de la carpeta)
===============================================================================
"""
import shutil
import subprocess
import sys
from pathlib import Path

MP_VERSION = "1.24"          # MicroPython del firmware (firmware/sketch/src/mpy)


def mpy_cross_cmd():
    """Devuelve el comando de mpy-cross: el paquete de pip o el del PATH."""
    try:
        import mpy_cross                      # pip install mpy-cross==1.24.1
        exe = getattr(mpy_cross, "mpy_cross", None)
        if exe and Path(exe).exists():
            return [exe]
        return [sys.executable, "-m", "mpy_cross"]
    except ImportError:
        pass
    exe = shutil.which("mpy-cross")
    if exe:
        return [exe]
    print("No encuentro mpy-cross. Instálalo con:  pip install mpy-cross==1.24.1")
    sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = mpy_cross_cmd()
    ver = subprocess.run(cmd + ["--version"], capture_output=True, text=True).stdout
    if MP_VERSION not in ver:
        print(f"Aviso: mpy-cross es {ver.strip() or '?'}; el firmware usa MicroPython {MP_VERSION}.")
        print(f"       Si el ESP32 dice 'incompatible .mpy', instala mpy-cross=={MP_VERSION}.1")
    files = []
    for a in sys.argv[1:]:
        p = Path(a)
        files += sorted(p.glob("*.py")) if p.is_dir() else [p]
    ok = 0
    for f in files:
        out = f.with_suffix(".mpy")
        # -s: nombre del archivo en los mensajes de error ("línea N")
        r = subprocess.run(cmd + ["-s", f.name, "-o", str(out), str(f)], capture_output=True, text=True)
        if r.returncode:
            print(f"ERROR {f}:\n{r.stderr or r.stdout}")
            continue
        ok += 1
        print(f"{f.name} ({f.stat().st_size // 1024} KB) -> {out.name} ({out.stat().st_size // 1024} KB)")
    print(f"{ok} de {len(files)} compilados.")


if __name__ == "__main__":
    main()
