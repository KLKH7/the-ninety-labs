"""Grade "most involved" as an order with no count, once, on a held-out match
(docs/eval/player-involvement-rank-plan.md).

    uv run python -m ninety.eval.player_involvement_rank_eval --clip runs/demo-8080-hunt \\
        --vision runs/demo-8080-hunt-work/vision --feed runs/demo-8080-hunt/final-work/identity_feed.jsonl \\
        --truth-events ~/ninety-notes/footage-hunt/seed8080-v2/events.jsonl \\
        --truth-meta ~/ninety-notes/footage-hunt/seed8080-v2/meta.json

The truth's events are read only here. The verdict sets `rank:involvement_order` in
player_stats_calibration.json; nothing else is read back.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from ninety.eval.event_score import git_commit
from ninety.eval.player_stats_eval import DETECTED_TYPES, _jsonl
from ninety.intel import identity, player_stats
from ninety.intel.match_insights import load_fixture
from ninety.intel.teamsheet import LABEL
from ninety.match import detected

MINUTES = (45, 90)
MEAN_BAR = 2.0  # mean top-3 overlap over the four cases (design, pre-registered)
CASE_FLOOR = 1  # and no case below 1 of 3
ORDER_ON = {"rank:involvement_order": {"on": True}}  # grading reads the order whatever the flag says


def truth_top3(counts: Counter, pool: list[str]) -> set[str]:
    """The truth's top three; every player tied with third place counts as in it."""
    ranked = sorted(pool, key=lambda p: -counts[p])
    if len(ranked) <= 3:
        return set(ranked)
    third = counts[ranked[2]]
    return {p for p in ranked if counts[p] >= third}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--clip", type=Path, required=True)
    ap.add_argument("--vision", type=Path, required=True)
    ap.add_argument("--feed", type=Path, required=True)
    ap.add_argument("--truth-events", type=Path, required=True)
    ap.add_argument("--truth-meta", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("docs/eval/player-involvement-rank.json"))
    ap.add_argument("--calibration", type=Path, default=player_stats.CALIBRATION)
    args = ap.parse_args(argv)
    clip = args.clip
    frames = json.loads((clip / "tracked.json").read_text())["frames"]
    association = json.loads((clip / "association.json").read_text())["tracks"]
    events = detected.load(clip / "detected.jsonl")
    b_frames = identity.broadcast_frames(args.vision, clip)
    feed = identity.load_for(args.feed, [*frames, *b_frames], load_fixture(clip / "clip.json"))
    tactical = identity.tactical(frames, feed)
    named_b = identity.named_broadcast(association, tactical, feed, events, b_frames)
    body = player_stats.build(frames, identity.sided(events, named_b), feed, tactical, named_b)

    segments = json.loads((clip / "clip.json").read_text())["segments"]
    shown = lambda f: any(s["frame"] <= f < s["frame"] + s["frames"] for s in segments)  # noqa: E731
    meta = json.loads(args.truth_meta.read_text())
    by_role = {(r["team"], LABEL[r["role"]]): r["id"] for r in meta["roster"]}
    eid_to_pid = {by_role[(p["team"], p["position"])]: pid for pid, p in feed.roster.items()}
    t_events = [e for e in _jsonl(args.truth_events)
                if e["type"] in DETECTED_TYPES and shown(int(e["frame"]))]

    cases = []
    for minute in MINUTES:
        raw = player_stats.stats(body, 60.0 * minute, {}, withhold=False)
        truth = Counter()
        for e in t_events:
            if float(e["t"]) <= 60.0 * minute:
                for pid in {eid_to_pid.get(e.get(k)) for k in ("player", "receiver", "interceptor")} - {None}:
                    truth[pid] += 1
        for team in ("home", "away"):
            rows = [r for r in raw if r["team"] == team]
            ours = [f["player"] for f in player_stats.order(rows, ORDER_ON)["facts"]]
            pool = [r["player"] for r in rows]
            top = truth_top3(truth, pool)
            lead = max(truth[p] for p in pool)
            names = {r["player"]: r["name"] for r in rows}
            cases.append({"minute": minute, "team": team, "ours": [names[p] for p in ours],
                          "truth_top3": sorted(names[p] for p in top),
                          "overlap": len(set(ours) & top), "leader_right": truth[ours[0]] == lead,
                          "truth_events_shown": sum(truth.values())})
    mean = sum(c["overlap"] for c in cases) / len(cases)
    met = mean >= MEAN_BAR and min(c["overlap"] for c in cases) >= CASE_FLOOR
    out = {"commit": git_commit(), "plan": "docs/eval/player-involvement-rank-plan.md", "clip": str(clip),
           "cases": cases, "mean_overlap": mean, "met": met,
           "leaders_right": sum(c["leader_right"] for c in cases)}
    args.out.write_text(json.dumps(out, indent=1) + "\n")
    cal = json.loads(args.calibration.read_text()) if args.calibration.exists() else {"stats": {}}
    cal["stats"]["rank:involvement_order"] = {"on": met, "why": None if met else (
        f"held-out top-3 agreement {mean:.2f} of 3 (min {min(c['overlap'] for c in cases)}), under the bar "
        f"{MEAN_BAR} with none below {CASE_FLOOR} (docs/eval/player-involvement-rank.md)")}
    args.calibration.write_text(json.dumps(cal, indent=1) + "\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
