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
