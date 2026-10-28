"""The viewer hides its page until main.ts chooses the layout (no flash of the developer panels), and
must still show it if no script ever does: a CSS animation reveals the body after 3 s regardless."""

import re
from pathlib import Path

CSS = (Path(__file__).resolve().parents[1] / "web" / "viewer" / "src" / "style.css").read_text()


def test_the_hidden_page_has_a_reveal_fallback():
    rule = re.search(r"body:not\(\[data-layout\]\)\s*\{([^}]*)\}", CSS)
    assert rule, "the body is no longer hidden until the layout is set"
    body = rule.group(1)
    assert "visibility: hidden" in body
    anim = re.search(r"animation:\s*([\w-]+)\s+0s\s+(\d+(?:\.\d+)?)s\s+forwards", body)
    assert anim, "no fail-safe animation reveals the page"
    name, delay = anim.group(1), float(anim.group(2))
    assert delay <= 3, f"the fail-safe waits {delay} s"
    pattern = r"@keyframes\s+" + re.escape(name) + r"\s*\{\s*to\s*\{\s*visibility:\s*visible"
    keyframes = re.search(pattern, CSS)
    assert keyframes, f"@keyframes {name} does not end visible"
