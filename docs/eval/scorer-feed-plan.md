# Plan: the shooter of a shot or goal from the ball and the ID feed (pre-registered Oct 27, 2026)

Committed before any shooter named this way is compared with the answer key. The results go in
[scorer-feed.json](scorer-feed.json) and EVALUATION.md (*Scorers from the ID feed*).

## Why

On the demo match (seed 8324), three of the four detected goals name a broadcast track the player-ID
feed does not name (the tracker loses the striker in the box, or reads the strike from the wrong
man: goal 1's shooter is an away track on a home goal), so the phone said the club ("London 12′")
where a broadcast names the scorer. Broadcasts name scorers from the tracking provider's data.

## The rule (fixed now; `ninety/intel/identity.py`, step 9)

1. **Which events.** Detected `shot` and `goal` events whose `player` the feed does not already name
   (through the join or directly, steps 5 to 7). An event it names keeps that name.
2. **The strike.** A shot's strike is the shot itself: its time `t` and its `x`, `y`, the ball's
   place vision detected at the strike. A goal's strike is its shot: the scoring side's last detected
   shot within `GOAL_SHOT_S` = 5 s before it (*design*: the phone's own pairing); if that shot's
   player is named by the feed, the goal takes that name (`by: shot`). No shot, no name.
3. **The player.** The feed player of the event's side (a goal's side is told by the end it went in,
   I24; a shot's is the event's) nearest to the ball at the strike, at the feed row captured nearest
   the strike's frame (within 2 frames), and only within `BALL_M` = 1.5 m: the ball at a player's
   feet (GROUNDING P6, the detector's `CONTROL_M`). Nobody within it: no name.
4. **What it changes.** The event gains `player_named` (the feed's player id, name, shirt, position,
   side, `source: id_feed`, `by: ball` or `by: shot`, the distance). Nothing else: the event, its time,
   side, outcome and ball position stay vision's. The feed's positions only say who stood at the ball.

## The measurement (offline; `ninety/eval/scorer_feed.py`)

- **Matches.** Seed 8080 (the earlier demo, held out: nothing here was set on it) is the gate.
  Seed 8324 (the demo) is reported beside it. Its step-9 output was printed once while the code was
  written (three goals and three shots named), never compared with the answer key before this plan.
- **Truth.** A named shot is right when the answer key's shot nearest it in time, within 1.0 s,
  was taken by that player; a named goal when the answer key's goal nearest it, within 2.0 s, was
  scored by him (the engine's player id mapped to the feed's by the team sheet). A named event with
  no answer-key shot or goal that near is wrong.
- **Gate.** Precision (right / named) **≥ 0.95** on seed 8080, with its Wilson 95% interval
  reported. The counts are small (a match has about a dozen detected shots), so the interval is the
  honest headline; the gate is the point estimate, as pre-registered by the Coordinator.
- **If it misses.** The step stays off the demo (no name rather than a wrong one) and the miss is
  published. No threshold is changed after the score.
- **Scored once**, the commit recorded in the json.
