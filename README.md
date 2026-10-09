# ESP32 SciCalc

Calculadora científica portátil basada en ESP32 con un sistema híbrido:

- **Núcleo en C++ nativo** (FreeRTOS): interfaz, calculadora, archivos, conectividad y supervisión.
- **Sandbox MicroPython**: ejecuta los `.py` de la MicroSD sin poder colgar ni dañar el sistema.

El simulador de escritorio [`simulador/scicalc_sim.py`](simulador/scicalc_sim.py) es la **especificación funcional**: el firmware imita su comportamiento.

## Python en el ESP32 (Paso 5)

El firmware lleva **MicroPython 1.24.1** dentro (`firmware/sketch/src/mpy/`, lo compila el IDE de Arduino sin instalar nada más). En el modo **Python**: EXE ejecuta el script, SHIFT+EXE muestra el código.

- Cada script corre en **su propia tarea** con heap propio (~70 KB en el ESP32-WROOM sin PSRAM) y pila de 16 KB. Al acabar se libera todo.
- **Watchdog de 5 s** (no cuenta el tiempo esperando un permiso). **AC** lo detiene. Una recursión infinita da `RuntimeError` y quedarse sin memoria da `MemoryError`: la calculadora sigue funcionando.
- Los errores salen como en el simulador: `ZeroDivisionError: divide by zero (línea 5)`, y si fallan dentro de `/lib`, en qué archivo y línea.
- **Archivos**: leer es libre; escribir, borrar, renombrar o crear carpetas **pregunta** en pantalla (EXE sí · SHIFT+EXE sí a todo · AC no). No se puede salir de la SD (`..` está bloqueado). En modo PC lo escrito aparece en la carpeta `simulador/sd` del PC.
- `import` busca en la carpeta del script y en `/lib` (también paquetes con `__init__.py`).
- Módulos: `math`, `cmath`, `random`, `time`, `os` (y `os.path`), `json`, `re`, `struct`, `array`, `collections`, `heapq`, `binascii`, `errno`, `io`, `gc`, `sys`. No existen `subprocess`, `socket`, `machine`… ni `eval`/`exec`/`input`. Números decimales en doble precisión (como la calculadora) y enteros de tamaño ilimitado.
- Todos los ejemplos de `simulador/sd/scripts` funcionan igual que en el simulador.

### Juegos en el ESP32 (módulo `scicalc`)

Los juegos usan la misma API que en el simulador (`scicalc.pantalla` y `scicalc.teclas`, ver [docs/API_scicalc.md](docs/API_scicalc.md)):

- **El script no dibuja**: apunta las órdenes en una cola y `mostrar()` se la pasa a la UI, que es la única que toca la pantalla (en modo PC, lo único que habla por el USB). Así el menú y el juego nunca dibujan a la vez. `mostrar()` limita a ~30 fps y mantiene vivo el watchdog.
- **Sprites PNG**: los pequeños se guardan ya decodificados (hasta 48 KB entre todos); los grandes (un fondo de Scratch de 320×218 son 140 KB) se vuelven a leer de la SD cada vez que se dibujan. Escala, espejo, giro (los grandes no giran) y transparencia.
- **Teclas**: las pulsaciones llegan al juego; AC lo para. En modo PC, «mantenida» es el estado real del teclado del PC; con el teclado físico, una tecla cuenta como mantenida mientras se autorrepite.
- **El intérprete de Scratch va congelado en la flash** (`scratch`, `scratch_red` y `t9`, compilados al generar el firmware): ya no se compila en la placa ni gasta RAM de Python. AtrapaManzanas usa unos 49 KB de los ~70 KB que tiene Python (probado en un MicroPython 1.24.1 con 60 KB de heap).
- **Scripts grandes precompilados**: si junto a `juego.py` hay un `juego.mpy`, el ESP32 ejecuta el `.mpy` (el simulador sigue con el `.py`). Así Clonaria (23 KB de código, que no se puede compilar en la placa) usa ~45 KB. Se generan en el PC:

  ```bash
  pip install mpy-cross==1.24.1
  python pc/compilar_mpy.py simulador/sd/juegos/clonaria/clonaria.py
  ```

  `clonaria.mpy` ya viene hecho. Si cambias un `.py` que tiene `.mpy`, vuelve a compilarlo (o borra el `.mpy`): la consola avisa con «[clonaria.mpy precompilado]».

Aún no hay `scicalc.red` en el ESP32 (multijugador, web): Clonaria juega solo y el navegador no funciona allí. Paper Minecraft no cabe (ver más abajo). También faltan el editor de scripts y la Consola.

Para cambiar la configuración de MicroPython, ver [`firmware/micropython/README.md`](firmware/micropython/README.md).

## Modo PC: el ESP32 sin pantalla ni teclado

Para desarrollar sin cablear nada: **todo el firmware corre en el ESP32**, pero la pantalla, el teclado, la MicroSD y el altavoz están en el PC, por el mismo cable USB.

```
 ESP32 (todo el sistema)                         PC (pc/scicalc_pantalla.py)
 ───────────────────────     USB-serie 921600    ─────────────────────────────
 Display  ── órdenes de dibujo ───────────────►  pinta la pantalla 320×240
 Buzzer   ── tonos ───────────────────────────►  los toca por el altavoz
 Storage  ── "dame /fotos/x.png" ─────────────►  lee simulador/sd/ (= MicroSD)
          ◄── bytes del archivo ──────────────
 Teclado  ◄── tecla pulsada / soltada ────────   ratón o teclado del PC
 Serial.printf ── texto ──────────────────────►  consola del programa
```

Viene **activado por defecto** (`SCICALC_REMOTE 1` en `config.h`).

1. **Arduino IDE**: abre `firmware/sketch/sketch.ino`. Placa *ESP32 Dev Module*, esquema de particiones *Huge APP (3MB No OTA)*. Instala las librerías de `libraries.txt` (Gestor de librerías). Probado con el núcleo **esp32 de Espressif** 2.0.17 y 3.3.12.
2. Sube el programa al ESP32 y **cierra el Monitor Serie** del IDE (el puerto solo lo puede usar un programa).
3. En el PC:

   ```bash
   pip install pygame-ce pyserial
   python pc/scicalc_pantalla.py                  # busca el puerto solo
   python pc/scicalc_pantalla.py --puerto COM5    # o dile cuál
   python pc/scicalc_pantalla.py --lista          # ver puertos
   ```

Al conectar, el programa **reinicia el ESP32** (como hace el IDE al subir) y verás el arranque. Si cierras y vuelves a abrir el programa con `--sin-reset`, el ESP32 sigue donde estaba y repinta la pantalla entera.

Teclas del PC: las mismas que el simulador (Enter = EXE, Retroceso = DEL, Esc = AC, Tab = SHIFT, M = MENU, flechas, números...). Además: **F2** sonido sí/no, **F5/F6** batería −/+ (el ESP32 la muestra en su barra), **F7** cargando, **F9** reiniciar el ESP32, **F12** captura de la pantalla.

Detalles:

- **Pantalla**: cada primitiva de `Display` (rectángulos, triángulos, texto, bloques de píxeles) es una trama. El texto viaja como códigos de glifo y cada glifo (la fuente 5×8 de Adafruit) se envía una sola vez. Los bloques de píxeles van comprimidos por tramos cuando compensa; las fotos van en crudo (~90 KB/s).
- **MicroSD**: el ESP32 monta la carpeta del PC como sistema de archivos (`/pc`, VFS de ESP-IDF), así que el explorador, el visor de texto y los decodificadores PNG/JPG/GIF/BMP funcionan sin cambios. Las apps solo leen; los scripts de Python pueden escribir tras pedir permiso. Otra carpeta: `--sd ruta`.
- **Sonido**: nueva clase `Buzzer` (`tone()` en cola). Clic al pulsar teclas, aviso al aparecer un diálogo y melodía al arrancar. En el hardware real usará el zumbador del pin `PIN_BUZZER`.
- **Estado**: el ESP32 manda una vez por segundo heap, bloque máximo, tiempo encendido y app activa; el programa los muestra bajo la pantalla.
- Protocolo: `A5 5A | tipo | longitud (2) | datos | suma`, descrito en `firmware/sketch/RemoteLink.h`. Lo que no es trama se muestra como texto.
- Si la imagen sale con fallos, baja la velocidad: `REMOTE_BAUD = 460800` en `config.h` y `--baudios 460800` en el PC.
- Con el cable ocupado por el modo PC, *SciCalc Link* por USB no se puede usar a la vez.

**Volver al hardware real** (pantalla ILI9341, teclado y MicroSD cableados, o Wokwi): pon `#define SCICALC_REMOTE 0` en `config.h` (en PlatformIO, entorno `esp32dev-hw`). Con `SCICALC_REMOTE_SD 0` puedes usar la MicroSD física y seguir con la pantalla en el PC.

## Estado

| Paso | Contenido | Estado |
|---|---|---|
| 1 | Hardware y mapa de pines | ✅ |
| 2 | Firmware base (Display, Keyboard, Storage, AppManager) | ✅ |
| 3 | Menú e interfaz completos: 6 modos, diálogos, barra de estado, explorador, visores | ✅ |
| – | Modo PC: pantalla, teclado, SD y sonido en el PC (`pc/scicalc_pantalla.py`) | ✅ |
| 4 | Calculadora nativa (parser C++) | pendiente |
| **5** | **MicroPython: tarea con heap propio, watchdog, archivos con permisos, import desde la SD** | ✅ **este paso**: también los juegos (módulo `scicalc`, intérprete de Scratch congelado) |
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

**En Paper Minecraft**: menú SciCalc (SHIFT+EXE o «(») › **Multijugador...**

- **Buscar partidas en la red**: encuentra las partidas de este juego abiertas en tu Wi-Fi (servidores dedicados y calculadoras que hostean). *Unirse* te mete en ese mundo; si estás en el título, el juego empieza uno solo y lo cambia por el de la partida.
- **Hostear este mundo**: tu calculadora hace de servidor con el mundo en el que estás; los demás lo encuentran con *Buscar*.
- **+ Añadir servidor (IP)**: para jugar por internet; escribe `IP` o `IP:puerto` con el teclado en pantalla (los números se escriben directamente). Luego, en el servidor: *Unirse* o *Nueva partida aquí* (sube tu mundo).
- **Tu nombre**: el que ven los demás encima de tu personaje.
- **Bluetooth**: solo en el ESP32 real.

El servidor dedicado guarda los mundos en `pc/mundos_servidor/`: aunque se vaya todo el mundo o se apague, al volver la partida sigue ahí. `python pc/scicalc_servidor.py --nombre "Casa de Yerai"` le pone nombre.

También en **Ajustes › Multijugador**:

- **Servidor dedicado**: todos se conectan a la IP del PC que ejecuta `scicalc_servidor.py` (se pone en `/red.json`: `servidor`, `puerto`, `nombre`).
- **Anfitrión**: esta calculadora hace de servidor y los demás ponen su IP. En el simulador, el primero que entra lo abre y los demás simuladores del mismo PC se conectan solos.

Necesita Wi-Fi conectado y está bloqueado en modo examen.

- **Clonaria**: al empezar, `1` un jugador / `2` multijugador. Todos comparten el mismo mundo (semilla del anfitrión), ven los bloques que pican o ponen los demás —también los cambiados antes de entrar— y a los otros jugadores con su nombre encima.
- **Scratch**: las variables en la nube (☁) se sincronizan entre todos los que juegan al mismo proyecto.
- **Paper Minecraft** (y otros juegos de Scratch con un perfil): menú SciCalc › **Multijugador...** (ver arriba). Quien hostea sube su mundo; los demás lo reciben y aparecen a su lado. Los bloques que pica o pone cada uno se ven en todas las pantallas y cada jugador ve a los demás con su nombre. No se comparten criaturas, objetos tirados ni inventario. Se configura en la sección `multijugador` del perfil (`pc/perfiles/paper_minecraft.json`, ver `/lib/scratch_red.py`).
- **Tus juegos**: módulo `scicalc.red` ([docs/API_scicalc.md](docs/API_scicalc.md)).

Medios de conexión en el ESP32 (firmware, pendiente; mismo protocolo en todos):

| Medio | Cómo | Notas |
|---|---|---|
| Wi-Fi | `WiFiClient` al servidor o a la calculadora anfitriona | el único disponible en el simulador |
| USB al PC | la calculadora habla por el puerto serie y SciCalc Link en el PC lo reenvía al servidor | el PC hace de puente a internet |
| Bluetooth entre calculadoras | Bluetooth clásico SPP: una hace de anfitriona | el ESP32-WROOM-32 tiene BT clásico; **el ESP32-S3 solo tiene BLE**, ahí habría que usar BLE (más lento) |

## Navegador y red

- **Navegador** (`sd/apps/navegador.py`, en Python › apps): páginas web en modo texto, como los móviles de antes (el ESP32 no puede con JavaScript ni CSS). SHIFT+EXE escribe la dirección con T9 como en un Nokia (sin punto = busca en internet), ◄ ► eligen enlace, EXE lo abre, **+** descarga lo enlazado, DEL vuelve atrás. Lo que no es una página (zip, py, png…) se guarda en `/descargas` de la MicroSD. Es un script normal: usa `scicalc.red.web()` y `/lib/t9.py`.
- **Ajustes › Wi-Fi › Detalles de la red**: tu IP local, máscara de subred, puerta de enlace, DNS 1 y 2, MAC y señal. IP automática (DHCP) o estática; los DNS se pueden cambiar siempre y *Probar DNS* pregunta directamente al DNS elegido. En el ESP32: `WiFi.config(ip, puerta, máscara, dns1, dns2)` guardado en NVS.

## Estructura

```
firmware/
  platformio.ini        proyecto PlatformIO (src_dir = sketch)
  micropython/          configuración y puerto de MicroPython (para regenerar src/mpy)
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
    PySandbox.*         Python: tarea, heap, watchdog, salida y permisos
    src/mpy/            MicroPython 1.24.1 ya generado (no tocar a mano)
    RemoteLink.*        modo PC: enlace USB (tramas, teclas, peticiones)
    RemoteFS.*          modo PC: la carpeta del PC como "MicroSD" (VFS /pc)
    Buzzer.*            sonido (zumbador o altavoz del PC)
    diagram.json libraries.txt wokwi.toml   simulación en Wokwi
simulador/              scicalc_sim.py (referencia) + carpeta sd/ de ejemplo
pc/                     scicalc_pantalla.py (modo PC: pantalla, teclado, SD
                        y sonido del ESP32), scicalc_link.py, sb3_a_scicalc.py
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
