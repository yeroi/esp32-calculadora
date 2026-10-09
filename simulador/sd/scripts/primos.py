# primos.py - criba de Eratostenes
def primos(limite):
    es_primo = [True] * (limite + 1)
    es_primo[0] = es_primo[1] = False
    for i in range(2, int(limite ** 0.5) + 1):
        if es_primo[i]:
            for j in range(i * i, limite + 1, i):
                es_primo[j] = False
    return [n for n, p in enumerate(es_primo) if p]

p = primos(200)
print(len(p), "primos menores que 200:")
for i in range(0, len(p), 10):
    print(" ".join("%3d" % x for x in p[i:i + 10]))
