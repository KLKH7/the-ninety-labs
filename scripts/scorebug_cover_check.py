"""The baked scorebug never shows through the big screen's own (web/viewer/src/scorebug.ts).

Every STEP_S of footage, the baked bug's widest box (web/render/render.js `layoutBug`, 2 source px more
each side) is screenshotted with the footage shown and hidden: an opaque bug that covers it makes the
two identical. Headless WebKit (Playwright's Chromium cannot decode H.264).

    uv run python scripts/scorebug_cover_check.py <viewer url> <bundle>/manifest.json 1920x1080 [--dock]
"""

from __future__ import annotations

import io
import json
import sys

from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

STEP_S = 5.0


def main(url: str, manifest: str, size: str, dock: bool) -> dict:
    W, H = map(int, size.split("x"))
    dur = json.load(open(manifest))["footage"]["duration_s"]
    leaks, n = [], 0
    with sync_playwright() as p:
        b = p.webkit.launch()
        ctx = b.new_context(viewport={"width": W, "height": H})
        state = "open" if dock else "closed"
        ctx.add_init_script(f"try{{localStorage.setItem('ninety.dock','{state}');"
                            "localStorage.setItem('ninety.askHint','used')}catch(e){}")
        page = ctx.new_page()
        page.goto(url)
        page.wait_for_selector("body[data-state=ready] #overlay[data-t]")
        st = page.locator("#stage").bounding_box()
        fx, fy = st["width"] / 1280, st["height"] / 720
        clip = {"x": st["x"] + 26 * fx, "y": st["y"] + 22 * fy, "width": 404 * fx, "height": 44 * fy}
        v = 0.3
        while v < dur:
            page.evaluate("v => { const s = document.getElementById('scrub'); s.step = 'any';"
                          " s.value = String(v); s.dispatchEvent(new Event('input')); }", v)
            page.wait_for_function("(() => { const x = document.getElementById('video');"
                                   " return !x.seeking && x.readyState >= 2; })()", timeout=20000)
            page.wait_for_timeout(120)
            shown = Image.open(io.BytesIO(page.screenshot(clip=clip))).convert("RGB")
            page.evaluate("document.getElementById('video').style.visibility = 'hidden'")
            page.wait_for_timeout(60)
            hidden = Image.open(io.BytesIO(page.screenshot(clip=clip))).convert("RGB")
            page.evaluate("document.getElementById('video').style.visibility = ''")
            diff = ImageChops.difference(shown, hidden)
            if diff.getbbox():
                leaks.append({"v": round(v, 1), "pixels": sum(1 for q in diff.getdata() if max(q) > 0)})
            n += 1
            v += STEP_S
        b.close()
    return {"size": size, "dock": dock, "frames": n, "leaks": leaks}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = main(args[0], args[1], args[2], "--dock" in sys.argv)
    print(json.dumps(out))
    sys.exit(1 if out["leaks"] or not out["frames"] else 0)
