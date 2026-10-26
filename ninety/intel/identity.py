"""Who a tracked player is, and his side, from the player-ID feed: vision's tracks matched to it.

Vision does not identify players: shirt numbers are a few pixels tall on our renders, and naming
by role missed its gate (docs/eval/naming.json). As real broadcasts license identity from an
optical tracking provider, the demo names players from a simulated provider's feed
(ninety/sim/identity_feed.py, docs/FEED_SPEC.md; AGENTS.md, hard rules; docs/LESSONS.md, lesson 269).
The feed is the one engine output the live path reads, and it is read here only, for identity and
side: which vision track is which player, and so which club an event's player plays for. Nothing
here returns a position or a statistic, and nothing the feed says becomes an event, a position or
an outcome (tests/test_identity_feed.py).

1. **Aligned by capture time.** Each tactical frame (tracked.json, after the camera join) is
   matched to the feed row captured at the same time, whatever order rows arrived in. Every
   `id_correction` is applied to the frames it covers; low-confidence entries are skipped.
2. **One to one, per window, on the same side.** Within each window of WINDOW_S seconds of a
   segment, a side's tracks are matched to that side's feed players by the Hungarian method. A
   pair counts only if their mean distance over the frames both are seen is at most GATE_M,
   vision's measured position error (ninety/vision/events.RIVAL_M), a track may be matched to
   nobody, and the matching keeps the most shared frames, each discounted by the pair's mean
   distance over the gate: a short fragment never takes a player from a track that follows him
   for the whole window, and a track on a man is not given the team-mate beside him. A track
   read on the wrong side is
   never given a player of the other side, so it stays unnamed.
3. **Carried along the track.** A track is the player it was matched to for a strict majority of
   its frames on the feed; its `share` is that fraction.
4. **One track per player at a time.** Tracks given one player that overlap in time cannot all
   be him: the non-overlapping set with the most frames keeps him (naming.keep_apart).
5. **Names cross the camera join (lesson 259).** Events name the broadcast's tracks, another id
   space. A broadcast track takes the player of the tactical track its association pairs it with
   (naming.tactical: at least the association gate and the same side), never by its id string.
6. **The broadcast camera, directly.** As broadcasts match a provider's feed to their own
   calibrated camera, the broadcast's tracks (in pitch metres, only in frames that passed the
   camera trust test) are matched to the feed too, by steps 1-4 with one change: both sides'
   players are candidates, since the broadcast's side is what the feed supplies. Pre-registered
   in docs/eval/identity-direct-plan.md.
7. **Combined.** A broadcast track named both through the join and directly takes the more
   confident: the direct share against the tactical share times the association's confidence.
8. **Side.** An event whose player is named takes his side from the feed (`team_source`
   id_feed, confidence 1.0); every other field of every event is left as vision detected it.
   Since a track is matched only on its own side, this mostly confirms the side vision's track
   reads, now surely, and corrects an event whose side disagreed with its player's track. A sure
   side reaches whatever reads sides (the fact-checker's side gate, possession share): that is
   the feed's one effect on a statistic, and it is allowed (AGENTS.md).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from ninety.intel import naming, roles
from ninety.intel.teamsheet import Fixture
from ninety.vision.events import RIVAL_M

SCHEMA = "ninety-id-feed/2"  # ninety/sim/identity_feed.SCHEMA (the live path may not import the simulator)
SOURCE = "id_feed"  # how every name and side from here is marked
SOURCE_LABEL = "Player ID feed"  # what a fan is told the name comes from
DISCLOSURE = ("Names come from a simulated tracking-provider ID feed; vision does not identify "
              "players. We simulate that feed, including occasional identity swaps that get corrected.")
GATE_M = RIVAL_M  # measured: vision's pooled 90th-percentile pitch-position error (EVALUATION.md)
WINDOW_S = naming.WINDOW_S  # design: the window naming.py matches in
FPS = 25  # vision's frames are the broadcast's 25 fps (ninety/intel/scene.FPS)
META_KEYS = {"type", "schema", "provider", "seed", "fps", "pitch", "kickoff", "periods", "teams",
             "players", "latency_s", "noise_m", "feed_seed"}
PLAYER_KEYS = {"player_id", "team", "jersey", "name", "position"}
FRAME_KEYS = {"type", "frame_id", "period", "game_clock", "t", "delivered", "players"}
CORRECTION_KEYS = {"type", "t", "delivered", "player_ids", "from_t", "to_t"}
ENTRY = 6  # player_id, team, jersey, x, y, confidence
# In the package, not docs/: the image copies ninety/ only (docs/LESSONS.md, lesson 100).
CALIBRATION = Path(__file__).resolve().parent / "identity_calibration.json"


def _key(t: float) -> int:
    return round(float(t) * FPS)


class Feed:
    """A loaded feed: its metadata, its players by id, and per capture frame each id's (x, y) in
    our pitch metres (0 to 105, 0 to 68), corrections applied and low-confidence entries dropped."""

    def __init__(self, meta: Mapping, at: Mapping[int, Mapping[str, tuple[float, float]]], corrections: int):
        self.meta = dict(meta)
        self.roster = {p["player_id"]: dict(p) for p in meta["players"]}
        self.at = dict(at)
        self.corrections = corrections

    def positions(self, t: float) -> Mapping[str, tuple[float, float]]:
        """Each confident id's position at capture time `t`; {} where the feed has no row."""
        return self.at.get(_key(t), {})

    def matches(self, fixture: Fixture) -> bool:
        """The same match: its seed (the team sheets' names come from it) and its two clubs."""
        teams = self.meta["teams"]
        return (self.meta.get("seed"), teams["home"]["code"], teams["away"]["code"]) == (
            fixture.seed, fixture.home_code, fixture.away_code)


def _refuse(path, what) -> None:
    raise ValueError(f"{path}: an identity feed carries identity only; {what}")


def load(path: Path, times: Sequence[float] | None = None) -> Feed:
    """Read a feed, keeping only the rows captured at `times` (all when None), refusing any file
    that carries more than identity (a ball, an event, a speed)."""
    keep = None if times is None else {_key(t) for t in times}
    rows: dict[int, list] = {}
    corrections: list[dict] = []
    with Path(path).open() as fh:
        meta = json.loads(fh.readline() or "{}")
        if meta.get("type") != "metadata" or meta.get("schema") != SCHEMA:
            raise ValueError(f"{path}: not an identity feed (line 1 must be {SCHEMA} metadata)")
        if set(meta) - META_KEYS or any(set(p) != PLAYER_KEYS for p in meta["players"]):
            _refuse(path, "extra metadata fields")
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            kind = r.get("type")
            if kind == "frame":
                if set(r) - FRAME_KEYS or any(len(e) != ENTRY for e in r["players"]):
                    _refuse(path, f"extra frame fields {sorted(set(r) - FRAME_KEYS)}")
                k = _key(r["t"])
                if keep is None or k in keep:
                    rows[k] = r["players"]
            elif kind == "id_correction":
                if set(r) != CORRECTION_KEYS:
                    _refuse(path, f"correction fields {sorted(r)}")
                corrections.append(r)
            else:
                _refuse(path, f"a row of type {kind!r}")
    for c in corrections:  # the provider says these two were swapped over [from_t, to_t)
        a, b = c["player_ids"]
        lo, hi = _key(c["from_t"]), _key(c["to_t"])
        for k, entries in rows.items():
            if lo <= k < hi:
                for e in entries:
                    if e[0] == a:
                        e[0] = b
                    elif e[0] == b:
                        e[0] = a
    cx, cy = meta["pitch"]["length"] / 2, meta["pitch"]["width"] / 2
    at = {k: {e[0]: (e[3] + cx, e[4] + cy) for e in entries if e[5] == 1} for k, entries in rows.items()}
    return Feed(meta, at, len(corrections))


def assign(frames: Sequence[Mapping], feed: Feed, window_s: float = WINDOW_S,
           gate_m: float = GATE_M, any_side: bool = False, one_at_a_time: bool = True) -> dict[str, dict]:
    """Each track the feed names: its feed id, share and span (steps 2-4). With `any_side`, both
    sides' feed players are candidates for every track (step 6)."""
    team_of = {i: r["team"] for i, r in feed.roster.items()}
    # (segment, window, side) -> track -> feed id -> [distance sum, frames]
    sums: dict[tuple, dict[str, dict[str, list]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(
        lambda: [0.0, 0])))
    seen: Counter = Counter()
    spans: dict[str, tuple[float, float]] = {}
    for f in frames:
        pos = feed.positions(f["t"])
        if not pos:
            continue
        t = float(f["t"])
        for p in f["players"]:
            track, side = p["id"], p["team"]
            seen[track] += 1
            t0, t1 = spans.get(track, (t, t))
            spans[track] = (min(t0, t), max(t1, t))
            cell = sums[(naming.segment(track), int(t // window_s), "any" if any_side else side)][track]
            for i, (x, y) in pos.items():
                if any_side or team_of.get(i) == side:
                    d = cell[i]
                    d[0] += ((p["x"] - x) ** 2 + (p["y"] - y) ** 2) ** 0.5
                    d[1] += 1
    votes: dict[str, Counter] = defaultdict(Counter)
    far = 1e9  # a pair never seen together, or further than the gate, is no pair
    for by_track in sums.values():
        ids = sorted({i for cell in by_track.values() for i in cell})  # the side's, as summed above
        tracks = sorted(by_track)

        def cost(tr: str, i: str, by_track=by_track) -> float:
            c = by_track[tr].get(i)
            if not c or c[0] / c[1] > gate_m:
                return far
            # design: a pair's gain is its shared frames, discounted by how far apart they are on
            # average (1 at 0 m, 0 at the gate): a track on a man all window beats a fragment on him,
            # and beats itself paired with a team-mate a metre away.
            return -c[1] * (1.0 - c[0] / c[1] / gate_m)

        # One "no player" column per track at cost 0 (as naming.match_windows): a track with no
        # pair within the gate takes one, and never forces another track onto the wrong man.
        m = [[cost(tr, i) for i in ids] + [0.0] * len(tracks) for tr in tracks]
        for k, j in enumerate(roles.hungarian(m)):
            if j < len(ids) and m[k][j] < far:
                votes[tracks[k]][ids[j]] += by_track[tracks[k]][ids[j]][1]
    out: dict[str, dict] = {}
    for track, w in votes.items():
        # design: on a tie of frames, the lower id, so the result never depends on dict order
        fid, n = min(w.items(), key=lambda kv: (-kv[1], kv[0]))
        if 2 * n <= seen[track]:
            continue  # not that player for most of its frames on the feed
        out[track] = {"id": fid, "share": round(n / seen[track], 3), "frames": n,
                      "span_s": round(spans[track][1] - spans[track][0], 1), "span": spans[track]}
    if not one_at_a_time:  # step 4 left out: for an evaluation's reasons only
        return out
    claims: dict[str, list] = defaultdict(list)
    for track, r in out.items():
        claims[r["id"]].append((track, *r["span"], r["frames"]))
    for group in claims.values():
        keep = naming.keep_apart(group)
        for track, *_ in group:
            if track not in keep:
                del out[track]
    return out


def tactical(frames: Sequence[Mapping], feed: Feed, any_side: bool = False) -> dict[str, dict]:
    """Each track the feed names: who he is, as a fan is told (the team sheet's label)."""
    out = {}
    for track, r in assign(frames, feed, any_side=any_side).items():
        who = feed.roster[r["id"]]
        out[track] = {"track": track, "team": who["team"], "player": r["id"], "name": who["name"],
                      "number": who["jersey"], "position": who["position"], "share": r["share"],
                      "span_s": r["span_s"], "source": SOURCE}
    return out


def gate(path: Path = CALIBRATION) -> dict:
    """The measured association gate (docs/eval/identity.json) a broadcast track's name crosses the
    camera join at; None (only pairings every paired frame agreed on, naming.tactical) unmeasured.
    `direct`: whether the direct path met its pre-registered gate (docs/eval/identity-direct-plan.md)."""
    try:
        body = json.loads(path.read_text())
    except FileNotFoundError:
        return {"association": None, "direct": False}
    return {"association": body.get("association") if body.get("held_out_met") else None,
            "direct": bool(body.get("direct_held_out_met"))}


def broadcast(association: Mapping[str, Mapping], named: Mapping[str, Mapping],
              gate: Mapping) -> dict[str, dict]:
    """Each broadcast track whose tactical track (through the association, step 5) is named."""
    out = {}
    for track, tv in naming.tactical(association, gate).items():
        w = named.get(tv)
        if w:
            out[track] = {**w, "track": track, "via": tv}
    return out


def broadcast_frames(vision: Path) -> list[dict]:
    """Every segment's broadcast tracked frames (pitch metres, only frames that passed the camera
    trust test), ids renumbered as the join renumbers them: segments in name order (step 6)."""
    from ninety.vision.match_join import renumber

    names = sorted(p.name for p in Path(vision).iterdir() if (p / "broadcast" / "tracked.json").is_file())
    out = []
    for k, name in enumerate(names):
        body = json.loads((Path(vision) / name / "broadcast" / "tracked.json").read_text())
        out += [renumber(f, k) for f in body["frames"]]
    return out


def _number(track: str) -> str:
    return track.split("-t", 1)[1]


def combined(ids: Sequence[str], via_join: Mapping[str, Mapping], direct: Mapping[str, Mapping],
             association: Mapping[str, Mapping]) -> dict[str, dict]:
    """Each event-space broadcast id its name (step 7): through the join, directly, or, named
    both ways, the more confident (direct share against tactical share x association confidence;
    a tie to the direct path). A track is found by its number, which the tracker gives once for
    both sides in a segment, since an event's id letter can differ from its track's."""
    by_num = {_number(t): w for t, w in direct.items()}
    out = {}
    for track in sorted(set(ids)):
        j, d = via_join.get(track), by_num.get(_number(track))
        if j is not None:
            j = {**j, "confidence": round(j["share"] * association[track].get("confidence", 0.0), 3),
                 "path": "join"}
        if d is not None:
            d = {**d, "track": track, "confidence": d["share"], "path": "direct"}
        pick = d if d is not None and (j is None or d["confidence"] >= j["confidence"]) else j
        if pick is not None:
            out[track] = pick
    return out


def event_ids(events: Sequence[Mapping], association: Mapping[str, Mapping]) -> list[str]:
    """The broadcast ids a line-up must cover: every person an event names, and the join's."""
    people = ("player", "receiver", "intended", "interceptor", "deflected_by")  # naming.PEOPLE
    return sorted({e[k] for e in events for k in people if e.get(k)} | set(association))


def sided(events: Sequence[Mapping], named_broadcast: Mapping[str, Mapping]) -> list[dict]:
    """The events, each whose player the feed names given his side (step 8); nothing else changes."""
    out = []
    for e in events:
        w = named_broadcast.get(e.get("player") or "")
        out.append({**e, "team": w["team"], "team_confidence": 1.0, "team_source": SOURCE} if w else dict(e))
    return out


def lineup(named: Mapping[str, Mapping]) -> list[dict]:
    """match.json line-up rows (ninety/e2e.read_lineup): one per named track, marked by its source."""
    return [{"id": t, "name": w["name"], "number": w["number"], "position": w["position"],
             "confident": True, "source": SOURCE} for t, w in sorted(named.items())]


def disclosure(feed: Feed) -> dict:
    """What the bundle says of where its names come from."""
    return {"source": SOURCE, "label": SOURCE_LABEL, "provider": feed.meta.get("provider"),
            "note": DISCLOSURE, "id_corrections": feed.corrections}


def load_for(path: Path, frames: Sequence[Mapping], fixture: Fixture) -> Feed:
    """The feed for these tracked frames, refused unless it is this fixture's."""
    feed = load(path, [f["t"] for f in frames])
    if not feed.matches(fixture):
        raise ValueError(f"{path}: the feed (seed {feed.meta.get('seed')}, {feed.meta['teams']}) is not "
                         f"this match's (seed {fixture.seed}, {fixture.home_code} v {fixture.away_code})")
    return feed


def main(argv: list[str] | None = None) -> None:
    """Write the detected events with the feed's sides (step 8), for match_insights and ninety-e2e."""
    from ninety.intel.match_insights import load_fixture

    ap = argparse.ArgumentParser(description="Give detected events their player's side from the ID feed.")
    ap.add_argument("--tracked", type=Path, required=True, help="the joined match's tracked.json")
    ap.add_argument("--association", type=Path, required=True)
    ap.add_argument("--detected", type=Path, required=True)
    ap.add_argument("--fixture", type=Path, required=True, help="the clip's clip.json")
    ap.add_argument("--feed", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    frames = json.loads(args.tracked.read_text())["frames"]
    feed = load_for(args.feed, frames, load_fixture(args.fixture))
    association = json.loads(args.association.read_text())["tracks"]
    named = broadcast(association, tactical(frames, feed), gate())
    events = [json.loads(x) for x in args.detected.read_text().splitlines() if x.strip()]
    rows = sided(events, named)
    args.out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    n = sum(r.get("team_source") == SOURCE for r in rows)
    print(f"{args.out}: {n} of {len(rows)} events given their player's side by the feed")


__all__ = ["CALIBRATION", "DISCLOSURE", "Feed", "GATE_M", "SOURCE", "SOURCE_LABEL", "assign", "broadcast",
           "disclosure", "gate", "lineup", "load", "load_for", "sided", "tactical"]


if __name__ == "__main__":
    main()
