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


def _standin():
    import json

    from ninety.eval.companion_tools import STANDIN
    from ninety.intel.match_insights import MatchInsights

    return MatchInsights.from_dict(json.loads(STANDIN.read_text()))


def test_named_players_running_is_held_while_its_grading_is_worse_than_team_distances():
    # docs/eval/physical.md: the name rule leaves pieces of a player's track unnamed, so his distance
    # can miss most of his running (±87% today, against team distance's ±21%).
    mi = _standin()
    facts = mi.physical(1, mi.minutes)["facts"]
    held = [f for f in facts if f["metric"] in ("player_km", "player_top_kmh", "player_sprints")]
    assert held and all(not f["confident"] and f["why_held"] for f in held)
    assert all(cm.code_texts(f) == [] for f in held)
    assert all(f["confident"] for f in facts if f["metric"] == "player_zone")


def test_the_gate_opens_when_named_players_are_measured_well_enough(monkeypatch):
    mi = _standin()
    good = {"distance_pct": 10, "top_kmh": 1, "sprints_pct": 10}
    monkeypatch.setattr(physical, "labels", lambda: good)
    km = next(f for f in mi.physical(1, mi.minutes)["facts"] if f["metric"] == "player_km")
    assert km["confident"] and km["within_pct"] == 10 and km["also"] == [[10, "%"]]


def test_a_players_top_speed_is_the_fastest_of_his_pieces_not_their_sum():
    a = physical.rows(frames([0.0, 5.0, 10.0], track="h-t1"))
    b = physical.rows(frames([50.0, 57.0, 64.0], track="h-t2"))
    people = {"h-t1": {"team": "home", "name": "Kai Terrow"}, "h-t2": {"team": "home", "name": "Kai Terrow"}}
    top = next(r for r in physical.players(a + b, people, 1, 90) if r["metric"] == "player_top_kmh")
    assert top["value"] == pytest.approx(7.0 * 3.6, abs=0.1)


def test_the_zone_is_where_his_own_team_attacks():
    # x = 95 is home's final third, away's own third.
    home = physical.rows(frames([95.0, 95.5, 96.0], track="h-t1", team="home"))
    away = physical.rows(frames([95.0, 95.5, 96.0], track="a-t1", team="away"))
    people = {
        "h-t1": {"team": "home", "name": "Kai Terrow"},
        "a-t1": {"team": "away", "name": "Zane Kirrick"},
    }
    got = physical.players(home + away, people, 1, 90)
    zones = {r["team"]: r["third"] for r in got if r["metric"] == "player_zone"}
    assert zones == {"home": "final", "away": "own"}


@pytest.mark.parametrize(
    "fact, said",
    [
        ({"metric": "player_sprints", "value": 4, "unit": "times", "also": [[25.2, "km/h"]]},
         "did not sprint above 25.2 km/h from minute 1 to minute 21."),
        ({"metric": "player_zone", "value": None, "unit": None, "third": "own", "channel": "right"},
         "was most often in their final third on the left from minute 1 to minute 21."),
    ],
)
def test_a_zero_or_a_zone_is_said_only_as_the_fact_has_it(fact, said):
    from ninety.agents.factcheck import Claim
    from ninety.agents.insight_check import verify
    from ninety.intel.teamsheet import Fixture

    fx = Fixture(7, "OAK", "FEN")
    lb = fx.sheet("home")[4]
    who = {"track": "h-t5", "team": "home", "name": lb.name, "role": "LB", "position": "left-back",
           "sheet_name": lb.name, "say": lb.name}
    people = {"h-t5": who}
    f = {"id": "x", "kind": "running", "team": "home", "club": "London Athletic", "player": "h-t5",
         "player_is": lb.name, "minute_from": 1, "minute_to": 21, "confident": True, **fact}
    names = [s.name for t in ("home", "away") for s in fx.sheet(t)]
    assert not verify(Claim(f"{lb.name} {said}", ["x"]), {"x": f}, fx.clubs, people, names).ok


# The merge queue's fourth review of #323: the guard was a word list, so other phrasings still got the
# zone with a name in the headline. Code now gates on what is asked.
UNASKED_FIGURES = [
    "How far has Kai Terrow run?", "Who is the fastest player?", "How many sprints?",
    "Who looks most tired?", "Who has the best work rate?", "Who has run the most?",
    "Who ran the furthest?", "Who has run the furthest?", "How many km has Kai done?",
]


@pytest.mark.parametrize("q", UNASKED_FIGURES)
def test_a_held_figure_asked_for_is_not_available_never_another_answer(q):
    # The merge queue's third review of #323: a distance question was answered with the zone.
    from ninety.agents.contracts import Question

    mi = _standin()
    a, calls = cm.code_match_answer(Question("s", None, q, 60.0 * 20 - 1), mi)
    assert "physical" in [c["name"] for c in calls]
    assert a.status == "unanswerable" and "isn't available yet" in a.text and a.headline is None


def test_each_figure_is_held_on_its_own_label():
    bar = 21
    held = physical.held({"distance_pct": 10, "sprints_pct": 30, "top_kmh": 2}, bar)
    assert set(held) == {"player_sprints"}
    worse_top = physical.TOP_SPEED_BAR_KMH + 1
    held = physical.held({"distance_pct": 30, "sprints_pct": 10, "top_kmh": worse_top}, bar)
    assert set(held) == {"player_km", "player_top_kmh"}
    assert set(physical.held({"distance_pct": 30, "sprints_pct": 10, "top_kmh": 1}, bar)) == {"player_km"}


def test_the_zone_says_it_is_of_the_footage_the_video_named_him_in():
    z = {"metric": "player_zone", "player_is": "Kai Terrow", "third": "own", "channel": "right",
         "minute_from": 1, "minute_to": 20, "confident": True}
    assert cm.code_texts(z) == [
        "Kai Terrow was most often in their own third on the right from minute 1 to minute 20, in the "
        "footage the video named him in."
    ]


def _zone_reply(mi, q, who=None):
    """A model that plans the physical tool and answers with a zone sentence (the first, or who's)."""
    import asyncio
    import json

    from ninety.agents.contracts import Question

    zone = next(
        f for f in mi.physical(6, 20)["facts"]
        if f["metric"] == "player_zone" and who in (None, f["player_is"])
    )
    replies = [
        json.dumps({"tools": [{"name": "physical", "minute_from": 6, "minute_to": 20}]}),
        json.dumps({"text": cm.code_texts(zone)[0], "evidence": [zone["id"]]}),
    ]

    async def ask(prompt):
        return replies.pop(0)

    return asyncio.run(cm.answer_match(Question("s", None, q, 60.0 * 20 - 1), mi, ask))


@pytest.mark.parametrize("q", UNASKED_FIGURES)
def test_the_model_answering_a_held_figure_with_the_zone_falls_back_to_not_available(q):
    r = _zone_reply(_standin(), q)
    assert r.source == "code"
    assert r.answer.status == "unanswerable" and "isn't available yet" in r.answer.text
    assert r.answer.headline is None


@pytest.mark.parametrize(
    "q, who",
    [("Where did Theo Cindell play?", "Theo Cindell"), ("Where has Theo been playing?", "Theo Cindell"),
     ("Where has London Athletic's left-back been playing?", None)],
)
def test_a_question_of_place_about_one_player_gets_his_zone(q, who):
    from ninety.agents.contracts import Question

    mi = _standin()
    a, calls = cm.code_match_answer(Question("s", None, q, 60.0 * 20 - 1), mi)
    assert "physical" in [c["name"] for c in calls]
    assert a.status == "verified" and "most often in their" in a.text
    who = who or a.text.split(" was most often")[0]
    assert a.text.startswith(who)
    assert _zone_reply(mi, q, who).source == "model"
    # the model telling another player's zone is refused: code answers about the one asked
    other = next(f["player_is"] for f in mi.physical(6, 20)["facts"]
                 if f["metric"] == "player_zone" and f["player_is"] != who)
    r = _zone_reply(mi, q, other)
    assert r.source == "code" and r.answer.text.startswith(who)


# The merge queue's delta review of #323: a side alone leaked into the zone, and a question naming
# a player (or several, or none) got another player's zone.
@pytest.mark.parametrize(
    "q, says",
    [
        ("Show me the heat map", "Name a player"),
        ("Where does Alex play?", "More than one player fits"),
        ("Where has the left-back been playing?", "More than one player fits"),
        ("Where does Kai play?", "Name a player"),
        ("Who is on the left?", "isn't available yet"),
        ("How much has the left back done?", "isn't available yet"),
        ("Who is out of position?", "isn't available yet"),
    ],
)
def test_the_zone_is_never_another_players_or_an_answer_to_a_side(q, says):
    r = _zone_reply(_standin(), q)
    assert r.source == "code" and r.answer.status == "unanswerable" and says in r.answer.text
    assert r.answer.headline is None


def test_the_top_speed_bar_is_the_worst_measured_track_on_the_clip():
    import json
    from pathlib import Path

    d = json.loads(Path("docs/eval/companion-tracked.json").read_text())
    assert physical.TOP_SPEED_BAR_KMH == d["by_smoothing"]["25"]["peak_kmh"]["max"]


@pytest.mark.parametrize(
    "q, metric, pick",
    [
        ("Who is the fastest player?", "player_top_kmh", max),
        ("Who has made the most sprints?", "player_sprints", max),
        ("Who has covered the most distance?", "player_km", max),
    ],
)
def test_once_a_figure_is_said_its_question_gets_that_figure_at_its_highest(monkeypatch, q, metric, pick):
    # The latent gap of the fourth review: with good labels, "fastest" got the distance sentence and
    # the first player by distance, not the fastest.
    from ninety.agents.contracts import Question

    mi = _standin()
    monkeypatch.setattr(physical, "labels", lambda: {"distance_pct": 10, "top_kmh": 1, "sprints_pct": 10})
    a, calls = cm.code_match_answer(Question("s", None, q, 60.0 * 20 - 1), mi)
    [c] = [c for c in calls if c["name"] == "physical"]
    rows = [f for f in mi.physical(c["minute_from"], c["minute_to"])["facts"] if f["metric"] == metric]
    assert a.status == "verified"
    [cited] = [f for f in rows if f["id"] in a.evidence]
    assert cited["value"] == pick(f["value"] for f in rows)


def test_with_only_top_speed_said_the_fastest_is_the_maximum_and_not_the_distance_sentence(monkeypatch):
    from ninety.agents.contracts import Question

    mi = _standin()
    monkeypatch.setattr(physical, "labels", lambda: {"distance_pct": 90, "top_kmh": 1, "sprints_pct": 90})
    a, calls = cm.code_match_answer(Question("s", None, "Who is the fastest player?", 60.0 * 20 - 1), mi)
    [c] = [c for c in calls if c["name"] == "physical"]
    facts = mi.physical(c["minute_from"], c["minute_to"])["facts"]
    rows = [f for f in facts if f["metric"] == "player_top_kmh"]
    assert a.status == "verified" and "km/h" in a.text
    [cited] = [f for f in rows if f["id"] in a.evidence]
    assert cited["value"] == max(f["value"] for f in rows)
    # a model answering "fastest" with a zone sentence is refused, even though the zone is true
    r = _zone_reply(mi, "Who is the fastest player?")
    assert r.source == "code" and any("player_top_kmh; it cites another" in x for x in r.reasons)


@pytest.mark.parametrize("q", ["Who has been the best player?", "Who is working hardest?"])
def test_a_question_asking_no_place_is_never_answered_with_the_zone(q):
    # A model may plan the physical tool for a question that names no figure and no place: while
    # every running figure is held, the zone is not its answer.
    r = _zone_reply(_standin(), q)
    assert r.source == "code" and r.answer.headline is None and "most often in" not in r.answer.text
    if q == "Who has been the best player?":
        # Lesson 297 (Kian's voice): the intent table's best row answers with the closest measured fact,
        # whose passes took out more opponents, cited, never the zone and never a "can't".
        assert r.answer.status == "verified" and any(e.startswith("ask:bypassed") for e in r.answer.evidence)
        assert "opponents out of the game" in r.answer.text and "can't" not in r.answer.text
    else:
        assert r.answer.status == "unanswerable"


def test_once_a_figure_is_said_a_question_asking_no_figure_and_no_place_is_still_not_answered(monkeypatch):
    monkeypatch.setattr(physical, "labels", lambda: {"distance_pct": 10, "top_kmh": 1, "sprints_pct": 10})
    r = _zone_reply(_standin(), "Who has been the best player?")
    # Lesson 297: the best row's closest measured fact (whose passes took out more opponents), never a
    # running figure or the zone, even once a figure is said.
    assert r.source == "code" and any(e.startswith("ask:bypassed") for e in r.answer.evidence)
    assert "km" not in r.answer.text and "most often in" not in r.answer.text


@pytest.mark.parametrize("who", ["Alex Gumble", "Alex Purrow", "Mateo Vinnet", "Ilya Sarrow"])
def test_a_full_name_is_that_player_even_when_others_share_his_first_name(who):
    # The merge queue's review of #323: "Where does Alex Gumble play?" listed all three Alexes.
    from ninety.agents.contracts import Question

    mi = _standin()
    first = who.split()[0]
    assert sum(n.split()[0] == first for n in mi.sheet_names()) > 1
    q = f"Where does {who} play?"
    a, _ = cm.code_match_answer(Question("s", None, q, 60.0 * 20 - 1), mi)
    assert a.status == "verified" and a.text.startswith(f"{who} was most often")
    assert _zone_reply(mi, q, who).source == "model"
