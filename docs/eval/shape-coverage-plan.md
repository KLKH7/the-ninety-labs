# Shape facts: how many tracked players a fact needs (plan, written before measuring)

Committed before `ninety.eval.shape_coverage` was first run. The rule, the tolerance and the data
are fixed here; the measurement only reads N off them (lesson 11).

**Question.** A shape fact (`ninety/intel/shape.py`: width, length, line height, area, the gaps
between lines) is computed from the players the tracker saw. With k of a team's 11 tracked, how far
is a minute's value from the value all 11 give? N (`MIN_TRACKED`) is the smallest k at which it is
close enough.

**Close enough.** Within the tracker's own position error, `POSITION_ERROR_M` = 1.26 m, the 90th
percentile of tracked players' pitch-position error on validation clips (`RIVAL_M`,
docs/eval/attribution-derive.md). Below that, a missing player is a smaller error than the ones
every tracked player already carries. For the area, the tolerance is the window's hull perimeter
times 1.26 m: to first order, the area that moving the hull's edge outward by the position error
adds. Read at the 90th percentile of all windows and draws, for every metric at once.

**Data.** Simulated matches, seeds 7 and 11 (the seeds S4's window length was measured on; never a
test seed 900001 to 900030), 10 minutes each, every frame. The simulator's positions are the
reference here (grading use, AGENTS.md: the answer key is for grading); nothing measured here reads
or tunes anything on the live path but the one constant N.

**Who goes missing.** Two schemes, each 20 draws per team-minute and per k from 4 to 11, with a
fixed random seed (0):
1. *at random*: k of the 11 kept, the same k for the whole minute (a player out of view stays out);
2. *far from the ball*: the 11 - k players furthest from the ball at the minute's middle frame
   dropped for the whole minute (a broadcast camera's blind spot).

N is the larger of the two schemes' answers. If no k below 11 passes, N = 11: a shape fact needs
every player of the team tracked. Counts behind and ahead of the ball need 11 by definition, and are
not measured.
