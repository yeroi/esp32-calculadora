// =============================================================================
//  mpconfigport.h  —  Configuración de MicroPython para ESP32 SciCalc
// -----------------------------------------------------------------------------
//  Sandbox: solo lo que un script de calculadora necesita. NO hay os/machine/
//  socket/VFS de MicroPython: el acceso a la SD pasa por el módulo propio
//  "_sc" (port/scicalc_port.c), que aplica las reglas del sandbox (rutas
//  dentro de la SD y permiso antes de escribir).
// =============================================================================
#include <stdint.h>
#include <alloca.h>

typedef intptr_t mp_int_t;
typedef uintptr_t mp_uint_t;
typedef long mp_off_t;

#define MICROPY_MPHALPORT_H                 "../port/mphalport.h"
#define MP_SSIZE_MAX                        (0x7fffffff)
// El ESP32 usa la ABI "windowed" de Xtensa: el NLR debe ir con setjmp
// (como el port oficial de MicroPython para ESP32)
#define MICROPY_NLR_SETJMP                  (1)
#define MICROPY_STACK_CHECK_MARGIN          (1024)
#define MICROPY_CONFIG_ROM_LEVEL            (MICROPY_CONFIG_ROM_LEVEL_EXTRA_FEATURES)

// ---- Núcleo ------------------------------------------------------------------
#define MICROPY_ENABLE_COMPILER             (1)
#define MICROPY_ENABLE_GC                   (1)
#define MICROPY_PY_GC                       (1)
#define MICROPY_HELPER_REPL                 (0)
#define MICROPY_ENABLE_EXTERNAL_IMPORT      (1)     // import desde la SD (/lib y la carpeta del script)
#define MICROPY_READER_POSIX                (0)
#define MICROPY_READER_VFS                  (0)
#define MICROPY_KBD_EXCEPTION               (1)     // AC y el watchdog paran el script
#define MICROPY_STACK_CHECK                 (1)     // recursión infinita -> RuntimeError
#define MICROPY_CAN_OVERRIDE_BUILTINS       (1)     // open() del sandbox
#define MICROPY_LONGINT_IMPL                (MICROPY_LONGINT_IMPL_MPZ)
#define MICROPY_FLOAT_IMPL                  (MICROPY_FLOAT_IMPL_DOUBLE)   // como la calculadora
#define MICROPY_ERROR_REPORTING             (MICROPY_ERROR_REPORTING_NORMAL)
#define MICROPY_ENABLE_SOURCE_LINE          (1)     // número de línea en los errores
#define MICROPY_WARNINGS                    (0)
#define MICROPY_ROM_TEXT_COMPRESSION        (0)
#define MICROPY_PY_SYS_PLATFORM             "esp32"
#define MICROPY_HW_BOARD_NAME               "ESP32 SciCalc"
#define MICROPY_HW_MCU_NAME                 "ESP32"
#define MICROPY_ALLOC_PATH_MAX              (256)

// ---- Lo que NO hay en el sandbox -----------------------------------------------
#define MICROPY_PY_BUILTINS_INPUT           (0)
#define MICROPY_PY_BUILTINS_EVAL_EXEC       (0)
#define MICROPY_PY_BUILTINS_COMPILE         (0)
#define MICROPY_PY_BUILTINS_EXECFILE        (0)
#define MICROPY_PY_BUILTINS_HELP            (0)
#define MICROPY_PY_SYS_STDFILES             (0)
#define MICROPY_PY_SYS_STDIO_BUFFER         (0)
#define MICROPY_PY_SYS_PS1_PS2              (0)
#define MICROPY_PY_SYS_EXC_INFO             (0)
#define MICROPY_PY_SELECT                   (0)
#define MICROPY_PY_TIME                     (0)     // "time" lo da el sandbox
#define MICROPY_PY_OS                       (0)     // "os" lo da el sandbox
#define MICROPY_PY_ASYNCIO                  (0)
#define MICROPY_PY_UCTYPES                  (0)
#define MICROPY_PY_DEFLATE                  (0)
#define MICROPY_PY_HASHLIB                  (0)
#define MICROPY_PY_CRYPTOLIB                (0)
#define MICROPY_PY_FRAMEBUF                 (0)
#define MICROPY_PY_PLATFORM                 (0)
#define MICROPY_PY_MACHINE                  (0)
#define MICROPY_PY_NETWORK                  (0)
#define MICROPY_PY_SOCKET                   (0)
#define MICROPY_PY_SSL                      (0)
#define MICROPY_PY_WEBSOCKET                (0)
#define MICROPY_PY_ONEWIRE                  (0)
#define MICROPY_PY_BLUETOOTH                (0)
#define MICROPY_PY_BTREE                    (0)
#define MICROPY_PY_THREAD                   (0)
#define MICROPY_VFS                         (0)

// ---- Módulos disponibles ---------------------------------------------------------
#define MICROPY_PY_MATH                     (1)
#define MICROPY_PY_MATH_SPECIAL_FUNCTIONS   (1)
#define MICROPY_PY_MATH_FACTORIAL           (1)
#define MICROPY_PY_MATH_ISCLOSE             (1)
#define MICROPY_PY_CMATH                    (1)
#define MICROPY_PY_IO                       (1)     // io.StringIO / BytesIO
#define MICROPY_PY_JSON                     (1)
#define MICROPY_PY_RE                       (1)
#define MICROPY_PY_HEAPQ                    (1)
#define MICROPY_PY_BINASCII                 (1)
#define MICROPY_PY_RANDOM                   (1)
#define MICROPY_PY_RANDOM_EXTRA_FUNCS       (1)
#define MICROPY_PY_ERRNO                    (1)
#define MICROPY_PY_STRUCT                   (1)
#define MICROPY_PY_ARRAY                    (1)
#define MICROPY_PY_COLLECTIONS              (1)
#define MICROPY_PY_COLLECTIONS_DEQUE        (1)
#define MICROPY_PY_COLLECTIONS_ORDEREDDICT  (1)

// ---- Código ya compilado ------------------------------------------------------------
// Módulos congelados en la flash (frozen_content.c, ver Makefile): el
// intérprete de Scratch (scratch, scratch_red) y t9. No se compilan en la
// placa ni ocupan RAM de Python. Y juego.mpy junto a juego.py (mpy-cross).
#ifndef MICROPY_MODULE_FROZEN_MPY                   // (make ya los define al generar)
#define MICROPY_MODULE_FROZEN_MPY           (1)
#endif
#ifndef MICROPY_QSTR_EXTRA_POOL
#define MICROPY_QSTR_EXTRA_POOL             mp_qstr_frozen_const_pool
#endif
#define MICROPY_PERSISTENT_CODE_LOAD        (1)

// Semilla de random: generador por hardware del ESP32
uint32_t scpy_random_seed(void);
#define MICROPY_PY_RANDOM_SEED_INIT_FUNC    (scpy_random_seed())
