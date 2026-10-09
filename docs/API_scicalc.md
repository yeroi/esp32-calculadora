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

## red (multijugador)

El script no abre sockets: le pide la conexión al núcleo, que la lleva por él
(en el ESP32, una tarea con `WiFiClient`). Todos los jugadores de la misma
**sala** se ven entre sí. Servidor, puerto y nombre salen de `/red.json`
(Ajustes › Multijugador).

| Función | Descripción |
|---|---|
| `conectar(sala, nombre=None)` | entra en una sala (no espera) |
| `esperar(seg=6)` | espera a estar conectado; `True` si lo consigue. Mantiene vivo el watchdog |
| `estado()` | `"conectando"`, `"conectado"`, `"error"` o `"desconectado"` |
| `error()` | texto del último error |
| `mi_id()` / `anfitrion()` | tu número de jugador / el del anfitrión (el más antiguo de la sala) |
| `jugadores()` | `{id: nombre}` de la sala, tú incluido |
| `enviar(d)` | manda el diccionario `d` a los demás (no se guarda) |
| `var(nombre, valor)` | variable compartida: la reciben todos y **se guarda en la sala** |
| `vars()` | todas las variables de la sala (también las de antes de entrar) |
| `recibir()` | lista de mensajes llegados desde la última llamada |
| `desconectar()` | sale de la sala |
| `conectar(sala, nombre, host, puerto, hostear)` | con `host`: a ese servidor; `hostear=True`: esta calculadora es el servidor |
| `vaciar()` | borra las variables de la sala (al abrir un mundo nuevo) |
| `buscar()` | partidas en la red local: `[{"ip", "puerto", "nombre", "salas": [...]}]` |
| `salas(host, puerto)` | salas de un servidor |
| `servidores()` / `guardar_servidor(host, puerto)` / `quitar_servidor(i)` | servidores añadidos por IP |
| `config()` / `poner_nombre(n)` | nombre y servidor de Ajustes › Multijugador |
| `web(url)` / `descargar(url, nombre)` | piden una página o guardan un archivo en `/descargas`; devuelven un número de petición |
| `respuesta(n)` | respuesta de `web`/`descargar` (o `None` si aún no llegó) |

Las funciones `buscar`, `salas`, `servidores`, `config`... esperan la respuesta
(manteniendo vivo el watchdog). `web` y `descargar` no esperan: el script sigue
dibujando y mira `respuesta(n)` en cada fotograma (ver `sd/apps/navegador.py`).
Si falla, la respuesta es `{"error": "..."}`.

Mensajes de `recibir()`: `{"t":"de","id":3,"d":{...}}` (un `enviar`),
`{"t":"var","id":3,"n":...,"v":...}`, `{"t":"entra","id":4,"nombre":"Luis"}`,
`{"t":"sale","id":4}`, `{"t":"estado","e":"desconectado","msg":...}`.

Regla práctica: lo que cambia muy a menudo (posiciones) con `enviar`; lo que
tiene que ver quien entre más tarde (bloques del mundo, puntuaciones) con `var`.

```python
from scicalc import red
red.conectar("mi_juego")
if red.esperar():
    red.var("record", 120)
    red.enviar({"x": 10, "y": 4})
    for m in red.recibir():
        ...
```

## En el ESP32

`pantalla` y `teclas` funcionan igual (módulo en C del firmware). Diferencias:
sin `red` todavía (`from scicalc import red` da `ImportError`: comprueba si
existe), los sprites grandes no giran, y Python tiene ~70 KB: para scripts
grandes, precompila con `pc/compilar_mpy.py` (`juego.mpy` junto a `juego.py`).

## Watchdog

Un script que no llama a `mostrar()` en 5 s se corta (protege de bucles infinitos).
Un juego que muestra fotogramas sigue vivo; AC lo cierra siempre.

## Ejemplo: `sd/juegos/clonaria/clonaria.py`

Conversión de Clonaria (MIT) a MicroPython: mundo de 128×64 bloques en dos
`bytearray` (16 KB), física propia en lugar de Box2D y redibujado parcial.
Multijugador: el anfitrión publica la variable `semilla` (todos generan el
mismo mundo sin enviarlo), cada bloque cambiado es la variable `b:x,y` y las
posiciones van con `enviar` 10 veces por segundo.

## Ejemplo: proyectos de Scratch (`/lib/scratch.py`)

Intérprete de Scratch 3 escrito sobre esta API. Ver "Scratch" en el README.
Las variables en la nube (☁) se comparten con `red.var` en la sala
`scratch:<carpeta del juego>`.
