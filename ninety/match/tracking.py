"""Where the served matches' players are, frame by frame: what the phone's minimap and the window
facts read (ninety/intel/window.py).

Until Milestone 1 the positions are the simulator's, so every frame says `source: truth`: a stand-in
for tracking the video, as the agents read simulator events until then (AGENTS.md, "Ground truth is
the answer key"). After it, tracked positions replace them under `source: tracked`, and a test keeps
the live path off `truth`.

Frames keep only what the companion needs (frame, t, the ball's x and y, each player's id, team, x,
y): the frame schema's required fields, without the ball's height. Like the match events, the
served matches are simulated when the image is built (`match_server --precompute`), so a request
never starts a simulation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# The engine's frame rate (ninety/sim/engine.py FPS; tests/test_tracking.py holds them equal). Set
# here rather than imported, so reading precomputed frames never loads the simulator, which the
# live path must not (tests/test_live_reads_no_truth.py).
FPS = 25

FRAMES_DIR = "frames"  # inside NINETY_MATCH_DIR, beside the matches' event files
SOURCE = "truth"  # the simulator's positions (see the module docstring)
TRACKED = "tracked"  # positions from tracking the video (ninety/vision/track.py)
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
# Clips the companion serves from tracked positions: the M1 clip the laptop plays
# (ninety/match/detected.M1_CLIP), once its tracked frames file exists.
TRACKED_CLIPS = ("seed900001",)
# A tracked player's id: team plus track id (h-t12), as the companion schemas' tracked pattern. The
# tracker reads no shirt numbers, so a track is never given a squad id (h7).
TRACK_ID = re.compile(r"^(?P<team>[ha])-t\d+$")
TEAM_LETTER = {"home": "h", "away": "a"}


def slim(frame: dict, source: str = SOURCE) -> dict:
    """One engine frame cut to what the companion reads."""
    ball = frame["ball"]
    return {
        "frame": frame["frame"],
        "t": frame["t"],
        "source": source,
        "ball": {"x": ball["x"], "y": ball["y"]},
        "players": [{"id": p["id"], "team": p["team"], "x": p["x"], "y": p["y"]} for p in frame["players"]],
    }


@dataclass(frozen=True)
class Track:
    """One match's frames, oldest first, at the engine's FPS."""

    match: str
    frames: tuple[dict, ...]
    restarts: tuple[int, ...] = ()  # kickoff frames: everyone is reset there, which is not movement

    @property
    def source(self) -> str:
        sources = {f.get("source", SOURCE) for f in self.frames}
        if len(sources) != 1:
            raise ValueError(f"{self.match}: frames mix sources {sorted(sources)}")
        return sources.pop()

    @property
    def roster(self) -> tuple[str, ...]:
        """Every player in the match's frames."""
        return tuple(sorted({p["id"] for f in self.frames for p in f["players"]}))

    @property
    def duration(self) -> float:
        return float(self.frames[-1]["t"]) if self.frames else 0.0

    def between(self, t_from: float, t_to: float) -> list[dict]:
        """The frames from t_from to t_to, both included."""
        return [f for f in self.frames if t_from <= f["t"] <= t_to]


def kickoffs(events: list[dict]) -> tuple[int, ...]:
    return tuple(int(e["frame"]) for e in events if e["type"] == "kickoff")


def from_match(match: str, run) -> Track:
    """A Track from a simulated match (ninety.sim.engine.Match)."""
    return Track(match, tuple(slim(f) for f in run.frames), kickoffs(run.events))


def write(out: Path, track: Track) -> Path:
    path = out / FRAMES_DIR / f"{track.match}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"restarts": list(track.restarts), "frames": list(track.frames)}
    path.write_text(json.dumps(body, separators=(",", ":")))
    return path


@lru_cache(maxsize=4)
def track(match: str, seed: int, minutes: float, match_dir: str = "") -> Track:
    """A served match's frames: read from match_dir when it holds them (the image's precomputed
    matches, ninety/mcp/match_server.py), else simulated."""
    stored = Path(match_dir) / FRAMES_DIR / f"{match}.json" if match_dir else None
    if stored and stored.exists():
        body = json.loads(stored.read_text())
        return Track(match, tuple(body["frames"]), tuple(body["restarts"]))
    from ninety.sim.engine import simulate  # the pre-M1 stand-in; never on the live path

    return from_match(match, simulate(seed, minutes))


class NotTracked(ValueError):
    """A clip's tracked frames are missing, or are not tracked positions the companion can serve."""


def tracked_path(clip: str) -> Path:
    return FIXTURES / f"tracked-{clip}.json"  # written by ninety/vision/tracked_frames.py


@lru_cache(maxsize=4)
def tracked(clip: str, path: str | None = None) -> Track:
    """A clip's positions from tracking the video: `{restarts, frames}`, as `write` stores a match,
    each frame a `frame.schema.json` frame, every one `source: tracked`, frames strictly increasing,
    each player a track id of its own team (h-t12). Kickoff resets are the file's restarts and the
    clip's detected kickoff events. Anything else is refused: the companion never shows positions it
    cannot vouch were tracked."""
    from ninety.agents.contracts import schema_validator  # the frame schema, references resolved
    from ninety.match import detected

    if clip not in TRACKED_CLIPS:
        raise NotTracked(f"{clip}: not a tracked clip")
    file = Path(path) if path else tracked_path(clip)
    if not file.exists():
        raise NotTracked(f"{clip}: no tracked positions yet ({file.name})")
    try:
        body = json.loads(file.read_text())
        rows, restarts = body["frames"], [int(r) for r in body["restarts"]]
    except (ValueError, TypeError, KeyError) as exc:
        raise NotTracked(f"{file.name}: not a {{restarts, frames}} object ({exc})") from None
    validator, frames, last = schema_validator("frame"), [], -1
    for n, frame in enumerate(rows):
        errors = sorted(validator.iter_errors(frame), key=lambda e: list(e.path))
        if errors:
            raise NotTracked(f"{file.name}, frame {n}: not a frame: {errors[0].message}")
        if frame.get("source") != TRACKED:
            raise NotTracked(f"{file.name}, frame {n}: source {frame.get('source')!r}, not {TRACKED!r}")
        if frame["frame"] <= last:
            raise NotTracked(f"{file.name}, frame {n}: frames are not strictly increasing")
        bad = [
            p["id"] for p in frame["players"]
            if not (m := TRACK_ID.match(str(p["id"]))) or m["team"] != TEAM_LETTER.get(p["team"])
        ]
        if bad:
            raise NotTracked(f"{file.name}, frame {n}: player ids {bad[:3]} are not track ids of their team")
        last = frame["frame"]
        frames.append(slim(frame, TRACKED))
    if len(frames) < 2:
        raise NotTracked(f"{file.name}: fewer than two frames")
    events = detected.load(detected.m1_path(clip)) if clip == detected.M1_CLIP else []
    detected_kickoffs = kickoffs([e for e in events if "frame" in e])
    return Track(clip, tuple(frames), tuple(sorted({*restarts, *detected_kickoffs})))


__all__ = [
    "FPS", "SOURCE", "TRACKED", "TRACKED_CLIPS", "NotTracked", "Track", "from_match", "kickoffs",
    "slim", "track", "tracked", "tracked_path", "write",
]
