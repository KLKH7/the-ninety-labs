"""Who has the ball now, and where: the phone's "attacking now" layer, from the video alone.

Live path: it reads only the vision observations, through the same tracks, ball path and ball
spells the event detector reads (ninety/vision/events.py), never the answer key. Code decides
everything here; no model is asked.

At each of the phone's minimap frames (every STEP_S), the team in possession is the side of the
player in the latest ball spell, held for HOLD_S after the spell ends. Its confidence is that
player's side confidence (`track.assign_teams`, a score, not a probability) times an age factor
falling from 1 to 0 over HOLD_S. The third is where the ball is, along the direction that team
attacks. The phone shows a phase only above SHOW, says "likely" below SURE, and says
"attacking" only when it is sure and the ball is plainly in the final third
(docs/eval/possession.md measures all three, and sets SHOW and SURE on validation clips).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ninety.vision import events as ev
from ninety.vision import track as tr

STEP_S = 0.2  # the phone's minimap frame (web/phone/src/clock.ts TOLERANCE_S): no finer than it draws
# Design: one pass and a touch. After the last player seen with the ball, his side is still the
# likeliest to have it this long; past it the phone stops saying who has it.
HOLD_S = 4.0
PITCH_X = ev.PITCH_X
THIRD_M = PITCH_X / 3  # the broadcast's thirds of the pitch's length (Law 1 length, GROUNDING L1)
# A ball within this of a third's line could be on either side of it: the players' measured
# position error, 90th percentile (ninety/vision/events.RIVAL_M, docs/eval/attribution-derive.md).
EDGE_M = ev.RIVAL_M
THIRDS = ("own", "middle", "final")
CALIBRATION = Path(__file__).resolve().parents[2] / "docs" / "eval" / "possession-calibration.json"


@dataclass(frozen=True)
class Phase:
    t: float
    team: str | None  # "home", "away", or None: nobody seen with the ball for HOLD_S
    third: str | None  # of the pitch, along the direction `team` attacks
    plainly: bool  # the ball is more than EDGE_M from either line of its third
    confidence: float  # 0 to 1: the side's confidence times the age factor


def attacks_right(team: str) -> bool:
    return ev._attacks_right(team)  # the detector's convention, the same for every half


def third_of(x: float, team: str) -> tuple[str, bool]:
    """The third the ball at x is in, for `team`, and whether it is plainly inside it."""
    along = x if attacks_right(team) else PITCH_X - x
    i = min(2, max(0, int(along // THIRD_M)))
    lines = [line for line in (THIRD_M, 2 * THIRD_M) if abs(along - line) < EDGE_M]
    return THIRDS[i], not lines


def timeline(rows: list[dict]) -> list[Phase]:
    """A Phase every STEP_S over the clip's frames."""
    if not rows:
        return []
    tracks = tr.track_players(rows)
    tr.assign_teams(tracks)
    path = tr.ball_path(rows)
    spells = [s for s in ev.spells(path, tracks) if s.track.team is not None]
    ball = {p.frame: p for p in path}
    t_of = {r["frame"]: r["t"] for r in rows}
    first, last = rows[0]["frame"], rows[-1]["frame"]
    step = round(STEP_S * tr.FPS)
    out = []
    for frame in range(first, last + 1, step):
        t = t_of.get(frame, rows[0]["t"] + (frame - first) / tr.FPS)
        held = [s for s in spells if s.first <= frame]
        spell = held[-1] if held else None
        age_s = max(0, frame - spell.last) / tr.FPS if spell else None
        if spell is None or age_s > HOLD_S:
            out.append(Phase(round(t, 2), None, None, False, 0.0))
            continue
        team = spell.track.team
        seen = [p for f, p in ball.items() if spell.first <= f <= frame]
        where = max(seen, key=lambda p: p.frame) if seen else ball[spell.last]
        third, plainly = third_of(where.x, team)
        conf = (spell.track.side_confidence or 0.0) * (1 - age_s / HOLD_S)
        out.append(Phase(round(t, 2), team, third, plainly, round(conf, 3)))
    return out


def gates(path: Path = CALIBRATION) -> tuple[float | None, float | None, bool]:
    """SHOW, SURE and whether "attacking" may be said, as measured on the validation clips
    (ninety/eval/possession_score.py): None when no cut-off reached its target and its evidence
    floor, which never shows (SHOW) or never says sure (SURE); "attacking" only if its own bar opened."""
    body = json.loads(path.read_text())
    return body["show"], body["sure"], bool(body["attacking"])


def on_screen(p: Phase, show: float | None, sure: float | None, attacking_open: bool = False) -> dict:
    """What the phone may draw for a phase: nothing below SHOW; "likely" below SURE; "attacking"
    only when its own bar opened, the phase is sure and the ball plainly in the final third."""
    if p.team is None or show is None or p.confidence < show:
        return {"t": p.t, "team": None, "third": None, "label": "unknown", "sure": False}
    is_sure = sure is not None and p.confidence >= sure
    attacking = attacking_open and is_sure and p.third == "final" and p.plainly
    return {"t": p.t, "team": p.team, "third": p.third, "label": "attacking" if attacking else "possession",
            "sure": is_sure}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="A clip's possession timeline from its observations.")
    ap.add_argument("observations", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    phases = timeline(tr.read_observations(args.observations))
    args.out.write_text(json.dumps([asdict(p) for p in phases], separators=(",", ":")) + "\n")
    print(f"wrote {args.out}: {len(phases)} phases")


if __name__ == "__main__":
    main()
