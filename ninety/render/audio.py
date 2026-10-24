"""The broadcast's sound: a referee's whistle at each foul (lesson 234), synthesised here, so no
recording or third-party sound is used. Only the viewing copy (clip.mp4) carries it; training reads
the JPEGs, which have no sound.

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


def whistle(seed: int = 0) -> list[float]:
    """One blast, samples in -1..1. A little breath noise, from a fixed seed, so it is the same every time."""
    rng = random.Random(f"whistle-{seed}")
    n = int(WHISTLE_S * RATE)
    out, phase = [], 0.0
    for i in range(n):
        t = i / RATE
        flutter = math.sin(2 * math.pi * FLUTTER_HZ * t)
        phase += 2 * math.pi * (TONE_HZ + FLUTTER_PITCH_HZ * flutter) / RATE
        env = min(1.0, t / ATTACK_S, (WHISTLE_S - t) / RELEASE_S)
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


def write_wav(path: Path, samples: list[float]) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(round(v * 32767))) for v in samples))
