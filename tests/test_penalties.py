"""The penalty report counts what it says it counts, in the cells the studies use."""

from ninety.sim.penalties import one, tabulate


def kick(cross, z, dive, outcome):
    return {"cross": cross, "z": z, "dive": dive, "outcome": outcome}


def test_kicks_fall_in_the_published_cells():
    kicks = [
        kick(2.5, 0.3, 1.45, "on_target"),  # side, dived toward it, saved, low
        kick(-2.5, 1.2, -1.45, "goal"),  # side, toward, scored, middle height
        kick(2.5, 2.0, -1.45, "goal"),  # side, dived away, high
        kick(-3.0, 0.5, None, "blocked"),  # side, stayed, parried and cleared: kept out
        kick(0.5, 1.0, 1.45, "goal"),  # middle third (|y| < 1.22 m), dived
        kick(-1.1, 1.0, None, "on_target"),  # middle, stayed, saved
        kick(1.3, 1.0, None, "goal"),  # 1.3 m is a side third, stayed
        kick(2.0, 1.0, 1.45, "off_target"),  # not on target: not counted
        {"outcome": "goal"},  # never crossed his line where measured: not counted
    ]
    t = tabulate(kicks)
    assert t["total"]["n"] == 7 and t["total"]["kept"] == 3
    c = t["cells"]
    assert (c[("side", "toward")]["n"], c[("side", "toward")]["kept"]) == (2, 1)
    assert (c[("side", "away")]["n"], c[("side", "away")]["kept"]) == (1, 0)
    assert (c[("side", "stay")]["n"], c[("side", "stay")]["kept"]) == (2, 1)
    assert (c[("middle", "dive")]["n"], c[("middle", "dive")]["kept"]) == (1, 0)
    assert (c[("middle", "stay")]["n"], c[("middle", "stay")]["kept"]) == (1, 1)
    h = t["heights"]  # thirds of the 2.44 m crossbar
    assert (h["low"]["n"], h["low"]["kept"]) == (2, 2)
    assert (h["middle"]["n"], h["middle"]["kept"]) == (4, 1)
    assert (h["high"]["n"], h["high"]["kept"]) == (1, 0)


def test_one_penalty_is_taken_and_ends():
    k = one(0)
    assert k and k["outcome"] in ("goal", "on_target", "off_target", "blocked")
    assert "cross" in k and "z" in k
