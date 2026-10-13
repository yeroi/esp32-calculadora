// =============================================================================
//  CalcEngine.cpp  —  Analizador por descenso recursivo (ver CalcEngine.h)
// -----------------------------------------------------------------------------
//  Sin excepciones (el núcleo de Arduino las desactiva): cada paso comprueba
//  err_ y, al primer fallo, el resto de llamadas devuelven 0 sin hacer nada.
// =============================================================================
#include "CalcEngine.h"
#include <math.h>
#include <string.h>

namespace Calc {
namespace {

enum class T : uint8_t { End, Num, Const, Func, Plus, Minus, Mul, Div, Pow, LP, RP, Sq, Fact };
enum Fn : uint8_t { F_ASIN, F_ACOS, F_ATAN, F_SIN, F_COS, F_TAN, F_LN, F_LOG, F_SQRT };
enum Cn : uint8_t { C_ANS, C_PI, C_E };

struct Tok {
  T t;
  uint8_t id;     // Fn o Cn
  double v;       // número
};

constexpr int MAX_TOK = 96;

// Nombres de función en el MISMO orden que FUNC_NAMES del simulador: "asin"
// antes que "sin" para que gane la más larga.
const char* const FUNC_NAMES[] = {"asin", "acos", "atan", "sin", "cos", "tan", "ln", "log", "√"};

bool startsWith(const char* s, const char* p) { return strncmp(s, p, strlen(p)) == 0; }

// Devuelve false si hay un error de sintaxis
bool tokenize(const char* s, Tok* out, int& n) {
  n = 0;
  while (*s) {
    if (n >= MAX_TOK - 2) return false;
    char c = *s;
    if (c == ' ') { s++; continue; }
    if ((c >= '0' && c <= '9') || c == '.') {
      char buf[40];
      int k = 0, dots = 0;
      while ((*s >= '0' && *s <= '9') || *s == '.') {
        if (*s == '.') dots++;
        if (k < 30) buf[k++] = *s;
        s++;
      }
      if (dots > 1 || (k == 1 && buf[0] == '.')) return false;
      if (*s == 'E') {                                 // 1.5E−3
        s++;
        buf[k++] = 'e';
        if (startsWith(s, "−")) { s += strlen("−"); buf[k++] = '-'; }
        else if (*s == '-') { s++; buf[k++] = '-'; }
        int d = 0;
        while (*s >= '0' && *s <= '9') { if (k < 38) buf[k++] = *s; s++; d++; }
        if (!d) return false;
      }
      buf[k] = 0;
      out[n++] = {T::Num, 0, strtod(buf, nullptr)};
      continue;
    }
    bool hit = false;
    for (uint8_t f = 0; f < sizeof(FUNC_NAMES) / sizeof(FUNC_NAMES[0]); f++) {
      size_t L = strlen(FUNC_NAMES[f]);
      if (strncmp(s, FUNC_NAMES[f], L) == 0 && s[L] == '(') {
        out[n++] = {T::Func, f, 0};
        out[n++] = {T::LP, 0, 0};
        s += L + 1;
        hit = true;
        break;
      }
    }
    if (hit) continue;
    if (startsWith(s, "Ans")) { out[n++] = {T::Const, C_ANS, 0}; s += 3; continue; }
    if (startsWith(s, "π"))   { out[n++] = {T::Const, C_PI, 0};  s += strlen("π"); continue; }
    if (c == 'e')             { out[n++] = {T::Const, C_E, 0};   s++; continue; }
    if (startsWith(s, "−"))   { out[n++] = {T::Minus, 0, 0}; s += strlen("−"); continue; }
    if (startsWith(s, "×"))   { out[n++] = {T::Mul, 0, 0};   s += strlen("×"); continue; }
    if (startsWith(s, "÷"))   { out[n++] = {T::Div, 0, 0};   s += strlen("÷"); continue; }
    if (startsWith(s, "²"))   { out[n++] = {T::Sq, 0, 0};    s += strlen("²"); continue; }
    T t;
    switch (c) {
      case '+': t = T::Plus; break;
      case '-': t = T::Minus; break;
      case '*': t = T::Mul; break;
      case '/': t = T::Div; break;
      case '^': t = T::Pow; break;
      case '(': t = T::LP; break;
      case ')': t = T::RP; break;
      case '!': t = T::Fact; break;
      default: return false;
    }
    out[n++] = {t, 0, 0};
    s++;
  }
  out[n] = {T::End, 0, 0};
  return true;
}

class Parser {
 public:
  Parser(const Tok* t, int n, double ans, bool deg) : t_(t), n_(n), ans_(ans), deg_(deg) {}

  Err parse(double& out) {
    if (n_ == 0) return Err::Syntax;
    double v = expr();
    if (err_ == Err::None && p_ != n_) err_ = Err::Syntax;
    if (err_ == Err::None && (isnan(v) || isinf(v))) err_ = Err::Math;
    out = v;
    return err_;
  }

 private:
  T peek() const { return p_ < n_ ? t_[p_].t : T::End; }
  const Tok& next() {
    static const Tok END = {T::End, 0, 0};
    return p_ < n_ ? t_[p_++] : (p_++, END);
  }
  double fail(Err e) {
    if (err_ == Err::None) err_ = e;
    return 0;
  }

  double expr() {
    double v = term();
    while (err_ == Err::None && (peek() == T::Plus || peek() == T::Minus)) {
      bool plus = next().t == T::Plus;
      double r = term();
      v = plus ? v + r : v - r;
    }
    return v;
  }

  double term() {
    double v = unary();
    while (err_ == Err::None) {
      T k = peek();
      if (k == T::Mul || k == T::Div) {
        next();
        double r = unary();
        if (k == T::Div) {
          if (r == 0) return fail(Err::Math);
          v /= r;
        } else {
          v *= r;
        }
      } else if (k == T::Num || k == T::Const || k == T::Func || k == T::LP) {
        v *= power();                                  // implícita: 2π, 3(4)
      } else {
        break;
      }
    }
    return v;
  }

  double unary() {
    if (err_ != Err::None) return 0;
    if (peek() == T::Minus) { next(); return -unary(); }
    if (peek() == T::Plus)  { next(); return unary(); }
    return power();
  }

  double power() {
    double b = postfix();
    if (err_ == Err::None && peek() == T::Pow) {
      next();
      double e = unary();
      if (err_ != Err::None) return 0;
      // math.pow de Python: base negativa con exponente no entero -> error
      if (b < 0 && e != floor(e)) return fail(Err::Math);
      if (b == 0 && e < 0) return fail(Err::Math);
      double r = pow(b, e);
      if (isnan(r) || isinf(r)) return fail(Err::Math);
      return r;
    }
    return b;
  }

  double postfix() {
    double v = primary();
    while (err_ == Err::None && (peek() == T::Sq || peek() == T::Fact)) {
      if (next().t == T::Sq) {
        v = v * v;
      } else {
        if (v < 0 || v != floor(v) || v > 170) return fail(Err::Math);
        double f = 1;
        for (int i = 2; i <= (int)v; i++) f *= i;
        v = f;
      }
    }
    return v;
  }

  double primary() {
    if (err_ != Err::None) return 0;
    const Tok& tk = next();
    switch (tk.t) {
      case T::Num: return tk.v;
      case T::Const:
        return tk.id == C_PI ? M_PI : tk.id == C_E ? M_E : ans_;
      case T::LP: {
        double v = expr();
        closeParen();
        return v;
      }
      case T::Func: {
        uint8_t f = tk.id;
        if (next().t != T::LP) return fail(Err::Syntax);
        double x = expr();
        closeParen();
        if (err_ != Err::None) return 0;
        return apply(f, x);
      }
      default:
        return fail(Err::Syntax);
    }
  }

  void closeParen() {
    if (err_ != Err::None) return;
    if (peek() == T::RP) next();
    else if (peek() != T::End) fail(Err::Syntax);
  }

  // round(x, 14) de Python: quita el ruido de sin(180°) = 1.2e-16
  static double round14(double x) {
    if (x == 0 || isnan(x) || isinf(x)) return x;
    double r = round(x * 1e14) / 1e14;
    return isinf(r) ? x : r;
  }

  double apply(uint8_t f, double x) {
    const double D2R = M_PI / 180.0;
    switch (f) {
      case F_SIN: case F_COS: case F_TAN: {
        double a = deg_ ? x * D2R : x;
        if (f == F_TAN && fabs(cos(a)) < 1e-15) return fail(Err::Math);
        return round14(f == F_SIN ? sin(a) : f == F_COS ? cos(a) : tan(a));
      }
      case F_ASIN: case F_ACOS: {
        if (x < -1 || x > 1) return fail(Err::Math);
        double r = f == F_ASIN ? asin(x) : acos(x);
        return deg_ ? r / D2R : r;
      }
      case F_ATAN: {
        double r = atan(x);
        return deg_ ? r / D2R : r;
      }
      case F_LN:
        if (x <= 0) return fail(Err::Math);
        return log(x);
      case F_LOG:
        if (x <= 0) return fail(Err::Math);
        return log10(x);
      case F_SQRT:
        if (x < 0) return fail(Err::Math);
        return sqrt(x);
    }
    return fail(Err::Syntax);
  }

  const Tok* t_;
  int n_, p_ = 0;
  double ans_;
  bool deg_;
  Err err_ = Err::None;
};

}  // namespace

Err evaluate(const char* expr, double ans, bool degrees, double& out) {
  Tok toks[MAX_TOK];
  int n;
  if (!tokenize(expr, toks, n)) return Err::Syntax;
  return Parser(toks, n, ans, degrees).parse(out);
}

String format(double v) {
  if (v == 0) return "0";
  char buf[40];
  if (fabs(v) < 1e15 && v == floor(v)) {
    snprintf(buf, sizeof(buf), "%lld", (long long)v);
  } else {
    snprintf(buf, sizeof(buf), "%.10g", v);
    char* e = strchr(buf, 'e');
    if (e) {                                           // 1.5e-07 -> 1.5E-7
      int ex = atoi(e + 1);
      snprintf(e, sizeof(buf) - (e - buf), "E%d", ex);
    }
  }
  String s;
  for (const char* p = buf; *p; p++) {
    if (*p == '-') s += "−";
    else s += *p;
  }
  return s;
}

}  // namespace Calc
