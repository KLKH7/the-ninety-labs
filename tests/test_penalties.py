"""The penalty report counts what it says it counts, in the cells the studies use."""

import math

from ninety.sim.penalties import BAR_ELI, BAR_ELI_ALL, HEIGHT_SAVED, on_target, one, tabulate


def kick(cross, z, dive, outcome):
    return {"cross": cross, "z": z, "dive": dive, "outcome": outcome}


def test_on_target_is_the_kicks_own_flight_clear_of_the_woodwork():
    # Law 1: 7.32 m by 2.44 m; posts and bar up to 12 cm; a size-5 ball about 22 cm across
    assert on_target(3.4, 0.2) and on_target(-3.4, 0.2) and on_target(0.0, 2.1)
    assert not on_target(3.6, 0.2)  # into the post or wide
    assert not on_target(0.0, 2.3)  # into the bar or over


def test_kicks_fall_in_the_published_cells():
    kicks = [
        kick(2.5, 0.3, 1.45, "on_target"),  # side, dived toward it, saved, low
        kick(-2.5, 1.2, -1.45, "goal"),  # side, toward, scored, middle height
        kick(2.5, 2.0, -1.45, "goal"),  # side, dived away, high
        kick(-3.0, 0.5, None, "blocked"),  # side, stayed, cleared by a defender: kept out
        kick(0.5, 1.0, 1.45, "goal"),  # middle third (|y| < 1.22 m), dived
        kick(-1.1, 1.0, None, "on_target"),  # middle, stayed, saved
        kick(1.3, 1.0, None, "goal"),  # 1.3 m is a side third, stayed
        kick(2.0, 0.1, 1.45, "off_target"),  # going in, tipped round the post: a save, kept out
        kick(3.6, 0.5, 1.45, "blocked"),  # going wide by its own flight: not counted
        kick(0.0, 2.3, None, "on_target"),  # into the bar by its own flight: not counted
        {"outcome": "goal"},  # never crossed his line where measured: not counted
    ]
    t = tabulate(kicks)
    assert t["total"]["n"] == 8 and t["total"]["kept"] == 4
    c = t["cells"]
    assert (c[("side", "toward")]["n"], c[("side", "toward")]["kept"]) == (3, 2)
    assert (c[("side", "away")]["n"], c[("side", "away")]["kept"]) == (1, 0)
    assert (c[("side", "stay")]["n"], c[("side", "stay")]["kept"]) == (2, 1)
    assert (c[("middle", "dive")]["n"], c[("middle", "dive")]["kept"]) == (1, 0)
    assert (c[("middle", "stay")]["n"], c[("middle", "stay")]["kept"]) == (1, 1)
    h = t["heights"]  # thirds of the 2.44 m crossbar (0.81 m, 1.63 m), by the ball's centre
    assert (h["low"]["n"], h["low"]["kept"]) == (3, 3)
    assert (h["middle"]["n"], h["middle"]["kept"]) == (4, 1)
    assert (h["high"]["n"], h["high"]["kept"]) == (1, 0)


def test_on_the_boundaries_a_kick_takes_the_side_and_the_band_above():
    t = tabulate([kick(7.32 / 6 + 1e-9, 2.44 / 3 - 0.11 + 1e-9, None, "goal")])  # just past each line
    assert t["cells"][("side", "stay")]["n"] == 1 and t["heights"]["middle"]["n"] == 1
    t = tabulate([kick(7.32 / 6 - 1e-9, 2.44 / 3 - 0.11 - 1e-9, 0.0, "goal")])  # a dive of 0 is still a dive
    assert t["cells"][("middle", "dive")]["n"] == 1 and t["heights"]["low"]["n"] == 1


def test_the_published_numbers_are_bar_elis_and_higueras_herbadas():
    # Bar-Eli et al. 2007, Table 1: 286 on target, 82 in the middle third, the keeper stayed 18 times,
    # 8 of them on side kicks; Table 2: 42 stopped (right way 16 + 15, middle with a jump 4 + 1).
    assert sum(n for _, n in BAR_ELI.values()) == 286 == BAR_ELI_ALL[1]
    assert BAR_ELI[("middle", "dive")][1] + BAR_ELI[("middle", "stay")][1] == 82
    assert BAR_ELI[("middle", "stay")][1] + BAR_ELI[("side", "stay")][1] == 18
    assert BAR_ELI[("side", "toward")] == (31, 113) and BAR_ELI[("side", "away")] == (0, 83)
    assert BAR_ELI[("middle", "dive")] == (5, 72) and BAR_ELI[("middle", "stay")] == (6, 10)
    assert sum(k for k, _ in BAR_ELI.values()) == 42 == BAR_ELI_ALL[0]
    assert HEIGHT_SAVED == {"low": "16.5%", "middle": "33.5%", "high": "9.1%"}


def test_a_penalty_records_where_it_crossed_and_which_way_he_dived():
    for seed in (1, 8):  # two penalties he dived at, one to each side
        k = one(seed)
        assert k and k["outcome"] in ("goal", "on_target", "off_target", "blocked")
        assert abs(k["cross"]) < 3.66 + 1.0 and 0.0 <= k["z"] < 3.0  # from the goal's centre, at his line
        assert 0 < abs(k["dive"]) <= 1.45 + 1e-9  # a dive, at most its full travel (P15)
        assert math.copysign(1, k["dive"]) == math.copysign(1, k["cross"])  # toward where it crossed


def test_a_kick_into_the_top_of_the_net_is_recorded_high():
    k = one(2)  # a goal struck high, with no dive
    assert k["outcome"] == "goal" and "dive" not in k
    assert 2.44 * 2 / 3 < k["z"] + 0.11 < 2.44  # in the top third, under the bar: its height, not its time
