"""The score, who scored, who made it, and the saves (GROUNDING I24), from vision's detected goals and
shot outcomes (ninety/vision/events.py, ninety/vision/outcomes.py; #271): nothing until they exist.

- A **goal** is a detected `goal` event, and the club that scored it is told by the goal it went
  into, not by a shirt's colour: the ball crossed the goal line at one end (Law 10), and each club
  attacks one end all match (home toward x = PITCH_X, the engine's convention; it does not change
  ends). A goal whose detected side disagrees with its end, or whose detection confidence is under
  the fact-checker's event gate (factcheck.MIN_CONFIDENCE), is in doubt (an own goal, or a misread),
  so the score has bounds. It is never said (Kian, Oct 26, option B): vision finds some goals and
  misses others, so a count of them would contradict the broadcast's scorebug; a score question
  names each goal it spotted instead.
- The **scorer** is the goal's shooter (`player`), named as the role gate allows (I6), else by his
  position or club.
- An **assist** is the final pass to the scorer before he scored (Opta's assist, I24): the detected
  event just before the goal's shot is a completed pass by the same side whose receiver is the
  scorer. Anything else in between (another pass, a shot), and there is no assist.
- A **save** is a detected shot whose outcome is `on_target` (#271: the keeper stopped a shot that
  was going in), credited to the club defending the end it was struck at, told the same way.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from ninety.agents.factcheck import MIN_CONFIDENCE
from ninety.intel.scene import PITCH_X, TEAMS, attacks_right, minute_of

OTHER = {"home": "away", "away": "home"}


def attacking_end(x: float) -> str:
    """The club that attacks the end nearer x (scene.attacks_right: home toward x = PITCH_X)."""
    return "home" if (x > PITCH_X / 2) == attacks_right("home") else "away"


def goals(events: Sequence[Mapping]) -> list[dict]:
    """Each detected goal with its scorer, its assist (when there was one) and its minute."""
    rows = sorted(events, key=lambda e: (float(e["t"]), str(e["id"])))
    out = []
    for k, g in enumerate(rows):
        if g.get("type") != "goal" or g.get("team") not in TEAMS:
            continue
        # The goal's shot is the event just before it, a shot by the scoring side that went in: each
        # shot is one goal's, and a goal with anything else before it has none (merge-queue review).
        prev = rows[k - 1] if k > 0 else None
        is_shot = prev is not None and prev.get("type") == "shot" and prev.get("outcome") == "goal"
        shot_i = k - 1 if is_shot and prev.get("team") == g["team"] else None
        # The goal's `player` is the scoring side's last holder (C, #271): without a shot just before it,
        # that may not be who put it in (an own goal), so no scorer is named.
        scorer = (g.get("player") or rows[shot_i].get("player")) if shot_i is not None else None
        assister = None
        if shot_i is not None and shot_i > 0:
            before = rows[shot_i - 1]
            if (
                before.get("type") == "pass" and before.get("outcome") == "success"
                and before.get("team") == g["team"] and scorer and before.get("receiver") == scorer
                and before.get("player") and before["player"] != scorer
            ):
                assister = before["player"]
        end = attacking_end(float(g["x"])) if g.get("x") is not None else None
        sure = g.get("confidence") is None or float(g["confidence"]) >= MIN_CONFIDENCE
        known = end is not None and end == g["team"] and sure
        out.append(
            {
                "id": f"goal:{g['id']}",
                "kind": "goal",
                "team": g["team"],
                "minute": minute_of(float(g["t"])),
                "t": round(float(g["t"]), 2),
                "event": g["id"],
                "event_confidence": g.get("confidence"),
                "team_confidence": g.get("team_confidence"),
                "side_known": known,
                "player": scorer,
                "assister": assister,
                "players": [p for p in (scorer, assister) if p],
                "confident": known,
            }
        )
    return out


def saves(events: Iterable[Mapping]) -> list[dict]:
    """Each shot the keeper stopped (#271's `on_target`), for the club that saved it."""
    return [
        {
            "id": f"save:{e['id']}",
            "kind": "save",
            "team": OTHER[attacking_end(float(e["x"]))],  # the club defending the end it was struck at
            "minute": minute_of(float(e["t"])),
            "t": round(float(e["t"]), 2),
            "side_known": True,
            # A save is as sure as the shot's detection (the fact-checker's event gate).
            "confident": e.get("confidence") is None or float(e["confidence"]) >= MIN_CONFIDENCE,
        }
        for e in events
        if e.get("type") == "shot" and e.get("outcome") == "on_target" and e.get("x") is not None
    ]


def score(goal_rows: Sequence[Mapping], minute_to: int, clubs: Mapping[str, str]) -> dict:
    """The score after `minute_to`: each club's goals, with bounds from goals of unknown side, for
    code's bookkeeping only: never said, never confident (option B)."""
    window = [g for g in goal_rows if g["minute"] <= minute_to]
    unknown = sum(not g["side_known"] for g in window)
    n = {t: sum(g["side_known"] and g["team"] == t for g in window) for t in TEAMS}
    return {
        "id": f"score:m{minute_to}",
        "kind": "score",
        "metric": "score",
        "team": None,
        "minute": minute_to,
        "value": n["home"],
        "unit": "goals",
        # The away club's goals are the number after its name (lesson 221: each number its own role).
        "also": [[n["away"], "goals", rf"\b{clubs['away']}\b[^.\d]*$"]],
        "home": n["home"],
        "away": n["away"],
        "lo": dict(n),
        "hi": {t: n[t] + unknown for t in TEAMS},
        # Never said (Kian, Oct 26): vision finds some goals and misses others, so a count of them
        # would contradict the broadcast's scorebug. The goals it did spot are said one by one.
        "confident": False,
        "in_doubt": unknown > 0,
    }


# The score as the broadcast's scorebug shows it, read from the graphic's pixels (ninety/vision/
# scorebug.py, #356), never counted from goals: `score_read` (a reading held, the first one so a clip
# that starts at 2-1 has a score) and `score_change` (a change, with the side that scored). Measured
# on the validation clips against a bar stated first (docs/eval/scorebug-plan.md, "Validation,
# current reader"): no false change (16 of 16 match a true goal of their side), 880 of 880 digits
# right, 16 of 16 goals found, on our renderer's fixed scorebug only (scores of 10 or more, an
# absent or occluded bug and replay graphics are unmeasured). So a score is said as the bug shows it.
SCOREBUG_MEASURED = True
SCORE_TYPES = ("score_read", "score_change")


def scorebug(events: Iterable[Mapping]) -> list[dict]:
    """Each score the scorebug was read to show, oldest first: the first reading, then each one that
    differs from the last (a reading held again says nothing new)."""
    out = []
    last = None
    for e in sorted((e for e in events if e.get("type") in SCORE_TYPES and e.get("score")),
                    key=lambda e: (e["t"], e["id"])):
        held = (int(e["score"]["home"]), int(e["score"]["away"]))
        if held == last:
            continue
        last = held
        conf = e.get("confidence")
        out.append({
            "id": f"scorebug:{e['id']}", "kind": "scorebug", "metric": "scorebug", "team": None,
            "minute": minute_of(float(e["t"])), "t": round(float(e["t"]), 2), "event": e["id"],
            "home": int(e["score"]["home"]), "away": int(e["score"]["away"]), "source": "scorebug",
            "event_confidence": conf,
            "confident": SCOREBUG_MEASURED and (conf is None or float(conf) >= MIN_CONFIDENCE),
        })
    return out


def save_counts(save_rows: Sequence[Mapping], minute_from: int, minute_to: int) -> dict[str, dict]:
    window = [s for s in save_rows if minute_from <= s["minute"] <= minute_to]
    unknown = sum(not s["confident"] for s in window)
    out = {}
    for team in TEAMS:
        n = sum(s["confident"] and s["team"] == team for s in window)
        out[team] = {
            "id": f"saves:{team}:m{minute_from}-{minute_to}",
            "kind": "saves",
            "metric": "saves",
            "team": team,
            "minute_from": minute_from,
            "minute_to": minute_to,
            "value": n,
            "unit": "saves",
            "lo": n,
            "hi": n + unknown,
            "confident": unknown == 0,
        }
    return out


__all__ = ["SCOREBUG_MEASURED", "goals", "save_counts", "saves", "score", "scorebug"]
