"""The answer key's values for the Ask grader's intents, per window, offline.

Grading only: this reads the simulator's ground truth (events.jsonl, frames.jsonl), and nothing on
the live path may import it (tests/test_ask_grade.py). Two scopes for every value:

- "match": the whole match from the full simulated run (the answer key of every minute played);
- "footage": only the frames the footage shows (the clip windows in <work>/clips/*/meta.json), what
  vision could have seen. The demo's clip windows show 20.9% of the match (1129 s of 5400).

A pass over the full run's frames (455 MB on seed 8324) is reduced once to a small cache (`build`):
per frame, the side in possession (#424's truth rule, ninety/eval/possession_time.py: the latest
possessor carried, nobody's during a dead ball or with the ball beyond a line), the ball's third
for each side's attacking direction, and each player's speed. Everything else is from the events.
"""

from __future__ import annotations

import gzip
import json
import math
from array import array
from dataclasses import dataclass
from pathlib import Path

from ninety.eval.set_piece_set import restarts
from ninety.intel.scene import PITCH_X, PITCH_Y

FPS = 25
DEAD_FROM = {"out_of_play", "goal", "foul", "offside", "half_time"}  # possession_time.py (#424)
DEAD_TO = {"set_piece", "kickoff"}
THIRD_X = PITCH_X / 3  # Law 1: the pitch's length in thirds (the attacking third, GROUNDING I17)


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def footage_windows(work: Path) -> list[tuple[int, int]]:
    """The engine frames the footage shows: each clip's [first_frame, last_frame]."""
    out = []
    for meta in sorted((work / "clips").glob("*/meta.json")):
        w = json.loads(meta.read_text())["window"]
        out.append((int(w["first_frame"]), int(w["last_frame"])))
    return sorted(out)


def footage_events(work: Path) -> list[dict]:
    """The clips' own truth events (their union by id), as the footage shows them."""
    seen: dict[str, dict] = {}
    for ev in sorted((work / "clips").glob("*/events.jsonl")):
        for e in _jsonl(ev):
            seen.setdefault(e["id"], e)
    return sorted(seen.values(), key=lambda e: e["frame"])


def _dead_frames(events: list[dict]) -> list[tuple[int, int]]:
    evs = sorted(events, key=lambda e: e["frame"])
    out = []
    for i, e in enumerate(evs):
        if e["type"] in DEAD_FROM:
            end = next((f["frame"] for f in evs[i + 1 :] if f["type"] in DEAD_TO), None)
            out.append((int(e["frame"]), int(end) if end is not None else 1_000_000_000))
    return out


def build(run: Path, out: Path) -> None:
    """Reduce the full run's frames to the cache (one streaming pass; small memory)."""
    import numpy as np

    events = _jsonl(run / "events.jsonl")
    meta = json.loads((run / "meta.json").read_text())
    ids = [r["id"] for r in meta["roster"]]
    col = {p: i for i, p in enumerate(ids)}
    dead = _dead_frames(events)
    half = next((e["frame"] for e in events if e["type"] == "half_time"), None)
    size = int(meta["minutes"] * 60 * FPS) + 60 * FPS
    dead_at = bytearray(size)
    for a, z in dead:
        dead_at[a : min(z, size)] = b"\x01" * (min(z, size) - a)
    side, ball_x, speed = array("b"), array("f"), array("f")
    team, home_right = None, None
    with (run / "frames.jsonl").open() as fh:
        for line in fh:
            r = json.loads(line)
            n = int(r["frame"])
            b = r["ball"]
            if home_right is None:
                gk = next(p for p in r["players"] if p["team"] == "home" and p["role"] == "GK")
                home_right = gk["x"] < PITCH_X / 2
            is_dead = n < size and dead_at[n]
            beyond = not (0 <= b["x"] <= PITCH_X and 0 <= b["y"] <= PITCH_Y)
            who = r.get("possessor") or ""
            if is_dead or beyond:
                team = None
            elif who:
                team = "home" if who.startswith("h") else "away"
            side.append(0 if team is None else (1 if team == "home" else 2))
            ball_x.append(b["x"])
            v = [0.0] * len(ids)
            for p in r["players"]:
                v[col[p["id"]]] = math.sqrt(p["vx"] * p["vx"] + p["vy"] * p["vy"])  # sqrt is exact (IEEE 754)
            speed.extend(v)
    np.savez_compressed(
        out,
        side=np.frombuffer(side, np.int8),
        ball_x=np.frombuffer(ball_x, np.float32),
        speed=np.frombuffer(speed, np.float32).reshape(-1, len(ids)),
        ids=np.array(ids),
        home_right=np.array(bool(home_right)),
        half=np.array(half if half is not None else -1),
    )


@dataclass
class Truth:
    events: list[dict]  # the full match's
    shown: list[tuple[int, int]]  # footage frame windows
    side: object  # np arrays from the cache
    ball_x: object
    speed: object
    ids: list[str]
    home_right: bool
    half_frame: int
    names: dict[str, dict]  # engine id -> {name, team, number}

    # --- windows and scope -------------------------------------------------------------------
    def mask(self, f0: int, f1: int, scope: str):
        import numpy as np

        n = len(self.side)
        m = np.zeros(n, bool)
        m[max(0, f0) : min(n, f1 + 1)] = True
        if scope == "footage":
            s = np.zeros(n, bool)
            for a, z in self.shown:
                s[a : z + 1] = True
            m &= s
        return m

    def in_scope(self, e: dict, scope: str) -> bool:
        return scope == "match" or any(a <= e["frame"] <= z for a, z in self.shown)

    def coverage(self, t: float) -> float:
        """The share of the match up to t that the footage shows."""
        f = int(t * FPS)
        shown = sum(max(0, min(z, f) - a + 1) for a, z in self.shown if a <= f)
        return shown / max(1, f)

    def _evs(self, t0: float, t1: float, scope: str, types: set[str]):
        return [
            e for e in self.events if e["type"] in types and t0 <= e["t"] <= t1 and self.in_scope(e, scope)
        ]

    # --- values ------------------------------------------------------------------------------
    def goals(self, t1: float, scope: str = "match") -> list[dict]:
        return [
            {
                "minute": int(e["t"] // 60) + 1,
                "t": e["t"],
                "team": e["team"],
                "name": self.names.get(e["player"], {}).get("name"),
                "player": e["player"],
            }
            for e in self._evs(0, t1, scope, {"goal"})
        ]

    def score(self, t1: float) -> dict:
        g = self.goals(t1)
        return {"home": sum(x["team"] == "home" for x in g), "away": sum(x["team"] == "away" for x in g)}

    def count(self, metric: str, t0: float, t1: float, scope: str, edge: float = 0.0) -> dict:
        """{home, away, total} for a count metric over [t0 + edge, t1 - edge] (edge < 0 grows it)."""
        a, z = t0 + edge, t1 - edge
        if metric == "passes":
            evs = self._evs(a, z, scope, {"pass"})
        elif metric == "shots":
            evs = self._evs(a, z, scope, {"shot"})
        elif metric == "on_target":
            evs = [e for e in self._evs(a, z, scope, {"shot"}) if e.get("outcome") in ("on_target", "goal")]
        elif metric == "out_of_play":
            evs = self._evs(a, z, scope, {"out_of_play"})
        elif metric == "corners":
            by_frame = {e["frame"]: e for e in self.events if e["type"] in DEAD_TO}
            evs = [by_frame[r["frame"]] for r in restarts(self.events) if r["kind"] == "corner"]
            evs = [e for e in evs if a <= e["t"] <= z and self.in_scope(e, scope)]
        else:
            raise ValueError(metric)
        h = sum(e["team"] == "home" for e in evs)
        w = sum(e["team"] == "away" for e in evs)
        return {"home": h, "away": w, "total": len(evs)}

    def completion(self, t0: float, t1: float, scope: str) -> dict:
        out = {}
        evs = self._evs(t0, t1, scope, {"pass"})
        for k in ("home", "away", "total"):
            p = [e for e in evs if k == "total" or e["team"] == k]
            out[k] = round(100 * sum(e.get("outcome") == "success" for e in p) / len(p), 1) if p else None
        return out

    def possession(self, t0: float, t1: float, scope: str) -> float | None:
        """Home's share of time on the ball, dead ball excluded (#424's truth)."""
        m = self.mask(int(t0 * FPS), int(t1 * FPS), scope)
        h, w = int((self.side[m] == 1).sum()), int((self.side[m] == 2).sum())
        return round(100 * h / (h + w), 1) if h + w else None

    def territory(self, t0: float, t1: float, scope: str) -> dict:
        """Each side's share of in-play time with the ball in its attacking third."""
        import numpy as np

        f0, f1 = int(t0 * FPS), int(t1 * FPS)
        m = self.mask(f0, f1, scope) & (self.side > 0)
        idx = np.arange(len(self.side))
        second = idx >= self.half_frame if self.half_frame >= 0 else np.zeros(len(idx), bool)
        home_right = np.where(second, not self.home_right, self.home_right)
        x = self.ball_x
        home_att = np.where(home_right, x >= PITCH_X - THIRD_X, x <= THIRD_X)
        away_att = np.where(home_right, x <= THIRD_X, x >= PITCH_X - THIRD_X)
        n = int(m.sum())
        if not n:
            return {"home": None, "away": None}
        return {
            "home": round(100 * float((home_att & m).sum()) / n, 1),
            "away": round(100 * float((away_att & m).sum()) / n, 1),
        }

    def involvement(self, t0: float, t1: float, scope: str) -> list[tuple[str, str, int]]:
        """(name, team, n) by passes, shots and goals made, most first."""
        n: dict[str, int] = {}
        for e in self._evs(t0, t1, scope, {"pass", "shot", "goal"}):
            if e.get("player"):
                n[e["player"]] = n.get(e["player"], 0) + 1
        return sorted(
            ((self.names[p]["name"], self.names[p]["team"], k) for p, k in n.items()), key=lambda r: -r[2]
        )

    def peak_speed(self, t0: float, t1: float, scope: str) -> list[tuple[str, str, float]]:
        m = self.mask(int(t0 * FPS), int(t1 * FPS), scope)
        if not m.any():
            return []
        top = self.speed[m].max(axis=0) * 3.6
        return sorted(
            (
                (self.names[p]["name"], self.names[p]["team"], round(float(v), 1))
                for p, v in zip(self.ids, top, strict=True)
            ),
            key=lambda r: -r[2],
        )

    def distance(self, t0: float, t1: float, scope: str) -> list[tuple[str, str, float]]:
        m = self.mask(int(t0 * FPS), int(t1 * FPS), scope)
        km = self.speed[m].sum(axis=0) / FPS / 1000
        return sorted(
            (
                (self.names[p]["name"], self.names[p]["team"], round(float(v), 2))
                for p, v in zip(self.ids, km, strict=True)
            ),
            key=lambda r: -r[2],
        )

    def build_up(self, goal_t: float, team: str) -> list[dict]:
        """The scoring side's passes and shot in the move that led to a goal (since it last won the
        ball), oldest first."""
        before = [
            e
            for e in self.events
            if e["t"] <= goal_t and e["type"] in ("pass", "shot", "possession_change", "set_piece", "kickoff")
        ]
        move = []
        for e in reversed(before):
            if e["type"] in ("possession_change", "set_piece", "kickoff") and move:
                break
            if e["type"] in ("pass", "shot") and e["team"] == team:
                move.append(e)
        return [
            {
                "type": e["type"],
                "t": e["t"],
                "player": self.names.get(e["player"], {}).get("name"),
                "receiver": self.names.get(e.get("receiver"), {}).get("name"),
            }
            for e in reversed(move)
        ]


def load(run: Path, work: Path, cache: Path, fixture) -> Truth:
    """The truth for a run: its events, the footage windows, the frame cache (built if missing)
    and each engine player's name and shirt from the fixture's team sheet, by side and role (the
    sheet is public; the grader reads no player-ID feed)."""
    import numpy as np

    if not cache.exists():
        build(run, cache)
    z = np.load(cache)
    meta = json.loads((run / "meta.json").read_text())
    sheets = {side: {s.role: s for s in fixture.sheet(side)} for side in ("home", "away")}
    names = {}
    for r in meta["roster"]:
        s = sheets[r["team"]][r["role"]]
        names[r["id"]] = {"name": s.name, "team": r["team"], "number": s.number}
    return Truth(
        events=_jsonl(run / "events.jsonl"),
        shown=footage_windows(work),
        side=z["side"],
        ball_x=z["ball_x"],
        speed=z["speed"],
        ids=[str(i) for i in z["ids"]],
        home_right=bool(z["home_right"]),
        half_frame=int(z["half"]),
        names=names,
    )


def table(truth: Truth, intents: list[dict], times: list[float], windows) -> dict:
    """Every truth value the grader needs, keyed "<intent>|<t>|<window>", in both scopes: the
    frozen table the CI test grades against (no answer key needed in CI)."""
    out: dict[str, dict] = {}
    for t in times:
        for it in intents:
            for w in windows(it, t):
                key = f"{it['id']}|{t:g}|{w[0]:g}-{w[1]:g}"
                if key not in out:
                    out[key] = values(truth, it, t, w)
    return out


def values(truth: Truth, it: dict, t: float, w: tuple[float, float]) -> dict:
    """One intent's truth at time t over window w, in both scopes, plus the coverage."""
    t0, t1 = w
    m = it["metric"]
    out: dict = {"coverage": round(truth.coverage(t), 3), "t": t, "window": [t0, t1]}
    for scope in ("match", "footage"):
        v: dict = {}
        if m in ("score", "leader", "goals", "goal_build_up_home", "unmeasured", None):
            v["goals"] = truth.goals(t, scope)
            v["score"] = {k: sum(g["team"] == k for g in v["goals"]) for k in ("home", "away")}
            if m == "goal_build_up_home":
                v["build_up"] = [truth.build_up(g["t"], "home") for g in v["goals"] if g["team"] == "home"]
        elif m in ("passes", "shots", "on_target", "corners", "out_of_play"):
            v["count"] = truth.count(m, t0, t1, scope)
            v["count_lo"] = truth.count(m, t0, t1, scope, edge=1.0)
            v["count_hi"] = truth.count(m, t0, t1, scope, edge=-1.0)
        elif m == "completion":
            v["completion"] = truth.completion(t0, t1, scope)
        elif m == "possession_home":
            v["possession_home"] = truth.possession(t0, t1, scope)
        elif m in ("territory", "territory_leader"):
            v["territory"] = truth.territory(t0, t1, scope)
            v["possession_home"] = truth.possession(t0, t1, scope)
        elif m.startswith("involvement"):
            v["ranked"] = [list(r) for r in truth.involvement(t0, t1, scope)[:8]]
            for k in ("home", "away"):
                v[f"ranked_{k}"] = [list(r) for r in truth.involvement(t0, t1, scope) if r[1] == k][:5]
        elif m == "peak_speed":
            v["ranked"] = [list(r) for r in truth.peak_speed(t0, t1, scope)[:8]]
        elif m == "distance":
            v["ranked"] = [list(r) for r in truth.distance(t0, t1, scope)[:8]]
        out[scope] = v
    return out


def save(tab: dict, path: Path) -> None:
    path.write_bytes(gzip.compress((json.dumps(tab, sort_keys=True) + "\n").encode(), mtime=0))


def read(path: Path) -> dict:
    return json.loads(gzip.decompress(path.read_bytes()))
