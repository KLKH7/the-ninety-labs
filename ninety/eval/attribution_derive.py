"""Derive attribution's constants on clips that are not test clips, and test the track-break rule.

    uv run python -m ninety.eval.attribution_derive --clips <dir of seed<N>/> \\
        --observations <dir of observations-seed<N>.jsonl> --seeds 108,109 --out docs/eval/attribution-derive

Grading data, read offline: the clips' frames.jsonl and events.jsonl. A frozen test seed is refused:
the test clips are for the final score only (docs/eval/test-set-frozen.json).

Two measurements, fixed before they were run (docs/eval/attribution.md, "How the constants were set"):
- **RIVAL_M**: the 90th percentile of the players' pitch-position error, pooled over the clips, by
  ninety/eval/pitch_score.py's rule (each detection paired with the true player whose box it
  overlaps, IoU 0.5). A rival track that much nearer than its true place may really be the nearer.
- **The track-break rule** (ninety/vision/events.py, `may_continue`): with it off and on, how many
  detected passes go from a player to himself (passer and next holder are one true player, through
  two tracks), how many of the passes the rule removes were such self-passes, and how many true
  passes are matched each way.
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path

from ninety.eval.attribution_score import clip, grade, match, truth_player, write_or_check
from ninety.eval.event_score import git_commit, load_events
from ninety.eval.pitch_score import _summary, errors
from ninety.vision import events as ev
from ninety.vision import track as tr

ROOT = Path(__file__).resolve().parents[2]
TEST_SET = ROOT / "docs" / "eval" / "test-set-frozen.json"
COMMAND = ("uv run python -m ninety.eval.attribution_derive --clips <render run v1>/train "
           "--observations <dir> --seeds <the validation seeds> --out docs/eval/attribution-derive")


def test_seeds() -> set[int]:
    """Every seed kept for evaluation: the frozen test sets' and all of TEST_SEEDS (900001 to
    900030, ninety/render/splits.py), and anything else at or above RESERVED_FROM."""
    from ninety.render.splits import TEST_SEEDS
    return set(json.loads(TEST_SET.read_text())["seeds"]) | set(TEST_SEEDS)


def refused(seed: int) -> bool:
    """Whether a seed may not be used to derive anything (a test or reserved seed)."""
    from ninety.render.splits import RESERVED_FROM
    return seed in test_seeds() or seed >= RESERVED_FROM


def self_passes(rows: list[dict], frames: dict[int, dict], join_breaks: bool) -> dict:
    """The passes detect() emits, and for each whether its passer and the next holder are one true
    player (a self-pass), or cannot be told (a track whose box pairs with nobody)."""
    events, _ = ev.detect(rows, join_breaks=join_breaks)
    tracks = tr.track_players(rows)
    tr.assign_teams(tracks)
    sp = ev.spells(tr.ball_path(rows), tracks)
    obs = {r["frame"]: r for r in rows}
    out = []
    for e in (e for e in events if e["type"] == "pass"):
        i = next(i for i, s in enumerate(sp) if s.last == e["frame"])
        a, b = sp[i], sp[i + 1] if i + 1 < len(sp) else None
        if b is None:
            continue  # out of play before anyone had it again: no next holder to compare
        pa = truth_player(a.track, a.last, obs, frames)
        pb = truth_player(b.track, b.first, obs, frames)
        out.append({"id": e["id"], "frame": e["frame"], "tracks": [a.track.id, b.track.id],
                    "players": [pa, pb], "self": None if pa is None or pb is None else pa == pb})
    return {"events": events, "passes": out}


def one(seed: int, clips: Path, observations: Path) -> dict:
    root = clips / f"seed{seed}"
    frames_list = [json.loads(x) for x in (root / "frames.jsonl").read_text().splitlines() if x.strip()]
    frames = {f["frame"]: f for f in frames_list}
    rows = tr.read_observations(observations / f"observations-seed{seed}.jsonl")
    players, _, _, not_ok = errors(frames_list, rows)
    truth = [e for e in load_events(root / "events.jsonl", "truth") if e["type"] == "pass"]
    ways = {}
    for name, join in (("off", False), ("on", True)):
        r = self_passes(rows, frames, join)
        detected = [e for e in r["events"] if e["type"] == "pass"]
        ways[name] = {"passes": len(detected), "matched": len(match(truth, detected)),
                      "self": sum(1 for p in r["passes"] if p["self"]),
                      "list": r["passes"]}
    on_frames = {p["frame"] for p in ways["on"]["list"]}
    removed = [p for p in ways["off"]["list"] if p["frame"] not in on_frames]
    return {"seed": seed, "frames_camera_ok": len(rows) - len(not_ok), "true_passes": len(truth),
            "player_errors": players, "off": ways["off"], "on": ways["on"], "removed": removed}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--clips", type=Path, required=True,
                    help="dir of seed<N>/ with frames.jsonl and events.jsonl")
    ap.add_argument("--observations", type=Path, required=True)
    ap.add_argument("--seeds", required=True)
    ap.add_argument("--out", type=Path, required=True, help="writes <out>.json and <out>.md")
    ap.add_argument("--check", action="store_true", help="fail unless the committed report is up to date")
    a = ap.parse_args(argv)
    seeds = [int(s) for s in a.seeds.split(",")]
    if banned := sorted(s for s in seeds if refused(s)):
        raise SystemExit(f"test seeds {banned}: the test clips are for the final score only")
    # A clip the camera fit could not place (observe fails: too few markings in any frame) has no
    # observations: it is listed, never silently dropped, and has nothing to measure.
    unplaced = [s for s in seeds if not (a.observations / f"observations-seed{s}.jsonl").exists()]
    seeds = [s for s in seeds if s not in unplaced]
    per = [one(s, a.clips, a.observations) for s in seeds]
    pooled = _summary([x for c in per for x in c["player_errors"]])
    dev = grade([clip(s, a.clips, [a.observations]) for s in seeds])
    totals = {w: {k: sum(c[w][k] for c in per) for k in ("passes", "matched", "self")} for w in ("off", "on")}
    removed = [dict(r, seed=c["seed"]) for c in per for r in c["removed"]]
    body = {
        "command": COMMAND, "commit": git_commit(), "date": datetime.date.today().isoformat(),
        "seeds": seeds, "unplaced": unplaced, "players_position_error": pooled,
        "players_position_error_per_clip": {c["seed"]: _summary(c["player_errors"]) for c in per},
        "track_break_rule": {"totals": totals, "removed": removed,
                             "removed_self": sum(1 for r in removed if r["self"]),
                             "removed_not_self": sum(1 for r in removed if r["self"] is False),
                             "removed_unknown": sum(1 for r in removed if r["self"] is None)},
        "development_attribution": dev,
        "clips": [{k: v for k, v in c.items() if k != "player_errors"} for c in per],
    }
    write_or_check(a.out, body, report_md, a.check)
    rule = body["track_break_rule"]
    print(json.dumps({"players_position_error": pooled, "track_break_rule": rule["totals"],
                      "removed_self": rule["removed_self"], "removed_not_self": rule["removed_not_self"]},
                     indent=1))


def report_md(body: dict) -> str:
    pe, tb = body["players_position_error"], body["track_break_rule"]
    off, on = tb["totals"]["off"], tb["totals"]["on"]
    dev = body["development_attribution"]["pass"]
    names = {r: dev[r] for r in ("player", "receiver", "interceptor")}
    lines = [
        "# Attribution constants, derived on validation clips (never test clips)",
        "",
        f"Generated by `{body['command']}` at commit `{body['commit']}`, {body['date']}.",
        f"Seeds: {', '.join(map(str, body['seeds']))} (ours-v2's validation seeds without a camera cut).",
        f"Not placed (the camera fit found too few markings in every frame, so no observations): "
        f"{', '.join(map(str, body['unplaced'])) or 'none'}.",
        "",
        "## Players' pitch-position error (sets RIVAL_M)",
        "",
        f"{pe['n']} detections: median {pe['median_m']} m, 90th percentile **{pe['p90_m']} m**, "
        f"largest {pe['max_m']} m.",
        "",
        "| Seed | Detections | Median (m) | p90 (m) |",
        "|---|---|---|---|",
        *[f"| {k} | {v['n']} | {v['median_m']} | {v['p90_m']} |"
          for k, v in body["players_position_error_per_clip"].items()],
        "",
        "## The track-break rule",
        "",
        "| | Detected passes | True passes matched | Self-passes (one true player, two tracks) |",
        "|---|---|---|---|",
        f"| rule off | {off['passes']} | {off['matched']} | {off['self']} |",
        f"| rule on | {on['passes']} | {on['matched']} | {on['self']} |",
        "",
        f"Passes the rule removes: {len(tb['removed'])}: {tb['removed_self']} self-passes, "
        f"{tb['removed_not_self']} between two different players, {tb['removed_unknown']} not checkable.",
        "",
        "## Development numbers (attribution on these clips, with the constants in the code at this commit)",
        "",
        f"Passes matched {dev['matched']}, team right {dev['team_right']}. Side confidence "
        f"(`team_confidence`, reported only): right side {dev['team_confidence']['right']}; "
        f"wrong side {dev['team_confidence']['wrong']}.",
        "",
        "| Role | Truth names | Named | Right | Not checkable | Left null |",
        "|---|---|---|---|---|---|",
    ]
    for role, r in names.items():
        lines.append(f"| {role} | {r['truth_names']} | {r['named']} | {r['right']} | {r['unchecked']} "
                     f"| {r['left_null']} |")
    lines += ["", "## Per clip", ""]
    for c in body["clips"]:
        lines.append(f"- seed {c['seed']}: camera trusted on {c['frames_camera_ok']} frames; true passes "
                     f"{c['true_passes']}; detected off/on {c['off']['passes']}/{c['on']['passes']}, matched "
                     f"{c['off']['matched']}/{c['on']['matched']}, self {c['off']['self']}/{c['on']['self']}")
        for r in c["removed"]:
            lines.append(f"  - removed pass at frame {r['frame']}: tracks {r['tracks']} are {r['players']}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
