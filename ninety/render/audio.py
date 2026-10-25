"""The broadcast's sound, all synthesised here, so no recording or third-party sound is used: the
referee's whistle (at each foul, lesson 234; at each kick-off; two blasts at half-time and three at
full-time, Law 5's signals by common practice) and a crowd under it, a low murmur that swells at a
goal and a little at a shot. Only the viewing copy (clip.mp4) carries it; training reads the JPEGs,
which have no sound.

A pea whistle is a tone of about 3 kHz that the pea inside makes flutter many times a second, in pitch
and in loudness (*design*: the numbers below are chosen by ear to read as a whistle, not measured).
"""

from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path

RATE = 44_100  # samples a second
WHISTLE_S = 0.42  # one short blast
TONE_HZ = 3_150.0
FLUTTER_HZ = 28.0  # the pea's trill
FLUTTER_PITCH_HZ = 140.0  # how far the trill swings the pitch
FLUTTER_DEPTH = 0.35  # how far it swings the loudness
ATTACK_S, RELEASE_S = 0.02, 0.08
LEVEL = 0.5  # of full scale, so the blast is clear and never clips
LONG_S = 1.1  # the long blast that ends a half (*design*)
GAP_S = 0.18  # between the blasts of one call
# A call is its blasts' lengths: a foul or a kick-off one short blast, half-time a short then a long
# one, full-time two short then a long one (*design*, by common refereeing practice).
CALLS = {"foul": (WHISTLE_S,), "kickoff": (WHISTLE_S,), "half_time": (WHISTLE_S, LONG_S),
         "full_time": (WHISTLE_S, WHISTLE_S, LONG_S)}
# The crowd (*design*, by ear: tasteful and low under the picture, never over the whistle). A murmur
# of low-passed noise breathing slowly, at CROWD_LEVEL; a goal lifts it to GOAL_LEVEL for about
# GOAL_S, a shot to SHOT_LEVEL for about SHOT_S, each rising fast and dying away slowly.
CROWD_LEVEL = 0.05
GOAL_LEVEL, GOAL_S = 0.28, 7.0
SHOT_LEVEL, SHOT_S = 0.12, 2.5
SWELL_RISE_S = 0.35


def whistle(seed: int = 0, seconds: float = WHISTLE_S) -> list[float]:
    """One blast, samples in -1..1. A little breath noise, from a fixed seed, so it is the same every time."""
    rng = random.Random(f"whistle-{seed}")
    n = int(seconds * RATE)
    out, phase = [], 0.0
    for i in range(n):
        t = i / RATE
        flutter = math.sin(2 * math.pi * FLUTTER_HZ * t)
        phase += 2 * math.pi * (TONE_HZ + FLUTTER_PITCH_HZ * flutter) / RATE
        env = min(1.0, t / ATTACK_S, (seconds - t) / RELEASE_S)
        amp = env * (1.0 - FLUTTER_DEPTH * 0.5 * (1.0 + flutter))
        out.append(LEVEL * amp * (math.sin(phase) + 0.08 * (rng.random() * 2.0 - 1.0)))
    return out


def track(seconds: float, at: list[float]) -> list[float]:
    """A silent track `seconds` long with a whistle starting at each time in `at`."""
    out = [0.0] * int(round(seconds * RATE))
    blast = whistle()
    for t in at:
        s = int(round(t * RATE))
        for j, v in enumerate(blast):
            if 0 <= s + j < len(out):
                out[s + j] = max(-1.0, min(1.0, out[s + j] + v))
    return out


def call(kind: str) -> list[float]:
    """A referee's call: its blasts one after another, GAP_S apart."""
    out: list[float] = []
    for k, length in enumerate(CALLS[kind]):
        if k:
            out += [0.0] * int(GAP_S * RATE)
        out += whistle(k, length)
    return out


def swell(t: float, at: float, level: float, seconds: float) -> float:
    """How far a swell started at `at` lifts the crowd at time t: up over SWELL_RISE_S, then away."""
    u = t - at
    if u < 0 or u > seconds:
        return 0.0
    return level * min(1.0, u / SWELL_RISE_S) * (1.0 - u / seconds) ** 2


def crowd(seconds: float, goals: list[float], shots: list[float], seed: int = 0) -> list[float]:
    """The crowd for `seconds`: low-passed noise (a murmur, not a hiss), breathing slowly, lifted at
    each goal and shot time. The same for the same arguments."""
    rng = random.Random(f"crowd-{seed}")
    n = int(round(seconds * RATE))
    out = [0.0] * n
    lp = 0.0
    a_lp = 0.12  # a one-pole low-pass over white noise, about 850 Hz at 44.1 kHz: a murmur (*design*)
    breathe = [(rng.uniform(0.05, 0.2), rng.uniform(0, 2 * math.pi)) for _ in range(3)]
    events = [(g, GOAL_LEVEL, GOAL_S) for g in goals] + [(s, SHOT_LEVEL, SHOT_S) for s in shots]
    step = RATE // 50  # the level is worked out 50 times a second and held between
    level = CROWD_LEVEL
    for i in range(n):
        if i % step == 0:
            t = i / RATE
            wave_ = 1.0 + 0.25 * sum(math.sin(2 * math.pi * f * t + ph) for f, ph in breathe) / 3
            level = CROWD_LEVEL * wave_ + sum(swell(t, at, lv, sec) for at, lv, sec in events)
        lp += a_lp * ((rng.random() * 2.0 - 1.0) - lp)
        out[i] = level * 2.5 * lp  # the low-pass takes the noise to about 0.4 of full swing
    return out


def mix(seconds: float, calls: list[tuple[float, str]], goals: list[float],
        shots: list[float]) -> list[float]:
    """The sound track: the crowd, and each call (time, kind) over it, clipped to -1..1."""
    out = crowd(seconds, goals, shots)
    for t, kind in calls:
        s = int(round(t * RATE))
        for j, v in enumerate(call(kind)):
            if 0 <= s + j < len(out):
                out[s + j] = out[s + j] + v
    return [max(-1.0, min(1.0, v)) for v in out]


def write_wav(path: Path, samples: list[float]) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(round(v * 32767))) for v in samples))
