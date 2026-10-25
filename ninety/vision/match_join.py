"""One condensed-match clip from its segments' joined live runs, on the match clock, for ninety-e2e.

    uv run python -m ninety.vision.match_join --manifest <demo manifest.json> \\
        --clips <dir of the rendered segments> --vision <dir of the segments' runs> --out <clip>

A demo match is rendered as one clip per segment of the edit (docs/eval/demo-match.md), and each
segment goes through the live path on its own: live_job on the broadcast and on the tactical views,
then ninety.vision.join, into `<vision>/<segment>/joined/`. This puts the segments back together,
in the manifest's order, as one clip that `ninety-e2e <clip> --match` reads like any other. Nothing
is detected again.

**The clock.** Every segment is rendered on the match clock (its frames keep their match numbers and
times), so nothing is shifted: segment k shows its own runs of match frames (more than one where the
broadcast cut a dead ball inside it), and the joined clip shows them back to back. Its clip.json
records each run as a timeline segment (ninety/match/timeline.py: image index, first match
frame, frames), so the viewer and the audio description map video time to match time across every
jump. The join refuses segments that overlap or run out of order, a segment whose own timeline
does not list its frames, and runs that list other frames than the segment shows.

**Ids.** Each segment's tracker numbers its tracks from 1, so track 8 of two segments are not the
same man. Track ids are renumbered per segment, `h-t8` in segment 3 becoming `h-t3008`, wherever
they appear (events, tracked frames, the association); event ids get the segment as a prefix.

Beside the clip, what `ninety-e2e <clip> --match` is given: detected.jsonl (--events-file),
detections.jsonl (--detections, the broadcast's, its clip id the joined clip's), observations.jsonl
and tracked.json (--observations, --tracked), views/<lens>/observations.jsonl (--views) and
association.json. Every frame number in them is a match frame, as in each segment's own files.

The clip's footage is the segments' broadcast images, linked in order as images/00000.jpg on; its
clip.json keeps only what the viewer and e2e read (fps, size, the team codes, the timeline). The
edit's own chapters and the half-time come from the manifest, which was chosen from the answer key:
they go to edit.json beside it, named as the edit's, and nothing the agents read carries them
(the manifest's rule: show them as the edit's chapters, never as detections, never to an agent).

Reads the manifest, each segment's clip.json (fps, size, codes, its first frame and length) and
the joined runs; never a segment's frames.jsonl, events.jsonl or meta.json (tests/test_match_join.py).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

FPS = 25
TRACK = re.compile(r"^([ha])-t(\d+)$")
PER_SEGMENT = 1000  # track ids per segment: a segment of under a minute and a half has a few hundred
RUN_FILES = ("detected.jsonl", "observations.jsonl", "tracked.json", "association.json")
VIEWS = ("tac-l", "tac-r")
META_KEYS = ("width", "height", "fps", "home_code", "away_code")


def segment_name(seed: int, start_s: float) -> str:
    return f"seed{seed}-t{round(start_s * FPS):06d}"


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def renumber(value, k: int):
    """Every track id in `value` (a string, or inside lists and dicts) moved into segment k's range."""
    if isinstance(value, str):
        m = TRACK.match(value)
        if not m:
            return value
        n = int(m.group(2))
        if n >= PER_SEGMENT:
            raise SystemExit(f"segment {k}: track {value} is past {PER_SEGMENT} tracks a segment")
        return f"{m.group(1)}-t{k * PER_SEGMENT + n}"
    if isinstance(value, list):
        return [renumber(v, k) for v in value]
    if isinstance(value, dict):
        return {renumber(key, k) if isinstance(key, str) else key: renumber(v, k) for key, v in value.items()}
    return value


def read_segment(clips: Path, vision: Path, name: str) -> dict:
    meta = json.loads((clips / name / "clip.json").read_text())
    joined = vision / name / "joined"
    missing = [f for f in RUN_FILES if not (joined / f).is_file()]
    if missing:
        raise SystemExit(f"{joined}: not joined yet, missing {missing}")
    return {
        "name": name,
        "start": meta["start_frame"],
        "frames": meta["frames"],
        # its own timeline: a dead-ball cut inside the segment is a jump in its match frames
        "runs": meta.get("segments")
        or [{"index": 0, "frame": meta["start_frame"], "frames": meta["frames"]}],
        "params": {k: meta["params"].get(k, meta.get(k)) for k in META_KEYS},
        "images": sorted((clips / name / "images").glob("*.jpg")),
        "events": _jsonl(joined / "detected.jsonl"),
        "observations": _jsonl(joined / "observations.jsonl"),
        "tracked": json.loads((joined / "tracked.json").read_text()),
        "association": json.loads((joined / "association.json").read_text()),
        # the broadcast's detections (e2e's --detections) and each view's own placed observations
        "detections": _jsonl(vision / name / "broadcast" / "detections.jsonl"),
        "views": {v: _jsonl(vision / name / "views" / "views" / v / "observations.jsonl") for v in VIEWS},
    }


def check(segs: list[dict]) -> None:
    """In order, no overlap, each segment whole and its runs on its own frames."""
    end = -1
    for s in segs:
        first, n = s["start"], s["frames"]
        if first <= end:
            raise SystemExit(f"refused: {s['name']} starts at frame {first}, not after the last's {end}")
        if len(s["images"]) != n:
            raise SystemExit(f"refused: {s['name']} has {len(s['images'])} images, not its {n} frames")
        own = [f for r in s["runs"] for f in range(r["frame"], r["frame"] + r["frames"])]
        if len(own) != n or own != sorted(set(own)) or own[0] != first:
            raise SystemExit(f"refused: {s['name']}'s own timeline does not list its {n} frames in order")
        obs = [r["frame"] for r in s["observations"]]
        if obs != own:
            raise SystemExit(f"refused: {s['name']}'s observations are not its shown frames")
        if any(abs(r["t"] - r["frame"] / FPS) > 1e-6 for r in s["observations"]):
            raise SystemExit(f"refused: {s['name']}'s observations are not on the match clock")
        shown = set(own)
        if [d["frame"] for d in s["detections"]] != own or any(
                [r["frame"] for r in rows] != own for rows in s["views"].values()):
            raise SystemExit(f"refused: {s['name']}'s detections or views are not its shown frames")
        stray = [x["frame"] for x in s["tracked"]["frames"] + s["events"] if x["frame"] not in shown]
        if stray:
            raise SystemExit(f"refused: {s['name']} has tracked frames or events outside it: {stray[:3]}")
        end = own[-1]


def build(manifest: dict, clips: Path, vision: Path, out: Path) -> dict:
    seed = manifest["seed"]
    names = [segment_name(seed, s["start_s"]) for s in manifest["segments"]]
    segs = [read_segment(clips, vision, n) for n in names]
    check(segs)
    params = segs[0]["params"]
    if any(s["params"] != params for s in segs):
        raise SystemExit("refused: the segments were rendered at different sizes, rates or teams")
    out.mkdir(parents=True, exist_ok=True)
    (out / "images").mkdir(exist_ok=True)
    timeline, events, observations, tracked, restarts, tracks = [], [], [], [], [], {}
    detections, views = [], {v: [] for v in VIEWS}
    index = 0
    for k, s in enumerate(segs):
        timeline += [{**r, "index": index + r["index"]} for r in s["runs"]]
        for i, image in enumerate(s["images"]):
            link = out / "images" / f"{index + i:05d}.jpg"
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(image.resolve())
        index += s["frames"]
        events += [{**renumber(e, k), "id": f"s{k:02d}-{e['id']}"} for e in s["events"]]
        observations += s["observations"]
        detections += [{**d, "clip": f"seed{seed}-match"} for d in s["detections"]]
        for v in VIEWS:
            views[v] += s["views"][v]
        tracked += [renumber(f, k) for f in s["tracked"]["frames"]]
        restarts += s["tracked"].get("restarts", [])
        tracks |= renumber(s["association"]["tracks"], k)
    frames = [r["frame"] for r in observations]
    assert frames == sorted(set(frames)), "duplicate or unordered frames"  # check() rules it out
    fps = params["fps"] or FPS
    clip = {
        "clip_id": f"seed{seed}-match",
        "seed": seed,
        "fps": fps,
        "frames": index,
        "t_start": segs[0]["start"] / fps,
        "t_end": frames[-1] / fps,
        "segments": timeline,
        "params": params,
        "source": "ninety.vision.match_join",
    }
    (out / "clip.json").write_text(json.dumps(clip, indent=1) + "\n")
    (out / "detected.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    (out / "observations.jsonl").write_text(
        "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in observations))
    (out / "detections.jsonl").write_text(
        "".join(json.dumps(d, separators=(",", ":")) + "\n" for d in detections))
    for v in VIEWS:
        (out / "views" / v).mkdir(parents=True, exist_ok=True)
        (out / "views" / v / "observations.jsonl").write_text(
            "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in views[v]))
    (out / "tracked.json").write_text(
        json.dumps({"restarts": restarts, "frames": tracked}, separators=(",", ":")) + "\n")
    (out / "association.json").write_text(json.dumps({
        "match_m": segs[0]["association"].get("match_m"), "tracks": tracks}, indent=1) + "\n")
    (out / "edit.json").write_text(json.dumps({
        "about": "The edit's chapters and the half-time, chosen from the answer key by the demo-match "
                 "rule: show them as the edit's chapters, never as detections, never to an agent.",
        "rule": manifest.get("rule"),
        "chapters": manifest["chapters"],
    }, indent=1) + "\n")
    report = {"clip": clip["clip_id"], "segments": len(segs), "frames": index, "events": len(events),
              "tracked_frames": len(tracked), "broadcast_tracks": len(tracks)}
    (out / "match_join.json").write_text(json.dumps(report, indent=1) + "\n")
    return report


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--manifest", type=Path, required=True, help="the demo match's manifest (demo_match)")
    ap.add_argument("--clips", type=Path, required=True, help="the rendered segments, seed<N>-t<frame>/")
    ap.add_argument("--vision", type=Path, required=True, help="each segment's runs, <segment>/joined/")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    print(json.dumps(build(json.loads(a.manifest.read_text()), a.clips, a.vision, a.out)))


if __name__ == "__main__":
    main()
