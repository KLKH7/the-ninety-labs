"""The broadcast's crowd from recordings (Kian, Oct 26): two CC0 stadium recordings in place of the
synthesised murmur of audio.py, mixed to the match. The referee's whistles stay audio.py's.

- **Bed:** the ambience recording's steady stretches, looped in a seeded order with equal-power
  crossfades (XFADE_S), at BED_DBFS: the old synthesised murmur's level, so the whistles sit over it
  as before and footage.py's gain, whistle taming and limiter see the bed they were tuned on.
- **Reactions,** cut from the reaction recording, each placed so its onset lands REACT_DELAY_S after
  the moment the picture shows: a goal a roar, a shot an "ooh" (a blocked one a smaller lift), a
  restart (the kick-off of a half, a corner) a quiet lift. Their levels over the bed are REACT_OVER_DB.
- **Peaks:** a limiter holds the track at or under CEILING, so nothing clips before footage.py's own
  true-peak limiter.

The broadcast's sound is part of the synthetic broadcast: it is keyed to the render's own events
(like a stadium reacting to play) and never feeds vision, the agents or the Ask.

Only licences in ALLOWED_LICENCES are used (AGENTS.md, licences): a source with any other licence,
or whose bytes do not match its sha256, is refused. The recordings are build inputs kept out of git
(crowd_sources.json lists them; THIRD_PARTY_NOTICES.md credits them). Every level and time here is a
*design* value, chosen by measurement of the two files (docs in crowd_sources.json), not sourced.

    uv run python -m ninety.render.crowd_mix <run dir> --sources <dir of the wavs> --out crowd.m4a
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import subprocess
from pathlib import Path

import numpy as np

from ninety.render import audio

RATE = audio.RATE
ALLOWED_LICENCES = frozenset({"CC0-1.0"})  # what we may mix in; never NC/ND/SA terms
MANIFEST = Path(__file__).with_name("crowd_sources.json")
XFADE_S = 2.0  # the bed's crossfades: long enough that a seam is a blend, not a cut
BED_DBFS = -35.0  # the bed's RMS: the synthesised murmur's (8324: median -35.5 dBFS a second)
# A reaction's RMS over the bed. A goal's roar under +20 dB in the whistle band (footage.WHISTLE_OVER_DB),
# so footage.py never mistakes it for a whistle and cuts it.
REACT_OVER_DB = {"roar": 13.0, "ooh": 8.0, "lift": 4.0}
REACT_DELAY_S = 0.3  # the crowd answers just after the ball does
REACT_FADE_IN_S, REACT_FADE_OUT_S = 0.4, 2.5
# A cue is dropped when a stronger one (or one of its own kind) is already sounding: a shot that
# scores is the goal's roar, not an "ooh" and then a roar.
PRIORITY = {"roar": 3, "ooh": 2, "lift": 1}
CEILING = 10 ** (-1.0 / 20)  # -1 dBFS sample peak
LIMIT_BLOCK_S, LIMIT_RELEASE_S = 0.005, 0.25
SHOT_CUE = {"on_target": "ooh", "off_target": "ooh", "blocked": "lift"}


class LicenceRefused(ValueError):
    """A source whose licence is not in ALLOWED_LICENCES."""


def check_licence(source: dict) -> None:
    lic = source.get("licence")
    if lic not in ALLOWED_LICENCES:
        raise LicenceRefused(f"{source.get('name')}: licence {lic!r} is not allowed "
                             f"({', '.join(sorted(ALLOWED_LICENCES))} only)")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def decode(path: Path) -> np.ndarray:
    """The file as mono float32 at RATE (ffmpeg)."""
    pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", str(RATE),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(pcm, dtype=np.float32).copy()


def load(sources_dir: Path, manifest: Path = MANIFEST) -> dict:
    """{"bed": [pieces], "roar"/"ooh"/"lift": [(samples, onset s)]} from the manifest's sources,
    each licence and sha256 checked first."""
    spec = json.loads(Path(manifest).read_text())
    out: dict = {"bed": [], "roar": [], "ooh": [], "lift": []}
    for src in spec["sources"]:
        check_licence(src)
        path = Path(sources_dir) / src["file"]
        if sha256(path) != src["sha256"]:
            raise ValueError(f"{path}: sha256 does not match crowd_sources.json")
        x = decode(path)
        for a, b in src.get("bed", []):
            out["bed"].append(x[int(a * RATE):int(b * RATE)])
        for kind, cuts in src.get("reactions", {}).items():
            for a, onset, b in cuts:
                out[kind].append((x[int(a * RATE):int(b * RATE)], onset - a))
    return out


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if len(x) else 0.0


def bed(seconds: float, pieces: list[np.ndarray], seed: int = 0) -> np.ndarray:
    """`seconds` of the bed: the pieces, each at the same RMS, in a seeded order (no piece twice in a
    row), each from a seeded offset, joined with equal-power crossfades of XFADE_S."""
    rng = random.Random(f"crowd-bed-{seed}")
    n, xf = int(round(seconds * RATE)), int(XFADE_S * RATE)
    level = 10 ** (BED_DBFS / 20)
    pieces = [p * (level / max(_rms(p), 1e-9)) for p in pieces]
    t = np.linspace(0, math.pi / 2, xf, dtype=np.float32)
    fade_in, fade_out = np.sin(t), np.cos(t)
    out = np.zeros(n + len(max(pieces, key=len)), dtype=np.float32)
    pos, last = 0, -1
    while pos < n:
        k = rng.choice([i for i in range(len(pieces)) if i != last or len(pieces) == 1])
        last = k
        p = pieces[k]
        start = rng.randrange(0, max(1, len(p) // 2))  # a seeded offset, so a repeat is not the same seam
        seg = p[start:].copy()
        if len(seg) < 3 * xf:
            seg = p.copy()
        if pos:
            seg[:xf] *= fade_in
            out[pos - xf:pos] *= fade_out
            out[pos - xf:pos - xf + len(seg)] += seg
            pos = pos - xf + len(seg)
        else:
            out[:len(seg)] = seg
            pos = len(seg)
    return out[:n]


def schedule(cues: list[tuple[float, str]], clips: dict) -> list[tuple[float, str]]:
    """The cues that sound: in time order, a cue is dropped while a reaction of higher or equal
    priority is still sounding (until its onset + its length). A goal's roar always sounds."""
    kept: list[tuple[float, str]] = []
    busy_until, busy_pri = -1.0, 0
    longest = {k: max((len(s) / RATE - on for s, on in v), default=0.0)
               for k, v in clips.items() if k != "bed"}
    for t, kind in sorted(cues, key=lambda c: (c[0], -PRIORITY[c[1]])):
        if kind != "roar" and t < busy_until and PRIORITY[kind] <= busy_pri:
            continue
        kept.append((t, kind))
        busy_until, busy_pri = t + longest.get(kind, 0.0), PRIORITY[kind]
    return kept


def limit(x: np.ndarray, ceiling: float = CEILING) -> np.ndarray:
    """A peak limiter: per LIMIT_BLOCK_S block the gain that keeps it under `ceiling`, taken a block
    early (look-ahead), released over LIMIT_RELEASE_S; then a hard bound at `ceiling`."""
    b = max(1, int(LIMIT_BLOCK_S * RATE))
    nb = -(-len(x) // b)
    padded = np.zeros(nb * b, dtype=np.float32)
    padded[:len(x)] = np.abs(x)
    peak = padded.reshape(nb, b).max(axis=1)
    need = np.minimum(1.0, ceiling / np.maximum(peak, 1e-9))
    need = np.minimum(need, np.concatenate([need[1:], [1.0]]))  # look-ahead by a block
    rel = math.exp(-LIMIT_BLOCK_S / LIMIT_RELEASE_S)
    g = np.empty_like(need)
    cur = 1.0
    for i, v in enumerate(need):
        cur = v if v < cur else v - (v - cur) * rel
        g[i] = cur
    gain = np.repeat(g, b)[:len(x)].astype(np.float32)
    return np.clip(x * gain, -ceiling, ceiling)


def mix(seconds: float, cues: list[tuple[float, str]], calls: list[tuple[float, str]], clips: dict,
        seed: int = 0) -> np.ndarray:
    """The sound track: the bed, each kept cue's reaction (a seeded pick of its kind), audio.py's
    referee calls over them, and the limiter. The same for the same arguments."""
    rng = random.Random(f"crowd-react-{seed}")
    out = bed(seconds, clips["bed"], seed)
    n = len(out)
    bed_level = 10 ** (BED_DBFS / 20)
    fin, fout = int(REACT_FADE_IN_S * RATE), int(REACT_FADE_OUT_S * RATE)
    for t, kind in schedule(cues, clips):
        samples, onset = rng.choice(clips[kind])
        r = samples * (bed_level * 10 ** (REACT_OVER_DB[kind] / 20) / max(_rms(samples), 1e-9))
        r[:fin] *= np.linspace(0, 1, min(fin, len(r)), dtype=np.float32)
        r[-fout:] *= np.linspace(1, 0, min(fout, len(r)), dtype=np.float32)
        s = int(round((t + REACT_DELAY_S - onset) * RATE))
        a, b = max(0, s), min(n, s + len(r))
        if b > a:
            out[a:b] += r[a - s:b - s]
    for t, kind in calls:
        blast = np.asarray(audio.call(kind), dtype=np.float32)
        s = int(round(t * RATE))
        a, b = max(0, s), min(n, s + len(blast))
        if b > a:
            out[a:b] += blast[a - s:b - s]
    return limit(out)


def _corner(e: dict) -> bool:
    return (e["x"] <= 1 or e["x"] >= 104) and (e["y"] <= 1 or e["y"] >= 67)


def cues_from_run(run: Path) -> tuple[float, list[tuple[float, str]], list[tuple[float, str]]]:
    """(seconds, cues, calls) on a package's picture timeline (images/ links into the rendered
    segments, as the footage hunt packages them): each segment's own calls and crowd moments
    (clip.json), shots' outcomes and corners from its events.jsonl and frames.jsonl, at its images'
    place in the package."""
    run = Path(run)
    fps = json.loads((run / "clip.json").read_text())["fps"]
    imgs = sorted((run / "images").iterdir())
    segs: list[tuple[int, Path, int]] = []  # (package index, segment dir, its first local index)
    for i, p in enumerate(imgs):
        target = Path(os.readlink(p)) if p.is_symlink() else p.resolve()
        d, loc = target.parent.parent, int(target.stem)
        if not segs or segs[-1][1] != d or loc != segs[-1][2] + (i - segs[-1][0]):
            segs.append((i, d, loc))
    cues: list[tuple[float, str]] = []
    calls: list[tuple[float, str]] = []
    for k, (i, d, loc) in enumerate(segs):
        count = (segs[k + 1][0] if k + 1 < len(segs) else len(imgs)) - i
        clip = json.loads((d / "clip.json").read_text())

        def at(x: int, i=i, loc=loc, count=count) -> float | None:
            return (i + x - loc) / fps if loc <= x < loc + count else None

        index = {}
        with open(d / "frames.jsonl") as f:
            for n_, line in enumerate(f):
                index[json.loads(line)["frame"]] = n_
        events = [json.loads(line) for line in open(d / "events.jsonl")]
        outcome = {e["frame"]: e.get("outcome") for e in events if e["type"] == "shot"}
        for x, kind in clip.get("calls", []):
            if (t := at(x)) is not None:
                calls.append((t, kind))
                if kind == "kickoff":
                    cues.append((t, "lift"))
        for x in clip.get("crowd", {}).get("goals", []):
            if (t := at(x)) is not None:
                cues.append((t, "roar"))
        frame_of = {v: f for f, v in index.items()}
        for x in clip.get("crowd", {}).get("shots", []):
            t, oc = at(x), outcome.get(frame_of.get(x))
            if t is not None and oc in SHOT_CUE:
                cues.append((t, SHOT_CUE[oc]))
        for e in events:
            if e["type"] == "set_piece" and _corner(e) and e["frame"] in index:
                if (t := at(index[e["frame"]])) is not None:
                    cues.append((t, "lift"))
    return len(imgs) / fps, sorted(cues), sorted(calls)


def encode(samples: np.ndarray, out: Path) -> None:
    """AAC in an m4a, mono at RATE, as the render's own sound track."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "f32le", "-ar", str(RATE), "-ac", "1",
                    "-i", "-", "-c:a", "aac", "-b:a", "128k", str(out)],
                   input=samples.astype(np.float32).tobytes(), check=True)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run", type=Path)
    ap.add_argument("--sources", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--cues-out", type=Path, help="write the cues and calls placed, as JSON")
    a = ap.parse_args(argv)
    seconds, cues, calls = cues_from_run(a.run)
    clips = load(a.sources)
    track = mix(seconds, cues, calls, clips, a.seed)
    encode(track, a.out)
    if a.cues_out:
        a.cues_out.write_text(json.dumps({"seconds": seconds, "cues": schedule(cues, clips),
                                          "dropped": len(cues) - len(schedule(cues, clips)),
                                          "calls": calls}, indent=1))
    print(f"{a.out}: {seconds:.2f} s, {len(schedule(cues, clips))} reactions of {len(cues)} cues, "
          f"{len(calls)} calls, peak {float(np.abs(track).max()):.3f}")


if __name__ == "__main__":
    main()
