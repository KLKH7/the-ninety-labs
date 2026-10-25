# Detection gaps: plan for the events vision does not detect yet

*Status: planned. Nothing here is built or measured. Each event below gets its own pre-registered
plan file (rule, constants and their sources, the bar) before any of its code runs on a clip.*

Automatic event detection (`ninety/vision/events.py`) writes `pass`, `shot` and `out_of_play` from
pixels. Work in progress adds the ball's height (#226, #286), shot outcomes with `goal` (#271),
`possession_change` (Track A) and a camera fit that follows broadcast cuts (Track B). This plan
covers what is left: **set pieces, interceptions, tackles, pressure and deflections**, and, once the
engine's fouls are settled, **fouls**.

Rubric: technological implementation (more event types, each measured) and real-world impact
(fewer events left to log by hand; the Describer can say a corner or a tackle from the footage).

## Rules every event here follows

- **Live path reads pixels only.** Each detector reads the observations (`observe.py`), the tracks
  (`track.py`) and the events already found; never `frames.jsonl`, `events.jsonl`, `meta.json` or
  the render's edit list. Each new module goes on the `test_vision_live_path` guard list.
- **The answer key's own definition.** Each event is detected as the engine defines it
  (`ninety/sim/engine.py`, `docs/DATA_CONTRACT.md`, "Events"), so detected and true events can be
  compared row for row. Where the engine's definition is a design value, the plan says so; it is
  copied, not tuned.
- **Constants from a source or from measurement precision**, cited in `docs/GROUNDING.md` or
  measured on validation clips, set before any test number. Never fitted to the test set.
- **Scored once** on a pre-registered test set (Track C's set-piece and possession sets, simulated
  on the frozen engine), with strict and lenient matching (`ninety/eval/event_score.py`), Wilson
  95% intervals and every miss and false event listed. The frozen 5-clip test set is too small for
  any of these (13 passes, 1 shot, 1 set piece).
- **A confidence on every event**, a score not a probability, so the fact-checking agent's
  `MIN_CONFIDENCE` (0.5) gate decides what airs.
- **Mutation-tested** tests, a lesson for any mistake, and the challenge map marked `planned`
  until a number is committed.

## Shared dependencies

| Dependency | Why | Status |
|---|---|---|
| Ball height (#226, #286) | lofted passes, crosses and deflections are misplaced on the ground without it; a throw-in's ball is at head height | draft: validation derive, one test run, Kian's OK on `--flight` |
| Ball path turn detector (#271, `outcomes.py`) | a save, block and deflection are all the ball's path turning near a player | draft: pod scoring |
| Camera across cuts (Track B) | most restarts follow a broadcast cut; today a clip with a cut gives no trusted camera | running |
| Possession changes (Track A) | interceptions and tackles are kinds of possession change | branch, PR pending |
| Test sets (Track C) | enough of each event for a rate | simulating on the frozen engine; renders need the pod |
| Tactical camera's fused players (#274, `fuse.py`) | the broadcast shows 5 to 8 of 22 players; anything about players away from the ball | in review |

## 1. Set pieces (and their kind)

**The truth.** At each restart the engine emits `set_piece` (or `kickoff`) at the ball's spot,
naming the taker (`engine.py`, the restart in `stop` and the emit after it). The restart's kind
(throw-in, goal kick, corner, free kick, penalty kick) is known to the engine (`Restart.kind`) **but
is not in the event**: the schema has no field for it. The stoppage before it (`out_of_play`,
`foul`, `offside`, `goal`) is.

**The truth's kind, without a schema change.** #299 (`ninety/eval/set_piece_set.py`,
`restart_kind`) reads it offline from the event that stopped play and where the ball was placed
(Laws 13 to 17), and its tests require that rule to name every kind as the engine built it, and
every restart of 8 minutes of seed 7. The scorer grades the detected kind against that. Because
the truth's rule also reads the stoppage event, the detector must not simply copy it: the
detector sees only pixels (a still ball, a spot, a cut), and its plan file says where its rule and
the truth's could agree for the wrong reason. If R4 and R1 (Kian) later add a `restart` field to
the schema from the engine's `Restart.kind`, the scorer switches to it.

**The signal.** After a stoppage the ball is dead, then it is still at a spot (Law 13 for free
kicks; the engine holds a set ball still), then it is struck or thrown. So:
1. a dead ball: an `out_of_play`, a `goal` (#271), a detected foul (section 6) or a broadcast cut
   (Track B's shot boundary) with no ball in play across it;
2. the ball still: its speed under the carry threshold (`events.CARRY_MPS`) on enough frames, with
   a player within `CONTROL_M`;
3. the restart: the first strike after that (the existing spell logic), at that spot.

**The kind, from the spot (Laws 1, 13 to 17):** in a corner arc (1 m from the corner flag) a
corner; in a goal area a goal kick; on the penalty mark (11 m) with the other players outside the
penalty area a penalty kick; on the centre spot a kick-off (#271 already finds this); beyond a
touchline with the ball at head height (needs the ball's height) a throw-in; anywhere else a free
kick. Each tolerance is the ball's measured position error near that spot.

**Measure.** Track C's set-piece set, every kind counted per split. Report type and team F1, spot
error, time from the true restart, and, if the kind is graded, a confusion table of kinds.

**Order.** After Track B lands. Owner R3.

## 2. Interceptions as their own event

**The truth.** A failed pass names its `interceptor` when an opponent takes it under control. It is
also an `interception` event only when he took it on its way, short of where it was aimed:
`engine.in_the_lane`, along the pass's line less than `INTERCEPT_SHARE` of its length. A ball
collected at the end of its run is a recovery: a `possession_change` only.

**The signal.** `events.py` already names the interceptor (the next spell's holder) on a failed
pass. Add `interception` when that spell starts short of where the pass was going, along its line
by less than `INTERCEPT_SHARE` (the engine's value, copied). Vision does not know the passer's
intended target, so the pass's direction and speed must stand in for it: the plan file defines the
stand-in (for example, where the ball would have stopped rolling on its path) and measures how
often it disagrees with the truth on validation passes before any test number.

**Measure.** Track C's possession set: interceptions F1, and how many detected interceptions are
true recoveries (and the reverse).

**Order.** First: cheapest, and it builds on Track A's possession changes. Owner R3.

## 3. Tackles

**The truth.** A `tackle` is an opponent touching the ball while a team-mate of the other side is
dribbling it, and not on a loose touch; its outcome is success when the tackler's side comes away
with it (`engine.py`, the tackle emit and `tackle["outcome"]`), and it names the player challenged
as `receiver`.

**The signal.** A carried spell (the ball moving with the carrier, as `events.py` defines it) ends
with the ball within `CONTROL_M` of an opponent while the carrier is still within reach (P14:
1 m plus one frame of motion), with no strike between (so it is not a pass or interception). The
outcome is which side holds the next spell. Two players in contact overlap in the image, so the
plan measures how often the tracker keeps both tracks through the contact on validation clips, and
gives no tackle a confidence above the gate when it does not.

**Measure.** Track C's possession set: tackle F1, outcome accuracy, tackler and challenged player
named (track ids) against the truth.

**Order.** After interceptions. Owner R3.

## 4. Pressure

**The truth.** The engine emits `pressure` when an opponent comes within 2.0 m of the carrier, at
most once per 8 s for each presser, naming the presser as `player` and the carrier as `receiver`
(`engine.py`, the pressure emit). The source of the 2.0 m and the 8 s is to be found in
`GROUNDING.md`; if they are design values, the plan says so and copies them unchanged.

**The signal.** Computed from tracked positions only: the carrier (the spell's holder) and the
nearest opponent track, their distance under 2.0 m, with the same 8 s per-presser rule. The
pressure is about the player on the ball, which the broadcast camera follows, so this does not need
the tactical camera (team-wide pressing like PPDA does). The players' position error (about 0.2 m
median, 90% within 0.3 to 1.4 m) makes the 2.0 m boundary uncertain: the plan widens no threshold,
but gives a pressure within that error of 2.0 m a lower confidence.

**Measure.** Track C's possession set: pressure F1, presser and carrier named.

**Order.** Second (with or right after interceptions): broadcast-only and cheap. Owner R3.

## 5. Deflections

**The truth.** A `deflection` is the ball coming off a player without his controlling it (a
block, a parry or a heavy touch), the ball staying free; a failed pass names it `deflected_by`.
P14: the player must be within a foot's reach (1 m), or a keeper's stretched arms in his box
(1.48 m), plus one frame of motion.

**The signal.** The ball's path turns (direction or speed changes by more than the measured
velocity noise allows) within P14's reach of a player, with no spell of that player after it. This
is #271's turn test for saves and blocks, used everywhere in play, so it lands after #271 and
reuses its code. A lofted ball's ground track bends as it rises, so this needs the ball's height
(#226).

**Measure.** Track C's possession set and the shot-outcome set: deflection F1, `deflected_by` on
failed passes, and how many true deflections are read as passes.

**Order.** After #226 and #271. Owner R3.

## 6. Fouls (planned only: not started until Kian's engine work on fouls is done)

Kian (KLKH7) is changing how fouls work inside the engine. Nothing in this section is implemented
until he says the engine's fouls are settled, and its rule is re-read against the engine then.

**The truth today.** The engine emits `foul` at the fouled player's spot, naming the fouler as
`player` and the fouled player as `receiver`; a free kick or penalty follows. The fouled player goes
down and is up before the restart (P18, `fall` and `fall_dir` on the frame). #280 (open) makes
fouls legible on screen: the fouler's hand up, team-mates' heads turned, a whistle on the mp4.

**The signal, without judging contact.** Vision does not rule on contact (as with offside in #266:
explain, never rule). A detected foul is a foul *given*:
1. play stops in play: the ball slows and players decelerate, with no `out_of_play` or `goal`;
2. a player is down: his box much wider than tall at a foot point, for some frames (measured on
   validation renders of fouls). The detector has only `player` and `ball` classes, so if box shape
   is not enough, a `player_down` label from the renderer's `fall` is a training option, which
   is R2's call;
3. a free kick or penalty (section 1) is taken near that spot. That makes set pieces a dependency.
4. optionally the whistle in the mp4's audio, if #280 lands; a narrow-band detector on the
   soundtrack, measured like everything else.

The fouler and fouled player are named by track only when unambiguous, as passes are.

**Measure.** A foul set chosen by Track C's method from the engine's foul events, once the engine
is settled. Report foul F1, the fouled player named, and the restart linked.

**Order.** After section 1 and after Kian's engine change. Owner R3, with R2 for renders.

## Order and timing

Feature freeze is Sun Oct 25, 6 pm; after it, only bug fixes go in.

| Order | Event | Can it land by the freeze? |
|---|---|---|
| 1 | Interceptions | likely, if Track C's possession set is simulated and a validation sample is rendered |
| 2 | Pressure | likely, same conditions |
| 3 | Set pieces | only on clips without a reverse-angle cut (#298 is off by default); otherwise `planned` |
| 4 | Tackles | after the freeze |
| 5 | Deflections | after #226 and #271; after the freeze |
| 6 | Fouls | after Kian's engine work; after the freeze |

Anything not measured by the freeze stays `planned` in `docs/CHALLENGE_MAP.md` and is described in
the README as planned, not as running.
