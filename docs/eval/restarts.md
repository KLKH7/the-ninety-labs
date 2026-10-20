# Restarts: the dead ball, the kick-off and the Laws' distances

Before and after the restart fix (GROUNDING L14, L4, L7 to L9; defect sweep rows 2, 3 and 5 in
[defect-sweep-7ee8720.md](defect-sweep-7ee8720.md)). The outcome rows are held-out checks: they
were measured, never tuned to.

## What was measured

| | |
|---|---|
| Before | `main` at `d6040af` (with #154, the team-length bound) |
| After | this change merged onto it (`ninety/sim/engine.py` as committed with this report) |
| Matches | 16 seeds (7, 11, 21, 42, 101 to 112), 20 minutes each: 320 match minutes per engine |
| Script | `scripts/defect_sweep/restarts.py`; raw output in [restarts/main-d6040af.json](restarts/main-d6040af.json) and [restarts/this-branch.json](restarts/this-branch.json) |

The same seed does not pair two engines: the matches part within a minute (lesson 90), so the two
columns are two samples, compared by their standard errors over matches.

## The defects

| | Before | After |
|---|---:|---:|
| Ball moves more than 3 m in one frame, per 90 minutes | 74.8 (median jump 6.6 m) | 0 |
| Frames where a player moves faster than the validator's limit, per 90 | 3.7 (the kick-off reset) | 0 |
| Seconds from a goal to the kick-off | everyone reset in the goal's frame, kick 2 to 4 s later | 16.0 to 19.1 (6 goals): players walk back, the ball is fetched from the net |
| Restarts with an opponent inside the Law's distance when the ball first moves | 133 of 330 | 0 of 315 |
| of which free kicks (9.15 m) | 76 of 141 | 0 of 119 |
| throw-ins (2 m) | 47 of 152 | 0 of 143 |
| goal kicks (penalty area) | 8 of 29 | 0 of 39 |
| corners (9.15 m from the ball) | 2 of 8 | 0 of 14 |
| Taker carries the set ball before his kick (a second touch, Laws 8, 13 to 17) | 49 | 0 |
| Taker plays it again before another player has | 3 | 0 |
| Stoppages never restarted (over 200 s) | 0 | 0 |
| Matches meeting the data contract (`ninety-validate`) | 16 of 16 | 16 of 16 |

Real football has no single-frame ball jumps and no player resets. The real time from a goal to
the kick-off is about 72 s with the celebration (GROUNDING R1), which is still not modelled. On
main the `kickoff` event is written in the goal's frame; now it is the kick itself.

## Held-out outcomes

| | Before | After |
|---|---:|---:|
| Shots a team per 90 (mean ± standard error over matches) | 17.7 ± 1.6 | 18.3 ± 1.9 |
| Goals a team per 90 | 1.8 ± 0.5 (13 goals) | 0.8 ± 0.4 (6 goals) |
| Pass completion | 79.7% | 80.8% |
| Shots within 10 s of the shooting side's own restart | 43 | 32 |
| Other shots | 83 | 98 |
| First pass after a throw-in fails | 11% | 5% |
| after a free kick | 25% | 13% |
| after a goal kick | 3% | 3% |
| after a corner | 50% (8) | 20% (14) |
| Ball lost within 5 s of a throw-in | 33% | 28% |

Shots and completion are unchanged within noise. Goals are lower, by about 1.7 standard errors on
13 against 6 goals: not settled. Two earlier versions of this change measured on the same seeds
gave 1.0 and 2.0 goals a team per 90, which shows how loose 16 matches of 20 minutes are on goals.
20-minute matches also over-weight kick-offs. Nothing was tuned.

Football-sense (`uv run ninety-football-sense`, same matches, per 90 minutes; none of its rules
looks at restarts): FS1 17.2 to 22.2, FS2 17.7 to 20.2, FS6 own-box passes 25.3 to 32.1, FS7 253
to 273, FS9 1.4 to 1.4.

### On the earlier base

Measured first against `main` at `2581ec3`, before #154, with this change at `57ae070` (same
seeds; [earlier-main-2581ec3.json](restarts/earlier-main-2581ec3.json),
[earlier-branch-57ae070.json](restarts/earlier-branch-57ae070.json)): ball jumps 74.8 to 0 per 90,
encroachment 109 of 302 to 0 of 275, and shots 13.9 ± 1.1 to 18.6 ± 1.5 a team per 90 (z 2.5),
goals 1.4 ± 0.5 to 2.4 ± 0.6, most of the extra shots within 10 s of a side's own restart (40 to
64), with the first pass after a throw-in failing 15% to 4%. On today's base that shot rise does
not appear (above). Which base's restart behaviour is realistic is open: real restart-retention
rates are not yet sourced.

## Reproduce

```bash
uv run ninety-sim --seed 7 --minutes 20 --out runs/new/seed7
```

```bash
uv run python scripts/defect_sweep/restarts.py runs/new/seed7 runs/new/seed11
```

```bash
uv run pytest -q tests/test_restarts.py
```
