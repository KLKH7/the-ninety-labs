"""The player-ID feed: a simulated optical-tracking provider's live feed, exported from the match engine.

Vision cannot tell who a player is on our renders: shirt numbers are a few pixels tall and naming
by role missed its gate (docs/eval/naming.json). Real broadcasts do not read names off pixels
either: they license player identity from an optical tracking provider. Kian decided on Oct 26
that the demo names players this way, openly (AGENTS.md, hard rules; docs/LESSONS.md, lesson 269).

This module simulates that provider's feed (docs/FEED_SPEC.md). It is the ONLY engine output the
live path may read, and the live path reads it for identity and side only (ninety/intel/identity.py).
Like a real feed it is imperfect, seeded so a seed always gives the same feed:

- 25 Hz frames, pitch-centred metres, each player with his team, shirt and provider id;
- position noise at the error a certified provider measures (NOISE_M);
- a player dropped for a few frames now and then when another stands on top of him (occlusion),
  flagged low confidence for a second after he is picked up again;
- now and then two team-mates close together swap ids, and the provider's operator corrects it a
  few seconds later with an `id_correction` row (the swapped frames stay as they were delivered);
- every row is delivered LATENCY_S after it was captured, so a consumer aligns by the capture time
  `t`, never by arrival order.

It carries no ball, no event, no velocity, no action and no score.

    uv run python -m ninety.sim.identity_feed --run <ninety-sim out dir> --home-code LON \\
        --away-code LIS --out identity_feed.jsonl
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import random
from collections.abc import Iterable, Mapping
from pathlib import Path

from ninety.intel.teamsheet import Fixture

SCHEMA = "ninety-id-feed/2"
PROVIDER = "simulated optical tracking provider (seeded from the match engine)"
PITCH_M = (105.0, 68.0)  # Law 1, our pitch (ninety/sim/engine PITCH_X, PITCH_Y)
FPS = 25  # GROUNDING ID1 (Linke, Link & Lames 2020): TRACAB tracks at 25 Hz
NOISE_M = 0.08  # GROUNDING ID2 (Linke, Link & Lames 2020): TRACAB Gen5 position RMSE 0.08 m
NOISE_RHO = 0.95  # design (ID2): a tracker's error drifts frame to frame, it does not jitter
LATENCY_S = 15.0  # GROUNDING ID3 (SciSports): the live TRACAB stream is held ~15 s for operator corrections
JITTER_S = 0.04  # design (ID3): delivery jitter up to one frame, so rows can arrive out of order
OCCLUDED_M = 0.75  # design (ID4): another player this close hides a player from most cameras
DROP_PER_S = 0.2  # design (ID4): while occluded, a dropout starts at this rate
DROP_FRAMES = (3, 12)  # design (ID4): a dropout lasts 0.12 to 0.48 s
LOW_FRAMES = 25  # design (ID5): one second of low confidence after a player is picked up again
SWAP_M = 1.0  # design (ID6): only team-mates this close can be confused (overlaps cause identity errors)
SWAP_PER_S = 0.02  # design (ID6): rare; a close pair swaps at this rate per second together
SWAP_S = (2.0, 6.0)  # design (ID7): the operator corrects a swap after a few seconds
DECIMALS = 2  # design: centimetres, as providers deliver


def pid(code: str, number: int) -> str:
    """The provider's player id: club code and shirt (not the engine's id)."""
    return f"{code}{number:02d}"


def roster(engine_roster: Iterable[Mapping], fixture: Fixture) -> tuple[list[dict], dict[str, str]]:
    """The metadata's team sheets, and engine id -> provider id."""
    codes = {"home": fixture.home_code, "away": fixture.away_code}
    sheets = {t: {s.role: s for s in fixture.sheet(t)} for t in codes}
    out, ids = [], {}
    for r in engine_roster:
        s = sheets[r["team"]][r["role"]]
        ids[r["id"]] = pid(codes[r["team"]], s.number)
        out.append({"player_id": ids[r["id"]], "team": r["team"], "jersey": s.number, "name": s.name,
                    "position": s.position})
    return out, ids


def metadata(fixture: Fixture, players: list[dict], half_time: float | None, seed_feed: int) -> dict:
    return {
        "type": "metadata", "schema": SCHEMA, "provider": PROVIDER, "fps": FPS,
        "pitch": {"length": PITCH_M[0], "width": PITCH_M[1], "origin": "centre", "units": "m"},
        "kickoff": "2026-10-24T15:00:00Z",  # design: a fictional fixture's kick-off
        "periods": [{"period": 1, "start_t": 0.0},
                    *([{"period": 2, "start_t": half_time}] if half_time is not None else [])],
        "teams": {t: {"club": fixture.clubs[t], "code": c} for t, c in
                  (("home", fixture.home_code), ("away", fixture.away_code))},
        "players": players, "latency_s": LATENCY_S, "noise_m": NOISE_M, "feed_seed": seed_feed,
    }


def rows(frames: Iterable[Mapping], ids: Mapping[str, str], teams: Mapping[str, str],
         numbers: Mapping[str, int], half_time: float | None, seed: int) -> Iterable[dict]:
    """Frame rows and id_correction rows, each with its capture time `t` and delivery time."""
    rng = random.Random(f"id-feed-{seed}")
    dt = 1.0 / FPS
    axis = NOISE_M / math.sqrt(2)  # an RMSE of NOISE_M in the plane is NOISE_M / sqrt 2 on each axis
    s = axis * math.sqrt(1 - NOISE_RHO ** 2)  # AR(1) innovations whose stationary sd is `axis`
    noise: dict[str, tuple[float, float]] = {}
    dropped: dict[str, int] = {}  # id -> frames left
    low: dict[str, int] = {}  # id -> low-confidence frames left
    swaps: list[dict] = []  # open swaps: {"a", "b", "from_t", "end_t"}
    for f in frames:
        t = float(f["t"])
        period = 2 if half_time is not None and t >= half_time else 1
        clock = t - (half_time if period == 2 else 0.0)
        ps = f["players"]
        pos = {p["id"]: (p["x"], p["y"]) for p in ps}
        for done in [w for w in swaps if t >= w["end_t"]]:
            swaps.remove(done)
            yield {"type": "id_correction", "t": round(t, 3),
                   "delivered": round(t + LATENCY_S + rng.uniform(0, JITTER_S), 3),
                   "player_ids": [ids[done["a"]], ids[done["b"]]], "from_t": round(done["from_t"], 3),
                   "to_t": round(t, 3)}
        busy = {i for w in swaps for i in (w["a"], w["b"])}
        near: dict[str, float] = {}
        for i, p in enumerate(ps):
            for q in ps[i + 1:]:
                d = math.dist((p["x"], p["y"]), (q["x"], q["y"]))
                near[p["id"]] = min(near.get(p["id"], 99.0), d)
                near[q["id"]] = min(near.get(q["id"], 99.0), d)
                if (d < SWAP_M and p["team"] == q["team"] and p["id"] not in busy and q["id"] not in busy
                        and rng.random() < SWAP_PER_S * dt):
                    swaps.append({"a": p["id"], "b": q["id"], "from_t": t, "end_t": t + rng.uniform(*SWAP_S)})
                    busy |= {p["id"], q["id"]}
        label = {i: i for i in pos}
        for w in swaps:
            label[w["a"]], label[w["b"]] = w["b"], w["a"]
        out = []
        for p in ps:
            i = p["id"]
            nx, ny = noise.get(i, (rng.gauss(0, axis), rng.gauss(0, axis)))
            noise[i] = (NOISE_RHO * nx + rng.gauss(0, s), NOISE_RHO * ny + rng.gauss(0, s))
            if dropped.get(i):
                dropped[i] -= 1
                if not dropped[i]:
                    low[i] = LOW_FRAMES
                continue
            if near.get(i, 99.0) < OCCLUDED_M and rng.random() < DROP_PER_S * dt:
                dropped[i] = rng.randint(*DROP_FRAMES)
                continue
            conf = 0 if low.get(i) else 1
            if low.get(i):
                low[i] -= 1
            shown = label[i]  # the id the provider believes is here
            out.append([ids[shown], teams[shown], numbers[shown],
                        round(p["x"] + noise[i][0] - PITCH_M[0] / 2, DECIMALS),
                        round(p["y"] + noise[i][1] - PITCH_M[1] / 2, DECIMALS), conf])
        yield {"type": "frame", "frame_id": int(f["frame"]), "period": period, "game_clock": round(clock, 2),
               "t": round(t, 3), "delivered": round(t + LATENCY_S + rng.uniform(0, JITTER_S), 3),
               "players": out}


def write(path: Path, engine_roster: list[Mapping], frames: Iterable[Mapping], fixture: Fixture,
          half_time: float | None, seed: int | None = None) -> dict:
    """Write the feed in delivery order; returns counts of frames, corrections and dropouts."""
    seed = fixture.seed if seed is None else seed
    players, ids = roster(engine_roster, fixture)
    teams = {r["id"]: r["team"] for r in engine_roster}
    jersey = {p["player_id"]: p["jersey"] for p in players}
    numbers = {i: jersey[ids[i]] for i in ids}
    n = {"frames": 0, "id_corrections": 0}
    with Path(path).open("w") as fh:
        fh.write(json.dumps(metadata(fixture, players, half_time, seed), separators=(",", ":")) + "\n")
        pending: list[tuple[float, int, str]] = []  # (delivered, order, line): written as they arrive
        for k, r in enumerate(rows(frames, ids, teams, numbers, half_time, seed)):
            n["frames" if r["type"] == "frame" else "id_corrections"] += 1
            heapq.heappush(pending, (r["delivered"], k, json.dumps(r, separators=(",", ":"))))
            while pending and pending[0][0] <= r["delivered"] - 2 * JITTER_S:  # nothing later can precede it
                fh.write(heapq.heappop(pending)[2] + "\n")
        while pending:
            fh.write(heapq.heappop(pending)[2] + "\n")
    return n


def _run(run: Path) -> tuple[dict, Iterable[dict], float | None]:
    meta = json.loads((run / "meta.json").read_text())
    half = None
    with (run / "events.jsonl").open() as fh:  # the period boundary only: the feed carries no event
        for line in fh:
            if '"half_time"' in line:
                half = float(json.loads(line)["t"])
                break

    def frames():
        with (run / "frames.jsonl").open() as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)

    return meta, frames(), half


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Export the simulated tracking provider's player-ID feed.")
    ap.add_argument("--run", type=Path, required=True, help="a ninety-sim output directory")
    ap.add_argument("--home-code", required=True, help="the render's home club code (clip.json params)")
    ap.add_argument("--away-code", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--feed-seed", type=int, default=None, help="the feed's own seed (default: the match's)")
    args = ap.parse_args(argv)
    meta, frames, half = _run(args.run)
    fixture = Fixture(int(meta["seed"]), args.home_code, args.away_code)
    n = write(args.out, meta["roster"], frames, fixture, half, args.feed_seed)
    print(f"{args.out}: {n['frames']} frames at {FPS} Hz, {n['id_corrections']} id corrections, "
          f"seed {fixture.seed}")


if __name__ == "__main__":
    main()
