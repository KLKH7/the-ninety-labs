import pytest

from ninety.agents.factcheck import Claim, check
from ninety.match.facts import compact, events_in

EVENTS = events_in(7, 5, 1, 5)
KNOWN = {e["id"]: e for e in EVENTS}
PASS = next(e for e in EVENTS if e["type"] == "pass" and "distance_m" in e and e.get("receiver"))
# any event in the second minute of play (01:00 to 01:59), whatever the engine produces there
CLOCK_EVENT = next(e for e in EVENTS if e["clock"].startswith("01:"))


def test_true_claim_passes():
    who, to = PASS["player"], PASS["receiver"]
    text = f"{who} finds {to} with a {PASS['distance_m']} m pass in minute {PASS['minute']}."
    assert check(Claim(text, [PASS["id"]]), KNOWN).ok


def test_planted_number_is_rejected():
    text = f"{PASS['player']} plays a {PASS['distance_m'] + 37} m pass."
    verdict = check(Claim(text, [PASS["id"]]), KNOWN)
    assert not verdict.ok
    assert any("distance_m" in reason for reason in verdict.reasons)


def test_unknown_evidence_is_rejected():
    verdict = check(Claim("A pass.", ["e99999"]), KNOWN)
    assert not verdict.ok and "unknown event ids" in verdict.reasons[0]


def test_uncited_player_is_rejected():
    other = next(f"h{n}" for n in range(1, 12) if f"h{n}" not in (PASS["player"], PASS.get("receiver")))
    verdict = check(Claim(f"{other} starts the move.", [PASS["id"]]), KNOWN)
    assert not verdict.ok


def test_no_evidence_is_rejected():
    assert not check(Claim("Nothing happened.", []), KNOWN).ok


def test_counts_of_cited_events_are_allowed():
    passes = [e for e in EVENTS if e["type"] == "pass"][:3]
    text = f"{len(passes)} passes in a row."
    assert check(Claim(text, [e["id"] for e in passes]), KNOWN).ok


def test_event_ids_and_player_ids_are_not_read_as_numbers():
    text = f"{PASS['player']} passes."
    assert check(Claim(text, [PASS["id"]]), KNOWN).ok


def test_number_before_a_full_stop_is_still_checked():
    verdict = check(Claim(f"{PASS['player']} passes in minute 88.", [PASS["id"]]), KNOWN)
    assert not verdict.ok


def test_distance_cannot_be_used_as_speed():
    verdict = check(Claim(f"A {PASS['distance_m']} km/h pass.", [PASS["id"]]), KNOWN)
    assert not verdict.ok
    assert "ball_speed_kmh" in verdict.reasons[0]


def test_speed_cannot_be_used_as_distance():
    verdict = check(Claim(f"A {PASS['ball_speed_kmh']} m pass.", [PASS["id"]]), KNOWN)
    assert not verdict.ok
    assert "distance_m" in verdict.reasons[0]


def test_seconds_cannot_be_used_as_minutes():
    verdict = check(Claim(f"A pass in minute {PASS['second']}.", [PASS["id"]]), KNOWN)
    assert PASS["second"] != PASS["minute"]
    assert not verdict.ok
    assert "minute" in verdict.reasons[0]


def test_units_are_allowed_when_they_match_their_fields():
    text = (
        f"A {PASS['distance_m']} metres pass at {PASS['ball_speed_kmh']} kph "
        f"in {PASS['minute']} minutes and {PASS['second']} seconds."
    )
    assert check(Claim(text, [PASS["id"]]), KNOWN).ok


def test_roster_player_not_in_evidence_is_rejected():
    roster_player = "home_keeper"
    verdict = check(
        Claim(f"{roster_player} starts the move.", [PASS["id"]]),
        KNOWN,
        roster=[{"id": roster_player}],
    )
    assert not verdict.ok
    assert roster_player in verdict.reasons[0]


def test_unknown_id_shaped_word_is_not_rejected():
    verdict = check(Claim("z99 starts the move.", [PASS["id"]]), KNOWN)
    assert verdict.ok


def test_old_ordinal_clock_form_is_rejected():
    verdict = check(
        Claim(f"At {CLOCK_EVENT['minute']}:{CLOCK_EVENT['second']:02d}.", [CLOCK_EVENT["id"]]),
        KNOWN,
    )
    assert not verdict.ok
    assert any("clock" in reason for reason in verdict.reasons)


def test_clock_with_wrong_second_is_rejected():
    wrong = f"01:{(int(CLOCK_EVENT['clock'][3:]) + 1) % 60:02d}"
    verdict = check(Claim(f"A pass at {wrong}.", [CLOCK_EVENT["id"]]), KNOWN)
    assert not verdict.ok
    assert any("clock" in reason for reason in verdict.reasons)


def test_clock_with_the_right_minute_and_second_passes():
    text = f"An event at {CLOCK_EVENT['clock']}."
    assert check(Claim(text, [CLOCK_EVENT["id"]]), KNOWN).ok


def test_clock_accepts_unpadded_minute():
    text = f"An event at {int(CLOCK_EVENT['clock'][:2])}:{CLOCK_EVENT['clock'][3:]}."
    assert check(Claim(text, [CLOCK_EVENT["id"]]), KNOWN).ok


def test_ordinal_minute_remains_valid():
    text = f"A pass in the {CLOCK_EVENT['minute']} minute."
    assert check(Claim(text, [CLOCK_EVENT["id"]]), KNOWN).ok


def test_compact_event_floors_seconds_at_sixty():
    event = {
        "t": 59.6,
        "id": "x",
        "type": "pass",
        "team": "home",
        "player": "h1",
        "receiver": None,
        "outcome": None,
        "ball_speed_kmh": None,
        "end_x": None,
        "x": 0,
        "y": 0,
    }
    compact_event = compact(event)
    assert compact_event["second"] == 59
    assert compact_event["clock"] == "00:59"


def test_player_in_no_known_event_is_still_rejected():
    """Planted defect: a squad player absent from every event must not slip through. The known
    events are the clip's less any that name him, so the test does not rely on someone happening
    to stay out of the clip (with every player in it, it had nobody to plant)."""
    absent = next(f"h{n}" for n in range(1, 12) if f"h{n}" not in (PASS["player"], PASS.get("receiver")))
    names = ("player", "receiver", "intended", "interceptor", "deflected_by")  # every field the checker reads
    known = {i: e for i, e in KNOWN.items() if absent not in (e.get(k) for k in names)}
    verdict = check(Claim(f"{absent} starts the move.", [PASS["id"]]), known)
    assert not verdict.ok
    assert absent in verdict.reasons[0]


def test_a_pass_finds_only_its_receiver():
    """Lesson 42: who a pass was for and who won it are cited players, but neither received it, so a
    verb that says it arrived must name the receiver."""
    failed = {"id": "e1", "clock": "00:10", "minute": 1, "second": 10, "type": "pass", "team": "home",
              "player": "h7", "intended": "h9", "interceptor": "a4", "outcome": "fail", "distance_m": 20}
    other = {**failed, "id": "e2", "receiver": "h10", "outcome": "success"}
    other.pop("interceptor")
    known = {e["id"]: e for e in (failed, other)}
    for e, name in ((failed, "h9"), (failed, "a4"), (other, "h9")):
        verdict = check(Claim(f"h7 finds {name} with a 20 m pass.", [e["id"]]), known)
        assert not verdict.ok and f"player {name} received no cited pass from h7" in verdict.reasons
    assert not check(Claim("h7 picks out h9.", ["e2"]), known).ok
    assert check(Claim("h7 finds h10 with a 20 m pass.", ["e2"]), known).ok
    assert check(Claim("h7's pass for h9 is cut out by a4.", ["e1"]), known).ok


def test_a_passer_finds_only_the_player_his_own_pass_reached():
    """Two cited passes: each passer's verb must name his own pass's receiver, not the other's."""
    one = {"id": "e1", "clock": "00:10", "minute": 1, "second": 10, "type": "pass", "team": "home",
           "player": "h7", "receiver": "h10", "outcome": "success", "distance_m": 20}
    two = {**one, "id": "e2", "player": "h3", "receiver": "h9"}
    known = {e["id"]: e for e in (one, two)}
    assert check(Claim("h7 finds h10, then h3 finds h9.", ["e1", "e2"]), known).ok
    for text in ("h7 finds h9.", "h3 finds h10.", "h7 Finds H9.", "H7 Finds H9."):
        assert not check(Claim(text, ["e1", "e2"]), known).ok, text
    assert check(Claim("H7 Finds H10.", ["e1"]), known).ok  # ids compared whatever their case


def test_found_about_a_tackle_or_pressure_is_not_read_as_a_pass():
    """A tackle's or a press's `receiver` is the player challenged: the pass rule does not apply."""
    tackle = {"id": "e1", "clock": "00:10", "minute": 1, "second": 10, "type": "tackle", "team": "away",
              "player": "a4", "receiver": "h9", "outcome": "success"}
    press = {**tackle, "id": "e2", "type": "pressure", "outcome": None}
    known = {e["id"]: e for e in (tackle, press)}
    assert check(Claim("a4 found h9 in possession and won it.", ["e1"]), known).ok
    assert check(Claim("a4 picks out h9 to press.", ["e2"]), known).ok
    # his failed pass and his tackle on h9 cited together: the tackle did not make h9 a receiver
    failed = {**tackle, "id": "e3", "type": "pass", "receiver": None, "intended": "a9", "outcome": "fail"}
    known["e3"] = failed
    assert not check(Claim("a4 finds h9.", ["e1", "e3"]), known).ok


# Computed facts as evidence (the Companion's window facts, ninety/intel/window.py).
SPEED = {"id": "peak_speed:player_h7_window_0.00-95.20", "metric": "peak_speed", "value": 27.3,
         "unit": "km/h", "scope": "player:h7:window:0.00-95.20", "source_ids": ["frames:0-2380"]}
RUN = {"id": "distance_run:player_h7_window_0.00-95.20", "metric": "distance_run", "value": 151.0,
       "unit": "m", "scope": "player:h7:window:0.00-95.20", "source_ids": ["frames:0-2380"]}
FACTS = {f["id"]: f for f in (SPEED, RUN)}


def test_a_cited_facts_value_with_its_unit_passes():
    assert check(Claim("h7's top speed so far is 27.3 km/h.", [SPEED["id"]]), FACTS).ok
    assert check(Claim("h7 has covered 151 m so far.", [RUN["id"]]), FACTS).ok


def test_a_facts_value_needs_its_unit():
    verdict = check(Claim("h7 has hit 27.3 so far.", [SPEED["id"]]), FACTS)
    assert not verdict.ok and verdict.reasons == ["number 27.3 is not in the cited evidence"]


def test_a_facts_value_with_another_unit_is_rejected():
    verdict = check(Claim("h7 has covered 27.3 m.", [SPEED["id"]]), FACTS)
    assert not verdict.ok and verdict.reasons == ["number 27.3 is not a cited distance_m"]
    assert not check(Claim("h7 is at 151 km/h.", [RUN["id"], SPEED["id"]]), FACTS).ok


def test_a_number_a_cited_fact_does_not_hold_is_rejected():
    verdict = check(Claim("h7 is running at 50 km/h.", [SPEED["id"]]), FACTS)
    assert not verdict.ok and verdict.reasons == ["number 50 is not a cited ball_speed_kmh"]


def test_a_facts_unit_counts_only_straight_after_its_number():
    # "frames" is the fact's unit, but here it follows another number.
    sprints = {"id": "s", "metric": "sprint_frames", "value": 3.0, "unit": "frames", "scope": "player:h7"}
    assert check(Claim("h7 sprinted for 3 frames.", ["s"]), {"s": sprints}).ok
    assert not check(Claim("h7 sprinted 3 times in 40 frames.", ["s"]), {"s": sprints}).ok


def test_a_fact_scoped_to_a_player_cites_only_that_player():
    assert check(Claim("h7 has covered 151 m so far.", [RUN["id"]]), FACTS).ok
    verdict = check(Claim("a7 has covered 151 m so far.", [RUN["id"]]), FACTS)
    assert not verdict.ok and verdict.reasons == ["player a7 does not appear in the cited evidence"]


def test_a_fact_is_not_counted_as_an_event():
    # Two cited facts are not "2" of anything a claim may state.
    assert not check(Claim("h7 has 2 numbers.", [RUN["id"], SPEED["id"]]), FACTS).ok


def test_an_ordinal_minute_must_be_the_cited_minute():
    # "the 9th minute" was never read as a number, so any ordinal passed (lesson 95).
    minute = CLOCK_EVENT["minute"]
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(minute, "th")
    assert check(Claim(f"A pass in the {minute}{suffix} minute.", [CLOCK_EVENT["id"]]), KNOWN).ok
    wrong = check(Claim(f"A pass in the {minute + 7}th minute.", [CLOCK_EVENT["id"]]), KNOWN)
    assert not wrong.ok
    assert wrong.reasons == [f"number {minute + 7}th is not a cited minute"]


def test_an_ordinal_count_must_be_in_the_evidence():
    verdict = check(Claim(f"{PASS['player']} plays his 97th pass.", [PASS["id"]]), KNOWN)
    assert verdict.reasons == ["number 97th is not in the cited evidence"]


def test_a_cited_stat_keeps_its_bare_value_beside_a_cited_fact():
    # A window stat (type "stat") states its value bare; a window fact needs its unit. Both rules
    # hold in one claim: a fact must not be read as a stat, nor a stat as a fact.
    stat = {"id": "st", "type": "stat", "metric": "pressing_share", "team": "home", "window": 1,
            "minute_from": 2, "minute_to": 3, "value": 0.6, "unit": "share", "events": 4, "percent": 60}
    known = {"st": stat, **FACTS}
    assert check(Claim("Home press 60 of the time while h7 hits 27.3 km/h.", ["st", SPEED["id"]]), known).ok
    bare_fact = check(Claim("Home press 60 of the time while h7 hits 27.3.", ["st", SPEED["id"]]), known)
    assert bare_fact.reasons == ["number 27.3 is not in the cited evidence"]


def test_a_tracked_players_fact_cites_only_that_track():
    # Tracked players are a team plus track id (h-t12): naming another track, or a squad id, is
    # naming a player the evidence does not hold.
    run = {**RUN, "id": "distance_run:player_h-t12", "scope": "player:h-t12:window:0.00-95.20"}
    known = {run["id"]: run}
    assert check(Claim("h-t12 has covered 151 m so far.", [run["id"]]), known).ok
    for other in ("h-t1", "a-t12", "h7"):
        verdict = check(Claim(f"{other} has covered 151 m so far.", [run["id"]]), known)
        assert not verdict.ok and verdict.reasons == [f"player {other} does not appear in the cited evidence"]


@pytest.mark.parametrize("text", [
    "h7's top speed is 50 km/h.",  # spaced
    "h7's top speed is 50km/h.",  # the unit glued on
    "h7's top speed is 50kph.",
    "h7 has covered 9999m.",
    "h7's top speed is fifty km/h.",  # in words
    "h7's top speed is Fifty-Two km/h.",
    "h7 has covered one hundred and two m.",
    "h7 has covered two thousand metres.",
    "h7 made 7 sprints.",  # a bare count the evidence does not hold
    "h7 made seven sprints.",
])
def test_a_planted_number_in_any_written_form_is_rejected(text):
    # Review of #145: the glued and spelled forms passed the check, so a model following an
    # injected instruction could air a number the evidence does not hold.
    assert not check(Claim(text, [SPEED["id"]]), FACTS).ok


@pytest.mark.parametrize("text", [
    "h7's top speed so far is 27.3km/h.",
    "h7 has covered 151m so far.",
    "h7 is one of the quickest, at 27.3 km/h.",  # "one of" is not a count
    "No one has been quicker than h7's 27.3 km/h.",
])
def test_a_true_number_in_any_written_form_passes(text):
    assert check(Claim(text, [SPEED["id"], RUN["id"]]), FACTS).ok


# Review of #145: the word reader summed hyphenated words ("one-two" read as 3) and counted the
# idioms' "one", so true commentary from any agent was rejected (lesson 11: both kinds of error).
ONE_TWO = {
    pid: {"id": pid, "type": "pass", "team": "home", "player": a, "receiver": b, "outcome": "success"}
    for pid, a, b in (("p1", "h7", "h9"), ("p2", "h9", "h7"))
}


@pytest.mark.parametrize("text", [
    "h7 and h9 play a one-two down the right.",
    "A neat one-two between h7 and h9.",
    "h7 and h9 work one-twos down the right.",
    "h7 wins a one-on-one with h9.",
    "h7 takes h9 on one v one.",
    "h7 plays a one-touch pass to h9.",
    "h9 sends it back first time, one-time, to h7.",
    "h7 goes in two-footed on h9.",
    "h7 is one of the busiest, linking with h9.",
    "No one links better than h7 and h9.",
])
def test_football_idioms_are_words_not_counts(text):
    assert check(Claim(text, ["p1", "p2"]), ONE_TWO).ok


@pytest.mark.parametrize("text, read", [
    ("h7 and h9 play twenty-eight passes.", "28"),
    ("h7 and h9 trade three passes.", "3"),
    ("Home keep it at one-nil.", "1"),
    ("h7 and h9 string together two hundred and five passes.", "205"),
])
def test_planted_counts_in_words_are_still_read(text, read):
    verdict = check(Claim(text, ["p1", "p2"]), ONE_TWO)
    assert not verdict.ok and any(f"number {read} " in r for r in verdict.reasons)


@pytest.mark.parametrize("text, digits", [
    ("Home lead two-one.", "Home lead 2-1."),  # a score: two numbers, never 3
    ("They line up four-four-two.", "They line up 4-4-2."),  # a formation, never 10
    ("twenty-eight", "28"),
    ("two hundred and five", "205"),
    ("three thousand and twelve", "3012"),
])
def test_number_words_combine_only_into_one_well_formed_number(text, digits):
    from ninety.agents.factcheck import spelled_as_digits

    assert spelled_as_digits(text) == digits
