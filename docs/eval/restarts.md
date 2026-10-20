# Restarts: the dead ball, the kick-off and the Laws' distances

Before and after the restart fix (GROUNDING L14, L4, L7 to L9; defect sweep rows 2, 3 and 5 in
[defect-sweep-7ee8720.md](defect-sweep-7ee8720.md)). The outcome rows are held-out checks: they
were measured, never tuned to.

## What was measured

| | |
|---|---|
| Before | `main` at `2581ec3` |
| After | this change's engine (`ninety/sim/engine.py` as committed with this report) |
| Matches | 16 seeds (7, 11, 21, 42, 101 to 112), 20 minutes each: 320 match minutes per engine |
| Script | `scripts/defect_sweep/restarts.py`; raw output in [restarts/main-2581ec3.json](restarts/main-2581ec3.json) and [restarts/this-branch.json](restarts/this-branch.json) |

The same seed does not pair two engines: the matches part within a minute (lesson 90), so the two
columns are two samples, compared by their standard errors over matches.

## The defects

| | Before | After |
|---|---:|---:|
| Ball moves more than 3 m in one frame, per 90 minutes | 74.8 (median jump 7.9 m) | 0 |
| Frames where a player moves faster than the validator's limit, per 90 | 2.8 (the kick-off reset) | 0 |
| Seconds from a goal to the kick-off | 1.9 to 4.0 (10 goals; everyone reset in the goal's frame) | 15.3 to 19.6 (17 goals; players walk back, the ball is fetched from the net) |
| Restarts with an opponent inside the Law's distance when the ball first moves | 109 of 302 | 0 of 275 |
| of which free kicks (9.15 m) | 47 of 83 | 0 of 73 |
| throw-ins (2 m) | 49 of 167 | 0 of 142 |
| goal kicks (penalty area) | 12 of 28 | 0 of 29 |
| corners (9.15 m from the ball) | 1 of 24 | 0 of 31 |
| Matches meeting the data contract (`ninety-validate`) | 16 of 16 | 16 of 16 |

Real football has no single-frame ball jumps and no player resets. The real time from a goal to
the kick-off is about 72 s with the celebration (GROUNDING R1), which is still not modelled.

## Held-out outcomes

| | Before | After |
|---|---:|---:|
| Shots a team per 90 (mean ± standard error over matches) | 13.9 ± 1.1 | 18.6 ± 1.5 |
| Goals a team per 90 | 1.4 ± 0.5 | 2.4 ± 0.6 |
| Pass completion | 84.2% | 86.4% |
| Shots within 10 s of the shooting side's own restart | 40 | 64 |
| Other shots | 59 | 68 |
| First pass after a throw-in fails | 15% | 4% |
| after a free kick | 15% | 21% |
| after a goal kick | 14% | 10% |
| after a corner | 36% | 16% |
| Ball lost within 5 s of a throw-in | 38% | 27% |
| of a corner | 40% | 34% |

Shots rose by 4.6 a team per 90 (z 2.5) and are now about 40% above the real 12 to 13 (GROUNDING
R4). Goals rose by 1.0 (z 1.3, not settled). Most of the rise is shots soon after a side's own
restart, and restarts lose the ball less: before, opponents stood inside the Laws' distances and
could tackle the taker before the kick. That is an association in 16 short matches, not a proven
cause, and 20-minute matches over-weight kick-offs. Real restart-retention rates are not yet
sourced, so whether 4% failed throw-ins is realistic is open. Nothing was tuned to bring shots
back.

Football-sense (`uv run ninety-football-sense`, same matches, per 90 minutes), open-play rules
owned by the engine-decisions work: FS1 10.4 to 9.0, FS2 26.2 to 30.1, FS6 own-box passes 188 to
195, FS7 456 to 495, FS9 58.5 to 71.2. None of these rules looks at restarts.

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
