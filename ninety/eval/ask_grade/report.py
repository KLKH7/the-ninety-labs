"""The Ask grader's report: a before/after table per intent and the worst answers, verbatim.

    uv run python -m ninety.eval.ask_grade.report --run main=<main.jsonl> --run "#423"=<pr423.jsonl> ... \\
        --out docs/eval/companion-full-eval

The first --run is the "before" column. Writes <out>.md and <out>.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ninety.eval.ask_grade.grade import CHECKS, CORE, OTHERS, load_intents
from ninety.eval.ask_grade.run import TIMES, summarise

WORST = 10


def _pct(v) -> str:
    return "–" if v is None else f"{100 * v:.0f}%"


def worst(rows: list[dict], n: int = WORST) -> list[dict]:
    """The answers that fail the core, most failed checks first, a chip first among equals; one per
    text and question."""
    bad = [r for r in rows if not r["core"]]
    bad.sort(
        key=lambda r: (-sum(v is False for v in r["checks"].values()), not r.get("chip"), r["intent"], r["t"])
    )
    out, seen = [], set()
    for r in bad:
        keys = {(r.get("text") or "").strip(), (r["intent"], r["q"])}  # one per answer text and per question
        if keys & seen:
            continue
        seen |= keys
        out.append(r)
        if len(out) == n:
            break
    return out


def _clock(t: float) -> str:
    return "FT" if t >= 5400 else f"{int(t // 60)}:{int(t % 60):02d}"


def render(runs: dict[str, list[dict]], meta: dict) -> tuple[str, dict]:
    intents, _ = load_intents()
    sums = {k: summarise(v) for k, v in runs.items()}
    labels = list(runs)
    lines = [
        "# The Ask, graded against the answer key (seed 8324)",
        "",
        "Every fan question in `ninety/eval/ask_grade/intents.json` (22 intents, at least 10 paraphrases "
        "each, the phone's chips marked) asked at 10:00, 33:50, 45:00, 60:00, 85:00 and full time through "
        "the Ask's code path (`companion_match.code_match_answer`), each answer graded by "
        "`ninety/eval/ask_grade` against the simulator's ground truth: over the footage when the answer "
        "says so, else over the whole match. "
        "The tolerances were committed before the first graded run (`tolerances.json`, commit "
        f"{meta.get('preregistered', '?')}). The footage shows "
        f"{meta.get('coverage', '?')} of the match.",
        "",
        "**The headline is the core pass rate**: an answer passes the core when it is answered (a "
        "verified reply, not a \"can't\"), relevant (its lead sentence carries the intent's metric), correct "
        '(within tolerance of the truth) and no false "not known" (no "can\'t" while the insights hold '
        "the facts). Each other check is its own column: no_future (a real leak: a minute past now said, or "
        "a cited fact, or a cited aggregate's source fact, timed after now), span_clipped (the answer's span "
        "ends by now; a span to the current minute bin's end with every cited fact before now fails only "
        'this), coverage_honest (a figure from part of the match says "in the footage"), natural (no '
        '"footage shown", "Esportes\'s", bare ranges, lower-case starts, "a London Athletic player") '
        "and consistent (the same headline as the intent's other paraphrases at that time). The CI ratchet "
        "holds every column separately.",
        "",
        "## Core pass rate per intent",
        "",
        "| Intent | " + " | ".join(labels) + " |",
        "|---|" + "---|" * len(labels),
    ]
    for it in intents:
        cells = [_pct(sums[k]["intents"].get(it["id"], {}).get("core")) for k in labels]
        lines.append(f"| {it['id']} | " + " | ".join(cells) + " |")
    lines.append("| **all** | " + " | ".join(f"**{_pct(sums[k]['core'])}**" for k in labels) + " |")
    lines.append("| chips | " + " | ".join(_pct(sums[k]["chips"].get("core")) for k in labels) + " |")
    lines += [
        "",
        "## Every check, all answers",
        "",
        "| Check | " + " | ".join(labels) + " |",
        "|---|" + "---|" * len(labels),
    ]
    for c in ("core", *CORE, *OTHERS, "pass"):
        name = {"core": "**core**", "pass": "all checks"}.get(c, c)
        lines.append(f"| {name} | " + " | ".join(_pct(sums[k].get(c)) for k in labels) + " |")
    for k in labels:
        lines += [
            "",
            f"## Each check per intent ({k})",
            "",
            "| Intent | core | " + " | ".join(CHECKS) + " |",
            "|---|---|" + "---|" * len(CHECKS),
        ]
        for it in intents:
            d = sums[k]["intents"].get(it["id"], {})
            lines.append(
                f"| {it['id']} | {_pct(d.get('core'))} | " + " | ".join(_pct(d.get(c)) for c in CHECKS) + " |"
            )
    lines += ["", "Answers per column: " + ", ".join(f"{k} {sums[k]['n']}" for k in labels) + ".", ""]
    for k in labels:
        if meta.get("sources", {}).get(k):
            lines.append(f"- **{k}**: {meta['sources'][k]}")
    for k in labels:
        lines += ["", f"## The {WORST} worst answers ({k}), verbatim", ""]
        for i, r in enumerate(worst(runs[k]), 1):
            failed = [c for c, v in r["checks"].items() if v is False]
            chip = " (a chip)" if r.get("chip") else ""
            lines.append(f"{i}. **{r['intent']}**, {_clock(r['t'])}{chip}: “{r['q']}”  ")
            lines.append(f"   → “{(r.get('text') or '').strip()}”  ")
            lines.append(
                f"   fails: {', '.join(failed)}" + (f"; flags: {', '.join(r['flags'])}" if r["flags"] else "")
            )
    lines += [
        "",
        f"Times: {', '.join(_clock(t) for t in TIMES)}. Regenerate with "
        "`uv run python -m ninety.eval.ask_grade.report` (command in its docstring).",
        "",
    ]
    body = {
        "meta": meta,
        "summaries": sums,
        "worst": {
            k: [
                {k2: r.get(k2) for k2 in ("intent", "t", "q", "text", "checks", "flags", "chip")}
                for r in worst(runs[k])
            ]
            for k in labels
        },
    }
    return "\n".join(lines), body


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", action="append", required=True, metavar="LABEL=JSONL")
    ap.add_argument("--source", action="append", default=[], metavar="LABEL=TEXT", help="what each column is")
    ap.add_argument("--meta", type=Path, default=None, help="a JSON of extra meta (preregistered, coverage)")
    ap.add_argument("--out", type=Path, required=True, help="the report's path without suffix")
    args = ap.parse_args(argv)
    runs = {}
    for spec in args.run:
        label, path = spec.split("=", 1)
        runs[label] = [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
    meta = json.loads(args.meta.read_text()) if args.meta else {}
    meta["sources"] = dict(s.split("=", 1) for s in args.source)
    md, body = render(runs, meta)
    args.out.with_suffix(".md").write_text(md)
    args.out.with_suffix(".json").write_text(json.dumps(body, indent=1, default=str) + "\n")
    print(args.out.with_suffix(".md"))


if __name__ == "__main__":
    main()
