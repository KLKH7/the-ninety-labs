"""Read-only MCP server exposing matches to agents.

Agents never see raw files or the ground-truth log directly: they query typed, compact events
through these tools, naming the match they were asked about. Two transports, the same tools:

    uv run python -m ninety.mcp.match_server                       # stdio, for local agents
    uv run python -m ninety.mcp.match_server --precompute matches/  # write the served matches

Precomputing also writes each match's frames, which the phone companion reads (ninety/api/companion.py).

Over HTTP it is mounted at /mcp in the API (ninety/api/app.py), where Foundry's published
Analyst calls it with a key (infra/main.bicep). The served matches are a fixed list, simulated
when the image is built: a call never starts a simulation, so it answers in milliseconds and
cannot be used to make the server do expensive work. The simulator gives the same match on every
machine (docs/LESSONS.md, lesson 29), so a precomputed match equals one computed here.
"""

from __future__ import annotations

import argparse
import json
import os
from functools import lru_cache
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from ninety.intel import shape
from ninety.intel.match_insights import MatchInsights, load_fixture
from ninety.intel.windows import agent_rows
from ninety.match import detected, tracking
from ninety.match.facts import AGENT_TYPES, compact, events_in, match_events, select

MINUTES = 5  # every served match is a five-minute clip, as the slice and the evaluations use
# Simulator matches: the pre-M1 stand-in, kept for the committed replays and the agent evaluation.
MATCHES = {"seed7": 7, "seed21": 21, "seed33": 33}  # the demo match and the held-out evaluation seeds
# Detected matches: the live path from Milestone 1, read from vision's detected events only.
DETECTED = {detected.M1_CLIP: detected.m1_path}
MATCH_DIR = os.environ.get("NINETY_MATCH_DIR", "")
MAX_EVENTS = 60
# Each match's window stats are stored under their own folder: the top level holds one file per
# match id and nothing else.
STATS_DIR = "stats"
TOOLS = ("list_events", "match_info")  # the published Analyst may call only these (tests check they exist)
# The insight tools the Companion chooses from (ninety/agents/companion_match.py). Served here too, read
# only, but not in the published Analyst's allowed tools: adding them changes that agent's definition.
INSIGHT_TOOLS = (
    "line_breaks", "overloads", "counter_press", "pass_options", "goal_build_up", "players", "style",
    "referee", "lineup", "possession", "territory", "shots", "passing", "physical",
    "halves", "key_moments",
)
INSIGHTS_DIR = "insights"  # inside NINETY_MATCH_DIR: a match's precomputed MatchInsights, one file each
# Every tool the server serves. team_shape, re_perceive and the insight tools are served but not in
# the published Analyst's allowed tools: adding them changes that agent's definition, which takes an
# `agents-live` publish run. Until then the workflow hands the minute's shape facts to the writers as evidence
# (ninety/agents/workflow.py).
SERVED = (*TOOLS, "team_shape", "re_perceive", *INSIGHT_TOOLS)
# Vision's per-camera observations for a served clip, when its multi-view run is in the image:
# <NINETY_VIEWS_DIR>/<match>/<camera>/observations.jsonl (ninety/vision/live_job.py writes views/).
VIEWS_DIR = os.environ.get("NINETY_VIEWS_DIR", "")

def match_id(seed: int) -> str:
    return f"seed{seed}"


def unserved(match: str) -> str:
    """The id an evaluation gives a match whose events it sends inline. No server serves it, so an
    agent that calls the match tools anyway gets an error, never the deployed image's match."""
    alias = f"{match}-inline"
    if alias in MATCHES or alias in DETECTED:
        raise ValueError(f"{alias} is served")
    return alias


@lru_cache(maxsize=len(MATCHES) + len(DETECTED))
def events_of(match: str) -> tuple[dict, ...]:
    if match in DETECTED:
        rows = detected.load(DETECTED[match]())
        return tuple(compact(e) for e in rows if e["type"] in AGENT_TYPES)
    if match not in MATCHES:
        raise ValueError(f"unknown match {match!r}; available: {', '.join([*DETECTED, *MATCHES])}")
    stored = Path(MATCH_DIR) / f"{match}.json" if MATCH_DIR else None
    if stored and stored.exists():
        return tuple(json.loads(stored.read_text()))
    return tuple(events_in(MATCHES[match], MINUTES, 1, MINUTES + 1))


@lru_cache(maxsize=len(MATCHES) + len(DETECTED))
def stats_of(match: str) -> tuple[dict, ...]:
    """The match's window stats, computed by code from its full events (positions included, which
    the compact events leave out): detected events for a detected clip, the simulator's otherwise."""
    if match in DETECTED:
        return tuple(agent_rows(detected.load(DETECTED[match]())))
    if match not in MATCHES:
        raise ValueError(f"unknown match {match!r}; available: {', '.join([*DETECTED, *MATCHES])}")
    stored = Path(MATCH_DIR) / STATS_DIR / f"{match}.json" if MATCH_DIR else None
    if stored and stored.exists():
        return tuple(json.loads(stored.read_text()))
    return tuple(agent_rows(match_events(MATCHES[match], MINUTES)))


def list_events(match: str, minute_from: int, minute_to: int, event_type: str | None) -> list[dict]:
    """Events of one match between two match minutes (inclusive), oldest first. `match` is the
    match id you were given (for example seed7). Optionally one event_type: pass, shot, goal,
    tackle, interception or pressure; null for all. Each event has id, clock, minute, second,
    type, team, player, and where relevant receiver (completed passes), intended (who a pass was
    for), interceptor (who won it), deflected_by (who only touched it), outcome, ball_speed_kmh
    and distance_m."""
    types = (event_type,) if event_type in AGENT_TYPES else AGENT_TYPES
    rows = [e for e in events_of(match) if minute_from <= e["minute"] <= minute_to and e["type"] in types]
    return rows[:MAX_EVENTS]


def match_info(match: str) -> dict:
    """One match: its id, length in minutes, event types, and stats computed by code for each
    team in each 15-minute window (ppda, field_tilt, passes_per_minute, territory_shift). Cite a
    stat by id; quote its value, percent or minutes as given."""
    events = events_of(match)  # refuses an unknown match
    minutes = max((e["minute"] for e in events), default=0) if match in DETECTED else MINUTES
    return {"match": match, "minutes": minutes, "event_types": list(AGENT_TYPES),
            "stats": list(stats_of(match))}


def fixture_path(clip: str) -> Path:
    return tracking.FIXTURES / f"fixture-{clip}.json"  # its seed and club codes, from its clip.json


@lru_cache(maxsize=4)
def insights_of(match: str) -> MatchInsights | None:
    """A match's insight facts: precomputed in NINETY_MATCH_DIR/insights when the image has them,
    else computed from a tracked clip's frames and detected events. None for a match with no
    tracked frames: the simulator's positions are the answer key, never served as insight."""
    stored = Path(MATCH_DIR) / INSIGHTS_DIR / f"{match}.json" if MATCH_DIR else None
    if stored and stored.exists():
        return MatchInsights.from_dict(json.loads(stored.read_text()))
    if match not in DETECTED and match not in MATCHES:
        raise ValueError(f"unknown match {match!r}; available: {', '.join([*DETECTED, *MATCHES])}")
    if match not in tracking.TRACKED_CLIPS or match not in DETECTED or not fixture_path(match).exists():
        return None
    try:
        frames = tracking.tracked(match).frames
    except tracking.NotTracked:
        return None
    events = detected.load(DETECTED[match]())
    return MatchInsights.build(match, frames, events, load_fixture(fixture_path(match)))


def _insight(match: str, tool: str, *args) -> dict:
    mi = insights_of(match)
    if mi is None:
        return {"match": match, "tracked": False, "facts": [], "summary": []}
    return {"match": match, "tracked": True, "clubs": mi.fixture.clubs, **getattr(mi, tool)(*args)}


def line_breaks(match: str, minute_from: int, minute_to: int, club: str | None = None) -> dict:
    """Line breaks (packing): for each completed pass between two match minutes (inclusive), how
    many opponents it took out of the game, counted by code from tracked positions: opponents nearer
    the goal than the ball where the pass was played, and no longer nearer than where it ended. club:
    one club's name, or null for both. Facts are the passes that bypassed most, strongest first;
    summary has each club's total. Each fact has id, club, minute, value with unit, lo and hi
    (bounds from untracked players and tracking error), confident, passer_is and receiver_is (how to
    name them) and visual. Cite facts by id; quote value or an `also` number with its unit."""
    return _insight(match, "line_breaks", minute_from, minute_to, club)


def overloads(match: str, minute_from: int, minute_to: int, club: str | None = None) -> dict:
    """Overloads: moments between two match minutes when one club had at least 2 more players
    than the other in one of nine zones (own, middle or final third, by left, centre or right
    channel, as that club attacks), counted by code from tracked positions. club: one club's name,
    or null for both. Each fact has id, club, third, channel, value (extra players) with unit,
    own_players and other_players, duration_s, confident and visual; summary counts each club's
    confident overloads by zone. Cite by id; quote numbers with their units."""
    return _insight(match, "overloads", minute_from, minute_to, club)


def counter_press(match: str, minute_from: int, minute_to: int, club: str | None = None) -> dict:
    """Counter-pressing: for each open-play turnover between two match minutes, the club that
    lost the ball, the most of its players within five yards of the ball in the 5 s after (value,
    players), the time it took to win it back (regain_s, seconds, null if a dead ball came first)
    and whether that was within 5 s (regained). club: the club that lost it, or null for both.
    summary: each club's turnovers and regains within 5 s. Cite by id; quote numbers with units."""
    return _insight(match, "counter_press", minute_from, minute_to, club)


def pass_options(match: str, minute_from: int, minute_to: int, club: str | None = None) -> dict:
    """Pass options (decision quality): for each pass between two match minutes, the passer's
    teammates ahead of the ball with no opponent within five yards (value, teammates), whether the
    pass went to one of them (target_open) and its outcome. club: the passing club, or null for
    both. Lost passes come first. summary: per club, passes with no open teammate ahead. Cite by
    id; quote numbers with their units."""
    return _insight(match, "pass_options", minute_from, minute_to, club)


def goal_build_up(match: str, minute: int, club: str | None = None) -> dict:
    """The latest goal vision detected at or before `minute` (one club's, or either), and the insight
    facts of the minute before it, strongest first: what led to it. Cite by id; quote numbers with
    their units."""
    return _insight(match, "goal_build_up", minute, club)


def players(match: str, minute_from: int, minute_to: int, club: str | None = None) -> dict:
    """Players ranked by the opponents their completed passes took out of the game between two
    match minutes. The leader's fact is confident only when his lowest possible total beats every
    other player's highest; say "the most" only then. player_is is how to name him."""
    return _insight(match, "players", minute_from, minute_to, club)


def style(match: str, minute_from: int, minute_to: int, club: str | None = None) -> dict:
    """How each club plays between two match minutes, computed by code from detected passes and
    tracked shape: share of passes from each channel (left, centre, right as it attacks), its median
    width against the other club's, crosses (wide final-third passes ending in the box), its keeper's
    long (32 m or more) and short passes, regains that led to a shot (open-play regain to shot, seconds) and
    one-twos. Cite by id; quote a channel's share right after naming the channel."""
    return _insight(match, "style", minute_from, minute_to, club)


def referee(match: str, minute_from: int, minute_to: int, club: str | None = None) -> dict:
    """Offside readings at each completed pass between two match minutes, from the 22 tracked
    positions (Law 11): verdict onside, offside, too_close (within the tracking error: never call it),
    unsure (a defender out of view) or restart, with the margin in metres when there is a call; and
    the Laws summarised in our own words (offside, fouls, handball, cards, VAR). The tracking cannot
    see contact: never judge a foul, handball or penalty from these facts."""
    return _insight(match, "referee", minute_from, minute_to, club)


def possession(match: str, minute_from: int, minute_to: int, club: str | None = None) -> dict:
    """Each club's share of the passes between two match minutes, the pass ratio Opta publishes as
    possession (not time on the ball), with bounds: a pass whose side the video could not tell could be
    either's, and the share is stated only when no pass is in doubt. Cite by id."""
    return _insight(match, "possession", minute_from, minute_to, club)


def territory(match: str, minute_from: int, minute_to: int, club: str | None = None) -> dict:
    """Where the ball was between two match minutes: each club's share of the footage shown with the
    ball in its attacking third, as a range (lo to hi: the ball near a third's line could be on either
    side), and the share in each third. Cite by id; say the range as given."""
    return _insight(match, "territory", minute_from, minute_to, club)


def halves(match: str, minute_to: int, club: str | None = None) -> dict:
    """The first half against the second (Law 7's 45 minutes), up to a match minute: where the ball
    was, the shots and what the passes did in each, with the same ids and bounds as those tools. Cite
    by id."""
    return _insight(match, "halves", 1, minute_to, club)


def key_moments(match: str, minute_from: int, minute_to: int, club: str | None = None) -> dict:
    """The key moments between two match minutes, latest first: goals, shots, regains that led to a
    shot, one-twos and the biggest line breaks, each a checked fact. Cite by id."""
    return _insight(match, "key_moments", minute_from, minute_to, club)


def physical(match: str, minute_from: int, minute_to: int, club: str | None = None) -> dict:
    """Each named player's running between two match minutes: distance in km (from the footage
    shown, with its measured error as within_pct), top speed in km/h, sprints above 25.2 km/h held
    for a second, and the zone he was in most. Tracks the video could not name are left out. Cite by
    id."""
    return _insight(match, "physical", minute_from, minute_to, club)


def passing(match: str, minute_from: int, minute_to: int, club: str | None = None) -> dict:
    """What the passes did between two match minutes: progressive passes (a published definition),
    passes into the final third, long passes (32 m or more) and passes intercepted, each club's count
    with bounds while the video could not tell whose some were, and the totals; and the pairs of
    named players who passed to each other most (only passes the video could name both players of).
    Cite by id."""
    return _insight(match, "passing", minute_from, minute_to, club)


def shots(match: str, minute_from: int, minute_to: int, club: str | None = None) -> dict:
    """The shot map between two match minutes: each detected shot's spot, its distance from the
    goal its club attacks (m) and the angle the posts make there (degrees), nearest first; and each
    club's shots and those from inside the penalty area. How a shot ended (goal, saved, blocked, off target)
    is not known until the line-crossing events exist. Cite by id."""
    return _insight(match, "shots", minute_from, minute_to, club)


def lineup(match: str, club: str | None = None) -> dict:
    """The fictional clubs' team sheets (name, number, position) and, for each tracked player,
    the position vision inferred from his place in the team's shape, with its share and how a
    sentence may name him (say): by name only when that share passed its measured gate."""
    mi = insights_of(match)
    if mi is None:
        return {"match": match, "tracked": False}
    return {"match": match, "tracked": True, **mi.lineup(club)}


@lru_cache(maxsize=len(tracking.TRACKED_CLIPS))
def shape_of(match: str) -> tuple[dict, ...]:
    """The match's team-shape facts, from tracked positions only (`tracking.tracked`, which refuses
    any frame not `source: tracked`). A match with no tracked frames has none: the simulator's
    positions are the answer key, never served as shape."""
    if match not in DETECTED and match not in MATCHES:
        raise ValueError(f"unknown match {match!r}; available: {', '.join([*DETECTED, *MATCHES])}")
    if match not in tracking.TRACKED_CLIPS:
        return ()
    try:
        return tuple(shape.shape_rows(tracking.tracked(match).frames))
    except tracking.NotTracked:
        return ()


def team_shape(match: str, minute_from: int, minute_to: int) -> dict:
    """Each team's shape, computed by code from tracked player positions, for each match minute
    from minute_from to minute_to (inclusive). `match` is the match id you were given. Each fact has
    id, metric (width, length, line_height: the deepest outfield player's distance from his own goal
    line, area: the outfield players' convex hull, back_to_mid and mid_to_front: the gaps between
    the lines, behind_ball and ahead_of_ball: players goal-side of the ball and beyond it), team,
    minute, value, unit, change (from the minute before, or null), tracked (players of 11 seen),
    need and confident. A fact that is not confident rests on too few tracked players: claims
    citing it are held. Cite a fact by id; quote its value or change as given, with its unit."""
    rows = [r for r in shape_of(match) if minute_from <= r["minute"] <= minute_to]
    return {"match": match, "tracked": match in tracking.TRACKED_CLIPS and bool(shape_of(match)),
            "need": shape.MIN_TRACKED, "facts": rows[:MAX_EVENTS * 2]}


@lru_cache(maxsize=len(DETECTED))
def _perceiver(match: str):
    from ninety.agents.perceive import Perceiver

    root = Path(VIEWS_DIR) / match if VIEWS_DIR else None
    views = {}
    for path in sorted(root.glob("*/observations.jsonl")) if root and root.is_dir() else []:
        views[path.parent.name] = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return Perceiver(views)


def re_perceive(match: str, event_id: str, camera: str, mode: str) -> dict:
    """Look again at one detected event of a match through one camera: R3's event detection re-run
    on that camera's observations, in mode "window" (3 s around the event) or "track" (the whole clip:
    each track's side voted over every frame it was seen). Returns the same event as that camera saw
    it (type, t, team, team_confidence, player, confidence), or found null and why. Read-only; it
    never reads ground truth. Use it when a claim's evidence is unsure, not to find new events. Unlike
    the fact-checker's own looks, calls here are neither capped nor logged: no published agent may
    call it yet (it is not in TOOLS)."""
    if match not in DETECTED:
        served = ", ".join(DETECTED)
        raise ValueError(f"no detected events to look at again for {match!r}; available: {served}")
    events = {e["id"]: e for e in detected.load(DETECTED[match]())}
    if event_id not in events:
        raise ValueError(f"no detected event {event_id!r} in {match}")
    perceiver = _perceiver(match)
    if not perceiver.views:
        return {"event": event_id, "camera": camera, "mode": mode, "found": None,
                "why": "this match has no per-camera observations to look again through"}
    return perceiver.re_perceive(events[event_id], camera, mode).as_dict()


def make_server() -> FastMCP:
    """A server with the match tools. Stateless with JSON responses: what Foundry's MCP tool needs
    (one request, one answer, no session). The API builds its own, since an HTTP server's session
    manager runs once."""
    server = FastMCP(
        "ninety-match",
        stateless_http=True,
        json_response=True,
        # DNS-rebinding protection guards servers on a user's own machine and accepts only localhost
        # Host headers; ours is public and answers only with the key, so the Host check is off.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    insight = (
        line_breaks, overloads, counter_press, pass_options, goal_build_up, players, style, referee, lineup,
        possession, territory, shots, passing, physical, halves, key_moments,
    )
    for tool in (list_events, match_info, team_shape, re_perceive, *insight):
        server.add_tool(tool)
    return server


server = make_server()


def precompute(out: Path) -> None:
    """Writes each served match's events, its window stats, and its frames for the phone companion
    (ninety/match/tracking.py), all from one simulation."""
    from ninety.sim.engine import simulate  # the pre-M1 stand-in; never on the live path

    out.mkdir(parents=True, exist_ok=True)
    for match, seed in MATCHES.items():
        run = simulate(seed, MINUTES)
        rows = select(run.events, 1, MINUTES + 1)
        (out / f"{match}.json").write_text(json.dumps(rows, separators=(",", ":")))
        tracking.write(out, tracking.from_match(match, run))
        stats = agent_rows(run.events)  # the same simulation's events as match_events gives
        (out / STATS_DIR).mkdir(exist_ok=True)
        (out / STATS_DIR / f"{match}.json").write_text(json.dumps(stats, separators=(",", ":")))
        print(f"{match}: {len(rows)} events, {len(run.frames)} frames")


def main() -> None:
    ap = argparse.ArgumentParser(description="The match MCP server (stdio), or precompute its matches.")
    ap.add_argument("--precompute", type=Path, metavar="DIR", help="write every served match to DIR")
    args = ap.parse_args()
    if args.precompute:
        precompute(args.precompute)
    else:
        server.run()


if __name__ == "__main__":
    main()
