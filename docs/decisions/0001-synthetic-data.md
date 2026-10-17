# 0001: How we generate synthetic football data

- **Status:** accepted, Oct 13, 2026
- **Rubric:** technological implementation ("creative, optimized synthetic data creation") and
  data innovation (brief item (v)); it also feeds agentic design, through the Vision Auditor and
  Data agent loop.
- **Measured by:** [EVALUATION.md, synthetic data](../EVALUATION.md#synthetic-data)

## What we need

Two linked kinds of data, from one seed:

1. **Match events and tracking:** every pass, shot, tackle and possession change, plus every
   player and ball position at 25 fps. The agent track runs on these today.
2. **Broadcast-style video of that same match**, with exact per-frame ground truth: camera
   matrix, player and ball boxes, visibility and pitch keypoints. Automatic event detection is
   trained and graded on it.

On top of that, the generator has to produce **hard cases on demand** (occlusion, motion blur,
crowded boxes, low-contrast kits), because the targeted-data rounds are our differentiator.

## Hard filters (from AGENTS.md), applied before scoring

| Option | Synthetic only | MIT / Apache / BSD | Labels from the generator | Result |
|---|---|---|---|---|
| A. Our simulator + our three.js renderer | yes | yes (three.js MIT, Playwright Apache-2.0, Chromium BSD) | yes | **scored** |
| B. Our simulator + a pure-Python software rasterizer | yes | yes | yes | **scored** |
| C. Google Research Football as event and video source | yes | reported Apache-2.0 (built on the Gameplay Football engine) | only after C++ engine changes | **scored** |
| D. RoboCup soccer server (rcssserver) | yes | **LGPL-3.0** | 2D only, no video | rejected |
| E. Unity / Unreal (the SoccerSynth approach), or Blender | yes | **proprietary EULA / GPL-3.0** as a build dependency | yes | rejected |
| F. Event logs only, no video (today's `ninety-sim`) | yes | yes | yes | **scored** (agent track) |
| G. Generative video or image models | risky: trained on real broadcasts, can reproduce kits, crests and graphics | varies | **no**: a model guesses where players are, which breaks "code computes every number" | rejected for training data |
| H. Real match data or footage | **no** | n/a | n/a | rejected; published per-match averages are only used to calibrate the simulator's rates, cited and never committed |
| I. A published synthetic dataset (e.g. SoccerSynth-Detection) | yes | no licence stated | yes, but not linked to our events | rejected |

## Scores (1 = poor, 5 = best)

| | A. sim + three.js | B. sim + Python rasterizer | C. Google Research Football | F. events only |
|---|---|---|---|---|
| Rubric fit: how a judge sees it in the video | 5: our own broadcast with live boxes, and a "made more of what failed" round | 4: same story, plainer pictures | 3: recognisable game graphics, someone else's engine | 2: no video, so no automatic event detection |
| Exact ground truth | 5: camera matrix from code; visibility and boxes counted from an id pass of exactly what was drawn | 5 | 3: needs engine changes to export camera and boxes | 5 |
| Realism for detector transfer | 3 today, room to grow (PBR materials, shadows, textures, GPU) | 2: flat shading, hard to improve | 3: fixed 2019 game look | n/a |
| Control over hard cases | 5: every knob is our parameter | 5 | 3: scenario scripts, little control of camera and look | 2 |
| Generation speed | 3: 0.47 s (overcast) to 0.61 s (sun shadows) per 720p frame on 4 CPU cores in software GL; faster on a GPU (`--gpu`) | 3 | 4 | 5 |
| Cost | 5: free, runs locally or in CI | 5 | 5 | 5 |
| Time to first clip (renderer v1 due Oct 15) | 5: running today | 4 | 2: C++ build, camera export, licence review | 5 |
| **Total** | **31** | 28 | 23 | 24 |

## Decision

**A: extend our seeded simulator and render it ourselves in three.js**, as the architecture
already planned, with one change in how the work is split:

- **Python owns the scene.** For every frame it computes the broadcast camera (pinhole, exact
  `P = K [R | t]`), every player's body as capsules in world metres, and the ball, then sends
  them to the page. The geometry that is drawn and the geometry that is labelled are the same
  numbers.
- **three.js draws, then counts.** Besides the picture, the page renders an object-id pass: each
  player alone (their full in-image silhouette) and all together (what is still visible, with
  the goal frame and scorebug as occluders). Boxes, visibility and keypoint visibility come
  from those counts, never from an estimate.
- **Software GL by default** (SwiftShader in headless Chromium), so the same seed gives the same
  pixels and labels on the same Chromium build. `--gpu` trades reproducibility for speed.
- **Option F stays** as the agent track's feed (`ninety-sim`), and the same seed's events ship
  alongside every clip.

## What we give up

- **Photorealism, for now.** Players are capsule figures with kit colours and a running gait,
  not motion-captured meshes. The off-the-shelf detector check (guide section 6.2) decides
  whether the realism pass on Oct 17 is enough.
- **Speed on CPU.** 2 to 2.5 minutes per 10-second clip on 4 cores (the 5-clip test set took 11.5
  minutes). 20 training clips plus the test set take about an hour; longer clips or bigger rounds
  want a GPU machine.
- **A browser in the toolchain.** Generation needs Node (for three.js) and Chromium. CI installs
  both in a dedicated `render` job.
- **Bit-identical pixels across machines.** Only guaranteed on the same Chromium build; the build
  is recorded in every `clip.json`.
- **Parquet, for now.** Frame labels are compact JSON lines (about 4.4 KB a frame, so a 5-minute
  clip is about 33 MB). The Parquet export in ARCHITECTURE.md is planned for when clips get long.

## How we will know it worked

From [EVALUATION.md](../EVALUATION.md#synthetic-data), reported by `ninety-render-check` into
`docs/eval/render-checks.json`:

| Check (render guide section 6) | Bar | Status |
|---|---|---|
| 1. Ground truth projects onto its pixels | ball centre within 1 px of its drawn pixels; keypoints within 1 px; every player's foot point inside its box | running in CI |
| 2. Off-the-shelf detector recall on 200 frames | close to the same detector on real broadcast footage | planned (needs the detector, Oct 18) |
| 3. Ball occlusion | share of in-frame ball frames with visibility under 0.5 is above zero | running |
| 4. Determinism | same seed renders identical labels and images | running in CI |
| 5. Look at it | side-by-side with real broadcast framing; fix the biggest difference first | manual, at each realism pass |
| Split integrity | test seeds (900001 to 900005) never train; overrides refused on the test set | running in unit tests |

### First measurement (Oct 14, fixed test set, 5 clips, 1,250 frames)

From `docs/eval/render-checks.json`: ball projection error mean 0.10 px, max 0.30 px; keypoints
max 0.0014 px; every player's foot inside its box; no frame with a label problem; the re-render of
seed 900001 matched labels and all 250 images byte for byte. Players are 38 to 102 px tall
(5th to 95th percentile across clips), inside the guide's 30 to 120 px.

**Not good enough yet:** the ball is under 0.5 visible in 1 of 1,250 frames (0.08%). The check
passes (above zero), but the test set is too easy, because the simulator has no corners, free
kicks or goalmouth scrambles, so players rarely crowd the ball. That is the first thing the
realism pass and the simulator's set pieces must change.

### Second measurement (Oct 17, day and clear only, same 5 seeds)

Dusk, night, overcast and rain did not yet look like broadcast footage, so every clip is now a
clear day (`PLANNED` in `ninety/render/params.py`). Four of the five test seeds had been
overcast, dusk or rain, and the engine has changed since Oct 14 (portable math, #55), so the
whole test set was re-rendered at commit `e587b48`.

From `docs/eval/render-checks.json`: ball projection error mean 0.08 px, max 0.26 px; keypoints
max 0.0035 px; every player's foot inside its box; no frame with a label problem; the re-render
of seed 900001 matched labels and all 250 images byte for byte.

- The ball is under 0.5 visible in 51 of 1,250 frames (**4.08%**; per clip 6.0%, 4.0%, 0%,
  6.0%, 4.4%). Better than 0.08%, but **short of the minimum**: PLAN.md and EVALUATION.md need
  at least 5% before the test set is frozen (Oct 18), so it is not ready to freeze. Passing the
  render checks does not change that.
- Player height p05 is 16 px in seed 900001, under the guide's 30 px; the other four clips are
  31 to 54 px at p05, and every clip's p95 is 86 to 106 px. Not yet traced.

### Third measurement (Oct 17, hard cases drawn from the seed)

`kit_contrast` and `occlusion` used to change only with `--set`, which the test set refuses, so
the test set could never hold a crowded window or low-contrast kits. They are now drawn from the
seed at `HARD_CASE_RATE` = 0.3, set from the train floors before rendering, not from this number.
Re-rendered at commit `6269283`: seeds 900001, 900002 and 900004 are crowded, 900004 has
low-contrast kits.

All checks pass (ball projection max 0.30 px, keypoints max 0.0015 px, determinism identical).

- The ball is under 0.5 visible in 55 of 1,250 frames (**4.40%**; crowded clips 6.4%, 8.8%,
  2.4%; natural clips 0% and 4.4%). Still **short of the 5% minimum**, so the test set is still
  not ready to freeze. The rate is not raised to reach 5%; whether to move the freeze or change
  the test set's design is R2's decision.
- Player height p05 is 9 px in seed 900004 (the 16 px case moved from 900001 to 900004 with the
  new window), under the guide's 30 px. Not yet traced; a camera cut is the first suspect.

The final proof comes later: detector recall on the fixed test set before and after each
targeted round.

### Realism pass (Oct 14)

The match being filmed is the full engine: players decide, the body and the ball move under
physics, and the picture reads that state back. The ball is drawn where the engine left it.
Heading, speed, a strike and a keeper's dive are the engine's, and the limbs are posed from
them. The wide shot is a bowl of seats under a roof, with a grass surface and a run-off around
the pitch. Each limb is one solid volume on the engine's capsule, with a chest and hips, so the
labelled silhouette is still the body that was drawn. Stands, grass and roofs stay decor.
What changed in the picture, and two knobs that used to fail loudly:

- shirts carry a seeded pattern in a shader and a number from a glyph texture, both on the
  capsules Python already labelled. The labelled silhouette is the one that is drawn
- `weather=rain` darkens the grass, lowers its roughness and draws streaks. Streaks are an image
  effect, like motion blur: they are not an occluder, and visibility stays a count of geometry
- `camera_cut=true` leaves the gantry only when another angle frames the ball better: high
  behind the goal while the ball is in that penalty area, a low three-quarter beside the goal
  for the four seconds after a goal (aimed at the mouth, since the ball is already back on the
  centre spot), a tighter lens beside the gantry for a throw or an aerial touch when that shot
  still holds the player and the ball, or the far stand when play is on the far side, that
  camera is much closer, and its shot still holds the ball and the opposite stand. Both that
  shot and the gantry look up into the bowl on a lens long enough that a player still has a
  body, so the stand is the backdrop. The gantry
  is the shot the match is watched from, and each angle, including the return, is held for at
  least four seconds. The gantry itself is lowered to 23° down to the near touchline (the
  handbook's 22 to 24°) without moving the sampled height, so seed 5's draw stays put. The cut
  is logged as `camera.angle`. A cut is not a pan, so the blur streak is zero on the frame the
  camera jumps. The net is decor. On a goal it gives outward behind the line and settles, and
  it stays out of the id pass
- the stands hold drawn spectators, including a near stand that sits behind the gantry so the
  reverse angle has a stadium behind the pitch. Sky, floodlight towers and sharpening are decor,
  not occluders

A referee is still not drawn. The renderer only draws, and the engine does not have an official
yet. Inventing one would put a person on the pitch that the match does not contain.
