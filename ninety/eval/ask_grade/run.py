"""Run fan questions x paraphrases x match times through the Ask and grade each answer, offline.

    # the truth table, once (reads the answer key; grading only):
    uv run python -m ninety.eval.ask_grade.run truth --run ~/ninety-notes/demo-engine-v2/out/seed8324 \\
        --work runs/demo-8324-final-work --insights runs/demo-8324-final/final-work/insights.json \\
        --cache <scratch>/truth-8324.npz --out ninety/eval/ask_grade/truth-8324.json.gz
    # grade the code path (no model, no cost):
    uv run python -m ninety.eval.ask_grade.run grade --insights <insights.json[.gz]> --label main \\
        --out runs/ask-grade/main.jsonl
    # rebuild the insights from the package first (#424 computes possession into them):
    uv run python -m ninety.eval.ask_grade.run grade --rebuild-insights runs/demo-8324-final ...
    # the model path on a ~10% sample (costs money; NINETY_DEMO_PASSCODE must be set; stops at $1.50):
    uv run python -m ninety.eval.ask_grade.run grade --model ...

The answer key is read only by `truth`; `grade` reads the frozen truth table it wrote, so CI grades
without it. Nothing on the live path imports this package (tests/test_ask_grade.py).
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import gzip
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from ninety.eval.ask_grade import grade as G

HERE = Path(__file__).parent
TIMES = (600.0, 2030.0, 2700.0, 3600.0, 5100.0, 5400.0)  # 10', 33:50, 45', 60', 85', full time
TRUTH_TABLE = HERE / "truth-8324.json.gz"
SESSION = "ask-grade"
MODEL_SHARE = 0.10  # design: about one answer in ten goes through the model
SPEND_CAP_USD = 1.50  # the coordinator's cap for one model run
PASSCODE_ENV = "NINETY_DEMO_PASSCODE"


def load_insights(path: Path):
    from ninety.intel.match_insights import MatchInsights

    raw = path.read_bytes()
    if path.suffix == ".gz":
        raw = gzip.decompress(raw)
    return MatchInsights.from_dict(json.loads(raw))


def rebuild_insights(package: Path, out: Path) -> Path:
    """The insights rebuilt from a package's tracked frames, detected events and scorebug, by the
    checked-out code's own builder (ninety/intel/match_insights.main), in a child process so its
    memory is returned. Run it through ~/ninety-notes/heavy.sh."""
    work = package / "final-work"
    detected = work / "detected.sided.jsonl"
    if not detected.exists():
        detected = package / "detected.jsonl"
    cmd = [
        sys.executable,
        "-m",
        "ninety.intel.match_insights",
        str(package / "tracked.json"),
        str(detected),
        str(package / "clip.json"),
        "--clip",
        "seed8324-match",
        "--out",
        str(out),
        "--scorebug",
        str(package / "scorebug.jsonl"),
    ]
    if (package / "association.json").exists():
        cmd += ["--association", str(package / "association.json")]
    if (work / "identity_feed.jsonl").exists():
        cmd += ["--identity-feed", str(work / "identity_feed.jsonl")]
        vision = (
            package.parent / f"{package.name}-work" / "vision"
        )  # the segments' runs, as the package built
        if vision.exists():
            cmd += ["--broadcast-vision", str(vision)]
    subprocess.run(cmd, check=True)
    return out


def holds(insights, it: dict, t: float) -> bool | None:
    """Do the insights hold a fact this intent could be answered from, by time t?"""
    m = it["metric"]
    minute = G.now_minute(t)
    facts = insights.facts

    def any_fact(kind, pred=lambda f: True):
        return any((f.get("t") or 0) <= t and pred(f) for f in facts.get(kind, []))

    def row(key):
        rows = (
            {r["key"]: r for r in getattr(insights, "stats", {}).get("rows", [])}
            if isinstance(getattr(insights, "stats", None), dict)
            else {}
        )
        r = rows.get(key)
        return bool(r) and any(
            s.get("minute_to", 0) <= minute and (s.get("home") is not None or s.get("away") is not None)
            for s in r["series"]
        )

    if m is None or m == "unmeasured":
        return None
    if m in ("score", "leader", "goals", "goal_build_up_home"):
        return True  # the scorebug always reads a score; the goals are facts or "no goal yet"
    if m == "possession_home":
        return any_fact(
            "possession", lambda f: f.get("metric") == "possession_share" and f.get("confident")
        ) or row("possession")
    if m in ("territory", "territory_leader"):
        return any_fact("territory") or row("territory")
    if m in ("passes", "completion"):
        return any_fact("pass")
    if m in ("shots", "on_target"):
        return any_fact("shot")
    if m == "corners":
        return row("corner")
    if m == "out_of_play":
        return row("throw_in") or row("goal_kick")
    if m.startswith("involvement"):
        return any_fact("pass", lambda f: f.get("player"))
    if m in ("peak_speed", "distance"):
        return any_fact("running")
    return None


def questions(intents: list[dict]) -> list[tuple[dict, dict]]:
    return [(it, q) for it in intents for q in it["questions"]]


def sampled(it: dict, q: str, t: float) -> bool:
    h = hashlib.sha256(f"{it['id']}|{q}|{t:g}".encode()).digest()
    return h[0] < 256 * MODEL_SHARE


def ask_code(insights, q: str, t: float) -> dict:
    from ninety.agents import companion_match as cm
    from ninety.agents.contracts import Question

    t0 = time.perf_counter()
    try:
        a, calls = cm.code_match_answer(Question(SESSION, None, q, float(t)), insights, suggest=False)
        rec = {
            "status": a.status,
            "text": a.text,
            "t_to": a.t_to,
            "metric": a.metric,
            "value": a.value,
            "tools": [c.get("name") for c in calls],
            "source": "code",
        }
    except Exception as exc:  # noqa: BLE001  a crash is graded as no answer, and kept
        rec = {
            "status": "error",
            "text": "",
            "t_to": None,
            "error": repr(exc)[:300],
            "tools": [],
            "source": "code",
        }
    rec["latency_s"] = round(time.perf_counter() - t0, 3)
    return rec


def run(
    insights, intents: list[dict], table: dict, tol: dict, clubs: dict, times=TIMES, answer=None
) -> list[dict]:
    """Every question at every time, graded. `answer(it, q, t)` overrides the code path."""
    roster = table["_roster"]
    out = []
    for t in times:
        for it, qd in questions(intents):
            q = qd["q"]
            w = G.window_of(it, q, t)
            ans = answer(it, q, t) if answer else ask_code(insights, q, t)
            tv = table.get(G.wkey(it, t, w))
            g = G.grade(it, q, t, ans, tv, tol, clubs, roster, holds(insights, it, t))
            out.append(
                {
                    "intent": it["id"],
                    "q": q,
                    "chip": qd.get("chip"),
                    "t": t,
                    "window": list(w),
                    "clubs_asked": G.clubs_in(q, clubs),
                    **ans,
                    **g,
                }
            )
    consistency(out)
    for r in out:
        r["pass"] = G.passed(r["checks"])
    return out


def consistency(rows: list[dict]) -> None:
    """The same headline across an intent's paraphrases at one time, same window and same club
    asked about; the modal headline is the reference. A group of one does not apply."""
    groups = collections.defaultdict(list)
    for r in rows:
        groups[(r["intent"], r["t"], tuple(r["window"]), tuple(sorted(r["clubs_asked"])))].append(r)
    for g in groups.values():
        heads = [G.headline(r.get("text") or "") for r in g]
        modal = collections.Counter(heads).most_common(1)[0][0]
        for r, h in zip(g, heads, strict=True):
            r["checks"]["consistent"] = None if len(g) < 2 else h == modal


def summarise(rows: list[dict]) -> dict:
    """Pass rates per intent and per check, and overall."""
    checks = (
        "answered",
        "relevant",
        "correct",
        "consistent",
        "coverage_honest",
        "no_future",
        "no_false_unknown",
        "natural",
    )
    per: dict[str, dict] = {}
    for iid in dict.fromkeys(r["intent"] for r in rows):
        rs = [r for r in rows if r["intent"] == iid]
        d = {"n": len(rs), "pass": round(sum(r["pass"] for r in rs) / len(rs), 3)}
        for c in checks:
            app = [r["checks"][c] for r in rs if r["checks"].get(c) is not None]
            d[c] = round(sum(app) / len(app), 3) if app else None
        per[iid] = d
    chips = [r for r in rows if r.get("chip")]
    return {
        "n": len(rows),
        "pass": round(sum(r["pass"] for r in rows) / len(rows), 3),
        "chips": {
            "n": len(chips),
            "pass": round(sum(r["pass"] for r in chips) / len(chips), 3) if chips else None,
            "answered": round(sum(r["checks"]["answered"] for r in chips) / len(chips), 3) if chips else None,
        },
        "intents": per,
    }


# ---- the model path (costs money) -----------------------------------------------------------------


def model_answerer(insights, log: list[dict]):
    """answer(it, q, t) through companion_match.answer_match with the Foundry agents, on the ~10%
    sample; code's answer elsewhere. Each call logs latency and an estimated cost; spending stops at
    SPEND_CAP_USD and the rest is answered by code."""
    if not os.environ.get(PASSCODE_ENV):
        raise SystemExit(f"--model needs {PASSCODE_ENV} set in the environment (it is never printed)")
    from ninety.eval.latency_cost import INPUT, OUTPUT, price, tokens

    spent = {"usd": 0.0}
    loop = asyncio.new_event_loop()
    state: dict = {}

    async def setup():
        import contextlib

        from ninety.agents import companion_match as cm
        from ninety.agents import credentials, foundry
        from ninety.agents.judge import judge as run_judge
        from ninety.agents.judge import judge_agent

        stack = contextlib.AsyncExitStack()
        credential = await stack.enter_async_context(credentials.new_credential())
        await credentials.sign_in(credential)
        client = foundry.chat_client(credential)
        match_ag, judge_ag = cm.companion_match_agent(client), judge_agent(client)
        usage = {"in": 0, "out": 0}

        async def ask(prompt):
            reply = (await match_ag.run(prompt)).text
            usage["in"] += tokens(prompt)
            usage["out"] += tokens(reply or "")
            return reply

        async def judge(claim, evidence):
            usage["in"] += tokens(json.dumps(evidence, default=str)) + tokens(claim.text)
            return await run_judge(judge_ag, claim, evidence)

        state.update(stack=stack, ask=ask, judge=judge, usage=usage)

    loop.run_until_complete(setup())

    def answer(it, q, t):
        if not sampled(it, q, t) or spent["usd"] >= SPEND_CAP_USD:
            return ask_code(insights, q, t)
        from ninety.agents import companion_match as cm
        from ninety.agents.contracts import Question

        state["usage"].update({"in": 0, "out": 0})
        t0 = time.perf_counter()
        try:
            r = loop.run_until_complete(
                cm.answer_match(
                    Question(SESSION, None, q, float(t)), insights, ask=state["ask"], judge=state["judge"]
                )
            )
            a = r.answer
            rec = {
                "status": a.status,
                "text": a.text,
                "t_to": a.t_to,
                "metric": a.metric,
                "value": a.value,
                "tools": [c.get("name") for c in r.tools],
                "source": r.source,
                "reasons": list(r.reasons),
            }
        except Exception as exc:  # noqa: BLE001
            rec = {
                "status": "error",
                "text": "",
                "t_to": None,
                "error": repr(exc)[:300],
                "tools": [],
                "source": "model",
            }
        u = state["usage"]
        usd = float(price(INPUT) * u["in"] + price(OUTPUT) * u["out"])
        spent["usd"] += usd
        rec.update(
            latency_s=round(time.perf_counter() - t0, 3),
            tokens_in=u["in"],
            tokens_out=u["out"],
            usd=round(usd, 6),
            model=True,
        )
        log.append({"intent": it["id"], "q": q, "t": t, "latency_s": rec["latency_s"], "usd": rec["usd"]})
        return rec

    def close():
        loop.run_until_complete(state["stack"].aclose())
        loop.close()

    answer.close = close
    answer.spent = spent
    return answer


# ---- CLI ---------------------------------------------------------------------------------------


def cmd_truth(args) -> None:
    from ninety.eval.ask_grade import truth as T

    insights = load_insights(args.insights)
    tr = T.load(args.run, args.work, args.cache, insights.fixture)
    intents, _ = G.load_intents()
    tab = T.table(tr, [it for it in intents if it["kind"] != "chip"], list(TIMES), G.windows)
    tab["_roster"] = [[v["name"], v["team"]] for v in tr.names.values()]
    T.save(tab, args.out)
    print(f"{args.out}: {len(tab) - 1} truth values")


def cmd_grade(args) -> None:
    from ninety.eval.ask_grade import truth as T

    if args.rebuild_insights:
        args.insights = rebuild_insights(args.rebuild_insights, args.out.with_suffix(".insights.json"))
    insights = load_insights(args.insights)
    intents, clubs = G.load_intents()
    table = T.read(args.truth_table)
    tol = G.load_tolerances()
    log: list[dict] = []
    answer = model_answerer(insights, log) if args.model else None
    try:
        rows = run(insights, intents, table, tol, clubs, answer=answer)
    finally:
        if answer is not None:
            answer.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows))
    s = summarise(rows)
    s["label"] = args.label
    if args.model:
        lat = sorted(x["latency_s"] for x in log)
        s["model"] = {
            "answers": len(log),
            "usd": round(answer.spent["usd"], 4),
            "cap_usd": SPEND_CAP_USD,
            "latency_p50_s": lat[len(lat) // 2] if lat else None,
            "latency_max_s": lat[-1] if lat else None,
        }
    args.out.with_suffix(".summary.json").write_text(json.dumps(s, indent=1) + "\n")
    print(json.dumps({"label": args.label, "n": s["n"], "pass": s["pass"], "chips": s["chips"]}))
    for iid, d in s["intents"].items():
        print(
            f"{iid:14} pass {d['pass']:.2f}  "
            + "  ".join(
                f"{k[:7]} {'-' if d[k] is None else f'{d[k]:.2f}'}" for k in d if k not in ("n", "pass")
            )
        )


FIXTURE = HERE.parents[2] / "tests" / "fixtures" / "ask-grade-insights-8324.json.gz"
BASELINE = HERE / "baseline.json"
RATCHETED = ("pass", "correct")  # per intent: these rates may only go up (tests/test_ask_grade.py)


def ratchet_rates(insights_path: Path = FIXTURE) -> dict:
    """The ratcheted rates of the code path on the frozen fixture: overall and per intent."""
    from ninety.eval.ask_grade import truth as T

    intents, clubs = G.load_intents()
    rows = run(load_insights(insights_path), intents, T.read(TRUTH_TABLE), G.load_tolerances(), clubs)
    s = summarise(rows)
    return {
        "pass": s["pass"],
        "chips_answered": s["chips"]["answered"],
        "intents": {k: {c: v[c] for c in RATCHETED} for k, v in s["intents"].items()},
    }


def cmd_baseline(args) -> None:
    rates = ratchet_rates(args.insights)
    body = {
        "about": "The Ask's code path on tests/fixtures/ask-grade-insights-8324.json.gz, graded by "
        "ninety/eval/ask_grade. tests/test_ask_grade.py fails if any rate here goes down; raise it with "
        "`uv run python -m ninety.eval.ask_grade.run baseline` when a change raises it.",
        **rates,
    }
    BASELINE.write_text(json.dumps(body, indent=1) + "\n")
    print(f"{BASELINE}: pass {rates['pass']}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("truth", help="write the frozen truth table (reads the answer key)")
    t.add_argument(
        "--run", type=Path, required=True, help="the full simulated run (events.jsonl, frames.jsonl)"
    )
    t.add_argument("--work", type=Path, required=True, help="the footage's work folder (clips/*/meta.json)")
    t.add_argument(
        "--insights", type=Path, required=True, help="any insights of the match, for its team sheets"
    )
    t.add_argument("--cache", type=Path, required=True, help="the frame cache (.npz; built if missing)")
    t.add_argument("--out", type=Path, default=TRUTH_TABLE)
    g = sub.add_parser("grade", help="ask every question and grade the answers")
    g.add_argument("--insights", type=Path)
    g.add_argument(
        "--rebuild-insights",
        type=Path,
        default=None,
        metavar="PACKAGE",
        help="rebuild the insights from a package (tracked.json, detected, scorebug) first",
    )
    g.add_argument("--truth-table", type=Path, default=TRUTH_TABLE)
    g.add_argument("--label", default="run")
    g.add_argument("--out", type=Path, required=True)
    g.add_argument(
        "--model",
        action="store_true",
        help=f"answer ~{MODEL_SHARE:.0%} through the Foundry agents (costs money; {PASSCODE_ENV})",
    )
    b = sub.add_parser("baseline", help="write baseline.json from the frozen fixture (code path)")
    b.add_argument("--insights", type=Path, default=FIXTURE)
    args = ap.parse_args(argv)
    if args.cmd == "truth":
        cmd_truth(args)
    elif args.cmd == "baseline":
        cmd_baseline(args)
    else:
        if args.insights is None and args.rebuild_insights is None:
            ap.error("grade needs --insights or --rebuild-insights")
        cmd_grade(args)


if __name__ == "__main__":
    main()
