"""The broadcast look (web/render/look.js) must not break the streams it does not apply to.

GRADE_GLSL is compiled into every stream's post shader (render.js), but only the broadcast stream of
a stadium=broadcast clip defines LOOK_SAT. On GPU GL (ANGLE/Vulkan) a shader that names an undefined
macro fails to compile and the tactical views came out black (8324 demo renders, Oct 26); SwiftShader,
where the look was gated, did not show it. So the grade's source must give LOOK_SAT a default before
it is used, and every macro it uses must be defined in it or by applyBroadcastLook.
"""

import re
from pathlib import Path

LOOK = Path(__file__).resolve().parents[1] / "web" / "render" / "look.js"


def grade_glsl() -> str:
    m = re.search(r"export const GRADE_GLSL = `(.*?)`;", LOOK.read_text(), re.S)
    assert m, "GRADE_GLSL not found in look.js"
    return m.group(1)


def test_look_sat_has_a_default_before_it_is_used():
    src = grade_glsl()
    guard = src.find("#ifndef LOOK_SAT")
    define = src.find("#define LOOK_SAT")
    use = src.find("LOOK_SAT +")
    assert guard != -1 and define != -1, "GRADE_GLSL must define a default LOOK_SAT"
    assert guard < define < use, "the default must come before the grade uses LOOK_SAT"


def test_every_macro_the_grade_uses_is_defined():
    src = grade_glsl()
    used = set(re.findall(r"\b(LOOK_[A-Z_]+)\b", src))
    defined = set(re.findall(r"#define\s+(LOOK_[A-Z_]+)", src))
    assert used <= defined, f"macros used without a default in GRADE_GLSL: {sorted(used - defined)}"
