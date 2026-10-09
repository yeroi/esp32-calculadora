# MicroPython del firmware

El firmware lleva **MicroPython 1.24.1** (port *embed*) ya generado en
`firmware/sketch/src/mpy/`. El IDE de Arduino lo compila solo: **no hay que hacer
nada de esta carpeta para usarlo**.

Esta carpeta es el "código fuente" de esa integración, para cuando quieras
cambiar algo:

| Archivo | Qué es |
|---|---|
| `mpconfigport.h` | Qué tiene MicroPython (módulos, float double, límites...) |
| `port/scicalc_port.c` | Módulo `_sc` (archivos con permisos), `import` desde la SD, GC para Xtensa, preludio con `open`, `os`, `time` |
| `port/scicalc_py.h` | Puente con el firmware C++ (`PySandbox.cpp`) |
| `Makefile` + `package.py` | Regeneran `sketch/src/mpy/` |

## Regenerar (Linux, macOS o WSL)

Hace falta si cambias `mpconfigport.h` o añades funciones/módulos en `port/`
(MicroPython genera tablas de nombres a partir del código).

```bash
git clone --depth 1 -b v1.24.1 https://github.com/micropython/micropython.git
cd firmware/micropython
make MICROPYTHON_TOP=/ruta/a/micropython
python3 package.py /ruta/a/micropython ../sketch/src/mpy
```

`package.py` copia los archivos necesarios y reescribe los `#include` con rutas
relativas (el IDE de Arduino no permite añadir rutas de include).
