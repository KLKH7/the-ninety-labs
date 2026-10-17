"""The touch report (ninety/sim/touches.py) listens to the engine without changing it, and counts
what its report says it counts."""

from types import SimpleNamespace

from ninety.sim.engine import DT, Engine
from ninety.sim.touches import Watch, follow, stop_frames, throw_outcome


def test_listening_never_changes_the_match():
    a, b = Engine(5), Watch(5)
    plain, watched = a.run(1.0), b.run(1.0)
    assert b.touch_log  # it heard touches...
    assert watched.events == plain.events  # ...and the match is the same, event for event
    assert watched.frames == plain.frames


def clear_scene(e: Engine, keep: tuple[str, ...]) -> None:
    for p in e.players:
        p.vx = p.vy = 0.0
        if p.id not in keep:
            p.x, p.y = (2.0, 2.0) if p.team == "home" else (103.0, 66.0)
    e.decide = lambda *a, **k: None  # nobody chooses anything else


def test_a_slow_pass_to_a_free_team_mate_is_his_controlled_foot_touch():
    e = Watch(3)
    clear_scene(e, ("h4", "h8"))
    passer, mate = e.by_id["h4"], e.by_id["h8"]
    passer.x, passer.y, passer.heading = 40.0, 34.0, 0.0
    mate.x, mate.y, mate.heading = 55.0, 34.0, 3.1416
    e.give(passer.id)
    e.ball = (40.37, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.pass_to(passer, 55.0, 34.0, lofted=False, pace=6.0, receiver=mate.id)
    for _ in range(int(4.0 / DT)):
        e.step()
    rec = next(r for r in e.touch_log if r["player"] == mate.id)
    assert rec["kind"] == "touch" and rec["who"] == "intended receiver" and not rec["aerial"]
    assert rec["controls"] and rec["reacted"] and 3.0 < rec["rel"] < 12.0  # 6 m/s, plus his own run at it
    assert follow(e.match, rec, stop_frames(e.match))["kept"]


def test_a_ball_at_a_man_who_has_not_reacted_is_a_body_hit_at_its_height():
    e = Watch(3)
    clear_scene(e, ("h4", "a6"))
    e.last_touch = "h4"  # struck by h4, far away, this instant: a6 has had no time to react
    e.kicked_at = e.t
    e.kicker_clear = True
    victim = e.by_id["a6"]
    victim.x, victim.y, victim.heading = 50.0, 34.0, 3.1416
    e.ball = (48.5, 34.0, 1.2, 15.0, 0.0, 0.0)
    for _ in range(4):
        e.step()
    rec = next(r for r in e.touch_log if r["player"] == victim.id)
    assert rec["kind"] == "body" and not rec["reacted"] and not rec["controls"]
    assert 0.45 < rec["z"] < 1.4 and rec["who"] == "loose ball"


ROSTER = [{"id": i, "team": "home" if i[0] == "h" else "away"} for i in ("h1", "h2", "a1")]


def match(possessors, ball_x=None, events=()):
    """A synthetic match: per frame, who has the ball; the ball at ball_x[k] along y = 34 and every
    player at the origin of x, so the ball's distance from anyone is its x."""
    xs = ball_x or [0.0] * len(possessors)
    frames = [{"frame": k, "possessor": who, "ball": {"x": x, "y": 34.0},
               "players": [{"id": r["id"], "x": 0.0, "y": 34.0} for r in ROSTER]}
              for k, (who, x) in enumerate(zip(possessors, xs, strict=True))]
    return SimpleNamespace(roster=ROSTER, frames=frames, events=list(events))


def test_a_loose_touch_he_gets_back_is_kept_and_measured_on_the_way():
    m = match([None, None, None, "h1"], [3.0, 1.5, 2.5, 0.4])
    out = follow(m, {"frame": 0, "player": "h1"}, stop_frames(m))
    assert out["kept"] and out["after_s"] == 3 * DT
    assert out["met_m"] == 3.0 and out["far_m"] == 2.5  # where it was met is not how far it went after


def test_a_touch_someone_else_or_a_stoppage_takes_is_not_kept():
    m = match([None, "a1", "a1"])
    assert not follow(m, {"frame": 0, "player": "h1"}, stop_frames(m))["kept"]
    m = match([None, None, "h1"], events=[{"type": "out_of_play", "frame": 1}])
    # his again only at the restart
    assert not follow(m, {"frame": 0, "player": "h1"}, stop_frames(m))["kept"]


def test_a_throw_in_counts_its_first_contact_and_who_holds_it_five_seconds_on():
    frames = 5 * 25 + 2
    ours_lost = match(["h1"] + [None] * 10 + ["a1"] * (frames - 11))
    touches = [{"frame": 3, "player": "h2", "team": "home", "controls": False, "stopped": False,
                "kept": False},
               {"frame": 6, "player": "a1", "team": "away", "controls": True, "stopped": False, "kept": True}]
    throw = {"frame": 0, "team": "home", "taker": "h1"}
    out = throw_outcome(ours_lost, throw, touches, [])
    assert out == {"mate": True, "mate_controls": False, "mate_kept": False, "held": False}
    theirs_first = throw_outcome(match(["h1"] + ["h2"] * (frames - 1)), throw, touches[1:], [])
    assert theirs_first["mate"] is False and theirs_first["held"] is True
    out_first = throw_outcome(ours_lost, throw, touches, [2])
    assert out_first["mate"] is False  # it went out before anyone touched it
