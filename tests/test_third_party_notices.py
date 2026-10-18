"""THIRD_PARTY_NOTICES.md lists every locked dependency, and every licence is one AGENTS.md allows."""

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# The licences the rule in AGENTS.md names, as written in the notices table. A dependency under any
# other licence needs the rule changed first.
ALLOWED = {
    "MIT",
    "MIT-0",
    "MIT-CMU",
    "Apache-2.0",
    "LLVM-exception",
    "BSD",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "0BSD",
    "ISC",
    "PSF-2.0",
    "CNRI-Python",
    "Zlib",
    "BSL-1.0",
    "CC0-1.0",
    "MPL-2.0",
}
PROPRIETARY = "NVIDIA proprietary"  # a redistributable runtime, allowed only for NVIDIA's own packages


def locked_packages(lock: dict) -> set[tuple[str, str]]:
    """(name, version) pairs: a package can be locked at two versions, one per Python version."""
    return {(p["name"], p["version"]) for p in lock["package"] if p.get("source", {}).get("registry")}


def notices_table(text: str) -> dict[tuple[str, str], str]:
    section = text.split("## Every locked dependency", 1)[1].split("\n## ", 1)[0]
    rows = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0] not in ("Package", "---"):
            rows[(cells[0], cells[1])] = cells[2]
    return rows


def licence_problems(name: str, licence: str) -> list[str]:
    if licence == PROPRIETARY:
        return [] if name.startswith(("nvidia-", "cuda-toolkit")) else [f"{name}: proprietary, not NVIDIA's"]
    tokens = [t for t in re.split(r"\s+|[()]", licence) if t and t not in ("AND", "OR", "WITH")]
    return [f"{name}: {t} is not allowed" for t in tokens if t not in ALLOWED]


def table_problems(locked: set[tuple[str, str]], table: dict[tuple[str, str], str]) -> list[str]:
    problems = [f"{n} {v} is locked but not in the notices" for n, v in sorted(locked) if (n, v) not in table]
    problems += [
        f"{n} {v} is in the notices but not locked" for n, v in sorted(table) if (n, v) not in locked
    ]
    for (name, _), licence in table.items():
        problems += licence_problems(name, licence)
    return problems


def test_every_locked_dependency_is_listed_with_an_allowed_licence():
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    table = notices_table((ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8"))
    assert table_problems(locked_packages(lock), table) == []


@pytest.mark.parametrize(
    "locked, table, expect",
    [
        ({("tool", "1.0")}, {}, "not in the notices"),
        ({("tool", "1.0")}, {("tool", "0.9"): "MIT"}, "tool 1.0 is locked but not in the notices"),
        ({("tool", "1.0"), ("tool", "2.0")}, {("tool", "1.0"): "MIT"}, "tool 2.0 is locked"),
        ({("tool", "1.0")}, {("tool", "1.0"): "GPL-3.0-only"}, "GPL-3.0-only is not allowed"),
        ({("tool", "1.0")}, {("tool", "1.0"): "MIT AND AGPL-3.0"}, "AGPL-3.0 is not allowed"),
        ({("tool", "1.0")}, {("tool", "1.0"): "NVIDIA proprietary"}, "proprietary, not NVIDIA's"),
    ],
)
def test_each_problem_is_caught(locked, table, expect):
    assert any(expect in p for p in table_problems(locked, table))


def test_allowed_combinations_pass():
    assert licence_problems("numpy", "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0") == []
    assert licence_problems("torch", "Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSL-1.0") == []
    assert licence_problems("nvidia-cudnn-cu13", "NVIDIA proprietary") == []
