"""Turn a nightly evaluation's reports into committed evidence: docs/eval/nightly/<date>/.

    uv run python -m ninety.eval.nightly runs/eval --date 2026-10-24          # copy, then check
    uv run python -m ninety.eval.nightly runs/eval --date 2026-10-24 --body   # also print a PR body

`.github/workflows/evals.yml` runs this after the nightly and opens a pull request with the copy;
a maintainer can run it on a downloaded `eval-reports` artifact the same way. The reports are
copied byte for byte, never edited (docs/EVALUATION.md). It refuses a report that does not record
which agent definitions it ran with (ninety/agents/evidence.py): an archive that cannot say what it
measured is not evidence. A dated archive is history: tests/test_evidence_fresh.py never calls it
stale, while the top-level docs/eval/ reports it may replace are checked against the code.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from ninety.agents import evidence

ROOT = Path(__file__).resolve().parents[2]
NIGHTLY = ROOT / evidence.NIGHTLY
KINDS = (".md", ".json")
# Reports the nightly still writes whose method is known to be wrong: archived as history, and
# named in the PR so nobody promotes them. Remove an entry in the change that fixes the method.
INVALID = {
    "analyst.md": "the Analyst reads the deployed match through the tools while grading uses this "
    "commit's events (ninety/agents/analyst_eval.py, lesson 90); not a valid number until fixed",
}


class NotEvidence(RuntimeError):
    """A nightly report that does not record its agent definitions."""


def reports(src: Path) -> list[Path]:
    return sorted(p for p in src.iterdir() if p.is_file() and p.suffix in KINDS)


def check(src: Path) -> list[str]:
    """Why each report in `src` is not committable evidence; empty when all are."""
    out = []
    for path in reports(src):
        found = evidence.read(path, src)
        if found is None:
            out.append(f"{path.name}: names no agent definition")
        elif found[1] != "recorded" and not found[1].startswith("data of "):
            out.append(f"{path.name}: names agent versions but no definition fingerprints ({found[1]})")
        elif any(r.sha is None for r in found[0]):
            out.append(f"{path.name}: an agent without a fingerprint")
    return out


def archive(src: Path, date: str, dest_root: Path = NIGHTLY) -> list[Path]:
    """Copy every report in `src` to `dest_root/date/`, after checking them all."""
    if not reports(src):
        raise NotEvidence(f"{src}: no reports to archive")
    if errors := check(src):
        raise NotEvidence("; ".join(errors))
    dest = dest_root / date
    if dest.exists():
        raise FileExistsError(f"{dest} exists: one archive a night, never overwritten")
    dest.mkdir(parents=True)
    return [Path(shutil.copy2(p, dest / p.name)) for p in reports(src)]


def body(copied: list[Path], date: str, run_url: str = "") -> str:
    """A pull request body: each report's header, up to its first section."""
    lines = [
        f"Nightly agent evaluation of {date}, committed unedited from the `evals` workflow"
        + (f" ([run]({run_url}))" if run_url else "")
        + ".",
        "",
    ]
    for path in copied:
        if path.suffix != ".md":
            continue
        head = path.read_text().split("\n## ", 1)[0].strip()
        lines += [f"### `{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path.name}`", ""]
        if path.name in INVALID:
            lines += [f"**Invalid, do not promote:** {INVALID[path.name]}.", ""]
        lines += [head, ""]
    lines += [
        "The top-level reports in `docs/eval/` are not replaced here: promoting a nightly to the",
        "published number is a reviewed change of its own (`tests/test_evidence_fresh.py`,",
        "`ninety/agents/evidence.py` STALE). PRs opened by the workflow's token do not start CI on",
        "their own: close and reopen this PR, or push to its branch, to run it.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src", type=Path, help="the nightly's output directory (runs/eval)")
    ap.add_argument("--date", required=True, help="the night, YYYY-MM-DD (the archive's folder)")
    ap.add_argument("--body", type=Path, help="also write a pull request body here")
    ap.add_argument("--run-url", default="")
    args = ap.parse_args(argv)
    try:
        copied = archive(args.src, args.date)
    except (NotEvidence, FileExistsError) as e:
        sys.exit(f"not archived: {e}")
    for p in copied:
        print(f"archived {p.relative_to(ROOT) if p.is_relative_to(ROOT) else p}")
    if args.body:
        args.body.write_text(body(copied, args.date, args.run_url))


if __name__ == "__main__":
    main()
