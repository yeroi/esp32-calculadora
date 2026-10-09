# intento_borrar.py - DEMO DE SEGURIDAD
# Intenta hacer cosas peligrosas: el sandbox las bloquea.

try:
    import os
    os.remove("hola.py")
except Exception as e:
    print("1) import os  ->", e)

try:
    open("hola.py", "w").write("hackeado")
except Exception as e:
    print("2) escribir   ->", e)

try:
    open("../../secreto.txt").read()
except Exception as e:
    print("3) salir SD   ->", e)

print("4) leer       -> OK:", open("scripts/hola.py").readline().strip())
