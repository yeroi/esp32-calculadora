# =============================================================================
#  Navegador — páginas web en modo texto y descargas (app de ESP32 SciCalc)
# -----------------------------------------------------------------------------
#  Como los móviles de antes: el ESP32 no puede con JavaScript ni CSS, así que
#  de cada página se queda con el texto, los títulos y los enlaces. El núcleo
#  descarga (scicalc.red.web / red.descargar) y este script lo muestra.
#
#  Teclas:
#    ▲ ▼        desplazar             ◄ ►     elegir enlace
#    EXE        abrir el enlace       +       descargar lo enlazado
#    SHIFT+EXE  escribir dirección (T9: 2=abc ... 1 = . / : - _ ? = &)
#               sin punto = buscar en internet
#    DEL        atrás                 AC      salir
#  Lo que no es una página (zip, py, png...) se guarda en /descargas.
#  Necesita Wi-Fi (Ajustes > Wi-Fi). Bloqueado en modo examen.
# =============================================================================
from scicalc import pantalla as P, teclas as K, red
from t9 import T9

COLS = (P.ANCHO - 10) // 6           # caracteres por línea (fuente 6x8)
LH = 10                              # alto de línea
TOP = 14                             # debajo de la barra de dirección
FILAS = (P.ALTO - TOP - 12) // LH
FONDO, TEXTO, ENLACE, TITULO, GRIS = 0x0A0C12, 0xEEF1F5, 0x28A8FA, 0xFFAA28, 0x878E9E
INICIO = [("Buscar en internet", "buscar:"),
          ("Wikipedia (es)", "https://es.m.wikipedia.org"),
          ("MicroPython", "https://micropython.org"),
          ("micropython-lib (paquetes)", "https://github.com/micropython/micropython-lib"),
          ("Este proyecto en GitHub", "https://github.com/yeroi/esp32-calculadora")]
BLOQUES = ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section",
           "article", "header", "footer", "ul", "ol", "table", "pre", "blockquote", "hr",
           "dt", "dd", "form", "nav", "main", "aside", "figure", "title")
FUERA = ("script", "style", "noscript", "svg", "head", "template", "iframe", "select")
ENTIDADES = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": " ",
             "laquo": "«", "raquo": "»", "middot": "·", "ntilde": "ñ", "Ntilde": "Ñ",
             "aacute": "á", "eacute": "é", "iacute": "í", "oacute": "ó", "uacute": "ú",
             "uuml": "ü", "iexcl": "¡", "iquest": "¿", "copy": "©", "hellip": "…",
             "mdash": "—", "ndash": "–", "rsquo": "'", "lsquo": "'", "ldquo": '"', "rdquo": '"'}


# ---- utilidades de URL (MicroPython no trae urllib.parse) -----------------------
def unir(base, href):
    """Como urllib.parse.urljoin, lo justo para enlaces de páginas."""
    href = href.strip()
    if "://" in href[:12]:
        return href
    esquema, _, resto = base.partition("://")
    host, _, ruta = resto.partition("/")
    if href.startswith("//"):
        return esquema + ":" + href
    if href.startswith("/"):
        return esquema + "://" + host + href
    if href.startswith("?"):
        return esquema + "://" + host + "/" + ruta.split("?")[0] + href
    carpeta = ruta.split("?")[0].rsplit("/", 1)[0] if "/" in ruta else ""
    partes = (carpeta + "/" + href).split("/")
    out = []
    for i, p in enumerate(partes):
        if p == "..":
            if out:
                out.pop()
        elif p in ("", ".") and i != len(partes) - 1:
            continue
        else:
            out.append("" if p == "." else p)
    return esquema + "://" + host + "/" + "/".join(out)


def codificar(t):
    out = ""
    for b in t.encode("utf-8"):
        c = chr(b)
        out += c if (c.isalpha() and b < 128) or c.isdigit() or c in "-_.~" else "%%%02X" % b
    return out


def decodificar(t):
    out, i = bytearray(), 0
    while i < len(t):
        if t[i] == "%" and i + 3 <= len(t):
            try:
                out.append(int(t[i + 1:i + 3], 16))
                i += 3
                continue
            except ValueError:
                pass
        out.extend(t[i].encode("utf-8"))
        i += 1
    return out.decode("utf-8")


def resolver(texto):
    t = texto.strip()
    if not t:
        return None
    if "://" in t:
        return t
    if "." in t and " " not in t:
        return "https://" + t
    return "https://html.duckduckgo.com/html/?q=" + codificar(t)


def entidades(t):
    if "&" not in t:
        return t
    out, i = "", 0
    while i < len(t):
        j = t.find("&", i)
        if j < 0:
            return out + t[i:]
        k = t.find(";", j, j + 10)
        out += t[i:j]
        if k < 0:
            out += "&"
            i = j + 1
            continue
        e = t[j + 1:k]
        if e.startswith("#"):
            try:
                out += chr(int(e[2:], 16) if e[1:2] in "xX" else int(e[1:]))
            except ValueError:
                out += t[j:k + 1]
        else:
            out += ENTIDADES.get(e, t[j:k + 1])
        i = k + 1
    return out


# ---- HTML -> párrafos de palabras con su enlace -----------------------------------
def leer_html(html, base):
    """Devuelve (título, párrafos, enlaces). Párrafo: [(palabra, nº enlace|None, título?)]."""
    parrafos, enlaces = [[]], []
    titulo, fuera, enlace, cab, en_titulo = "", 0, None, False, False
    i, n = 0, len(html)
    while i < n:
        j = html.find("<", i)
        texto = html[i:j if j >= 0 else n]
        if texto and (en_titulo or not fuera):
            texto = entidades(texto)
            if en_titulo:
                titulo += texto
            else:
                for w in texto.split():
                    parrafos[-1].append((w, enlace, cab))
        if j < 0:
            break
        if html.startswith("<!--", j):                 # comentario
            k = html.find("-->", j)
            i = n if k < 0 else k + 3
            continue
        k = html.find(">", j)
        if k < 0:
            break
        tag = html[j + 1:k]
        i = k + 1
        cierra = tag.startswith("/")
        nombre = tag.lstrip("/").split(None, 1)[0].lower().rstrip("/") if tag.strip("/ ") else ""
        if nombre in FUERA:
            fuera = max(0, fuera + (-1 if cierra else 1))
            continue
        if nombre == "title":
            en_titulo = not cierra
            continue
        if nombre in BLOQUES:
            if parrafos[-1]:
                parrafos.append([])
            cab = (not cierra) and nombre in ("h1", "h2", "h3")
            if nombre == "li" and not cierra:
                parrafos[-1].append(("•", None, False))
        elif nombre == "a":
            if cierra:
                enlace = None
            else:
                href = atributo(tag, "href")
                if href and not (href.startswith("javascript:") or href.startswith("#")
                                 or href.startswith("mailto:")):
                    enlaces.append(unir(base, entidades(href)))
                    enlace = len(enlaces) - 1
        elif nombre == "img" and not cierra:
            alt = atributo(tag, "alt")
            if alt:
                parrafos[-1].append(("[" + entidades(alt)[:30] + "]", enlace, False))
    # El buscador (DuckDuckGo) pasa los enlaces por una redirección: la URL real
    for e, u in enumerate(enlaces):
        if "duckduckgo.com/l/" in u and "uddg=" in u:
            enlaces[e] = decodificar(u.split("uddg=", 1)[1].split("&", 1)[0])
    return " ".join(titulo.split()), parrafos, enlaces


def atributo(tag, nombre):
    low = tag.lower()
    i = low.find(nombre + "=")
    while i > 0 and low[i - 1] not in " \t\n":
        i = low.find(nombre + "=", i + 1)
    if i < 0:
        return None
    v = tag[i + len(nombre) + 1:].lstrip()
    if v[:1] in "\"'":
        q = v[0]
        return v[1:v.find(q, 1)] if v.find(q, 1) > 0 else v[1:]
    return v.split()[0].rstrip("/>") if v else ""


def maquetar(parrafos):
    """Párrafos -> líneas de COLS caracteres: [[(palabra, enlace, título), ...], ...]."""
    lineas = []
    for p in parrafos:
        linea, ancho = [], 0
        for w, en, cab in p:
            if len(w) > COLS:
                w = w[:COLS - 1] + "…"
            if ancho + len(w) > COLS and linea:
                lineas.append(linea)
                linea, ancho = [], 0
            linea.append((w, en, cab))
            ancho += len(w) + 1
        lineas.append(linea)
    while lineas and not lineas[-1]:
        lineas.pop()
    return lineas


# ---- la app ---------------------------------------------------------------------
class Navegador:
    def __init__(self):
        self.url, self.titulo, self.lineas, self.enlaces = "", "", [], []
        self.sel, self.scroll, self.historial = -1, 0, []
        self.peticion = None          # (número, url, guardar en historial)
        self.descarga = None          # número de petición de una descarga
        self.preguntar = None         # (url, nombre) esperando "¿descargar?"
        self.edit = None              # T9 de la barra de dirección
        self.msg, self.sucio = "", True
        self.inicio()

    def inicio(self):
        self.url, self.titulo = "", "Inicio"
        self.enlaces = [u for _, u in INICIO]
        p = [[("Navegador", None, True), ("SciCalc", None, True)], []]
        for i, (t, _) in enumerate(INICIO):
            p.append([("•", None, False)] + [(w, i, False) for w in t.split()])
        p += [[], [(w, None, False) for w in
                   "SHIFT+EXE: escribir una dirección o buscar. + descarga. DEL: atrás.".split()]]
        self.lineas, self.sel, self.scroll = maquetar(p), -1, 0
        self.sucio = True

    def abrir(self, url, guardar=True):
        if url == "buscar:":
            self.edit = T9("", "url")
            self.sucio = True
            return
        self.peticion = (red.web(url), url, guardar)
        self.msg = "Cargando " + url
        self.sucio = True

    def recibir(self, r):
        _, url, guardar = self.peticion
        self.peticion = None
        if not isinstance(r, dict) or "error" in r:
            self.msg = "No se pudo abrir: " + str(r.get("error") if isinstance(r, dict) else r)
            return
        if r.get("descarga"):                      # no es una página
            self.preguntar = (r["url"], r.get("nombre", "descarga"), r.get("largo", 0))
            self.msg = ""
            return
        if guardar:
            self.historial.append(self.url)
        self.url, self.msg = r["url"], ""
        if r.get("tipo") == "text/plain":
            self.titulo, self.enlaces = r["url"].rsplit("/", 1)[-1], []
            self.lineas = maquetar([[(w, None, False) for w in l.split()] for l in r["texto"].split("\n")])
        else:
            t, parr, self.enlaces = leer_html(r["texto"], r["url"])
            self.titulo, self.lineas = t or r["url"], maquetar(parr)
        self.sel, self.scroll = -1, 0

    def enlaces_visibles(self):
        out = []
        for linea in self.lineas[self.scroll:self.scroll + FILAS]:
            for _, en, _ in linea:
                if en is not None and en not in out:
                    out.append(en)
        return out

    def tecla(self, k, shift):
        self.sucio = True
        if self.edit:
            r = self.edit.tecla(k, shift)
            if r == "ok":
                url = resolver(self.edit.texto)
                self.edit = None
                if url:
                    self.abrir(url)
            elif r == "cancelar":
                self.edit = None
            return
        if self.preguntar:
            if k == "EXE":
                url, nombre, _ = self.preguntar
                self.descarga = red.descargar(url, nombre)
                self.msg = "Descargando " + nombre
            self.preguntar = None
            return
        if shift and k == "EXE":
            self.edit = T9(self.url, "url")
            return
        if self.peticion or self.descarga:
            return
        self.msg = ""
        if k == "UP":
            self.scroll = max(0, self.scroll - 1)
        elif k == "DOWN":
            self.scroll = max(0, min(len(self.lineas) - FILAS, self.scroll + 1))
        elif k in ("LEFT", "RIGHT"):
            en = self.enlaces_visibles()
            if not en:
                return
            if self.sel not in en:
                self.sel = en[0] if k == "RIGHT" else en[-1]
                return
            i = en.index(self.sel) + (1 if k == "RIGHT" else -1)
            if 0 <= i < len(en):
                self.sel = en[i]
            elif k == "RIGHT" and self.scroll + FILAS < len(self.lineas):
                self.scroll = min(len(self.lineas) - FILAS, self.scroll + FILAS - 1)
                sig = [e for e in self.enlaces_visibles() if e > self.sel]
                if sig:
                    self.sel = sig[0]
        elif k == "EXE" and 0 <= self.sel < len(self.enlaces):
            self.abrir(self.enlaces[self.sel])
        elif k == "ADD" and 0 <= self.sel < len(self.enlaces):
            u = self.enlaces[self.sel]
            self.preguntar = (u, decodificar(u.split("?")[0].rstrip("/").rsplit("/", 1)[-1]) or "descarga", 0)
        elif k == "DEL":
            if self.historial:
                u = self.historial.pop()
                if u:
                    self.abrir(u, guardar=False)
                else:
                    self.inicio()

    def paso(self):
        if self.peticion:
            r = red.respuesta(self.peticion[0])
            if r is not None:
                self.recibir(r)
                self.sucio = True
        if self.descarga:
            r = red.respuesta(self.descarga)
            if r is not None:
                self.descarga = None
                self.msg = ("Guardado en %s (%d KB)" % (r["ruta"], r["bytes"] // 1024)) if r.get("ok") \
                    else "Descarga fallida: " + str(r.get("error"))
                self.sucio = True
        if self.edit and self.edit.ultima is not None:
            self.sucio = True                       # el cursor cambia al fijarse la letra

    # ---- dibujo -------------------------------------------------------------------
    def dibujar(self):
        if not self.sucio:
            return
        self.sucio = False
        P.limpiar(FONDO)
        barra = self.edit.mostrar() if self.edit else (self.url or "inicio · SHIFT+EXE dirección")
        P.rect(0, 0, P.ANCHO, 12, 0x28A8FA if self.edit else 0x1E222C)
        P.texto(barra[-COLS:], 3, 2, 0xFFFFFF)
        if self.edit:
            ayuda = ["2abc 3def 4ghi 5jkl 6mno 7pqrs 8tuv 9wxyz", "1 = . / : - _ ? = &   0 = espacio",
                     "repite la tecla para otra letra", "SHIFT+tecla: mayúscula   . = punto",
                     "", "Sin punto: buscar en internet", "EXE ir   DEL borrar"]
            for i, l in enumerate(ayuda):
                P.texto(l, 6, TOP + 6 + i * LH, GRIS)
            return
        y = TOP
        for linea in self.lineas[self.scroll:self.scroll + FILAS]:
            x = 4
            for w, en, cab in linea:
                col = TITULO if cab and en is None else (ENLACE if en is not None else TEXTO)
                if en is not None and en == self.sel:
                    P.rect(x - 1, y - 1, len(w) * 6 + 2, LH, ENLACE)
                    col = 0xFFFFFF
                P.texto(w, x, y, col)
                x += (len(w) + 1) * 6
            y += LH
        if len(self.lineas) > FILAS:                 # barra de desplazamiento
            h = P.ALTO - TOP - 12
            P.rect(P.ANCHO - 3, TOP, 2, h, 0x1E222C)
            P.rect(P.ANCHO - 3, TOP + h * self.scroll // len(self.lineas), 2,
                   max(6, h * FILAS // len(self.lineas)), ENLACE)
        if self.preguntar:
            url, nombre, largo = self.preguntar
            P.rect(30, 70, 260, 60, 0x1E222C)
            P.marco(30, 70, 260, 60, ENLACE)
            P.texto("Descargar a /descargas:", 38, 78, ENLACE)
            P.texto(nombre[:40], 38, 92, 0xFFFFFF)
            if largo:
                P.texto("%d KB" % (largo // 1024), 38, 104, GRIS)
            P.texto("EXE sí   otra tecla no", 38, 116, GRIS)
        pie = self.msg or "▲▼ mover  ◄► enlace  EXE abrir  + bajar  DEL atrás"
        P.rect(0, P.ALTO - 11, P.ANCHO, 11, 0x1E222C)
        P.texto(pie[:COLS], 3, P.ALTO - 10, 0xFFAA28 if self.msg else GRIS)


def main():
    nav = Navegador()
    while True:                                     # AC (sistema) cierra la app
        for k, shift in K.eventos():
            nav.tecla(k, shift)
        nav.paso()
        nav.dibujar()
        P.mostrar()


main()
