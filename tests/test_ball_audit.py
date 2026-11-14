"""The Vision Auditor's ball audit (ninety/eval/ball_audit.py): the plan's groups, places and match rule."""

from ninety.eval import ball_audit as ba


def _frame(f, x, y, z=0.0, cx=100.0, visible=1.0):
    return {"frame": f, "ball": {"x": x, "y": y, "z": z, "bbox": [cx - 4, 96, cx + 4, 104],
                                 "visibility": visible, "center_px": [cx, 100.0]}}


def _obs(f, cx=None, score=0.9):
    return {"frame": f, "ball": [] if cx is None else [{"bbox": [cx - 4, 96, cx + 4, 104], "score": score}]}


def test_line_distance_reaches_the_markings_arcs_included():
    assert ba.line_distance(10.0, 0.0) == 0.0  # on the touchline
    assert abs(ba.line_distance(52.5, 34.0 + 9.15) - 0.0) < 0.02  # on the centre circle
    assert ba.line_distance(30.0, 30.0) > ba.LINE_M  # open field


def test_places_name_where_a_ball_at_a_line_is():
    assert ba.place(0.5, 0.5) == "corner arc"
    assert ba.place(40.0, 0.3) == "touchline"
    assert ba.place(0.2, 30.0) == "goal line"
    assert ba.place(52.5, 25.0) == "halfway and centre circle"
    assert ba.place(16.5, 20.0) == "penalty and goal areas"


def test_a_ball_is_found_only_within_the_scorers_5_px_and_at_its_threshold():
    ball = _frame(1, 10, 0)["ball"]
    assert ba.found(ball, [{"bbox": [96, 96, 104, 104], "score": 0.9}])
    assert not ba.found(ball, [{"bbox": [102, 96, 110, 104], "score": 0.9}])  # centre 6 px away
    assert not ba.found(ball, [{"bbox": [96, 96, 104, 104], "score": 0.4}])  # under the threshold


def test_each_ball_lands_in_its_group_dead_or_moving_at_a_line_or_away():
    # frames 0-4: a ball set on the touchline, never found; 10-14: a ball rolling in midfield, found;
    # 20-24 a ball held up (z 1.2) at the touchline
    frames = [_frame(f, 40.0, 0.2) for f in range(5)]
    frames += [_frame(f, 30.0 + 0.4 * f, 30.0) for f in range(10, 15)]
    frames += [_frame(f, 40.0, 0.2, z=1.2) for f in range(20, 25)]
    frames += [_frame(30, 30, 30, visible=0.0)]  # hidden: not a ball to find
    obs = [_obs(f) for f in range(5)] + [_obs(f, 100.0) for f in range(10, 15)]
    obs += [_obs(f) for f in range(20, 25)]
    obs.append(_obs(30, 100.0))
    rows = ba.audit_clip(frames, obs)
    groups = {(r["frame"], r["group"], r["found"], r["grounded"]) for r in rows}
    assert (2, "dead at a line", False, True) in groups
    assert (12, "moving away from lines", True, True) in groups
    assert (22, "dead at a line", False, False) in groups
    assert not any(r["frame"] in (0, 4, 10, 14, 30) for r in rows)  # no neighbour, or hidden
    s = ba.summary(rows)
    assert s["dead at a line"]["found"] == 0 and s["moving away from lines"]["recall"] == 1.0
