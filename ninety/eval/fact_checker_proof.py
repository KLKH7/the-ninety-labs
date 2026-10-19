"""Regenerates the fact-checker's proof: the planted-claim report, the ablation and the failure
table, offline (no model calls, no Azure, a few seconds of CPU).

    uv run python -m ninety.eval.fact_checker_proof          # writes the files below
    uv run python -m ninety.eval.fact_checker_proof --check  # fails if any is out of date

The output is byte for byte the same on every run: no dates, no timings, inputs from committed files.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ninety.eval import ablation, failure_table, planted

ROOT = Path(__file__).resolve().parents[2]
COMMAND = "uv run python -m ninety.eval.fact_checker_proof"
OUTPUTS = {
    "planted": ROOT / "docs/eval/fact-checker-planted.md",
    "ablation": ROOT / "docs/eval/ablation.md",
    "results": ROOT / "docs/eval/ablation.json",
    "failures": ROOT / "docs/eval/failure-table.md",
}


def render() -> dict[str, str]:
    data = planted.load()
    rows = ablation.run(data)
    return {
        "planted": ablation.fact_checker_report(rows, data, COMMAND),
        "ablation": ablation.ablation_report(rows, data, COMMAND),
        "results": ablation.results(rows),
        "failures": failure_table.report(COMMAND),
    }


def stale() -> list[Path]:
    """The output files whose committed text differs from a fresh render."""
    return [
        OUTPUTS[k] for k, text in render().items()
        if not OUTPUTS[k].exists() or OUTPUTS[k].read_text() != text
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if a committed file is out of date")
    args = ap.parse_args()
    if args.check:
        if out := stale():
            sys.exit("out of date: " + ", ".join(str(p.relative_to(ROOT)) for p in out) + f"; run {COMMAND}")
        print("up to date")
        return
    for key, text in render().items():
        OUTPUTS[key].write_text(text)
        print(f"wrote {OUTPUTS[key].relative_to(ROOT)}")


if __name__ == "__main__":
    main()
