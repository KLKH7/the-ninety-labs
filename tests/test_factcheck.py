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


def test_an_ordinal_minute_must_be_the_cited_minute():
    # "the 9th minute" was never read as a number, so any ordinal passed (lesson 94).
    minute = CLOCK_EVENT["minute"]
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(minute, "th")
    assert check(Claim(f"A pass in the {minute}{suffix} minute.", [CLOCK_EVENT["id"]]), KNOWN).ok
    wrong = check(Claim(f"A pass in the {minute + 7}th minute.", [CLOCK_EVENT["id"]]), KNOWN)
    assert not wrong.ok
    assert wrong.reasons == [f"number {minute + 7}th is not a cited minute"]


def test_an_ordinal_count_must_be_in_the_evidence():
    verdict = check(Claim(f"{PASS['player']} plays his 97th pass.", [PASS["id"]]), KNOWN)
    assert verdict.reasons == ["number 97th is not in the cited evidence"]
