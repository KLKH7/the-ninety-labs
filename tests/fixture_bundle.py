"""A small Replay bundle for building and smoke-testing the image without the published one.

The CI `image` job builds the Dockerfile with this bundle (served from the runner, pinned by the
sha256 printed here), runs the container and points tests/test_live_smoke.py at it: the whole demo
image, checked on every pull request, with no Azure and no release asset.

    uv run python -m tests.fixture_bundle runs/fixture  # prints the sha256 of runs/fixture/replay.tar.gz
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from ninety import e2e
from tests.e2e_clip import H, W, write_clip

ROOT = Path(__file__).resolve().parent.parent


def main(out: Path) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:  # a real JPEG, so the viewer draws every frame without an error
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H})
        page.set_content('<body style="margin:0;background:#2e7d32"></body>')
        jpeg = page.screenshot(type="jpeg")
        browser.close()
    clip, detections, events = write_clip(out / "clip-src", jpeg)
    bundle = out / "bundle"
    e2e.main([str(clip), "--out", str(bundle), "--detections", str(detections), "--frames", "--plant",
              "--events-file", str(events)])
    spec = importlib.util.spec_from_file_location("replay", ROOT / "infra" / "replay.py")
    replay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replay)
    return replay.pack(bundle, out / "replay.tar.gz")


if __name__ == "__main__":
    print(main(Path(sys.argv[1])))
