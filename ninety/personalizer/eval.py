"""Measure the Personalizer: of the variants the published agent writes for true claims, how many
survive the re-check and air, by persona and language, why the rest were dropped, and how long a
request takes over A2A.

    uv run python -m ninety.personalizer.eval --seeds 21,33   # writes runs/eval/personalizer.md

Claims are the fact-checker evaluation's true claims (ninety/eval/factcheck_eval.py) that pass the
code checks, so each starts verified. Each goes through the real path: the A2A client, the A2A
server in process, the published `ninety-personalizer` at its pinned version. Needs Azure; cloud
sessions run it through `.github/workflows/agents-live.yml` (task `personalizer`).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import math
import re
import subprocess
import time
from collections import Counter
from pathlib import Path

from ninety.agents.contracts import LANGS, Profile

# The outage threshold and refusal, shared with every live evaluation (ninety/agents/evidence.py).
from ninety.agents.evidence import MAX_UNANSWERED_SHARE, NothingMeasured  # noqa: F401
from ninety.agents.factcheck import check
from ninety.personalizer import core
from ninety.personalizer.client import in_process

ROOT = Path(__file__).resolve().parents[2]
PROFILES = [
    Profile(persona, lang, club="home" if persona == "club" else None)
    for persona in core.WRITTEN for lang in LANGS
]


def claims(seeds: list[int], minutes: float, limit: int) -> list[tuple]:
    """Up to `limit` true claims per seed that pass the code checks, with their evidence."""
    from ninety.eval.factcheck_eval import cases

    out = []
    for seed in seeds:
        rows = [r for r in cases(seed, minutes) if r["true"]]
        ok = [r for r in rows if check(r["claim"], {e["id"]: e for e in r["evidence"]}).ok]
        out += [(seed, r["kind"], r["claim"], r["evidence"]) for r in ok[:limit]]
    return out


async def run(cases: list[tuple], ask, budget_s: float) -> list[dict]:
    client = in_process(core.model_personalizer(ask, timeout_s=budget_s - core.SERVER_MARGIN_S), budget_s)
    rows = []
    try:
        await _each(client, cases, rows)
    finally:
        await client.close()  # awaits any request cut off at the deadline before the loop closes
    return rows


async def _each(client, cases: list[tuple], rows: list[dict]) -> None:
    for request, (seed, kind, claim, evidence) in enumerate(cases):  # one at a time: each time alone
        started = time.perf_counter()
        variants = await client(claim, evidence, PROFILES)
        ms = (time.perf_counter() - started) * 1000
        for i, (p, v) in enumerate(zip(PROFILES, variants, strict=True)):
            why = client.last_dropped.get(i) if client.last_route == "remote" else client.last_route
            rows.append({"request": request, "seed": seed, "kind": kind, "persona": p.persona,
                         "lang": p.lang,
                         "claim": claim.text, "text": v.text, "dropped": why, "route": client.last_route,
                         "ms": ms})




def answered(row: dict) -> bool:
    """Whether the model answered the request this row belongs to. Unanswered: the client fell
    back (timeout, 5xx, refused), or the server's model call failed. Either measures the service,
    never how well the Personalizer writes."""
    return row["route"] == "remote" and not (row["dropped"] or "").startswith("server: model failed")


def requests_of(rows: list[dict]) -> dict:
    """One row per request sent, keyed by its index: two claims with the same words are two requests
    (audit row 9: keyed by seed and text they were one). Rows written before the index had one row
    per profile, in order, request after request, so their index is the row's position over that."""
    return {r.get("request", i // len(PROFILES)): r for i, r in enumerate(rows)}


# A 95th percentile is distinct from the maximum only from 20 values (nearest rank: the 19th of 20);
# below that the "p95" was the slowest request under another name (audit row 9).
MIN_FOR_P95 = 20


def _rank(values: list[float], q: float) -> float:
    """The q-quantile by nearest rank: the smallest value with at least q of the values at or below."""
    return values[max(0, math.ceil(q * len(values)) - 1)]


def timing(times: list[float]) -> str:
    if not times:
        return "Time per answered request: none answered."
    p95 = (f"p95 {_rank(times, 0.95):.0f} ms" if len(times) >= MIN_FOR_P95
           else f"p95 not shown ({len(times)} requests; it needs {MIN_FOR_P95})")
    return (f"Time per answered request (n = {len(times)}): p50 {_rank(times, 0.5):.0f} ms, {p95}, "
            f"max {times[-1]:.0f} ms.")


def report(rows: list[dict], label: str, seeds: str, budget_s: float = core.BUDGET_S, *, defs: dict) -> str:
    from ninety.agents.evidence import md_line

    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    requests = requests_of(rows)
    answered_requests = [r for r in requests.values() if answered(r)]
    times = sorted(r["ms"] for r in answered_requests)
    lines = [
        "# Personalizer evaluation",
        "",
        f"Generated by `uv run python -m ninety.personalizer.eval` on {datetime.date.today()} at commit "
        f"`{sha.stdout.strip()}`, seeds {seeds}, {label}, budget {budget_s} s. {len(requests)} true "
        f"claims, each sent once over A2A for {len(PROFILES)} profiles; the model answered "
        f"{len(answered_requests)} of them. A variant *airs* when it passes the re-check; otherwise the "
        "profile gets the verified English text. Air rates and times count answered requests only.",
        "",
        md_line(defs),
        "",
        "| Persona | Language | Variants | Model answered | Airs |",
        "|---|---|---|---|---|",
    ]
    for p in PROFILES:
        mine = [r for r in rows if (r["persona"], r["lang"]) == (p.persona, p.lang)]
        ok = [r for r in mine if answered(r)]
        lines.append(f"| {p.persona} | {p.lang} | {len(mine)} | {len(ok)} | "
                     f"{sum(r['dropped'] is None for r in ok)} |")
    # Reasons grouped by their words: the numbers in them become N.
    dropped = Counter(re.sub(r"\d+(?:\.\d+)?(?:st|nd|rd|th)?", "N", r["dropped"])
                      for r in rows if answered(r) and r["dropped"] is not None)
    outages = Counter((r["dropped"] if r["route"] == "remote" else r["route"])
                      for r in requests.values() if not answered(r))
    lines += [
        "",
        timing(times),
        "",
        "## Why variants were dropped",
        "",
        *([f"- {n} x {why}" for why, n in dropped.most_common(20)] or ["- none"]),
        "",
        "## Requests the model did not answer",
        "",
        *([f"- {n} x {why}" for why, n in outages.most_common()] or ["- none"]),
    ]
    return "\n".join(lines) + "\n"


async def _main(args, published=core.published_ask) -> str:
    seeds = [int(s) for s in args.seeds.split(",")]
    # Sign in before the slow part: building the claims simulates matches for minutes, and the
    # agents-live sign-in expires five minutes after login (an earlier run measured only that).
    # The simulation runs in a thread, so it does not hold the event loop meanwhile.
    async with published() as (ask, label):
        cases = await asyncio.to_thread(claims, seeds, args.minutes, args.limit)
        rows = await run(cases, ask, args.budget)
    raw = args.out.with_suffix(".json")
    raw.write_text(json.dumps(rows, indent=1, ensure_ascii=False, allow_nan=False))
    requests = requests_of(rows)
    unanswered = sum(not answered(r) for r in requests.values())
    if unanswered > MAX_UNANSWERED_SHARE * len(requests):
        raise NothingMeasured(
            f"the model did not answer {unanswered} of {len(requests)} requests "
            f"(over {MAX_UNANSWERED_SHARE:.0%}); see {raw}"
        )
    defs = definitions() if published is core.published_ask else {}  # a test's stand-in is no agent
    return report(rows, label, args.seeds, args.budget, defs=defs)


def definitions() -> dict:
    """The published Personalizer's definition (ninety/agents/evidence.py), as `core.published_ask`
    pins it."""
    from ninety.agents import evidence

    return evidence.of_code(lambda client: [core.personalizer_agent(client)])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", default="21,33", help="comma-separated simulator seeds (held out)")
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--limit", type=int, default=10, help="true claims per seed")
    ap.add_argument("--budget", type=float, default=core.BUDGET_S)
    ap.add_argument("--out", type=Path, default=ROOT / "runs/eval/personalizer.md")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = asyncio.run(_main(args))
    args.out.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
