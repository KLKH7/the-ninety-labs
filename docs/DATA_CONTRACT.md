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
| `meta.json` | `fps`; `roster` (each player's `id`, `team` and `role`, so the validator knows the goalkeepers); `seed` or scenario name; `score` (the goals in this clip's `events.jsonl`); `window`, for a clip cut from a longer match | `fps` positive; goalkeepers from `roster`; `score` against the goal events (C9); `window` against the frames |

A rendered clip (`ninety-render`, `ninety-dataset`) is the same directory plus `clip.json` (the
render parameters) and `images/`, and is checked the same way: `uv run ninety-validate <clip>`.

**A window.** A rendered clip is a few seconds cut from a simulated match, so its `meta.json`
carries `window: {"first_frame", "last_frame"}`, the match frames it covers, which must be its
first and last frames. Its frames keep their match numbers, and its events are those inside it.
What happened outside the window is not in the clip, so a judgement that needs it is withheld,
and only when the clip's own frames show that play from beyond the cut is still running:

- C7: a pass with no later on-ball event in the clip, still loose (nobody holds it) and closing on
  its end point at the last frame;
- C8, C3: an interception, goal or substitution with no pass, shot or event before it in the
  clip, and nobody holding the ball from the first frame up to it;
- P3: a window whose first event is a restart, with nobody holding the ball before it, opened on
  a dead ball, so a new ball may be placed.

A window that opens at frame 0 starts with the match and is withheld nothing at its start. A
missing event alone never excuses a judgement, everything whose evidence lies inside the window is
judged exactly as for a whole match, and the same clip without `window` fails. Clips rendered before
the renderer wrote `meta.json` get it from their own files: `uv run ninety-render-meta <clip>...`.

Coordinates are pitch metres: `x` 0 to 105 toward the right goal, `y` 0 to 68 from the near
touchline, ball `z` is height. Player ids are `h1`..`h11` and `a1`..`a11`. Events from the
engine have `source: "truth"`; the vision pipeline writes the same schema with
`source: "vision"` and a `confidence`, which is what lets the two be compared row for row.

## Events

`kickoff`, `pass`, `shot`, `goal`, `tackle`, `interception` (an opponent takes control of a
pass), `deflection` (the ball comes off a player, a block, parry or heavy touch, and stays
free), `pressure`, `possession_change`, `out_of_play`, `set_piece` and `substitution`. A goal
with no `player` is an own goal. Touches (`deflection`, `interception`) must be physically
possible (P14).

## What the validator checks

Valid is not enough. The events and the frames must tell the same story, the frames must be
physically possible, and the match must be legal football, because the video is drawn from
the frames and graded against the events.

Every check, its source in the Laws of the Game or sports science, and whether the validator
and the engine meet it today, is in one place: the register, [GROUNDING.md](GROUNDING.md).
Check IDs (C1, P2, L7) are the same there, in the validator's output and in its tests.

Every check has a test that plants a defect and requires it to fail
([`tests/test_validate.py`](../tests/test_validate.py)), so none can pass by checking nothing.
Legal cases (a kick-off reset, a substitution at a stoppage, a lofted pass under gravity) have
tests that require them to pass, so no check is stricter than the Laws.

## Today's engine

`uv run ninety-sim --seed 7 --minutes 90 --out runs/seed7` then
`uv run ninety-validate runs/seed7`: meets the contract. Players
decide and physics decides what happens: a kick gives the ball a velocity, the ball flies under
gravity and air drag, bounces and rolls (`ninety/sim/ball.py`), each team sends the player who
can reach it first, and whoever gets there takes it. Completed and intercepted passes, saves,
goals and balls going out are results, never decided at the kick. What the engine still does not
model (opponents' distance at restarts, halves, offside, officials, enough stoppages) is listed,
with sources, in [GROUNDING.md](GROUNDING.md).

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
