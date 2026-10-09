// =============================================================================
//  scicalc_gfx.c  —  Módulo "scicalc" (pantalla y teclas) para los juegos
// -----------------------------------------------------------------------------
//  La misma API que el simulador (docs/API_scicalc.md):
//      from scicalc import pantalla as P, teclas as K
//      P.limpiar(c)  P.rect(x,y,w,h,c)  P.marco  P.linea  P.texto
//      P.sprite(ruta) -> Sprite (.ancho, .alto)
//      P.dibujar(spr, x, y, escala=1, espejo=False, angulo=0, centro=None)
//      P.recorte(x, y, w, h) / P.recorte()   P.mostrar()
//      K.pulsadas()  K.pulsada(nombre)  K.eventos()  K.ms()
//  El dibujo no se hace aquí: se apunta (scpy_gfx_*) y lo pinta la UI
//  (PyGfx.cpp). mostrar() espera a que esté pintado y mantiene vivo el
//  watchdog. "red" (multijugador) aún no existe en el ESP32: el script lo
//  sabe porque "from scicalc import red" da ImportError.
// =============================================================================
#include <string.h>
#include "py/objstr.h"
#include "py/runtime.h"
#include "port/scicalc_py.h"

void sc_pending(void);                       // scicalc_port.c

// Nombres de las teclas en el orden del enum Key del firmware (Keyboard.h)
static const char *const sc_key_names[] = {
    "", "SHIFT", "MENU", "UP", "DOWN", "LEFT", "RIGHT", "DEL", "AC",
    "SIN", "COS", "TAN", "POW", "LN", "SQRT", "LP", "RP",
    "7", "8", "9", "DIV", "4", "5", "6", "MUL", "1", "2", "3", "SUB", "0", ".", "EXE", "ADD",
};
#define SC_NKEYS (sizeof(sc_key_names) / sizeof(sc_key_names[0]))

// ---- Utilidades ------------------------------------------------------------------------
static void sc_gfx_on(void) {
    if (scpy_gfx_begin() != 0) {
        mp_raise_msg(&mp_type_MemoryError, MP_ERROR_TEXT("sin memoria para la pantalla"));
    }
}

// Como int() del simulador: acepta float (trunca) y bool
static mp_int_t sc_int(mp_obj_t o) {
    if (mp_obj_is_float(o)) {
        mp_float_t f = mp_obj_get_float(o);
        if (f > 30000) return 30000;
        if (f < -30000) return -30000;
        return (mp_int_t)f;
    }
    return mp_obj_get_int(o);
}

static uint32_t sc_col(mp_obj_t o) {
    return (uint32_t)sc_int(o) & 0xFFFFFF;
}

// ---- Sprite ---------------------------------------------------------------------------
typedef struct {
    mp_obj_base_t base;
    mp_int_t id, w, h;
} sc_sprite_t;

static void sc_sprite_attr(mp_obj_t self_in, qstr attr, mp_obj_t *dest) {
    if (dest[0] != MP_OBJ_NULL) {
        return;                              // solo lectura
    }
    sc_sprite_t *s = MP_OBJ_TO_PTR(self_in);
    if (attr == MP_QSTR_ancho) {
        dest[0] = MP_OBJ_NEW_SMALL_INT(s->w);
    } else if (attr == MP_QSTR_alto) {
        dest[0] = MP_OBJ_NEW_SMALL_INT(s->h);
    } else if (attr == MP_QSTR_id) {
        dest[0] = MP_OBJ_NEW_SMALL_INT(s->id);
    }
}

static MP_DEFINE_CONST_OBJ_TYPE(
    sc_sprite_type, MP_QSTR_Sprite, MP_TYPE_FLAG_NONE,
    attr, sc_sprite_attr
    );

// Sprites ya cargados (ruta -> Sprite): cargar dos veces el mismo no repite nada
MP_REGISTER_ROOT_POINTER(mp_obj_t scicalc_sprites);

void sc_gfx_reset(void) {
    MP_STATE_VM(scicalc_sprites) = MP_OBJ_NULL;   // cada script empieza de cero
}

// ---- pantalla -------------------------------------------------------------------------
static mp_obj_t p_color(mp_obj_t r, mp_obj_t g, mp_obj_t b) {
    return MP_OBJ_NEW_SMALL_INT((sc_int(r) & 255) << 16 | (sc_int(g) & 255) << 8 | (sc_int(b) & 255));
}
static MP_DEFINE_CONST_FUN_OBJ_3(p_color_obj, p_color);

static mp_obj_t p_limpiar(size_t n, const mp_obj_t *a) {
    sc_gfx_on();
    scpy_gfx_shape(0, 0, 0, 0, 0, n ? sc_col(a[0]) : 0);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(p_limpiar_obj, 0, 1, p_limpiar);

static mp_obj_t sc_shape(int kind, const mp_obj_t *a) {
    sc_gfx_on();
    scpy_gfx_shape(kind, sc_int(a[0]), sc_int(a[1]), sc_int(a[2]), sc_int(a[3]), sc_col(a[4]));
    return mp_const_none;
}
static mp_obj_t p_rect(size_t n, const mp_obj_t *a) { (void)n; return sc_shape(1, a); }
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(p_rect_obj, 5, 5, p_rect);
static mp_obj_t p_marco(size_t n, const mp_obj_t *a) { (void)n; return sc_shape(2, a); }
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(p_marco_obj, 5, 5, p_marco);
static mp_obj_t p_linea(size_t n, const mp_obj_t *a) { (void)n; return sc_shape(3, a); }
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(p_linea_obj, 5, 5, p_linea);

// texto(t, x, y, c=BLANCO, fondo=None, tam=1)
static mp_obj_t p_texto(size_t n, const mp_obj_t *pos, mp_map_t *kw) {
    enum { A_T, A_X, A_Y, A_C, A_FONDO, A_TAM };
    static const mp_arg_t allowed[] = {
        { MP_QSTR_t, MP_ARG_REQUIRED | MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL} },
        { MP_QSTR_x, MP_ARG_REQUIRED | MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL} },
        { MP_QSTR_y, MP_ARG_REQUIRED | MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL} },
        { MP_QSTR_c, MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL} },
        { MP_QSTR_fondo, MP_ARG_OBJ, {.u_obj = mp_const_none} },
        { MP_QSTR_tam, MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL} },
    };
    mp_arg_val_t v[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all(n, pos, kw, MP_ARRAY_SIZE(allowed), allowed, v);
    sc_gfx_on();
    mp_obj_t t = v[A_T].u_obj;
    if (!mp_obj_is_str(t)) {
        t = mp_call_function_1(MP_OBJ_FROM_PTR(&mp_type_str), t);
    }
    size_t len;
    const char *s = mp_obj_str_get_data(t, &len);
    if (len > 240) {
        len = 240;                           // ~80 caracteres, como el simulador
    }
    uint32_t fg = v[A_C].u_obj == MP_OBJ_NULL ? 0xFFFFFF : sc_col(v[A_C].u_obj);
    int32_t bg = v[A_FONDO].u_obj == mp_const_none ? -1 : (int32_t)sc_col(v[A_FONDO].u_obj);
    int tam = v[A_TAM].u_obj == MP_OBJ_NULL ? 1 : sc_int(v[A_TAM].u_obj);
    scpy_gfx_text(s, len, sc_int(v[A_X].u_obj), sc_int(v[A_Y].u_obj), fg, bg, tam);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_KW(p_texto_obj, 3, p_texto);

// sprite(ruta): solo PNG; el tamaño se lee de la cabecera
static mp_obj_t p_sprite(mp_obj_t ruta) {
    sc_gfx_on();
    if (MP_STATE_VM(scicalc_sprites) == MP_OBJ_NULL) {
        MP_STATE_VM(scicalc_sprites) = mp_obj_new_dict(0);
    }
    char abs[256];
    if (scpy_resolve(mp_obj_str_get_str(ruta), abs, sizeof abs) != 0) {
        mp_raise_OSError(13);
    }
    mp_obj_t key = mp_obj_new_str(abs, strlen(abs));
    mp_map_elem_t *e = mp_map_lookup(mp_obj_dict_get_map(MP_STATE_VM(scicalc_sprites)), key, MP_MAP_LOOKUP);
    if (e) {
        return e->value;
    }
    uint8_t b[24];
    int r = scpy_read(abs, 0, b, sizeof b);
    if (r < 0) {
        mp_raise_OSError(-r);
    }
    static const uint8_t sig[8] = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'};
    if (r < 24 || memcmp(b, sig, 8) != 0) {
        mp_raise_ValueError(MP_ERROR_TEXT("solo se admiten sprites PNG"));
    }
    sc_sprite_t *s = mp_obj_malloc(sc_sprite_t, &sc_sprite_type);
    s->w = (b[16] << 24) | (b[17] << 16) | (b[18] << 8) | b[19];
    s->h = (b[20] << 24) | (b[21] << 16) | (b[22] << 8) | b[23];
    s->id = scpy_gfx_sprite(abs);
    mp_obj_dict_store(MP_STATE_VM(scicalc_sprites), key, MP_OBJ_FROM_PTR(s));
    return MP_OBJ_FROM_PTR(s);
}
static MP_DEFINE_CONST_FUN_OBJ_1(p_sprite_obj, p_sprite);

// dibujar(spr, x, y, escala=1, espejo=False, angulo=0, centro=None)
static mp_obj_t p_dibujar(size_t n, const mp_obj_t *pos, mp_map_t *kw) {
    enum { A_S, A_X, A_Y, A_ESC, A_ESP, A_ANG, A_CEN };
    static const mp_arg_t allowed[] = {
        { MP_QSTR_s, MP_ARG_REQUIRED | MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL} },
        { MP_QSTR_x, MP_ARG_REQUIRED | MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL} },
        { MP_QSTR_y, MP_ARG_REQUIRED | MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL} },
        { MP_QSTR_escala, MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL} },
        { MP_QSTR_espejo, MP_ARG_OBJ, {.u_obj = mp_const_false} },
        { MP_QSTR_angulo, MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL} },
        { MP_QSTR_centro, MP_ARG_OBJ, {.u_obj = mp_const_none} },
    };
    mp_arg_val_t v[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all(n, pos, kw, MP_ARRAY_SIZE(allowed), allowed, v);
    if (!mp_obj_is_type(v[A_S].u_obj, &sc_sprite_type)) {
        mp_raise_TypeError(MP_ERROR_TEXT("dibujar necesita un sprite de pantalla.sprite()"));
    }
    sc_sprite_t *s = MP_OBJ_TO_PTR(v[A_S].u_obj);
    float sx = 1, sy = 1;
    mp_obj_t e = v[A_ESC].u_obj;
    if (e != MP_OBJ_NULL) {
        if (mp_obj_is_type(e, &mp_type_tuple) || mp_obj_is_type(e, &mp_type_list)) {
            mp_obj_t *it;
            size_t ne;
            mp_obj_get_array(e, &ne, &it);
            if (ne != 2) {
                mp_raise_ValueError(MP_ERROR_TEXT("escala: un número o (ancho, alto)"));
            }
            sx = mp_obj_get_float(it[0]);
            sy = mp_obj_get_float(it[1]);
        } else {
            sx = sy = mp_obj_get_float(e);
        }
    }
    float ang = v[A_ANG].u_obj == MP_OBJ_NULL ? 0 : mp_obj_get_float(v[A_ANG].u_obj);
    int hasC = v[A_CEN].u_obj != mp_const_none;
    float cx = 0, cy = 0;
    if (hasC) {
        mp_obj_t *it;
        size_t nc;
        mp_obj_get_array(v[A_CEN].u_obj, &nc, &it);
        if (nc != 2) {
            mp_raise_ValueError(MP_ERROR_TEXT("centro: (x, y)"));
        }
        cx = mp_obj_get_float(it[0]);
        cy = mp_obj_get_float(it[1]);
    }
    scpy_gfx_draw(s->id, mp_obj_get_float(v[A_X].u_obj), mp_obj_get_float(v[A_Y].u_obj),
        sx, sy, mp_obj_is_true(v[A_ESP].u_obj), ang, hasC, cx, cy);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_KW(p_dibujar_obj, 3, p_dibujar);

static mp_obj_t p_recorte(size_t n, const mp_obj_t *a) {
    sc_gfx_on();
    if (n == 0 || a[0] == mp_const_none) {
        scpy_gfx_clip(0, 0, -1, -1);
    } else if (n == 4) {
        scpy_gfx_clip(sc_int(a[0]), sc_int(a[1]), sc_int(a[2]), sc_int(a[3]));
    } else {
        mp_raise_TypeError(MP_ERROR_TEXT("recorte(x, y, w, h) o recorte()"));
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(p_recorte_obj, 0, 4, p_recorte);

static mp_obj_t p_mostrar(void) {
    sc_gfx_on();
    scpy_gfx_show();
    sc_pending();                            // AC / watchdog
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(p_mostrar_obj, p_mostrar);

static const mp_rom_map_elem_t p_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_pantalla) },
    { MP_ROM_QSTR(MP_QSTR_ANCHO), MP_ROM_INT(320) },
    { MP_ROM_QSTR(MP_QSTR_ALTO), MP_ROM_INT(218) },
    { MP_ROM_QSTR(MP_QSTR_NEGRO), MP_ROM_INT(0x000000) },
    { MP_ROM_QSTR(MP_QSTR_BLANCO), MP_ROM_INT(0xFFFFFF) },
    { MP_ROM_QSTR(MP_QSTR_ROJO), MP_ROM_INT(0xFF0000) },
    { MP_ROM_QSTR(MP_QSTR_VERDE), MP_ROM_INT(0x00FF00) },
    { MP_ROM_QSTR(MP_QSTR_AZUL), MP_ROM_INT(0x0000FF) },
    { MP_ROM_QSTR(MP_QSTR_AMARILLO), MP_ROM_INT(0xFFFF00) },
    { MP_ROM_QSTR(MP_QSTR_color), MP_ROM_PTR(&p_color_obj) },
    { MP_ROM_QSTR(MP_QSTR_limpiar), MP_ROM_PTR(&p_limpiar_obj) },
    { MP_ROM_QSTR(MP_QSTR_rect), MP_ROM_PTR(&p_rect_obj) },
    { MP_ROM_QSTR(MP_QSTR_marco), MP_ROM_PTR(&p_marco_obj) },
    { MP_ROM_QSTR(MP_QSTR_linea), MP_ROM_PTR(&p_linea_obj) },
    { MP_ROM_QSTR(MP_QSTR_texto), MP_ROM_PTR(&p_texto_obj) },
    { MP_ROM_QSTR(MP_QSTR_sprite), MP_ROM_PTR(&p_sprite_obj) },
    { MP_ROM_QSTR(MP_QSTR_dibujar), MP_ROM_PTR(&p_dibujar_obj) },
    { MP_ROM_QSTR(MP_QSTR_recorte), MP_ROM_PTR(&p_recorte_obj) },
    { MP_ROM_QSTR(MP_QSTR_mostrar), MP_ROM_PTR(&p_mostrar_obj) },
    { MP_ROM_QSTR(MP_QSTR_Sprite), MP_ROM_PTR(&sc_sprite_type) },
};
static MP_DEFINE_CONST_DICT(p_globals, p_globals_table);
static const mp_obj_module_t sc_pantalla_module = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&p_globals,
};

// ---- teclas ---------------------------------------------------------------------------
static mp_obj_t k_name(int k) {
    const char *s = (k > 0 && (size_t)k < SC_NKEYS) ? sc_key_names[k] : "?";
    return mp_obj_new_str(s, strlen(s));
}

static mp_obj_t k_pulsadas(void) {
    uint64_t bits = scpy_keys_held();
    mp_obj_t set = mp_obj_new_set(0, NULL);
    for (size_t k = 1; k < SC_NKEYS; ++k) {
        if (bits & (1ULL << k)) {
            mp_obj_set_store(set, k_name(k));
        }
    }
    return set;
}
static MP_DEFINE_CONST_FUN_OBJ_0(k_pulsadas_obj, k_pulsadas);

static mp_obj_t k_pulsada(mp_obj_t name) {
    const char *s = mp_obj_str_get_str(name);
    uint64_t bits = scpy_keys_held();
    for (size_t k = 1; k < SC_NKEYS; ++k) {
        if (strcmp(sc_key_names[k], s) == 0) {
            return mp_obj_new_bool(bits & (1ULL << k));
        }
    }
    return mp_const_false;
}
static MP_DEFINE_CONST_FUN_OBJ_1(k_pulsada_obj, k_pulsada);

static mp_obj_t k_eventos(void) {
    mp_obj_t list = mp_obj_new_list(0, NULL);
    int k, sh;
    while (scpy_key_event(&k, &sh)) {
        mp_obj_t t[2] = {k_name(k), mp_obj_new_bool(sh)};
        mp_obj_list_append(list, mp_obj_new_tuple(2, t));
    }
    return list;
}
static MP_DEFINE_CONST_FUN_OBJ_0(k_eventos_obj, k_eventos);

static mp_obj_t k_ms(void) {
    return mp_obj_new_int_from_uint(scpy_ticks_ms() & 0x3FFFFFFF);
}
static MP_DEFINE_CONST_FUN_OBJ_0(k_ms_obj, k_ms);

static const mp_rom_map_elem_t k_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_teclas) },
    { MP_ROM_QSTR(MP_QSTR_pulsadas), MP_ROM_PTR(&k_pulsadas_obj) },
    { MP_ROM_QSTR(MP_QSTR_pulsada), MP_ROM_PTR(&k_pulsada_obj) },
    { MP_ROM_QSTR(MP_QSTR_eventos), MP_ROM_PTR(&k_eventos_obj) },
    { MP_ROM_QSTR(MP_QSTR_ms), MP_ROM_PTR(&k_ms_obj) },
};
static MP_DEFINE_CONST_DICT(k_globals, k_globals_table);
static const mp_obj_module_t sc_teclas_module = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&k_globals,
};

// ---- scicalc ----------------------------------------------------------------------------
static const mp_rom_map_elem_t scicalc_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_scicalc) },
    { MP_ROM_QSTR(MP_QSTR_pantalla), MP_ROM_PTR(&sc_pantalla_module) },
    { MP_ROM_QSTR(MP_QSTR_teclas), MP_ROM_PTR(&sc_teclas_module) },
};
static MP_DEFINE_CONST_DICT(scicalc_globals, scicalc_globals_table);

const mp_obj_module_t scicalc_module = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&scicalc_globals,
};
MP_REGISTER_MODULE(MP_QSTR_scicalc, scicalc_module);
