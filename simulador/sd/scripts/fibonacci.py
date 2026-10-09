# fibonacci.py
a, b = 0, 1
for i in range(1, 31):
    print("F(%2d) = %d" % (i, b))
    a, b = b, a + b
