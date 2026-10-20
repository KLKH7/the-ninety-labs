"""The failure table (docs/eval/failure-table.md): each injected failure in the multi-agent workflow,
and what must recover. Expected values are written here, not read from the table (lesson 8)."""

from __future__ import annotations

import pytest

from ninety.eval import workflow_failures as wf

ROWS = {r["scenario"]: r for r in wf.rows()}
BASE = ROWS["none"]

# scenario -> (claim status, verdict category, Judge calls, an insight airs, template graphics lost)
EXPECTED = {
    # The insight, then its variants re-checked (casual and club in English pass; the Spanish ones
    # are held, since the stand-in Personalizer returns English): three Judge calls.
    "none": ("verified", None, 3, True, 0),
    # The real Judge wrapper retries once, then holds: two calls, then the template stays.
    "judge timeout": ("held", "timeout", 2, False, 0),
    # The Tactician never answers, so there is nothing for the Judge to read.
    "tactician outage": ("held", "service", 0, False, 0),
    # The insight still airs; the in-process fallback gives the variants, re-checked the same way.
    "personalizer down": ("verified", None, 3, True, 0),
    # The confidence gate holds the claim before the Judge, and the unsure pass's two graphics
    # (analyst and casual) are not drawn.
    "low confidence": ("held", "low_confidence", 0, False, 2),
}


def test_every_scenario_has_an_expectation():
    assert list(ROWS) == list(EXPECTED)


@pytest.mark.parametrize("name", list(EXPECTED))
def test_failure_row(name):
    status, category, asked, insight, lost = EXPECTED[name]
    row = ROWS[name]
    assert row["status"] == status and row["category"] == category
    assert row["judge_asked"] == asked
    assert bool(row["insights"]) is insight
    assert all(i["verified"] for i in row["insights"])
    assert set(row["templates"]) <= set(BASE["templates"])
    assert len(BASE["templates"]) - len(row["templates"]) == lost
    if lost:  # only the unsure detection's graphics are gone
        assert all(f"-{wf.SIDE}-" in i for i in set(BASE["templates"]) - set(row["templates"]))
    if row["status"] == "held":
        assert any("stays" in step for step in row["fallback"])  # the trace says the template stayed


def test_with_the_personalizer_down_the_fallback_answers_and_the_viewer_sees_the_same():
    row = ROWS["personalizer down"]
    assert "personalizer fallback: fallback: refused" in row["fallback"]  # the real client's route
    assert not any(step.startswith("personalizer") for step in BASE["fallback"])  # in process, no failure
    assert row["insights"] == BASE["insights"]


# scenario -> the fallback badges on screen
BADGES = {
    "none": [],
    "judge timeout": ["held: timeout"],
    "tactician outage": ["held: service"],
    "personalizer down": ["personalizer: refused"],
    "low confidence": ["held: low_confidence"],
}


# scenario -> the trace steps marked as fallbacks, which the agent trace shows
TRACE_FALLBACKS = {
    "none": [],
    "judge timeout": ["producer: held: timeout"],
    "tactician outage": ["tactician: template", "producer: held: service"],
    "personalizer down": ["personalizer: personalizer: refused"],
    "low confidence": ["producer: held: low_confidence"],
}


@pytest.mark.parametrize("name", list(BADGES))
def test_a_failure_puts_a_fallback_badge_on_screen_and_in_the_trace(name):
    assert ROWS[name]["badges"] == BADGES[name]
    assert ROWS[name]["trace_fallbacks"] == TRACE_FALLBACKS[name]


def test_every_injected_failure_recovers():
    assert [r["scenario"] for r in ROWS.values() if not r["recovers"]] == []


def test_the_recovery_check_can_fail():
    # A row that aired an unchecked claim, dropped a template and recorded no fallback is caught on
    # each count: the table's "yes" is a measurement, not a constant.
    broken = {**ROWS["tactician outage"], "insights": [{"text": "x", "verified": False}],
              "templates": BASE["templates"][1:], "fallback": [], "status": "verified"}
    assert wf.recovered({**broken, "badges": []}, BASE) == {
        "templates stay": False, "nothing unverified airs": False,
        "claim ends as it must": False, "fallback recorded": False, "fallback badge on screen": False,
    }


def test_the_committed_table_is_up_to_date():
    stale = [p.name for p, text in wf.render().items() if not p.exists() or p.read_text() != text]
    assert stale == [], f"run {wf.COMMAND}"


# --- the Personalizer node itself (ninety/agents/workflow.py, Personalizer) -----------------------


def minute(personalize: bool, **override):
    import asyncio

    from ninety.agents import workflow
    from ninety.match import detected
    from ninety.match.facts import compact

    scenario = wf.SCENARIOS[0]
    events = wf.events_for(scenario)
    known = {e["id"]: compact(e) for e in workflow.agent_events(events)}
    models, _ = wf.models_for(scenario, known)
    if override:
        from dataclasses import replace

        models = replace(models, **override)
    run = workflow.run_workflow(models, events, wf.MINUTE, detected.M1_CLIP, personalize=personalize)
    return asyncio.run(run)


def test_the_personalizer_is_off_unless_asked():
    result = minute(False)
    assert not [s for s in result.trace if s.role == "personalizer"]
    assert [c["persona"] for c in result.cues if c["kind"] == "insight"] == ["analyst"]


def test_a_personalizer_that_raises_leaves_the_insight_on_air():
    async def broken(claim, evidence, profiles):
        raise RuntimeError("injected: a defect in the Personalizer")

    result = minute(True, personalizer=broken)
    assert [s.action for s in result.trace if s.role == "personalizer"] == ["error"]
    assert [c["persona"] for c in result.cues if c["kind"] == "insight"] == ["analyst"]
    assert result.reviews[0].status == "verified"


def test_every_variant_is_fact_checked_before_it_airs():
    async def inflating(claim, evidence, profiles):
        from ninety.agents.contracts import Variant

        # Every persona gets a number the evidence does not hold.
        return [Variant(p.persona, p.lang, claim.text.replace("42 km/h", "99 km/h"), tuple(claim.evidence))
                for p in profiles]

    result = minute(True, personalizer=inflating)
    assert [c["persona"] for c in result.cues if c["kind"] == "insight"] == ["analyst"]
    refused = [s for s in result.trace if s.role == "fact_checker" and "99" in s.detail]
    assert refused  # each inflated variant was refused, and none aired


def test_the_live_cli_personalizes_in_process_when_no_service_is_set(monkeypatch, tmp_path, capsys):
    from tests.test_workflow import GOOD_RUN, SUPPORTED, cli, detected_file, live

    monkeypatch.delenv("NINETY_PERSONALIZER_URL", raising=False)
    live(monkeypatch, {**GOOD_RUN, "judge": [SUPPORTED] * 6})
    cues = tmp_path / "cues.jsonl"
    cli(monkeypatch, "--events", detected_file(tmp_path), "--personalize", "--cues-out", cues)
    import json

    aired = [json.loads(line) for line in cues.read_text().splitlines()]
    personas = {c["persona"] for c in aired if c["kind"] == "insight"}
    assert {"analyst", "casual"} <= personas  # the insight, and a variant re-checked and aired
    assert "personalizer" in capsys.readouterr().out


def test_personalize_cannot_be_recorded_yet(monkeypatch, tmp_path):
    import pytest as pt

    from tests.test_workflow import cli

    with pt.raises(SystemExit):
        cli(monkeypatch, "--personalize", "--record", tmp_path / "r.json")


def test_the_live_run_injects_each_failure_around_the_published_agents(monkeypatch, tmp_path):
    # agents-live task=failures, with W1's fake Foundry in place of the published agents and a fake
    # sign-in: no Azure. Three grounds: the M1 clip, then the held-out seeds (here W1's built match).
    import json
    import sys

    from ninety.agents import credentials, workflow
    from ninety.match.facts import compact
    from tests.test_workflow import EVENTS, PASSES, SUPPORTED, Credential, FakeFoundry

    order: list[str] = []

    class Signed(Credential):
        async def get_token(self, *scopes, **kwargs):
            order.append("token")
            return await super().get_token(*scopes, **kwargs)

    def simulate(seed, minutes):
        order.append(f"simulate {seed}")
        return EVENTS

    monkeypatch.setattr(credentials, "new_credential", lambda: credentials.SignedIn(Signed(3600)))
    monkeypatch.setattr(workflow, "simulated_events", simulate)
    m1 = {wf.MAIN: {"team": "away", "distance_m": 8, "ball_speed_kmh": 42}}
    built = {e["id"]: compact(e) for e in EVENTS}
    seed = (PASSES[0]["id"], PASSES[1]["id"], built)
    # The live models each scenario still calls: the Analyst in 4, the Tactician in 3; the
    # Challenger in 4 on the M1 clip, 3 on a seed (the low-confidence row, M1 only, has its Analyst
    # and Tactician injected).
    replies = {"moment-analyst": [], "tactician": [], "challenger": [], "judge": [SUPPORTED] * 60}
    for (main, side, known), challenges in (((wf.MAIN, wf.SIDE, m1), 4), (seed, 3), (seed, 3)):
        replies["moment-analyst"] += [wf.picks(main, [main, side])] * 4
        replies["tactician"] += [wf.reply(wf.claim_on(main, known))] * 3
        replies["challenger"] += ['{"agree": true}'] * challenges
    monkeypatch.setattr(workflow, "FoundryAgent", FakeFoundry(replies))
    monkeypatch.setattr(sys, "argv", ["workflow_failures", "--live", "--out", str(tmp_path)])
    wf.main()
    body = json.loads((tmp_path / "failure-table-live.json").read_text())
    assert [g["match"] for g in body["grounds"]] == ["seed900001", "seed21", "seed33"]
    # Signed in once, first, before either held-out seed was simulated.
    assert order[:3] == ["token", "simulate 21", "simulate 33"] and order.count("token") == 1
    for ground in body["grounds"]:
        rows = {r["scenario"]: r for r in ground["rows"]}
        assert [n for n, r in rows.items() if not r["recovers"]] == [], ground["match"]
        assert rows["judge timeout"]["category"] == "timeout"
        assert rows["tactician outage"]["category"] == "service"
        if ground["match"] == "seed900001":
            assert rows["low confidence"]["category"] == "low_confidence"
        else:  # the seeds' events are simulator stand-ins, with no detection confidence to doubt
            assert "low confidence" not in rows
        assert "personalizer fallback: fallback: refused" in rows["personalizer down"]["fallback"]
    md = (tmp_path / "failure-table-live.md").read_text()
    assert md.count("# Failure table") == 3 and "live, seed33" in md