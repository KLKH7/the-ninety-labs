# Deterministic intelligence

`ninety/intel` computes facts from the event and frame contracts. It does not read engine
internals, ask a model to calculate a number, or use ground-truth-only fields. A downstream
agent may explain a fact, but the fact's value and source ids come from code.

## Current metrics

- **Pass distance:** Euclidean distance between `(x, y)` and `(end_x, end_y)` in pitch metres.
- **Pass completion:** completed passes divided by attempted passes. A pass is completed only
  when its contract outcome is `success`.
- **Shot accuracy:** shots whose outcome is `on_target` or `goal`, divided by all shots.
- **Ball and shot speed:** the contract's `ball_speed_kmh`, aggregated by mean or maximum.
- **Possession:** frames grouped by the first character of the typed possessor id (`h` or `a`).
  Frames where nobody has the ball (in flight, loose, dead) count for neither team. The home
  share is rounded to two places and the away share is one minus it, so they always sum to one.
- **Player movement:** consecutive frame displacement divided by the frame timestamp delta,
  converted from metres per second to km/h. No speed is capped or silently corrected.
- **Sprint frames:** movement samples at or above the display threshold of 25 km/h. This is a
  product threshold, not a claim about a player's maximum speed. Its source is still to be
  cited in `docs/GROUNDING.md` (*verify*).

## Citations

Every fact has a scope (`team:home`, `team:away`, `player:h7`, or `team:home:window:3`) and
`source_ids`:

- event-based facts cite the ids of exactly the events that went into the value; a value of
  zero cites nothing;
- frame-based facts (possession, distance, speed, sprints) cite one inclusive frame range,
  `frames:<first>-<last>`, never one id per frame. Listing every frame made a 90-minute match
  85 MB of facts, too large for an agent's evidence.

## Experimental control-vs-chaos index

This is a transparent descriptive signal, not an established football statistic or a player
rating. It is computed independently for each team and time window:

```text
attempts = number of that team's pass events
control = completed_passes / max(attempts, 1)
chaos = min(1, (opponent_pressure_events + opponent_recoveries) / max(attempts, 1))
index = control - chaos
```

Here, an opponent recovery is an `interception`, or a `tackle` with outcome `success`, whose
`team` is the other team; a failed tackle recovers nothing. The `min(1, ...)` bounds the chaos
term so the index stays in `[-1, 1]`; it is a range bound, not a tuned value. Each output cites
exactly the contributing events (the team's passes and the opponent's pressure events and
recoveries in the window) and its window scope. Claims about this index must
call it an experimental signal and must not present it as an official league metric.
