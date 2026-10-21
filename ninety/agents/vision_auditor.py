"""The Vision Auditor: reads where the detector fails on training-side clips, clusters the failures,
and hands the Data agent typed render requests. The loop of targeted synthetic data as a handoff:

    detector errors (code) -> Vision Auditor -> clusters.json -> Data agent -> render queue

    uv run python -m ninety.agents.vision_auditor docs/eval/round1/audit.json --round round1 \
        --budget 80 --first-seed 7101 --out runs/round1          # offline: code-written rationale
    ... --replay replays/vision-auditor-round1.json              # the model's recorded answers
    ... --record replays/vision-auditor-round1.json              # call the model, save its answers

Input: `audit.json` from ninety.vision.failure_clusters, which matched every label with the
scorer's own rule and put it in one situation from the ground truth's geometry. Every number the
Auditor uses comes from that file; the Auditor computes nothing about pixels.

What is code and what is the model:
- Code refuses an audit that names a seed outside the training split (the fixed test set's
  per-frame results never choose what is rendered), builds one cluster per class and situation with
  mostly hidden misses (as failure_clusters.handoff), maps it to render settings
  (failure_clusters.RENDER), and splits the budget with the Data agent's own rule
  (data_agent.allocate), so the clip counts here are the ones the Data agent will plan.
- The model only explains and prioritises: a one-line rationale per cluster and an order. Every
  number in a rationale must be one of that cluster's own numbers, and the order must name every
  cluster exactly once; otherwise the code-written rationale and the code's order stand. The order
  moves the list and breaks the allocator's ties; it never changes a miss count.

Writes `clusters.json` (schemas/failure_clusters.schema.json), the Data agent's plan
(`requests.json`, nothing enqueued), and `trace.jsonl` (schemas/agent_trace.schema.json).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from ninety.agents import data_agent
from ninety.agents.contracts import TraceStep, schema_validator
from ninety.agents.factcheck import NUMBER_PATTERN, spelled_as_digits
from ninety.agents.replay import Replayer, Turn, WorkflowRecording
from ninety.eval.vision_score import CLASSES, VISIBILITY_GROUPS
from ninety.render.params import KIT_CONTRAST
from ninety.render.splits import split_of
from ninety.vision.failure_clusters import RENDER, SITUATIONS, summarize

Ask = Callable[[str], Awaitable[str]]

ROLE = "vision_auditor"
WORKFLOW = "vision-auditor"
GROUP = "mostly hidden"  # the weakness vision-report-v2 names (finding 4); the round targets it
RATIONALE_MAX_CHARS = 200
# A rationale may hold no ids, so every digit run is a number, wherever it sits ("38of95" is two),
# with thousands commas and a sign. Number words are read by the fact-checker's own reader
# (factcheck.spelled_as_digits, lesson 69), and words for a share or a multiple, which name a
# number without its digits, are refused outright (lesson 129).
DIGITS = re.compile(rf"(?:(?<![\w.])-)?(?:\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?|{NUMBER_PATTERN})")
SHARE_WORDS = re.compile(
    r"\b(?:half|halves|halved|thirds?|quarters?|twice|double[sd]?|triple[sd]?|treble[sd]?|dozens?"
    r"|percent|per\s+cent|percentage)\b|%",
    re.I,
)

INSTRUCTIONS = (
    "You are the Vision Auditor. Below are failure clusters of a football object detector, each "
    "with numbers computed by code. For each cluster write one sentence (at most "
    f"{RATIONALE_MAX_CHARS} characters) saying why it deserves new training footage, using only "
    "the numbers given for that cluster. Then order the clusters from most to least urgent. "
    'Answer JSON only: {"order": [cluster ids], "rationales": {"<id>": "<sentence>"}}.'
)


# ---------------------------------------------------------------------------------------------
# Input: the audit, checked
# ---------------------------------------------------------------------------------------------


def check_audit(audit: dict) -> dict:
    """Refuse an audit that is not training-side, or whose rows are not the scorer's groups."""
    seeds = audit.get("seeds")
    if not isinstance(seeds, list) or not seeds:
        raise ValueError("audit must list the seeds it was measured on")
    if not all(isinstance(s, int) and not isinstance(s, bool) for s in seeds):
        raise ValueError("audit seeds must be whole numbers")
    if len(set(seeds)) != len(seeds):
        raise ValueError("audit names a seed twice")
    if len(seeds) != audit.get("clips"):
        raise ValueError(f"audit names {len(seeds)} seeds for {audit.get('clips')} clips")
    wrong = [s for s in seeds if split_of(s) != "train"]
    if wrong:
        raise ValueError(f"seeds {wrong} are not training seeds; the Auditor never reads the test set")
    threshold = audit.get("threshold")
    if not (isinstance(threshold, (int, float)) and math.isfinite(threshold)):
        raise ValueError(f"audit threshold must be a finite number, got {threshold!r}")
    for row in audit["rows"]:
        if (
            row["cls"] not in CLASSES
            or row["visibility"] not in VISIBILITY_GROUPS
            or row["situation"] not in SITUATIONS
            or row["kit_contrast"] not in KIT_CONTRAST
        ):
            raise ValueError(f"audit row outside the scorer's groups: {row}")
        if not (isinstance(row["labels"], int) and isinstance(row["missed"], int)
                and 0 <= row["missed"] <= row["labels"]):
            raise ValueError(f"audit row counts must be 0 <= missed <= labels: {row}")
    return audit


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------------------------
# Clusters (code)
# ---------------------------------------------------------------------------------------------


def _id(cls: str, situation: str) -> str:
    return f"{cls}-" + re.sub(r"[^a-z]+", "-", situation.lower()).strip("-")


def clusters(audit: dict) -> tuple[list[dict], list[dict]]:
    """One cluster per class and situation with mostly hidden misses, most misses first (balls
    before players), as failure_clusters.handoff orders them; unrenderable ones apart."""
    mapped, unmapped = [], []
    for cls in ("ball", "player"):
        for r in summarize(audit["rows"], cls, GROUP):
            if not r["missed"]:
                continue
            c = {
                "id": _id(cls, r["situation"]),
                "name": f"{cls} {GROUP}, {r['situation']}",
                "cls": cls,
                "visibility": GROUP,
                "situation": r["situation"],
                "labels": r["labels"],
                "misses": r["missed"],
                "recall": r["recall"],
                "missed_low_contrast": r["missed_low_contrast"],
            }
            render = RENDER[r["situation"]]
            if render is None:
                unmapped.append(c)
            else:
                mapped.append({**c, "render": dict(render)})
    return mapped, unmapped


def facts(cluster: dict) -> set[float]:
    """The numbers a rationale may use: the cluster's own, as written in clusters.json."""
    values = {cluster[k] for k in ("labels", "misses", "recall", "missed_low_contrast")}
    if "clips" in cluster:
        values.add(cluster["clips"])
    if cluster.get("seeds"):
        values.update(cluster["seeds"])
    values.add(cluster["labels"] - cluster["misses"])  # the found labels: labels minus misses
    return {float(v) for v in values}


def template(cluster: dict) -> str:
    """The code-written rationale: what airs when there is no model, or the model's fails."""
    return (
        f"{cluster['misses']} of {cluster['labels']} {cluster['cls']} labels missed "
        f"{cluster['situation']}, recall {cluster['recall']}."
    )


def check_rationale(text: object, cluster: dict) -> str | None:
    """Why a model's rationale is refused, or None when it may stand."""
    if not isinstance(text, str) or not text.strip():
        return "empty"
    if len(text) > RATIONALE_MAX_CHARS:
        return f"longer than {RATIONALE_MAX_CHARS} characters"
    if any(ord(c) < 32 for c in text):
        return "control characters"
    allowed = facts(cluster)
    if share := SHARE_WORDS.search(text):
        return f"a share or multiple in words: {share.group()}"
    read = DIGITS.findall(spelled_as_digits(text))
    invented = [n for n in read if float(n.replace(",", "")) not in allowed]
    if invented:
        return f"numbers not in the cluster: {', '.join(invented)}"
    return None


# ---------------------------------------------------------------------------------------------
# The model: explain and prioritise, checked
# ---------------------------------------------------------------------------------------------


def prompt(drafts: list[dict]) -> str:
    keys = ("id", "name", "labels", "misses", "recall", "missed_low_contrast", "clips", "seeds")
    rows = [{k: c[k] for k in keys if k in c} for c in drafts]
    return INSTRUCTIONS + "\n\n" + json.dumps(rows, sort_keys=True)


def read_reply(reply: str, drafts: list[dict]) -> tuple[list[str] | None, dict[str, str], list[str]]:
    """The model's order (None if refused), its accepted rationales, and every refusal."""
    refusals = []
    try:
        data = json.loads(reply)
        if not isinstance(data, dict):
            raise ValueError
    except ValueError:
        return None, {}, ["reply is not a JSON object"]
    ids = [c["id"] for c in drafts]
    order = data.get("order")
    if not (isinstance(order, list) and sorted(map(str, order)) == sorted(ids)):
        refusals.append("order must name every cluster exactly once")
        order = None
    texts = data.get("rationales") if isinstance(data.get("rationales"), dict) else {}
    accepted = {}
    by_id = {c["id"]: c for c in drafts}
    for cid in ids:
        reason = check_rationale(texts.get(cid), by_id[cid])
        if reason:
            refusals.append(f"{cid}: {reason}")
        else:
            accepted[cid] = texts[cid]
    unknown = sorted(set(texts) - set(ids))
    if unknown:
        refusals.append(f"rationales for unknown clusters: {', '.join(unknown)}")
    return order, accepted, refusals


def allocate(mapped: list[dict], budget: int, first_seed: int) -> list[dict]:
    """Clips and seeds per cluster, by the Data agent's own rule, in list order."""
    out, seed = [], first_seed
    for c, n in zip(mapped, data_agent.allocate(mapped, budget), strict=True):
        out.append({**c, "clips": n, "seeds": [seed, seed + n - 1] if n else None})
        seed += n
    return out


# ---------------------------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------------------------


class Trace:
    def __init__(self, moment: str):
        self.moment, self.steps, self._t = moment, [], time.perf_counter()

    def add(self, role: str, action: str, detail: str) -> None:
        now = time.perf_counter()
        self.steps.append(TraceStep(role, self.moment, action, round((now - self._t) * 1000, 1), detail))
        self._t = now


async def audit_round(
    audit: dict,
    run: str,
    budget: int,
    first_seed: int,
    ask: Ask | None = None,
    source: dict | None = None,
) -> tuple[dict, list[TraceStep]]:
    """clusters.json and the trace. Without `ask` the rationale is the code's and so is the order."""
    trace = Trace(run)
    check_audit(audit)
    trace.add(ROLE, "read", f"{len(audit['rows'])} rows from {audit['clips']} training clips")
    mapped, unmapped = clusters(audit)
    trace.add(ROLE, "cluster", f"{len(mapped)} clusters with a render setting, {len(unmapped)} unmapped")
    drafts = allocate(mapped, budget, first_seed)
    written: dict[str, str] = {}  # cluster id -> the model's rationale that stands
    if ask is not None and drafts:
        order, accepted, refusals = read_reply(await ask(prompt(drafts)), drafts)
        if order:
            by_id = {c["id"]: c for c in mapped}
            mapped = [by_id[i] for i in order]
            drafts = allocate(mapped, budget, first_seed)
        # The order can move a tie's clip, so each rationale is checked again on the final numbers.
        final = {c["id"]: c for c in drafts}
        for cid, text in accepted.items():
            if reason := check_rationale(text, final[cid]):
                refusals.append(f"{cid}: {reason} after the order")
            else:
                written[cid] = text
        detail = f"{len(written)} of {len(drafts)} rationales and {'the' if order else 'no'} order accepted"
        trace.add(ROLE, "reject" if refusals else "explain", "; ".join([detail, *refusals]))
    else:
        trace.add(ROLE, "explain", "code-written rationale, no model")

    def explained(c: dict) -> dict:
        if c["id"] in written:
            return {**c, "rationale": written[c["id"]], "explained_by": "model"}
        return {**c, "rationale": template(c), "explained_by": "code"}

    result = {
        "round": run,
        "source": {**(source or {}), "seeds": sorted(audit["seeds"]), "threshold": audit["threshold"],
                   "group": GROUP},
        "budget": budget,
        "first_seed": first_seed,
        "clusters": [explained(c) for c in drafts],
        "unmapped": [explained(c) for c in unmapped],
    }
    schema_validator("failure_clusters").validate(result)
    clips = sum(c["clips"] for c in drafts)
    trace.add(ROLE, "handoff", f"{clips} clips over {len(drafts)} clusters to the Data agent")
    return result, trace.steps


def untyped(result: dict) -> dict:
    """clusters.json on the fields `failure_clusters --out` wrote before the Auditor (round, then
    name, misses and render), in its key order: what round 2's pre-registration (#158) fixed."""
    return {
        "round": result["round"],
        "clusters": [{"name": c["name"], "misses": c["misses"], "render": c["render"]}
                     for c in result["clusters"]],
        "unmapped": [{"name": c["name"], "misses": c["misses"]} for c in result["unmapped"]],
    }


def handoff(result: dict, commit: str, trace: list[TraceStep]) -> dict:
    """The Data agent's plan from the Auditor's clusters; nothing is enqueued here."""
    t = time.perf_counter()
    p = data_agent.plan(result, result["budget"], result["first_seed"], commit)
    trace.append(TraceStep(
        "data_agent", result["round"], "plan",
        round((time.perf_counter() - t) * 1000, 1), f"{len(p['requests'])} render requests, not enqueued",
    ))
    return p


def write(out: Path, result: dict, plan: dict, trace: list[TraceStep]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "clusters.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    (out / "requests.json").write_text(json.dumps(plan, indent=2, allow_nan=False) + "\n")
    validator = schema_validator("agent_trace")
    rows = [asdict(s) for s in trace]
    for row in rows:
        validator.validate(row)
    (out / "trace.jsonl").write_text("".join(json.dumps(r, allow_nan=False) + "\n" for r in rows))


def _live_ask() -> Ask:  # pragma: no cover - needs Azure
    from agent_framework import Agent

    from ninety.agents.foundry import chat_client

    agent = Agent(client=chat_client(), name="vision-auditor", instructions=INSTRUCTIONS)

    async def ask(text: str) -> str:
        return (await agent.run(text)).text

    return ask


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Failure clusters to the Data agent: the Vision Auditor.")
    ap.add_argument("audit", type=Path, help="audit.json from ninety.vision.failure_clusters")
    ap.add_argument("--round", required=True)
    ap.add_argument("--budget", type=int, required=True)
    ap.add_argument("--first-seed", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True, help="for clusters.json, requests.json, trace.jsonl")
    ap.add_argument("--commit", help="engine commit to render with (default: HEAD, which must be pushed)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--replay", type=Path, help="answer the model call from this recording")
    mode.add_argument("--record", type=Path, help="call the model on Foundry and save its answer here")
    a = ap.parse_args(argv)
    audit = json.loads(a.audit.read_text())
    source = {"audit": str(a.audit), "audit_sha256": digest(a.audit)}
    source.update({k: audit[k] for k in ("checkpoint", "detections") if k in audit})
    ask, turns = None, []
    if a.replay:
        recording = WorkflowRecording.load(a.replay)
        replayer = Replayer(recording.turns)
        ask = replayer.ask(ROLE)
    elif a.record:  # pragma: no cover - needs Azure
        live = _live_ask()

        async def ask(text: str) -> str:
            reply = await live(text)
            turns.append(Turn(ROLE, text, reply))
            return reply

    result, trace = asyncio.run(audit_round(audit, a.round, a.budget, a.first_seed, ask, source))
    if a.record:  # pragma: no cover - needs Azure
        WorkflowRecording(
            WORKFLOW, data_agent.pushed_head(), {}, {"audit_sha256": source["audit_sha256"],
                                                      "budget": a.budget, "first_seed": a.first_seed},
            datetime.now(UTC).isoformat(timespec="seconds"), turns,
        ).save(a.record)
    plan = handoff(result, a.commit or data_agent.pushed_head(), trace)
    write(a.out, result, plan, trace)
    for c in result["clusters"]:
        print(f"{c['clips']:4d} clips  {c['name']}  [{data_agent.render_set(c['render'])}]  {c['rationale']}")
    for c in result["unmapped"]:
        print(f"   - unmapped  {c['name']}  {c['rationale']}")
    print(f"{len(plan['requests'])} requests written to {a.out}")


if __name__ == "__main__":
    main()
