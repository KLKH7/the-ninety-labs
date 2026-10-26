"""How often a name from the player-ID feed is the right man: ninety/intel/identity.py graded on a
joined match.

    uv run python -m ninety.eval.identity_eval --clip runs/demo-8080-match \\
        --vision runs/demo-8080-vision-v2 --truth <the seed's simulated run> \\
        --feed identity_feed.jsonl --out docs/eval/identity.json

The feed is the engine's own ids, so a name can only be wrong where vision's side of the
association is: a track that switches players, a track on the wrong side, or a broadcast track
the camera join paired with another man. That is what this grades, as naming_eval grades role
names: every tracked player of each camera is given his true player, the one nearest on average
over its frames (ninety/eval/association.true_players), and a name is right when the true player
is the feed id named. Only the association gate is chosen, on the development half (the even
segments), from naming_eval's pre-registered grid at its target, then the held-out half is
scored once. No vision number is computed or changed here.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from ninety.agents.factcheck import side_known
from ninety.eval.association import true_players
from ninety.eval.event_score import git_commit
from ninety.eval.naming_eval import (
    ASSOCIATIONS,
    TARGET,
    _jsonl,
    broadcast_frames,
    by_number,
    load_truth,
    score,
)
from ninety.intel import identity, naming
from ninety.intel.match_insights import load_fixture
from ninety.intel.teamsheet import LABEL


def _true(owner: dict, track: str) -> str | None:
    hit = owner.get(track) or owner.get(track.split("-t")[1])
    return hit[0] if hit else None


def engine_ids(feed: identity.Feed, truth_run: Path) -> dict[str, str]:
    """The provider's player id -> the engine's, by side and position (the team sheet's label of
    the engine's role): the answer key's roster, read only here."""
    meta = json.loads((truth_run / "meta.json").read_text())
    by = {(r["team"], LABEL[r["role"]]): r["id"] for r in meta["roster"]}
    return {i: by[(p["team"], p["position"])] for i, p in feed.roster.items()}


def grade(tactical: dict, broadcast: dict, events: list[dict], owner_v, owner_b, split, eid) -> dict:
    tracks = [t for t in tactical if split(t)]
    named_t = [_true(owner_v, t) == eid[w["player"]] for t, w in tactical.items() if split(t)]
    actors = [e["player"] for e in events if e.get("player") and split(e["player"])]
    named_e = [_true(owner_b, a) == eid[broadcast[a]["player"]] for a in actors if a in broadcast]
    return {"track_names": score(named_t), "events": len(actors), "event_names": score(named_e),
            "event_coverage": round(len(named_e) / len(actors), 3) if actors else None,
            "tracks_named": len(tracks)}


def direct_path(args, frames, association, events, owner_v, owner_b, eid, tv, assoc: float,
                held) -> tuple[dict, bool]:
    """The broadcast's tracks matched to the feed directly, combined with the join (pre-registered:
    docs/eval/identity-direct-plan.md): graded once, with every unnamed event's reason."""
    b_frames = identity.broadcast_frames(args.vision)
    feed_b = identity.load_for(args.feed, [*frames, *b_frames], load_fixture(args.clip / "clip.json"))
    direct = identity.tactical(b_frames, feed_b, any_side=True)
    via = identity.broadcast(association, tv, {"association": assoc})
    comb = identity.combined(identity.event_ids(events, association), via, direct, association)
    report = {"plan": "docs/eval/identity-direct-plan.md", "direct_tracks": len(direct),
              "held_out": grade(tv, comb, events, owner_v, owner_b, held, eid),
              "all": grade(tv, comb, events, owner_v, owner_b, lambda t: True, eid),
              "paths": dict(Counter(w["path"] for w in comb.values()))}
    # Why each event is unnamed, the first reason that holds (the plan's order).
    seen = {identity._number(p["id"]) for f in b_frames for p in f["players"]}
    loose = identity.assign(b_frames, feed_b, any_side=True, one_at_a_time=False)
    majority = {identity._number(t) for t in loose}
    calibrated = {f["frame"] for f in b_frames}
    reasons = Counter()
    for e in events:
        who = e.get("player")
        if who and who in comb:
            reasons["named"] += 1
        elif not who:
            reasons["no_player_attributed"] += 1
        elif identity._number(who) not in seen:
            reasons["calibration_withheld"] += 1
        elif identity._number(who) not in majority:
            reasons["no_feed_majority"] += 1
        else:
            reasons["name_held_by_another_track"] += 1
    report["events"] = len(events)
    report["reasons"] = dict(reasons)
    report["events_on_withheld_frames"] = sum(e["frame"] not in calibrated for e in events)
    sided = identity.sided(events, comb)
    report["events_side_sure"] = sum(map(side_known, sided))
    h = report["held_out"]["event_names"]
    return report, (h["precision"] or 0) >= TARGET


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--clip", type=Path, required=True)
    ap.add_argument("--vision", type=Path, required=True)
    ap.add_argument("--truth", type=Path, required=True)
    ap.add_argument("--feed", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("docs/eval/identity.json"))
    ap.add_argument("--calibration", type=Path, default=identity.CALIBRATION)
    args = ap.parse_args(argv)
    clip = args.clip
    frames = json.loads((clip / "tracked.json").read_text())["frames"]
    association = json.loads((clip / "association.json").read_text())["tracks"]
    events = _jsonl(clip / "detected.jsonl")
    segments = sorted(p.name for p in args.vision.iterdir() if (p / "broadcast" / "tracked.json").exists())
    b_frames = broadcast_frames(args.vision, segments)
    truth, _ = load_truth(args.truth, {f["frame"] for f in frames} | {f["frame"] for f in b_frames})
    owner_v = true_players([f for f in frames if f["frame"] in truth], truth)
    owner_b = by_number(true_players([f for f in b_frames if f["frame"] in truth], truth))
    dev = lambda t: naming.segment(t) % 2 == 0  # noqa: E731
    held = lambda t: naming.segment(t) % 2 == 1  # noqa: E731

    feed = identity.load_for(args.feed, frames, load_fixture(clip / "clip.json"))
    eid = engine_ids(feed, args.truth)
    tv = identity.tactical(frames, feed)
    rows = []
    for assoc in ASSOCIATIONS:
        bp = identity.broadcast(association, tv, {"association": assoc})
        rows.append({"association": assoc, "dev": grade(tv, bp, events, owner_v, owner_b, dev, eid)})
    ok = [r for r in rows if (r["dev"]["event_names"]["precision"] or 0) >= TARGET
          and (r["dev"]["track_names"]["precision"] or 0) >= TARGET]
    # The most events named on development; ties go to the stricter gate.
    chosen = max(ok, key=lambda r: (r["dev"]["event_names"]["named"], r["association"])) if ok else None
    out = {"commit": git_commit(), "clip": str(clip), "truth": str(args.truth), "feed": str(args.feed),
           "target": TARGET, "gate_m": identity.GATE_M, "grid": rows,
           "chosen": chosen and chosen["association"]}
    if chosen:
        bp = identity.broadcast(association, tv, {"association": chosen["association"]})
        out["held_out"] = grade(tv, bp, events, owner_v, owner_b, held, eid)
        out["all"] = grade(tv, bp, events, owner_v, owner_b, lambda t: True, eid)
        # The share of tracked player-frames whose track the feed names (what the radar shows).
        seen = [p["id"] for f in frames for p in f["players"]]
        out["frame_coverage"] = round(sum(t in tv for t in seen) / len(seen), 3)
        out["tracks"] = len(set(seen))
        out["id_corrections"] = feed.corrections
        sided = identity.sided(events, bp)
        out["events_sided"] = sum(e.get("team_source") == identity.SOURCE for e in sided)
        out["events_total"] = len(events)
        # Sides sure enough for the fact-checker to air (factcheck.side_known), without and with the feed.
        out["events_side_sure"] = {"without_feed": sum(map(side_known, events)),
                                   "with_feed": sum(map(side_known, sided))}
        out["events_side_changed"] = sum(a["team"] != b["team"] for a, b in zip(events, sided, strict=True))
    direct_met = None
    if chosen:
        out["direct"], direct_met = direct_path(args, frames, association, events, owner_v, owner_b, eid, tv,
                                                chosen["association"], held)
    args.out.write_text(json.dumps(out, indent=1) + "\n")
    # The gate is used only if the held-out half also meets the target on both units.
    h = out.get("held_out") or {}
    met = bool(h) and all((h[u]["precision"] or 0) >= TARGET for u in ("track_names", "event_names"))
    args.calibration.write_text(json.dumps({"association": chosen and chosen["association"],
                                            "target": TARGET, "held_out_met": met,
                                            "direct_held_out_met": bool(direct_met),
                                            "source": "docs/eval/identity.json"}, indent=1) + "\n")
    shown = ("chosen", "held_out", "all", "frame_coverage", "tracks", "id_corrections", "events_sided",
             "events_total", "events_side_sure", "events_side_changed", "direct")
    print(json.dumps({k: out.get(k) for k in shown},
                     indent=1))


if __name__ == "__main__":
    main()
