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
- **Player movement:** consecutive frame displacement divided by the frame timestamp delta,
  converted from metres per second to km/h. No speed is capped or silently corrected.
- **Sprint frames:** movement samples at or above the display threshold of 25 km/h. This is a
  product threshold, not a claim about a player's maximum speed.

## Experimental control-vs-chaos index

This is a transparent descriptive signal, not an established football statistic or a player
rating. It is computed independently for each team and time window:

```text
attempts = number of that team's pass events
control = completed_passes / max(attempts, 1)
chaos = min(1, (opponent_pressure_events + opponent_recoveries) / max(attempts, 1))
index = control - chaos
```

Here, an opponent recovery is an `interception` or `tackle` event whose `team` is the other
team. The result is in `[-1, 1]` because both components are in `[0, 1]`. Every output cites
the contributing event ids and includes its time-window scope. Claims about this index must
call it an experimental signal and must not present it as an official league metric.
