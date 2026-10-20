"""The pitch-position scorer (ninety/eval/pitch_score.py) on frames built here."""

import pytest

from ninety.eval.pitch_score import score


def truth(frame, px, py, bx, bz=0.1):
    return {"frame": frame,
            "players": [{"bbox": [100, 100, 120, 150], "visibility": 1.0, "x": px, "y": py}],
            "ball": {"bbox": [200, 200, 210, 210], "visibility": 1.0, "center_px": [205, 205],
                     "x": bx, "y": 30.0, "z": bz}}


def obs(frame, ok=True, px=50.0, bx=60.0, box=(100, 100, 120, 150), ball_px=(200, 200, 210, 210)):
    return {"frame": frame, "camera": {"ok": ok},
            "players": [{"bbox": list(box), "score": 0.9, "x": px, "y": 20.0}],
            "ball": [{"bbox": list(ball_px), "score": 0.9, "x": bx, "y": 30.0}]}


def test_errors_are_measured_against_the_matched_player_and_the_ball_on_the_ground():
    frames = [truth(0, 50.0, 20.0, 60.0), truth(1, 50.0, 20.0, 60.0)]
    r = score(frames, [obs(0, px=50.3, bx=60.2), obs(1, px=51.0)])
    assert r["players"]["n"] == 2 and r["players"]["max_m"] == pytest.approx(1.0)
    assert r["ball_on_ground"]["max_m"] == pytest.approx(0.2)


def test_a_frame_with_an_untrusted_camera_is_not_scored_and_is_listed():
    r = score([truth(0, 50.0, 20.0, 60.0)], [obs(0, ok=False, px=99.0)])
    assert r["players"]["n"] == 0 and r["frames"]["camera_not_ok"] == [0]


def test_a_box_that_matches_no_player_and_a_ball_off_its_centre_are_not_paired():
    r = score([truth(0, 50.0, 20.0, 60.0)], [obs(0, box=(300, 300, 320, 350), ball_px=(220, 200, 230, 210))])
    assert r["players"]["n"] == 0 and r["ball_on_ground"]["n"] == 0


def test_a_ball_in_the_air_is_reported_apart():
    r = score([truth(0, 50.0, 20.0, 60.0, bz=3.0)], [obs(0, bx=66.0)])
    assert r["ball_on_ground"]["n"] == 0 and r["ball_in_the_air"]["max_m"] == pytest.approx(6.0)


def test_an_observed_frame_missing_from_the_truth_is_refused():
    with pytest.raises(ValueError, match="not in the truth"):
        score([truth(0, 50.0, 20.0, 60.0)], [obs(5)])
