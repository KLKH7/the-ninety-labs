# Restarts: the dead ball, the kick-off and the Laws' distances

Before and after the restart fix (GROUNDING L14, L4, L7 to L9; defect sweep rows 2, 3 and 5 in
[defect-sweep-7ee8720.md](defect-sweep-7ee8720.md)). The outcome rows are held-out checks: they
were measured, never tuned to.

## What was measured

| | |
|---|---|
| Before | `main` at `618fd7a` (with #154, the team-length bound, and #157, clearances) |
| After | this change merged onto it (`bca5579`; `ninety/sim/engine.py` as committed with this report) |
| Matches | 16 seeds (7, 11, 21, 42, 101 to 112), 20 minutes each: 320 match minutes per engine |
| Script | `scripts/defect_sweep/restarts.py`; raw output in [restarts/main-618fd7a.json](restarts/main-618fd7a.json) and [restarts/this-branch.json](restarts/this-branch.json) |

The same seed does not pair two engines: the matches part within a minute (lesson 90), so the two
columns are two samples, compared by their standard errors over matches.

## The defects

| | Before | After |
|---|---:|---:|
| Ball moves more than 3 m in one frame, per 90 minutes | 66.7 (median jump 5.7 m) | 0 |
| Frames where a player moves faster than the validator's limit, per 90 | 2.8 (the kick-off reset) | 0 |
| Seconds from a goal to the kick-off | everyone reset in the goal's frame, kick 2 to 4 s later | 13.7 to 19.2 (11 goals): players walk back, the ball is fetched from the net |
| Restarts with an opponent inside the Law's distance when the ball first moves | 117 of 290 | 0 of 306 |
| of which free kicks (9.15 m) | 67 of 123 | 0 of 123 |
| throw-ins (2 m) | 36 of 118 | 0 of 129 |
| goal kicks (penalty area) | 12 of 32 | 0 of 39 |
| corners (9.15 m from the ball) | 2 of 17 | 0 of 15 |
| Taker carries the set ball before his kick (a second touch, Laws 8, 13 to 17) | 51 | 0 |
| Taker plays it again before another player has | 1 | 0 |
| Stoppages never restarted (over 200 s) | 0 | 0 |
| Matches meeting the data contract (`ninety-validate`) | 16 of 16 | 16 of 16 |

Real football has no single-frame ball jumps and no player resets. A goal stops a real match for a
minute or more (GROUNDING L4); this change left it at 14 to 19 s, and the celebration (below) makes
it 61 to 83 s. On main the `kickoff` event is written in the goal's frame; now it is the kick itself.

## Held-out outcomes

| | Before | After |
|---|---:|---:|
| Shots a team per 90 (mean ± standard error over matches) | 17.4 ± 1.7 | 19.0 ± 2.1 |
| Goals a team per 90 | 1.4 ± 0.5 | 1.6 ± 0.5 |
| Pass completion | 79.8% | 79.6% |
| Shots within 10 s of the shooting side's own restart | 36 | 39 |
| Other shots | 88 | 96 |
| First pass after a throw-in fails | 8% | 6% |
| after a free kick | 21% | 14% |
| after a goal kick | 14% | 10% |
| after a corner | 29% | 27% |
| Ball lost within 5 s of a throw-in | 29% | 39% |

Shots, goals and completion are unchanged within noise. Nothing was tuned. 20-minute matches
over-weight kick-offs.

Football-sense (`uv run ninety-football-sense`, same matches, per 90 minutes; none of its rules
looks at restarts): FS1 20.8 to 20.8, FS2 13.2 to 16.0, FS6 own-box passes 28.4 to 29.5, FS7 300
to 287, FS9 2.0 to 0.8.

### Clips and a fresh critic

Four 60 s clips of this engine (a goal kick, a goal and its kick-off; a throw-in and a free kick 19 m
out; a corner; seed 21 from 0:45) were cut into contact sheets and given to a reviewer who had not
seen the code, with only the question "what would a fan or broadcaster find wrong". It found no
teleport, no encroachment and no double touch, and named as right: the keeper fetching the ball for
his goal kick, the ball rolled back to the centre after the goal rather than reappearing there, both
teams in their own halves at the kick-off, no opponent within 2 m at the throw-in. Its top football
complaint, in this area but not caused by this change: players stand still through the 25 to 35 s
stoppages, with no wall, no jostling and no organisation, and the kick-off comes about 17 s after a
goal against a minute or more in real matches (L4; the 72 s it was compared with then is a penalty
goal's, lesson 140). The celebration below answers the second.

### On earlier bases

Against `main` at `d6040af` (before #157), with this change at `45a2d0d`
([earlier-main-d6040af.json](restarts/earlier-main-d6040af.json),
[earlier-branch-45a2d0d.json](restarts/earlier-branch-45a2d0d.json)): the same defects to 0, shots
17.7 ± 1.6 to 18.3 ± 1.9, goals 1.8 ± 0.5 to 0.8 ± 0.4 (13 against 6 goals, not settled; earlier
versions of the change gave 1.0 and 2.0 on the same seeds). On today's base goals are level.

#### Before #154

Measured first against `main` at `2581ec3`, before #154, with this change at `57ae070` (same
seeds; [earlier-main-2581ec3.json](restarts/earlier-main-2581ec3.json),
[earlier-branch-57ae070.json](restarts/earlier-branch-57ae070.json)): ball jumps 74.8 to 0 per 90,
encroachment 109 of 302 to 0 of 275, and shots 13.9 ± 1.1 to 18.6 ± 1.5 a team per 90 (z 2.5),
goals 1.4 ± 0.5 to 2.4 ± 0.6, most of the extra shots within 10 s of a side's own restart (40 to
64), with the first pass after a throw-in failing 15% to 4%. On today's base that shot rise does
not appear (above). Which base's restart behaviour is realistic is open: real restart-retention
rates are not yet sourced.

## After a goal (the celebration)

Measured on the same 16 seeds, 20 minutes each, against `main` at `8b426b5` (with #156, this
report's first change, and since then #160, #163, #164 and #166 from the engine-decisions work), the
celebration branch merged onto it at `8c7bb1b`; raw output in
[restarts/main-8b426b5.json](restarts/main-8b426b5.json) and
[restarts/celebration-branch.json](restarts/celebration-branch.json):

| | Before | After |
|---|---:|---:|
| Seconds from a goal to the kick-off | 15.6 to 19.2 (10 goals) | 61.4 to 83.0 (9 kick-offs) |
| Ball in play, share of the 20 minutes | 61.9% | 60.7% |
| Shots a team per 90 | 15.9 ± 1.6 | 15.2 ± 1.9 |
| Goals a team per 90 | 1.4 ± 0.4 | 1.4 ± 0.4 |
| Pass completion | 84.8% | 84.5% |
| Restart defects (jumps, encroachment, carried set balls, stuck restarts) | 0 | 0 |
| Matches meeting the data contract (`ninety-validate`) | 15 of 16 | 15 of 16 |

A goal's celebration "may last one, one and a half minutes" (Collina, FIFA, 2022): the kick-off now
comes 60 to 90 s after the goal (GROUNDING L4). Ball in play is about 55.8% of a Premier League
match's total time, added time included (Opta via The Analyst, 2023); these 20-minute matches have
no added time. Shots, goals and completion are unchanged within noise; the matches part after their
first goal (lesson 90). Football-sense, per 90: FS1 17.2 to 19.4, FS2 7.6 to 7.9, FS6 27.8 to 23.9,
FS7 296 to 298, FS9 1.7 to 1.1. Up to a match's first goal nothing changes: seed 21, which has no
goal in its 20 minutes, is frame for frame the same on both. It is also the one match failing the
contract, on both: its shot at 4:37 is blocked, touched again by the shooter, tackled and only then
collected, and the shot's end point is written where it was collected (C7). That is open-play event
logic, outside this change.

### The huddle

The first version sent every team-mate to the scorer's own centre: in 32 to 63% of celebration
frames two bodies were more than 5 cm into each other (the first audit's count, three planted
goals). Now each runs to his own place on an arc round the scorer, a shoulder's breadth apart, on
the side he comes from and in the order of the team-mates' bearings. The places are worked out for
all of them once a frame. Within reach of his place (GROUNDING L4, *design*: where one running at
`RECOVER` must start braking for it, about 3.2 m) team-mates stand closer than the usual personal
space. Each team-mate leaves at his own moment, and the scorer goes last.

Counted by [`scripts/defect_sweep/huddle.py`](../../scripts/defect_sweep/huddle.py) over the whole
celebration of a planted goal (h9 scores from 100, 30) on 12 seeds not used while designing it (1,
4, 6, 8 to 10, 12 to 17):

| | Now |
|---|---:|
| Frames with two bodies more than 5 cm into each other, mean over seeds | 0.9% |
| worst seed | 3.2% |
| longest a goal | 0.8 s |
| Frames once all stand at their places, settled, until the first leaves | 0 of 193 |
| The same count over a minute of open play from the same seeds | 0.35% |

What remains comes from the last few arriving at a run beside a team-mate already in place: a
shoulder's breadth between places leaves 5 cm to spare, and the engine's steering bends a run round
a team-mate but does not slow it. The third audit measured the version before this one at 2.1% of
frames on the same seeds (an adapted copy of the script), a keeper's goal at 3.2% (up to 8.4%), and
goals from the far post or long range at 1.6 to 1.8%; and that wider places, or a longer reach, would
cut overlaps further. Those values were set before and were not changed after seeing that.

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
