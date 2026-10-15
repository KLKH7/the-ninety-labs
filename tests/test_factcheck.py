from ninety.agents.factcheck import Claim, check
from ninety.match.facts import events_in

EVENTS = events_in(7, 5, 1, 5)
KNOWN = {e["id"]: e for e in EVENTS}
PASS = next(e for e in EVENTS if e["type"] == "pass" and "distance_m" in e)


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


def test_clock_seconds_are_checked_against_second_field():
    """Planted defect: the right minute with a wrong second must fail."""
    wrong = (PASS["second"] + 7) % 60
    verdict = check(Claim(f"A pass at {PASS['minute']}:{wrong:02d}.", [PASS["id"]]), KNOWN)
    assert not verdict.ok and "second" in verdict.reasons[0]


def test_wrong_minute_in_clock_form_is_rejected():
    """Planted defect: the minute before the colon must be checked too."""
    wrong = PASS["minute"] + 87
    verdict = check(Claim(f"A pass at {wrong}:{PASS['second']:02d}.", [PASS["id"]]), KNOWN)
    assert not verdict.ok
    assert "minute" in verdict.reasons[0]


def test_clock_with_the_right_minute_and_second_passes():
    text = f"A pass at {PASS['minute']}:{PASS['second']:02d}."
    assert check(Claim(text, [PASS["id"]]), KNOWN).ok


def test_player_in_no_known_event_is_still_rejected():
    """Planted defect: a squad player absent from every event must not slip through."""
    involved = {v for e in EVENTS for v in (e["player"], e.get("receiver")) if v}
    absent = next(f"{t}{n}" for t in "ha" for n in range(1, 12) if f"{t}{n}" not in involved)
    verdict = check(Claim(f"{absent} starts the move.", [PASS["id"]]), KNOWN)
    assert not verdict.ok
    assert absent in verdict.reasons[0]
