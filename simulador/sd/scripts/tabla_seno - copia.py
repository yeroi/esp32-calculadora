# tabla_seno.py - tabla trigonometrica con barras
import math

print(" grados   seno     grafica")
for g in range(0, 181, 15):
    s = math.sin(math.radians(g))
    print("%5d   %6.3f   %s" % (g, s, "#" * int(s * 20)))
