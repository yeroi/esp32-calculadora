// =============================================================================
//  scicalc_port.c  —  MicroPython dentro del ESP32 SciCalc
// -----------------------------------------------------------------------------
//  * scpy_run(): arranca MicroPython con un heap propio, ejecuta el "preludio"
//    (open, os, time del sandbox, en Python) y luego el script. Los errores se
//    escriben como en el simulador:  "\x01Tipo: mensaje (línea N)".
//  * Módulo "_sc": las ÚNICAS puertas a la SD. Toda ruta pasa por
//    scpy_resolve() (no se puede salir de la SD) y toda escritura pregunta
//    al usuario (scpy_ask) ANTES de tocar nada. Por eso un script que
//    importe _sc directamente no gana nada.
//  * import desde la SD: carpeta del script y /lib.
//  * gc_collect() para Xtensa: vuelca las ventanas de registros a la pila
//    antes de buscar punteros (si no, el GC liberaría objetos vivos).
// =============================================================================
#include <string.h>
#include <stdio.h>
#include "py/builtin.h"
#include "py/compile.h"
#include "py/gc.h"
#include "py/lexer.h"
#include "py/mperrno.h"
#include "py/mphal.h"
#include "py/objstr.h"
#include "py/runtime.h"
#include "py/stackctrl.h"
#include "port/scicalc_py.h"

#define SC_PATH_MAX (256)
#define SC_CHUNK    (4000)

// ---- Salida -----------------------------------------------------------------------
void mp_hal_stdout_tx_strn_cooked(const char *str, size_t len) {
    scpy_out(str, len);
}
mp_uint_t mp_hal_stdout_tx_strn(const char *str, size_t len) {
    scpy_out(str, len);
    return len;
}
static void sc_print_strn(void *env, const char *str, size_t len) {
    (void)env;
    scpy_out(str, len);
}
static const mp_print_t sc_print = {NULL, sc_print_strn};

// micropython.kbd_intr(): aquí no hay consola serie que interrumpir
void mp_hal_set_interrupt_char(int c) {
    (void)c;
}

// ---- Utilidades -------------------------------------------------------------------
static void sc_check_pending(void) {
    mp_obj_t e = MP_STATE_MAIN_THREAD(mp_pending_exception);
    if (e != MP_OBJ_NULL) {
        MP_STATE_MAIN_THREAD(mp_pending_exception) = MP_OBJ_NULL;
        nlr_raise(e);
    }
}

// PermissionError (lo define el preludio) o, si no existe aún, OSError
static NORETURN void sc_raise_perm(const char *msg) {
    mp_obj_t arg = mp_obj_new_str(msg, strlen(msg));
    mp_obj_dict_t *d = MP_STATE_VM(mp_module_builtins_override_dict);
    if (d != NULL) {
        mp_map_elem_t *e = mp_map_lookup(&d->map, MP_OBJ_NEW_QSTR(MP_QSTR_PermissionError), MP_MAP_LOOKUP);
        if (e != NULL) {
            nlr_raise(mp_call_function_1(e->value, arg));
        }
    }
    nlr_raise(mp_obj_new_exception_arg1(&mp_type_OSError, arg));
}

static void sc_check(int r) {
    if (r < 0) {
        mp_raise_OSError(-r);
    }
}

// Ruta del script -> absoluta dentro de la SD (o PermissionError)
static const char *sc_path(mp_obj_t p, char *buf) {
    const char *s = mp_obj_str_get_str(p);
    if (scpy_resolve(s, buf, SC_PATH_MAX) != 0) {
        sc_raise_perm("acceso fuera de la SD bloqueado");
    }
    return buf;
}

static void sc_need(const char *op, const char *abs, const char *extra) {
    int ok = scpy_ask(op, abs, extra ? extra : "");
    sc_check_pending();                  // AC mientras se preguntaba
    if (!ok) {
        sc_raise_perm("permiso denegado por el usuario");
    }
}

// ---- Módulo _sc -----------------------------------------------------------------------
static mp_obj_t sc_resolve(mp_obj_t p) {
    char buf[SC_PATH_MAX];
    const char *a = sc_path(p, buf);
    return mp_obj_new_str(a, strlen(a));
}
static MP_DEFINE_CONST_FUN_OBJ_1(sc_resolve_obj, sc_resolve);

static mp_obj_t sc_stat(mp_obj_t p) {
    char buf[SC_PATH_MAX];
    uint32_t size = 0;
    int t = scpy_stat(sc_path(p, buf), &size);
    sc_check(t);
    mp_obj_t tup[2] = {MP_OBJ_NEW_SMALL_INT(t), mp_obj_new_int_from_uint(size)};
    return mp_obj_new_tuple(2, tup);
}
static MP_DEFINE_CONST_FUN_OBJ_1(sc_stat_obj, sc_stat);

static void sc_list_cb(void *ctx, const char *name, int isDir) {
    (void)isDir;
    mp_obj_list_append(MP_OBJ_FROM_PTR(ctx), mp_obj_new_str(name, strlen(name)));
}
static mp_obj_t sc_listdir(size_t n_args, const mp_obj_t *args) {
    char buf[SC_PATH_MAX];
    const char *a = sc_path(n_args ? args[0] : MP_OBJ_NEW_QSTR(MP_QSTR__dot_), buf);
    mp_obj_t list = mp_obj_new_list(0, NULL);
    sc_check(scpy_list(a, sc_list_cb, MP_OBJ_TO_PTR(list)));
    return list;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(sc_listdir_obj, 0, 1, sc_listdir);

// read(ruta, desde, n)  n < 0 = hasta el final
static mp_obj_t sc_read(mp_obj_t p, mp_obj_t off_in, mp_obj_t n_in) {
    char buf[SC_PATH_MAX];
    const char *a = sc_path(p, buf);
    uint32_t off = mp_obj_get_int(off_in);
    mp_int_t n = mp_obj_get_int(n_in);
    if (n < 0) {
        uint32_t size = 0;
        int t = scpy_stat(a, &size);
        sc_check(t);
        if (t != 1) {
            mp_raise_OSError(t == 0 ? MP_ENOENT : MP_EISDIR);
        }
        n = size > off ? size - off : 0;
    }
    vstr_t vstr;
    vstr_init_len(&vstr, n);
    size_t done = 0;
    while (done < (size_t)n) {
        size_t want = (size_t)n - done;
        if (want > SC_CHUNK) {
            want = SC_CHUNK;
        }
        int r = scpy_read(a, off + done, (uint8_t *)vstr.buf + done, want);
        sc_check(r);
        if (r == 0) {
            break;
        }
        done += r;
        sc_check_pending();
    }
    vstr.len = done;
    return mp_obj_new_bytes_from_vstr(&vstr);
}
static MP_DEFINE_CONST_FUN_OBJ_3(sc_read_obj, sc_read);

// wopen(ruta, truncar, exclusivo) -> tamaño actual. Pide permiso de escritura.
static mp_obj_t sc_wopen(mp_obj_t p, mp_obj_t trunc_in, mp_obj_t excl_in) {
    char buf[SC_PATH_MAX];
    const char *a = sc_path(p, buf);
    uint32_t size = 0;
    int t = scpy_stat(a, &size);
    sc_check(t);
    if (t == 2) {
        mp_raise_OSError(MP_EISDIR);
    }
    if (t == 1 && mp_obj_is_true(excl_in)) {
        mp_raise_OSError(MP_EEXIST);
    }
    sc_need("write", a, NULL);
    bool trunc = mp_obj_is_true(trunc_in);
    if (trunc || t == 0) {
        sc_check(scpy_write(a, 0, NULL, 0, 1));
        size = 0;
    }
    return mp_obj_new_int_from_uint(size);
}
static MP_DEFINE_CONST_FUN_OBJ_3(sc_wopen_obj, sc_wopen);

static mp_obj_t sc_write(mp_obj_t p, mp_obj_t off_in, mp_obj_t data) {
    char buf[SC_PATH_MAX];
    const char *a = sc_path(p, buf);
    mp_buffer_info_t bi;
    mp_get_buffer_raise(data, &bi, MP_BUFFER_READ);
    sc_need("write", a, NULL);           // ya concedido -> no vuelve a preguntar
    uint32_t off = mp_obj_get_int(off_in);
    size_t done = 0;
    while (done < bi.len) {
        size_t n = bi.len - done;
        if (n > SC_CHUNK) {
            n = SC_CHUNK;
        }
        int r = scpy_write(a, off + done, (const uint8_t *)bi.buf + done, n, 0);
        sc_check(r);
        done += n;
    }
    return mp_obj_new_int_from_uint(done);
}
static MP_DEFINE_CONST_FUN_OBJ_3(sc_write_obj, sc_write);

static mp_obj_t sc_remove(mp_obj_t p) {
    char buf[SC_PATH_MAX];
    const char *a = sc_path(p, buf);
    uint32_t size;
    int t = scpy_stat(a, &size);
    sc_check(t);
    if (t == 0) {
        mp_raise_OSError(MP_ENOENT);
    }
    sc_need("remove", a, NULL);
    sc_check(scpy_remove(a));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(sc_remove_obj, sc_remove);

static mp_obj_t sc_rename(mp_obj_t from, mp_obj_t to) {
    char b1[SC_PATH_MAX], b2[SC_PATH_MAX];
    const char *a = sc_path(from, b1);
    const char *b = sc_path(to, b2);
    uint32_t size;
    int t = scpy_stat(a, &size);
    sc_check(t);
    if (t == 0) {
        mp_raise_OSError(MP_ENOENT);
    }
    sc_need("rename", a, b);
    sc_check(scpy_rename(a, b));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(sc_rename_obj, sc_rename);

static mp_obj_t sc_mkdir(mp_obj_t p) {
    char buf[SC_PATH_MAX];
    const char *a = sc_path(p, buf);
    sc_need("mkdir", a, NULL);
    sc_check(scpy_mkdir(a));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(sc_mkdir_obj, sc_mkdir);

static mp_obj_t sc_rmdir(mp_obj_t p) {
    char buf[SC_PATH_MAX];
    const char *a = sc_path(p, buf);
    sc_need("rmdir", a, NULL);
    sc_check(scpy_rmdir(a));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(sc_rmdir_obj, sc_rmdir);

// Espera troceada: AC y el watchdog la cortan enseguida
static mp_obj_t sc_sleep_ms(mp_obj_t ms_in) {
    mp_int_t ms = mp_obj_get_int(ms_in);
    while (ms > 0) {
        uint32_t d = ms > 20 ? 20 : (uint32_t)ms;
        scpy_sleep_ms(d);
        ms -= d;
        sc_check_pending();
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(sc_sleep_ms_obj, sc_sleep_ms);

static mp_obj_t sc_ticks_ms(void) {
    return mp_obj_new_int_from_uint(scpy_ticks_ms() & 0x3FFFFFFF);
}
static MP_DEFINE_CONST_FUN_OBJ_0(sc_ticks_ms_obj, sc_ticks_ms);

static mp_obj_t sc_argv(void) {
    mp_obj_t list = mp_obj_new_list(0, NULL);
    for (int i = 0; i < scpy_argc(); ++i) {
        const char *s = scpy_argv(i);
        mp_obj_list_append(list, mp_obj_new_str(s, strlen(s)));
    }
    return list;
}
static MP_DEFINE_CONST_FUN_OBJ_0(sc_argv_obj, sc_argv);

static mp_obj_t sc_cwd(void) {
    char buf[SC_PATH_MAX];
    scpy_resolve(".", buf, sizeof buf);
    return mp_obj_new_str(buf, strlen(buf));
}
static MP_DEFINE_CONST_FUN_OBJ_0(sc_cwd_obj, sc_cwd);

static const mp_rom_map_elem_t sc_module_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR__sc) },
    { MP_ROM_QSTR(MP_QSTR_resolve), MP_ROM_PTR(&sc_resolve_obj) },
    { MP_ROM_QSTR(MP_QSTR_stat), MP_ROM_PTR(&sc_stat_obj) },
    { MP_ROM_QSTR(MP_QSTR_listdir), MP_ROM_PTR(&sc_listdir_obj) },
    { MP_ROM_QSTR(MP_QSTR_read), MP_ROM_PTR(&sc_read_obj) },
    { MP_ROM_QSTR(MP_QSTR_wopen), MP_ROM_PTR(&sc_wopen_obj) },
    { MP_ROM_QSTR(MP_QSTR_write), MP_ROM_PTR(&sc_write_obj) },
    { MP_ROM_QSTR(MP_QSTR_remove), MP_ROM_PTR(&sc_remove_obj) },
    { MP_ROM_QSTR(MP_QSTR_rename), MP_ROM_PTR(&sc_rename_obj) },
    { MP_ROM_QSTR(MP_QSTR_mkdir), MP_ROM_PTR(&sc_mkdir_obj) },
    { MP_ROM_QSTR(MP_QSTR_rmdir), MP_ROM_PTR(&sc_rmdir_obj) },
    { MP_ROM_QSTR(MP_QSTR_sleep_ms), MP_ROM_PTR(&sc_sleep_ms_obj) },
    { MP_ROM_QSTR(MP_QSTR_ticks_ms), MP_ROM_PTR(&sc_ticks_ms_obj) },
    { MP_ROM_QSTR(MP_QSTR_argv), MP_ROM_PTR(&sc_argv_obj) },
    { MP_ROM_QSTR(MP_QSTR_cwd), MP_ROM_PTR(&sc_cwd_obj) },
};
static MP_DEFINE_CONST_DICT(sc_module_globals, sc_module_globals_table);

const mp_obj_module_t sc_module = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&sc_module_globals,
};
MP_REGISTER_MODULE(MP_QSTR__sc, sc_module);

// ---- open() integrado: lo sustituye el del preludio -------------------------------------
mp_obj_t mp_builtin_open(size_t n_args, const mp_obj_t *args, mp_map_t *kwargs) {
    (void)n_args; (void)args; (void)kwargs;
    mp_raise_OSError(MP_EPERM);
}
MP_DEFINE_CONST_FUN_OBJ_KW(mp_builtin_open_obj, 1, mp_builtin_open);

// ---- import desde la SD -----------------------------------------------------------------
mp_import_stat_t mp_import_stat(const char *path) {
    char buf[SC_PATH_MAX];
    if (scpy_resolve(path, buf, sizeof buf) != 0) {
        return MP_IMPORT_STAT_NO_EXIST;
    }
    uint32_t size;
    int t = scpy_stat(buf, &size);
    return t == 2 ? MP_IMPORT_STAT_DIR : t == 1 ? MP_IMPORT_STAT_FILE : MP_IMPORT_STAT_NO_EXIST;
}

mp_lexer_t *mp_lexer_new_from_file(qstr filename) {
    char buf[SC_PATH_MAX];
    if (scpy_resolve(qstr_str(filename), buf, sizeof buf) != 0) {
        mp_raise_OSError(MP_EACCES);
    }
    uint32_t size = 0;
    int t = scpy_stat(buf, &size);
    sc_check(t);
    if (t != 1) {
        mp_raise_OSError(MP_ENOENT);
    }
    char *data = m_new(char, size + 1);
    size_t done = 0;
    while (done < size) {
        size_t want = size - done;
        if (want > SC_CHUNK) {
            want = SC_CHUNK;
        }
        int r = scpy_read(buf, done, (uint8_t *)data + done, want);
        if (r <= 0) {
            m_del(char, data, size + 1);
            mp_raise_OSError(r < 0 ? -r : MP_EIO);
        }
        done += r;
    }
    data[size] = 0;
    return mp_lexer_new_from_str_len(filename, data, size, size + 1);
}

// ---- GC para Xtensa (ventanas de registros) -------------------------------------------------
static void __attribute__((noinline)) sc_gc_inner(int level) {
    // Cada llamada anidada obliga a volcar una ventana de 8 registros a la pila
    if (level < 8) {
        sc_gc_inner(level + 1);
        if (level != 0) {
            return;
        }
    }
    if (level == 8) {
        volatile uintptr_t sp;
        #if defined(__xtensa__)
        __asm__ volatile ("mov %0, a1" : "=r" (sp));
        #else
        sp = (uintptr_t)__builtin_frame_address(0);
        #endif
        gc_collect_root((void **)sp, ((uintptr_t)MP_STATE_THREAD(stack_top) - sp) / sizeof(void *));
    }
}

void gc_collect(void) {
    gc_collect_start();
    sc_gc_inner(0);
    gc_collect_end();
}

void nlr_jump_fail(void *val) {
    (void)val;
    scpy_fatal("nlr_jump_fail");
    for (;;) {
    }
}

// ---- Preludio: open(), os y time del sandbox (en Python) ---------------------------------------
static const char sc_prelude[] =
    "import sys, builtins, _sc\n"
    "sys.path.clear()\n"
    "sys.path.extend(('', '/lib'))\n"
    "sys.argv.clear()\n"
    "sys.argv.extend(_sc.argv())\n"
    "class PermissionError(OSError):\n"
    "    pass\n"
    "builtins.PermissionError = PermissionError\n"
    "class _File:\n"
    "    def __init__(s, p, m='r'):\n"
    "        s.p = _sc.resolve(p)\n"
    "        s.b = 'b' in m\n"
    "        s.pos = 0\n"
    "        s.closed = False\n"
    "        s.c = b''\n"
    "        s.co = 0\n"
    "        s.wr = 'w' in m or 'a' in m or 'x' in m or '+' in m\n"
    "        s.rd = 'r' in m or '+' in m\n"
    "        if s.wr:\n"
    "            n = _sc.wopen(s.p, 'w' in m, 'x' in m)\n"
    "            if 'a' in m:\n"
    "                s.pos = n\n"
    "        else:\n"
    "            t = _sc.stat(s.p)[0]\n"
    "            if t == 0:\n"
    "                raise OSError(2, 'no existe: ' + p)\n"
    "            if t == 2:\n"
    "                raise OSError(21, 'es una carpeta: ' + p)\n"
    "    def _chunk(s, n):\n"
    "        if not (s.co <= s.pos < s.co + len(s.c)):\n"
    "            s.co = s.pos\n"
    "            s.c = _sc.read(s.p, s.pos, 512)\n"
    "        i = s.pos - s.co\n"
    "        return s.c[i:i + n]\n"
    "    def read(s, n=-1):\n"
    "        if not s.rd:\n"
    "            raise OSError(1, 'archivo abierto solo para escribir')\n"
    "        d = _sc.read(s.p, s.pos, -1 if n is None else n)\n"
    "        s.pos += len(d)\n"
    "        return d if s.b else d.decode()\n"
    "    def readline(s):\n"
    "        o = b''\n"
    "        while True:\n"
    "            c = s._chunk(256)\n"
    "            if not c:\n"
    "                break\n"
    "            i = c.find(b'\\n')\n"
    "            if i >= 0:\n"
    "                o += c[:i + 1]\n"
    "                s.pos += i + 1\n"
    "                break\n"
    "            o += c\n"
    "            s.pos += len(c)\n"
    "        return o if s.b else o.decode()\n"
    "    def readlines(s):\n"
    "        return [l for l in s]\n"
    "    def __iter__(s):\n"
    "        return s\n"
    "    def __next__(s):\n"
    "        l = s.readline()\n"
    "        if not l:\n"
    "            raise StopIteration\n"
    "        return l\n"
    "    def write(s, d):\n"
    "        if not s.wr:\n"
    "            raise OSError(1, 'archivo abierto solo para leer')\n"
    "        if isinstance(d, str):\n"
    "            d = d.encode()\n"
    "        n = _sc.write(s.p, s.pos, d)\n"
    "        s.pos += n\n"
    "        s.c = b''\n"
    "        return n\n"
    "    def seek(s, o, w=0):\n"
    "        s.pos = o if w == 0 else (s.pos + o if w == 1 else _sc.stat(s.p)[1] + o)\n"
    "        return s.pos\n"
    "    def tell(s):\n"
    "        return s.pos\n"
    "    def flush(s):\n"
    "        pass\n"
    "    def close(s):\n"
    "        s.closed = True\n"
    "    def __enter__(s):\n"
    "        return s\n"
    "    def __exit__(s, *a):\n"
    "        s.close()\n"
    "def _open(f, m='r', *a, **k):\n"
    "    return _File(f, m)\n"
    "builtins.open = _open\n"
    "def _split(p):\n"
    "    i = p.rfind('/') + 1\n"
    "    h = p[:i]\n"
    "    if h and h != '/' * len(h):\n"
    "        h = h.rstrip('/')\n"
    "    return h, p[i:]\n"
    "def _join(a, *r):\n"
    "    for b in r:\n"
    "        if b.startswith('/'):\n"
    "            a = b\n"
    "        elif not a or a.endswith('/'):\n"
    "            a += b\n"
    "        else:\n"
    "            a += '/' + b\n"
    "    return a\n"
    "def _splitext(p):\n"
    "    i = p.rfind('.')\n"
    "    if i <= p.rfind('/') + 1:\n"
    "        return p, ''\n"
    "    return p[:i], p[i:]\n"
    "def _stat(p):\n"
    "    t, n = _sc.stat(p)\n"
    "    if not t:\n"
    "        raise OSError(2, 'no existe: ' + p)\n"
    "    return (0x4000 if t == 2 else 0x8000, 0, 0, 0, 0, 0, n, 0, 0, 0)\n"
    "class _ospath:\n"
    "    exists = staticmethod(lambda p: _sc.stat(p)[0] != 0)\n"
    "    isfile = staticmethod(lambda p: _sc.stat(p)[0] == 1)\n"
    "    isdir = staticmethod(lambda p: _sc.stat(p)[0] == 2)\n"
    "    getsize = staticmethod(lambda p: _sc.stat(p)[1])\n"
    "    join = staticmethod(_join)\n"
    "    split = staticmethod(_split)\n"
    "    basename = staticmethod(lambda p: _split(p)[1])\n"
    "    dirname = staticmethod(lambda p: _split(p)[0])\n"
    "    splitext = staticmethod(_splitext)\n"
    "class _os:\n"
    "    sep = '/'\n"
    "    path = _ospath\n"
    "    listdir = staticmethod(lambda p='.': sorted(_sc.listdir(p)))\n"
    "    getcwd = staticmethod(_sc.cwd)\n"
    "    stat = staticmethod(_stat)\n"
    "    remove = staticmethod(_sc.remove)\n"
    "    unlink = staticmethod(_sc.remove)\n"
    "    rename = staticmethod(_sc.rename)\n"
    "    mkdir = staticmethod(_sc.mkdir)\n"
    "    rmdir = staticmethod(_sc.rmdir)\n"
    "class _time:\n"
    "    sleep = staticmethod(lambda s: _sc.sleep_ms(int(s * 1000)))\n"
    "    sleep_ms = staticmethod(_sc.sleep_ms)\n"
    "    sleep_us = staticmethod(lambda u: _sc.sleep_ms(u // 1000))\n"
    "    ticks_ms = staticmethod(_sc.ticks_ms)\n"
    "    ticks_us = staticmethod(lambda: _sc.ticks_ms() * 1000)\n"
    "    ticks_diff = staticmethod(lambda a, b: a - b)\n"
    "    ticks_add = staticmethod(lambda a, b: a + b)\n"
    "    time = staticmethod(lambda: _sc.ticks_ms() / 1000)\n"
    "    monotonic = time\n"
    "sys.modules['os'] = _os\n"
    "sys.modules['os.path'] = _ospath\n"
    "sys.modules['time'] = _time\n";

static void sc_exec_str(const char *src, size_t len, qstr name) {
    mp_lexer_t *lex = mp_lexer_new_from_str_len(name, src, len, 0);
    mp_parse_tree_t pt = mp_parse(lex, MP_PARSE_FILE_INPUT);
    mp_obj_t f = mp_compile(&pt, name, false);
    mp_call_function_0(f);
}

static void sc_run_prelude(void) {
    // En un diccionario propio: el script no ve _File, _os, etc.
    mp_obj_dict_t *main = mp_globals_get();
    mp_obj_dict_t *d = MP_OBJ_TO_PTR(mp_obj_new_dict(0));
    mp_globals_set(d);
    mp_locals_set(d);
    sc_exec_str(sc_prelude, sizeof(sc_prelude) - 1, MP_QSTR__lt_sandbox_gt_);
    mp_globals_set(main);
    mp_locals_set(main);
}

static size_t sc_heap_size;

// ---- Informe de errores (como el simulador) --------------------------------------------------
static int sc_report(mp_obj_t exc, const char *path) {
    const mp_obj_type_t *type = mp_obj_get_type(exc);
    if (mp_obj_is_subclass_fast(MP_OBJ_FROM_PTR(type), MP_OBJ_FROM_PTR(&mp_type_SystemExit))) {
        return SCPY_OK;
    }
    if (mp_obj_is_subclass_fast(MP_OBJ_FROM_PTR(type), MP_OBJ_FROM_PTR(&mp_type_KeyboardInterrupt))) {
        return SCPY_INTERRUPTED;
    }
    size_t n = 0, *v = NULL;
    mp_obj_exception_get_traceback(exc, &n, &v);
    qstr script = qstr_find_strn(path, strlen(path));
    int line = -1;
    const char *deep = NULL;
    int deepLine = 0;
    for (size_t i = 0; i + 2 < n; i += 3) {          // (archivo, línea, bloque)
        qstr f = v[i];
        if (line < 0 && f == script) {
            line = (int)v[i + 1];
        }
        const char *fs = qstr_str(f);
        if (deep == NULL && strncmp(fs, "/lib/", 5) == 0) {
            deep = fs;
            deepLine = (int)v[i + 1];
        }
    }
    scpy_out("\x01", 1);
    mp_obj_print_helper(&sc_print, exc, PRINT_EXC);
    char tail[96];
    int k = line > 0 ? snprintf(tail, sizeof tail, " (línea %d)\n", line) : snprintf(tail, sizeof tail, "\n");
    scpy_out(tail, k);
    if (deep) {
        k = snprintf(tail, sizeof tail, "\x01  falló dentro de %s, línea %d\n", deep, deepLine);
        scpy_out(tail, k);
    }
    if (mp_obj_is_subclass_fast(MP_OBJ_FROM_PTR(type), MP_OBJ_FROM_PTR(&mp_type_MemoryError))) {
        size_t total = sc_heap_size;
        k = snprintf(tail, sizeof tail, "\x03Sin memoria: Python tiene unos %u KB en esta placa.\n",
            (unsigned)(total / 1024));
        scpy_out(tail, k);
        return SCPY_NOMEM;
    }
    return SCPY_ERROR;
}

// ---- Ejecución -------------------------------------------------------------------------------
int scpy_run(const char *path, void *heap, size_t heap_size, void *stack_top, size_t stack_size) {
    volatile int result = SCPY_OK;
    sc_heap_size = heap_size;
    mp_stack_set_top(stack_top);
    mp_stack_set_limit(stack_size > 3072 ? stack_size - 3072 : stack_size / 2);
    gc_init(heap, (uint8_t *)heap + heap_size);
    mp_init();
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        sc_run_prelude();
        sc_check_pending();
        qstr q = qstr_from_str(path);
        mp_store_global(MP_QSTR___file__, MP_OBJ_NEW_QSTR(q));
        mp_lexer_t *lex = mp_lexer_new_from_file(q);
        mp_parse_tree_t pt = mp_parse(lex, MP_PARSE_FILE_INPUT);
        mp_obj_t f = mp_compile(&pt, q, false);
        mp_call_function_0(f);
        nlr_pop();
    } else {
        result = sc_report(MP_OBJ_FROM_PTR(nlr.ret_val), path);
    }
    mp_deinit();
    return result;
}

void scpy_interrupt(void) {
    mp_sched_keyboard_interrupt();
}
