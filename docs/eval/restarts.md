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
it 66 to 87 s. On main the `kickoff` event is written in the goal's frame; now it is the kick itself.

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
goal's, lesson 126). The celebration below answers the second.

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

Measured on the same 16 seeds against `main` with the change above (`cf3b17a`), the celebration
branch at `3e668c0`; its raw output in [restarts/celebration-branch.json](restarts/celebration-branch.json):

| | Before | After |
|---|---:|---:|
| Seconds from a goal to the kick-off | 13.7 to 19.2 (11 goals) | 66.4 to 86.7 (8 goals) |
| Ball in play, share of the 20 minutes | 56.6% | 53.6% |
| Shots a team per 90 | 19.0 ± 2.1 | 17.6 ± 2.0 |
| Goals a team per 90 | 1.6 ± 0.5 | 1.3 ± 0.4 |
| Pass completion | 79.6% | 78.9% |
| Restart defects (jumps, encroachment, carried set balls, stuck restarts) | 0 | 0 |
| Matches meeting the data contract (`ninety-validate`) | 16 of 16 | 16 of 16 |

A goal's celebration "may last one, one and a half minutes" (Collina, FIFA, 2022): the kick-off now
comes 60 to 90 s after the goal (GROUNDING L4). Ball in play is about 55.8% of a Premier League
match's total time, added time included (Opta via The Analyst, 2023); these 20-minute matches have
no added time. Shots, goals and completion are unchanged within noise (9 goals against 11; the
matches part after their first goal, lesson 90). Football-sense, per 90: FS1 20.8 to 21.4, FS2 16.0
to 11.8, FS6 29.5 to 30.9, FS7 287 to 269, FS9 0.8 to 1.1. Up to a match's first goal nothing
changes: seed 21 is frame for frame the same as on `main` until its goal at 5:03.

### The huddle

The first version sent every team-mate to the scorer's own centre: in 32 to 63% of celebration
frames two bodies were more than 5 cm into each other (the audit's count, three planted goals; open
play 0 to 0.6%). Now each runs to his own place on an arc round the scorer, a shoulder's breadth
apart, on the side he comes from and in the order of the team-mates' bearings, and only within 3 m
of the scorer do team-mates stand closer than the usual personal space (GROUNDING L4). Over the
whole celebration of a planted goal on 8 seeds (2, 3, 5, 7, 11, 21, 42, 101), 0 to 2.2% of frames
(mean 1.3%) have two bodies more than 5 cm into each other, at most 0.4 s a goal, and none once
they have gathered (`test_gathered_round_the_scorer_no_two_bodies_overlap`). The rest come from runs that
arrive too fast to stop at a place a shoulder's breadth from the next: the engine's steering bends a
run round a team-mate but does not slow it, and bodies in contact brace only with the grip left
after steering (`separate`). Fixing that is a change to every player's movement, not this one's.
Four other ways were measured on the same goals and were worse, a mean of 2.2 to 4.2% of frames:
places fixed at the goal, places kept once reached, each stopping on his own line to the scorer
behind those already there, and standing close only once slower than a walk.

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
