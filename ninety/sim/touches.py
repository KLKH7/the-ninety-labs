"""How players meet the ball: every deliberate touch and every body hit, who made it, on what
surface, how fast the ball came at him, and what became of it; and how throw-ins turn out,
beside published figures. A report, never a gate, and it never changes the engine: `Watch` only
listens to the engine's own calls and passes every one through unchanged (a test runs both and
compares). The comparisons it is read against were fixed before the engine changed
(docs/EVALUATION.md, 'Match engine: touches').

    uv run python -m ninety.sim.touches --seeds 40,41,42,43,44,45,46,47   # writes docs/eval/touches.md
"""

from __future__ import annotations

import argparse
import math
from bisect import bisect_left
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from statistics import median

from ninety.sim import decisions
from ninety.sim.body import relative_speed
from ninety.sim.engine import BODY_TOUCH_Z, FPS, Engine, Match

ROOT = Path(__file__).resolve().parents[2]
KEEP_WINDOW_S = 10.0  # a ball nobody has within this long after a touch was not kept by him
HELD_AFTER_S = 5.0  # a throw-in's possession is read this long after the throw
STOPS = {"out_of_play", "offside", "foul", "goal"}  # play stopped: whatever followed was a restart
WHO = ("intended receiver", "team-mate", "opponent", "shot", "loose ball", "own dribble")
SURFACES = ("foot", "air", "hands")
SPEED_BINS = (0.0, 6.0, 12.0, 18.0, 24.0, math.inf)  # m/s, the ball relative to the player
# Published comparisons, for reading the report only (docs/EVALUATION.md): Stone, Smith and Barry
# 2021, 16,154 Premier League throw-ins, 2018-19; R3 for pass completion (itself *verify*).
THROW_FIRST_CONTACT = 0.83
THROW_RETAINED = 0.54
COMPLETION = "75 to 88% (R3, *verify*)"


class Watch(Engine):
    """The engine, listened to. Each override reads the state it is given, before the engine
    changes it (LESSONS 7), then hands the call on unchanged and returns what the engine returns."""

    def __init__(self, seed: int):
        super().__init__(seed)
        self.touch_log: list[dict] = []
        self.throw_log: list[dict] = []
        self._touch: tuple[str, float, bool, bool] | None = None  # (player, height, aerial, hands)

    def _show_touch(self, p, cx, cy, cz, aerial):
        # contact() names the part only for a deliberate touch, just before touched() resolves it.
        self._touch = (p.id, cz, aerial, self.hands(p, cx, cy))
        return super()._show_touch(p, cx, cy, cz, aerial)

    def touched(self, p, x, y, controls):
        deliberate = self._touch is not None and self._touch[0] == p.id
        z, aerial, hands = self._touch[1:] if deliberate else (self.ball[2], None, self.hands(p, x, y))
        self._touch = None
        vx, vy, vz = self.ball[3], self.ball[4], self.ball[5]
        rec = {
            "frame": self.frame, "player": p.id, "team": p.team, "who": self.who(p),
            "kind": "touch" if deliberate else "body", "z": z, "aerial": aerial, "hands": hands,
            "rel": relative_speed(vx, vy, vz, p.vx, p.vy),
            "reacted": self.t - self.reacting_since(p) >= self.reaction(p),
            "controls": controls,
        }
        self.touch_log.append(rec)
        stopped = super().touched(p, x, y, controls)
        rec["stopped"] = bool(stopped)
        return stopped

    def deflect(self, p, cx, cy, cz, keep, at=None):
        last = self.touch_log[-1] if self.touch_log else None
        if last and last["player"] == p.id and last["kind"] == "body" and last["frame"] == self.frame:
            last["z"] = cz  # the height where the body met it, which touched() is not given
        return super().deflect(p, cx, cy, cz, keep, at)

    def pass_to(self, carrier, tx, ty, lofted, throw=False, pace=decisions.ARRIVE_MPS, receiver=None):
        before = len(self.match.events)
        out = super().pass_to(carrier, tx, ty, lofted, throw, pace, receiver)
        new = self.match.events[before:]
        if throw and new and new[-1]["type"] == "pass":  # thrown now, not still turning to throw
            self.throw_log.append({"frame": self.frame, "team": carrier.team, "taker": carrier.id})
        return out

    def who(self, p) -> str:
        """Whose ball this was when it reached him, read before the touch resolves it."""
        k = self.kicked
        if k and k["type"] == "shot":
            return "shot"
        if k and k["type"] == "pass":
            if p.id == self.intended:
                return "intended receiver"
            return "team-mate" if p.team == k["team"] else "opponent"
        if p.id == self.dribbler:
            return "own dribble"
        return "loose ball"


def surface(rec: dict) -> str:
    if rec["hands"]:
        return "hands"
    if rec["kind"] == "touch":
        return "air" if rec["aerial"] else "foot"
    return "air" if rec["z"] > BODY_TOUCH_Z else "foot"


def stop_frames(m: Match) -> list[int]:
    return sorted(e["frame"] for e in m.events if e["type"] in STOPS)


def follow(m: Match, rec: dict, stops: list[int]) -> dict:
    """What became of a touch, read off the frames: was he the next player to have the ball, with
    no stoppage first (kept); how far from him it was as the touch left it (met); and, if he did
    not have it at once, how long that took and the furthest it got from him on the way. The
    engine's own verdict at the touch is `controls`."""
    f0 = rec["frame"]
    stop = next((s for s in stops[bisect_left(stops, f0):]), math.inf)
    out = {"kept": False, "met_m": None, "after_s": None, "far_m": None}
    far = None
    for f in m.frames[f0 : f0 + int(KEEP_WINDOW_S * FPS)]:
        if f["frame"] >= stop:
            break
        me = next(q for q in f["players"] if q["id"] == rec["player"])
        gap = math.hypot(f["ball"]["x"] - me["x"], f["ball"]["y"] - me["y"])
        if f["frame"] == f0:
            out["met_m"] = gap
        else:
            far = max(far or 0.0, gap)
        if f["possessor"]:
            if f["possessor"] == rec["player"]:
                out.update(kept=True, after_s=(f["frame"] - f0) / FPS, far_m=far)
            break
    return out


def quantile(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, math.ceil(q * len(xs)) - 1))]


def throw_outcome(m: Match, throw: dict, touches: list[dict], stops: list[int]) -> dict | None:
    """First contact after the throw (a team-mate's, an opponent's, or none before play stopped),
    and which team had the ball last, HELD_AFTER_S later."""
    f0 = throw["frame"]
    end = f0 + int(HELD_AFTER_S * FPS)
    if end >= len(m.frames):
        return None  # thrown too near the end to read
    stop = next((s for s in stops[bisect_left(stops, f0):]), math.inf)
    first = next((r for r in touches if r["frame"] >= f0 and r["player"] != throw["taker"]), None)
    if first and first["frame"] > stop:
        first = None
    team_of = {r["id"]: r["team"] for r in m.roster}
    holder = next((f["possessor"] for f in reversed(m.frames[f0 : end + 1]) if f["possessor"]), None)
    mate = bool(first) and first["team"] == throw["team"]
    return {"mate": mate, "mate_controls": mate and first["controls"] and not first["stopped"],
            "mate_kept": mate and first["kept"],
            "held": bool(holder) and team_of[holder] == throw["team"]}


def measure(seed: int, minutes: float = 90) -> dict:
    e = Watch(seed)
    m = e.run(minutes)
    touches, stops = e.touch_log, stop_frames(m)
    for rec in touches:
        rec.update(follow(m, rec, stops))
        rec["surface"] = surface(rec)
    throws = [o for o in (throw_outcome(m, t, touches, stops) for t in e.throw_log) if o]
    passes = [ev for ev in m.events if ev["type"] == "pass"]
    return {"seed": seed, "touches": touches, "throws": throws, "passes": len(passes),
            "completed": sum(ev.get("outcome") == "success" for ev in passes)}


def pct(part: int, whole: int) -> str:
    return f"{part / whole:.1%}" if whole else "n/a"


def report(results: list[dict], minutes: float = 90) -> str:
    touches = [r for res in results for r in res["touches"]]
    deliberate = [r for r in touches if r["kind"] == "touch"]
    body = [r for r in touches if r["kind"] == "body"]
    seeds = ", ".join(str(r["seed"]) for r in results)
    lines = [
        "# Touches",
        "",
        f"Generated by `uv run python -m ninety.sim.touches` on seeds {seeds}, {minutes:g} minutes "
        "each. A report beside published figures, never a target: nothing in the engine is tuned to "
        "these numbers. The comparisons are fixed in docs/EVALUATION.md ('Match engine: touches').",
        "",
        "A **deliberate touch** is a player who has reacted to the ball playing it (foot, or above "
        f"{BODY_TOUCH_Z} m thigh, chest or head, shown here as *air*, or a keeper's hands). A **body "
        "hit** is the ball meeting a body that is not playing it. **Controlled** is the engine's "
        "verdict at the touch; **kept** is read off the frames afterwards: he was the next player to "
        f"have the ball, within {KEEP_WINDOW_S:g} s, before any stoppage. Speeds are the ball's "
        "relative to the player as it arrived.",
        "",
        "## Deliberate touches by surface",
        "",
        "| Surface | Touches | Controlled | Kept | Median speed, m/s |",
        "|---|---|---|---|---|",
    ]
    for s in (*SURFACES, "all but own dribble", None):
        rows = [r for r in deliberate if s is None or r["surface"] == s
                or (s == "all but own dribble" and r["who"] != "own dribble")]
        if rows:
            lines.append(
                f"| {s or 'all'} | {len(rows)} | {pct(sum(r['controls'] for r in rows), len(rows))} "
                f"| {pct(sum(r['kept'] for r in rows), len(rows))} | {median(r['rel'] for r in rows):.1f} |")
    failed = [r for r in deliberate if not r["controls"]]
    aloft = sum(r["surface"] == "air" for r in failed)
    lines += ["", f"Failed deliberate touches: {len(failed)}, of which {aloft} in the air.", "",
              "## By whose ball it was (controlled, of touches)", "",
              "| Whose ball | " + " | ".join(SURFACES) + " | all |", "|---" * (len(SURFACES) + 2) + "|"]
    for w in WHO:
        cells = []
        for s in (*SURFACES, None):
            rows = [r for r in deliberate if r["who"] == w and (s is None or r["surface"] == s)]
            cells.append(f"{pct(sum(r['controls'] for r in rows), len(rows))} of {len(rows)}" if rows else "")
        lines.append(f"| {w} | " + " | ".join(cells) + " |")
    lines += ["", "## By arriving speed (controlled, of touches)", "",
              "| Speed, m/s | " + " | ".join(SURFACES) + " |", "|---" * (len(SURFACES) + 1) + "|"]
    for lo, hi in zip(SPEED_BINS, SPEED_BINS[1:], strict=False):
        cells = []
        for s in SURFACES:
            rows = [r for r in deliberate if r["surface"] == s and lo <= r["rel"] < hi]
            cells.append(f"{pct(sum(r['controls'] for r in rows), len(rows))} of {len(rows)}" if rows else "")
        label = f"{lo:g} to {hi:g}" if hi < math.inf else f"{lo:g} and over"
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    lines += ["", "## Where a kept ball ends up", "",
              "*Met at* is how far the ball was from his centre at the end of the frame he touched it. "
              "A ball he did not have at once (a touch that left it loose, which he got back): how "
              "long that took and the furthest it got from him on the way.", "",
              "| Surface | Kept | Had at once | Met at, median m | Not at once: median s "
              "| furthest, median m | furthest, 90th percentile m |",
              "|---|---|---|---|---|---|---|"]
    for s in SURFACES:
        rows = [r for r in deliberate if r["surface"] == s and r["kept"]]
        if rows:
            later = [r for r in rows if r["after_s"] > 0]
            tail = (f"{median(r['after_s'] for r in later):.2f} | {median(r['far_m'] for r in later):.2f} "
                    f"| {quantile([r['far_m'] for r in later], 0.9):.2f}") if later else "| |"
            lines.append(f"| {s} | {len(rows)} | {pct(len(rows) - len(later), len(rows))} "
                         f"| {median(r['met_m'] for r in rows):.2f} | {tail} |")
    lines += ["", "## Body hits (the ball meets a body that is not playing it)", "",
              "| | foot height | in the air | Median speed, m/s |", "|---|---|---|---|"]
    for reacted, label in ((False, "not reacted"), (True, "reacted, a glancing ball")):
        rows = [r for r in body if r["reacted"] == reacted and not r["hands"]]
        if rows:
            low = sum(r["surface"] == "foot" for r in rows)
            lines.append(f"| {label} | {low} | {len(rows) - low} | {median(r['rel'] for r in rows):.1f} |")
    throws = [t for res in results for t in res["throws"]]
    n = len(throws)
    passes = sum(r["passes"] for r in results)
    lines += [
        "", "## Throw-ins", "",
        f"{n} throw-ins ({n / len(results):.1f} a match).", "",
        "| Measure | Engine | Published |", "|---|---|---|",
        f"| first contact by a team-mate | {pct(sum(t['mate'] for t in throws), n)} "
        f"| {THROW_FIRST_CONTACT:.0%} (Stone, Smith and Barry 2021) |",
        f"| first contact by a team-mate who controls it "
        f"| {pct(sum(t['mate_controls'] for t in throws), n)} | |",
        f"| first contact by a team-mate who keeps it | {pct(sum(t['mate_kept'] for t in throws), n)} | |",
        f"| possession held {HELD_AFTER_S:g} s later | {pct(sum(t['held'] for t in throws), n)} "
        f"| {THROW_RETAINED:.0%} retained (Stone 2021, by their own definition of retained, *verify*) |",
        "", "## Passes", "",
        "| Measure | Engine | Published |", "|---|---|---|",
        f"| completion | {pct(sum(r['completed'] for r in results), passes)} of {passes} | {COMPLETION} |",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", default="40,41,42,43,44,45,46,47")
    ap.add_argument("--minutes", type=float, default=90)
    ap.add_argument("--out", type=Path, default=ROOT / "docs/eval/touches.md")
    args = ap.parse_args()
    seeds = [int(s) for s in args.seeds.split(",")]
    with ProcessPoolExecutor() as pool:
        results = list(pool.map(measure, seeds, [args.minutes] * len(seeds)))
    text = report(results, args.minutes)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
