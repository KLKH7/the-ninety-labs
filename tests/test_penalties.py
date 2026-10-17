"""The penalty report (ninety.sim.penalties) measures what it says it does."""

from ninety.sim import penalties


def test_a_penalty_is_taken_and_its_outcome_is_read_from_what_happened():
    rows = [penalties.take(seed) for seed in range(1, 9)]
    assert all(r["taken"] for r in rows)
    for r in rows:
        assert r["right_way"] in (True, False, None)
        assert not (r["goal"] and r["keeper"])  # a stop is a keeper's touch with no goal
        assert 0.2 < r["flight"] < 1.5 and r["wide"] >= 0.0
    assert any(r["goal"] for r in rows)


def test_a_penalty_never_comes_off_the_man_who_took_it():
    # He stands behind the ball on the mark, so his kick leaves the front of his body: before, he
    # walked onto the mark itself and kicked the ball out through his own outline.
    from ninety.sim.engine import PENALTY_MARK_M, PITCH_Y, Engine

    for seed in range(1, 13):
        e = Engine(seed)
        taker = max((p for p in e.players if p.team == "home" and p.role != "GK"),
                    key=lambda p: p.profile["finishing"])
        spot = (penalties.GOAL_X - PENALTY_MARK_M, PITCH_Y / 2)
        e.possessor, e.kicked = None, None
        e.ball = (*spot, 0.0, 0.0, 0.0, 0.0)
        e.stop("penalty_kick", "home", spot, taker.id)
        e.restart.ready_at = e.t + penalties.SETTLE_S
        for p in e.players:
            p.vx = p.vy = 0.0
            if p is not taker:
                p.x, p.y = e.penalty_wait_spot(p)
        taker.x, taker.y, taker.heading = spot[0] - 1.0, spot[1], 0.0
        shot_at = None
        for _ in range(int((penalties.SETTLE_S + 5.0) * 25)):
            e.step()
            if shot_at is None and any(ev["type"] == "shot" for ev in e.match.events):
                shot_at = len(e.match.events)
                assert taker.x < spot[0]  # behind the ball, not on it
            if shot_at is not None and len(e.match.events) > shot_at + 2:
                break
        assert shot_at is not None
        after = e.match.events[shot_at:]
        assert not any(ev["type"] == "deflection" and ev.get("player") == taker.id for ev in after), seed
