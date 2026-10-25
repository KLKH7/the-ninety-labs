import pytest

from ninety.agents.factcheck import Claim, check
from ninety.match.facts import compact, events_in

EVENTS = events_in(7, 5, 1, 5)
KNOWN = {e["id"]: e for e in EVENTS}
PASS = next(e for e in EVENTS if e["type"] == "pass" and "distance_m" in e and e.get("receiver"))
# the first event from 01:00 on, whatever the engine produces there: a minute past the first keeps the
# ordinal minute ("2nd") and the clock ("01:xx") apart. Not a fixed minute: a stoppage can fill one
# (after a goal the kick-off waits a minute or more, GROUNDING L4; lesson 47)
CLOCK_EVENT = next(e for e in EVENTS if e["clock"] >= "01:00")


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
    wrong = f"{CLOCK_EVENT['clock'][:3]}{(int(CLOCK_EVENT['clock'][3:]) + 1) % 60:02d}"
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
    # "the 9th minute" was never read as a number, so any ordinal passed (lesson 130).
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


# Lesson 219: the forms the reader still missed. Each planted form aired on the old check; each true
# form must still pass (lesson 11: false rejections are measured too).
# Two cited passes: h7's was 12 m at 40 km/h, h4's 30 m at 70 km/h.
TWO = {
    "p1": {"id": "p1", "type": "pass", "team": "home", "player": "h7", "receiver": "h9", "outcome": "success",
           "minute": 2, "second": 14, "distance_m": 12, "ball_speed_kmh": 40},
    "p2": {"id": "p2", "type": "pass", "team": "home", "player": "h4", "receiver": "h7", "outcome": "success",
           "minute": 3, "distance_m": 30, "ball_speed_kmh": 70},
}
# One pass of 50 m at 31 km/h.
LONG = {"id": "p31", "type": "pass", "team": "home", "player": "h7", "receiver": "h9", "outcome": "success",
        "minute": 2, "distance_m": 50, "ball_speed_kmh": 31}


@pytest.mark.parametrize("text, reason", [
    ("h7 juega un pase a cincuenta km/h a h9.", "number 50 is not a cited ball_speed_kmh"),
    # 50 is the pass's distance, so read bare it passed: as a speed it must be the cited speed
    ("h7 juega un pase a 50 kilómetros por hora a h9.", "number 50 is not a cited ball_speed_kmh"),
    ("h7 juega un pase a 50 km por hora a h9.", "number 50 is not a cited ball_speed_kmh"),
    ("h7 da un pase de treinta metros a h9.", "number 30 is not a cited distance_m"),
    ("h7 da un pase de ciento veinte metros a h9.", "number 120 is not a cited distance_m"),
    ("h7 da siete pases a h9.", "number 7 is not in the cited evidence"),
    ("h7 encuentra a h9 en el minuto cincuenta.", "number 50 is not a cited minute"),
    ("h7 encuentra a h9 en el minuto 50.", "number 50 is not a cited minute"),
    ("h7 da once pases a h9.", "number 11 is not in the cited evidence"),
    ("h7 encuentra a h9 a los 3 segundos.", "number 3 is not a cited second"),
])
def test_a_planted_spanish_number_is_rejected(text, reason):
    verdict = check(Claim(text, ["p31"]), {"p31": LONG})
    assert not verdict.ok and reason in verdict.reasons


@pytest.mark.parametrize("text", [
    "h7 juega un pase a treinta y un km/h a h9.",
    "h7 juega un pase a treinta y uno kilómetros por hora a h9.",
    "h7 juega un pase a 31 kilometros por hora a h9.",
    "h7 da un pase de cincuenta metros a h9.",
    "h7 da un pase de 50 metros a h9 en el minuto dos.",  # "un" is the article, not a count
    "h7 encuentra a h9 en el minuto 2.",
    "Once again h7 finds h9 over 50 m.",  # the English adverb, not "11"
    "h7, del once inicial, encuentra a h9.",
])
def test_a_true_spanish_number_passes(text):
    assert check(Claim(text, ["p31"]), {"p31": LONG}).ok


@pytest.mark.parametrize("text", [
    "h7 gana el uno contra uno y encuentra a h9.",
    "h7 es uno de los mejores y encuentra a h9.",
    "h7 se va de uno y encuentra a h9.",  # beats his man
    "h7 y h9 hacen un dos contra uno.",
    "h7 lo da todo, al cien por cien, y encuentra a h9.",
    "h7 sale a mil por hora y encuentra a h9.",  # at full tilt
    "h7 controla con los dos pies y encuentra a h9.",
    "h7 and h9 make a two-on-one.",
    "h7 and h9 work a three v two.",
    "h7 encuentra a h9 a los 14 segundos.",
])
def test_idioms_and_true_seconds_in_spanish_pass(text):
    # Review of #257: each was rejected by the first version of the Spanish reader. Two passes are
    # cited, so a "uno" misread as 1 is no count the evidence holds.
    assert check(Claim(text, ["p1", "p2"]), TWO).ok


@pytest.mark.parametrize("text, number", [
    ("h7 plays a two-on-three m pass to h9.", "3"),
    ("h7 plays a one-on-three m pass to h9.", "3"),
    ("h7 finds h9 at three v four km/h.", "4"),
    ("h7 finds h9 in the two on four minute.", "4"),
    ("h7 finds h9 with three on four players near the ball.", "4"),
    ("h7 juega un pase de dos contra tres metros a h9.", "3"),
])
def test_a_number_after_an_n_on_m_idiom_with_a_unit_is_still_checked(text, number):
    # Review of #268: "two-on-three" is a word, but "two-on-three m" ends in a number with its unit
    # (or a counted noun), which must be in the evidence like any other.
    verdict = check(Claim(text, ["p1", "p2"]), TWO)
    assert not verdict.ok and any(f"number {number} " in r for r in verdict.reasons), verdict.reasons


@pytest.mark.parametrize("text", [
    "h7 and h9 make a two-on-three in midfield.",
    "h7 and h9 work a three v four on the right.",
    "h7 y h9 juegan un dos contra tres en el medio.",
])
def test_an_n_on_m_idiom_with_no_unit_after_it_is_a_word(text):
    assert check(Claim(text, ["p1", "p2"]), TWO).ok


@pytest.mark.parametrize("text, reason", [
    ("h7 plays his seventh pass to h9.", "number 7th is not in the cited evidence"),
    ("h7 finds h9 in the ninth minute.", "number 9th is not a cited minute"),
    ("h7 finds h9 in the twenty-first minute.", "number 21st is not a cited minute"),
    ("h7 finds h9 in the ninth-minute move.", "number 9th is not a cited minute"),
    ("h7 finds h9 in the first minute.", "number 1st is not a cited minute"),
    ("h7 finds h9 with his third pass.", "number 3rd is not in the cited evidence"),
    ("h7 da su séptimo pase a h9.", "number 7th is not in the cited evidence"),
    ("h7 encuentra a h9 en el noveno minuto.", "number 9th is not a cited minute"),
])
def test_an_ordinal_in_words_must_be_in_the_evidence(text, reason):
    verdict = check(Claim(text, ["p31"]), {"p31": LONG})
    assert not verdict.ok and reason in verdict.reasons


@pytest.mark.parametrize("text", [
    "h7 finds h9 in the second minute.",
    "h7 finds h9 in the 2nd minute.",
    "h7 finds h9 first time.",
    "h7 finds h9 in the second half.",
    "h7 finds h9 with his first touch.",
    "h7 picks up the second ball and finds h9.",
    "h7 finds h9 in the final third.",
    "h7 plays the attacking-third pass to h9.",  # hyphenated, as the window stats write it
    "h7 finds h9 with a third-man run.",
    "h7 finds h9, and the fourth official looks on.",
    "h7 has a third of the passes and finds h9.",
    "h7 encuentra a h9 en el segundo minuto.",
    "h7 encuentra a h9 en la primera parte.",
    "h7 encuentra a h9 con un tercer hombre.",
])
def test_a_word_that_is_no_ordinal_count_passes(text):
    # Two passes cited, so a "first" misread as 1 is no count the evidence holds.
    assert check(Claim(text, ["p1", "p2"]), TWO).ok


@pytest.mark.parametrize("text", [
    "h7 plays a 50 yards pass to h9.",  # the digits are the cited distance_m; the unit is not metres
    "h7 plays a 50-yard pass to h9.",
    "h7 plays a 50 yd pass to h9.",
    "h7 plays it 50 feet to h9.",
    "h7 hits it at 31 mph to h9.",
    "h7 hits it at 31 m/s to h9.",
    "h7 hits it at 31 metres per second to h9.",
    "h7 hits it 50 km to h9.",
    "h7 hits it fifty yards to h9.",
    "h7 da un pase de cincuenta yardas a h9.",
    "h7 da un pase a 31 millas por hora a h9.",
])
def test_a_number_in_a_unit_we_do_not_publish_is_rejected(text):
    # "50 yards" is not 50 m, and "31 mph" is not 31 km/h: refused whatever the digits, never converted.
    verdict = check(Claim(text, ["p31"]), {"p31": LONG})
    assert not verdict.ok and any("a unit the evidence does not use" in r for r in verdict.reasons)


@pytest.mark.parametrize("text", [
    "h7 plays a 50 m pass to h9 at 31 km/h.",
    "h7 plays a 50-metre pass to h9 at 31kmh.",
    "h7 plays a 50 meter pass to h9 at 31 kilometres per hour.",
    "h7 plays a 50 metre pass to h9 at 31 kilometers an hour.",
    "h7 plays a 50 m pass to h9 at 31 k.p.h.",
])
def test_a_number_in_our_units_passes(text):
    assert check(Claim(text, ["p31"]), {"p31": LONG}).ok


def test_a_speed_in_k_p_h_is_read_as_a_speed():
    # 50 is the cited distance, so read bare it passed.
    verdict = check(Claim("h7 plays a pass at 50 k.p.h. to h9.", ["p31"]), {"p31": LONG})
    assert verdict.reasons == ["number 50 is not a cited ball_speed_kmh"]


@pytest.mark.parametrize("text, number", [
    ("h7 finds h9 in the six-yard box.", "6"),
    ("h7 finds h9 at the edge of the 18-yard box.", "18"),
    ("h7 places it on the 12-yard spot for h9.", "12"),
])
def test_a_pitch_marking_in_yards_is_checked_as_before(text, number):
    # A marking's name is no measurement in an unpublished unit: its number is read bare, as on main.
    verdict = check(Claim(text, ["p31"]), {"p31": LONG})
    assert verdict.reasons == [f"number {number} is not in the cited evidence"]


def test_a_unit_glued_with_a_hyphen_is_read_as_its_field():
    # "a 2-metre pass" was read as a bare 2, which the cited minute let through.
    verdict = check(Claim("h7 plays a 2-metre pass to h9.", ["p31"]), {"p31": LONG})
    assert verdict.reasons == ["number 2 is not a cited distance_m"]




@pytest.mark.parametrize("text, reason", [
    ("h7's 30 m pass finds h9.", "number 30 is not a cited distance_m of h7"),
    ("h7's crisp low 70 km/h pass finds h9.", "number 70 is not a cited ball_speed_kmh of h7"),
    ("h7 plays a 30 m pass to h9.", "number 30 is not a cited distance_m of h7"),
    ("h4 hits a 40 km/h ball to h7.", "number 40 is not a cited ball_speed_kmh of h4"),
    ("h7, whose 30 m pass found h9, was found by h4.", "number 30 is not a cited distance_m of h7"),
    ("h4 found h7. Then h7 sent his 30 m pass on.", "number 30 is not a cited distance_m of h7"),
    ("h7 pasa el balón 30 metros a h9.", "number 30 is not a cited distance_m of h7"),
    ("h7's thirty m pass finds h9.", "number 30 is not a cited distance_m of h7"),
    # Review of #257: "de" broke the gap, and only the first number after the verb was bound
    ("h7 juega un pase de 30 metros a h9.", "number 30 is not a cited distance_m of h7"),
    ("h7 plays a 12 m pass at 70 km/h to h9.", "number 70 is not a cited ball_speed_kmh of h7"),
    ("h7 plays a 12 m, 70 km/h pass to h9.", "number 70 is not a cited ball_speed_kmh of h7"),
    ("h7 plays a delightful curling 30 m pass to h9.", "number 30 is not a cited distance_m of h7"),
    ("h7 plays a 12 m pass. His 70 km/h ball finds h9.", "number 70 is not a cited ball_speed_kmh of h7"),
    # the dots of "k.p.h." end no clause (second review of #257)
    ("h7 plays a 12 m pass at seventy k.p.h.", "number 70 is not a cited ball_speed_kmh of h7"),
])
def test_a_number_bound_to_a_player_must_be_from_his_cited_event(text, reason):
    # Each number is in the evidence, so the old check passed them all: it is the other pass's.
    verdict = check(Claim(text, ["p1", "p2"]), TWO)
    assert verdict.reasons == [reason]


@pytest.mark.parametrize("text", [
    "h7's 12 m pass finds h9, and h4's 30 m pass found h7.",
    "h7 plays a 12 m pass at 40 km/h to h9; h4 hit a 70 km/h ball to h7.",
    "h7, whose 12 m pass found h9, was found by h4.",
    "h4 found h7. Then h7 sent his 12 m pass on.",
    "h4 finds h7 with his 30 m pass.",  # two players named: "his" binds nothing
    "h7 pasa el balón 12 metros a h9.",
    "A 30 m pass from h4 finds h7, who plays 12 m to h9.",  # "from h4" and "who" bind nothing
    "h9 meets h7's 12 m pass.",
    "h4 finds h7, who plays his 12 m pass to h9.",  # three players named: "his" binds nothing
    "h7 da un pase de 12 metros a h9, y h4 juega una pelota de 30 metros a h7.",  # articles, not 1
    "h7 plays a 12 m pass. His 40 km/h ball finds h9.",  # "his" is h7, named before it
    "h7 juega un pase de 12 metros a h9.",
    "h7 plays a 12 m pass at 40 km/h to h9, and h4 plays a 30 m pass at 70 km/h to h7.",
    "h7 plays a delightful curling 12 m pass to h9.",
    # second review of #257: a possessive binds its own noun phrase only, and a verb's clause ends at
    # ";" and at "and"
    "h4 receives h7's 12 m pass and plays a 30 m pass.",
    "h9 meets h7's 12 m pass at the end of a 30 m move.",
    "h7 plays a 12 m pass; a 30 m ball follows.",
    "h7 plays a 12 m pass and then a 30 m ball comes back.",
    # each clause ender on its own (review of #268: "but", "then" and their Spanish forms were unpinned)
    "h7 plays a 12 m pass, but a 30 m ball comes back.",
    "h7 plays a 12 m pass, then a 30 m ball comes back.",
    "h7 juega un pase de 12 m, pero un balón de 30 m vuelve.",
    "h7 juega un pase de 12 m, luego un balón de 30 m vuelve.",
    "h7 juega un pase de 12 m y un balón de 30 m vuelve.",
])
def test_a_number_bound_to_its_own_player_passes(text):
    assert check(Claim(text, ["p1", "p2"]), TWO).ok


def test_a_number_bound_to_a_player_may_be_a_fact_scoped_to_him():
    assert check(Claim("h7's 151 m so far, at up to 27.3 km/h.", [RUN["id"], SPEED["id"]]), FACTS).ok
    other = {**RUN, "id": "a7run", "scope": "player:a7:window:0.00-95.20", "value": 90.0}
    verdict = check(Claim("h7's 90 m so far.", [RUN["id"], "a7run"]), {**FACTS, "a7run": other})
    assert verdict.reasons == ["number 90 is not a cited distance_m of h7"]


# Kian's blind labels (docs/eval/factcheck-human-labels.md): words about play a cited fact must show.
def _play(eid, clock, type_, team, player, **more):
    minute, second = 2 if clock < "02:00" else 3, int(clock[-2:])
    return {"id": eid, "minute": minute, "second": second, "clock": clock, "type": type_, "team": team,
            "player": player, **more}


PLAY = {e["id"]: e for e in (
    _play("p1", "01:33", "pass", "home", "h7", intended="h9", interceptor="a8", outcome="fail",
          distance_m=21, ball_speed_kmh=51),
    _play("i1", "01:35", "interception", "away", "a8"),
    _play("p2", "01:37", "pass", "away", "a8", receiver="a10", intended="a10", outcome="success",
          distance_m=12, ball_speed_kmh=40),
    _play("lb", "02:05", "pass", "home", "h4", receiver="h9", intended="h9", outcome="success",
          distance_m=32, ball_speed_kmh=80),
    _play("pr", "02:04", "pressure", "away", "a6", receiver="h4"),
    # another player's interception after a pass cut out by a8: a second act
    _play("i2", "01:36", "interception", "home", "h3"),
    # h7's earlier pass, completed: a different act from the one a8 cut out
    _play("p0", "01:20", "pass", "home", "h7", receiver="h9", intended="h9", outcome="success",
          distance_m=10, ball_speed_kmh=35),
)}


@pytest.mark.parametrize("text, evidence, reason", [
    # L19: the interception is that very pass being cut out, and 21 m is no long ball
    ("The interception by a8 at 01:35 came immediately after h7's failed pass at 01:33.", ["p1", "i1"],
     "one act, not one after the other"),
    ("h7's pass at 01:33 came before a8's interception at 01:35.", ["p1", "i1"], "one act, not one before"),
    # the connective opening the sentence, and every form of it (review of #353)
    ("After h7's failed pass, a8 intercepts the ball.", ["p1", "i1"], "one act, not one after"),
    ("Following h7's pass, a8 cuts it out.", ["p1", "i1"], "one act, not one following"),
    ("h7's pass was followed by a8's interception.", ["p1", "i1"], "one act, not one followed by"),
    ("a8's interception was preceded by h7's pass.", ["p1", "i1"], "one act, not one preceded by"),
    ("The interception came after a8 cut out h7's pass.", ["p1", "i1"], "one act, not one after"),
    ("h7's failed long pass at 01:33 is cut out by a8.", ["p1"], "a long ball is a pass of 32 m or more"),
    # L16: pressure said with no cited pressure event
    ("h4 plays a 32 m pass to h9 despite pressure.", ["lb"], "no cited event is a pressure event"),
    ("h4, under heavy pressure, finds h9 with a 32 m pass.", ["lb"], "no cited event is a pressure event"),
    ("h4 is pressured but finds h9 with a 32 m pass.", ["lb"], "no cited event is a pressure event"),
    ("Amid pressure, h4 finds h9 with a 32 m pass.", ["lb"], "no cited event is a pressure event"),
])
def test_a_claim_about_the_play_needs_a_cited_fact_that_shows_it(text, evidence, reason):
    verdict = check(Claim(text, evidence), PLAY)
    assert not verdict.ok and any(reason in r for r in verdict.reasons), verdict.reasons


@pytest.mark.parametrize("text, evidence", [
    ("h7's pass at 01:33 is cut out by a8, who then finds a10.", ["p1", "i1", "p2"]),  # "then": a new act
    ("After the interception, a8 finds a10.", ["i1", "p2"]),  # two acts, in order
    ("h4 plays a long ball to h9.", ["lb"]),  # 32 m is a long ball
    ("h4 finds h9 with a 32 m pass despite pressure from a6.", ["lb", "pr"]),  # the pressure is cited
    ("a8 finds a10 with a 12 m pass.", ["p2"]),
    ("h7's pass is cut out by a8, then a8 passes to a10.", ["p1", "i1", "p2"]),  # "then" orders two acts
    ("h3's interception came after h7's failed pass.", ["p1", "i2"]),  # another player's: a second act
    # the interceptor's own next pass is a second act, whatever comes first in the sentence
    ("a8 passes to a10 after intercepting h7's pass.", ["p1", "i1", "p2"]),
    ("After winning the ball, a8 passes to a10.", ["i1", "p2"]),
    ("After h7's pass to h9, a8 intercepts h7's next pass.", ["p0", "p1", "i1"]),  # two passes by h7
    ("After the interception, a8 passes to a10.", ["p1", "i1", "p2"]),  # the pass after is a8's own
])
def test_play_words_with_their_fact_cited_still_pass(text, evidence):
    assert check(Claim(text, evidence), PLAY).ok, check(Claim(text, evidence), PLAY).reasons
