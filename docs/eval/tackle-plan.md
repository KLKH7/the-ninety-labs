# Tackles from video: the rule and how it is measured (written 2026-10-24, before any run)

Section 3 of [detection-gaps-plan.md](detection-gaps-plan.md), built third. Rubric: technological
implementation (one more event type from pixels, with its outcome, measured) and real-world impact
(tackles won and lost are hand-logged today).

Nothing below has been run on any clip when this file is committed. No detected tackle, and no
score for this rule, has been looked at.

## What the answer key records

`ninety/sim/engine.py` (at `65247ba` and main) writes `tackle` for the tackler's side, at the ball,
naming the tackler `player` and the player challenged `receiver`, in two ways:
1. **A lunge that reaches the ball** while an opponent holds it (`poke`): the ball is knocked loose
   at `POKE_MPS` (5.0 m/s, *design*) in about the tackler's direction, plus 0.3 of the holder's
   velocity. The outcome is open (`null`) until someone controls the ball: `success` when he is of
   the tackler's side, `fail` otherwise (`tackle["outcome"]`). If nobody controls it before the ball
   is dead, it stays `null`.
2. **A ball won off a dribbler:** an opponent controls a ball the other side's dribbler has pushed
   ahead of himself (not after a heavy first touch, `loose_touch`): `tackle`, `success`, at the
   point of control.

## The rule (`ninety/vision/events.py`, `tackles`)

At the end of each spell `a` whose track has a side, at its last frame f (the ball's last frame at
his feet):
1. **no strike:** the ball's speed after f, the median frame-to-frame speed over `SHOT_LOOK_S`
   (the pass's own `ball_speed_kmh`), is under `ARRIVE_MPS` (6.0 m/s, `decisions.ARRIVE_MPS`, the
   softest pace the engine strikes a ground pass to *arrive* at, so every ground pass leaves faster:
   a ball leaving slower is not one of the engine's ground passes). Copied, with a test that holds
   it to the engine's. When the speed is unknown (under two ball points in the 0.3 s), no tackle.
2. **an opponent at the ball:** a track of the other side is seen at f within `CONTROL_M` (1.5 m,
   P6) of the ball; the nearest such track is the tackler.
3. then a `tackle` is written at f, for the tackler's side, at the ball, naming the tackler
   `player` and `a`'s holder `receiver`, each by the ball rule (`attribute`, from the ball at f), with
   `team_confidence` from the tackler's track;
4. **outcome:** the side of the next spell with a side after `a`, with no detected out of play and
   no cut between: the tackler's side `success`, `a`'s side `fail` (he kept it, or a team-mate got
   it); none before the clip ends, the ball goes out or a cut, `null`;
5. **confidence:** the ball's score at f times min(1, `a`'s frames / (2 x MIN_SPELL_FRAMES)), as a
   pass's. **Contact:** two players in contact overlap in the image and the tracker can lose one of
   them. Unless both the tackler's and the holder's tracks are seen again within `SPELL_GAP_FRAMES`
   after f, the confidence is held under the fact-checker's gate: at most `HELD` = 0.49, just under
   `factcheck.MIN_CONFIDENCE` (0.5), copied, with a test that holds it under the gate.

Only the first kind is aimed at. The second (a pushed ball taken) shows as `a`'s spell ending on
his own push with nobody within 1.5 m, so this rule misses it unless an opponent is already at the
ball; the measurement counts the misses of each kind (a true tackle is of the first kind when its
outcome was open when written, which the answer key cannot show; so misses are split by whether a
`deflection` of the challenged player is written at the same frame, as `poke`'s knock is).

Nothing else changes. The detector still writes a pass for the same spell change when the next
spell is another player's (Kian's rule, unchanged): a tackled ball leaving under 6 m/s is, by the
engine's definition, no pass, so those passes are false. They are counted in the measurement and
the question is put to Kian, rather than changed here.

**New constants:** `ARRIVE_MPS` (the engine's) and `HELD` (the gate's, less a hundredth). The rest
are the detector's.

## Measurement

As [interception-plan.md](interception-plan.md), "Development measurement" (M1 and M2, the same
stand-in observations and scorer). Reported: tackles true, detected, matched, precision and recall
with Wilson 95% intervals, pooled and per clip; **outcome** right on matched tackles whose true
outcome is not null (with its interval); tackler and challenged player named against the truth
where named; how many detected tackles keep both tracks through the contact, and their precision
against those that do not; and how many detected passes start at a detected tackle's frame.

**Bar for writing it by default (development):** on M1 with noise, strict recall and precision both
at least 0.5, as for interceptions; otherwise built and tested, left out of `events.WRITTEN`, and
said so here. Development numbers on stand-in observations only; no test number.

## Outcome

To be written after the runs, below this line, without changing anything above.

### Outcome (2026-10-25, [turnovers-dev.json](turnovers-dev.json), from commit `f996285`)

Development numbers on **stand-in observations** built from the answer key, validation only; not a
vision result. Strict matching (lenient gives the same here).

| Run | True | Detected | Found (recall, 95%) | Right (precision, 95%) | Outcome right |
|---|---:|---:|---|---|---|
| M1, 30 windows, noise 0.188 m | 44 | 4 | 3 (0.07, 0.02 to 0.18) | 3 | 2 of 3 |
| M1, no noise | 44 | 44 | 40 (0.91, 0.79 to 0.96) | 40 (0.91, 0.79 to 0.96) | 34 of 40 |
| M2, 4 rendered clips, noise | 6 | 0 | 0 | none | |
| M2, no noise | 6 | 6 | 6 | 6 | 6 of 6 |

**Bar missed** (recall 0.07 against 0.5), so `tackle` is not in `events.WRITTEN`: built, tested and
measured, not written by the live path. With exact places the rule finds 9 tackles in 10 and calls
the outcome 34 of 40; every one kept both tracks through the contact. With fresh noise every frame it
finds almost none: of the 41 missed, 33 were balls taken off a dribble and 8 knocked loose. Why is not
measured yet; the likely causes are the noise's speed jitter (about 2 m/s over the speed window)
against the 6 m/s strike test, and spells broken by the same jitter. Exact places also show the double count the plan expected: 42 of 44 detected tackles
also start a detected pass, false by the engine's definition.

**Open, for review:** the noise model (as in interception-plan.md). Kian: with a tackle detected, the
pass the detector also writes at that spell's end is false by the engine's definition; should the
tackle replace it? That changes the pass rule and its published numbers, so it is not changed here. The first run drew its noise from the platform's generator, which is not the same on every machine (lesson 46), and gave 1 of 44 found; the committed report is the rerun with portable draws, from the same commit's code. Two draws of the same noise moving a rate this much is the measure's own spread.

## Amendment 1, 2026-10-25 (before any run of it)

The stand-in's noise model gains an error shared across each frame and over each clip, and the bar is
read on M4 (equal shares) instead of M1; the rule, its constants and the bar's numbers are unchanged.
Written once, in [interception-plan.md](interception-plan.md), "Amendment 1".
