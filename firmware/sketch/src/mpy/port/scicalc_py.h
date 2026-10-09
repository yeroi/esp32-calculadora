// =============================================================================
//  scicalc_py.h  —  Puente entre MicroPython (C) y el firmware (C++)
// -----------------------------------------------------------------------------
//  scicalc_port.c (lado MicroPython) llama a las funciones scpy_* que
//  implementa PySandbox.cpp (lado firmware): salida, archivos de la SD,
//  permisos, tiempo. Todas se llaman desde la TAREA del script.
// =============================================================================
#ifndef SCICALC_PY_H
#define SCICALC_PY_H
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// ---- Lo da MicroPython (scicalc_port.c) --------------------------------------
enum { SCPY_OK = 0, SCPY_ERROR = 1, SCPY_INTERRUPTED = 2, SCPY_NOMEM = 3 };
// Ejecuta el script 'path' (ruta absoluta en la SD). Bloquea hasta que acaba.
int  scpy_run(const char* path, void* heap, size_t heapSize, void* stackTop, size_t stackSize);
// Pide parar el script (KeyboardInterrupt). Se puede llamar desde otra tarea.
void scpy_interrupt(void);

// ---- Lo da el firmware (PySandbox.cpp) ------------------------------------------
void scpy_out(const char* s, size_t n);                        // salida de print()
// Ruta del script -> absoluta y normalizada dentro de la SD. 0 o -EACCES.
int  scpy_resolve(const char* in, char* out, size_t cap);
int  scpy_stat(const char* abs, uint32_t* size);               // 0 no, 1 archivo, 2 carpeta, <0 error
int  scpy_read(const char* abs, uint32_t off, uint8_t* buf, size_t n);   // bytes o -errno
typedef void (*scpy_list_cb)(void* ctx, const char* name, int isDir);
int  scpy_list(const char* abs, scpy_list_cb cb, void* ctx);    // nº de entradas o -errno
int  scpy_write(const char* abs, uint32_t off, const uint8_t* d, size_t n, int trunc);
int  scpy_remove(const char* abs);
int  scpy_rename(const char* from, const char* to);
int  scpy_mkdir(const char* abs);
int  scpy_rmdir(const char* abs);
// Pregunta al usuario (diálogo). op: write/remove/rename/mkdir/rmdir. 1 = sí.
int  scpy_ask(const char* op, const char* abs, const char* extra);
uint32_t scpy_ticks_ms(void);
void scpy_sleep_ms(uint32_t ms);
int  scpy_argc(void);
const char* scpy_argv(int i);
uint32_t scpy_random_seed(void);
void scpy_fatal(const char* why);

#ifdef __cplusplus
}
#endif
#endif
