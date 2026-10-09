# derivada.py - derivada numérica
# Úsalo desde la Consola con argumentos:   python derivada.py 2
import sys, math

x = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
f = lambda t: t ** 3 - 2 * t
h = 1e-6
print("f(x) = x^3 - 2x")
print("f'(%g) = %.6f" % (x, (f(x + h) - f(x - h)) / (2 * h)))
