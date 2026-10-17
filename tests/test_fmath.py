"""The simulator's math is the same on every platform (lesson 26).

macOS and Linux once simulated different matches from the same seed: their C math libraries
disagree in the last bit, and a match is chaotic. ninety/sim/fmath.py computes with exactly
rounded operations only. These tests pin its results bit for bit (CI runs them on Linux and
macOS), check it against the platform's functions, and fail if code that writes the ground truth
or the published evaluation calls the C library again."""

import ast
import hashlib
import math
import random
from pathlib import Path
from statistics import NormalDist

import pytest

from ninety.sim import fmath

ROOT = Path(__file__).resolve().parents[1]
# Code whose output is ground truth or a published number. The renderer is out: its pixels come
# from a browser's GPU path, which decision 0001 already says is not bit-reproducible.
PORTABLE = ("ninety/sim", "ninety/match", "ninety/eval")
C_LIBRARY = {"exp", "expm1", "exp2", "log", "log1p", "log2", "log10", "pow", "sin", "cos", "tan",
             "asin", "acos", "atan", "atan2", "sinh", "cosh", "tanh", "asinh", "acosh", "atanh",
             "erf", "erfc", "gamma", "lgamma", "cbrt"}
# sha256 of outputs() below, computed on macOS arm64, Linux arm64 and Linux x86_64.
PINNED = "897a0a21297890060e2e7986b24dc8db4173ce7c4e5b1419aaccf1e48b85f7b5"


def outputs() -> str:
    r = fmath.Random(2026)
    out = []
    for _ in range(2000):
        a, b = r.uniform(-30.0, 30.0), r.uniform(-30.0, 30.0)
        out += [fmath.exp(a), fmath.log(abs(a) + 1e-3), fmath.sin(a), fmath.cos(a), fmath.atan2(a, b),
                fmath.normal_cdf(a / 4), fmath.erfc(a / 5), r.gauss(0.0, 1.0)]
    out += [fmath.normal_inv_cdf(p / 1000) for p in range(1, 1000, 7)]
    return repr(out)


def test_portable_math_gives_the_same_bits_on_every_platform():
    assert hashlib.sha256(outputs().encode()).hexdigest() == PINNED


def ulps(ours: float, theirs: float) -> float:
    return abs(ours - theirs) / math.ulp(max(abs(ours), abs(theirs)))


# fdlibm's functions are within 1 ulp of the true value, and so are the platform's, so the two may
# differ by up to 2 ulps.
TWO_ULPS = 2.0


@pytest.mark.parametrize("name, low, high", [
    ("exp", -745.0, 709.0), ("exp", -2.0, 2.0), ("sin", -50.0, 50.0), ("cos", -50.0, 50.0),
])
def test_each_function_agrees_with_the_platform_to_two_ulps(name, low, high):
    r = random.Random(1)
    ours, theirs = getattr(fmath, name), getattr(math, name)
    worst = max(ulps(ours(x), theirs(x)) for x in (r.uniform(low, high) for _ in range(20000)))
    assert worst <= TWO_ULPS


def test_log_and_atan2_agree_with_the_platform_to_two_ulps():
    r = random.Random(2)
    xs = [math.exp(r.uniform(-700, 700)) for _ in range(20000)] + [r.uniform(0.5, 2) for _ in range(20000)]
    assert max(ulps(fmath.log(x), math.log(x)) for x in xs if x != 1.0) <= TWO_ULPS
    pairs = [(r.uniform(-100, 100), r.uniform(-100, 100)) for _ in range(20000)]
    pairs += [(r.uniform(-1, 1) * 1e-3, r.uniform(-1, 1)) for _ in range(5000)]
    assert max(ulps(fmath.atan2(y, x), math.atan2(y, x)) for y, x in pairs) <= TWO_ULPS


def test_the_quadrants_and_edges_of_atan2_match_the_platform():
    """Signed zeros, infinities and ratios beyond 2^66 give the values C specifies exactly."""
    edges = (0.0, -0.0, 1.0, -1.0, 1e-300, -1e-300, math.inf, -math.inf)
    for y in edges:
        for x in edges:
            assert repr(fmath.atan2(y, x)) == repr(math.atan2(y, x)), (y, x)


def test_the_normal_distribution_matches_the_standard_library():
    """Absolute error of the cdf: the series and continued fraction converge to the last bit, so
    what remains is rounding, a few ulps of 1 (1.1e-16 each)."""
    nd = NormalDist()
    r = random.Random(3)
    for z in (r.uniform(-8.0, 8.0) for _ in range(20000)):
        assert abs(fmath.normal_cdf(z) - nd.cdf(z)) <= 8 * 1.1e-16
    for p in (r.uniform(0.001, 0.999) for _ in range(5000)):
        x = fmath.normal_inv_cdf(p)
        assert abs(x - nd.inv_cdf(p)) <= 1e-12 and abs(fmath.normal_cdf(x) - p) <= 8 * 1.1e-16


def test_gauss_draws_a_standard_normal_and_refuses_what_it_cannot_do_portably():
    r = fmath.Random(4)
    draws = [r.gauss(1.0, 2.0) for _ in range(200000)]
    mean = sum(draws) / len(draws)
    sd = math.sqrt(sum((d - mean) * (d - mean) for d in draws) / len(draws))
    # Standard errors of a 200,000-draw mean and sd: 2/sqrt(n) = 0.0045 and 2/sqrt(2n) = 0.0032.
    assert abs(mean - 1.0) < 4 * 0.0045 and abs(sd - 2.0) < 4 * 0.0032
    for name in ("normalvariate", "expovariate", "lognormvariate", "vonmisesvariate"):
        with pytest.raises(NotImplementedError):
            getattr(r, name)(1.0, 1.0)


def test_uniform_and_integer_draws_are_those_of_random_random():
    """The subclass changes only the normal draws, so seeds keep every other stream."""
    ours, theirs = fmath.Random("seed"), random.Random("seed")
    assert [ours.uniform(0, 5) for _ in range(50)] == [theirs.uniform(0, 5) for _ in range(50)]
    assert [ours.choice("abcdef") for _ in range(50)] == [theirs.choice("abcdef") for _ in range(50)]


def platform_calls(source: str) -> list[str]:
    """Every call into the C math library, `**` (C's pow), and every plain random.Random built."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "math"
                and node.attr in C_LIBRARY):
            found.append(f"line {node.lineno}: math.{node.attr}")
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            found.append(f"line {node.lineno}: **")
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and isinstance(node.func.value, ast.Name) and node.func.value.id == "random"):
            found.append(f"line {node.lineno}: random.{node.func.attr}()")
        elif isinstance(node, ast.ImportFrom) and node.module == "math":
            names = [a.name for a in node.names if a.name in C_LIBRARY]
            found += [f"line {node.lineno}: from math import {name}" for name in names]
        elif isinstance(node, ast.Name) and node.id == "NormalDist":
            found.append(f"line {node.lineno}: NormalDist")
    return found


def test_the_check_finds_each_way_of_reaching_the_c_library():
    """Positive control: a planted call of each kind is found; sqrt, hypot and annotations are not."""
    planted = ("import math, random\nfrom math import exp\nfrom statistics import NormalDist\n"
               "a = math.exp(1.0)\nb = 2.0 ** 0.5\nr = random.Random(7)\nn = NormalDist()\n"
               "c = math.sqrt(2.0) + math.hypot(3.0, 4.0)\ns: random.Random\n")
    assert sorted(platform_calls(planted)) == [
        "line 2: from math import exp", "line 4: math.exp", "line 5: **", "line 6: random.Random()",
        "line 7: NormalDist",
    ]


def test_ground_truth_and_evaluation_code_never_reach_the_c_library():
    files = [p for d in PORTABLE for p in sorted((ROOT / d).rglob("*.py")) if p.name != "fmath.py"]
    assert len(files) > 10  # the scan found the packages
    found = {str(p.relative_to(ROOT)): platform_calls(p.read_text()) for p in files}
    assert not {k: v for k, v in found.items() if v}, "use ninety/sim/fmath.py"
