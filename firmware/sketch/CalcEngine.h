// =============================================================================
//  CalcEngine.h  —  Motor matemático de la calculadora (Paso 4)
// -----------------------------------------------------------------------------
//  Traducción directa de tokenize() / Parser / fmt_number() de scicalc_sim.py:
//  mismo comportamiento, mismos errores ("Syntax ERROR" / "Math ERROR").
//
//  Gramática (descenso recursivo):
//    expr    := term (('+'|'−') term)*
//    term    := unary (('×'|'÷'|implícita) unary)*
//    unary   := ('−'|'+') unary | power
//    power   := postfix ('^' unary)?
//    postfix := primary ('²'|'!')*
//    primary := número | constante | func '(' expr ')' | '(' expr ')'
//  Los paréntesis finales se pueden omitir (como en las Casio).
// =============================================================================
#pragma once
#include <Arduino.h>

namespace Calc {

enum class Err : uint8_t { None, Syntax, Math };

// Evalúa la expresión UTF-8 (con ×, ÷, −, π, √, ², Ans...). Devuelve Err::None
// y deja el valor en 'out' si todo va bien.
Err evaluate(const char* expr, double ans, bool degrees, double& out);

// Formato de 10 cifras significativas, como fmt_number() del simulador
// (usa el signo menos tipográfico "−" y "E" para la notación científica).
String format(double v);

}  // namespace Calc
