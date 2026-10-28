# Ball height for shots, on target, saves and out of play: pre-registration

Written and committed on 2026-10-27, before any number with the flight fit on was computed. The
question: does the ball's height (the flight fit, `ninety/vision/flight.py` with PR #410's
size and launch-speed checks, `--flight` in `ninety/vision/live_job.py`) make these four counts
good enough to say?

## What is compared

Two arms of the events stage, from the same stored observations (no vision model is re-run):

- **off** (today's detector): `events.detect` + `restarts.detect` / `restarts.merge` on the
  observations as stored;
- **on**: the same, after `flight.heights` (PR #410's flight.py, on main at 279441fa).

Both arms run with `saves=True` (the shot-outcome rule kept for measurement, as
`events.py --keep-saves` does), so `on_target` outcomes are visible in both. The events stage is
run per broadcast segment (a run of consecutive frames), as the stored demo `detected.jsonl` was.

## Sets, in this order

1. **Held-out: seed 8080**, the hunt cut (`runs/demo-8080-hunt/observations.jsonl`, 53 segments,
   24,322 frames; truth `~/ninety-notes/footage-hunt/events.jsonl`, engine 65247ba3). Nothing in
   flight.py or the event rules was derived on it. The verdict is taken here only.
2. **Seed 8324** (`runs/demo-8324-final-work`, 46 segments). In-sample for the detector's
   development: reported, never used to pass a bar.

Truth is restricted to shown frames (a goal also when its previous frame is shown). Detected
events are kept when their team is `home` or `away`. Nothing is tuned between the 8080 and 8324
runs; no constant in flight.py or the event rules is changed in this experiment.

## Types and the matching rule

`ninety.eval.event_score.match` with its fixed window (same type and team, within 1.0 s, one to
one, nearest in time first), time only: no truth frames are stored for these cuts, so the place
radius is not applied (as in the earlier 8324 counts measurement).

| Type | Truth | Detected |
|---|---|---|
| shot | `shot` | `shot` |
| on target | `shot` with outcome `on_target` or `goal` | `shot` with outcome `on_target` or `goal` |
| save | `shot` with outcome `on_target` | `shot` with outcome `on_target` |
| out of play | `out_of_play` | `out_of_play` |

## Bars (per type, on held-out 8080, flight on)

A type passes only if all of these hold:

1. precision >= 0.80 (point estimate);
2. the 95% Wilson interval of precision has its lower end >= 0.50;
3. at least 5 detections of the type;
4. recall strictly above the off arm's recall on the same set.

## Also reported (not part of the bar)

- precision and recall with Wilson intervals, both arms, both sets;
- count error per club: detected minus true, home and away;
- comparison direction: whether sign(home - away) of the detected count equals the truth's,
  over the whole cut and in each 15-minute window where truth is not tied (ties reported apart);
- the flight fit's own counts (pieces in flight).

## What follows

A type that passes on 8080 gets a PR that uses the flight-on events for that type only, with
tests that fail without it and PR #410's changes. If none passes, the numbers go in
`docs/eval/ball-height-events.md` and the experiment stops. Hard stop 22:00 PT, 27 Oct.

## Amendment 1 (before either variant was scored): variant B, "shot by outcome"

Added on 2026-10-27 at the Coordinator's request, committed before any flight-on number of
variant A or any number of variant B was computed. Variant A is everything above (today's event
rules on flight-corrected observations). Variant B is a second shot rule, run on the same
flight-corrected observations (flight on), graded with the same sets, matching rule and bars.

**Who the keeper is.** Vision's keeper flag only (`track.Track.keeper`: a track in neither kit,
whose mean place is inside a penalty area, `track.assign_teams` / `sides.assign`). The player-ID
feed is not used: AGENTS.md allows the feed for identity and side only, never for an event or an
outcome, so a feed role cannot decide a save.

**A strike.** On `track.ball_path` of the flight-corrected observations, a frame i is a strike
for side S when:

- the ball's speed `events._speed_kmh(path, i)` is at least **10 m/s** (36 km/h): a struck ball
  leaves at 10 m/s or more (events.CARRY_MPS comment, docs/eval/event-motion.md, measured);
- `events.heads_for_goal(path, i, S)`: its line over the first SHOT_LOOK_S crosses the goal line S
  attacks between the posts widened by SHOT_MARGIN_M, from within SHOT_MAX_M (35 m) of it (the
  final third and the area just outside it; existing constants, not refit).

Consecutive qualifying frames are one strike, at the first of them.

**The window.** W = SHOT_MAX_M / 10 m/s = **3.5 s** after the strike: the longest time a strike
at the floor speed takes to cover the farthest distance a strike may start from (derived from
the two constants above, not fitted). For the scorebug, scorebug.LOOKBACK_S (10 s, the
scorebug's own bound for linking a goal to its shot).

**The outcome.** The first of these, after the strike and before the next strike:

- (a) **keeper gains it**: within W, on at least events.MIN_SPELL_FRAMES (2) frames, the ball is
  within CONTROL_M + RIVAL_M = **2.76 m** of a keeper track standing within PENALTY_AREA_X of the
  goal line S attacks (CONTROL_M 1.5 m, GROUNDING P6, the ball at a player's feet or hands; RIVAL_M
  1.26 m, the players' measured position error p90);
- (b) **goal on the scorebug**: the first scorebug read after the strike that shows S's score
  above the last read before it, within LOOKBACK_S;
- (c) **over that goal line**: within W, events.out_of_play fires with the ball beyond the goal
  line S attacks (x beyond it by BALL_R) and inside the touchlines (0 <= y <= 68).

No outcome, no shot. Detected types:

| Type | Detected (variant B) | Truth (unchanged) |
|---|---|---|
| shot | any of (a), (b), (c) | `shot` |
| on target | (a) or (b) | `shot` with outcome `on_target` or `goal` |
| save (keeper catch) | (a) with the ball's median speed over its frames at the keeper <= CARRY_MPS (4 m/s, events.py: below it the ball moves with the player) | `shot` with outcome `on_target` |

The event's time is the strike frame's time, its team S. Out of play is not part of variant B.
The bars, sets and order are those above; A and B are reported separately, and only a type that
passes on held-out 8080 may ship.
