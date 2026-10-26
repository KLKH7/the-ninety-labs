"""The commentary track (ninety/speech/commentary.py): checked calls, one voice, never a guessed side."""

import json
import random

import pytest

from ninety.speech import bundle, commentary, describe
from ninety.speech.commentary import GAP_S, MAX_LAG_S

CLUBS = {"home": "London", "away": "Lisbon"}


def ev(i, t, kind, team="home", side=0.99, conf=0.9, **kw):
    return {"id": i, "t": t, "type": kind, "team": team, "team_confidence": side, "player": None,
            "x": 90.0, "y": 34.0, "source": "vision", "confidence": conf, **kw}


def lines(events, cues=(), clubs=CLUBS):
    return commentary.commentary(events, list(cues), clubs)["lines"]


def texts(events, cues=(), clubs=CLUBS):
    return [line["text"] for line in lines(events, cues, clubs)]


def test_a_commentator_calls_goals_shots_and_restarts_in_the_present_tense():
    events = [ev("v1", 10.0, "shot", outcome="on_target"), ev("v2", 20.0, "goal", team="away"),
              ev("v3", 40.0, "out_of_play", y=68.0), ev("v4", 60.0, "out_of_play", x=105.0, y=40.0),
              ev("v5", 80.0, "kickoff")]
    assert texts(events) == ["London shoot, on target.", "Goal! Lisbon score!", "It's gone out of play.",
                             "London kick off."]  # v4 is 20 s after v3: within REPEAT_S, not called again


def test_the_ball_going_out_is_said_in_turn_in_plain_words_and_not_twice_in_half_a_minute():
    outs = [ev(f"v{i}", 40.0 * i, "out_of_play", y=0.0) for i in range(1, 6)]
    assert texts(outs) == [*commentary.OUT_SAID, commentary.OUT_SAID[0]]
    close = [ev("v1", 40.0, "out_of_play", y=0.0),
             ev("v2", 40.0 + commentary.REPEAT_S - 1, "out_of_play", y=0.0),
             ev("v3", 40.0 + commentary.REPEAT_S + 1, "out_of_play", y=0.0)]
    assert texts(close) == [commentary.OUT_SAID[0], commentary.OUT_SAID[1]]


@pytest.mark.parametrize("side", [None, 0.3, 0.96])  # unknown, unsure, at the threshold (not above it)
def test_a_side_not_told_surely_is_never_said(side):
    events = [ev("v1", 10.0, "shot", side=side, outcome="off_target"), ev("v2", 20.0, "goal", side=side),
              ev("v3", 40.0, "kickoff", side=side)]
    said = texts(events)
    assert said == ["A shot, wide.", "Goal!", "Kick-off."]
    assert not any(word in " ".join(said) for word in ("London", "Lisbon", "home", "away", "Home", "Away"))


def test_a_detection_below_the_confidence_gate_is_not_called():
    body = commentary.commentary([ev("v1", 10.0, "goal", conf=0.4)], [], CLUBS)
    assert body["lines"] == [] and "below" in body["refused"][0]["reason"]


def test_a_goal_is_never_crowded_out_by_an_insight_or_a_restart():
    pass_ = ev("v3", 10.4, "pass", player="h-t4", receiver="h-t8", outcome="success", end_x=78.0, end_y=34.0,
               ball_speed_kmh=40.0)
    events = [ev("v1", 10.0, "out_of_play", y=0.0), ev("v2", 10.2, "goal"), pass_]
    cue = {"id": "insight-m-v3", "kind": "insight", "persona": "analyst", "verified": True, "t_in": 10.4,
           "text": "h-t4 plays it 12 m to h-t8, at 40 km/h.", "evidence": ["v3"]}
    said = lines(events, [cue])
    assert said[0]["kind"] == "goal" and said[0]["t"] == 10.2  # on its moment, whatever came first
    assert all(line["kind"] != "insight" or line["t"] >= said[0]["t_end"] + GAP_S for line in said)


def test_an_insight_is_said_only_when_verified_and_never_names_an_unsure_side():
    events = [ev("v3", 10.0, "pass", side=0.3, player="h-t4", receiver="h-t8", outcome="success",
                 end_x=78.0, end_y=34.0, ball_speed_kmh=40.0)]
    cue = {"id": "insight-m-v3", "kind": "insight", "persona": "analyst", "t_in": 10.0,
           "text": "h-t4 plays it 12 m to h-t8, at 40 km/h.", "evidence": ["v3"]}
    assert texts(events, [{**cue, "verified": False}]) == []
    (said,) = texts(events, [{**cue, "verified": True}])
    assert said == "A player plays it 12 metres to another player, at 40 kilometres an hour."
    assert "London" not in said and "h-t" not in said


def test_a_number_the_evidence_does_not_hold_is_refused():
    events = [ev("v3", 10.0, "pass", player="h-t4", receiver="h-t8", outcome="success",
                 end_x=78.0, end_y=34.0)]
    cue = {"id": "insight-m-v3", "kind": "insight", "persona": "analyst", "verified": True, "t_in": 10.0,
           "text": "h-t4 plays it 30 m to h-t8.", "evidence": ["v3"]}
    body = commentary.commentary(events, [cue], CLUBS)
    assert body["lines"] == [] and "30" in body["refused"][0]["reason"]


def test_lines_never_overlap_leave_silence_and_are_never_late():
    rng = random.Random(7)
    kinds = ["goal", "shot", "out_of_play", "kickoff", "shot", "out_of_play"]
    events = sorted((ev(f"v{n}", round(rng.uniform(0, 120), 2), rng.choice(kinds),
                        team=rng.choice(["home", "away"]), side=rng.choice([0.3, 0.99]),
                        outcome=rng.choice(["on_target", "off_target", None]),
                        y=rng.choice([0.0, 34.0, 68.0]))
                     for n in range(80)), key=lambda e: e["t"])
    body = commentary.commentary(events, [], CLUBS)
    said = body["lines"]
    assert said and body["dropped"]  # the play outruns one voice: some calls must go
    for a, b in zip(said, said[1:], strict=False):
        assert b["t"] >= a["t_end"] + GAP_S - 1e-9
    assert all(0 <= line["t"] - line["t_event"] <= MAX_LAG_S + 1e-9 for line in said)
    goals = [e for e in events if e["type"] == "goal"]
    called = {line["evidence"][0] for line in said}
    # A goal is dropped only when another goal holds the voice.
    for g in goals:
        if g["id"] not in called:
            assert any(line["kind"] == "goal" and line["t"] - GAP_S < g["t"] + MAX_LAG_S
                       and line["t_end"] + GAP_S > g["t"] for line in said)


def test_the_bundle_voices_every_call_and_the_estimate_calls_nothing(tmp_path):
    body = commentary.commentary([ev("v1", 10.0, "shot", outcome="on_target")], [], CLUBS)
    summary = commentary.write(body, tmp_path)
    assert summary == {"count": 1, "dropped": 0, "refused": 0, "chars": len("London shoot, on target.")}
    assert ("London shoot, on target.", "commentary") in bundle.lines(tmp_path)
    cost = bundle.estimate(tmp_path, cache=tmp_path / "empty-cache")
    assert cost["by_kind"]["commentary"] == 1 and cost["new_lines"] == cost["lines"]
    assert cost["usd_at_s1"] == round(cost["chars"] * bundle.USD_PER_CHAR, 4)
    assert not (tmp_path / "speech.json").exists()  # an estimate synthesises nothing
    assert json.loads((tmp_path / "commentary.json").read_text())["format"] == 1


def test_voicing_the_bundle_points_each_call_at_its_audio(tmp_path):
    from tests.test_speech import FakeSynth

    events = [ev("v1", 10.0, "shot", outcome="on_target"), ev("v2", 30.0, "goal", team="away")]
    commentary.write(commentary.commentary(events, [], CLUBS), tmp_path)
    # The goal's synthesis fails: its call keeps no audio, and the player shows its caption alone.
    bundle.write(tmp_path, synth=FakeSynth(fail={"Goal!"}), cache=tmp_path / "cache", sleep=lambda s: None)
    lines = {line["text"]: line for line in json.loads((tmp_path / "commentary.json").read_text())["lines"]}
    shot = lines["London shoot, on target."]
    assert shot["audio"].startswith("speech/") and (tmp_path / shot["audio"]).is_file()
    assert lines["Goal! Lisbon score!"]["audio"] is None
    assert [k for k in ("t", "t_end", "text", "audio", "event") if k not in shot] == []


@pytest.mark.parametrize(("restart", "sure", "unsure"), [
    ("corner", "Corner to London.", "A corner."), ("goal_kick", "Goal kick to London.", "A goal kick."),
    ("throw_in", "London throw.", "A throw-in."), ("free_kick", "Free kick to London.", "A free kick."),
    ("penalty_kick", "Penalty to London!", "A penalty!"), (None, "A set piece.", "A set piece."),
])
def test_a_restart_names_the_side_taking_it_only_when_sure(restart, sure, unsure):
    # vision's set piece (#325): `team` is the side taking it; a null side confidence is unsure.
    assert texts([ev("v1", 10.0, "set_piece", side=0.99, restart=restart)]) == [sure]
    assert texts([ev("v1", 10.0, "set_piece", side=None, restart=restart)]) == [unsure]


# --- review of #328: each pins what a mutant got past -------------------------------------------

def test_a_line_lasts_as_long_as_it_takes_to_say_and_the_next_waits_a_second_of_silence():
    events = [ev("v1", 10.0, "shot", outcome="on_target"), ev("v2", 11.0, "shot", outcome="off_target")]
    first, second = lines(events)
    said = describe.estimated_seconds(first["text"])
    assert first["t"] == 10.0 and first["t_end"] == pytest.approx(10.0 + said, abs=0.01)
    assert second["t"] == pytest.approx(first["t_end"] + 1.0, abs=0.01)  # the earliest start, 1 s of silence


def test_a_call_that_would_start_more_than_two_seconds_late_is_dropped():
    goal = ev("v1", 10.0, "goal", team="away")  # "Goal! Lisbon score!" holds the voice ~1.3 s, then 1 s
    free = round(10.0 + describe.estimated_seconds("Goal! Lisbon score!") + 1.0, 2)
    just_in = ev("v2", round(free - 1.99, 2), "out_of_play", y=34.0, x=105.0)
    too_late = ev("v3", round(free - 2.02, 2), "out_of_play", y=34.0, x=105.0)
    assert [line["event"] for line in lines([goal, just_in])] == ["v1", "v2"]
    assert [line["event"] for line in lines([goal, too_late])] == ["v1"]


def test_a_call_falls_back_to_its_short_form_to_fit_before_a_goal():
    goal = ev("v1", 20.0, "goal")
    shot = ev("v2", 17.9, "shot", outcome="on_target")  # the full form would run into the goal
    said = {line["event"]: line for line in lines([goal, shot])}
    assert said["v2"]["text"] == "London shoot." and said["v2"]["short"] is True


def test_only_vision_detections_with_a_confidence_are_called():
    for row in (ev("v1", 10.0, "goal", conf=None), {**ev("v2", 10.0, "goal"), "source": "truth"}):
        body = commentary.commentary([row], [], CLUBS)
        assert body["lines"] == [] and "vision detection" in body["refused"][0]["reason"]


@pytest.mark.parametrize(("x", "y"), [(60.0, 68.0), (104.9, 0.5), (105.0, 34.0)])
def test_a_ball_out_is_only_out_the_restart_is_visions_reading(x, y):
    # Review of #328: where the ball crossed is not the restart; a set piece's `restart` says which.
    assert texts([ev("v1", 10.0, "out_of_play", x=x, y=y)]) == ["It's gone out of play."]


def test_half_time_and_a_blocked_shot_are_called():
    assert texts([ev("v1", 10.0, "shot", outcome="blocked"), ev("v2", 40.0, "half_time")]) == [
        "London shoot, blocked.", "Half-time."]


@pytest.mark.parametrize("cue", [
    {"verified": None}, {"verified": True, "evidence": ["nope"]}, {"verified": True, "evidence": []},
    {"verified": True, "persona": "casual"}, {"verified": True, "lang": "es"},
])
def test_an_insight_is_said_only_as_the_verified_english_analyst_claim_on_known_events(cue):
    events = [ev("v3", 10.0, "pass", player="h-t4", receiver="h-t8", outcome="success",
                 end_x=78.0, end_y=34.0)]
    base = {"id": "insight-m-v3", "kind": "insight", "persona": "analyst", "t_in": 10.0, "lang": "en",
            "text": "h-t4 plays it 12 m to h-t8.", "evidence": ["v3"]}
    assert texts(events, [{**base, **cue}]) == []
    assert len(texts(events, [{**base, "verified": True}])) == 1


def test_lines_are_spaced_on_the_videos_clock_across_a_cut():
    from ninety.match.timeline import Timeline

    # The ball goes out at 99 s; the picture cuts from 100.56 s to the restart at 130 s.
    timeline = Timeline([{"index": 0, "frame": 2450, "frames": 64},
                         {"index": 64, "frame": 3250, "frames": 100}], 25)
    out = ev("v1", 99.0, "out_of_play", y=68.0)
    restart = ev("v2", 130.2, "set_piece", restart="throw_in")
    first, second = commentary.commentary([out, restart], [], CLUBS, timeline)["lines"]
    # One voice on screen, though they are 31 s apart in the match: on the video's clock the restart
    # waits for the first line and its second of silence.
    said = describe.estimated_seconds(first["text"])
    assert timeline.to_video(second["t"]) >= timeline.to_video(first["t"]) + said + 1.0 - 0.01
    assert first["t"] == 99.0 and second["v"] == pytest.approx(timeline.to_video(second["t"]), abs=0.02)


def test_once_voiced_a_line_whose_audio_runs_long_drops_the_lower_priority_one_after_it():
    body = commentary.commentary([ev("v1", 10.0, "shot", outcome="on_target"), ev("v2", 12.9, "out_of_play",
                                                                                     x=105.0)], [], CLUBS)
    assert len(body["lines"]) == 2
    body = commentary.refit(body, {"cm-v1": 3.0})  # the shot's audio is 3 s, not the estimate
    assert [line["id"] for line in body["lines"]] == ["cm-v1"] and body["lines"][0]["t_end"] == 13.0
    assert body["dropped"][-1] == {"id": "cm-v2", "t": 12.9,
                                   "reason": "its audio runs longer than estimated: no room"}


def test_the_estimate_cli_calls_nothing_and_writes_nothing(tmp_path, monkeypatch, capsys):
    commentary.write(commentary.commentary([ev("v1", 10.0, "goal")], [], CLUBS), tmp_path)

    def no_azure():
        raise AssertionError("--estimate must not reach Azure")

    monkeypatch.setattr(bundle, "azure_synth", no_azure)
    bundle.main([str(tmp_path), "--estimate", "--cache", str(tmp_path / "cache")])
    assert json.loads(capsys.readouterr().out)["by_kind"]["commentary"] == 1
    assert not (tmp_path / "speech.json").exists() and not (tmp_path / "speech").exists()


def test_a_line_never_starts_before_its_moment():
    (line,) = lines([ev("v1", 10.004, "shot", outcome="on_target")])
    assert line["t"] >= 10.004 and line["v"] >= 10.004


def test_voicing_the_bundle_times_each_call_by_its_audio(tmp_path):
    from tests.test_speech import FakeSynth

    shot = ev("v1", 10.0, "shot", outcome="on_target")
    commentary.write(commentary.commentary([shot], [], CLUBS), tmp_path)
    bundle.write(tmp_path, synth=FakeSynth(), cache=tmp_path / "cache", sleep=lambda s: None)
    (line,) = json.loads((tmp_path / "commentary.json").read_text())["lines"]
    heard = (tmp_path / line["audio"]).stat().st_size / 6000  # 48 kbit/s: voice.FORMAT
    assert line["t_end"] == pytest.approx(line["t"] + heard, abs=0.011)
