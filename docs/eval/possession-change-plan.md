# Possession changes from video: the rule and how it is measured (written 2026-10-23, before any run)

Why: the detector writes passes, shots and out of play, and the event report counts the answer
key's possession changes as misses outside M1's scope ([EVALUATION.md](../EVALUATION.md), "Event
detection from video"). The spells the detector already builds say who has the ball, so a change
of side between two of them is a possession change the footage shows.

Nothing below has been run on any clip when this file is committed. No detected event, truth event
or score for this rule has been looked at.

## What the answer key records

`ninety/sim/engine.py` (engine-v1 at `cca498c`, the frozen test set's engine, and main):
- **Open play:** `possession_change` when a player of the side that did not have the ball takes
  control of it (the `controls` branch of the first touch), at the point of contact, for the
  player's side, naming him. A touch that does not control it (a deflection, a block) changes
  nothing; a tackle won, an interception and a loose ball collected each do.
- **Restarts:** `possession_change` when a restart is taken by the side that did not have the ball,
  placed at the taker (a ball's width behind the set ball), at the moment the engine gives him the
  set ball, which is up to 1.5 s before his kick.
- **`interception`** is recorded only when an opponent controls a pass short of where it was aimed
  (`in_the_lane`: the aimed point is `pass_target`, the passer's intention). The aim is not in the
  picture, so an interception cannot be told from a recovery (a long ball collected where it was
  going) by video. **No `interception` event is detected**; the failed pass keeps naming its
  `interceptor` as now. This is a decision, made before measuring.

## The rule (ninety/vision/events.py, `possession_changes`)

Over the spells `events.spells` already finds (CONTROL_M, CARRY_MPS, MIN_SPELL_FRAMES,
SPELL_GAP_FRAMES unchanged), in time order, skipping spells whose track has no side:
1. a spell `b` whose side differs from the last spell `a` with a side is a possession change for
   `b`'s side, at `b`'s first frame, placed at the ball there, naming `b`'s holder by `attribute`
   (the same rule as a pass's receiver), with `team_confidence` from `b`'s track;
2. **only in play, as far as the picture shows:** none is recorded when a detected out of play lies
   between `a`'s last frame and `b`'s first (the ball was dead: what follows is a restart), or a
   cut does (nothing seen before a cut is linked to anything after it, the pass rule's own
   condition);
3. none when `b`'s track may be `a`'s player picked up again (`may_continue`, the pass rule's own
   condition): two sides on one player is the kit read wrong, not a change;
4. `confidence`: the ball detection's score at `b`'s first frame times min(1, frames / (2 x
   MIN_SPELL_FRAMES)), the pass's own formula on `b`'s spell. A score, not a probability.

**No new constant.** Every number is one the pass rule already uses. So there is nothing to set on
validation clips; the rule's form is fixed here.

## Measurement

**Validation (development).** Ours-v2's validation observations (the 15 clips of
[attribution-plan.md](attribution-plan.md)) are not on the machine this is written on, nor their
answer key, and no data is set from them. When they are reachable they are scored as development
numbers by the same command, and the rule is not changed on them without an amendment here
written before the change.

**Test (scored once).** The frozen test set's five clips (`engine-v1`, `cca498c`), with the
committed observations (`tests/fixtures/observations-seed900001.jsonl`,
`docs/eval/attribution/observations-seed90000{2..5}.jsonl`), which event-report-v2 scored.
- The answer key is not on this machine. Its `events.jsonl` is rebuilt by running engine-v1's own
  clip code (`ninety/render/clip.py` at `cca498c`: the same `simulate`, `choose_start` and window
  filter) without drawing, and is used **only if its sha256 equals the digest in
  [test-set-frozen.json](test-set-frozen.json)** for every clip. Otherwise nothing is scored and
  this says so. The frame rows the scorer reads (frame, t, the ball's and players' places) come
  from the same run, rounded as the renderer rounds them; their file digest cannot match (it also
  holds the drawn boxes), so the events' digest is the check that the same match was rebuilt, and
  the observations' frame numbers must equal the window's.
- Graded by `ninety/eval/event_score.py`, unchanged rules: same type and team within 1.0 s, one to
  one, spot within 1.0 m (strict) or 2.0 m (lenient) of the ball at the detected time. The
  answer key's restart possession changes are placed at the taker, a ball's width from the ball:
  within both radii, so the ball stays the reference (lesson 38's test covers every kind).
- Reported per clip and pooled: true, detected, matched, precision and recall with Wilson 95%
  intervals, strict and lenient. The true ones are split into **open play** and **at a restart**
  (a true possession change at the same frame as a `set_piece` or `kickoff` of its side): the rule
  claims only open play, so a restart one is a miss the report names as such. Every unmatched
  detected change is listed with what truly happened there.
- 900001 is reported pooled and left out, as for passes (the detector's constants were first
  developed on it).
- No bar is set for publishing: five ten-second clips hold a handful of changes, and the number is
  reported whatever it is, with its denominator.

**What the rule gets wrong by design**, written now: a short spell by an opponent who only touched
the ball (two frames near him, moving with him) reads as two changes, there and back; a ball the
detector misses going out makes the restart's taker a change; a whole clip with the sides swapped
gives every change to the wrong side and fails them all (the side is read once per clip,
[possession-calibration.md](possession-calibration.md)).
