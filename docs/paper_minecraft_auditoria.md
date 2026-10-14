# Paper Minecraft v11.7: auditoría del código y plan

Auditoría hecha sobre el **código real** del juego. El `.sb3` convertido se ha descompilado a texto (9 247 líneas, 30 objetos). Los `#N` son números de bloque del `proyecto.json` convertido. Para volver a sacar el texto: `python pc/descompilar_scratch.py simulador/sd/scratch/paper_minecraft_v11_7_mi/proyecto.json`.

Estados:
- ✅ **hecho**: funciona en el juego.
- 🟡 **incompleto**: existe, pero le faltan partes.
- 🔴 **roto**: existe, pero tiene un fallo.
- ⬜ **no existe**: ni está ni hay base para ello.
- 🧪 **por probar**: el código parece correcto, pero no se ha comprobado jugando.

El intérprete de la calculadora implementa **todos** los tipos de bloque de Scratch que usa el juego, así que no falta nada por soporte.

## 1. Cómo funciona

| Sistema | Estado | Dónde / cómo |
|---|---|---|
| Generación del mundo | ✅ | Objeto **Generator**.<br>• Semilla 2 000–998 000. Todo el azar sale de la lista `_RANDOM` (Pseudorandom Cycle).<br>• Nivel de 200×128 en `_Level` (`i = y·200 + x + 1`). |
| Chunks (mundo infinito) | ✅ | Processor `go` #360-376: al salir por un borde se guarda el chunk y se carga o genera el siguiente (`_CHUNK_SEED` ± 198). |
| Biomas | ✅ | 1-10 por chunk, relieve con `BIOME_DATA`. El 8 es nevado; Nether si la semilla ≥ 1 000 000. |
| Cuevas, lava, minerales | ✅ | `Init Caves` #397.<br>Vetas: carbón, hierro, oro, diamante, redstone… (`Init Seams` #1030). |
| Árboles, mazmorras | ✅ | `Make Tree`, `Add Dungeons` (spawner + cofre). |
| Aldeas | 🟡 | `Spawn village` #1187 usa azar real, no el de la semilla: no se repiten con la misma semilla. No importa porque los chunks se guardan. |
| Coordenadas y cámara | ✅ | `_x`/`_y` en casillas.<br>`_ScrX`/`_ScrY`: cámara con desplazamiento por el ratón. |
| Movimiento | ✅ | Andar 0.15, saltar 0.42, gravedad −0.04/tick, agua, escaleras, subida automática de medio bloque, losas. |
| Correr | ✅ | En Scratch usa una tecla vacía `''` (#940). El intérprete la convierte en **doble toque en ◄/►** (`correr` en el perfil). |
| Romper bloques | ✅ | Cursor `Get Dig Speed` #1098: dureza del bloque × herramienta adecuada y su nivel (÷3·nivel, o ×3.33 si no es la adecuada). Grieta en 10 fases. |
| Soltar lo roto | ✅ | Solo con la herramienta correcta (`Add To Harvest`). Los objetos se atraen al jugador. |
| Colocar y usar | ✅ | Antorchas, puertas, losas, azada, semillas, mechero, polvo de hueso, cubo, comer (F), arco. |
| Durabilidad | ✅ | `Damage Tool` #568: en las herramientas, el contador del inventario es la durabilidad. |
| Inventario | ✅ | `_Inv`: barra 1-9, mochila hasta 36, armadura 37-40.<br>Arrastrar, dividir pilas (mitad), soltar de 1 en 1, tirar con Q. |
| Tamaño de pila | 🟡 | Solo 1 o 64 (no hay pilas de 16). |
| Shift-clic | 🟡 | También usa la tecla vacía `''` (#931): solo funciona mientras corres. |
| Crafteo | ✅ | `Check Recipe` #165: rejilla 2×2 o 3×3 (mesa), con recetas en espejo. |
| Hornos | ✅ | `Process Burn` #19: 10 s por objeto, con combustible según el bloque. |
| Cofres | ✅ | Lista `_Inside`; se guardan en la partida (registro 301). |
| Mobs | ✅ | 12 tipos:<br>• Pasivos: cerdo, oveja, vaca, gallina, aldeano.<br>• Lobo / perro domable.<br>• Hostiles: zombi, creeper, araña, esqueleto, enderman, pigman.<br>IA: deambular, saltar, trepar (araña), perseguir con línea de visión, flechas, explosión, quemarse al sol. |
| Vida, hambre, oxígeno, armadura | ✅ | Regeneración con hambre > 17.5, inanición, caída, lava, ahogo, armadura con durabilidad. |
| Invulnerabilidad del jugador | ⬜ | Solo existe la recarga de 1.5 s de cada mob. Los mobs sí tienen 0.8 s de invulnerabilidad. |
| Muerte y reaparición | ✅ | Se tira todo el inventario. Se reaparece en la cama o en el punto inicial, incluso en otro chunk. |
| Día y noche | ✅ | Unos 20 minutos por día; dormir lo acelera. |
| Iluminación | ✅ | `_Light`: luz de cielo y de bloques, propagada. |
| Clima | 🔴 | Objeto snow #18: compara `weather time = 1`, que nunca se cumple. Nunca hay clima aleatorio; solo nieve en el bioma nevado o con comandos. |
| Guardar / cargar | 🟡 | Se guardan el nivel por chunks, el jugador, el inventario, los cofres y los mobs.<br>**No se guardan** el hambre, la saturación, el oxígeno, la vida exacta de cada mob ni el clima. |
| Experiencia, encantamientos, logros, jefes, End | ⬜ | No existen en esta versión. Las capturas con número verde de nivel son de versiones más nuevas de Paper Minecraft. |

## 2. Multijugador (lo que hemos añadido nosotros)

Lo que se ha hecho ya, comparado con Minecraft real (referencia: el cliente libre **Minosoft** y el protocolo de Java Edition):

| Punto de la lista | Estado | Cómo está |
|---|---|---|
| Local, directo o servidor | ✅ | Partidas en la Wi-Fi (buscar), por IP directa o con un servidor dedicado (`pc/scicalc_servidor.py`). En el ESP32 real, también por Bluetooth. |
| Identidad de cada jugador | ✅ | Id de la sala y nombre (Ajustes o `red.json`). |
| Posición y animaciones | 🟡 | El "espejo" manda unas 10 veces por segundo cuerpo, objeto en mano, grieta y objetos tirados.<br>**Falta** interpolar (Minecraft suaviza 3 ticks). |
| Bloques rotos y puestos | ✅ | `b:chunk:i`, separado por chunk como en Minecraft (arreglado hoy). Lo que se cambió antes de entrar también llega.<br>**Falta** que el anfitrión confirme los cambios (número de secuencia) para evitar conflictos. |
| Unirse sin crear mundo | ✅ | El anfitrión guarda con el **Save Game** del propio juego. El invitado lo abre con **Load Game** (sin generar nada) y con el inventario vacío. |
| Mobs | 🟡 | Los simula **solo el anfitrión**: parche al guion `animate` de Mob con `_RedInvitado`.<br>El invitado los ve estén donde estén: se leen de la lista `_Mob`, no de lo que hay en la pantalla del anfitrión.<br>No desaparecen si están cerca de otro jugador (se agranda `_SpawnArea`).<br>**Falta**: que persigan y hagan daño al invitado, y que el invitado pueda pegarles. |
| Inventarios | ✅ | Cada uno el suyo, local. |
| Objetos soltados | 🟡 | Se ven en todas las pantallas, pero solo los recoge quien los soltó: no se duplican, pero tampoco los coge otro. |
| Cofres | 🔴 | `_Inside` **no se sincroniza**: cada jugador ve su propio contenido, lo que permite **duplicar objetos**. |
| Vida, daño, muerte | 🟡 | Cada uno la suya. No hay PvP. Los mobs no dañan al invitado. |
| Nombres sobre los jugadores | ✅ | |
| Chat | ⬜ | El juego tiene comandos con la tecla **T** (objeto Commands), pero son solo locales. |
| Entrar, salir, desconexiones | 🟡 | Hay avisos de entrada y salida.<br>**Falta** keep-alive: expulsar a quien no responde en unos 15 s, como Minecraft. |
| Guardado compartido | ✅ | El anfitrión guarda su mundo y el servidor dedicado guarda la sala. Cada invitado guarda posición, vida e inventario con su nombre. |
| Pruebas de latencia y reconexión | 🧪 | Solo probado en el mismo PC con dos simuladores. |

En **Minecraft 2D** (nuestro juego de MicroPython) ya hay:
- mobs del anfitrión que persiguen a cualquier jugador;
- golpes de todos los jugadores a los mobs;
- PvP;
- hora sincronizada;
- partida que sigue con los menús abiertos.

## 3. Plan por fases

### Fase 1: estabilizar (en curso)
- [x] Unirse sin generar mundo; inventario vacío del invitado.
- [x] Mobs simulados solo por el anfitrión y visibles para el invitado estén donde estén.
- [x] Bloques por chunk; no mandar los cambios internos de cargar un chunk.
- [x] Teclas inyectadas (guardar con O, pausa) que el juego no llegaba a leer.
- [x] Cofres compartidos: cada cofre se manda entero cuando cambia (`c:chunk:casilla`), también el que tienes abierto.
- [x] Clima arreglado con un parche (#18) y sincronizado desde el anfitrión, junto con la hora.

### Fase 2: combate y mobs con varios jugadores (como Minecraft)
- [x] La IA usa el **jugador más cercano**: en Mob, `_x`/`_y` pasan a `_ObjX`/`_ObjY`, que rellena el bloque nuevo `scicalc_objetivo` al principio de *Process Mob*. Los mobs aparecen alrededor de cualquier jugador.
- [x] Daño a otro jugador: el bloque `scicalc_cambiar_jugador` manda la vida, el desgaste de la armadura y el empujón al jugador atacado.
- [x] El invitado pega a un mob: tiene una copia de los mobs en su `_Mob` y su propio *Hit Mob* los encuentra. El golpe (`+9`, `+18`) se le manda al anfitrión, que lo aplica si el mob no es invulnerable. Es como `EntityAttackC2SP`.
- [x] Botín para quien mata: el bloque `scicalc_soltar` (al principio de *Drop Item*) hace que, si al mob le ha pegado otro jugador en los últimos 3 s, el botín aparezca en su mundo y lo recoja él.
- [ ] Invulnerabilidad del jugador de 0.5 s (10 ticks), retroceso y PvP opcional.
- [ ] Aparición alrededor de cada jugador y desaparición respecto al más cercano. Animales persistentes.

### Fase 3: red "de verdad"
- [x] Interpolación de jugadores y mobs (se acercan poco a poco a la posición recibida).
- [ ] Mobs por eventos (aparecer / mover / quitar) y rango de seguimiento por jugador, en vez de la lista entera.
- [ ] Confirmación de bloques con número de secuencia.
- [ ] Objetos soltados como entidades del anfitrión: los recoge el primero que los toca.
- [x] Keep-alive: ping cada 5 s. El servidor echa a quien no responde en 30 s y el cliente se da por desconectado si el servidor calla 20 s.

### Fase 4: funciones online
- [x] Chat con la tecla T (LN en la calculadora; enviar con SHIFT+EXE): lo que no empieza por "/" va a todos. Se muestra abajo a la izquierda como en Minecraft y en un bocadillo encima del jugador. Mensajes de sistema: entra, sale, muere.
- [ ] Lista de jugadores.
- [x] Datos de cada jugador (posición, vida, inventario) guardados en la sala con su nombre cada 10 s y al salir (`j:<nombre>`). Al volver a entrar, sigues donde estabas.

### Supervivencia, más adelante
Experiencia, encantamientos, logros y el End no existen en v11.7. Se podrían añadir parcheando, pero son proyectos grandes. Antes conviene terminar las fases 1-3.

---
*Cómo se ha auditado:*
1. Se descompiló `proyecto.json` a texto.
2. Se revisó cada objeto (Generator, Processor, Steve, Cursor, Tiles, gui_invrow, Mob, Health, Hunger, Oxygen, Armor, snow, Save Game, Commands).
3. Se comparó con el código de red de `simulador/sd/lib/scratch_red.py`.
