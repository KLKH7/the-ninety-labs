"""Rebuild the frozen test set's answer key without drawing, and prove it is the same match.

    git worktree add --detach <dir> cca498c          # engine-v1 plus renderer 0.3.2: the test set's commit
    (cd <dir> && uv sync)
    (cd <dir> && uv run python <this repo>/scripts/rebuild_test_truth.py \\
        --frozen <this repo>/docs/eval/test-set-frozen.json --out <outside the repo>/test)

Run inside a checkout of the frozen commit: it imports that checkout's own `ninety.render.clip`
(simulate, sample_params, choose_start, drawn_ball and the window's event filter), so nothing of
the engine is copied here. For each test seed it writes `seed<N>/events.jsonl` exactly as
`render_clip` writes it and refuses to go on unless its sha256 is the digest the freeze recorded
(docs/eval/test-set-frozen.json). It also writes `seed<N>/frames.jsonl` with what the event scorer
reads of each frame (frame, t, the drawn ball rounded as the renderer rounds it, the engine's
players); that file cannot match the freeze's digest, which also covers the drawn boxes, so the
events' digest is what shows the same match was rebuilt. Grading only (docs/eval/possession-change-plan.md):
nothing on the live path runs this or reads what it writes. It prints digests and counts, never
the events themselves.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    from ninety.render import clip as rc
    from ninety.sim.engine import FPS

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--frozen", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seconds", type=float, default=10.0)
    a = ap.parse_args(argv)
    frozen = json.loads(a.frozen.read_text())
    for c in frozen["clips"]:
        seed = c["seed"]
        p = rc.sample_params(seed)
        if p.to_dict() != c["params"]:
            raise SystemExit(f"seed {seed}: params differ from the freeze; not the same checkout")
        n = int(round(a.seconds * p.fps))
        match = rc.simulate(seed, (240.0 + a.seconds + 1) / 60)  # render_clip's horizon, no --start
        frames = match.frames
        start = rc.choose_start(frames, p, n, seed, 10.0, 240.0)
        t0, t1 = frames[start]["t"], frames[start + n - 1]["t"]
        events = "".join(json.dumps(e) + "\n" for e in match.events if t0 <= e["t"] <= t1)
        digest = hashlib.sha256(events.encode()).hexdigest()
        ok = digest == c["digest"]["events_jsonl"]
        print(json.dumps({"seed": seed, "start_frame": frames[start]["frame"], "events_sha256_matches": ok}))
        if not ok:
            raise SystemExit(f"seed {seed}: events.jsonl sha256 {digest} is not the frozen digest")
        rows = []
        for fr in frames[start:start + n]:
            x, y, z = rc.drawn_ball(fr)
            rows.append({"frame": fr["frame"], "t": fr["t"],
                         "ball": {"x": rc._r(x), "y": rc._r(y), "z": rc._r(z)}, "players": fr["players"]})
        if rows[-1]["frame"] - rows[0]["frame"] != n - 1 or round(rows[0]["t"] * FPS) != rows[0]["frame"]:
            raise SystemExit(f"seed {seed}: the window's frames are not consecutive")
        d = a.out / f"seed{seed}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "events.jsonl").write_text(events)
        (d / "frames.jsonl").write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))


if __name__ == "__main__":
    main()
