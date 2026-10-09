# permisos.py - DEMO DE PERMISOS
# Leer es libre. Escribir, borrar o renombrar te lo PREGUNTA la calculadora.
import os

print("Archivos en esta carpeta:", os.listdir("."))

with open("notas.txt", "w") as f:          # -> pide permiso
    f.write("Hola desde el sandbox\n")
print("1) notas.txt escrito")

os.rename("notas.txt", "notas_old.txt")     # -> pide permiso
print("2) renombrado a notas_old.txt")

os.remove("notas_old.txt")                  # -> pide permiso
print("3) borrado")

try:
    import subprocess
except ImportError as e:
    print("4) subprocess ->", e)

try:
    open("../../secreto.txt").read()
except Exception as e:
    print("5) salir de la SD ->", e)
