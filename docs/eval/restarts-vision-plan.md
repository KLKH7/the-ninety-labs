# Restarts from the video: the rules, written before any restart was scored

Automatic event detection finds passes, shots and out of play (`ninety/vision/events.py`). It does
not see the ball put back in play. A kick-off matters most: after a goal the side that conceded kicks
off (Law 8), so a shot toward goal followed by the defending side's kick-off, with no possession
between, is a goal the video itself shows (the goal rule of PR #271 reads it so). This plan covers
`ninety/vision/restarts.py`, kick-offs first; corners, goal kicks, throw-ins and free kicks follow
by the same rules, each added here before it is scored.

## The detector (live path: observations only, no ground truth)

- **A still ball.** Ball sightings (`track.ball_path`), none more than `events.SPELL_GAP_FRAMES`
  (6) apart and none across a cut of the broadcast's edit, each within `STILL_M` of the run's
  median, for `MIN_STILL_S` (1.0 s) or more; then two sightings in a row off the spot (one off the
  spot with the next back on it is the detector's error and is passed over). The restart is the
  last frame of the still spell: the ball was kicked and clearly moved (Law 8). A clip that ends on
  a still ball says nothing yet.
- **On the centre mark:** the spell's median within `SPOT_M` of (52.5, 34).
- **Law 8 at the kick** (GROUNDING L4): of the team-assigned outfield players seen, more than half
  in their own half (home defends x = 0, both halves), no player of the side not taking it inside
  the 9.15 m circle, at least one player of each side seen. The side taking it is the side of the
  nearest player inside the circle (only the kicking side may be there).
- **Confidence:** the ball detection's median score over the spell times the share of players where
  Law 8 puts them; a score, not a probability.

**Tolerances.** `STILL_M` and `SPOT_M` are the broadcast camera's measured position error for a
point on the ground, `events.RIVAL_M` = 1.26 m (players' p90 on validation clips,
[attribution-derive.json](attribution-derive.json)): a ball set on the grass goes through the same
fitted camera. Players are allowed the same error at the halfway line and the circle.
`MIN_STILL_S` and "more than half" are *design*, set here before any restart was scored: the
broadcast returns from its cut 2 s before a restart (`ninety/render/edit.py`), and half of that
leaves room for the taker hiding the ball; "more than half" is the plain majority, because one
player's kit can be misread. None of them may change to fit a result; a change is a new plan
section, dated, and the scores re-run.

## Grading (`ninety/eval/restart_score.py`, offline, ground truth for grading only)

The engine's `kickoff` event is written when the taker stands set, 1 to 2.3 s before he plays it
(three demo kick-offs: 43 -> 101, 34362 -> 34409, 57820 -> 57845), while the video shows the kick.
So a true kick-off is timed at its kick: the last frame before the true ball first leaves where it
lay at the event (by more than 5 cm). A detection matches within `event_score.WINDOW_S` (1.0 s),
one to one, nearest first. Headline: recall and precision with the side right, 95% Wilson
intervals; beside them, the side not asked, and every timing error.

## Where it is measured

**Validation only:** the 15 kick-offs in the validation split of the set-piece set
([set-piece-set.md](set-piece-set.md), seeds 920101 to 920115), once its clips are rendered (not
yet, 2026-10-24). No rendered validation clip holds a kick-off today: the v2 validation clips and
the shot-outcome set's are windows without one. The test split is scored once, at a frozen commit.

**Development check, not a result:** the demo match (seed 8080) is the demo, not validation. On the
eight broadcast segments its vision run had finished on 2026-10-24 (frames 0 to 35636, one
kick-off): the kick-off found, side right, 0.08 s after the true kick, and no false kick-off in the
other seven. Its four kick-offs after goals are checked the same way when their segments are run.

## Beside the goal rule of PR #271

PR #271 judges a goal with its own kick-off test, pre-registered in its plan and scored on
validation before this module existed, so it does not use this one until after its test score. The
differences, to reconcile then, with validation numbers from both: its spot radius is the ball's
own measured 95% position error near the centre (0.688 m, `docs/eval/shot-outcomes.json` on that
branch) where this uses the players' 1.26 m; its "still" is 3 frames under `events.CARRY_MPS`
where this asks 1.0 s; it requires a dead ball first (the ball over the goal line, or a cut of 4 s
or more) and allows the ball fetched from the net to read as a spell; it does not check which side
kicks off. Neither is changed here to match the other before both are measured.

## Known limits (independent audit, before any validation score)

- An opponent inside the circle nearer the ball than the taker (a Law 8 offence, or a misread kit)
  names the wrong side; the side is still checked by the grader's sided score.
- A kick is seen only if the ball is sighted again within `SPELL_GAP_FRAMES` (0.24 s) of the still
  spell: a kicked ball lost to blur or a bad camera fit for longer drops the kick-off.
- A ball creeping under 1.26 m in a second reads as still; the spot and Law 8 checks carry it.
- Home defends x = 0 in both halves, as the engine plays it today (GROUNDING L3, partial); when
  the teams change ends, the halves here change with them.
These are recorded, not tuned: the validation score says how often each happens.

## Set pieces, and an amendment (2026-10-24, before any validation score)

Added to the same module, by the Laws (GROUNDING L1, L7 to L9, S14):

- **Where the still ball lies** (`place_kind`, the position error allowed): the centre mark, a
  kick-off; within the corner arc (1 m), a corner; in the goal area, a goal kick; on a penalty
  mark, a penalty; on a touchline (held or placed), a throw-in; elsewhere on the field, a free kick.
- **The arrangement at the kick** (`set_piece_arrangement`), which also names the side: a corner
  for the side attacking that goal, no opponent within 9.15 m (Law 17); a goal kick for the side
  defending it, no opponent in the penalty area (Law 16); a penalty for the side attacking it,
  nobody else in the area but its keeper (Law 14); a free kick or throw-in for the side of the
  player at the ball (within reach, P6), no opponent within 9.15 m (Law 13) or 2 m (Law 15). The
  nearest a keeper in his own area is his hold (Law 12), not a free kick.
- **A stoppage first:** the still opens the picture after a cut, or lasts `MIN_STOPPAGE_S` (4 s,
  the edit's `MIN_CUT_S`: the broadcast leaves out every longer wait). Written `type: "set_piece"`
  with a new optional `restart` field (schema).

**Amended after the development check on the demo (seed 8080), not after any validation or test
score.** As first written, the set-piece rules gave 13 false free kicks on the demo's finished
segments: balls held still 1.0 to 1.6 s in open play with nobody near. That led to the stoppage
rule. The demo's throw-in was read as a free kick; that led to the touchline class. Its free kick
was lost because the taker hid the kick for 9 frames; that led to `KICK_GAP_FRAMES`, the tracker's
1 s wait, now the gap allowed in a still spell and before the kick, for kick-offs too (it was
`SPELL_GAP_FRAMES`, 6). A still the clip happens to start on no longer counts as a stoppage, since
the demo's segments start anywhere in a wait. No tolerance changed. On the demo with these rules:
the kick-off found (side right), none of its 4 set pieces found, no false restart. (An earlier
version of this note and of PR #325 said 5; the finished segments hold 4.) Why each was missed:

| Set piece (truth frame) | Cause | General or specific |
|---|---|---|
| throw-in, near touchline (1376) | still 1.2 s from the segment's first frame: the window opens mid-wait and the demo renders no cut, so no stoppage is seen | specific to windows that open on a set ball (validation windows open 2 s before the stoppage) |
| free kick (17307) | still 3.2 s from the segment's first frame (as above), and at the kick no player of the side detected within reach of the ball | windowing: specific; the taker unseen at the ball: general (detection and tracking of a player over the ball) |
| throw-in, far touchline (19006) | the ball lies on the grass 0.27 m beyond the line, fully visible (about 30 px), but detected in 9 of 91 frames: no still spell | general: ball-detector recall on a dead ball at or beyond the far line |
| corner (20395) | the ball set in the arc, fully visible (about 47 px), scored 0.2 to 0.4 by the detector for the whole wait, under the 0.5 threshold: no sighting | general: ball-detector recall on a ball set at the corner |

None of the 4 is lost to the still rule itself once the ball is sighted. These are causes on the
demo, a development check: fixes are chosen from the validation split's misses, never from these.

**Grading set pieces** waits for #299's `restart_kind`, which reads each true set piece's kind from
the stoppage before it: same kind and side, within 1.0 s of the true kick, by the same rule as
kick-offs.

**Second audit (independent, on the set pieces), what changed and what is recorded.** Fixed: the
taker is named only within reach of the ball (the corner, goal-kick or penalty taker had no
distance limit); a keeper at the ball with it drawn over him for most of the still is his hold,
not a set ball, for every kind (it had covered free kicks and throw-ins only); tests now catch all
12 of its mutants. Recorded, not changed:
- The rule that the clip's start is no stoppage was chosen from the demo's segments. Validation
  windows open 2 s before the stoppage, so it does not touch them.
- A free kick within 1.26 m of a touchline reads as a throw-in.
- A kick hidden by the taker is timed at the last still sighting, up to 1 s before the strike.
- A wait shown uncut but shorter than 4 s is not found.
- A set piece's confidence is the ball detection's score alone; its arrangement is a gate, not a
  share.
