// Funciones de la "plataforma" que necesita MicroPython (port/scicalc_port.c)
#include <stdint.h>
#include <stddef.h>
uint32_t scpy_ticks_ms(void);
#define mp_hal_ticks_ms()        scpy_ticks_ms()
#define mp_hal_ticks_cpu()       (0)
#define mp_hal_pin_obj_t
void mp_hal_set_interrupt_char(int c);   // micropython.kbd_intr() (no hace nada)
