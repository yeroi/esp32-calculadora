# ecuacion2.py - resuelve ax^2 + bx + c = 0
# Consola:  python ecuacion2.py 1 -3 2
import sys, cmath

a, b, c = (float(v) for v in (sys.argv[1:4] if len(sys.argv) >= 4 else ("1", "-3", "2")))
d = cmath.sqrt(b * b - 4 * a * c)
print("x1 =", (-b + d) / (2 * a))
print("x2 =", (-b - d) / (2 * a))
