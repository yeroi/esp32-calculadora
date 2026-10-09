# Módulos que van YA COMPILADOS dentro del firmware (en la flash): no se
# compilan en la placa ni ocupan RAM de Python. Se importan antes que los de
# /lib de la SD (sys.path = ['', '.frozen', '/lib']).
freeze("../../simulador/sd/lib", ("scratch.py", "scratch_red.py", "t9.py"))
