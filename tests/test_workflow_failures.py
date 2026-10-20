"""The failure table (docs/eval/failure-table.md): each injected failure in the multi-agent workflow,
and what must recover. Expected values are written here, not read from the table (lesson 8)."""

from __future__ import annotations

import pytest

from ninety.eval import workflow_failures as wf
from ninety.match.facts import compact

ROWS = {r["scenario"]: r for r in wf.rows()}
BASE = ROWS["none"]
KNOWN = {e["id"]: compact(e) for e in wf.workflow.agent_events(list(wf.m1_ground().events))}

# scenario -> (claim status, verdict category, Judge calls, an insight airs, template graphics lost)
EXPECTED = {
    # The insight, then its five variants re-checked (casual and club in English; analyst, casual
    # and club in the stand-in's marked Spanish): six Judge calls.
    "none": ("verified", None, 6, True, 0),
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
    # The fallback is the verified English text: the English profiles see what they see without the
    # failure, and the Spanish ones are held rather than shown English.
    assert row["insights"] == [i for i in BASE["insights"] if i["lang"] == "en"]
    assert {i["lang"] for i in BASE["insights"]} == {"en", "es"}
    assert [v.split(":")[0] for v in row["variants_refused"]] == ["analyst/es", "casual/es", "club/es"]


def test_the_row_reads_the_minute_s_claim_whichever_moment_the_analyst_picked():
    # A live Analyst picks its own moments; the row's claim is the one that aired, else the first
    # moment's, never a lookup by the scripted main pass's id (live rows read "none" that way).
    from ninety.agents.contracts import Review
    from ninety.agents.factcheck import Claim, Verdict

    held = Review("m-e00051", Verdict(False, ["timeout"], "timeout"), None, None, "held")
    aired = Review("m-e00034", Verdict(True), None, Claim("h9 finds h6.", ["e00034"]), "verified")
    rejected = Review("m-e00040", Verdict(False, ["wrong number"], "numbers"), None, None, "rejected")
    assert wf.minute_claim([held, aired]) is aired
    assert wf.minute_claim([rejected, held]) is rejected
    assert wf.minute_claim([]) is None


def test_a_baseline_on_another_moment_than_the_main_pass_still_reads_its_claim():
    # The live baseline on M1 read "none" with a verified insight on screen: the Analyst had led
    # with another moment than the scripted main pass. Here it leads with the second pass.
    async def analyst(prompt: str) -> str:
        return wf.picks(wf.SIDE, [wf.SIDE, wf.MAIN])

    other = wf.Scenario("none", "nothing (the baseline)", claim="verified",
                        override=lambda agent: {"analyst": analyst})
    row = wf.run(other)
    assert row["insights"] and row["status"] == "verified"


def test_the_headline_says_when_the_baseline_fails():
    assert "**Baseline: passes. Recovered: 4 of 4**" in "\n".join(wf.table_lines(wf.rows()))
    english = baseline_with(personalizer_writing(lambda text: text.replace("complete", "completes")))
    table = wf.rows([english, *[r for r in wf.rows() if r["scenario"] != "none"]])
    assert "**Baseline: fails. Recovered: 4 of 4**" in "\n".join(wf.table_lines(table))


def test_every_moment_s_claim_must_end_as_the_failure_says():
    # A live minute has up to three moments: held means each held, verified means one aired and
    # none held. A rejected claim beside a verified one is the fact-checker working.
    assert not wf.ends_as_it_must(["held", "rejected"], "held")  # lesson 96: rejected is not held
    assert wf.ends_as_it_must(["held", "held", "held"], "held")
    assert not wf.ends_as_it_must([], "held")
    assert not wf.ends_as_it_must(["verified", "held"], "verified")
    assert wf.ends_as_it_must(["rejected", "verified"], "verified")
    assert not wf.ends_as_it_must(["rejected"], "verified")


def personalizer_writing(spanish):
    """A stand-in Personalizer: each persona keeps the claim's words; `spanish(text)` gives the
    Spanish profiles' text, or None to leave them out."""
    from ninety.agents.contracts import Variant

    async def personalize(claim, evidence, profiles):
        out = []
        for p in profiles:
            text = claim.text if p.lang == "en" else spanish(claim.text)
            if text is not None:
                out.append(Variant(p.persona, p.lang, text, tuple(claim.evidence)))
        return out

    return personalize


def baseline_with(personalize) -> dict:
    scenario = wf.Scenario("none", "nothing (the baseline)", claim="verified",
                           override=lambda agent: {"personalizer": personalize})
    return wf.run(scenario)


def test_the_baseline_fails_when_a_spanish_profile_reads_english_with_a_word_changed():
    # The byte-for-byte check alone let this air: English for a Spanish viewer, one word changed.
    row = baseline_with(personalizer_writing(lambda text: text.replace("complete", "completes")))
    assert row["variants_refused"] == [] and len(row["variants_english"]) == 3
    assert not wf.recovered(row, row)["every variant airs without a failure"]


def test_the_baseline_fails_when_the_spanish_profiles_are_left_out():
    row = baseline_with(personalizer_writing(lambda text: None))
    assert row["variants_refused"] == [] and row["variants_english"] == []
    assert sorted(row["variants_missing"]) == ["analyst/es", "casual/es", "club/es"]
    assert not wf.recovered(row, row)["every variant airs without a failure"]


def test_the_offline_spanish_is_spanish():
    assert {i["lang"] for i in BASE["insights"]} == {"en", "es"}
    assert BASE["variants_english"] == BASE["variants_missing"] == BASE["variants_refused"] == []
    spanish = [i["text"] for i in BASE["insights"] if i["lang"] == "es"]
    assert spanish and all(text == wf.claim_in_spanish(wf.MAIN, KNOWN) for text in spanish)


def test_the_baseline_fails_when_a_spanish_profile_gets_english():
    # The reviewer's ruling: without a failure, a Spanish profile held on the English text is a
    # defect (here, a Personalizer that writes no Spanish), so the baseline does not recover.
    from ninety.agents.contracts import Models

    english_only = wf.Scenario("none", "nothing (the baseline)", claim="verified",
                               override=lambda agent: {"personalizer": Models.scripted().personalizer})
    row = wf.run(english_only)
    assert row["variants_refused"] and not wf.recovered(row, row)["every variant airs without a failure"]
    assert all(wf.recovered(BASE, BASE).values())


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


def planted(name: str, column: str) -> dict:
    """A row that recovers, with one defect planted: the one its column must catch."""
    row = {**ROWS[name]}
    if column == "templates stay":
        row["templates"] = row["templates"][1:]
    elif column == "nothing unverified airs":
        # The cue still says verified, but its text fails the code checks: the flag is not trusted.
        first = {**row["insights"][0], "verified": True, "passes_check": False}
        row["insights"] = [first, *row["insights"][1:]]
    elif column == "claim ends as it must":
        # Held was expected: a second moment rejected is not the same end (lesson 96).
        row["statuses"] = [*row["statuses"], "rejected"]
    elif column == "fallback recorded":
        row["trace_fallbacks"] = []  # the Spanish variants' holds are still in row["fallback"]
    elif column == "fallback badge on screen":
        row["badges"] = []
    return row


@pytest.mark.parametrize(("name", "column"), [
    ("tactician outage", "templates stay"),
    ("personalizer down", "nothing unverified airs"),
    ("low confidence", "claim ends as it must"),
    ("judge timeout", "fallback recorded"),
    ("personalizer down", "fallback badge on screen"),
])
def test_each_recovery_column_catches_its_own_defect(name, column):
    assert all(wf.recovered(ROWS[name], BASE).values())
    checks = wf.recovered(planted(name, column), BASE)
    assert [c for c, ok in checks.items() if not ok] == [column]


def test_the_baseline_fails_if_it_records_a_fallback_or_shows_a_badge():
    marked = {**BASE, "trace_fallbacks": ["producer: held: timeout"]}
    assert wf.recovered(marked, BASE)["fallback recorded"] is False
    assert wf.recovered({**BASE, "badges": ["held: timeout"]}, BASE)["fallback badge on screen"] is False


def test_every_aired_text_is_checked_again_and_passes():
    for row in ROWS.values():
        assert all(i["passes_check"] for i in row["insights"]), row["scenario"]


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


@pytest.mark.parametrize("shape", [None, ["a variant as a bare string"], [{"persona": "casual"}], 42],
                         ids=["none", "strings", "dicts", "a number"])
def test_a_personalizer_returning_a_bad_shape_never_loses_the_minute(shape):
    # Whatever it returns, the node fails closed: no variant, the insight, the templates and the
    # trace all stay, and the minute ends.
    async def malformed(claim, evidence, profiles):
        return shape

    result = minute(True, personalizer=malformed)
    assert [c["persona"] for c in result.cues if c["kind"] == "insight"] == ["analyst"]
    assert result.reviews[0].status == "verified"
    assert sorted(c["id"] for c in result.cues if c["kind"] != "insight") == BASE["templates"]
    errors = [s for s in result.trace if s.role == "personalizer"]
    assert [(s.action, s.fallback) for s in errors] == [("error", "personalizer: error")]


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
    import contextlib
    import json
    import sys

    from ninety.agents import credentials, workflow
    from ninety.match.facts import compact
    from ninety.personalizer import core
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
    fake, prompts = FakeFoundry(replies), []

    def recording(**kwargs):
        agent = fake(**kwargs)
        answer = agent.run

        async def run(prompt):
            prompts.append((agent.name, prompt))
            return await answer(prompt)

        agent.run = run
        return agent

    monkeypatch.setattr(workflow, "FoundryAgent", recording)
    personalizer_asked: list[str] = []

    def spanish(text: str) -> str:  # the claims here are wf.claim_on's, worded as claim_in_spanish's
        return text.replace("complete a pass of", "completa un pase de").replace(" at ", " a ")

    @contextlib.asynccontextmanager
    async def published_ask(credential=None):
        # The published Personalizer's stand-in: each profile its claim, the Spanish ones marked.
        assert credential is not None  # the run's own credential, already signed in
        async def ask(text: str) -> str:
            personalizer_asked.append(text)
            body = json.loads(text)
            return json.dumps({"variants": [
                {"i": p["i"], "text": spanish(body["claim"]) if p["lang"] == "es" else body["claim"]}
                for p in body["profiles"]]})

        yield ask, "stand-in"

    monkeypatch.setattr(core, "published_ask", published_ask)
    from ninety.personalizer.client import RemotePersonalizer

    closed, close = [], RemotePersonalizer.close

    async def counted_close(self):
        closed.append(self)
        await close(self)

    monkeypatch.setattr(RemotePersonalizer, "close", counted_close)
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
        base = rows["none"]
        assert base["variants_refused"] == [] and "es" in {i["lang"] for i in base["insights"]}
    # Every Analyst read its minute inline, never the deployed match tools (lesson 90), and the
    # Personalizer's model wrote the variants.
    analysts = [p for name, p in prompts if name == "ninety-moment-analyst"]
    assert analysts and all("EVENTS: " in p and "-inline, minute" in p for p in analysts)
    assert personalizer_asked
    # Every Personalizer client the run opened is closed: one in process per row, and the
    # dead-address one each "Personalizer down" row swaps in.
    rows_run = sum(len(g["rows"]) for g in body["grounds"])
    assert len(closed) == rows_run + len(body["grounds"])
    md = (tmp_path / "failure-table-live.md").read_text()
    assert md.count("# Failure table") == 3 and "live, seed33" in md
    assert len(body["commit"]) == 40 and body["commit"] in md  # which engine simulated the seeds

def test_the_worst_personalized_minute_fits_the_superstep_budget():
    # Three moments, both writers rejected on every draft but the Tactician's last, which airs and
    # goes to the Personalizer: every hop a personalized minute can take. Over budget raises.
    import asyncio

    from ninety.agents import workflow
    from ninety.agents.contracts import Models
    from ninety.agents.slice import MAX_REWRITES
    from tests.test_workflow import EVENTS, PASSES, Judge, false_claim, picks, reply, true_claim

    mains = [p["id"] for p in PASSES[:workflow.MAX_MOMENTS_PER_MINUTE]]
    tactician = [r for m in mains for r in [reply(false_claim(m))] * MAX_REWRITES + [reply(true_claim(m))]]
    challenger = [reply(false_claim(m)) for m in mains for _ in range(1 + MAX_REWRITES)]
    models = Models.scripted({"analyst": [picks(*mains)], "tactician": tactician, "challenger": challenger},
                             judge=Judge())
    result = asyncio.run(workflow.run_workflow(models, EVENTS, 2, "test", personalize=True))
    assert [r.status for r in result.reviews] == ["verified"] * len(mains)
    assert len([s for s in result.trace if s.role == "personalizer"]) == len(mains)


@pytest.mark.parametrize("module", ["workflow_failures", "agent_ablation"])
def test_a_report_with_a_nan_is_refused_not_written(module):
    # Strict JSON (lesson 43): NaN is not JSON, so writing one must fail, not write "NaN".
    import importlib

    mod = importlib.import_module(f"ninety.eval.{module}")
    with pytest.raises(ValueError):
        mod.results({"rows": [{"x": float("nan")}]} if module == "agent_ablation" else [{"x": float("nan")}])
