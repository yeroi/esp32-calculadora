# =============================================================================
#  Genera las cabeceras de MicroPython (qstr, módulos...) y los módulos
#  congelados (manifest.py) para el firmware. Ver README.md. Uso:
#     make MICROPYTHON_TOP=/ruta/a/micropython
# =============================================================================
MICROPYTHON_TOP ?= ../../../micropython
SRC_QSTR += extmod/modjson.c extmod/modre.c extmod/modheapq.c extmod/modbinascii.c extmod/modrandom.c
SRC_QSTR += $(CURDIR)/port/scicalc_port.c $(CURDIR)/port/scicalc_gfx.c

# Módulos congelados: el intérprete de Scratch y t9 (ver manifest.py)
FROZEN_MANIFEST ?= $(CURDIR)/manifest.py
MICROPY_LONGINT_IMPL = mpz
# micropython-lib no hace falta (el manifest no lo usa)
override MPY_LIB_DIR = $(CURDIR)/port

include $(MICROPYTHON_TOP)/ports/embed/embed.mk
CFLAGS += -I$(CURDIR)

all: $(BUILD)/frozen_content.c
