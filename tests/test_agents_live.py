"""The live agent evaluation's harness, offline: the plan's moment rules, its argument rules, the
scores read from a trace, and the call cap (docs/eval/agents-live-plan.md). No Azure."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from ninety.eval import agents_live as al

CLUBS = {"home": "London Athletic", "away": "Lisbon Esportes"}


def mi(goals=(), line_breaks=(), overloads=()):
    return SimpleNamespace(fixture=SimpleNamespace(clubs=CLUBS), facts={
        "goal": list(goals), "line_break": list(line_breaks), "overload": list(overloads)})


def ev(i, t, kind="pass"):
    return {"id": i, "t": t, "type": kind}


def test_moments_follow_the_plans_rules():
    goal = {"id": "goal:g1", "event": "g1", "minute": 10, "t": 570.0, "team": "away"}
    def lb(i, minute, value, confident, team):
        return {"id": f"lb:{i}", "minute": minute, "t": 60.0 * minute - 5, "value": value,
                "confident": confident, "team": team, "event": i}

    def ov(i, minute, duration, team):
        return {"id": f"ov:{i}", "minute": minute, "t": 60.0 * minute - 5, "value": 3, "duration_s": duration,
                "confident": True, "team": team}

    lbs = [lb("a", 10, 9, True, "home"), lb("b", 20, 9, False, "home"), lb("c", 30, 5, True, "home"),
           lb("d", 31, 5, True, "away")]
    ovs = [ov(1, 40, 2.0, "home"), ov(2, 41, 4.0, "away")]
    events = [ev("g1", 570.0, "goal"), *(ev(f"q{i}", 3000.0 + i) for i in range(5)),
              *(ev(f"r{i}", 2400.0 + i) for i in range(3)), ev("s", 2420.0, "shot"),
              *(ev(f"h{i}", 2640.0 + i) for i in range(4))]
    specs = {s.key: s for s in al.select(events, mi([goal], lbs, ovs))}
    assert specs["goal-1"].club == "Lisbon Esportes" and specs["goal-1"].anchor == "g1"
    # Not in the goal's minute, confident only, the highest value, then the earliest.
    assert specs["line-break"].target == "lb:c"
    assert specs["line-break"].question == "Which pass cut through Lisbon Esportes's lines just now?"
    # Ties on value go to the longer overload.
    assert specs["overload"].target == "ov:2" and specs["overload"].club == "Lisbon Esportes"
    # Minute 41 has a shot; 45 is within 2 of nothing loud but has 4 events; 51 has 5.
    assert specs["quiet"].minute == 45
    assert specs["half-time"].minute == 45


def test_quiet_needs_three_events_and_no_shot_near():
    events = [ev("a", 60.0), ev("b", 61.0), *(ev(f"c{i}", 600.0 + i) for i in range(4)),
              *(ev(f"d{i}", 1500.0 + i) for i in range(3)), ev("s", 1620.0, "shot")]
    (quiet,) = [s for s in al.select(events, mi()) if s.key == "quiet"]
    assert quiet.minute == 11  # minute 2 has two events; minute 26 is a minute before a shot


@pytest.mark.parametrize("call,ok", [
    ({"name": "goal_build_up", "club": None, "minute_from": 21, "minute_to": 22}, True),
    ({"name": "goal_build_up", "club": "lisbon esportes", "minute_from": 1, "minute_to": 22}, True),
    ({"name": "goal_build_up", "club": None, "minute_from": 1, "minute_to": 21}, False),
    ({"name": "goal_build_up", "club": "London Athletic", "minute_from": 1, "minute_to": 22}, False),
    (None, False),
])
def test_goal_argument_rule(call, ok):
    spec = al.Spec("goal-1", "goal", 22, 1300.0, "Lisbon Esportes", "London Athletic", "g", "goal:g",
                   "What led to that goal?", "goal_build_up", 1320.0)
    assert al.args_right(spec, call) is ok


def test_window_and_half_time_rules():
    lb = al.Spec("line-break", "line_break", 43, 2540.0, "Lisbon Esportes", "London Athletic", None, "lb:x",
                 "q", "line_breaks", 2560.0)
    assert al.args_right(lb, {"minute_from": 29, "minute_to": 43, "club": None})
    assert not al.args_right(lb, {"minute_from": 29, "minute_to": 42, "club": None})
    assert not al.args_right(lb, {"minute_from": 29, "minute_to": 43, "club": "London Athletic"})
    ht = al.Spec("half-time", "half_time", 45, 2670.0, None, None, None, None, "q", "possession", 2675.0)
    assert al.args_right(ht, {"minute_from": 1, "minute_to": 44})
    assert not al.args_right(ht, {"minute_from": 31, "minute_to": 45})


def write_trace(tmp_path, rows, spec):
    (tmp_path / "moments.json").write_text(json.dumps([spec]))
    (tmp_path / "trace.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def call(role, prompt, reply, run="graph", key="goal-1", **kw):
    return {"kind": "model_call", "key": key, "run": run, "role": role, "agent": f"{role}:1", "ms": 10.0,
            "tokens_in": 10, "tokens_out": 5, "tokens_reported": True, "usd": 0.0, "hosted_tool_calls": [],
            "prompt": prompt, "reply": reply, "error": None, **kw}


SPEC = {"key": "goal-1", "kind": "goal", "minute": 22, "t": 1300.0, "club": "Lisbon Esportes",
        "other": "London Athletic", "anchor": "g", "target": "goal:g", "question": "What led to that goal?",
        "tool": "goal_build_up", "ask_t": 1320.0}
VERIFIED = {"ok": True, "reasons": [], "category": None}


def review(evidence, text="Lisbon scored."):
    return {"kind": "review", "key": "goal-1", "run": "graph", "moment": "m-g", "status": "verified",
            "author": "tactician", "primary": VERIFIED, "alternative": None, "attempts": [["tactician", 1]],
            "drafted": None, "aired": {"text": text, "evidence": evidence}}


def graph_rows(aired_evidence):
    return [
        call("analyst", "...", '{"moments":[]}'),
        {"kind": "moment_picked", "key": "goal-1", "run": "graph", "moment": "m-g", "main_event": "g",
         "evidence": ["g", "p1"]},
        call("tactician", '{"moment":{"id":"m-g","evidence":[{"id":"g"},{"id":"p1"}]}}', "{}"),
        review(aired_evidence),
        {"kind": "graph_done", "key": "goal-1", "run": "graph", "minute": 22, "ms": 100.0, "pins": {},
         "model_failed": False, "model_calls": 3, "templates": 2, "insights": [],
         "minute_event_ids": ["g", "p1"]},
    ]


def companion_rows(plan_reply, given, cited, source="model"):
    return [
        call("companion", "plan", plan_reply, run="companion"),
        {"kind": "mcp_call", "key": "goal-1", "run": "companion", "tool": "goal_build_up", "args": {},
         "ms": 1.0,
         "result_bytes": 10, "facts": 1, "summary": 0, "fact_ids": list(given), "same_as_in_process": True},
        call("companion", json.dumps({"facts": [{"id": i} for i in given]}), "{}", run="companion"),
        {"kind": "companion_done", "key": "goal-1", "run": "companion", "question": "q", "ask_t": 1320.0,
         "ms": 50.0, "source": source, "status": "verified", "text": "t", "evidence": list(cited),
         "reasons": [],
         "tools_used": []},
        {"kind": "run_end", "calls": 5, "usd": 0.0},
    ]


PLAN_RIGHT = '{"tools":[{"name":"goal_build_up","club":null,"minute_from":21,"minute_to":22}]}'


def test_a_grounded_moment_scores_clean(tmp_path):
    rows = graph_rows(["g"]) + companion_rows(PLAN_RIGHT, ["goal:g", "lb:1"], ["goal:g"])
    write_trace(tmp_path, rows, SPEC)
    m = al.score(tmp_path)["moments"]["goal-1"]
    g = m["graph"]
    assert g["anchor_given"] and g["analyst_picked_anchor"] and g["tactician_context"]
    assert m["graph"]["grounded"] and m["graph"]["ends"]["verified"] == 1
    c = m["companion"]
    assert c["tool_right"] and c["args_right"] and c["target_given"] and c["grounded"]


def test_ungrounded_claims_and_wrong_plans_are_caught(tmp_path):
    wrong = '{"tools":[{"name":"shots","club":null,"minute_from":21,"minute_to":22}]}'
    write_trace(tmp_path, graph_rows(["x9"]) + companion_rows(wrong, ["shot:1"], ["goal:g"]), SPEC)
    m = al.score(tmp_path)["moments"]["goal-1"]
    assert m["graph"]["grounded"] is False  # x9 was never given to the writer
    c = m["companion"]
    assert c["tool_right"] is False and c["args_right"] is False
    assert c["target_given"] is False and c["grounded"] is False


def test_a_plan_never_returned_is_not_a_wrong_plan(tmp_path):
    rows = companion_rows(PLAN_RIGHT, [], ["goal:g"], source="code")
    rows[0] = {**rows[0], "reply": None, "error": "cancelled (caller's timeout)"}
    write_trace(tmp_path, rows, SPEC)
    t = al.score(tmp_path)["totals"]
    assert t["tool_choice"] == "0/0" and t["plans_not_returned"] == 1


def test_dropout_drill_flags_a_claim_on_a_dropped_event(tmp_path):
    rows = [{"kind": "drill_start", "key": "goal-2", "run": "drill:vision-dropout", "injected": "x",
             "dropped": ["g"]},
            {**review(["g"], "A goal!"), "key": "goal-2", "run": "drill:vision-dropout"}]
    write_trace(tmp_path, rows, SPEC)
    d = al.score(tmp_path)["drills"]["drill:vision-dropout"]
    assert d["aired_cites_dropped"] and d["aired_says_goal"]


def test_dropout_removes_the_minute_around_the_moment():
    kept, dropped = al.dropout([ev("a", 100.0), ev("b", 129.0), ev("c", 131.0)], 100.0)
    assert dropped == ["a", "b"] and [e["id"] for e in kept] == ["c"]


def test_observer_records_failures_and_stops_at_the_cap(tmp_path):
    trace = al.Trace(tmp_path / "t.jsonl", max_calls=1)

    class Down:
        async def run(self, prompt):
            raise ConnectionError("down")

    agent = al.Observed(trace, "judge", "ninety-judge", "4", Down())
    with pytest.raises(ConnectionError):
        asyncio.run(agent.run("p"))
    (row,) = [json.loads(line) for line in (tmp_path / "t.jsonl").read_text().splitlines()]
    assert row["error"] == "ConnectionError: down" and row["usd"] == 0.0
    with pytest.raises(al.OverBudget):
        asyncio.run(agent.run("p"))


def test_a_drill_that_never_hits_its_fault_is_not_exercised(tmp_path):
    start = {"kind": "drill_start", "key": "goal-1", "run": "drill:judge-down", "injected": "x"}
    held = {**review(["g"]), "run": "drill:judge-down", "status": "held", "aired": None}
    write_trace(tmp_path, [start, call("tactician", "p", "{}", run="drill:judge-down"), held], SPEC)
    assert al.score(tmp_path)["drills"]["drill:judge-down"]["exercised"] is False
    failed = call("judge", "p", None, run="drill:judge-down", error="ServiceRequestError: x")
    write_trace(tmp_path, [start, failed, held], SPEC)
    assert al.score(tmp_path)["drills"]["drill:judge-down"]["exercised"] is True
