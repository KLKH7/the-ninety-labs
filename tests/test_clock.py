from ninety.match.clock import match_clock
from ninety.match.facts import events_in


def test_match_clock_floors_elapsed_time():
    cases = {
        0: "00:00",
        59.6: "00:59",
        59.999: "00:59",
        60.0: "01:00",
        87.84: "01:27",
        5400.0: "90:00",
        5999.0: "99:59",
        6000.0: "100:00",
    }
    for seconds, expected in cases.items():
        assert match_clock(seconds) == expected


def test_agent_events_use_the_same_clock_as_the_scorebug():
    for event in events_in(7, 30, 1, 30):
        minute, second = event["clock"].split(":")
        assert 0 <= event["second"] <= 59
        assert event["clock"] == match_clock(event["minute"] * 60 + event["second"] - 60)
        assert int(minute) == event["minute"] - 1
        assert int(second) == event["second"]
