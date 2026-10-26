"""The demo re-render's additions (0.5.19): the referee's calls and the crowd on the sound track,
the half-time and full-time card, a stinger at a clip's own ends, and the kits as given."""

import statistics

import pytest

from ninety.render import audio, clip, edit
from ninety.render.params import sample_params
from ninety.sim.pacing import MATCH_S


def test_each_call_is_its_blasts():
    """A kick-off is one short blast; half-time a short then a long one; full-time two short and a long."""
    one = len(audio.call("kickoff")) / audio.RATE
    assert one == pytest.approx(audio.WHISTLE_S, abs=1e-3)
    assert len(audio.call("half_time")) / audio.RATE == pytest.approx(
        audio.WHISTLE_S + audio.GAP_S + audio.LONG_S, abs=1e-3)
    assert len(audio.call("full_time")) / audio.RATE == pytest.approx(
        2 * audio.WHISTLE_S + 2 * audio.GAP_S + audio.LONG_S, abs=1e-3)


def test_the_crowd_is_low_swells_at_a_goal_more_than_at_a_shot_and_never_clips():
    seconds = 30.0
    track = audio.mix(seconds, [(1.0, "kickoff")], goals=[10.0], shots=[20.0])
    assert max(abs(v) for v in track) <= 1.0

    def rms(a, b):
        return statistics.pstdev(track[int(a * audio.RATE):int(b * audio.RATE)])

    quiet, goal, shot = rms(3, 5), rms(10.5, 12), rms(20.4, 21.4)
    assert quiet < 0.03  # a murmur, under the whistle's 0.5
    assert goal > 3 * quiet and goal > shot > 1.5 * quiet
    assert audio.mix(seconds, [], [10.0], [20.0]) == audio.mix(seconds, [], [10.0], [20.0])  # repeatable


def test_the_card_reads_half_time_through_the_interval_and_full_time_from_the_final_whistle():
    events = [{"type": "kickoff", "t": 1.7}, {"type": "half_time", "t": 2700.04},
              {"type": "kickoff", "t": 2705.84}]
    half, final = clip.periods(events)
    assert half == (2700.04, 2705.84) and final == MATCH_S - clip.FT_LEAD_S
    assert clip.period_card(2699.9, half, final) is None
    assert clip.period_card(2700.04, half, final) == "HALF-TIME"
    assert clip.period_card(2705.8, half, final) == "HALF-TIME"
    assert clip.period_card(2705.84, half, final) is None
    assert clip.period_card(final - 0.04, half, final) is None
    assert clip.period_card(final, half, final) == "FULL-TIME"
    assert clip.periods([{"type": "kickoff", "t": 1.0}]) == (None, final)  # no half_time event: no card


def test_a_clip_s_ends_carry_half_a_stinger_each_so_two_joined_show_one():
    n, fps = 100, 25
    ends = edit.edge_stingers(n, fps)
    half = round(edit.STINGER_S * fps / 2)
    assert sorted(ends) == list(range(half)) + list(range(n - half, n))
    assert all(0 < ends[k] < 1 for k in range(half)) and all(-1 < ends[n - 1 - k] < 0 for k in range(half))
    # the end of one clip and the start of the next read as one stinger through 0 at the join
    joined = [ends[i] for i in range(n - half, n)] + [ends[i] for i in range(half)]
    assert joined == sorted(joined)


def test_the_demo_kits_as_given_pass_and_crest_crimson_is_refused():
    """Kian's choice for 8080 (A): London navy #1B2F5B, white shorts; Lisbon crimson lifted to
    #E63942 (the crest's #B3202A is 1.97:1 on navy, under 3:1), dark crimson shorts; keepers yellow
    and teal. Given as kit overrides, they pass the broadcast rule; the crest's own crimson does not."""
    a = dict(kit_contrast="broadcast", home_kit="#1B2F5B/#ffffff/#1B2F5B", away_kit="#E63942/#7A0F16/#E63942",
             home_pattern="solid", away_pattern="solid", home_gk="#F2E205/#111111/#F2E205",
             away_gk="#2BD9C3/#111111/#2BD9C3")
    p = sample_params(8080, **a)
    assert (p.home_kit.shirt, p.away_kit.shirt) == ("#1b2f5b", "#e63942")
    with pytest.raises(ValueError, match="lesson 246"):
        sample_params(8080, **{**a, "away_kit": "#B3202A/#7A0F16/#B3202A"})
    with pytest.raises(ValueError, match="shirt/shorts/socks"):
        sample_params(8080, **{**a, "home_kit": "navy"})
