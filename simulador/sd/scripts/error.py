# error.py - DEMO DE EXCEPCIONES
# El error se muestra con su numero de linea y la
# calculadora sigue funcionando.
def dividir(a, b):
    return a / b

print("10 / 2 =", dividir(10, 2))
print("10 / 0 =", dividir(10, 0))
