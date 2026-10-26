"""Score Kian's blind labels against the fact-checker, by RULE.md.

    python3 docs/eval/factcheck-human-labels/score.py docs/eval/factcheck-human-labels/labels.json
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUPPORTED = {"passed", "rewritten"}  # the checker let these air
Z = 1.959964  # 95%


def wilson(k: int, n: int) -> str:
    if n == 0:
        return "n/a (n = 0)"
    p = k / n
    d = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / d
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return f"{k}/{n} = {p:.0%} (95% CI {max(0, c - h):.0%} to {min(1, c + h):.0%})"


def main() -> None:
    labels = json.loads(Path(sys.argv[1]).read_text())["labels"]
    key = json.loads((HERE / "key.json").read_text())
    rows = [(iid, k, (labels.get(iid) or {}).get("answer"), (labels.get(iid) or {}).get("note", ""))
            for iid, k in key.items()]
    missing = [iid for iid, _, a, _ in rows if a is None]
    unsure = [iid for iid, _, a, _ in rows if a == "unsure"]
    decided = [(iid, k, a) for iid, k, a, _ in rows if a in ("yes", "no")]
    agree = sum((k["stratum"] in SUPPORTED) == (a == "yes") for _, k, a in decided)
    passed = [(iid, a) for iid, k, a in decided if k["stratum"] in SUPPORTED]
    held = [(iid, a) for iid, k, a in decided if k["stratum"] not in SUPPORTED]
    lines = [
        "# Fact-checker against Kian's blind labels",
        "",
        f"{len(key)} items by RULE.md; {len(decided)} answered yes or no, {len(unsure)} unsure, "
        f"{len(missing)} unanswered (both left out of every rate).",
        "",
        f"- Agreement: {wilson(agree, len(decided))}",
        "- False passes (the checker aired it; Kian: not supported): "
        + wilson(sum(a == "no" for _, a in passed), len(passed)),
        "- False holds (the checker kept it off air; Kian: supported): "
        + wilson(sum(a == "yes" for _, a in held), len(held)),
        "",
        "By layer (each layer judged only on the items it decided):",
        "",
    ]
    # The code checks decide every item that is not held: "not supported" exactly when they rejected it.
    code = [(k["stratum"] != "rejected by code", a) for _, k, a in decided if k["stratum"] != "held"]
    # The Judge decides only what the code checks passed: passed and rewritten (it passed them), and
    # the ones it rejected.
    judged = [(k["stratum"] in SUPPORTED, a) for _, k, a in decided
              if k["stratum"] in ("passed", "rewritten", "rejected by the Judge")]
    held = [(False, a) for _, k, a in decided if k["stratum"] == "held"]
    for name, rows_ in (("Code checks", code), ("Judge", judged), ("Confidence gate (held)", held)):
        agree_ = sum(said == (a == "yes") for said, a in rows_)
        fp = [a for said, a in rows_ if said]
        fh = [a for said, a in rows_ if not said]
        lines.append(f"- {name}: agreement {wilson(agree_, len(rows_))}; false passes "
                     f"{wilson(fp.count('no'), len(fp))}; false holds {wilson(fh.count('yes'), len(fh))}")
    lines += [
        "",
        "| Stratum | Items | Kian yes | Kian no | Unsure |",
        "|---|---|---|---|---|",
    ]
    for s in ("passed", "rewritten", "rejected by code", "rejected by the Judge", "held"):
        mine = [a for _, k, a, _ in rows if k["stratum"] == s]
        counts = " | ".join(str(mine.count(a)) for a in ("yes", "no", "unsure"))
        lines.append(f"| {s} | {len(mine)} | {counts} |")
    lines += ["", "Disagreements, with Kian's note:", ""]
    for iid, k, a, note in rows:
        if a in ("yes", "no") and (k["stratum"] in SUPPORTED) != (a == "yes"):
            lines.append(f"- {iid} ({k['stratum']}, {k['verdict']}, {k['kind']}): Kian {a}. {note}".rstrip())
    lines += ["", "With about 25 items the intervals are wide: these are a check on the checker, not a "
              "measurement of its rates."]
    text = "\n".join(lines) + "\n"
    (HERE / "score.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
