# Módulo `scicalc` para scripts gráficos (juegos)

Especificación implementada en el simulador (`simulador/scicalc_sim.py`, v0.5).
El firmware la implementará igual en el Paso 5 como módulo nativo de MicroPython
que dibuja a través de la HAL `Display` y lee el estado del teclado.

```python
from scicalc import pantalla, teclas
```

## pantalla

Zona del script: **320 × 218 px** (debajo de la barra de estado). Colores `0xRRGGBB`.
No hay framebuffer (el ESP32 sin PSRAM no tiene RAM para uno): lo que no se vuelve
a dibujar se queda en pantalla, así que **redibuja solo lo que cambia**.

| Función | Descripción |
|---|---|
| `ANCHO`, `ALTO` | 320, 218 |
| `color(r, g, b)` | devuelve `0xRRGGBB` |
| `limpiar(c=0)` | rellena la zona del script |
| `rect(x, y, w, h, c)` | rectángulo relleno |
| `marco(x, y, w, h, c)` | contorno |
| `linea(x0, y0, x1, y1, c)` | línea |
| `texto(t, x, y, c=BLANCO, fondo=None, tam=1)` | texto (fuente 6×8 en el ESP32) |
| `sprite(ruta)` | carga un PNG (relativo a la carpeta del script); devuelve un objeto con `ancho` y `alto` |
| `dibujar(spr, x, y, escala=1, espejo=False, angulo=0, centro=None)` | dibuja el sprite (con transparencia). `escala` admite decimales; `angulo` en grados, sentido horario. Sin `centro`, (x, y) es la esquina y gira sobre el centro; con `centro=(cx, cy)` ese píxel del sprite cae en (x, y) y es el punto de giro |
| `recorte(x, y, w, h)` / `recorte()` | limita el dibujo a un rectángulo (redibujado por zonas) / quita el límite |
| `mostrar()` | envía el fotograma, limita a 30 fps y **mantiene vivo el watchdog** |

## teclas

Nombres: `UP DOWN LEFT RIGHT EXE DEL SHIFT 0…9 . ADD SUB MUL DIV POW SIN COS TAN LN SQRT LP RP`.
**AC** (salir del script) y **MENU** los reserva el sistema.

| Función | Descripción |
|---|---|
| `pulsadas()` | conjunto de teclas mantenidas ahora mismo |
| `pulsada(nombre)` | `True` si está mantenida |
| `eventos()` | lista de `(nombre, shift)` pulsadas desde la última llamada |
| `ms()` | milisegundos (como `time.ticks_ms()`) |

## Watchdog

Un script que no llama a `mostrar()` en 5 s se corta (protege de bucles infinitos).
Un juego que muestra fotogramas sigue vivo; AC lo cierra siempre.

## Ejemplo: `sd/juegos/clonaria/clonaria.py`

Conversión de Clonaria (MIT) a MicroPython: mundo de 128×64 bloques en dos
`bytearray` (16 KB), física propia en lugar de Box2D y redibujado parcial.

## Ejemplo: proyectos de Scratch (`/lib/scratch.py`)

Intérprete de Scratch 3 escrito sobre esta API. Ver "Scratch" en el README.
