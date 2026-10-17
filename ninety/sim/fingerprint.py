"""A team's style fingerprint, measured from what a match produced (docs/decisions/0002).

Every measure is computed from simulator events and frames after the match: it reports whether a
style did what its name says, never steers the engine (ENGINE.md, "Using the research").
"""

from __future__ import annotations

import math
from statistics import median

PITCH_X = 105.0
LONG_PASS_M = 32.0  # a long ball: about 35 yards, the common event-data definition (*verify*)
FAST_ATTACK_S = 10.0  # a shot within this long of winning the ball counts as a fast attack (*design*)
PPDA_ZONE = 0.6  # PPDA counts the opponents' passes in their own 60% of the pitch
DEFENSIVE_ACTIONS = {"tackle", "interception"}
SHOT_BANDS_M = (12.0, 20.0)  # close, middle, far


def own_goal_x(team: str) -> float:
    return 0.0 if team == "home" else PITCH_X


def forward(team: str) -> float:
    return 1.0 if team == "home" else -1.0


def other(team: str) -> str:
    return "away" if team == "home" else "home"


def from_own_goal(team: str, x: float) -> float:
    return abs(x - own_goal_x(team))


def team_fingerprint(team: str, events: list[dict], possession_frames: list[str | None],
                     minutes: float) -> dict:
    """The fingerprint of one team. `possession_frames` is the team ("home", "away" or None) on the
    ball in each sampled frame."""
    opp = other(team)
    passes = [e for e in events if e["type"] == "pass" and e["team"] == team and e.get("end_x") is not None]
    # PPDA: their passes in their own 60% of the pitch, per defensive action of ours in that zone.
    their_passes = sum(1 for e in events if e["type"] == "pass" and e["team"] == opp
                       and from_own_goal(opp, e["x"]) <= PPDA_ZONE * PITCH_X)
    actions = sum(1 for e in events if e["type"] in DEFENSIVE_ACTIONS and e["team"] == team
                  and from_own_goal(opp, e["x"]) <= PPDA_ZONE * PITCH_X)
    regains = [e for e in events if e["type"] == "possession_change" and e["team"] == team]
    shots = [e for e in events if e["type"] == "shot" and e["team"] == team]
    goal_x = PITCH_X - own_goal_x(team)
    bands = [0, 0, 0]
    for s in shots:
        d = math.hypot(goal_x - s["x"], 34.0 - s["y"])
        bands[sum(d > b for b in SHOT_BANDS_M)] += 1
    fast = sum(1 for s in shots if any(0 <= s["t"] - r["t"] <= FAST_ATTACK_S for r in regains))
    on_ball = sum(1 for p in possession_frames if p == team)
    owned = sum(1 for p in possession_frames if p is not None)
    possession = on_ball / owned if owned else 0.0
    attacking_third = [e for e in passes if from_own_goal(team, e["x"]) >= 2 * PITCH_X / 3]
    their_attacking_third = sum(1 for e in events if e["type"] == "pass" and e["team"] == opp
                                and from_own_goal(opp, e["x"]) >= 2 * PITCH_X / 3)
    tilt_total = len(attacking_third) + their_attacking_third
    return {
        "possession": possession,
        "passes": len(passes),
        "completion": (sum(e.get("outcome") == "success" for e in passes) / len(passes)) if passes else 0.0,
        "forward_m_per_pass": (sum(forward(team) * (e["end_x"] - e["x"]) for e in passes) / len(passes))
        if passes else 0.0,
        "long_share": (sum(math.hypot(e["end_x"] - e["x"], e["end_y"] - e["y"]) >= LONG_PASS_M
                           for e in passes) / len(passes)) if passes else 0.0,
        "tempo": len(passes) / (possession * minutes) if possession * minutes > 0 else 0.0,
        "ppda": their_passes / actions if actions else math.inf,
        "regain_m": median(from_own_goal(team, e["x"]) for e in regains) if regains else math.nan,
        "field_tilt": len(attacking_third) / tilt_total if tilt_total else 0.5,
        "shots": len(shots),
        "shots_by_band": bands,
        "fast_attack_shots": fast,
        "goals": sum(1 for e in events if e["type"] == "goal" and e["team"] == team),
    }


def match_fingerprints(events: list[dict], frames: list[dict], minutes: float, every: int = 5) -> dict:
    """Both teams' fingerprints. Possession is sampled every `every` frames from who has the ball."""
    owner = [(f["possessor"] and ("home" if f["possessor"].startswith("h") else "away")) or None
             for f in frames[::every]]
    return {team: team_fingerprint(team, events, owner, minutes) for team in ("home", "away")}
