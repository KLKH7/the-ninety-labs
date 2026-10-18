"""Portable math for the simulator: the same bits on every platform.

`math.exp`, `math.sin` and the other transcendental functions call the platform's C library, and
Apple's and glibc's disagree in the last bit for some inputs (about 1 `exp` in 500, 1 `erf` in 3).
A match is chaotic, so one bit in a player's profile became a different match on macOS and on
Linux (lesson 46). These functions use only operations IEEE 754 requires to round exactly (+, -,
*, /, sqrt) and exact ones (floor, frexp, ldexp), so every platform computes the same result.

`exp`, `log`, `sin`, `cos` and `atan2` follow fdlibm's algorithms and coefficients (see
THIRD_PARTY_NOTICES.md); they agree with the platform's functions to within an ulp or two
(tests/test_fmath.py). `math.sqrt` and `math.hypot` are already the same everywhere: IEEE fixes
`sqrt`, and CPython computes `hypot` itself.
"""

import math
import random

_INF = math.inf
_floor = math.floor
_ldexp = math.ldexp
_frexp = math.frexp
_sqrt = math.sqrt

# ---- exp -------------------------------------------------------------------
# x = k ln2 + r with |r| <= ln2 / 2; ln2 is split in two (ln2_hi has 32 bits, so k * ln2_hi is exact
# for every finite x), and e^r comes from fdlibm's rational approximation (e_exp).
_EXP_MIN = -7.45133219101941108420e02  # below this e^x rounds to zero; above 709.78 it overflows


def exp(x: float) -> float:
    # Constants written as literals (1/ln2, ln2_hi, ln2_lo, then fdlibm's P1 to P5): the simulator
    # calls this about a million times a simulated minute, and a literal loads faster than a global.
    if -7.45133219101941108420e02 <= x <= 7.09782712893383973096e02:
        k = _floor(x * 1.44269504088896338700e00 + 0.5)
        hi = x - k * 6.93147180369123816490e-01
        lo = k * 1.90821492927058770002e-10
        r = hi - lo
        t = r * r
        c = r - t * (1.66666666666666019037e-01 + t * (-2.77777777770155933842e-03 + t * (
            6.61375632143793436117e-05 + t * (-1.65339022054652515390e-06 + t * 4.13813679705723846039e-08))))
        return _ldexp(1.0 - ((lo - (r * c) / (2.0 - c)) - hi), k)
    if x < _EXP_MIN:
        return 0.0
    return math.exp(x)  # nan, infinity, or an overflow that raises as math.exp does


# ---- log -------------------------------------------------------------------
# x = 2^e m with sqrt(2)/2 <= m < sqrt(2); log(m) = 2 atanh(s) with s = (m - 1) / (m + 1), from
# fdlibm's e_log polynomial (Lg1 to Lg7, written as literals as in exp).


def log(x: float) -> float:
    if not 0.0 < x < _INF:
        return math.log(x)  # zero, negatives, nan and infinity raise or return what C fixes
    m, e = _frexp(x)
    if m < 7.07106781186547524401e-01:  # sqrt(2) / 2
        m *= 2.0
        e -= 1
    f = m - 1.0
    s = f / (2.0 + f)
    z = s * s
    w = z * z
    big = (w * (3.999999999940941908e-01 + w * (2.222219843214978396e-01 + w * 1.531383769920937332e-01))
           + z * (6.666666666666735130e-01 + w * (2.857142874366239149e-01 + w * (
               1.818357216161805012e-01 + w * 1.479819860511658591e-01))))
    hfsq = 0.5 * f * f
    return e * 6.93147180369123816490e-01 - ((hfsq - (s * (hfsq + big) + e * 1.90821492927058770002e-10)) - f)


# ---- sin and cos -------------------------------------------------------------
# x = n pi/2 + r with |r| <= pi/4. pi/2 is split in three; the first two parts have 33 bits, so
# n times each is exact while |n| < 2^20 (|x| below about 1.6 million radians).
_PIO2_1 = 1.57079632673412561417e00
_PIO2_2 = 6.07710050630396597660e-11
_PIO2_3 = 2.02226624879595063154e-21
_INV_PIO2 = 6.36619772367581382433e-01
_S1 = -1.66666666666666324348e-01
_S2 = 8.33333333332248946124e-03
_S3 = -1.98412698298579493134e-04
_S4 = 2.75573137070700676789e-06
_S5 = -2.50507602534068634195e-08
_S6 = 1.58969099521155010221e-10
_C1 = 4.16666666666666019037e-02
_C2 = -1.38888888888741095749e-03
_C3 = 2.48015872894767294178e-05
_C4 = -2.75573143513906633035e-07
_C5 = 2.08757232129817482790e-09
_C6 = -1.13596475577881948265e-11


def _ksin(x: float) -> float:
    z = x * x
    return x + z * x * (_S1 + z * (_S2 + z * (_S3 + z * (_S4 + z * (_S5 + z * _S6)))))


def _kcos(x: float) -> float:
    z = x * x
    r = z * (_C1 + z * (_C2 + z * (_C3 + z * (_C4 + z * (_C5 + z * _C6)))))
    hz = 0.5 * z
    w = 1.0 - hz
    return w + (((1.0 - w) - hz) + z * r)


_TRIG_MAX = 1.0e6  # radians: |n| stays below 2^20, where the reduction above is exact


def _reduce(x: float) -> tuple[int, float]:
    if not -_TRIG_MAX <= x <= _TRIG_MAX:
        # A larger angle needs Payne-Hanek reduction, which nothing here needs: a heading is
        # always within a few turns of zero. Refuse rather than return a wrong value.
        raise ValueError(f"sin and cos take |x| <= {_TRIG_MAX:g} radians, not {x!r}")
    n = _floor(x * _INV_PIO2 + 0.5)
    return n, ((x - n * _PIO2_1) - n * _PIO2_2) - n * _PIO2_3


def sin(x: float) -> float:
    if not -_INF < x < _INF:
        return math.sin(x)
    n, r = _reduce(x)
    q = n & 3
    if q == 0:
        return _ksin(r)
    if q == 1:
        return _kcos(r)
    if q == 2:
        return -_ksin(r)
    return -_kcos(r)


def cos(x: float) -> float:
    if not -_INF < x < _INF:
        return math.cos(x)
    n, r = _reduce(x)
    q = n & 3
    if q == 0:
        return _kcos(r)
    if q == 1:
        return -_ksin(r)
    if q == 2:
        return -_kcos(r)
    return _ksin(r)


# ---- atan2 -------------------------------------------------------------------
_ATAN_HI = (4.63647609000806093515e-01, 7.85398163397448278999e-01, 9.82793723247329054082e-01,
            1.57079632679489655800e00)
_ATAN_LO = (2.26987774529616870924e-17, 3.06161699786838301793e-17, 1.39033110312309984516e-17,
            6.12323399573676603587e-17)
_PI = 3.1415926535897931160e00
_PI_LO = 1.2246467991473531772e-16


def _atan(x: float) -> float:
    """atan of x >= 0: reduced to |x| < 7/16 about the nearest of atan(1/2), atan(1), atan(3/2),
    then fdlibm's polynomial (aT[0] to aT[10], as literals: atan2 runs a few thousand times a
    simulated second)."""
    if x >= 2.4375:
        if x > 7.3786976294838206464e19:  # 2^66: atan is pi/2 to the last bit
            return _ATAN_HI[3] + _ATAN_LO[3]
        i, x = 3, -1.0 / x
    elif x < 0.4375:
        i = -1
    elif x < 0.6875:
        i, x = 0, (2.0 * x - 1.0) / (2.0 + x)
    elif x < 1.1875:
        i, x = 1, (x - 1.0) / (x + 1.0)
    else:
        i, x = 2, (x - 1.5) / (1.0 + 1.5 * x)
    z = x * x
    w = z * z
    s1 = z * (3.33333333333329318027e-01
              + w * (1.42857142725034663711e-01
                     + w * (9.09088713343650656196e-02
                            + w * (6.66107313738753120669e-02
                                   + w * (4.97687799461593236017e-02 + w * 1.62858201153657823623e-02)))))
    s2 = w * (-1.99999999998764832476e-01
              + w * (-1.11111104054623557880e-01
                     + w * (-7.69187620504482999495e-02
                            + w * (-5.83357013379057348645e-02 + w * -3.65315727442169155270e-02))))
    if i < 0:
        return x - x * (s1 + s2)
    return _ATAN_HI[i] - ((x * (s1 + s2) - _ATAN_LO[i]) - x)


def atan2(y: float, x: float) -> float:
    if not (-_INF < x < _INF and -_INF < y < _INF):
        return math.atan2(y, x)
    if y == 0.0:
        return y if math.copysign(1.0, x) > 0 else math.copysign(_PI, y)
    if x == 0.0:
        return math.copysign(_ATAN_HI[3], y)
    ratio = abs(y / x)
    if ratio > 7.3786976294838206464e19:  # 2^66: the angle is pi/2 to the last bit, whatever x's sign
        return math.copysign(_ATAN_HI[3], y)
    z = _atan(ratio)
    if x > 0.0:
        return math.copysign(z, y)
    if y > 0.0:
        return _PI - (z - _PI_LO)
    return (z - _PI_LO) - _PI


# ---- the normal distribution -------------------------------------------------
_TWO_OVER_SQRT_PI = 1.12837916709551257390e00
_INV_SQRT_PI = 5.64189583547756286948e-01
_INV_SQRT2 = 7.07106781186547524401e-01
_INV_SQRT_2PI = 3.98942280401432677940e-01
_CDF_ROUNDING = 8 * 1.1e-16  # absolute error of normal_cdf: a few ulps of 1 (tests/test_fmath.py)
_CF_DEPTH = 60  # continued-fraction terms: erfc is converged to the last bit from 2.5 up


def erfc(a: float) -> float:
    """1 - erf(a). Near zero a series of positive terms; in the tails a continued fraction."""
    if a != a:
        return a
    if a < -2.5:
        return 2.0 - erfc(-a)
    if a > 2.5:
        if a > 27.3:
            return 0.0
        f = a
        for k in range(_CF_DEPTH, 0, -1):
            f = a + 0.5 * k / f
        return exp(-a * a) * _INV_SQRT_PI / f
    # erf(a) = 2/sqrt(pi) e^(-a^2) sum (2a^2)^n a / (1 * 3 * ... * (2n + 1))
    two_a2 = 2.0 * a * a
    term = total = a
    n = 0
    while abs(term) > 1e-17 * abs(total):
        n += 1
        term *= two_a2 / (2 * n + 1)
        total += term
    return 1.0 - _TWO_OVER_SQRT_PI * exp(-a * a) * total


def normal_cdf(x: float) -> float:
    """P(Z <= x) for a standard normal Z."""
    return 0.5 * erfc(-x * _INV_SQRT2)


def normal_inv_cdf(p: float) -> float:
    """The x with normal_cdf(x) = p, by Newton's method. The cdf is concave above the median and
    convex below it, so from a start on either side every step after the first lands on the near
    side of the root and the steps shrink to it. From 0.001 to 0.999 it starts at 0; in the tails
    it starts at -sqrt(-2 log p) (the upper tail by symmetry: 1 - p is exact there).

    Near the root the cdf's own rounding (a few times 1e-16) makes the steps jitter, about 1e-13
    in x, so some p never meet the step tolerance and stop after 100 steps. Either way the answer
    is returned only if its cdf is p to within that rounding."""
    if not 1e-300 <= p < 1.0:
        # Below 1e-300 (x under about -37) the density underflows and Newton cannot step.
        raise ValueError("p must be in the range 1e-300 <= p < 1.0")
    if p > 0.999:
        return -normal_inv_cdf(1.0 - p)
    x = 0.0 if p >= 0.001 else -_sqrt(-2.0 * log(p))
    for _ in range(100):
        step = (normal_cdf(x) - p) / (_INV_SQRT_2PI * exp(-0.5 * x * x))
        x -= step
        if abs(step) <= 4e-16 * max(1.0, abs(x)):
            break
    if abs(normal_cdf(x) - p) > _CDF_ROUNDING + 1e-13 * p:
        raise ArithmeticError(f"normal_inv_cdf({p!r}) did not converge")
    return x


def ipow(base: float, n: int) -> float:
    """base ** n for an integer n >= 0 by repeated products (`**` calls the C library's pow)."""
    result = 1.0
    for _ in range(n):
        result *= base
    return result


_NOT_PORTABLE = "uses the C library's log or exp; draw with gauss or add a portable version to fmath"


class Random(random.Random):
    """random.Random whose normal draws use the portable functions above. The integer and uniform
    draws are already exact everywhere; the methods that need the C library refuse."""

    def gauss(self, mu: float = 0.0, sigma: float = 1.0) -> float:
        # Marsaglia's polar method: a point uniform in the unit disc gives two independent normals
        # with one log and no sin or cos; the second is kept for the next call.
        z = self.gauss_next
        self.gauss_next = None
        if z is None:
            draw = self.random
            while True:
                u = 2.0 * draw() - 1.0
                v = 2.0 * draw() - 1.0
                q = u * u + v * v
                if 0.0 < q < 1.0:
                    break
            m = _sqrt(-2.0 * log(q) / q)
            z = u * m
            self.gauss_next = v * m
        return mu + z * sigma

    def _refuse(self, *args, **kwargs):
        raise NotImplementedError(_NOT_PORTABLE)

    normalvariate = lognormvariate = expovariate = vonmisesvariate = _refuse
    gammavariate = betavariate = paretovariate = weibullvariate = binomialvariate = _refuse
