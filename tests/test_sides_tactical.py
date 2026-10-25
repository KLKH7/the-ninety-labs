"""Team sides scored by pitch position (ninety/eval/sides_tactical.py): the broadcast fallback, TB."""


def test_a_tactical_track_inherits_the_side_of_the_broadcast_track_it_overlaps_most():
    from ninety.eval.sides_tactical import inherit
    from ninety.vision.track import Track

    tac = Track(1, frames=[0, 1, 2, 3], xy=[(10.0, 10.0)] * 4)
    lone = Track(2, frames=[0, 1], xy=[(80.0, 50.0)] * 2)  # nobody on the broadcast near him
    near = Track(10, frames=[0, 1, 2], xy=[(10.4, 10.0)] * 3, team="away", side_confidence=0.9)
    brief = Track(11, frames=[3], xy=[(10.2, 10.0)], team="home", side_confidence=0.99)
    far = Track(12, frames=[0, 1, 2, 3], xy=[(11.5, 10.0)] * 4, team="home", side_confidence=0.99)
    inherit([tac, lone], [near, brief, far])
    assert (tac.team, tac.side_confidence) == ("away", 0.9)
    assert lone.team is None and lone.side_confidence is None


# The scoring behind every number (the merge queue's review): pairing, a track's true team, the summary.
RED, BLUE = [200.0, 30.0, 40.0], [40.0, 60.0, 190.0]


def test_pairing_is_one_to_one_nearest_first_within_the_strict_radius():
    from ninety.eval.sides_tactical import _pair

    truth = [{"x": 10.0, "y": 10.0, "team": "home"}, {"x": 11.6, "y": 10.0, "team": "away"}]
    # Detection 0 is 0.3 m from the home player, 1.3 m from the away one; detection 1 is 0.6 m from
    # the home player and 1.0 m (the radius, kept) from the away one. Nearest first: 0 takes home,
    # so 1 takes away, not home.
    got = _pair([(0, 10.3, 10.0), (1, 10.6, 10.0)], truth)
    assert {i: p["team"] for i, p in got.items()} == {0: "home", 1: "away"}
    # Two detections near one player: the nearer has him, the other nobody.
    assert list(_pair([(0, 10.8, 10.0), (1, 10.3, 10.0)], truth[:1])) == [1]
    # Just beyond the radius pairs with nobody.
    assert _pair([(0, 12.61, 10.0)], truth[1:]) == {}


def obs(frames, players):
    """players: (x, y, rgb), standing still."""
    return [{"frame": f, "t": f / 25, "camera": {"ok": True, "P": None},
             "players": [{"bbox": [20 * i, 0, 20 * i + 10, 30], "score": 0.9, "x": x, "y": y, "rgb": c}
                         for i, (x, y, c) in enumerate(players)], "ball": []} for f in range(frames)]


def test_a_tracks_true_team_needs_half_its_frames_paired():
    from ninety.eval.sides_tactical import clip_tracks

    players = [(30.0, 20.0, BLUE), (30.0, 40.0, BLUE), (70.0, 20.0, RED), (70.0, 40.0, RED)]
    truth = {}
    for f in range(10):
        truth[f] = [{"x": 30.0, "y": 20.5, "team": "home"},  # always 0.5 m away: paired
                    {"x": 70.0, "y": 21.5, "team": "away"}]  # 1.5 m away: never paired
        if f < 5:
            truth[f].append({"x": 30.0, "y": 40.0, "team": "home"})  # 5 of 10 frames: enough
        if f < 4:
            truth[f].append({"x": 70.0, "y": 40.0, "team": "away"})  # 4 of 10 frames: not enough
    tracks, _ = clip_tracks(obs(10, players), truth)
    by_place = {(t["frames"], t["paired"]): t["true_team"] for t in tracks}
    assert len(tracks) == 4 and by_place == {(10, 10): "home", (10, 0): None, (10, 5): "home", (10, 4): None}


def test_a_track_shorter_than_the_events_stage_uses_is_not_scored():
    from ninety.eval.sides_tactical import clip_tracks
    from ninety.vision.tracked_frames import MIN_TRACK_FRAMES

    players = [(30.0, 20.0, BLUE), (70.0, 20.0, RED)]
    truth = {f: [{"x": 30.0, "y": 20.0, "team": "home"}, {"x": 70.0, "y": 20.0, "team": "away"}]
             for f in range(10)}
    assert len(clip_tracks(obs(MIN_TRACK_FRAMES, players), truth)[0]) == 2
    assert clip_tracks(obs(MIN_TRACK_FRAMES - 1, players), truth)[0] == []


def t(team, true, frames, conf, keeper=False):
    return {"team": team, "true_team": true, "frames": frames, "confidence": conf, "keeper": keeper}


def test_the_summary_weights_by_frames_and_keeps_keepers_and_unmatched_apart():
    from ninety.eval.sides_tactical import summarise

    clips = {
        1: [t("home", "home", 90, 0.99), t("away", "home", 10, 0.97),  # 0.90 right: sound
            t("home", None, 50, 0.5), t("away", "home", 40, 0.9, keeper=True)],
        2: [t("home", "away", 60, 0.95), t("away", "away", 40, 0.6)],  # 0.40 right: flipped
        3: [t("home", "home", 70, 0.7), t("away", "home", 30, 0.8)],  # 0.70: neither
    }
    s = summarise(clips)
    assert s["outfield"]["track_frames"] == 300 and s["outfield"]["right"] == 200
    assert s["outfield"]["accuracy"] == round(200 / 300, 4) and s["outfield"]["unmatched_tracks"] == 1
    assert (s["keeper"]["track_frames"], s["keeper"]["right"]) == (40, 0)
    assert (s["sound_clips"], s["flipped_clips"]) == (1, 1)
    c = s["confidence"]
    assert (c["n_right"], c["n_wrong"], c["largest_wrong"]) == (3, 3, 0.97)
    assert c["right_above_0.96"] == round(1 / 3, 4) and c["right_above_largest_wrong"] == round(1 / 3, 4)
    # Wrong 0.97, 0.95, 0.8 against right 0.99, 0.6, 0.7: 3 of 9 pairs put the wrong one lower.
    assert c["ordering"] == round(3 / 9, 4)


def test_a_clip_at_the_sound_share_is_sound_and_at_half_is_not_flipped():
    from ninety.eval.sides_tactical import SOUND_SHARE, summarise

    sound = {1: [t("home", "home", 80, 0.9), t("home", "away", 20, 0.9)]}
    assert SOUND_SHARE == 0.80 and summarise(sound)["sound_clips"] == 1
    half = {1: [t("home", "home", 50, 0.9), t("home", "away", 50, 0.9)]}
    assert (summarise(half)["sound_clips"], summarise(half)["flipped_clips"]) == (0, 0)
