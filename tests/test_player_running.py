"""A named player's running: distance, top speed, sprints and zone (GROUNDING I22)."""

import pytest

from ninety.agents import companion_match as cm
from ninety.intel import physical


def frames(xs, track="h-t1", team="home", y=34.0):
    """One frame a second with the track at x."""
    return [{"frame": 25 * k, "t": float(k), "players": [{"id": track, "team": team, "x": x, "y": y}]}
            for k, x in enumerate(xs)]


def test_a_sprint_is_a_second_or_more_above_the_threshold():
    fast = 25.2 / 3.6 + 0.1  # m/s just past the threshold
    xs = [0.0]
    for v in (2, fast, fast, 2, fast, 2):  # two runs: one of 2 s, one of 1 s
        xs.append(xs[-1] + v)
    rows = physical.rows(frames(xs))
    assert sum(r["sprints"] for r in rows) == 2
    assert max(r["top_kmh"] for r in rows) == pytest.approx(fast * 3.6, abs=0.1)


def test_a_jump_is_a_track_switching_players_not_running():
    rows = physical.rows(frames([0.0, 2.0, 30.0, 32.0]))  # 28 m in a second
    assert sum(r["m"] for r in rows) == pytest.approx(4.0)
    assert sum(r["sprints"] for r in rows) == 0


def test_a_named_players_pieces_of_track_are_one_player_and_unnamed_tracks_are_left_out():
    a = physical.rows(frames([0.0, 5.0, 10.0], track="h-t1"))
    b = physical.rows(frames([50.0, 55.0, 60.0, 65.0], track="h-t2"))
    c = physical.rows(frames([0.0, 9.0], track="h-t3"))
    people = {"h-t1": {"team": "home", "name": "Kai Terrow"}, "h-t2": {"team": "home", "name": "Kai Terrow"},
              "h-t3": {"team": "home", "name": None}}
    got = {r["metric"]: r for r in physical.players(a + b + c, people, 1, 90)}
    assert got["player_km"]["value"] == round((10 + 15) / 1000, 1)
    assert {r["player_is"] for r in physical.players(a + b + c, people, 1, 90)} == {"Kai Terrow"}


def test_the_sentences_say_the_label_and_the_threshold():
    km = {"metric": "player_km", "player_is": "Kai Terrow", "value": 2.4, "minute_from": 1, "minute_to": 20,
          "within_pct": 21, "confident": True}
    assert cm.code_texts(km) == [
        "Kai Terrow has covered 2.4 km from minute 1 to minute 20, from the footage shown, give or take 21%."
    ]
    none = {"metric": "player_sprints", "player_is": "Kai Terrow", "value": 0, "minute_from": 1,
            "minute_to": 20, "confident": True}
    assert cm.code_texts(none) == ["Kai Terrow did not sprint above 25.2 km/h from minute 1 to minute 20."]


@pytest.mark.parametrize(
    "said, ok",
    [
        ("sprinted 2 times above 25.2 km/h", True),
        ("sprinted 3 times above 25.2 km/h", False),
        ("sprinted 2 times above 30 km/h", False),
        ("sprinted 25.2 times above 2 km/h", False),
        ("bravely sprinted 2 times above 25.2 km/h", False),
    ],
)
def test_a_sprint_sentence_binds_the_count_and_the_threshold(said, ok):
    from ninety.agents.factcheck import Claim
    from ninety.agents.insight_check import verify
    from ninety.intel.teamsheet import Fixture

    fx = Fixture(7, "OAK", "FEN")
    lb = fx.sheet("home")[4]
    fast = 25.2 / 3.6 + 0.1
    xs = [0.0]
    for v in (2, fast, fast, 2, fast, 2):
        xs.append(xs[-1] + v)
    people = {
        "h-t5": {"track": "h-t5", "team": "home", "name": lb.name, "role": "LB", "position": "left-back",
                 "sheet_name": lb.name, "say": lb.name}
    }
    got = physical.players(physical.rows(frames(xs, track="h-t5")), people, 1, 90)
    fact = {**next(r for r in got if r["metric"] == "player_sprints"), "club": "London Athletic"}
    assert fact["value"] == 2
    names = [s.name for t in ("home", "away") for s in fx.sheet(t)]
    claim = Claim(f"{lb.name} {said} from minute 1 to minute 90.", [fact["id"]])
    v = verify(claim, {fact["id"]: fact}, fx.clubs, people, names)
    assert v.ok is ok, v.reasons


@pytest.mark.parametrize("q", ["Who has covered the most distance?", "Who is the fastest player?",
                               "How many sprints has Kai Terrow made?"])
def test_running_questions_route_to_the_physical_tool(q):
    assert "physical" in cm.route(q)
