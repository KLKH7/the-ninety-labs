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
    h-t<k*1000 + slot> (slot 1 the keeper), optionally an extra home track all clip long."""
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


def test_segments_are_separate_and_doubt_withholds_only_its_own():
    fr = frames(segment=0) + frames(segment=1, swap_keeper=True)
    assert naming.segment("h-t1003") == 1 and naming.segment("h-t3") == 0
    assert naming.side_doubt(fr) == {1}
    people = naming.people(fr, FX, OPEN)
    assert all(people[f"h-t{n}"]["name"] for n in range(1, 12))
    assert not any(w["name"] for t, w in people.items() if naming.segment(t) == 1)


def test_doubt_needs_more_than_half_the_frames():
    fr = frames(seconds=4.0)
    keeper = [p for f in fr for p in f["players"] if p["id"] == "h-t1"]
    for p in keeper[: len(keeper) // 2]:
        p["x"] = 40.0  # out of his area in exactly half the frames: no doubt
    assert naming.side_doubt(fr) == set()
    keeper[len(keeper) // 2]["x"] = 40.0
    for f in fr[len(fr) // 2 : len(fr) // 2 + 10]:
        next(p for p in f["players"] if p["id"] == "h-t1")["x"] = 40.0
    assert naming.side_doubt(fr) == {0}


def test_a_fragment_beaten_to_its_slot_is_not_named_and_the_longer_track_keeps_it():
    fr = frames(seconds=30.0)
    for f in fr[375:]:  # the striker's track ends at 15 s; another track carries him on
        for p in f["players"]:
            if p["id"] == "h-t10":
                p["id"] = "h-t40"
    for f in fr[300:375]:  # and for the 3 s before, a duplicate of him overlaps the first
        p = next(p for p in f["players"] if p["id"] == "h-t10")
        f["players"].append({**p, "id": "h-t41", "x": p["x"] + 0.3})
    people = naming.people(fr, FX, OPEN)
    striker = next(s.name for s in FX.sheet("home") if s.role == "ST")
    assert people["h-t10"]["name"] == striker and people["h-t40"]["name"] == striker
    assert people["h-t41"]["name"] is None
    assert len([w for w in people.values() if w["name"] == striker]) == 2  # never at once


def test_a_slot_needs_a_strict_majority_of_a_window():
    voted = [(i * 5, i * 0.2, {"h-t1": "GK" if i % 2 else "RB"}) for i in range(10)]
    assert naming.match_windows(voted, 10.0) == {}  # 5 of 10 for each: neither won
    voted[0] = (0, 0.0, {"h-t1": "GK"})
    assert naming.match_windows(voted, 10.0) == {"h-t1": {"GK": 10}}


def test_the_extra_track_dropped_is_the_one_furthest_from_any_slot():
    fr = frames(extra=True)
    for f in fr:
        stray = next(p for p in f["players"] if p["id"] == "h-t99")
        stray["x"] = 104.0  # a stray far upfield, listed first so it is not dropped for its place
        f["players"].remove(stray)
        f["players"].insert(0, stray)
    voted = naming.votes(fr, "home", naming.roles.places(frames(), "home"))
    assert all("h-t99" not in got for _, _, got in voted)


def test_events_cross_the_join_only_on_the_same_side_and_surely_without_a_gate():
    association = {"h-t7": {"track": "a-t2", "confidence": 1.0}, "h-t8": {"track": "h-t3", "confidence": 0.9}}
    assert naming.tactical(association, OPEN) == {"h-t8": "h-t3"}
    assert naming.tactical(association, {"association": None}) == {}
    sure = {"h-t9": {"track": "h-t4", "confidence": 1.0}}
    assert naming.tactical(sure, {"association": None}) == {"h-t9": "h-t4"}


def test_keep_apart_treats_touching_spans_as_overlapping_and_ties_keep_the_first():
    assert naming.keep_apart([("a", 0.0, 10.0, 5), ("b", 10.0, 20.0, 5)]) in ({"a"}, {"b"})
    assert naming.keep_apart([("a", 0.0, 10.0, 5), ("b", 5.0, 20.0, 5)]) == {"a"}


def test_of_two_overlapping_tracks_that_won_one_slot_the_heavier_keeps_the_name():
    fr = frames(seconds=30.0)
    for i, f in enumerate(fr):
        p = next(p for p in f["players"] if p["id"] == "h-t10")
        if i >= 350:  # the striker's second track, h-t40, from 14 s; it starts at 9 s as a duplicate
            p["id"] = "h-t40"
        elif i >= 225:
            f["players"].append({**p, "id": "h-t40", "x": p["x"] - 0.2})
    people = naming.people(fr, FX, OPEN)
    striker = next(s.name for s in FX.sheet("home") if s.role == "ST")
    assert people["h-t40"]["name"] == striker  # it won windows 1 and 2, for 21 s
    assert people["h-t10"]["name"] is None  # it won window 0, and overlaps h-t40 from 9 s to 14 s
