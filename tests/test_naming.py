"""Naming tracked players from the whole-pitch tracks (ninety/intel/naming.py)."""

from __future__ import annotations

import random

from ninety.intel import naming
from ninety.intel.match_insights import MatchInsights
from ninety.intel.roles import TEMPLATE
from ninety.intel.teamsheet import ROLES, Fixture

FX = Fixture(8080, "LON", "LIS")
OPEN = {"share": 0.5, "seconds": 2.0, "association": 0.75}


def _place(team: str, role: str, rng: random.Random) -> tuple[float, float]:
    d, across = TEMPLATE[role]
    x, y = d + rng.gauss(0, 0.5), across + rng.gauss(0, 0.5)
    return (x, y) if team == "home" else (105.0 - x, 68.0 - y)


def frames(seconds: float = 20.0, segment: int = 0, extra: bool = False, swap_keeper: bool = False):
    """A segment's tracked frames: every player of both sides holding his 4-3-3 place, track id
    h-t<k*1000 + slot> (slot 1 the keeper), optionally an extra short-lived home track."""
    rng = random.Random(segment)
    out = []
    base = segment * 1000
    for i in range(int(seconds * 25)):
        players = []
        for team in ("home", "away"):
            for n, role in enumerate(ROLES, 1):
                x, y = _place(team, role, rng)
                side = team
                if swap_keeper and role == "GK":
                    side = "away" if team == "home" else "home"
                players.append({"id": f"{side[0]}-t{base + n + (0 if team == 'home' else 50)}",
                                "team": side, "x": x, "y": y})
        if extra:
            x, y = _place("home", "ST", rng)
            players.append({"id": f"h-t{base + 99}", "team": "home", "x": x + 1, "y": y})
        out.append({"frame": segment * 10000 + i, "t": (segment * 10000 + i) / 25, "source": "tracked",
                    "ball": {"x": 52.5, "y": 34.0, "z": 0.0}, "players": players})
    return out


def test_each_track_named_for_its_slot():
    people = naming.people(frames(), FX, OPEN)
    sheet = {s.role: s.name for s in FX.sheet("home")}
    for n, role in enumerate(ROLES, 1):
        assert people[f"h-t{n}"]["name"] == sheet[role]


def test_no_calibration_names_nobody_and_says_the_club():
    people = naming.people(frames(), FX, {"share": None, "seconds": None, "association": None})
    assert not any(w["name"] for w in people.values())
    assert people["h-t3"]["say"] == "a London Athletic player"
    assert all("-t" not in w["say"] for w in people.values())


def test_more_than_eleven_tracks_still_vote_and_extra_gets_no_slot_it_did_not_win():
    voted = naming.votes(frames(extra=True), "home", naming.roles.places(frames(), "home"))
    assert voted, "frames with twelve home tracks are not skipped"
    assert all(len(got) == len(ROLES) for _, _, got in voted)  # eleven roles, one track each


def test_two_tracks_never_share_a_slot_at_once():
    people = naming.people(frames(extra=True), FX, OPEN)
    named = [w["name"] for t, w in people.items() if w["team"] == "home" and w["name"]]
    assert len(named) == len(set(named))


def test_keep_apart_keeps_the_heaviest_non_overlapping_set():
    claims = [("a", 0.0, 10.0, 5), ("b", 5.0, 15.0, 8), ("c", 11.0, 20.0, 4)]
    assert naming.keep_apart(claims) == {"a", "c"}  # 9 beats b's 8
    assert naming.keep_apart([("a", 0.0, 10.0, 5), ("b", 5.0, 15.0, 6)]) == {"b"}


def test_a_keeper_read_as_the_other_side_puts_the_segment_in_doubt():
    assert naming.side_doubt(frames()) == set()
    assert naming.side_doubt(frames(swap_keeper=True)) == {0}
    people = naming.people(frames(swap_keeper=True), FX, OPEN)
    assert not any(w["name"] for w in people.values())


def test_names_cross_the_join_only_above_the_gate_and_on_the_same_side():
    tactical = naming.people(frames(), FX, OPEN)
    association = {
        "h-t7": {"track": "h-t2", "confidence": 1.0},  # the broadcast's h-t7 is the tactical h-t2
        "h-t8": {"track": "h-t3", "confidence": 0.5},  # below the gate
        "a-t9": {"track": "h-t4", "confidence": 1.0},  # the cameras disagree on the side
        "h-t10": {"track": None, "confidence": 0.0},
    }
    b = naming.broadcast_people(association, tactical, FX, OPEN)
    assert b["h-t7"]["name"] == tactical["h-t2"]["name"] and b["h-t7"]["name"] != tactical["h-t7"]["name"]
    assert b["h-t8"]["name"] is None and b["a-t9"]["name"] is None and b["h-t10"]["name"] is None
    assert b["h-t8"]["say"] == "a London Athletic player"
    assert [r["id"] for r in naming.lineup(b)] == ["h-t7"]


def test_events_move_to_their_tactical_tracks_or_to_none():
    association = {"h-t7": {"track": "h-t2", "confidence": 1.0}, "h-t8": {"track": "h-t3", "confidence": 0.5}}
    ev = naming.tactical_events(
        [{"type": "pass", "player": "h-t7", "receiver": "h-t8"}], association, OPEN)
    assert ev == [{"type": "pass", "player": "h-t2", "receiver": None}]


def test_match_insights_lists_the_broadcast_lineup():
    association = {"h-t7": {"track": "h-t2", "confidence": 1.0}}
    mi = MatchInsights.build("c", frames(), [], FX, gate=OPEN, association=association)
    body = mi.as_dict()
    assert [r["id"] for r in body["lineup"]] == ["h-t7"]
    assert body["lineup"][0]["name"] == mi.people["h-t2"]["name"]
    assert MatchInsights.from_dict(body).broadcast == mi.broadcast
