# Per-player match stats from the Player ID feed: plan (pre-registered)

Written and committed before any number below was computed on any match. The code is
`ninety/intel/player_stats.py`, graded by `ninety/eval/player_stats_eval.py`, and the results
go in [player-stats.md](player-stats.md). If a stat misses its bar, it is turned off in
`ninety/intel/player_stats_calibration.json` (`"on": false`). It is never tuned.

## What is computed (live path only)

The inputs are tracked frames (`tracked.json`), detected events (`detected.jsonl`, with sides from
the feed) and the names the Player ID feed gives tracks (`identity.tactical` for the tactical
tracks, `identity.named_broadcast` for the tracks events name). Nothing is read from ground truth.
For each of the 22 players the feed names, up to match time T, and never after it:

- **Footage seconds.** The seconds of footage shown up to T: one per sampled tactical frame
  (`frame % 25 == 0`, the one-second step of team distance, GROUNDING I16).
- **Tracked seconds.** The footage seconds in which a tactical track the feed names this player
  is present. `coverage` is tracked seconds over elapsed match seconds (T), as the brief asks.
  `footage_coverage` is tracked seconds over footage seconds.
- **Distance while tracked.** The sum of one-second steps between consecutive samples (at most
  1.5 s apart) of tracks the feed names this player. A step from one named track to another is
  allowed when both are named him: tracks are stitched only through feed-named segments. A gap
  is never bridged. A step faster than 12 m/s is skipped as a track jumping (GROUNDING I16, R6).
- **Top speed.** The fastest sustained mean over `TOP_WINDOW_S = 3` consecutive one-second
  steps (*design*: on vision's 1.26 m position error, I1, one step's speed error is up to
  1.26·√2 m/s ≈ 6.4 km/h, and the mean over three steps is ≈ 2.1 km/h). It is withheld above
  the plausibility cap of 12 m/s (43.2 km/h), I16's jump rule, which is past R6's match peaks
  of 8 to 9 m/s.
- **Estimated footage distance** (used only to rank "furthest"): distance while tracked ×
  footage seconds ÷ tracked seconds. It is said as an estimate over the footage shown.
- **Events.** A detected event is his when the feed names its track (`identity_broadcast`).
  This gives passes attempted (`pass` as `player`), passes completed (`outcome == success`),
  shots (`shot`, plus a `goal` with no detected shot), goals (a `goal` credited to the player
  of its strike, `identity.strike_of`, else to the goal's own player, and only when he is on the
  goal's side), and involvements (distinct events naming him as player, receiver or interceptor).

Running is kept per player and match minute, and summed only over minutes that ended by T.
Events are exact to their time.

## Coverage rule (fixed now)

Distance, top speed and estimated distance are withheld for a player whose
`footage_coverage < 0.5`, meaning he was tracked under half the footage shown (*design*: the
strict-majority rule of identity step 3). Rankings for "fastest" and "furthest" include only
players at or above it. Event counts are not withheld by coverage, because they come from
events, not tracks. They are said as "in the footage shown".

## "Best player" formula (fixed now, transparent, no model)

`score = involvements + completed passes + 2 × shots + 5 × goals` (*design* weights: a goal
outweighs a shot, which outweighs a completed pass; all three are also counted as
involvements). Ties go to more involvements, then the name. "Most involved" ranks involvements.

## Bars (fixed now; each graded at full time on seed 8324's demo match against the truth)

| Stat | Graded against | Bar | Source |
|---|---|---|---|
| Distance while tracked | true distance over the same steps | median \|error\| ≤ 21% and p90 ≤ 21% | team distance's measured label, ±21% (I16, I22) |
| Top speed | true 3 s top over the same steps | p90 \|error\| ≤ 7.7 km/h | the phone card's worst measured top-speed error (I22) |
| Estimated footage distance | true distance over all footage seconds | p90 \|error\| ≤ 21% | as distance |
| Passes attempted / completed, shots, goals | true counts in the footage windows (clip events) | ≥ 80% of players within max(1, 21%) of truth, per stat | ±1 is the count's resolution; 21% as distance (*design*) |
| Rankings (best, involvement, passes, fastest, furthest) | the same formula on truth | mean top-3 overlap ≥ 2 of 3 over the two clubs | *design* |

A stat that misses its bar is turned off. Its tool answer says it is not available and why. A
ranking whose underlying stat is off is turned off with it.

## Limits said up front

- One match (seed 8324, the demo), not a general measure. The footage tracks about 16 of the
  90 minutes, so every running figure is "while tracked", not a match total.
- Truth is the engine's positions and events in the clip windows of the condensed footage,
  read only in `ninety/eval`. Feed ids are mapped to engine ids by side and position, as
  identity_eval does.
