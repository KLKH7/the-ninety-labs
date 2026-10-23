"""Planted claims about team shape: does the fact-checker's code half catch every false one, pass
every true one, and hold every claim on a fact built on too few tracked players?

    uv run python -m ninety.eval.shape_claims --rows    # simulate, write the shape facts (slow)
    uv run python -m ninety.eval.shape_claims           # the claims and the report, from those facts

The shape facts come from `ninety.intel.shape.shape_rows` over the simulator's positions for the
held-out evaluation seeds 21 and 33 (grading use: the positions stand in for a whole-pitch tracked
output, all 11 of each team seen). A second copy of every minute drops one player of each team at
random, as a camera that misses one would: those facts are not confident.

Claims are written here by templates, each true one only where its fact's fields make it true (the
condition is in the template's guard, written before any verdict was read, lesson 34), and every
false one by planting one defect in a true one: a wrong number, the opposite direction, the other
team, the words of the wrong degree, or no shape fact cited. The checker runs as the workflow runs
it: `check`, then `confidence_gate`. The Judge is not called (no model, no cost); what it adds on
these claims is not measured here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from ninety.agents.contracts import status_for
from ninety.agents.factcheck import (
    COMPACT_M2,
    DEEP_LINE_M,
    HIGH_LINE_M,
    NARROW_M,
    Claim,
    check,
    confidence_gate,
    shape_reasons,
    spelled_as_digits,
)
from ninety.intel import shape
from ninety.sim import fmath

ROOT = Path(__file__).resolve().parents[2]
ROWS = ROOT / "docs" / "eval" / "shape-claims-rows.json"
REPORT = ROOT / "docs" / "eval" / "shape-claims.md"
SEEDS = (21, 33)  # the agent evaluation's held-out seeds (ninety/mcp/match_server.MATCHES)
MINUTES = 5
RNG_SEED = 0


def simulated_rows() -> dict:
    """Each seed's shape facts with every player seen, and with one of each team missing."""
    from ninety.match.facts import AGENT_TYPES, compact, match_events
    from ninety.match.tracking import slim
    from ninety.sim.engine import simulate

    rng = fmath.Random(RNG_SEED)
    out = {}
    for seed in SEEDS:
        run = simulate(seed, MINUTES)
        frames = [slim(f) for f in run.frames]
        missing = {team: rng.choice(sorted({p["id"] for p in frames[0]["players"] if p["team"] == team}))
                   for team in ("home", "away")}
        thinned = [{**f, "players": [p for p in f["players"] if p["id"] not in missing.values()]}
                   for f in frames]
        events = [compact(e) for e in match_events(seed, MINUTES) if e["type"] in AGENT_TYPES]
        out[f"seed{seed}"] = {"full": shape.shape_rows(frames), "one_missing": shape.shape_rows(thinned),
                              "missing": missing, "events": events}
    return out


def _other(team: str) -> str:
    return "away" if team == "home" else "home"


def _title(team: str) -> str:
    return team.capitalize()


def true_claims(rows: dict[str, dict]) -> list[tuple[str, str, list[str]]]:
    """(kind, text, evidence) for every template whose guard holds on its fact."""
    out = []
    for r in rows.values():
        t, v, c, i = _title(r["team"]), r["value"], r["change"], r["id"]
        m = r["metric"]
        if m == "line_height":
            out.append(("line value", f"{t}'s defensive line stood {v} m from their own goal.", [i]))
            if c and c > 0:
                text = f"{t}'s back line pushed up {c} m in minute {r['minute']}."
                out.append(("line pushed up", text, [i]))
            if c and c < 0:
                out.append(("line dropped", f"{t}'s back line dropped back {-c} m.", [i]))
            if v > HIGH_LINE_M:
                out.append(("high line", f"{t} played a high line.", [i]))
            if v < DEEP_LINE_M:
                out.append(("deep block", f"{t} sat in a deep block.", [i]))
        elif m == "width":
            out.append(("width value", f"{t} were {v} m wide.", [i]))
            if c and c < 0:
                out.append(("narrowed", f"{t} narrowed by {-c} m.", [i]))
            if c and c > 0:
                out.append(("widened", f"{t} widened by {c} m.", [i]))
            if v < NARROW_M:
                out.append(("narrow", f"{t} were narrow.", [i]))
        elif m == "area":
            out.append(("area value", f"{t} covered {v} m² of pitch.", [i]))
            if c and c < 0:
                out.append(("more compact", f"{t} were more compact, down to {v} m².", [i]))
            if c and c > 0:
                out.append(("stretched", f"{t} stretched to {v} m².", [i]))
            if v < COMPACT_M2:
                out.append(("compact", f"{t} were compact.", [i]))
        elif m == "length":
            out.append(("length value", f"{t} were {v} m from front to back.", [i]))
        elif m == "behind_ball":
            out.append(("behind the ball", f"{t} had {v} players behind the ball.", [i]))
    return out


FLIP = (("pushed up", "dropped back"), ("narrowed", "widened"), ("more compact", "stretched to"))


def planted(kind: str, text: str, evidence: list[str], rows: dict[str, dict],
            events: list[dict]) -> list[tuple[str, str, list[str]]]:
    """Each defect that can be planted in one true claim, as (family, text, evidence)."""
    r = rows[evidence[0]]
    out = []
    for n in sorted(_numbers_of(r)):
        wrong = n + (30 if r["unit"] == "m²" else 3)
        if f" {n} " in text and wrong not in _numbers_of(r):
            out.append(("wrong number", text.replace(f" {n} ", f" {wrong} ", 1), evidence))
            break
    for a, b in FLIP:
        for x, y in ((a, b), (b, a)):
            if x in text:
                out.append(("opposite direction", text.replace(x, y, 1), evidence))
    team, other = _title(r["team"]), _title(_other(r["team"]))
    if f"{other.lower()}" not in text.lower():
        out.append(("other team", text.replace(team, other, 1), evidence))
    minute_events = [e["id"] for e in events if e["minute"] == r["minute"]]
    if minute_events:
        out.append(("no shape fact cited", text, minute_events[:1]))
    if kind in ("line value", "width value", "area value"):
        degree = {"line value": ("high line", "deep block"), "width value": ("narrow",),
                  "area value": ("compact",)}[kind]
        for word in degree:
            fits = {"high line": r["value"] > HIGH_LINE_M, "deep block": r["value"] < DEEP_LINE_M,
                    "narrow": r["value"] < NARROW_M, "compact": r["value"] < COMPACT_M2}[word]
            if not fits:
                phrase = {"high line": "played a high line", "deep block": "sat in a deep block",
                          "narrow": "were narrow", "compact": "were compact"}[word]
                out.append(("wrong degree", f"{team} {phrase}.", evidence))
    return out


def _numbers_of(r: dict) -> set[int]:
    return {r["value"]} | ({abs(r["change"])} if r["change"] is not None else set())


def verdict_of(text: str, evidence: list[str], known: dict[str, dict]) -> tuple[str, str]:
    """The verdict, and the layer that decided it: the shape check (`shape_reasons`), the other code
    checks (numbers, players, ids), the confidence gate, or none (it airs)."""
    claim = Claim(text, evidence)
    v = check(claim, known)
    if not v.ok:
        cited = [known[i] for i in evidence if i in known]
        by = "shape check" if shape_reasons(spelled_as_digits(text), cited) else "other code checks"
        return status_for(v), by
    v = confidence_gate(claim, known)
    return ("verified", "none") if v.ok else (status_for(v), "confidence gate")


def _got(text: str, evidence: list[str], known: dict[str, dict]) -> dict:
    got, by = verdict_of(text, evidence, known)
    return {"got": got, "by": by}


def evaluate(data: dict) -> list[dict]:
    results = []
    for match, d in sorted(data.items()):
        events = {e["id"]: e for e in d["events"]}
        full = {r["id"]: r for r in d["full"] if r["confident"]}
        for kind, text, ev in true_claims(full):
            results.append({"match": match, "family": "true", "kind": kind, "text": text, "evidence": ev,
                            "expect": "verified", **_got(text, ev, full | events)})
            for family, bad, bad_ev in planted(kind, text, ev, full, d["events"]):
                results.append({"match": match, "family": family, "kind": kind, "text": bad,
                                "evidence": bad_ev, "expect": "rejected",
                                **_got(bad, bad_ev, full | events)})
        thin = {r["id"]: r for r in d["one_missing"]}
        for kind, text, ev in true_claims({i: r for i, r in thin.items() if i in full}):
            results.append({"match": match, "family": "one player untracked", "kind": kind, "text": text,
                            "evidence": ev, "expect": "held", **_got(text, ev, thin | events)})
    return results


def report(results: list[dict], rows_sha: str) -> str:
    by = Counter((r["family"], r["got"] == r["expect"]) for r in results)
    families = list(dict.fromkeys(r["family"] for r in results))
    false = [r for r in results if r["expect"] == "rejected"]
    true = [r for r in results if r["family"] == "true"]
    held = [r for r in results if r["expect"] == "held"]
    lines = [
        "# Fact-checker on planted shape claims (offline, code checks only)",
        "",
        "Generated by `uv run python -m ninety.eval.shape_claims` from "
        f"`docs/eval/shape-claims-rows.json` (sha256 `{rows_sha[:16]}`), the shape facts of seeds "
        f"{', '.join(map(str, SEEDS))} ({MINUTES} simulated minutes each, every player seen; and again "
        "with one player of each team missing). `tests/test_shape_claims.py` fails if this file is out "
        "of date.",
        "",
        "Each claim goes through `check` then `confidence_gate`, as in the workflow. The Judge is not "
        "called, so this measures only the code half; a Judge run on these claims costs money and is "
        "not done here.",
        "",
        f"**Planted false claims caught:** {sum(r['got'] == 'rejected' for r in false)}/{len(false)}.  ",
        f"**True claims wrongly stopped:** {sum(r['got'] != 'verified' for r in true)}/{len(true)}.  ",
        f"**Claims on a fact with one player untracked, held:** "
        f"{sum(r['got'] == 'held' for r in held)}/{len(held)}.",
        "",
        "| Family | Claims | As expected | Expected | Decided by |",
        "|---|---|---|---|---|",
    ]
    for f in families:
        expect = next(r["expect"] for r in results if r["family"] == f)
        n = by[(f, True)] + by[(f, False)]
        layers = Counter(r["by"] for r in results if r["family"] == f)
        decided = ", ".join(f"{layer} {k}" for layer, k in sorted(layers.items()))
        lines.append(f"| {f} | {n} | {by[(f, True)]}/{n} | {expect} | {decided} |")
    wrong = [r for r in results if r["got"] != r["expect"]]
    lines += ["", "## Every claim not as expected", ""]
    lines += [f"- {r['match']} {r['family']} ({r['kind']}): {r['text']!r} cites {r['evidence']}: "
              f"{r['got']}, expected {r['expect']}" for r in wrong] or ["None."]
    lines += ["", "## A sample of each family", ""]
    for f in families:
        sample = next(r for r in results if r["family"] == f)
        lines.append(f"- {f}: {sample['text']!r} → {sample['got']}")
    return "\n".join(lines) + "\n"


def build() -> str:
    body = ROWS.read_bytes()
    return report(evaluate(json.loads(body)), hashlib.sha256(body).hexdigest())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rows", action="store_true", help="simulate and write the shape facts first")
    args = ap.parse_args()
    if args.rows:
        ROWS.write_text(json.dumps(simulated_rows(), separators=(",", ":"), sort_keys=True) + "\n")
    REPORT.write_text(build())
    print(REPORT.read_text())


if __name__ == "__main__":
    main()
