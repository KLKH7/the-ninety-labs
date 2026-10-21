"""The side decision per clip, measured on validation clips (docs/eval/side-decision-plan.md).

    uv run python -m ninety.eval.side_decision --clips <render run v1>/train \\
        --observations <validation observations> --seeds <the validation seeds> --out docs/eval/side-decision

Grading, offline: reads the clips' truth to sort clips (sound clusters or not) and to score, never as
a feature. Each naming candidate decides, per clip, whether to keep today's naming (N0, the mean
position vote) or to flip it. A flip is applied by swapping the outfield tracks' sides inside the
real pipeline, so events, names and scores stay consistent. Keepers are named by their half and
never flip. Refuses test seeds.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import math
import subprocess
from pathlib import Path

from ninety.eval import attribution_score as at
from ninety.eval import detector_derive as dd
from ninety.eval.event_score import Z95, git_commit, wilson
from ninety.vision import events as ev
from ninety.vision import track as tr

SOUND_SHARE = 0.80  # a cluster is sound when this share of its matched track-frames is one side (plan)
NAMING = ("N0", "N1", "N2", "N3", "N4")
COMMAND = ("uv run python -m ninety.eval.side_decision --clips <render run v1>/train "
           "--observations <validation observations> --seeds <the validation seeds> "
           "--out docs/eval/side-decision")


def ordering_95(pairs: list[tuple[float, bool]]) -> dict:
    """The ordering (dd.ordering, an area under the ROC curve) with its 95% interval by Hanley and
    McNeil's standard error (1982, Radiology 143:29-36), and the counts it rests on (lesson 89)."""
    a = dd.ordering(pairs)
    n1, n2 = sum(1 for _, ok in pairs if not ok), sum(1 for _, ok in pairs if ok)
    if a is None:
        return {"ordering": None, "ordering_95": None, "wrong": n1, "right": n2}
    q1, q2 = a / (2 - a), 2 * a * a / (1 + a)
    se = math.sqrt((a * (1 - a) + (n1 - 1) * (q1 - a * a) + (n2 - 1) * (q2 - a * a)) / (n1 * n2))
    lo, hi = round(max(0.0, a - Z95 * se), 2), round(min(1.0, a + Z95 * se), 2)
    return {"ordering": round(a, 4), "ordering_95": [lo, hi], "wrong": n1, "right": n2}


def command(argv: list[str] | None) -> str:
    """The command as run, paths inside the repository written relative to it."""
    import sys
    args = sys.argv[1:] if argv is None else argv
    out = []
    for x in args:
        try:
            x = str(Path(x).resolve().relative_to(dd.ROOT)) if Path(x).exists() else x
        except ValueError:  # a clip folder in the main checkout's runs/, or elsewhere
            x = x[x.index("runs/"):] if "runs/" in x else "<outside the repository>"
        out.append(x)
    return "uv run python -m ninety.eval.side_decision " + " ".join(out)


def dirty() -> bool:
    """Whether the working tree had uncommitted changes when a report was made: its commit stamp
    then names the last commit, not the code that ran."""
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=dd.ROOT,
                         capture_output=True, text=True)
    return bool(out.stdout.strip())


def clusters(tracks: list[dict]) -> dict:
    """Whether a clip's two kit clusters are sound (the plan): in each, at least SOUND_SHARE of its
    matched outfield track-frames belong to one true side, and the two majorities differ. A cluster
    split evenly has no majority, so its clip is not sound. Today's team labels are the cluster ids.
    `named_right` (sound clips only): whether the cluster labelled home is home's."""
    by_cluster = {"home": {"home": 0, "away": 0}, "away": {"home": 0, "away": 0}}
    for t in tracks:
        if t["team"] in by_cluster and t["truth"] in ("home", "away") and not t["keeper"]:
            by_cluster[t["team"]][t["truth"]] += t["frames"]
    majority, shares = {}, {}
    for c, counts in by_cluster.items():
        total = sum(counts.values())
        top = max(counts.values())
        winners = [k for k, v in counts.items() if v == top]
        majority[c] = winners[0] if total and len(winners) == 1 else None
        shares[c] = top / total if total else 0.0
    sound = (all(v >= SOUND_SHARE for v in shares.values()) and None not in majority.values()
             and majority["home"] != majority["away"])
    return {"sound": sound, "shares": shares, "majority": majority,
            "named_right": (majority["home"] == "home") if sound else None}


@contextlib.contextmanager
def flipped(flip: bool):
    """Swap the outfield tracks' sides as assign_teams names them, in track.py and in events.py's
    imported copy. Keepers (named by their half) keep theirs."""
    original = tr.assign_teams

    def assign(tracks):
        info = original(tracks)
        if flip:
            for t in tracks:
                if t.team is not None and not t.keeper:
                    t.team = "away" if t.team == "home" else "home"
        return info
    tr.assign_teams, ev.assign_teams = assign, assign
    try:
        yield
    finally:
        tr.assign_teams, ev.assign_teams = original, original


def evidence(rows: list[dict]) -> dict:
    """Each source's votes on whether today's naming is right (+) or should flip (-), from live data
    only: N0 the mean-position vote, N1 detected passes' direction, N2 carries within spells, N3 the
    goal the strike ending each possession spell heads for (not only the strikes the detector calls
    shots; the plan's table said "detected shots")."""
    tracks = tr.track_players(rows)
    info = tr.assign_teams(tracks)
    path = tr.ball_path(rows)
    index = {p.frame: i for i, p in enumerate(path)}
    sp = ev.spells(path, tracks)

    def toward(team, dx):  # +1 when the move is toward the goal `team` attacks under today's naming
        return (1 if dx > 0 else -1) * (1 if team == "home" else -1) if dx else 0
    events, _ = ev.detect(rows)
    n1 = [toward(e["team"], e["end_x"] - e["x"]) for e in events
          if e["type"] == "pass" and e.get("end_x") is not None]
    n2 = [toward(s.track.team, path[index[s.last]].x - path[index[s.first]].x)
          for s in sp if s.track.team is not None and not s.track.keeper]
    n3 = []
    for s in sp:
        if s.track.team is None or s.track.keeper:
            continue
        other = "away" if s.track.team == "home" else "home"
        mine = ev.heads_for_goal(path, index[s.last], s.track.team)
        theirs = ev.heads_for_goal(path, index[s.last], other)
        if mine != theirs:
            n3.append(1 if mine else -1)
    voting = info.get("frames_voting") or 0
    n0 = abs(info.get("vote_margin") or 0) / voting if voting else 0.0  # today's naming follows its own vote

    def margin(v):
        return sum(v) / len(v) if v else 0.0
    m = {"N0": n0, "N1": margin(n1), "N2": margin(n2), "N3": margin(n3)}
    m["N4"] = m["N0"] + m["N1"] + m["N2"] + m["N3"]
    return {"margins": m, "counts": {"N0": voting, "N1": len(n1), "N2": len(n2), "N3": len(n3)},
            "info": info, "tracks": tracks}


def separation_of(tracks: list[tr.Track], info: dict) -> float | None:
    """The kit clusters' separation (centre distance over the tracks' spread, as track.py chooses the
    feature by), from today's two centres: the K1 confidence's cluster-soundness proxy."""
    if not info.get("kits"):
        return None
    feature = info["feature"]
    pts = [(c, len(t.frames)) for t in tracks if len(t.frames) >= tr.MIN_COLOUR_FRAMES
           and (c := tr.kit(t, feature)) is not None]
    return tr.separation(pts, tuple(info["kits"]["home"]), tuple(info["kits"]["away"]), tr.NOISE[feature])


def clip(seed: int, clips: Path, observations: Path) -> dict | None:
    got = dd.read(seed, clips, observations)
    if got is None:
        return None
    rows, frames, _ = got
    e = evidence(rows)
    sides_now = dd.sides(rows, frames)
    cl = clusters(sides_now["tracks"])
    sound, shares, now_right = cl["sound"], cl["shares"], cl["named_right"]
    decisions = {n: e["margins"][n] >= 0 for n in NAMING}  # True: keep today's naming
    out = {"seed": seed, "sound": sound, "cluster_shares": shares, "now_right": now_right,
           "margins": {k: round(v, 4) for k, v in e["margins"].items()}, "counts": e["counts"],
           "separation": separation_of(e["tracks"], e["info"]), "candidates": {}}
    for n in NAMING:
        keep = decisions[n]
        with flipped(not keep):
            s = dd.sides(rows, frames)
            pairs = [p for p in at.clip(seed, clips, [observations])["pairs"] if p["type"] == "pass"]
        out["candidates"][n] = {
            "keep": keep, "right": None if not sound else (now_right == keep),
            "right_frames": s["right_frames"], "frames": s["frames"],
            "tracks_right": sum(1 for t in s["tracks"]
                                if t["team"] and t["truth"] and t["team"] == t["truth"]),
            "tracks": sum(1 for t in s["tracks"] if t["team"] and t["truth"]),
            "passes": [{"right": p["team"]["truth"] == p["team"]["detected"],
                        "team_confidence": p["team"].get("confidence")} for p in pairs],
        }
    return out


def confidences(c: dict, decision: str) -> dict:
    """K1 and K2 for a clip's decision: the share of sources (N0 to N3, those with a vote) agreeing
    with it, N4's margin breaking ties, times (K1 only) sep / (1 + sep)."""
    keep = c["candidates"][decision]["keep"]
    votes = [c["margins"][n] for n in ("N0", "N1", "N2", "N3") if c["margins"][n] != 0]
    share = sum(1 for v in votes if (v > 0) == keep) / len(votes) if votes else 0.0
    k2 = share + 1e-3 * min(1.0, abs(c["margins"]["N4"]))
    sep = c["separation"] or 0.0
    return {"K2": k2, "K1": k2 * sep / (1 + sep)}


def test_clip(seed: int, test_dir: Path, dirs: list[Path]) -> dict:
    """The test set, scored once with the frozen code: per-clip side accuracy (track-frames and
    tracks) and whether the clusters are sound, from the test truth. No candidate is chosen here."""
    rows = tr.read_observations(at.observations_file(seed, dirs))
    root = test_dir / f"seed{seed}"
    frames = {f["frame"]: f for f in map(json.loads, (root / "frames.jsonl").read_text().splitlines())}
    s = dd.sides(rows, frames)
    cl = clusters(s["tracks"])
    tracks = [t for t in s["tracks"] if t["team"] and t["truth"]]
    right = sum(1 for t in tracks if t["team"] == t["truth"])
    return {"seed": seed, "sound": cl["sound"], "named_right": cl["named_right"],
            "right_frames": s["right_frames"], "frames": s["frames"],
            "accuracy_95": wilson(s["right_frames"], s["frames"]),
            "tracks_right": right, "tracks": len(tracks), "tracks_95": wilson(right, len(tracks)),
            "feature": s["naming"].get("feature")}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--clips", type=Path, required=True)
    ap.add_argument("--observations", type=Path, required=True)
    ap.add_argument("--seeds", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--test-dir", type=Path, default=None,
                    help="score the frozen test set once instead (observations may be repeated dirs)")
    ap.add_argument("--more-observations", type=Path, action="append", default=[])
    a = ap.parse_args(argv)
    seeds = [int(s) for s in a.seeds.split(",")]
    if a.test_dir is not None:
        rows = [test_clip(s, a.test_dir, [a.observations, *a.more_observations]) for s in seeds]
        rf, fr = sum(r["right_frames"] for r in rows), sum(r["frames"] for r in rows)
        body = {"command": command(argv),
                "commit": git_commit(), "dirty": dirty(), "date": datetime.date.today().isoformat(),
                "clips": rows,
                "accuracy": round(rf / fr, 4) if fr else None, "accuracy_95": wilson(rf, fr)}
        tr_, tn = sum(r["tracks_right"] for r in rows), sum(r["tracks"] for r in rows)
        body["tracks_right"], body["tracks"], body["tracks_95"] = tr_, tn, wilson(tr_, tn)
        # Seed 900001 is the clip the detector's side naming was first developed on (#143, #187).
        rest = [r for r in rows if r["seed"] != 900001]
        rf2, fr2 = sum(r["right_frames"] for r in rest), sum(r["frames"] for r in rest)
        body["accuracy_without_900001"] = round(rf2 / fr2, 4) if fr2 else None
        body["accuracy_without_900001_95"] = wilson(rf2, fr2)
        at.write_or_check(a.out, body, test_md, a.check)
        print(json.dumps({k: body[k] for k in ("accuracy", "accuracy_95")}))
        return
    clips = [c for s in seeds if (c := clip(s, a.clips, a.observations)) is not None]
    pooled = {}
    for n in NAMING:
        sound = [c for c in clips if c["sound"]]
        right = sum(1 for c in sound if c["candidates"][n]["right"])
        rf = sum(c["candidates"][n]["right_frames"] for c in clips)
        fr = sum(c["candidates"][n]["frames"] for c in clips)
        passes = [p for c in clips for p in c["candidates"][n]["passes"]]
        pooled[n] = {"sound_clips_right": right, "sound_clips": len(sound),
                     "sound_clips_95": wilson(right, len(sound)),
                     "accuracy": round(rf / fr, 4) if fr else None, "accuracy_95": wilson(rf, fr),
                     "passes_right": sum(p["right"] for p in passes), "passes": len(passes)}
    base = pooled["N0"]
    qualifying = [n for n in NAMING[1:] if pooled[n]["sound_clips_right"] >= base["sound_clips_right"]
                  and (pooled[n]["accuracy"] or 0) >= (base["accuracy"] or 0)]
    best = max(qualifying, key=lambda n: (pooled[n]["accuracy"], -NAMING.index(n)), default=None)
    adopted = best if best and pooled[best]["accuracy"] > base["accuracy"] else "N0"
    order, order_95 = {}, {}
    for k in ("K0", "K1", "K2"):
        pairs = []
        for c in clips:
            conf = confidences(c, adopted)
            for p in c["candidates"][adopted]["passes"]:
                v = p["team_confidence"] if k == "K0" else conf[k]
                if v is not None:
                    pairs.append((v, p["right"]))
        order[k] = dd.ordering(pairs)
        order_95[k] = ordering_95(pairs)
    chosen = max(order, key=lambda k: (order[k] or -1, -("K0", "K1", "K2").index(k)))
    body = {"command": COMMAND, "commit": git_commit(), "date": datetime.date.today().isoformat(),
            "sound_share": SOUND_SHARE, "pooled": pooled, "adopted_naming": adopted,
            "confidence_ordering": order, "confidence_ordering_95": order_95, "adopted_confidence": chosen,
            "dirty": dirty(),
            "predictive": (order[chosen] or 0) >= 0.80,
            "clips": [{**c, "confidence": confidences(c, adopted)} for c in clips]}
    at.write_or_check(a.out, body, report_md, a.check)
    keys = ("pooled", "adopted_naming", "confidence_ordering", "adopted_confidence", "predictive")
    print(json.dumps({k: body[k] for k in keys}, indent=1))


def test_md(body: dict) -> str:
    lines = ["# Side decision on the frozen test set, scored once", "",
             f"Generated by `{body['command']}` at commit `{body['commit']}`, {body['date']}. "
             "Code frozen on validation ([side-decision-plan.md](side-decision-plan.md)).", "",
             f"Side accuracy by track-frames, all clips: **{body['accuracy']}** "
             f"(95% {body['accuracy_95']}; frames within a track are not independent, so this is "
             "optimistic). "
             f"By tracks: {body.get('tracks_right')} of {body.get('tracks')} (95% {body.get('tracks_95')}). "
             f"Without seed 900001, the clip the side naming was first developed on: "
             f"{body.get('accuracy_without_900001')} (95% {body.get('accuracy_without_900001_95')}).", "",
             "| Seed | Feature | Clusters sound | Named right | Accuracy, track-frames (95%) "
             "| Tracks right (95%) |",
             "|---|---|---|---|---|---|"]
    for r in body["clips"]:
        acc = round(r["right_frames"] / r["frames"], 3) if r["frames"] else None
        lines.append(f"| {r['seed']} | {r['feature']} | {r['sound']} | {r['named_right']} | {acc} "
                     f"{r['accuracy_95']} "
                     f"| {r['tracks_right']} of {r['tracks']} {r['tracks_95']} |")
    return "\n".join(lines) + "\n"


def report_md(body: dict) -> str:
    lines = [
        "# The side decision per clip, on validation clips",
        "",
        f"Generated by `{body['command']}` at commit `{body['commit']}`, {body['date']}. Plan: "
        "[side-decision-plan.md](side-decision-plan.md).",
        "",
        f"Adopted naming: **{body['adopted_naming']}**; confidence: **{body['adopted_confidence']}** "
        f"(ordering {body['confidence_ordering'][body['adopted_confidence']]}; predictive at 0.80: "
        f"**{body['predictive']}**).",
        "",
        "| Naming | Sound clips named right (95%) | Side accuracy by track-frames (95%) | Pass teams right |",
        "|---|---|---|---|",
        *[f"| {n} | {v['sound_clips_right']} of {v['sound_clips']} {v['sound_clips_95']} | {v['accuracy']} "
          f"{v['accuracy_95']} | {v['passes_right']} of {v['passes']} |" for n, v in body["pooled"].items()],
        "",
        "Confidence ordering (share of wrong-right pass pairs ordered right; 0.5 is chance), with its "
        "95% interval (Hanley and McNeil 1982) and the passes it rests on: "
        + "; ".join(f"{k} {v['ordering']} {v['ordering_95']} ({v['wrong']} wrong, {v['right']} right)"
                    for k, v in body["confidence_ordering_95"].items()) + ".",
        "",
        "## Per clip",
        "",
        "| Seed | Sound | Today right | Margins N0 / N1 / N2 / N3 (votes) | Adopted keeps "
        "| Accuracy (95% frames; tracks) |",
        "|---|---|---|---|---|---|",
    ]
    for c in body["clips"]:
        a = c["candidates"][body["adopted_naming"]]
        acc = round(a["right_frames"] / a["frames"], 3) if a["frames"] else None
        m, k = c["margins"], c["counts"]
        lines.append(f"| {c['seed']} | {c['sound']} | {c['now_right']} | {m['N0']} ({k['N0']}) / "
                     f"{m['N1']} ({k['N1']}) / {m['N2']} ({k['N2']}) / {m['N3']} ({k['N3']}) "
                     f"| {a['keep']} | {acc} "
                     f"{wilson(a['right_frames'], a['frames'])}; {a['tracks_right']} of {a['tracks']} "
                     f"{wilson(a['tracks_right'], a['tracks'])} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
