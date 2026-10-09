# ESP32 SciCalc

Calculadora científica portátil basada en ESP32 con un sistema híbrido:

- **Núcleo en C++ nativo** (FreeRTOS): interfaz, calculadora, archivos, conectividad y supervisión.
- **Sandbox MicroPython**: ejecuta los `.py` de la MicroSD sin poder colgar ni dañar el sistema.

El simulador de escritorio [`simulador/scicalc_sim.py`](simulador/scicalc_sim.py) es la **especificación funcional**: el firmware imita su comportamiento.

## Estado

| Paso | Contenido | Estado |
|---|---|---|
| 1 | Hardware y mapa de pines | ✅ |
| 2 | Firmware base (Display, Keyboard, Storage, AppManager) | ✅ |
| **3** | **Menú e interfaz completos: 6 modos, diálogos, barra de estado, explorador, visores** | ✅ **este paso** |
| 4 | Calculadora nativa (parser C++) | pendiente |
| 5 | MicroPython embed: tarea con heap propio, watchdog, VFS con permisos | pendiente |
| – | Consola con ALPHA + editor de código + `pip` por Wi-Fi · Ajustes reales (WiFi.h, BT SPP, NVS) · LinkService · buzzer · batería | pendiente (ya especificado en el simulador v0.4) |
| 9–10 | Hardware real (TFT_eSPI + DMA, MCP23017) · PCB | pendiente |

## Simulador (v0.6)

```bash
pip install pygame-ce
python simulador/scicalc_sim.py
```

Novedades de la v0.4 (especificación para el firmware):

- **Las líneas largas se parten** en varias filas en la salida de Python y en la Consola (por palabras cuando se puede).
- **Editor de código** en la calculadora: en *Python*, SHIFT+EXE sobre un `.py` lo edita y sobre una carpeta crea `nuevo.py`; en la *Consola*, `edit archivo.py`. Sangría automática tras `:`, DEL quita un nivel de sangría, SHIFT+EXE guarda, SHIFT+► guarda y ejecuta (y al cerrar la salida vuelves al editor), AC sale (pregunta si hay cambios). Bloqueado en modo examen.
- **`pip` con Wi-Fi** en la Consola: `pip install x`, `pip uninstall x`, `pip list`. Necesita Wi-Fi conectado (Ajustes › Wi-Fi) y pide confirmación antes de escribir en `/lib`.
  1. Busca primero en **micropython-lib** (el índice de `mip`): paquetes hechos para MicroPython.
  2. Si no está, prueba **PyPI**, solo ruedas de Python puro (`py3-none-any`), sin usar el pip del PC.
  3. Rechaza el código nativo (numpy, pandas…) y lo que pase de 1 MB.
- **v0.5 — juegos**: módulo `scicalc` (`pantalla` + `teclas`) para que los scripts dibujen y lean teclas ([docs/API_scicalc.md](docs/API_scicalc.md)), y **Clonaria** convertido a MicroPython en `sd/juegos/clonaria/`. El watchdog no corta un juego mientras siga mostrando fotogramas; AC lo cierra.
- **v0.6 — multijugador**: módulo `scicalc.red`, Ajustes › Multijugador, Clonaria en red y variables ☁ de Scratch (ver *Multijugador*).
- `sys` del sandbox como el de MicroPython: `modules`, `implementation`, `exit`, `print_exception`.

> En el ESP32 **no existe pip**. El comando `pip` de la calculadora es un instalador propio que hará lo mismo por Wi-Fi: `mip` (micropython-lib) y, como alternativa, descargar la rueda de PyPI y descomprimirla (el ESP32 trae `inflate` en la ROM). Aun así, casi nada de PyPI funciona en MicroPython porque usa módulos de CPython.

## Proyectos de Scratch

La calculadora ejecuta proyectos de Scratch 3 con un intérprete propio (`/lib/scratch.py`). El `.sb3` se prepara antes en el PC:

```bash
pip install pygame-ce resvg-py
python pc/sb3_a_scicalc.py MiJuego.sb3                  # -> simulador/sd/scratch/
python pc/sb3_a_scicalc.py MiJuego.sb3 E:\              # -> MicroSD (E:\scratch\)
```

`resvg-py` hace falta para dibujar bien los disfraces SVG: muchos llevan imágenes PNG incrustadas que pygame no sabe dibujar. Crea `sd/scratch/mijuego/` con los disfraces ya escalados (el escenario de 480×360 se guarda a 320×218, píxel a píxel con la pantalla), un `proyecto.json` simplificado y un lanzador `mijuego.py`. En la calculadora: **Python › scratch › mijuego › mijuego.py**. El convertidor dice qué tecla de la calculadora corresponde a cada tecla de Scratch (flechas → flechas, espacio → EXE; las letras a teclas libres, también en `LEEME.txt`). AC sale.

**Ratón virtual**: **8 4 6 2** mueven el puntero (mantener acelera) y **5** es el clic (mantenido = botón pulsado). Funcionan "ratón x/y", "¿ratón presionado?", "tocando puntero del ratón" y "al hacer clic en este objeto". Si el juego usa también las teclas 2, 4, 5, 6 u 8, pasan a SHIFT+número; cuando se acaban las teclas libres se usan combinaciones SHIFT+tecla. WASD van a las flechas.

**Pantalla completa**: el escenario se estira a toda la pantalla (320×218); en el menú se puede cambiar a "proporcional".

**Menú SciCalc** (SHIFT+EXE, o la tecla que diga el perfil): pausa el juego y permite guardar la partida, mandar la pausa del juego, cambiar la pantalla, poner el rendimiento en "rápido" (dibuja 1 de cada 2 fotogramas) y ver los controles.

**Partidas guardadas**: si el juego muestra una lista cuyo nombre contiene "save", su contenido se guarda en `partida_N.txt` junto al juego (el sandbox pide permiso para escribir). Cuando el juego pide pegar un código de partida, aparece un selector: pulsa el número de la partida.

**Controles por juego**: el convertidor crea `controles.json` (editable) y aplica los perfiles de `pc/perfiles/` (incluido el de Paper Minecraft: E → 9, F → 7, barra de objetos en SHIFT+1…9, P → "(" abre el menú, guardar con O). Correr (SHIFT en Scratch) es un doble toque rápido en ◄ o ►.

El intérprete reparte el tiempo como Scratch: en cada fotograma repite los guiones hasta que algo cambia en pantalla, así que los bucles de cálculo (generar un mundo, por ejemplo) van a toda velocidad. Probado con *Paper Minecraft* de griffpatch (30 objetos, 14 000 bloques): genera el mundo y se juega en el simulador.

Ejemplo incluido: `pc/ejemplos/AtrapaManzanas.sb3`, ya convertido en `simulador/sd/scratch/atrapamanzanas/`.

| Soportado | No soportado (por ahora) |
|---|---|
| Eventos: bandera, teclas, clic en objeto/escenario, mensajes (y esperar), clones (hasta 300), cambio de fondo | Sonido (los bloques no hacen nada) |
| Movimiento completo, rebotar, estilo de giro | Lápiz |
| Disfraces, fondos, tamaño, mostrar/ocultar, decir/pensar, capas, efecto fantasma | Arrastrar objetos con el ratón |
| Control: esperar, repetir, por siempre, si/si no, hasta, mientras, detener, clones | "Tocando color" y efectos de color |
| Sensores: tecla, ratón virtual, tocando objeto/borde, temporizador, distancia, "de", preguntar (solo números) | Escribir letras en "preguntar" (llegará con ALPHA) |
| Operadores, variables (con marcadores), listas, bloques propios (también sin refrescar) | |

La colisión usa cajas rectangulares (no el contorno exacto). En el ESP32 sin PSRAM solo caben proyectos pequeños (`proyecto.json` de pocas decenas de KB); con un ESP32-S3 con PSRAM, mucho más.

## Multijugador

Las calculadoras juegan juntas a través de un **servidor SciCalc** (protocolo propio: un JSON por línea sobre TCP, puerto 8267; no usa los servidores de Scratch ni de nadie).

```bash
python pc/scicalc_servidor.py          # servidor dedicado en un PC (o en internet)
```

En la calculadora, **Ajustes › Multijugador**:

- **Servidor dedicado**: todos se conectan a la IP del PC que ejecuta `scicalc_servidor.py` (se pone en `/red.json`: `servidor`, `puerto`, `nombre`).
- **Anfitrión**: esta calculadora hace de servidor y los demás ponen su IP. En el simulador, el primero que entra lo abre y los demás simuladores del mismo PC se conectan solos.

Necesita Wi-Fi conectado y está bloqueado en modo examen.

- **Clonaria**: al empezar, `1` un jugador / `2` multijugador. Todos comparten el mismo mundo (semilla del anfitrión), ven los bloques que pican o ponen los demás —también los cambiados antes de entrar— y a los otros jugadores con su nombre encima.
- **Scratch**: las variables en la nube (☁) se sincronizan entre todos los que juegan al mismo proyecto.
- **Paper Minecraft** (y otros juegos de Scratch con un perfil): menú SciCalc (SHIFT+EXE o «(») › **Multijugador: conectar**. El primero que se conecta abre la partida y sube su mundo; los demás lo reciben y aparecen a su lado. Los bloques que pica o pone cada uno se ven en todas las pantallas y cada jugador ve a los demás con su nombre. No se comparten criaturas, objetos tirados ni inventario. Se configura en la sección `multijugador` del perfil (`pc/perfiles/paper_minecraft.json`, ver `/lib/scratch_red.py`).
- **Tus juegos**: módulo `scicalc.red` ([docs/API_scicalc.md](docs/API_scicalc.md)).

Medios de conexión en el ESP32 (firmware, pendiente; mismo protocolo en todos):

| Medio | Cómo | Notas |
|---|---|---|
| Wi-Fi | `WiFiClient` al servidor o a la calculadora anfitriona | el único disponible en el simulador |
| USB al PC | la calculadora habla por el puerto serie y SciCalc Link en el PC lo reenvía al servidor | el PC hace de puente a internet |
| Bluetooth entre calculadoras | Bluetooth clásico SPP: una hace de anfitriona | el ESP32-WROOM-32 tiene BT clásico; **el ESP32-S3 solo tiene BLE**, ahí habría que usar BLE (más lento) |

## Estructura

```
firmware/
  platformio.ini        proyecto PlatformIO (src_dir = sketch)
  sketch/               TODO el código, en una carpeta plana (vale para
                        PlatformIO, Arduino IDE y Wokwi sin cambios)
    sketch.ino          arranque y creación de servicios y modos
    config.h Theme.h    pines, constantes, paleta
    Display.*           HAL gráfica (UTF-8 -> CP437 + glifos propios)
    Keyboard.*          escaneo en tarea FreeRTOS (core 0) -> cola
    Storage.*           MicroSD de SOLO lectura + utilidades de rutas
    SystemState.h       estado global (DEG/RAD, radios, examen, SD...)
    StatusBar.*         barra de estado
    Dialog.*            diálogos modales
    App.h AppManager.cpp  marco de modos y teclas globales
    ScrollList.h FolderBrowser.* FileViewer.* ImageDecoder.*  componentes
    MenuApp CalcApp PythonApp FilesApp SettingsApp DiagApp PlaceholderApp
    BootScreen.*        arranque con autodiagnóstico
    PackageManifest.*   lectura de /lib/paquetes.json
    diagram.json libraries.txt wokwi.toml   simulación en Wokwi
simulador/              scicalc_sim.py (referencia) + carpeta sd/ de ejemplo
pc/                     scicalc_link.py (programa del PC), sb3_a_scicalc.py
                        (convertidor de Scratch), scicalc_servidor.py
                        (servidor multijugador) y ejemplos/
```

## Compilar y probar

**PlatformIO** (recomendado):

```bash
cd firmware
pio run                     # compilar
pio run -t upload           # grabar el ESP32
pio device monitor          # monitor serie a 115200 (DTR/RTS desactivados)
```

**Arduino IDE**: abre `firmware/sketch/sketch.ino`, instala las librerías de `libraries.txt`, placa *ESP32 Dev Module* y esquema de particiones *Huge APP (3MB No OTA)*.

**Wokwi (web)**: crea un proyecto ESP32 y sube todos los archivos de `firmware/sketch/` (incluidos `diagram.json` y `libraries.txt`). Los archivos que añadas al proyecto aparecen en la raíz de la MicroSD simulada.

**Wokwi (VS Code)**: `pio run` en `firmware/` y luego *Wokwi: Start Simulator* con `firmware/sketch/wokwi.toml`.

Teclas en Wokwi: el teclado izquierdo es el bloque A (SHIFT, MENU, flechas, DEL, AC, funciones) y el derecho el bloque B (numérico).

## Paso 3: qué hace el firmware

- **Arranque**: autodiagnóstico de pantalla, teclado, MicroSD, PSRAM y sandbox, con barra de progreso.
- **Menú**: 6 modos, ▲▼ + EXE o acceso directo con las teclas 1–6. MENU vuelve desde cualquier sitio.
- **Barra de estado**: título, SHIFT, EXAMEN, LINK, BT, WiFi, DEG/RAD (solo en la calculadora), SD, hora y batería. Se repinta solo cuando algo cambia.
- **Diálogos modales**: EXE = Sí, SHIFT+EXE = Sí a todo, AC/DEL = No; los informativos solo tienen Aceptar. Se encolan y se pueden pedir **desde otra tarea** (`askBlocking`, con timeout), que es lo que usarán el sandbox (permisos) y SciCalc Link.
- **Archivos SD**: carpetas primero, `..` para subir, iconos por tipo, desplazamiento.
  - Texto/código con números de línea y resaltado de Python (comentarios, cadenas, palabras clave). No se carga entero: se indexan las líneas y se leen solo las 18 visibles.
  - Imágenes **PNG, JPG (baseline), BMP y GIF** (primer fotograma), escaladas y centradas como en el simulador (hasta x4).
  - Binarios en vista hexadecimal desplazable.
- **Python**: explorador de carpetas y `.py`. En modo examen está bloqueado. Hasta el Paso 5, EXE ofrece ver el código.
- **Ajustes**: todas las páginas (Wi-Fi, Bluetooth, USB, modo examen, paquetes, acerca de). El **modo examen funciona** (apaga Wi-Fi y BT, bloquea Python y muestra EXAMEN). Los interruptores de radio aún solo cambian el estado.
- **Diagnóstico**: chip, flash, PSRAM, heap y bloque máximo, SD y rejilla de las 32 teclas.
- **Calculadora y Consola**: pantallas provisionales (Pasos 4 y ALPHA). SHIFT+AC ya cambia DEG/RAD.

### Memoria (ESP32-WROOM-32, sin PSRAM)

| | |
|---|---|
| Flash usada | ~445 KB de 3 MB (partición *huge_app*) |
| RAM estática | ~27 KB |
| Visor PNG / GIF / JPG | ~45 / ~25 / ~4 KB, **solo mientras se dibuja** |
| Índice del visor de texto | 4 B por línea (máx. 4000 líneas = 16 KB) |

No hay framebuffer (150 KB no caben): todo se dibuja directamente en la pantalla y cada app redibuja solo lo que cambia.

### Limitaciones conocidas

- **JPG progresivo** no soportado (TJpgDec solo decodifica *baseline*): se avisa en pantalla.
- **PNG**: ancho máximo 640 px en RGBA con PlatformIO (`-DPNG_MAX_BUFFERED_PIXELS` en `platformio.ini`); en Arduino IDE/Wokwi, 320 px (no se pueden pasar opciones de compilación).
- **Hora**: sin RTC ni NTP se muestra `--:--` (la hora llegará con Wi-Fi/NTP).
- **Batería**: icono con `?` hasta el paso de lectura por ADC.
- **Disco USB (MSC)**: necesita USB nativo, es decir, un **ESP32-S3**. Con el WROOM-32 se usa el modo serie.

## Conexiones

Bus SPI compartido por la pantalla y la MicroSD (cada una con su CS).

```
                 ESP32 DevKit (WROOM-32)
              ┌───────────────────────────┐
   TFT SCK ───┤ GPIO18 (SCK)              │
   SD  SCK ───┤                           │
   TFT MOSI ──┤ GPIO23 (MOSI)             │
   SD  DI ────┤                           │
   TFT MISO ──┤ GPIO19 (MISO)             │
   SD  DO ────┤                           │
   TFT CS ────┤ GPIO5                     │
   TFT D/C ───┤ GPIO4                     │
   SD  CS ────┤ GPIO15                    │
   TFT RST ───┤ 3V3                       │
   TFT LED ───┤ 3V3                       │
              │                           │
   Filas   ───┤ 32 33 25 26 │ 27 14 12 13 │  (INPUT_PULLUP)
              │  teclado A  │  teclado B  │
   Columnas ──┤ 16 17 21 22 (compartidas) │  (activas a nivel bajo)
              └───────────────────────────┘
```

| Señal | GPIO | Notas |
|---|---|---|
| SPI SCK / MOSI / MISO | 18 / 23 / 19 | compartido TFT + SD |
| TFT CS / DC / RST | 5 / 4 / 3V3 | ILI9341 320×240 |
| SD CS | 15 | pin de arranque: en alto al encender, válido como CS |
| Filas teclado (Wokwi) | 32, 33, 25, 26, 27, 14, 12, 13 | 12 es de arranque: solo entrada con pull-up |
| Columnas teclado (Wokwi) | 16, 17, 21, 22 | |
| MCP23017 (real) | SDA 21, SCL 22, INTA 39 | INTA con pull-up externa de 10k |
| Batería (real) | 34 (ADC1) | divisor 100k + 100k |
| Buzzer (real) | 2 o 27 | LEDC, según el mapa final |

Prohibidos: GPIO 6–11 (flash), 1 y 3 (UART0).
