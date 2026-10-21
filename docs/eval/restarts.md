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
goal's, lesson 142). The celebration below answers the second.

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

## The wall (free kicks)

At a direct free kick within shooting range the defending side builds a wall (GROUNDING L14): as
many as a shoulder's breadth each fills, rounded down, across the part of the goal Bray's model has
it hide (from the near post, design, to a third of the half-goal past the centre), at 9.15 m and
0.5 m; the defenders with the shortest walks to its places, each walk estimated from above the way
he goes (round the keep-off circle, in behind the line, up into it), share them for the least total walk,
walk to it at least at a normal walking pace, come in behind the line and step up into their places,
and stand shoulder to shoulder.

Twelve planted free kicks (seeds 2, 3, 5, 7; 22 m out straight on, 18 m out at y = 24, 27 m out at
y = 44), by [`scripts/defect_sweep/wall.py`](../../scripts/defect_sweep/wall.py) `--planted`; the
first version ran on the engine of its time, so the minute of play before each kick differs:

| | First version (`5813294`) | Now (`5183be6`) |
|---|---:|---:|
| Walls formed, every player on his place to within a ball's radius | 0 of 12 | 12 of 12 |
| seconds into the stoppage | none formed | 11 to 33 s (stoppages 30 to 40 s) |
| Furthest a wall player is from his place when the kick is struck | 0.2 to 1.0 m, and 7.4 m (below) | 0.02 m |
| Gaps between neighbours' bodies when it is struck | 0.11 to 0.83 m, and 7.2 m (below) | -0.01 to 0.02 m |
| Frames with two of them more than 5 cm into each other while it forms | 0 of 11,004 | 27 of 11,007 (0.25%) |
| Kicks where two wall players' walked paths cross, the two there within a second | not measured | 1 of 12 |

In the first version one wall player stood 7 m from his place through the whole stoppage: his
place was on the edge of the 9.65 m keep-off circle (9.15 m and the margin), straight in from him,
and rounding sent him round the circle at his own distance (lesson 158).

The focused audit of that version planted 72 more: seeds 1, 4, 6, 8 to 12, free kicks at nine spots
at both ends (walls of two to five), every wall player followed frame by frame (the command under
Reproduce). Estimating each walk the way it goes (round the keep-off circle at the walker's distance
from the ball, in behind the line, up into it), not as a straight line, to choose the wall's players,
share out its places and pace them:

| | Straight lines (`8e52cb4`) | Walks round the circle (`5183be6`) |
|---|---:|---:|
| Kicks where two wall players' walked paths cross, the two there within a second | 22 of 72 (32 pairs) | 21 of 72 (35 pairs) |
| Kicks where the wall formed after the kick could be taken | 24, by up to 1.1 s | 18, by up to 1.3 s |
| Least time between the wall forming and the kick | 0.4 s | 0.6 s |
| Frames with two of them more than 5 cm into each other while it forms | 261 of 66,788 (0.39%) | 106 of 66,940 (0.16%) |

Every wall formed before its kick was struck; when it was struck no wall player stood more than
0.03 m from his place and neighbours' bodies were -0.02 to 0.03 m apart, in both. The crossings that
remain are two coming round the same side of the circle: a walk round it at one's own distance from
the ball is not the shortest way there, so the least total walk does not keep two such walks apart,
and both then use the way behind the wall (lesson 161). The estimate is from above: `keep_off` aims a
player at most 30 degrees round from where he is, so he walks a spiral in toward the circle, and over
15 walks of four planted kicks the walked paths were 0.5% to 19% shorter than the estimate, never
longer (`tests/test_restarts.py`), so a wall player is paced early rather than late.

The same 16 matches as above, the wall branch at `41ce3fba` against the celebration branch (no wall);
raw output in [restarts/wall-branch.json](restarts/wall-branch.json). 13 direct free kicks fell
within shooting range: walls of 4 at the two kicks about 22 m out near the centre, 2 or 3 further out
or wider, 1 at sharper angles, and none at one 2.6 m from the goal line, too tight an angle for a
whole player; when each kick was struck every wall player stood on his place, to within a ball's
radius, in all 13 (`scripts/defect_sweep/wall.py` on the runs). One was shot at directly, and the
wall blocked it.

| | No wall | Wall |
|---|---:|---:|
| Restart defects (jumps, encroachment, carried set balls, second touches, stuck restarts) | 0 | 0 |
| Matches meeting the data contract | 15 of 16 | 15 of 16 |
| Shots a team per 90 | 15.2 ± 1.9 | 17.2 ± 1.6 |
| Goals a team per 90 | 1.4 ± 0.4 | 1.55 ± 0.7 |
| Pass completion | 84.5% | 85.3% |
| Ball in play | 60.7% | 59.6% |

The match failing the contract is seed 21 on both, main's C7 (above). Shots (z 0.8) and goals (10
against 11, z 0.2) are level within chance; the two columns are different matches from the first
restart on (lesson 90). Football-sense per 90: FS1 19.4 to 17.7, FS2 7.9 to 8.4, FS6 23.9 to 22.8,
FS7 298 to 285, FS9 1.1 to 2.0. The version before this one (`5183be6`) showed a ball jump of 14.6 m
in one frame in seed 101: a throw-in drifting along the outside of the touchline was kept in play
past the end boards and snapped back to them when retaken (lesson 166); `41ce3fba` retakes it once
it passes the end of the touchline, and the sweep now counts a retaken restart as the same kind.

## Walking to restart positions

"A long time to take a corner" (a viewer, of seed 200 at 1:21). Over 25 corners in 20 matches of
20 minutes on main (`807bde2`), by [`scripts/defect_sweep/corners.py`](../../scripts/defect_sweep/corners.py),
the ball going out to the kick took 30.8 s at the median (26.2 to 34.9 s for the middle 80%). That is
Opta's mean for a corner (GROUNDING R1, about 30 s), so the length was right. Its parts: the ball on
its spot at the arc after 7.4 s; players still coming into the area until 29.3 s; the kick 1.9 s
after the last. Every player went to his place just in time for the kick, half a minute off, so
after the fetch the outfielders spent 72% of their time creeping at 0.2 to 1.2 m/s, slower than a
walk (L4's 1.36 m/s).

Now, while a restart waits, a player more than about a stride from his place, or closing on it, or
on his way round or out of the keep-off circle, goes there at no less than a walking pace. Once he
stands at his place with the ball set (still on its spot, at nobody's feet but the taker's) he has
settled: a shift of his place within a few strides he makes at his own pace, a bigger one he walks
again (GROUNDING L4, lesson 174). Getting there took more than the floor. The creep had hidden loops
between two rules, each fixed where they meet (lesson 174; GROUNDING L4, L14 and T3):
- every small shift of a moving place walked to and back (the stride's dead band; then settling);
- keep_off sending a player who had stopped a hair short of his place on the circle's edge back out
  past it (a straight way to a place within a stride);
- a player circling another who stood on his place (walking in is closing on it);
- the defending side's presser and cover swapped at every look (named once, until the ball is in
  play), and at a wall a presser named to the wall's own place (no presser while a wall stands);
- markers swapping men at every look, and the taker's marker placed where the wall stands (each
  marker keeps his man until the ball is in play; nobody marks the taker; the wall marks nobody);
- going round the circle, each step's dip into its margin sending him straight out, so he stopped
  short every few strides and went round below a walk (from the margin he heads out and round).

Some fixes broke something else, found by the audits and fixed in turn. Settling with the ball only
near its spot (at the whistle, still rolling) and following any later shift at his own pace brought
the creep back: in 41 of 144 free kicks a player crept more than 10 m in one go (42 by the third
audit's own count; now: settled only
with the ball set; walks again beyond a few strides; judged on his place, not his way). Near a line,
going round the circle was aimed off the pitch and kept on it inside the circle (an opponent inside
9.15 m at the kick); holding instead stranded players 20 to 52 m from their places, and one inside
the circle all wait (now: the long way round, or out by the way to his place). Nobody is inside the
Laws' distance at the kick.

Every restart wait in 20 matches, each outfielder but the taker, from the stoppage to the kick, by
[`scripts/defect_sweep/restart_moves.py`](../../scripts/defect_sweep/restart_moves.py):

| Per outfielder-minute of restart waits | Main (`807bde2`) | First floor (`e3e66d1`) | Third audit (`b090877`) | This branch (`00d5c41`) |
|---|---:|---:|---:|---:|
| Creeping (0.2 to 1.2 m/s) | 46.5% | 13.5% | 5.5% | 3.1% |
| Walking or faster | 16.1% | 42.6% | 35.7% | 36.8% |
| Standing (under 0.2 m/s) | 37.4% | 43.9% | 58.8% | 60.1% |
| Direction reversals | 0.70 | 10.39 | 0.86 | 0.88 |
| Metres walked to and fro | 1.30 | 7.11 | 1.52 | 1.45 |
| Waits in which a player reversed 3 times or more | 2.4% | 28.0% | 1.7% | 1.8% |
| Creep spells over 5 m (over 10 m), all matches | 3,136 (2,011) | | 125 (64) | 0 (0) |
| Free kicks with a creep spell over 10 m | 122 of 146 | | 41 of 144 | 0 of 173 |

A creep spell is one outfielder moving at 0.2 to 1.2 m/s from frame to frame, its length the path
walked in it (the third audit's measure, [`scripts/defect_sweep/creep_spells.py`](../../scripts/defect_sweep/creep_spells.py),
from the stoppage to the take). Per match, reversals are 0.88 ± 0.05 on this branch
against main's 0.70 ± 0.03 (t = +3.0), and waits with 3 or more reversals 1.8% ± 0.3% against
2.4% ± 0.2% (t = −2.2): a few more single turns than main, fewer players going out and back.

By restart and side (reversals per outfielder-minute of the wait):

| | Main | Third audit (`b090877`) | This branch |
|---|---:|---:|---:|
| Free kick, kicking side | 0.11 | 0.71 | 0.73 |
| Free kick, defending side | 0.97 | 0.66 | 0.68 |
| Throw-in, kicking side | 0.55 | 1.07 | 1.60 |
| Throw-in, defending side | 0.89 | 0.91 | 1.11 |
| Corner, kicking side | 0.35 | 0.63 | 0.40 |
| Corner, defending side | 1.04 | 1.85 | 0.59 |
| Goal kick, kicking side | 0.11 | 0.59 | 0.61 |
| Goal kick, defending side | 1.26 | 2.08 | 2.31 |

Split by whether the restart had a wall (a direct free kick within shot range):

| Player-waits with | Main, no wall | This branch, no wall | Main, wall | This branch, wall |
|---|---:|---:|---:|---:|
| 3 or more reversals | 2.1% | 1.7% | 7.2% | 3.0% |
| 10 or more reversals | 0.28% | 0.14% | 2.9% | 0% |

Walls now jiggle less than on main: no wall restart of 28 had anyone reverse 10 times or more,
against 8 of 22 on main. What remains is a few more turns than main where a walk replaces a creep:
most at throw-ins and goal kicks, where the waits are short and the ball is set late (in the
thrower's hands, on the goal-kick spot after the fetch), so players settle late, and until then
their places follow the dead ball as it is fetched and the kicking side's onside line read from
noisy sightings (O6). These are turns at a walk, 3 to 7 in a wait at most, not players going out
and back every look. Setting places from the restart's spot rather than the dead ball is a
follow-up.

The same 20 seeds, main against this branch:

| | Main | This branch |
|---|---:|---:|
| Corners | 25 | 14 |
| Outfielders' time after the fetch at corners: creeping | 72% | 3% |
| walking or faster | 19% | 55% |
| standing | 9% | 42% |
| Ball out to the corner kick, median (middle 80%) | 30.8 s (26.2 to 34.9) | 32.8 s (26.6 to 35.8) |
| Planted corners (five seeds, both flags): taken after | 30.00 s, all 10 | 30.00 s, all 10 |
| Restart defects (jumps, encroachment at the kick, carried set balls, second touches, stuck restarts) | 0 | 0 |
| Free kicks: opponents coming inside 9.15 m at any frame of the wait (in the first 0.5 s / near a line / other) | 15 (8 / 4 / 3) | 10 (6 / 0 / 4) |
| Matches meeting the data contract | 20 of 20 | 20 of 20 |
| Possessions a team per 90 (scripts/defect_sweep/possession.py) | 129 | 128 |
| Shots a team per 90 | 17.8 ± 1.3 | 14.4 ± 1.2 |
| Goals a team per 90 | 1.8 ± 0.6 | 1.1 ± 0.3 |
| Corners a team per 90 | 2.8 ± 0.6 | 1.6 ± 0.4 |
| Pass completion (per-match mean) | 84.8% | 84.6% |

± is the standard error over the 20 matches. The matches part at their first restart (lesson 90),
so the two columns are different matches: a difference under about two standard errors of the
difference (|t| under 2) is one chance alone would often give. Goals (t = −1.0) and corners (−1.7)
are within that; shots (t = −1.9) are at its edge. Every version of this branch has had fewer shots
and corners than main, so it may be real. Most of the shots missing come in the 10 s after a team's
own restart (31 against main's 51; at other times 97 against 107), which fits the defending side
keeping its markers through a set piece, but that is not measured. Corners were already a held-out
miss on main, against about 5 a team in a real match. Shots and corners are held-out checks, never
targets. The kick still comes when R1's wait is over.

A fresh critic, shown the seed 200 corner from both engines without being told which was which
(renderer 0.5.9, 2 frames a second, and top-down trails), preferred this branch's set-up, clearly:
the players walk in at a normal pace and the area is full and marked by about 1:02, where on main
they creep in at 0.3 to 0.7 m/s for the whole wait and are still arriving when the ball is kicked.
Over the whole minute it preferred main's, clearly. On this branch the taker played the corner short
4.8 s after taking it (main: 1.2 s), and a foul at 1:27 then started a free kick's wait to the end
of the clip: with the dead-ball cut off, about 15 s of players standing still, which read as a game
that had crashed. Across the 20 matches the time from take to kick is as on main (corners: median
1.2 s against 1.4 s, none over 3 s); free kicks kicked more than 3 s after the take are 17 of 173,
against main's 8 of 146 (`b090877`: 14 of 144). The critic's most artificial thing on this branch,
besides that, was the set area standing like statues for about 20 s before the kick: standing
players do not shift their weight or jostle, in the engine or on screen (follow-ups for the
renderer's idle motion and the corner's set-piece shape).

How close walk_to_wall's estimate comes to a wall player's own walk (his bending round others left
out, since the estimate is of his own way: lesson 176), over 60 walks in 15 scenarios after a minute
of play, by [`scripts/defect_sweep/wall_walks.py`](../../scripts/defect_sweep/wall_walks.py): on
main all 60 within it, the closest by 2 cm; on this branch 59, the closest by 2 cm, and one over it,
by 1.04 m in 28.3 m: a walker running at 3.2 m/s at the whistle, who spent his first second turning
(1.5 m walked, 0.5 m gained), a stopping distance the estimate has no term for. At `b090877` two were
over, by 0.18 m in 15.4 m and 0.02 m in 11.1 m; the first, going round the circle by stepping out
past it and spiralling back in, is gone now that going round from the margin heads out as well as
round. The walks differ between the two engines, as the minute of play does. Without a start at
speed the estimate is within about 1%, not a strict bound.

## Fouls at the call

"The foul doesn't look like a foul" (a viewer, of the same clip). Over 139 fouls in 20 matches on
main, by [`scripts/defect_sweep/fouls.py`](../../scripts/defect_sweep/fouls.py), the two players'
centres were 0.85 m apart at the call at the median (0.62 to 1.08 m for the middle 80%, 1.27 m at
most), close enough for the fouler's leg to reach the other's body (a leg's reach, 1 m, and the
two half-bodies, P11). The fouler came from behind in 73, from the side in 44 and from in front in
22; the ball was playable for him (within a foot's reach and below the knee) in 12. So each call
has a contact in reach, and how a foul is drawn (the challenge, the fall, the referee) is the
renderer's.

## Reproduce

```bash
uv run ninety-sim --seed 7 --minutes 20 --out runs/new/seed7
```

```bash
uv run python scripts/defect_sweep/restarts.py runs/new/seed7 runs/new/seed11
```

```bash
uv run python scripts/defect_sweep/wall.py --planted
uv run python scripts/defect_sweep/wall.py --planted 1 4 6 8 9 10 11 12 -- home:83:34 home:87:24 home:78:44 \
    away:22:34 away:18:44 away:27:24 home:88:30 home:75:20 away:20:50
```

```bash
uv run python scripts/defect_sweep/wall.py runs/new/seed7 runs/new/seed11
```

```bash
uv run python scripts/defect_sweep/corners.py runs/new/seed7 runs/new/seed11
uv run python scripts/defect_sweep/restart_moves.py runs/new/seed7 runs/new/seed11
uv run python scripts/defect_sweep/creep_spells.py runs/new/seed7 runs/new/seed11
uv run python scripts/defect_sweep/wall_walks.py
uv run python scripts/defect_sweep/fouls.py runs/new/seed7 runs/new/seed11
```

```bash
uv run pytest -q tests/test_restarts.py
```
