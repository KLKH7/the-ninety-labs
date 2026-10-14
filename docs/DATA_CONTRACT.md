# Data contract: ground-truth data

The match engine writes the truth. The renderer draws it. The vision pipeline is graded
against it. This file defines what the engine must write, so whoever builds or replaces a
part can work without waiting for the others. `uv run ninety-validate <clip>` checks it.

## The rule behind everything here

**The truth is the answer key; the vision pipeline takes the exam.** Ground-truth data is used
for exactly two things: training labels and grading. Nothing on the live path (vision, the
stats it feeds, the agents in the demo) reads it. Whatever generates the video must also write
the truth, which is why the video comes from a renderer driven by the engine and never from a
generative video model: a prompt-to-video model writes no truth, so nothing could be graded.

The full pipeline, from engine to validator to renderer to scoring, is drawn in
[ARCHITECTURE.md](ARCHITECTURE.md#synthetic-data-pipeline).

Football logic and physics live in the engine (`ninety/sim`). The renderer only draws: it
decides nothing about football and has no physics of its own. There is one engine: new
scenarios (a counter-attack, a corner) are modes of it, not a second model.

## A clip

A clip is one directory:

| File | Contents | Checked against |
|---|---|---|
| `events.jsonl` | one event per line | [`schemas/match_event.schema.json`](../schemas/match_event.schema.json) |
| `frames.jsonl` | one frame per line, every frame | [`schemas/frame.schema.json`](../schemas/frame.schema.json) |
| `meta.json` | at least `fps`; also `seed` or scenario name | `fps` must be positive |

Coordinates are pitch metres: `x` 0 to 105 toward the right goal, `y` 0 to 68 from the near
touchline, ball `z` is height. Player ids are `h1`..`h11` and `a1`..`a11`. Events from the
engine have `source: "truth"`; the vision pipeline writes the same schema with
`source: "vision"` and a `confidence`, which is what lets the two be compared row for row.

## What the validator checks

Valid is not enough. The events and the frames must tell the same story, and the frames must
be physically possible, because the video is drawn from the frames and graded against the
events.

| Check | Rule |
|---|---|
| files, meta | all three files present; `fps` positive |
| event schema, frame schema | every row matches its schema; events are `source: "truth"` |
| frame order | frames consecutive, `t = frame / fps` |
| roster | the same players, on the same teams, in every frame |
| player speed | no player moves faster than 10.5 m/s between frames, except at a kickoff restart |
| ball speed | the ball never moves faster than 40 m/s (about 145 km/h) |
| event players | every player and receiver is in the frames; the player of a pass or shot plays for the event's team |
| event frame | the event's frame exists and its `t` matches that frame |
| event location | at a pass, shot or tackle, the ball is within 2.5 m of the event's `x`, `y` |
| ball path | a pass or shot reaches its `end_x`, `end_y` by the time its stated speed allows, plus 0.5 s |

Every check has a test that plants one defect and requires it to fail
([`tests/test_validate.py`](../tests/test_validate.py)), so none can pass by checking nothing.

## Today's engine does not pass yet

On seed 7, five minutes, the validator reports 52 player jumps (a pass receiver moves to the
ball in one frame) and 2 ball jumps (the goalkeeper takes the ball after a missed shot). The
data was never meant to be watched; the video will be. Also missing before rendering: ball
flight is a straight line at constant speed with the same arc for every pass, and players have
no acceleration limit. These are the first physics work for the engine.

## The renderer's output (to agree)

The vision pipeline also needs, per frame, what the camera saw. Proposed, to be added to the
frame schema in one pull request agreed by both of us:

- `camera`: intrinsics and extrinsics (or one 3x4 projection matrix) in pitch metres;
- `boxes`: for every player and the ball, the 2D box in pixels and the fraction visible.

The renderer computes boxes by projecting each 3D position through the camera, so the labels
are exact. They are written next to the video and, like all ground truth, never read by the
live path.

## How the agents read data

Agents call the MCP tool `list_events`, which reads from [`ninety/match/facts.py`](../ninety/match/facts.py).
That function is the only place that knows where events come from. Today it runs the
simulator, as a stand-in until the vision pipeline exists; from Milestone 1 it reads detected
events. Changing the engine changes nothing in the agents, the fact-checker or their eval.
