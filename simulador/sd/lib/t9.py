# =============================================================================
#  t9.py — escribir texto con el teclado numérico, como en un móvil Nokia
# -----------------------------------------------------------------------------
#  2 = a b c 2, 3 = d e f 3 ... 9 = w x y z 9, 0 = espacio 0, 1 = signos.
#  Pulsar varias veces la misma tecla cambia la letra; otra tecla, ► o esperar
#  un segundo la deja puesta. SHIFT+tecla: mayúscula. La tecla "." escribe un
#  punto. DEL borra, EXE acepta, AC sale del script (lo reserva el sistema).
#
#      from t9 import T9
#      t = T9("hola")                 # modo "texto"; también "url" y "numero"
#      r = t.tecla(nombre, shift)     # 'ok', 'cancelar' (DEL con todo borrado) o None
#      t.texto, t.mostrar()
# =============================================================================
from scicalc import teclas as K

LETRAS = {"1": ".,-_!?1", "2": "abc2", "3": "def3", "4": "ghi4", "5": "jkl5", "6": "mno6",
          "7": "pqrs7", "8": "tuv8", "9": "wxyz9", "0": " 0"}
LETRAS_URL = {"1": "./:-_?=&1"}
ESPERA = 1000                        # ms para que la letra se quede puesta


class T9:
    def __init__(self, texto="", modo="texto", maximo=200):
        self.texto, self.modo, self.maximo = texto, modo, maximo
        self.ultima, self.t, self.i = None, 0, 0

    def tecla(self, k, shift=False):
        ahora = K.ms()
        if k == "EXE":
            return "ok"
        if k == "DEL":
            if not self.texto:
                return "cancelar"
            self.texto, self.ultima = self.texto[:-1], None
            return None
        if k == "RIGHT":
            self.ultima = None
            return None
        if len(self.texto) >= self.maximo and k != self.ultima:
            return None
        if k == ".":
            self.texto += "."
            self.ultima = None
            return None
        if self.modo == "numero":
            if k.isdigit():
                self.texto += k
            return None
        if k not in LETRAS:
            return None
        letras = LETRAS_URL.get(k, LETRAS[k]) if self.modo == "url" else LETRAS[k]
        if k == self.ultima and ahora - self.t < ESPERA and self.texto:
            self.i = (self.i + 1) % len(letras)          # misma tecla: siguiente letra
            self.texto = self.texto[:-1]
        else:
            self.i = 0
        c = letras[self.i]
        if shift or (self.modo == "texto" and not self.texto):
            c = c.upper()
        self.texto += c
        self.ultima, self.t = k, ahora
        return None

    def pendiente(self):
        """True mientras la última letra aún puede cambiar (se dibuja distinta)."""
        return self.ultima is not None and K.ms() - self.t < ESPERA

    def mostrar(self):
        return self.texto + ("" if self.pendiente() else "_")
