# =============================================================================
#  Genera las cabeceras de MicroPython (qstr, módulos...) para el firmware.
#  Ver README.md. Uso:  make MICROPYTHON_TOP=/ruta/a/micropython
# =============================================================================
MICROPYTHON_TOP ?= ../../../micropython
SRC_QSTR += extmod/modjson.c extmod/modre.c extmod/modheapq.c extmod/modbinascii.c extmod/modrandom.c
SRC_QSTR += $(CURDIR)/port/scicalc_port.c
include $(MICROPYTHON_TOP)/ports/embed/embed.mk
CFLAGS += -I$(CURDIR)
