"""The player-ID feed (ninety/sim/identity_feed.py, docs/FEED_SPEC.md) and what the live path takes
from it (ninety/intel/identity.py): who each track is, and so his side.

The feed is the one engine output the live path may read (AGENTS.md, hard rules; lesson 269), and
only for identity and side. These tests hold that: the feed carries identity only, with a real
provider's imperfections (GROUNDING ID1 to ID9); it names tracks through vision's own association;
and everything else the pipeline computes is the same with it and without it.
"""

from __future__ import annotations

import ast
import json
import math
import random
import re
from pathlib import Path

import pytest

from ninety import e2e
from ninety.intel import identity, naming
from ninety.intel import match_insights as mi_mod
from ninety.intel.match_insights import MatchInsights
from ninety.intel.roles import TEMPLATE
from ninety.intel.teamsheet import LABEL, ROLES, Fixture
from ninety.sim import identity_feed
from tests.e2e_clip import EVENTS, write_clip

ROOT = Path(__file__).resolve().parents[1]
FX = Fixture(8080, "LON", "LIS")
ENGINE_ROSTER = [{"id": f"{t[0]}{n}", "team": t, "role": r, "name": "engine-only name"}
                 for t in ("home", "away") for n, r in enumerate(ROLES, 1)]


def engine_frames(seconds: float = 20.0, segment: int = 0, roster=ENGINE_ROSTER, place=None):
    """Engine-like frames: every player in his 4-3-3 place, drifting, with what the engine also
    writes (ball, velocity, action) so the export must drop it."""
    rng = random.Random(segment)
    out = []
    for i in range(int(seconds * 25)):
        frame = segment * 10000 + i
        players = []
        for p in roster:
            if place:
                x, y = place(p)
            else:
                d, across = TEMPLATE[p["role"]]
                x, y = (d, across) if p["team"] == "home" else (105.0 - d, 68.0 - across)
            players.append({"id": p["id"], "team": p["team"], "role": p["role"], "x": x + 0.01 * (i % 3),
                            "y": y + rng.gauss(0, 0.05), "vx": 1.0, "vy": 0.0, "action": "run"})
        out.append({"frame": frame, "t": frame / 25, "ball": {"x": 52.5, "y": 34.0, "z": 0.0},
                    "possessor": None, "players": players})
    return out


def tracked(engine, noise: float = 0.2, wrong_side: str | None = None, offset: dict | None = None):
    """Vision's tactical tracks of the engine frames: track h-t<n> follows h<n> (a-t<n+50> a<n>)."""
    rng = random.Random(1)
    out = []
    for f in engine:
        players = []
        for p in f["players"]:
            n = int(p["id"][1:])
            seg = (f["frame"] // 10000) * 1000
            tid = f"{p['id'][0]}-t{seg + n + (0 if p['team'] == 'home' else 50)}"
            side = p["team"]
            if tid == wrong_side:
                side = "away" if side == "home" else "home"
                tid = f"{side[0]}-t{tid.split('-t')[1]}"
            dx = (offset or {}).get(tid, 0.0)
            players.append({"id": tid, "team": side, "x": p["x"] + dx + rng.gauss(0, noise),
                            "y": p["y"] + rng.gauss(0, noise)})
        out.append({"frame": f["frame"], "t": f["t"], "source": "tracked", "ball": f["ball"],
                    "players": players})
    return out


def _lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines()]


def _write(path: Path, lines: list[dict]) -> None:
    path.write_text("".join(json.dumps(x) + "\n" for x in lines))


@pytest.fixture
def feed_path(tmp_path):
    path = tmp_path / "identity_feed.jsonl"
    identity_feed.write(path, ENGINE_ROSTER, engine_frames(), FX, None)
    return path


def exact_feed(at: dict[int, dict[str, tuple[float, float]]]) -> identity.Feed:
    """A feed with no noise: positions by frame, for the matching's boundaries."""
    ids = sorted({i for r in at.values() for i in r})
    meta = {"players": [{"player_id": p, "team": "home", "jersey": 1, "name": p, "position": "x"}
                        for p in ids],
            "teams": {"home": {"code": "LON"}, "away": {"code": "LIS"}}}
    return identity.Feed(meta, at, 0)


def flat_frames(tracks: dict[str, list[tuple[int, float, float]]]) -> list[dict]:
    by: dict[int, list] = {}
    for tid, rows in tracks.items():
        for k, x, y in rows:
            by.setdefault(k, []).append({"id": tid, "team": "home", "x": x, "y": y})
    return [{"frame": k, "t": k / 25, "source": "tracked", "players": ps} for k, ps in sorted(by.items())]


# --- the feed: a provider's, identity only (GROUNDING ID1 to ID9) --------------------------------

def test_the_feed_is_25_hz_pitch_centred_and_carries_identity_only(feed_path):
    lines = _lines(feed_path)
    meta, frames = lines[0], [r for r in lines[1:] if r["type"] == "frame"]
    assert meta["type"] == "metadata" and set(meta) == identity.META_KEYS and meta["fps"] == 25
    assert meta["pitch"] == {"length": 105.0, "width": 68.0, "origin": "centre", "units": "m"}
    sheet = {s.role: s for s in FX.sheet("home")}
    gk = next(p for p in meta["players"] if p["position"] == "goalkeeper" and p["team"] == "home")
    assert gk == {"player_id": "LON01", "team": "home", "jersey": 1, "name": sheet["GK"].name,
                  "position": "goalkeeper"}
    text = feed_path.read_text()
    assert "engine-only name" not in text and '"h1"' not in text
    assert len(frames) == 500  # every engine frame
    assert all(set(r) == identity.FRAME_KEYS and all(len(e) == 6 for e in r["players"]) for r in frames)
    first = {e[0]: e for e in min(frames, key=lambda r: r["t"])["players"]}
    assert first["LON01"][3] == pytest.approx(TEMPLATE["GK"][0] - 52.5, abs=0.5)  # from the centre spot
    assert '"ball"' not in text and '"action"' not in text


def test_the_feed_s_position_error_is_the_provider_s(tmp_path):
    path = tmp_path / "f.jsonl"
    long = engine_frames(seconds=120)
    identity_feed.write(path, ENGINE_ROSTER, long, FX, None)
    true = {f["t"]: {p["id"]: (p["x"], p["y"]) for p in f["players"]} for f in long}
    back = {v: k for k, v in identity_feed.roster(ENGINE_ROSTER, FX)[1].items()}
    err = [math.dist((e[3] + 52.5, e[4] + 34.0), true[r["t"]][back[e[0]]])
           for r in _lines(path)[1:] if r["type"] == "frame" for e in r["players"]]
    rmse = math.sqrt(sum(d * d for d in err) / len(err))
    assert identity_feed.NOISE_M * 0.7 < rmse < identity_feed.NOISE_M * 1.3  # ID2: 0.08 m


def test_the_reader_aligns_by_capture_time_not_arrival_order(feed_path, tmp_path):
    lines = _lines(feed_path)
    lag = [r["delivered"] - r["t"] for r in lines[1:]]  # ID3, to the millisecond each is rounded to
    assert all(15.0 - 1e-3 <= d <= 15.0 + identity_feed.JITTER_S + 1e-3 for d in lag)
    shuffled = tmp_path / "shuffled.jsonl"
    rest = lines[1:]
    random.Random(3).shuffle(rest)
    _write(shuffled, [lines[0], *rest])
    assert identity.load(shuffled).at == identity.load(feed_path).at


def test_rows_reach_the_file_in_delivery_order_which_is_not_capture_order(feed_path):
    rows = _lines(feed_path)[1:]
    assert [r["delivered"] for r in rows] == sorted(r["delivered"] for r in rows)
    captured = [r["t"] for r in rows if r["type"] == "frame"]
    assert captured != sorted(captured)  # jitter (ID3): a reader must sort by `t`


def _pair(seconds: float, gap: float):
    """Two home team-mates standing `gap` apart, and a lone away keeper."""
    roster = [{"id": "h1", "team": "home", "role": "GK"}, {"id": "h2", "team": "home", "role": "RB"},
              {"id": "a1", "team": "away", "role": "GK"}]
    spots = {"h1": (50.0, 30.0), "h2": (50.0 + gap, 30.0), "a1": (100.0, 34.0)}
    return roster, engine_frames(seconds, roster=roster, place=lambda p: spots[p["id"]])


def test_occluded_players_drop_out_and_come_back_low_confidence(tmp_path):
    roster, frames = _pair(120, 0.3)
    path = tmp_path / "f.jsonl"
    identity_feed.write(path, roster, frames, FX, None, seed=5)
    rows = sorted((r for r in _lines(path)[1:] if r["type"] == "frame"), key=lambda r: r["t"])
    present = [{e[0]: e[5] for e in r["players"]} for r in rows]
    lost = [k for k in range(1, len(present)) if "LON01" in present[k - 1] and "LON01" not in present[k]]
    assert lost, "two players 0.3 m apart are occluded now and then (ID4)"
    back = next(k for k in range(lost[0], len(present)) if "LON01" in present[k])
    assert present[back]["LON01"] == 0  # ID5
    assert all(p.get("LIS01") == 1 for p in present)  # nobody near him: never dropped
    assert "LON01" not in identity.load(path).positions(rows[back]["t"])  # the reader skips it


def test_swaps_are_between_close_team_mates_and_each_is_corrected(tmp_path):
    roster, frames = _pair(600, 0.5)
    path = tmp_path / "f.jsonl"
    identity_feed.write(path, roster, frames, FX, None, seed=5)
    fixes = [r for r in _lines(path)[1:] if r["type"] == "id_correction"]
    assert fixes, "two team-mates 0.5 m apart for 10 minutes swap at least once (ID6)"
    for c in fixes:
        assert sorted(c["player_ids"]) == ["LON01", "LON02"]  # never the away keeper 50 m off
        assert identity_feed.SWAP_S[0] - 0.05 <= c["to_t"] - c["from_t"] <= identity_feed.SWAP_S[1] + 0.05
    roster, frames = _pair(600, 3.0)  # 3 m apart: never confused
    identity_feed.write(path, roster, frames, FX, None, seed=5)
    assert not [r for r in _lines(path)[1:] if r["type"] == "id_correction"]


@pytest.mark.parametrize("seconds,seed", [(600, 5), (120, 19), (120, 26)])  # 19, 26: a swap open at the end
def test_a_swap_relabels_exactly_its_span_and_every_one_is_corrected(tmp_path, seconds, seed):
    """Raw rows: inside each correction's span LON01's id is at h2's spot, outside it at his own;
    once loaded, every LON01 is at his own spot, a swap still open at the stream's end included."""
    roster, frames = _pair(seconds, 0.9)  # within SWAP_M, and 8 noise sds from the midpoint
    path = tmp_path / "f.jsonl"
    identity_feed.write(path, roster, frames, FX, None, seed=seed)
    lines = _lines(path)
    spans = [(c["from_t"], c["to_t"]) for c in lines[1:] if c["type"] == "id_correction"]
    assert spans
    for r in (r for r in lines[1:] if r["type"] == "frame"):
        x = next((e[3] + 52.5 for e in r["players"] if e[0] == "LON01"), None)
        if x is not None:
            swapped = any(a - 1e-6 <= r["t"] < b - 1e-6 for a, b in spans)
            assert (abs(x - 50.9) < abs(x - 50.0)) == swapped, r["t"]
    for k, at in identity.load(path).at.items():
        if "LON01" in at:
            assert abs(at["LON01"][0] - 50.0) < abs(at["LON01"][0] - 50.9), k / 25


def test_the_reader_applies_corrections(feed_path, tmp_path):
    lines = _lines(feed_path)
    swapped = []
    for r in lines[1:]:
        if r["type"] == "frame" and 2.0 <= r["t"] < 5.0:
            for e in r["players"]:
                e[0] = {"LON02": "LON04", "LON04": "LON02"}.get(e[0], e[0])
        swapped.append(r)
    fix = {"type": "id_correction", "t": 5.0, "delivered": 20.0, "player_ids": ["LON02", "LON04"],
           "from_t": 2.0, "to_t": 5.0}
    path = tmp_path / "s.jsonl"
    _write(path, [lines[0], *swapped, fix])
    assert identity.load(path).at == identity.load(feed_path).at
    _write(path, [lines[0], *swapped])
    assert identity.load(path).at != identity.load(feed_path).at


@pytest.mark.parametrize("extra", [{"ball": {"x": 1}}, {"vx": 1.0}, {"type": "event"}])
def test_a_feed_carrying_more_than_identity_is_refused(feed_path, extra):
    lines = _lines(feed_path)
    base = next(r for r in lines[1:] if r["type"] == "frame")
    _write(feed_path, [lines[0], {**base, **extra}])
    with pytest.raises(ValueError, match="identity only"):
        identity.load(feed_path)


def test_a_feed_entry_with_a_speed_or_metadata_with_more_is_refused(feed_path):
    lines = _lines(feed_path)
    frame = next(r for r in lines[1:] if r["type"] == "frame")
    frame["players"][0].append(7.5)
    _write(feed_path, [lines[0], frame])
    with pytest.raises(ValueError, match="identity only"):
        identity.load(feed_path)
    _write(feed_path, [{**lines[0], "events": []}])
    with pytest.raises(ValueError, match="identity only"):
        identity.load(feed_path)


def test_a_metadata_player_with_more_than_his_label_is_refused(feed_path):
    lines = _lines(feed_path)
    lines[0]["players"][0]["birth_date"] = "2000-01-01"
    _write(feed_path, lines)
    with pytest.raises(ValueError, match="identity only"):
        identity.load(feed_path)


def test_a_feed_of_another_fixture_is_refused(feed_path):
    frames = tracked(engine_frames())
    with pytest.raises(ValueError, match="not"):
        identity.load_for(feed_path, frames, Fixture(7, "LON", "LIS"))  # same clubs, another match
    with pytest.raises(ValueError, match="not"):
        identity.load_for(feed_path, frames, Fixture(8080, "LIS", "LON"))
    with pytest.raises(ValueError, match="another fixture"):
        MatchInsights.build("c", frames, [], Fixture(8080, "OAK", "FEN"), feed=identity.load(feed_path))


# --- naming tracks -------------------------------------------------------------------------------

def test_each_track_is_named_as_the_feed_player_it_follows(feed_path):
    named = identity.tactical(tracked(engine_frames()), identity.load(feed_path))
    assert len(named) == 22
    sheet = {s.role: s for s in FX.sheet("away")}
    w = named["a-t60"]  # follows a10, the striker (ROLES[9])
    assert (w["player"], w["name"], w["number"], w["source"]) == ("LIS09", sheet["ST"].name, 9, "id_feed")
    assert w["position"] == LABEL["ST"]


def test_a_track_further_than_vision_s_measured_error_is_not_named(feed_path):
    off = {"h-t9": identity.GATE_M + 0.5}
    named = identity.tactical(tracked(engine_frames(), noise=0.0, offset=off), identity.load(feed_path))
    assert "h-t9" not in named and "h-t10" in named


def test_the_gate_holds_a_pair_at_exactly_the_gate_and_not_past_it():
    at = {k: {"H1": (10.0, 10.0)} for k in range(50)}
    near = flat_frames({"h-t1": [(k, 11.0, 10.0) for k in range(50)]})
    far = flat_frames({"h-t1": [(k, 11.5, 10.0) for k in range(50)]})
    assert "h-t1" in identity.assign(near, exact_feed(at), gate_m=1.0)
    assert "h-t1" not in identity.assign(far, exact_feed(at), gate_m=1.0)


def test_a_track_read_on_the_wrong_side_is_never_given_a_player_of_the_other(feed_path):
    named = identity.tactical(tracked(engine_frames(), wrong_side="h-t9"), identity.load(feed_path))
    assert "a-t9" not in named  # h9's track read as away: no away player stands there


def test_two_tracks_on_one_player_at_once_name_only_one(feed_path):
    frames = tracked(engine_frames())
    for f in frames:  # a duplicate of h-t7 all clip long
        p = next(p for p in f["players"] if p["id"] == "h-t7")
        f["players"].append({**p, "id": "h-t99", "x": p["x"] + 0.1})
    named = identity.tactical(frames, identity.load(feed_path))
    assert ("h-t7" in named) != ("h-t99" in named)


def test_a_one_frame_fragment_never_takes_the_player_from_a_track_on_him_all_window():
    at = {k: {"H1": (10.0, 10.0)} for k in range(250)}
    frames = flat_frames({"h-t1": [(k, 10.3, 10.0) for k in range(250)], "h-t2": [(100, 10.0, 10.0)]})
    got = identity.assign(frames, exact_feed(at))
    assert got["h-t1"]["id"] == "H1" and got["h-t1"]["share"] == 1.0 and "h-t2" not in got


def test_a_track_on_a_man_all_clip_is_not_given_the_team_mate_a_metre_away():
    at = {k: {"H1": (10.0, 10.0), "H2": (11.0, 10.0)} for k in range(1000)}
    track = [(k, 10.0, 10.0) for k in range(1000)]
    # a fragment in 3 windows, 0.5 m from H1 and 1.5 m (past the gate) from H2
    bits = {f"h-t{9 + w}": [(250 * w + 100, 9.5, 10.0)] for w in range(1, 4)}
    got = identity.assign(flat_frames({"h-t1": track, **bits}), exact_feed(at))
    assert got["h-t1"]["id"] == "H1" and got["h-t1"]["share"] == 1.0


def test_a_track_that_is_the_player_for_exactly_half_its_frames_is_not_named(feed_path):
    frames = tracked(engine_frames(), noise=0.0)
    for f in frames:  # with 5 s windows, h-t7 is h7 for the first two (250 of 500 frames), then 5 m off
        p = next(p for p in f["players"] if p["id"] == "h-t7")
        if f["t"] >= 10.0:
            p["x"] += 5.0
    named = identity.assign(frames, identity.load(feed_path), window_s=5.0)
    assert "h-t7" not in named and "h-t8" in named


def test_two_overlapping_tracks_that_each_won_the_player_in_a_window_name_only_one(feed_path):
    frames = tracked(engine_frames(), noise=0.0)
    for f in frames:
        p = next(p for p in f["players"] if p["id"] == "h-t7")
        f["players"].remove(p)
        if f["t"] < 14.0:  # A: 0-14 s, on him in the first window, 0.8 m off in the second
            f["players"].append({**p, "id": "h-t97", "x": p["x"] + (0.8 if f["t"] >= 10.0 else 0.0)})
        if f["t"] >= 9.0:  # B: 9-20 s, on him; it wins the second window
            f["players"].append({**p, "id": "h-t98"})
    named = identity.tactical(frames, identity.load(feed_path))
    assert ("h-t97" in named) != ("h-t98" in named)


def test_names_cross_the_join_by_the_association_never_by_the_id_string(feed_path):
    named = identity.tactical(tracked(engine_frames()), identity.load(feed_path))
    association = {
        "h-t7": {"track": "h-t2", "confidence": 1.0},  # the broadcast's h-t7 is the tactical h-t2
        "h-t8": {"track": "h-t3", "confidence": 0.5},  # below the gate
        "a-t59": {"track": "h-t4", "confidence": 1.0},  # the cameras disagree on the side
    }
    b = identity.broadcast(association, named, {"association": 0.75})
    assert b["h-t7"]["name"] == named["h-t2"]["name"] != named["h-t7"]["name"]
    assert set(b) == {"h-t7"}
    assert [r["id"] for r in identity.lineup(b)] == ["h-t7"]


def test_the_committed_gate_is_used_only_when_its_held_out_half_met_the_target(tmp_path):
    body = json.loads(identity.CALIBRATION.read_text())
    assert body["source"] == "docs/eval/identity.json"
    held = json.loads((ROOT / "docs/eval/identity.json").read_text())["held_out"]
    met = all(held[u]["precision"] >= body["target"] for u in ("track_names", "event_names"))
    assert body["held_out_met"] == met
    direct = json.loads((ROOT / "docs/eval/identity.json").read_text())["direct"]["held_out"]["event_names"]
    assert body["direct_held_out_met"] == (direct["precision"] >= body["target"])  # the plan's gate
    p = tmp_path / "c.json"
    p.write_text(json.dumps({**body, "held_out_met": False, "direct_held_out_met": False}))
    assert identity.gate(p) == {"association": None, "direct": False}


# --- the broadcast camera, matched to the feed directly (docs/eval/identity-direct-plan.md) ------

def test_the_broadcast_frames_are_renumbered_as_the_join_renumbers_them(tmp_path):
    for name, tid in (("seed1-t000100", "h-t3"), ("seed1-t000000", "a-t2")):
        (tmp_path / name / "broadcast").mkdir(parents=True)
        (tmp_path / name / "broadcast" / "tracked.json").write_text(json.dumps(
            {"frames": [{"frame": 1, "t": 0.04, "players": [{"id": tid, "team": "home", "x": 1, "y": 1}]}]}))
    got = [p["id"] for f in identity.broadcast_frames(tmp_path) for p in f["players"]]
    assert got == ["a-t2", f"h-t{naming.PER_SEGMENT + 3}"]  # segments in name order: t000000 first


def test_a_broadcast_track_on_the_wrong_side_is_named_and_given_the_feed_s_side(feed_path):
    frames = tracked(engine_frames(), wrong_side="h-t9")  # h9's track, read as away (a-t9)
    feed = identity.load(feed_path)
    assert "a-t9" not in identity.tactical(frames, feed)
    w = identity.tactical(frames, feed, any_side=True)["a-t9"]
    assert (w["player"], w["team"]) == ("LON07", "home")  # h9 is the right winger, shirt 7


def test_combined_finds_a_track_by_number_and_keeps_the_more_confident_name():
    direct = {"h-t7": {"name": "D", "share": 0.9}, "a-t8": {"name": "E", "share": 0.6},
              "h-t5": {"name": "F", "share": 0.6}}
    via = {"a-t8": {"name": "J", "share": 1.0}, "h-t5": {"name": "G", "share": 1.0},
           "h-t9": {"name": "K", "share": 1.0}}
    association = {"a-t8": {"confidence": 0.5}, "h-t5": {"confidence": 0.9}, "h-t9": {"confidence": 0.5}}
    got = identity.combined(["a-t7", "a-t8", "h-t5", "h-t9"], via, direct, association)
    assert got["a-t7"]["name"] == "D" and got["a-t7"]["track"] == "a-t7"  # the event's letter, by number
    assert got["a-t8"]["name"] == "E"  # direct 0.6 beats the join's 1.0 x 0.5
    assert got["h-t5"]["name"] == "G"  # the join's 1.0 x 0.9 beats direct 0.6
    assert got["h-t9"]["path"] == "join"
    tie = identity.combined(["a-t8"], {"a-t8": {"name": "J", "share": 0.6}}, direct,
                            {"a-t8": {"confidence": 1.0}})
    assert tie["a-t8"]["name"] == "E"  # a tie goes to the broadcast's own track


def test_the_direct_path_is_used_only_when_its_gate_was_met(feed_path, tmp_path, monkeypatch):
    frames = tracked(engine_frames())
    feed = identity.load(feed_path)
    events = [{"player": "h-t5"}]
    for met, expect in ((True, {"h-t5"}), (False, set())):
        p = tmp_path / f"{met}.json"
        p.write_text(json.dumps({"association": 0.75, "held_out_met": True, "direct_held_out_met": met}))
        monkeypatch.setattr(identity, "CALIBRATION", p)
        monkeypatch.setattr(identity, "gate", lambda path=p: _gate(path))
        assert set(identity.named_broadcast({}, {}, feed, events, frames)) == expect


_gate = identity.gate


# --- the feed is used ONLY for identity and side ------------------------------------------------

def test_an_event_takes_only_its_named_player_s_side_from_the_feed():
    events = [{"id": "e1", "type": "pass", "team": "away", "team_confidence": 0.6, "player": "h-t7",
               "receiver": "h-t8", "x": 1.0, "confidence": 0.7},
              {"id": "e2", "type": "pass", "team": "home", "team_confidence": 0.6, "player": "h-t8"}]
    a, b = identity.sided(events, {"h-t7": {"team": "home", "name": "N"}})
    assert (a["team"], a["team_confidence"], a["team_source"]) == ("home", 1.0, "id_feed")
    side = ("team", "team_confidence", "team_source")
    rest = lambda e: {k: v for k, v in e.items() if k not in side}  # noqa: E731
    assert rest(a) == rest(events[0])
    assert b == events[1]


def test_the_side_step_changes_only_the_named_events_sides(feed_path, tmp_path):
    frames = tracked(engine_frames())
    (tmp_path / "tracked.json").write_text(json.dumps({"frames": frames}))
    events = [{"id": "e1", "t": 3.0, "frame": 75, "type": "pass", "team": "away", "team_confidence": 0.6,
               "player": "h-t7", "receiver": "h-t8", "x": 30.0, "y": 30.0, "confidence": 0.8},
              {"id": "e2", "t": 4.0, "frame": 100, "type": "pass", "team": "home", "team_confidence": 0.7,
               "player": "h-t3", "x": 30.0, "y": 30.0, "confidence": 0.8}]
    (tmp_path / "detected.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    params = {"home_code": "LON", "away_code": "LIS"}
    (tmp_path / "clip.json").write_text(json.dumps({"seed": 8080, "params": params}))
    pairs = {"h-t7": {"track": "h-t7", "confidence": 1.0}}
    (tmp_path / "association.json").write_text(json.dumps({"tracks": pairs}))
    out = tmp_path / "sided.jsonl"
    identity.main(["--tracked", str(tmp_path / "tracked.json"),
                   "--association", str(tmp_path / "association.json"),
                   "--detected", str(tmp_path / "detected.jsonl"), "--fixture", str(tmp_path / "clip.json"),
                   "--feed", str(feed_path), "--out", str(out)])
    a, b = _lines(out)
    side = ("team", "team_confidence", "team_source")
    assert (a["team"], a["team_confidence"], a["team_source"]) == ("home", 1.0, "id_feed")
    rest = lambda e: {k: v for k, v in e.items() if k not in side}  # noqa: E731
    assert rest(a) == rest(events[0])
    assert b == events[1]  # h-t3 has no association: vision's side, untouched


def _build(feed_path, feed: bool):
    frames = tracked(engine_frames())
    association = {"h-t7": {"track": "h-t2", "confidence": 1.0}}
    return MatchInsights.build("c", frames, [], FX, association=association,
                               feed=identity.load(feed_path) if feed else None)


NAMES = {"identity", "identity_tracks", "identity_broadcast", "lineup", "lineup_tactical"}


def test_every_fact_person_and_stat_is_the_same_with_the_feed_and_without(feed_path):
    a, b = _build(feed_path, False).as_dict(), _build(feed_path, True).as_dict()
    assert {k: v for k, v in a.items() if k not in NAMES} == {k: v for k, v in b.items() if k not in NAMES}
    assert set(b) - set(a) <= NAMES
    assert b["lineup"][0]["name"] == b["identity_tracks"]["h-t2"]["name"]
    assert b["identity"]["note"] == identity.DISCLOSURE and b["identity"]["label"] == "Player ID feed"
    round_trip = MatchInsights.from_dict(b).as_dict()
    assert round_trip["lineup"] == b["lineup"] and round_trip["lineup_tactical"] == b["lineup_tactical"]


def test_the_bundle_is_the_same_with_the_feed_but_for_its_named_line_up(tmp_path):
    """End to end, with detected events: insights with and without the feed (match_insights' CLI),
    then the bundle from each. Facts, cues, claims, events and every match.json field but the
    line-up are identical."""
    engine = engine_frames(seconds=70)
    feed = tmp_path / "feed.jsonl"
    identity_feed.write(feed, ENGINE_ROSTER, engine, FX, None)
    (tmp_path / "tracked.json").write_text(json.dumps({"frames": tracked(engine)}))

    def track(i: str) -> str:
        return f"{i[0]}-t{int(i[1:]) + (0 if i[0] == 'h' else 50)}"

    people = ("player", "receiver", "intended")
    renamed = [{**e, **{k: track(e[k]) for k in people if e.get(k)}} for e in EVENTS]
    (tmp_path / "detected.jsonl").write_text("".join(json.dumps(e) + "\n" for e in renamed))
    (tmp_path / "fixture.json").write_text(json.dumps({"seed": 8080, "home_code": "LON", "away_code": "LIS"}))
    (tmp_path / "association.json").write_text(json.dumps(
        {"tracks": {e["player"]: {"track": e["player"], "confidence": 1.0} for e in renamed}}))
    common = [str(tmp_path / "tracked.json"), str(tmp_path / "detected.jsonl"),
              str(tmp_path / "fixture.json"), "--clip", "c",
              "--association", str(tmp_path / "association.json")]
    mi_mod.main([*common, "--out", str(tmp_path / "plain.json")])
    mi_mod.main([*common, "--out", str(tmp_path / "fed.json"), "--identity-feed", str(feed)])
    plain_i, fed_i = (json.loads((tmp_path / f"{k}.json").read_text()) for k in ("plain", "fed"))
    assert plain_i["facts"]["pass"] and plain_i["facts"] == fed_i["facts"]  # event facts exist, unchanged
    clip, detections, events = write_clip(tmp_path / "clip")
    out = {}
    for k in ("plain", "fed"):
        e2e.main([str(clip), "--out", str(tmp_path / f"b-{k}"), "--detections", str(detections), "--frames",
                  "--events-file", str(events), "--match", "--team-stats", str(tmp_path / f"{k}.json")])
        out[k] = tmp_path / f"b-{k}"
    for name in ("cues.jsonl", "facts.json", "events.jsonl"):
        assert (out["plain"] / name).read_text() == (out["fed"] / name).read_text(), name
    timeless = lambda path: re.sub(r'"ms": [0-9.]+', "", path.read_text())  # noqa: E731
    assert timeless(out["plain"] / "trace.json") == timeless(out["fed"] / "trace.json")
    plain = json.loads((out["plain"] / "match.json").read_text())
    fed = json.loads((out["fed"] / "match.json").read_text())
    rest = lambda body: {k: v for k, v in body.items() if k not in NAMES}  # noqa: E731
    assert rest(plain) == rest(fed)
    assert fed["identity"]["label"] == "Player ID feed"
    assert fed["lineup"] and {r["source"] for r in fed["lineup"]} == {"id_feed"}
    assert {r["id"] for r in fed["lineup_tactical"]} >= {"h-t2", "a-t51"}


# Where the feed, or anything made from it, may be read (AGENTS.md: identity and side only).
ALLOWED = {
    "ninety/sim/identity_feed.py",  # writes it
    "ninety/intel/identity.py",  # the one reader: names, and the sided events
    "ninety/intel/match_insights.py",  # names tracks with it, after every fact and stat
    "ninety/eval/identity_eval.py",  # grades the names it gives
    "ninety/e2e.py",  # copies the line-up rows and the disclosure into match.json
}
TOKENS = re.compile(r"\b(identity_feed|identity_tracks|identity_broadcast|identity_source|lineup_tactical"
                    r"|identity_mod|load_for)\b"
                    r"|(?<!azure)\.identity\b(?!\s*\()")  # not azure.identity, nor three.js's q.identity()
MODULES = {"ninety.intel.identity", "ninety.sim.identity_feed"}


def imports(path: Path, text: str | None = None) -> set[str]:
    """Every module a file imports, relative imports resolved, `from x import y` as x.y too, and
    importlib.import_module / __import__ of a literal name."""
    pkg = list(path.relative_to(ROOT).with_suffix("").parts[:-1])
    out = set()
    for node in ast.walk(ast.parse(text if text is not None else path.read_text())):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                up = pkg[: len(pkg) - node.level + 1]
                base = ".".join([*up, base] if base else up)
            out |= {base, *(f"{base}.{a.name}" for a in node.names)}
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in ("import_module", "__import__"):
                out |= {a.value for a in node.args
                        if isinstance(a, ast.Constant) and isinstance(a.value, str)}
    return out


def test_only_the_identity_path_touches_the_feed():
    """No vision module, agent, MCP tool, metric or other evaluation imports the feed's writer or
    reader (however it is imported) or reads anything made from it; on the web, only the phone,
    which shows the names with their source."""
    py = [*(ROOT / "ninety").rglob("*.py"), *(ROOT / "scripts").rglob("*.py")]
    by_import = {str(p.relative_to(ROOT)) for p in py if imports(p) & MODULES}
    by_name = {str(p.relative_to(ROOT)) for p in py if TOKENS.search(p.read_text())}
    assert by_import | by_name <= ALLOWED, sorted((by_import | by_name) - ALLOWED)
    assert {"ninety/intel/match_insights.py", "ninety/e2e.py"} <= by_import | by_name
    files = [p for ext in ("*.ts", "*.tsx", "*.js", "*.mjs") for p in (ROOT / "web").rglob(ext)]
    web = {str(p.relative_to(ROOT)) for p in files
           if not {"node_modules", "dist", "dist-mock"} & set(p.parts) and TOKENS.search(p.read_text())}
    assert all(p.startswith("web/phone/src/") for p in web), web
    insights = (ROOT / "ninety/intel/match_insights.py").read_text()
    build = insights[insights.index("    def build("):insights.index("        return mi\n")]
    assert build.index("identity_mod.tactical") > build.index("mi.stats = stats_table(mi)")


@pytest.mark.parametrize("code", [
    "from ninety.intel import (\n    roles,\n    identity,\n)\n",
    "from . import identity\n",
    "from .identity import tactical\n",
    "import importlib\nm = importlib.import_module('ninety.intel.identity')\n",
])
def test_the_import_scan_sees_every_way_to_import_the_reader(code):
    assert imports(ROOT / "ninety" / "intel" / "stats_table.py", code) & MODULES
