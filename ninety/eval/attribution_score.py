"""Score who detected events name (team, passer, receiver, interceptor) against the ground truth.

    uv run python -m ninety.eval.attribution_score --test-dir runs/test-frozen-cca498c/test \\
        --observations <dir of observations-seed<N>.jsonl> --out docs/eval/attribution

Grading, so it reads the answer key; nothing on the live path imports it. The rule it grades
(ninety/vision/events.py, `attribute`, RIVAL_M) was fixed and pushed before this was first run.

Matching. A detected event is paired with a true event of the same type within 1.0 s, one to one,
the pairs closest in time first: the event scorer's rule (ninety/eval/event_score.py) without its
team condition, since the team is what is graded here. Out of play is graded on team only (the
truth names nobody for it).

Who a named track is. The track's detection in the event's frame (the observations line holding
that track's position there) is paired with the true player whose box overlaps it most, IoU at
least 0.5 (the pixel scorer's player rule, as ninety/eval/pitch_score.py). The name is right when
that player is the true event's player (or receiver, or interceptor). A named track whose box pairs
with nobody cannot be checked: it counts as not right, so leaving the hard cases out cannot raise
the accuracy.
"""

from __future__ import annotations

import argparse
import datetime
import json
from collections import Counter
from pathlib import Path

from ninety.eval.event_score import EPS, WINDOW_S, git_commit, load_events, ratio
from ninety.eval.pitch_score import PLAYER_IOU, SCORE_MIN, _iou
from ninety.vision import events as ev
from ninety.vision import track as tr

COMMAND = ("uv run python -m ninety.eval.attribution_score --test-dir runs/test-frozen-cca498c/test "
           "--observations docs/eval/attribution --observations tests/fixtures --out docs/eval/attribution")
TYPES = ("pass", "shot", "out_of_play")
ROLES = ("player", "receiver", "interceptor")
# The roles the detector names, per type: out of play names nobody (nor does the truth).
NAMED = {"pass": ROLES, "shot": ("player",), "out_of_play": ()}


def match(truth: list[dict], detected: list[dict]) -> list[tuple[dict, dict]]:
    """(true, detected) pairs: same type, at most WINDOW_S apart, one to one, nearest in time first,
    ties by list order."""
    cands = sorted((abs(d["t"] - t["t"]), i, j) for i, t in enumerate(truth) for j, d in enumerate(detected)
                   if t["type"] == d["type"] and abs(d["t"] - t["t"]) <= WINDOW_S + EPS)
    used_t, used_d, pairs = set(), set(), []
    for _, i, j in cands:
        if i in used_t or j in used_d:
            continue
        used_t.add(i)
        used_d.add(j)
        pairs.append((truth[i], detected[j]))
    return sorted(pairs, key=lambda p: p[1]["t"])


def who(name: str, frame: int, tracks: dict[int, tr.Track], obs: dict[int, dict],
        truth_frames: dict[int, dict]) -> str | None:
    """The true player behind a named track (`h-t12`) at this frame, or None when its box pairs with
    nobody."""
    return truth_player(tracks[int(name.split("-t")[1])], frame, obs, truth_frames, name)


def truth_player(t: tr.Track, frame: int, obs: dict[int, dict], truth_frames: dict[int, dict],
                 name: str = "track") -> str | None:
    """The true player whose box the track's detection at this frame overlaps most (IoU at least
    0.5), or None."""
    xy = t.at(frame)
    dets = [d for d in obs[frame]["players"] if d["score"] >= SCORE_MIN and (d["x"], d["y"]) == xy]
    if xy is None or len(dets) != 1:
        raise ValueError(f"{name} at frame {frame}: not one detection at its tracked position")
    labelled = [p for p in truth_frames[frame]["players"] if p.get("bbox") and p.get("visibility", 0) > 0]
    best = max(labelled, key=lambda p: _iou(p["bbox"], dets[0]["bbox"]), default=None)
    return best["id"] if best is not None and _iou(best["bbox"], dets[0]["bbox"]) >= PLAYER_IOU else None


def role_frame(event: dict, role: str, detected_frames: dict[str, int]) -> int:
    """The frame a role is judged at: the strike for the passer, the next spell's first frame for
    the one who got the ball (written by the detector beside the event)."""
    return event["frame"] if role == "player" else detected_frames[event["id"]]


def observations_file(seed: int, dirs: list[Path]) -> Path:
    """The clip's observations from the first directory holding them."""
    name = f"observations-seed{seed}.jsonl"
    found = next((d / name for d in dirs if (d / name).exists()), None)
    if found is None:
        raise FileNotFoundError(f"{name} in none of {[str(d) for d in dirs]}")
    return found


def clip(seed: int, test_dir: Path, observations: Path | list[Path]) -> dict:
    root = test_dir / f"seed{seed}"
    truth = [e for e in load_events(root / "events.jsonl", "truth") if e["type"] in TYPES]
    frames = {f["frame"]: f for f in map(json.loads, (root / "frames.jsonl").read_text().splitlines())}
    dirs = observations if isinstance(observations, list) else [observations]
    rows = tr.read_observations(observations_file(seed, dirs))
    detected, summary = ev.detect(rows)
    tracks = {t.id: t for t in tr.track_players(rows)}
    tr.assign_teams(list(tracks.values()))
    obs = {r["frame"]: r for r in rows}
    got = got_ball_frames(rows, detected)
    out = []
    for t, d in match(truth, detected):
        rec = {"type": t["type"], "truth_id": t["id"], "detected_id": d["id"],
               "dt_s": round(d["t"] - t["t"], 3), "team": {"truth": t["team"], "detected": d["team"]}}
        for role in NAMED[t["type"]]:
            named = d.get(role)
            actual = who(named, role_frame(d, role, got), tracks, obs, frames) if named else None
            rec[role] = {"truth": t.get(role), "detected": named, "is": actual}
        out.append(rec)
    matched = {r["detected_id"] for r in out}
    return {
        "seed": seed,
        "truth": dict(Counter(e["type"] for e in truth)),
        "detected": dict(Counter(e["type"] for e in detected)),
        # A false event's names, and who they are: what the agents would be told about nobody's action.
        "unmatched_detected": [{"id": e["id"], "type": e["type"], **{k: e[k] for k in ROLES if e.get(k)},
                                "is": {k: who(e[k], role_frame(e, k, got), tracks, obs, frames)
                                       for k in ROLES if e.get(k)}}
                               for e in detected if e["id"] not in matched],
        "camera_ok": f"{summary['frames_camera_ok']} of {summary['frames']} frames",
        "teams": summary["teams"],
        "pairs": out,
    }


def got_ball_frames(rows: list[dict], detected: list[dict]) -> dict[str, int]:
    """For each pass, the first frame of the next spell (where its receiver or interceptor is named),
    found as the detector finds it."""
    tracks = tr.track_players(rows)
    tr.assign_teams(tracks)
    path = tr.ball_path(rows)
    firsts = sorted(s.first for s in ev.spells(path, tracks))
    return {e["id"]: next((f for f in firsts if f > e["frame"]), e["frame"])
            for e in detected if e["type"] == "pass"}


def grade(clips: list[dict]) -> dict:
    """Per type: team accuracy over matched events; per role, how many the truth names, how many the
    detector names, and how many of those are the right player."""
    out: dict[str, dict] = {}
    for kind in TYPES:
        pairs = [p for c in clips for p in c["pairs"] if p["type"] == kind]
        right_team = sum(1 for p in pairs if p["team"]["truth"] == p["team"]["detected"])
        row = {"matched": len(pairs), "team_right": right_team,
               "team_accuracy": ratio(right_team, len(pairs))}
        for role in NAMED[kind]:
            rs = [p[role] for p in pairs]
            named = [r for r in rs if r["detected"]]
            right = [r for r in named if r["is"] is not None and r["is"] == r["truth"]]
            row[role] = {
                "truth_names": sum(1 for r in rs if r["truth"]),
                "named": len(named),
                "right": len(right),
                "unchecked": sum(1 for r in named if r["is"] is None),
                "accuracy": ratio(len(right), len(named)),
                "left_null": sum(1 for r in rs if r["truth"] and not r["detected"]),
            }
        out[kind] = row
    return out


def report_md(body: dict) -> str:
    g = body["grade"]
    lines = [
        "# Who detected events name: team and track, against the ground truth",
        "",
        f"Generated by `{body['command']}` at commit `{body['commit']}`, {body['date']}. Offline grading:",
        "the live path never reads this or the answer key (tests/test_vision_live_path.py).",
        "",
        "| Type | Matched | Team right | Role | Truth names | Detector names | Right | Not checkable "
        "| Left null |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for kind, row in g.items():
        team = f"{row['team_right']} of {row['matched']}"
        roles = list(NAMED[kind]) or ["-"]
        for n, role in enumerate(roles):
            lead = f"| {kind} | {row['matched']} | {team} " if n == 0 else "| | | "
            if role == "-":
                lines.append(lead + "| (none: the truth names nobody) | | | | | |")
                continue
            r = row[role]
            lines.append(lead + f"| {role} | {r['truth_names']} | {r['named']} | {r['right']} "
                         f"| {r['unchecked']} | {r['left_null']} |")
    lines += [
        "",
        "Read with care: a handful of events. A clip whose camera is trusted on no frame (a camera cut",
        "the fit does not follow) gives no events, so nothing of it is graded here; its passes are",
        "missed, not misnamed. A false event is listed under its clip with the players its names",
        "really are: what the agents would be told about something that did not happen as detected.",
        "",
        "## Per clip",
        "",
    ]
    for c in body["clips"]:
        lines.append(f"- seed {c['seed']}: truth {c['truth']}, detected {c['detected']}, "
                     f"{len(c['pairs'])} matched; camera trusted on {c['camera_ok']}; "
                     f"teams: {c['teams'].get('reason')}")
        for p in c["pairs"]:
            names = "; ".join(f"{r} {p[r]['detected'] or 'null'} is {p[r]['is'] or '-'}, "
                              f"truth {p[r]['truth'] or 'none'}" for r in ROLES if r in p)
            lines.append(f"  - {p['detected_id']} = {p['truth_id']} ({p['type']}, dt {p['dt_s']} s): team "
                         f"{p['team']['detected']}, truth {p['team']['truth']}"
                         + (f"; {names}" if names else ""))
        for u in c["unmatched_detected"]:
            names = "".join(f", {r} {u[r]} is {u['is'][r] or '?'}" for r in ROLES if r in u)
            lines.append(f"  - {u['id']} ({u['type']}): no true {u['type']} within 1.0 s{names}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--test-dir", type=Path, required=True, help="the frozen test clips (seed<N>/)")
    ap.add_argument("--observations", type=Path, action="append", required=True,
                    help="a dir of observations-seed<N>.jsonl; repeat to search several, first found wins")
    ap.add_argument("--seeds", default="900001,900002,900003,900004,900005")
    ap.add_argument("--out", type=Path, required=True, help="writes <out>.json and <out>.md")
    a = ap.parse_args(argv)
    seeds = [int(s) for s in a.seeds.split(",")]
    clips = [clip(s, a.test_dir, a.observations) for s in seeds]
    body = {
        "command": COMMAND,
        "commit": git_commit(),
        "date": datetime.date.today().isoformat(),
        "rule": {"rival_m": ev.RIVAL_M, "control_m": ev.CONTROL_M, "min_track_frames": ev.MIN_TRACK_FRAMES,
                 "window_s": WINDOW_S, "player_iou": PLAYER_IOU},
        "grade": grade(clips),
        "clips": clips,
    }
    a.out.with_suffix(".json").write_text(json.dumps(body, indent=2) + "\n")
    a.out.with_suffix(".md").write_text(report_md(body))
    print(json.dumps(body["grade"], indent=1))


if __name__ == "__main__":
    main()
