# Pressure from video: the rule and how it is measured (written 2026-10-24, before any run)

Section 4 of [detection-gaps-plan.md](detection-gaps-plan.md), built second. Rubric: technological
implementation (one more event type from pixels, measured); explainability (pressure on the player
on the ball is what the Analyst describes).

Nothing below has been run on any clip when this file is committed. No detected pressure, and no
score for this rule, has been looked at.

## What the answer key records

`ninety/sim/engine.py` (`tick_carrier`, at `65247ba` and main): while a player has the ball at his
feet (the engine's `possessor`; not while a pushed ball runs free, not over a throw-in), the
nearest opponent is found; when he is closer than **2.0 m** (strictly, body centre to body centre)
and his **side** has not pressed for more than **8 s** (strictly), the engine writes `pressure` for
the presser's side, placed at the presser, naming him `player` and the carrier `receiver`.

- **Sources.** Neither number has a row in `docs/GROUNDING.md`; both are literals in the engine
  since its first commit (`3260e094`). They are **design values**, copied here unchanged:
  `PRESSURE_M = 2.0`, `PRESSURE_REPEAT_S = 8.0`.
- **The 8 s is per side, not per presser.** The engine keys its memory by the pressing team
  (`self.pressed[opp]`), so a second presser of the same side within 8 s is not written. The gaps
  plan said "for each presser"; the engine is the definition, so this rule follows the engine.
- The memory runs over the whole match. A clip starts with no memory, so the first pressure of a
  side in a clip may be one the engine did not write (it wrote one in the 8 s before the window).
  That is a disagreement by design, counted in the measurement, not tuned away.

## The rule (`ninety/vision/events.py`, `pressures`)

Over the spells the detector already finds (CONTROL_M, CARRY_MPS, MIN_SPELL_FRAMES,
SPELL_GAP_FRAMES unchanged), for each spell whose track has a side, frame by frame in time order
over the frames where the ball is seen in the spell and the holder's track is seen:
1. the nearest track of the other side seen in that frame, and its distance d from the holder (both
   foot points on the pitch, the same ground places the engine measures);
2. if d < `PRESSURE_M` and the presser's side has no detected pressure in the previous
   `PRESSURE_REPEAT_S` (more than 8 s since, as the engine), a `pressure` is written: at that frame,
   for the presser's side, placed at the presser's foot point, `team_confidence` from his track;
3. **who:** `player` is the presser's id (`h-t12`) when his track is one the companion draws and no
   other track of his side is within `RIVAL_M` of his own distance from the holder; `receiver` is
   the holder's id by `attribute` (the ball rule passes and shots use). Otherwise null.
4. **confidence:** the ball's score in that frame times min(1, spell frames / (2 x
   MIN_SPELL_FRAMES)), as a pass's; **halved** when d is within `RIVAL_M` (1.26 m, the players'
   measured position error, p90) of `PRESSURE_M`, i.e. d > 0.74 m: there the true distance may be
   either side of 2.0 m. A score, not a probability. The threshold is not widened.

The 8 s memory runs over the detected pressures in time order through the whole clip, as the
engine's over the match; a cut does not reset it (the engine's clock runs on).

**New constants:** `PRESSURE_M` and `PRESSURE_REPEAT_S`, the engine's, copied, with a test that
holds them equal to the engine's literals. Nothing else is new.

## Measurement

As [interception-plan.md](interception-plan.md), "Development measurement": the same stand-in
observations (M1, the 30 validation windows with every player seen; M2, the rendered validation
clips with what the broadcast shows), noise sigma 0.188 m and none, the same scorer. A pressure is
placed at a player of its side (`event_score.PLAYER_PLACED`): its spot is judged against the
nearest player of that side, strict 1.0 m, lenient 2.0 m. Reported: true, detected, matched,
precision, recall with Wilson 95% intervals, pooled and per clip; the presser and carrier names
graded on matched pressures where named; and, among false pressures, how many come in a clip's
first 8 s with a true pressure of that side in the 8 s before the window (the memory the clip
cannot see; read from the M1 match, which holds the minutes before each window).

**Bar for writing it by default (development):** on M1 with noise, strict recall and precision both
at least 0.5, as for interceptions; otherwise built and tested, left out of `events.WRITTEN`, and
said so here. Development numbers on stand-in observations only; no test number.

## Outcome

To be written after the runs, below this line, without changing anything above.

### Outcome (2026-10-25, [turnovers-dev.json](turnovers-dev.json), from commit `f996285`)

Development numbers on **stand-in observations** built from the answer key, validation only; not a
vision result. Strict matching (lenient gives the same here).

| Run | True | Detected | Found (recall, 95%) | Right (precision, 95%) |
|---|---:|---:|---|---|
| M1, 30 windows, noise 0.188 m | 55 | 45 | 28 (0.51, 0.38 to 0.64) | 28 (0.62, 0.48 to 0.75) |
| M1, no noise | 55 | 55 | 40 (0.73, 0.60 to 0.83) | 40 (0.73, 0.60 to 0.83) |
| M2, 4 rendered clips, noise | 6 | 7 | 4 (0.67, 0.30 to 0.90) | 4 (0.57, 0.25 to 0.84) |
| M2, no noise | 6 | 7 | 4 (0.67, 0.30 to 0.90) | 4 (0.57, 0.25 to 0.84) |

**Bar met**, narrowly, on M1 with noise (0.51 and 0.62, both at least 0.5): `pressure` is in `events.WRITTEN`.
Of M1's 17 false pressures with noise, 6 fall in a window's first 8 s for a side the engine had
written one for in the 8 s before it (the memory a clip cannot see). Names on matched events of
all three kinds (M1, noise): 46 right, 2 wrong, 26 left null. The first run drew its noise from the platform's generator, which is not the same on every machine (lesson 46), and gave 32 of 55 found and 32 of 53 right; the committed report is the rerun with portable draws, from the same commit's code. Two draws of the same noise moving a rate this much is the measure's own spread. Recall at 0.51 against a bar of 0.5 is inside that spread: the bar is met as written, and it is not a margin.

**For review (Kian):** pressure now reaches the agents and the stats (PPDA counts `pressure`
events) from the broadcast, which shows 5 to 8 players: a detected pressure is one the picture
shows, not every one in the match. Its confidence is halved beyond 0.74 m, where a halved score
falls under the fact-checker's 0.5 gate. The interval is wide and the M2 sample is small.

## Amendment 1, 2026-10-25 (before any run of it)

The stand-in's noise model gains an error shared across each frame and over each clip, and the bar is
read on M4 (equal shares) instead of M1; the rule, its constants and the bar's numbers are unchanged.
Written once, in [interception-plan.md](interception-plan.md), "Amendment 1".

**Outcome of amendment 1:** on M4 pressure finds 37 of 55 (0.67) with 37 of 52 right (0.71): the bar is
met with room, and pressure stays written. M1's narrow pass (28 of 55) and M3's 40 of 55 bracket it.
Details in [interception-plan.md](interception-plan.md), "Amendment 1, outcome".
