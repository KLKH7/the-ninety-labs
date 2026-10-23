"""Which agent definitions produced each committed piece of agent evidence, and is it still them?

Every report a published agent produced (docs/eval/) and every recorded replay (replays/) says
which Foundry agent definitions it ran with: each agent's name, published version and
`definition_sha` (the fingerprint `ninety/agents/foundry.py` pins in `foundry_agents.json`). A
JSON report carries them under `agent_definitions`; a Markdown report carries one line that
starts `Agent definitions:`; a replay carries them as a field of the recording. The writers call
`record` (published agents) or `local` (an unpublished definition) and `md_line`.

    uv run python -m ninety.agents.evidence     # every evidence file, what ran, fresh or stale

Files written before fingerprints were recorded name their agents only as `ninety-judge:1` (or,
in the workflow replay, `pins`). Their fingerprints are derived, not invented: `HISTORY` is every
version ever pinned in `foundry_agents.json` on any branch, read from its git history, and each
(name, version) there maps to exactly one fingerprint. Publishing stores that fingerprint in the
version's Foundry metadata and `foundry.pinned` refuses a run whose code differs, so a run that
called `ninety-judge:1` ran definition `3eea4db1096b7a49`.

`tests/test_evidence_fresh.py` compares every file's definitions with the code's: a file whose
agents changed since it ran fails CI unless `STALE` lists it, with why and the run that fixes it.
Dated nightly archives (docs/eval/nightly/<date>/) are history: they must record their
definitions, but are never stale.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEY = "agent_definitions"
LINE = "Agent definitions:"
NIGHTLY = "docs/eval/nightly"
SCANNED = ("docs/eval/**/*.json", "docs/eval/**/*.md", "replays/*.json")

# Every (Foundry name, version) pinned in ninety/agents/foundry_agents.json on any branch, from
# `git log --all -- ninety/agents/foundry_agents.json` (Oct 17 to Oct 23, 2026), with the
# definition fingerprint it was published from. Frozen: it exists only to read files written
# before reports recorded fingerprints; every later file records its own. Versions with the same
# fingerprint (analyst 3 and 5, judge 1 and 3, judge 2 and 4) were republished unchanged.
HISTORY: dict[tuple[str, str], str] = {
    ("ninety-analyst", "2"): "ac3506fea4a55bf5",
    ("ninety-analyst", "3"): "c94c92bba7d0d03d",
    ("ninety-analyst", "4"): "ddcdc5682ca9053e",
    ("ninety-analyst", "5"): "c94c92bba7d0d03d",
    ("ninety-challenger", "1"): "9495af6c68f9aa7b",
    ("ninety-challenger", "2"): "84ddee6b377e8210",
    ("ninety-companion", "1"): "de3461b01cfc1bf1",
    ("ninety-describer", "1"): "064da096ff49c4f1",
    ("ninety-judge", "1"): "3eea4db1096b7a49",
    ("ninety-judge", "2"): "2b04c8ad1ac3c950",
    ("ninety-judge", "3"): "3eea4db1096b7a49",
    ("ninety-judge", "4"): "2b04c8ad1ac3c950",
    ("ninety-moment-analyst", "1"): "45c34e6301b3ae52",
    ("ninety-personalizer", "1"): "6ea7cb9fb8d81c74",
    ("ninety-personalizer", "2"): "14cda33892950116",
    ("ninety-tactician", "1"): "95abe9d50e602a7d",
    ("ninety-tactician", "2"): "59ffc39047d2afce",
}

_RERUN_EVAL = "the agents-live `eval` task at main (it runs factcheck_eval, analyst_eval and companion_eval)"
# Evidence whose agents changed since it ran, kept on purpose. Each says why it is still committed
# and which run replaces it; the test fails when an entry is no longer stale, so the list cannot rot.
STALE: dict[str, dict[str, str]] = {
    "docs/eval/fact-checker.md": {
        "why": "ninety-judge:1 (3eea4db1); the Judge is now ninety-judge:4 (2b04c8ad). The nightly "
        "on judge:4 has run but its reports were never committed (the nightly wrote only runs/eval/).",
        "rerun": _RERUN_EVAL + ", or the first committed nightly (docs/eval/nightly/)",
    },
    "docs/eval/fact-checker.json": {
        "why": "the data of docs/eval/fact-checker.md, same run",
        "rerun": "as docs/eval/fact-checker.md",
    },
    "docs/eval/analyst.md": {
        "why": "graded with ninety-judge:1; also invalid on its own terms: the Analyst read the deployed "
        "match through the tools while grading used this commit's events (lesson 90)",
        "rerun": "fix ninety/agents/analyst_eval.py to give the events inline (separate package), then "
        + _RERUN_EVAL,
    },
    "docs/eval/personalizer.md": {
        "why": "ninety-personalizer:1 (6ea7cb9f); v2 (14cda338, the casual persona keeps the clock, #191) "
        "is published and has not been measured live",
        "rerun": "the agents-live `personalizer` task at main",
    },
    "docs/eval/personalizer.json": {
        "why": "the data of docs/eval/personalizer.md, same run",
        "rerun": "as docs/eval/personalizer.md",
    },
    "docs/eval/planted-claims-v1.json": {
        "why": "frozen planted-claim set v1: its recorded Judge answers are ninety-judge:1's, from the "
        "Oct 17 fact-checker run; its sha256 is cited by the reports built from it, so it is never edited",
        "rerun": "a planted set v2 with the current Judge's answers recorded "
        "(ninety/eval/planted_judge.py over every claim, live), then fact_checker_proof",
    },
    "docs/eval/fact-checker-planted.md": {
        "why": "built offline from planted-claims-v1.json, so its Judge answers are ninety-judge:1's",
        "rerun": "as docs/eval/planted-claims-v1.json",
    },
    "docs/eval/ablation.md": {
        "why": "built offline from planted-claims-v1.json, so its Judge answers are ninety-judge:1's",
        "rerun": "as docs/eval/planted-claims-v1.json",
    },
    "docs/eval/ablation.json": {
        "why": "the data of docs/eval/ablation.md, same build",
        "rerun": "as docs/eval/planted-claims-v1.json",
    },
}

_LABEL = re.compile(r"\b(ninety-[a-z]+(?:-[a-z]+)*):(\d+)\b")
_MD = re.compile(r"`(ninety-[a-z]+(?:-[a-z]+)*):([\w.-]+)` definition `([0-9a-f]{16})`")


@dataclass(frozen=True)
class Ran:
    """One agent definition a file says it ran with."""

    name: str
    version: str | None
    sha: str | None  # None: the file names a version no registry ever pinned


@dataclass
class Evidence:
    path: str
    ran: list[Ran]
    source: str  # "recorded" (the file's own fingerprints), "derived" (labels + HISTORY), "data of <md>"
    stale: list[Ran] = field(default_factory=list)
    unknown: list[Ran] = field(default_factory=list)

    @property
    def fresh(self) -> bool:
        return not self.stale and not self.unknown


# Writers ------------------------------------------------------------------------------------


def record(agents) -> dict[str, dict[str, str]]:
    """The published definitions a live run calls: name -> version and fingerprint. Raises
    RegistryDrift, as `foundry.pinned` does, if the code no longer matches its pinned version."""
    from ninety.agents import foundry

    out = {}
    for agent in agents:
        name, version = foundry.pinned(agent)
        out[name] = {"version": version, "definition_sha": foundry.fingerprint(foundry.definition(agent))}
    return dict(sorted(out.items()))


def of_code(build) -> dict[str, dict[str, str]]:
    """`record` for the agents `build(client)` returns, built from this commit's code with a
    credential that is never used to sign in. For a writer whose live path builds its agents out of
    reach (inside a server or a workflow): that path calls `foundry.pinned` and refuses to run when
    the code differs from the pin, so these are the definitions it ran."""
    from azure.identity import DefaultAzureCredential

    from ninety.agents import foundry

    return record(build(foundry.chat_client(DefaultAzureCredential())))


def local(agents) -> dict[str, dict[str, str | None]]:
    """Definitions run from the code without publishing (`--local-judge`): no version."""
    from ninety.agents import foundry

    return dict(
        sorted(
            (
                foundry.foundry_name(a),
                {"version": None, "definition_sha": foundry.fingerprint(foundry.definition(a))},
            )
            for a in agents
        )
    )


def md_line(defs: dict[str, dict]) -> str:
    """The Markdown line a report states its definitions in (parsed back by `read`)."""
    if not defs:
        return f"{LINE} none (no published agent ran)."
    parts = [
        f"`{n}:{d['version'] or 'local'}` definition `{d['definition_sha']}`" for n, d in sorted(defs.items())
    ]
    return f"{LINE} " + ", ".join(parts) + "."


# Readers ------------------------------------------------------------------------------------


def _from_defs(defs: dict) -> list[Ran]:
    return [
        Ran(n, None if d.get("version") is None else str(d["version"]), d.get("definition_sha"))
        for n, d in sorted(defs.items())
    ]


def _derived(labels) -> list[Ran]:
    return [Ran(n, v, HISTORY.get((n, v))) for n, v in sorted(set(labels))]


def read(path: Path, root: Path = ROOT) -> tuple[list[Ran], str] | None:
    """What a file says it ran with, and how we know; None when it names no published agent."""
    text = path.read_text()
    if path.suffix == ".json":
        data = json.loads(text)
        if isinstance(data, dict) and data.get(KEY) is not None:  # null: a recording made before
            return _from_defs(data[KEY]), "recorded"
        labels = _LABEL.findall(text)
        if isinstance(data, dict) and isinstance(data.get("pins"), dict):  # a workflow recording
            labels += [(n, str(v)) for n, v in data["pins"].items()]
        if labels:
            return _derived(labels), "derived"
        sibling = path.with_suffix(".md")  # a list-shaped report's data: its .md says what ran
        if sibling.exists() and (found := read(sibling, root)):
            return found[0], f"data of {sibling.relative_to(root)}"
        return None
    for line in text.splitlines():
        if line.startswith(LINE):
            if "none (no published agent ran)" in line:
                return [], "recorded"
            return [Ran(n, None if v == "local" else v, s) for n, v, s in _MD.findall(line)], "recorded"
    labels = _LABEL.findall(text)
    return (_derived(labels), "derived") if labels else None


def current() -> dict[str, str]:
    """The fingerprint of every agent as this commit's code defines it. Builds the definitions with
    a credential object that is never used, so it needs no Azure (as tests/test_foundry_agents.py)."""
    from azure.identity import DefaultAzureCredential

    from ninety.agents import foundry

    agents = foundry.build_agents(foundry.chat_client(DefaultAzureCredential()))
    return {foundry.foundry_name(a): foundry.fingerprint(foundry.definition(a)) for a in agents}


def files(root: Path = ROOT) -> list[Path]:
    return sorted({p for pattern in SCANNED for p in root.glob(pattern) if p.is_file()})


def survey(root: Path = ROOT, now: dict[str, str] | None = None) -> list[Evidence]:
    """Every evidence file under `root`, with what it ran and which of those changed since."""
    now = current() if now is None else now
    out = []
    for path in files(root):
        found = read(path, root)
        if found is None:
            continue
        ran, source = found
        ev = Evidence(str(path.relative_to(root)), ran, source)
        for r in ran:
            if r.sha is None:
                ev.unknown.append(r)
            elif now.get(r.name) != r.sha:
                ev.stale.append(r)
        out.append(ev)
    return out


def problems(evidence: list[Evidence], stale: dict[str, dict[str, str]] = STALE) -> list[str]:
    """What fails CI: stale or unknown evidence not listed in `stale`, a listed file that is not
    stale (or no longer exists), a listing with no reason or no re-run, and a nightly archive that
    does not record its own fingerprints."""
    out = []
    seen = {e.path: e for e in evidence}
    for e in evidence:
        if e.path.startswith(NIGHTLY + "/"):
            if e.source != "recorded" and not e.source.startswith("data of "):
                out.append(f"{e.path}: a nightly report must record its agent definitions ({e.source})")
            elif e.unknown or any(r.sha is None for r in e.ran):
                out.append(f"{e.path}: a nightly report recorded no fingerprint for {_names(e.unknown)}")
            continue
        if not e.fresh and e.path not in stale:
            what = "; ".join(
                filter(
                    None,
                    [
                        e.stale and f"changed since it ran: {_names(e.stale)}",
                        e.unknown and f"no known fingerprint: {_names(e.unknown)}",
                    ],
                )
            )
            out.append(f"{e.path}: {what}. Re-run it, or list it in evidence.STALE with why and the re-run")
    for path, entry in stale.items():
        if path not in seen:
            out.append(
                f"evidence.STALE lists {path}, which is not agent evidence (missing, or names no agent)"
            )
        elif seen[path].fresh:
            out.append(f"evidence.STALE lists {path}, which is fresh now: remove it from the list")
        if not entry.get("why") or not entry.get("rerun"):
            out.append(f"evidence.STALE lists {path} without both a reason and the run that fixes it")
    return out


def _names(rs: list[Ran]) -> str:
    return ", ".join(f"{r.name}:{r.version or 'local'}" + (f" ({r.sha})" if r.sha else "") for r in rs)


def main() -> None:
    now = current()
    evidence = survey(now=now)
    for e in evidence:
        state = "fresh" if e.fresh else ("STALE, listed" if e.path in STALE else "STALE")
        print(f"{e.path}: {state} [{e.source}] {_names(e.ran) or 'no published agent'}")
    if errs := problems(evidence):
        sys.exit("\n".join(errs))


if __name__ == "__main__":
    main()
