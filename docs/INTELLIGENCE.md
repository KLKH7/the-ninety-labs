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
- **Sprint frames:** movement samples at or above the sprint threshold of 25.2 km/h (`stats.SPRINT_THRESHOLD_KMH`, cited in docs/GROUNDING.md I22). This is a
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

## Windows and shifts

`ninety/intel/windows.py` reads events only. Home attacks toward x = 105 for the whole match and
away toward x = 0. Each team gets these facts in each 15-minute window (`WINDOW_S`), scoped
`team:<side>:window:<n>`. Fifteen minutes is football's usual split and, measured on seeds 7 and 11
over 90 minutes, the shortest window with enough events for a share to mean something: a median of
11 attacking-third passes a window (a share's standard error near 0.15) and a defensive action in
every team-window. Five-minute windows held 3, and a third of team-windows had no defensive action.

- **PPDA** (`ppda`, passes per defensive action): the opponents' passes in their own 60% of the
  pitch, divided by this team's tackles and interceptions in that zone. Lower means a more
  intense press. A window with no defensive action there has no PPDA fact. The same function
  feeds the style fingerprint (`ninety/sim/fingerprint.py`), so the two cannot disagree. The
  measure is widely used in public football analytics (*verify*: cite its first definition).
- **Field tilt** (`field_tilt`, share): this team's passes played from its attacking third,
  divided by both teams' attacking-third passes. A window with none from either side has no fact.
- **Passes a minute** (`passes_per_minute`): this team's passes in the window over its length The last
  window ends at the last event, so a five-minute clip's tempo is over five minutes, not fifteen.

**Territory shift** (`territory_shift`): a side leads a window when its field tilt is more than one
standard error from level (|tilt - 0.5| > 0.5 / sqrt(n), n the passes counted); closer than that the
window cannot tell the sides apart, and nobody leads it. A shift is a window led by the other side
from the last window that had a leader. One fact for the side that took over, scoped to that window,
valued at its field tilt there, citing the passes counted. The first leader of the match is no shift.

These are descriptive signals for an agent to explain. They are not predictions, and they read no
ground-truth-only field.

Each rule's source is in [GROUNDING.md](GROUNDING.md#statistics-the-numbers-the-agents-explain)
(S1 to S5).

### Truth and detected events

The functions count whatever events they are given: ground truth for grading, detected events
(`source: vision`, ninety/match/detected.py) on the live path. They read only `t`, `type`, `team`
and `x`, which every detected event has (schemas/match_event.schema.json). A detection's confidence
does not drop it from a count: one unsure detection moves a window's count by one, while a claim
about that one event is held by the fact-checker's confidence gate. How far vision's window stats
are from truth's on the same clip is to be measured once R3's detected events land
(docs/EVALUATION.md).

### How the agents read and check them

- **Ledger:** `calculate_facts` includes every window fact, so `load_match` stores them as `fact`
  records citing the events they count.
- **MCP:** `match_info` returns them as `stats` (`windows.agent_rows`): the same id and value as
  the Ledger's fact, plus the window's `minute_from` and `minute_to`, `percent` for a share, and how
  many events it counts. The published Analyst already calls `match_info`, so no tool is added.
- **Fact-checker:** a claim may cite a stat by id. The numbers it may state from one are its value,
  its percent and its window's minutes; any other number is rejected as for an event. An insight
  cue built on a stat lists the events the stat counts as its evidence, as the overlay schema asks.
