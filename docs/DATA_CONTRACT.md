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
| `meta.json` | `fps`; `roster` (each player's `id`, `team` and `role`, so the validator knows the goalkeepers); `seed` or scenario name; `score` (the goals in this clip's `events.jsonl`); `window`, for a clip cut from a longer match; `cuts`, the dead balls the broadcast cut away from | `fps` positive; goalkeepers from `roster`; `score` against the goal events (C9); `window` against the frames; `cuts` against the frames and the events (C2) |

A rendered clip (`ninety-render`, `ninety-dataset`) is the same directory plus `clip.json` (the
render parameters) and `images/`, and is checked the same way: `uv run ninety-validate <clip>`.

**A player down (renderer 0.5.10 on).** While a fouled player is drawn lying over his feet, his
player row in `frames.jsonl` carries `fall`, the degrees his body is over (0 to 90); a standing
player's row has no `fall`. The field is optional and additive: positions, ball and events are
unchanged, clips rendered before 0.5.10 have none and stay valid, and the render check judges a
row with `fall` by its ground point inside the box rather than at its bottom (GROUNDING V5).

**A window.** A rendered clip is a few seconds cut from a simulated match, so its `meta.json`
carries `window: {"first_frame", "last_frame"}`, the match frames it covers, which must be its
first and last frames. Its frames keep their match numbers, and its events are those inside it.
What happened outside the window is not in the clip, so a judgement that needs it is withheld,
and only when the clip's own frames show that play from beyond the cut is still running:

- C7: a pass with no later on-ball event in the clip, which nobody has held since it was played,
  and whose last frame's motion, carried on in a straight line, passes within `NEAR_M` of its end
  point ahead of it; or a pass struck on the clip's last frame, none of whose flight is in the clip;
- C8: an interception or goal with no pass or shot before it in the clip, and the ball loose and
  moving from the first frame up to it (moving: farther than rounding alone can move a ball at
  rest, `2 * sqrt(3) * POSITION_PRECISION_M` a frame, about 1.7 mm, so a ball at rest is not a
  pass in flight);
- C3: a substitution with no event before it in the clip, nobody holding the ball from the first
  frame up to it, and no open play after it before a restart (Law 3);
- P3: a window whose first event is a restart, with nobody holding the ball before it, opened on
  a dead ball, so a new ball may be placed.

**A cut.** A broadcast does not show the whole of a stoppage: the engine plays every second of
the wait before a restart (GROUNDING R1: 16 s for a throw-in, up to 41 s for a free kick), and the
rendered picture stays on the stoppage a moment, then cuts to the restart being set
(`ninety/render/edit.py`). Only a broadcast clip cuts (`dead_ball_cut`, on in `ninety-render`
outside the test set): datasets, the Azure job, training rounds and the test sets show every frame.
The match frames a cut leaves out are recorded in `meta.json` as `cuts: [{"first_frame",
"last_frame"}]` (frame numbers), and the frames on either side keep their match numbers and times.
A cut lies wholly inside a dead ball, and the clip shows that ball dead at both ends: the event that
stopped play (`out_of_play`, `foul`, `offside`, `goal`) before the cut and the restart that ends it
(`set_piece`, `kickoff`) after it are both events of the clip, no touch of the ball in play and no
other restart lies between them, and no event is inside the cut, so every event of the clip is on a
frame it shows (C2, C5). The physics checks judge
consecutive frames only, never the jump across a cut. `clip.json` also carries `segments`, the runs
of consecutive frames the images show (image `index` is match frame `frame`): whatever maps video
time to match time (the viewer, the audio description) reads them through `ninety/match/timeline.py`
instead of adding the clip's start, and a reader that links frames (vision's tracks and passes)
links nothing across a cut.

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

From Milestone 1 the live path (the Ledger, the stats, the MCP tool `list_events`, the
fact-checker and the overlay cues) reads detected events only, through
[`ninety/match/detected.py`](../ninety/match/detected.py). That module accepts only valid
`match_event` records with `"source": "vision"` and a `confidence`. It refuses ground-truth
events and any file named `events.jsonl` or `frames.jsonl`. `uv run ninety-live --out cues.jsonl`
runs the path on the M1 clip ([`ninety/agents/live.py`](../ninety/agents/live.py)).
[`tests/test_live_reads_no_truth.py`](../tests/test_live_reads_no_truth.py) runs the path with
an audit hook on every file it opens. It fails if the path opens the answer key or loads any of
our code that writes, reads or fetches it.

Until the detector's events for the M1 clip land (`tests/fixtures/detected-seed900001.jsonl`),
the path reads a hand-written stand-in, `tests/fixtures/detected-standin-seed900001.jsonl`. Every
one of its ids starts with `standin-`, and it was never derived from ground truth.

The fact-checker holds back any claim that cites a detection below `MIN_CONFIDENCE`
([`ninety/agents/factcheck.py`](../ninety/agents/factcheck.py)), and no template cue airs on such
a detection. The threshold is a design value until it is measured from the event report.

The simulator's matches (`seed7`, `seed21`, `seed33` in [`ninety/mcp/match_server.py`](../ninety/mcp/match_server.py))
remain the pre-M1 stand-in for the committed replays and the agent evaluation. The simulator is
imported only when those are asked for.
