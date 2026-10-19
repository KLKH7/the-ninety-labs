"""The served matches' frames (ninety/match/tracking.py)."""

import pytest

from ninety.match import tracking
from ninety.sim import engine


def test_the_frame_rate_is_the_engines():
    assert tracking.FPS == engine.FPS


def test_a_track_refuses_frames_from_two_sources():
    frames = ({"frame": 0, "t": 0.0, "source": "truth", "players": []},
              {"frame": 1, "t": 0.04, "source": "tracked", "players": []})
    with pytest.raises(ValueError, match="mix sources"):
        tracking.Track("x", frames).source
