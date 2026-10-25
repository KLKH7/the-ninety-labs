"""The insight fact-check measured: planted false claims caught, true ones let through, unsure held.

On a stand-in tracked match (ninety/eval/insight_standin.py: a simulated match spoiled as the
tracker spoils it), every sentence code can say about every fact and every 15-minute summary
(`companion_match.code_texts`) is a true claim. Each is then planted with defects, one at a time:

- number: a stated number one more, and one less, than the fact's;
- spelled: the wrong number written in words;
- club: the two clubs' names swapped;
- team word: the acting club replaced by "the home side";
- id: the player's name replaced by his track id;
- name: a named player replaced by another name on the sheets;
- kind: the sentence cites a fact of another kind;
- minute: the minute one later;
- polarity: the direction turned around (won back or not, lost or completed, to an open teammate
  or not, somebody open or nobody), numbers and names kept;
- uncited: no evidence.

A planted claim is caught when the check rejects it. Separately, each true claim on a fact that is
not confident is held, never passed. Code wrote the claims and code checks them, written by the same
author: this is an author's test of the reader, not an independent audit (docs/LESSONS.md, lesson 4).

    uv run python -m ninety.eval.insight_claims RUN --minutes 30 --out docs/eval/insight-claims.json
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from collections import Counter
from pathlib import Path

from ninety.agents import companion_match as cm
from ninety.agents.contracts import status_for
from ninety.agents.factcheck import Claim
from ninety.agents.insight_check import verify
from ninety.eval import insight_standin
from ninety.intel.teamsheet import Fixture

# Plants that reverse which way a fact went (the merge queue's review, lesson 11): each turns a true
# sentence's direction around, keeping its numbers and names.
POLARITY_FLIPS = (
    (r"(?<!never )\bwon (it|the ball) back", r"never won \1 back"),
    (r"\bnever won it back", "won it back"),
    (r"\blost the ball and had", "won the ball back and had"),
    (r"\blost (a|the) pass with no", r"completed \1 pass with no"),
    (r"\blost the ball with no", "completed the pass with no"),
    (r"\bbut lost the pass elsewhere", "and the pass found an open teammate"),
    (r"\bbut the pass went elsewhere and was lost", "and the pass found an open teammate"),
    (r"\bhad \d+ (open )?teammates?", "had no teammates"),
)
WORDS = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
}


SUMMARY_TOOLS = (
    "line_breaks", "overloads", "counter_press", "pass_options", "possession", "territory", "shots",
    "passing", "score",
)


def facts_and_summaries(mi) -> list[dict]:
    rows = [f for kind in mi.facts.values() for f in kind]
    for lo in range(1, mi.minutes + 1, cm.WINDOW_MIN):
        hi = lo + cm.WINDOW_MIN - 1
        for tool in SUMMARY_TOOLS:
            rows += getattr(mi, tool)(lo, hi)["summary"]
        rows += mi.players(lo, hi)["facts"]
        rows += mi.physical(lo, hi)["facts"] + mi.passing(lo, hi)["facts"]
        rows += mi.style(lo, hi)["summary"]
    rows += [f for kind in ("counter", "one_two") for f in mi.facts.get(kind, ())]
    return rows


def plants(text: str, fact: dict, mi, other: dict | None) -> list[tuple[str, Claim]]:
    clubs = mi.fixture.clubs
    ev = [fact["id"]]
    out = []
    numbers = [
        m
        for m in re.finditer(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.]*\d)", text)
        if not re.match(r"\s*(?:to )?minute", text[m.end() :])
        and "minute" not in text[max(0, m.start() - 7) : m.start()]
    ]
    for m in numbers[:2]:
        n = float(m.group())
        for d in (1, -1):
            if n + d < 0:
                continue
            new = cm._number(round(n + d, 1))
            out.append(("number", Claim(text[: m.start()] + new + text[m.end() :], ev)))
        if n.is_integer() and int(n) + 2 in WORDS:
            out.append(("spelled", Claim(text[: m.start()] + WORDS[int(n) + 2] + text[m.end() :], ev)))
    a, b = clubs["home"], clubs["away"]
    if a in text or b in text:
        swapped = text.replace(a, "\0").replace(b, a).replace("\0", b)
        out.append(("club", Claim(swapped, ev)))
    if fact.get("club") and fact["club"] in text:
        out.append(("team word", Claim(text.replace(fact["club"], "the home side", 1), ev)))
    who = fact.get("passer_is")
    if who and who in text and fact.get("passer"):
        out.append(("id", Claim(text.replace(who, fact["passer"]), ev)))
        named = [s for s in mi.sheet_names() if s != who]
        if mi.people.get(fact["passer"], {}).get("name"):
            out.append(("name", Claim(text.replace(who, named[0]), ev)))
    if other is not None:
        out.append(("kind", Claim(text, [other["id"]])))
    m = re.search(r"minute (\d+)", text)
    if m:
        out.append(("minute", Claim(text[: m.start(1)] + str(int(m.group(1)) + 1) + text[m.end(1) :], ev)))
    for pattern, repl in POLARITY_FLIPS:
        flipped = re.sub(pattern, repl, text, count=1)
        if flipped != text:
            out.append(("polarity", Claim(flipped, ev)))
    out.append(("uncited", Claim(text, [])))
    return out


def run(mi) -> dict:
    rows = facts_and_summaries(mi)
    known = {f["id"]: {**f, "clubs": mi.fixture.clubs} for f in rows}
    clubs, people, names = mi.fixture.clubs, mi.people, mi.sheet_names()
    by_kind = {}
    for f in rows:
        by_kind.setdefault(f["kind"], f)
    true_ok = true_bad = held_ok = held_bad = true_held = 0
    wrongly = []
    caught, missed = Counter(), Counter()
    escapes = []
    ms = []
    for f in rows:
        unsure = not f.get("confident", True)
        texts = cm.code_texts({**known[f["id"]], "confident": True})
        for text in texts:
            claim = Claim(text, [f["id"]])
            t0 = time.perf_counter()
            v = verify(claim, known, clubs, people, names)
            ms.append((time.perf_counter() - t0) * 1000)
            status = status_for(v)
            if unsure:
                held_ok += status == "held"
                held_bad += status == "verified"
                continue
            if status == "verified":
                true_ok += 1
            else:
                true_bad += 1
                true_held += status == "held"
                wrongly.append({"text": text, "reasons": v.reasons})
            other = next((g for k, g in by_kind.items() if k != f["kind"] and g.get("confident")), None)
            for kind, planted in plants(text, known[f["id"]], mi, other):
                if planted.text == text and planted.evidence == claim.evidence:
                    continue
                pv = verify(planted, known, clubs, people, names)
                if status_for(pv) == "rejected":
                    caught[kind] += 1
                else:
                    missed[kind] += 1
                    escapes.append(
                        {
                            "kind": kind,
                            "text": planted.text,
                            "evidence": planted.evidence,
                            "status": status_for(pv),
                        }
                    )
    return {
        "facts": len(rows),
        "true_claims": true_ok + true_bad,
        "true_wrongly_stopped": true_bad,
        "true_held": true_held,
        "unsure_claims": held_ok + held_bad,
        "unsure_held": held_ok,
        "unsure_passed": held_bad,
        "planted": sum(caught.values()) + sum(missed.values()),
        "planted_caught": sum(caught.values()),
        "caught_by_kind": dict(caught),
        "missed_by_kind": dict(missed),
        "escapes": escapes[:20],
        "wrongly_stopped": wrongly[:20],
        "check_ms": {
            "p50": round(statistics.median(ms), 3),
            "p95": round(statistics.quantiles(ms, n=20)[18], 3),
        }
        if len(ms) > 1
        else {},
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run", type=Path, help="a simulated match folder (frames.jsonl, events.jsonl, meta.json)")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--home", default="OAK")
    ap.add_argument("--away", default="FEN")
    ap.add_argument("--missing", type=float, nargs="+", default=[0.0, 0.05])
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    meta = json.loads((args.run / "meta.json").read_text())
    fixture = Fixture(int(meta["seed"]), args.home, args.away)
    report = {"run": args.run.name, "seed": meta["seed"], "minutes": args.minutes, "by_missing": {}}
    for missing in args.missing:
        mi = insight_standin.build(args.run, args.minutes, fixture, missing=missing)
        report["gates"] = mi.gates
        report["by_missing"][str(missing)] = run(mi)
        r = report["by_missing"][str(missing)]
        print(
            missing,
            {
                k: r[k]
                for k in (
                    "true_claims",
                    "true_wrongly_stopped",
                    "planted",
                    "planted_caught",
                    "unsure_claims",
                    "unsure_held",
                    "missed_by_kind",
                )
            },
        )
    args.out.write_text(json.dumps(report, indent=1) + "\n")
    args.out.with_suffix(".md").write_text(markdown(report))


def markdown(report: dict) -> str:
    lines = [
        "# Insight claims: the fact-check on planted and true claims",
        "",
        "Generated by `uv run python -m ninety.eval.insight_claims <run> "
        f"--minutes {report['minutes']:g}` on the simulated match of seed {report['seed']} "
        f"({report['run']}), spoiled as the tracker spoils it (ninety/eval/insight_standin.py). Code "
        "checks only: no model and no Judge were called, nothing was spent.",
        "",
        "Caveat: the same author wrote the claim templates, the plants and the checker. This is an "
        "author's test of the reader, not an independent audit (docs/LESSONS.md, lesson 4). The plants "
        "reverse code's own templates. Free paraphrases meet the closed direction check: for a fact "
        "whose direction matters, any word left once its own phrases, numbers, names and glue words "
        "are taken out holds the sentence; the reviewer's 125 paraphrases and reversals are tests "
        "(tests/test_insight_check.py). Every model sentence also goes to the Judge.",
        "",
        "| Players missing a frame | True claims | Wrongly stopped | Planted false | Caught "
        "| Unsure claims | Held |",
        "|---|---|---|---|---|---|---|",
    ]
    for missing, r in report["by_missing"].items():
        lines.append(
            f"| {float(missing):.0%} | {r['true_claims']} | {r['true_wrongly_stopped']} | {r['planted']} | "
            f"{r['planted_caught']} | {r['unsure_claims']} | {r['unsure_held']} |"
        )
    lines += ["", "Caught by kind of plant:", ""]
    for missing, r in report["by_missing"].items():
        kinds = ", ".join(f"{k} {v}" for k, v in sorted(r["caught_by_kind"].items()))
        missed = ", ".join(f"{k} {v}" for k, v in sorted(r["missed_by_kind"].items())) or "none"
        lines.append(
            f"- {float(missing):.0%} missing: {kinds}; missed: {missed}; "
            f"check p50 {r['check_ms'].get('p50')} ms, p95 {r['check_ms'].get('p95')} ms"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
