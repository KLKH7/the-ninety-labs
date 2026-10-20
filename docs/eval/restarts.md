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
| Seconds from a goal to the kick-off | everyone reset in the goal's frame, kick 2 to 4 s later | 14.3 to 17.9 (7 goals): players walk back, the ball is fetched from the net |
| Restarts with an opponent inside the Law's distance when the ball first moves | 133 of 330 | 0 of 311 |
| of which free kicks (9.15 m) | 76 of 141 | 0 of 126 |
| throw-ins (2 m) | 47 of 152 | 0 of 133 |
| goal kicks (penalty area) | 8 of 29 | 0 of 36 |
| corners (9.15 m from the ball) | 2 of 8 | 0 of 16 |
| Matches meeting the data contract (`ninety-validate`) | 16 of 16 | 16 of 16 |

Real football has no single-frame ball jumps and no player resets. The real time from a goal to
the kick-off is about 72 s with the celebration (GROUNDING R1), which is still not modelled. On
main the `kickoff` event is written in the goal's frame; now it is the kick itself.

## Held-out outcomes

| | Before | After |
|---|---:|---:|
| Shots a team per 90 (mean ± standard error over matches) | 17.7 ± 1.6 | 18.1 ± 1.5 |
| Goals a team per 90 | 1.8 ± 0.5 (13 goals) | 1.0 ± 0.3 (7 goals) |
| Pass completion | 79.7% | 80.9% |
| Shots within 10 s of the shooting side's own restart | 43 | 39 |
| Other shots | 83 | 90 |
| First pass after a throw-in fails | 11% | 11% |
| after a free kick | 25% | 19% |
| after a goal kick | 3% | 3% |
| after a corner | 50% (8) | 24% (16) |
| Ball lost within 5 s of a throw-in | 33% | 36% |

Shots and completion are unchanged within noise. Goals fell by 0.85 a team per 90, about 1.5
standard errors on 13 against 7 goals: not settled. 20-minute matches over-weight kick-offs.
Nothing was tuned.

Football-sense (`uv run ninety-football-sense`, same matches, per 90 minutes; none of its rules
looks at restarts): FS1 17.2 to 19.7, FS2 17.7 to 17.4, FS6 own-box passes 25.3 to 32.3, FS7 253
to 278, FS9 1.4 to 1.4.

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
