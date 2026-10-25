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
