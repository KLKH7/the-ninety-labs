# Per-player match stats from the Player ID feed: results

These are graded against the bars set in [player-stats-plan.md](player-stats-plan.md), which was
committed (dfbf3953; 8e7a548b after the rebase onto main) before any number was computed. The run
is at 6cfdcfc5 (4f1673a2 after the rebase, the same code) on the demo match,
seed 8324 (`runs/demo-8324-final`), at full time. The truth is the engine's positions and events
in the condensed footage's clip windows, read only in `ninety/eval/player_stats_eval.py`. The raw
numbers, per player, are in [player-stats.json](player-stats.json). The verdicts the live path
reads are in `ninety/intel/player_stats_calibration.json`.

    uv run python -m ninety.eval.player_stats_eval --clip runs/demo-8324-final \
        --vision runs/demo-8324-final-work/vision --truth-clips runs/demo-8324-final-work/clips \
        --feed runs/demo-8324-final/final-work/identity_feed.jsonl

## Coverage

The footage shows 990 s of the 5,400 s match. Each of the 22 players was tracked under a name
the feed gives for 433 to 822 s of it: a footage coverage of 0.44 to 0.83, and a coverage of 0.08
to 0.15 of elapsed match time. 18 of the 22 players clear the pre-registered running rule
(footage coverage ≥ 0.5). Under it are Dan Nisker 0.44, Hugo Kaissop 0.44, Zane Rerrick (a
goalkeeper) 0.44 and Ilya Mondell 0.49, and their running figures are withheld.

## Per-stat error against the bar

| Stat | Players | Measured | Bar | On? |
|---|---|---|---|---|
| Distance while tracked | 18 | median \|error\| 2.0%, p90 3.4% (always slightly short: −3.7% to −0.4%) | median and p90 ≤ 21% | **on** |
| Top speed (3 s mean) | 18 | median \|error\| 0.3 km/h, p90 0.5 km/h | p90 ≤ 7.7 km/h | **on** |
| Estimated distance over all footage shown | 18 | median \|error\| 17.0%, p90 22.7% (always short: −25% to −13%) | p90 ≤ 21% | off |
| Passes attempted | 22 | 27% of players within max(1, 21%); 202 found of 290 | ≥ 80%, and total within 21% | off |
| Passes completed | 22 | 0% within; 147 of 268 | as above | off |
| Shots | 22 | 95% within, but 5 of 18 found | as above | off (see lesson 298) |
| Goals | 22 | 95% within, but 1 of 4 credited | as above | off (see lesson 298) |
| Involvements | 22 | 23% within; 484 of 680 | as above | off |

## Top-3 ranking agreement (per club, ours against the same rule on the truth)

| Ranking | Mean overlap of 3 | London (ours / truth) | Lisbon (ours / truth) | Served? |
|---|---|---|---|---|
| Fastest | 2.5 | Vanton, Finnet, Korrow / Vanton, Finnet, Raddon | Vomble, Mundell, Cirrick / the same | **yes** |
| Most involved | 2.5 | Korrow, Thinton, Hirrick / Thisker, Thinton, Korrow | Mundell, Windell, Vomble / Mundell, Vomble, Windell | no: involvements are off |
| Best (formula) | 2.0 | Korrow, Thinton, Hirrick / Thisker, Korrow, Thinton | Mundell, Windell, Vomble / Mundell, Vomble, Mondell | no: its counts are off |
| Passes | 2.0 | Korrow, Thinton, Hirrick / Thisker, Korrow, Thinton | Mundell, Windell, Nennet / Mundell, Mondell, Windell | no: passes are off |
| Furthest | 2.0 | Thinton, Finnet, Raddon / Finnet, Thinton, Dounton | Vomble, Mundell, Pesker / Vomble, Mundell, Korrick | no: the estimate is off |

Every ranking met its own 2-of-3 bar. The plan turns a ranking off with the stat it ranks, so
only "fastest" is served. Serving the other rankings without their counts would need a new,
pre-registered claim ("ranked by detected involvements"), and the plan made none.

## What a fan can be told

- **How far has X run?** His distance while the video tracked him, with how long that was. Example:
  "Leo Mundell: 355 m in the 210 s of footage he was tracked by 33:50 (Player ID feed)". It is
  never a match total, and it is withheld for a player tracked under half the footage.
- **Who's the fastest on the pitch?** Served, among the players tracked at least half the footage,
  as a 3 s sustained top speed.
- **Best player, most passes, most involved, shots and goals by player:** withheld, with the
  reason. The per-player counts undercount: only events whose track the feed names are his, and
  202 of the 359 detected passes are named here.

## Limits

- One match, the demo, not a general measure.
- The distance and top-speed errors compare the tracked positions with the truth over the same
  seconds, so they measure the measurement. They say nothing about what happened while a player
  was not tracked.
- The demo's tracked positions are smoothed one-second samples, and its tracks follow players
  closely. That may explain why the error is far smaller than the older role-named grading's
  ±87% ([physical.md](physical.md)), which lost pieces of track to unnamed fragments.
