# The set-piece set: pre-registered before any of its clips is chosen or rendered

Automatic event detection is being extended to restarts (throw-in, goal kick, corner, free kick,
penalty, kick-off) and to the camera fit across the broadcast's edit cut into a restart. The sets
we have cannot measure either:
- the frozen test set (`docs/eval/test-set-frozen.json`; seeds 900001 to 900030,
  `ninety/render/splits.py`) is 10 s windows chosen for the ball on the pitch, not for restarts,
  rendered every frame with no edit cut;
- the shot-outcome set ([shot-outcome-set.md](shot-outcome-set.md)) is chosen around shots, also
  with no cut.

So this set is rendered for it, by these rules, written before any of its matches was simulated.

- **Matches:** seeds 920101 to 920115 (**validation**) and 920201 to 920230 (**test**), the first
  35 minutes of each, used by nothing else: clear of the training seeds (below 900000), the frozen
  test sets (900001 to 900030), the shot-outcome set (910001 to 910016) and the demo (8001 to
  8050). Seed 920001 was simulated once, before this was written, only to time a 90-minute
  simulation on a shared laptop; it is in neither split and its events were not read.
  `uv run ninety-sim --seed <S> --minutes 35 --out <sims>/seed<S>`, at the render commit below.
  The engine plays the match frame by frame from kick-off, so the first 35 minutes of a longer
  match are the same frames; 35 minutes keeps the simulation and the render of a late window cheap.
- **Render commit:** `ac21ccc76e815d308490eaf6aa73fb199324affa`, `main` when this was written
  (renderer 0.5.17), recorded in `ninety/eval/set_piece_set.py` as
  `RENDER_COMMIT`. This set adds no engine or renderer change. The set's windows are a function of the rule and that commit's engine: if the
  set is rendered at another commit, the windows are re-chosen by this rule there, never carried
  over, and the change is recorded here.
- **Split, fixed now:** detectors are developed and their thresholds measured on validation; test
  is scored once, at a frozen commit. The same seeds and split serve the possession set
  ([possession-set.md](possession-set.md)), so no match is validation for one and test for the other.
- **The restart's kind** is not written in the answer key (`set_piece` carries no kind), so it is
  read from the key by one rule, `restart_kind` in `ninety/eval/set_piece_set.py` (Laws 13 to 17):
  a set piece after a `foul` on a penalty mark (11 m out, on the goal's centre line, to 0.5 m) is a
  penalty, after any other `foul` or an `offside` a free kick; after an `out_of_play` over a
  touchline a throw-in, over a goal line a goal kick when the ball is placed in the goal area and a
  corner when it is placed at a corner; a set piece with no stoppage since the last, from that
  restart's own spot, is that restart taken again; a `kickoff` is a kick-off. A test runs the
  engine and checks the rule against the engine's own kind for every restart it gives.
- **Windows:** one per restart, on whole frames, in the broadcast as a viewer sees it
  (`dead_ball_cut`, `ninety/render/edit.py`): from 2 s before the event that stopped play (the
  stoppage, then the edit's hold on it, the cut, and the picture back 2 s before the restart) to
  6 s after the restart (the kick and its first touch). A kick-off at the start of the match has no
  stoppage; its window opens at frame 0. The window's length is the frames it shows (cut frames do
  not count), found from the render's own `edit.plan`, so the rendered clip is exactly the window.
  A window whose start lies inside the last window joins it, up to 30 s shown; one that would make
  it longer is dropped and counted, never shifted. Only windows ending by minute 32 are used, so the
  simulation runs at least the render's margin (`SIM_MARGIN_S`, 180 s) past every window, as the
  render does (lesson 140).
- **The subset** (the render budget): matches in seed order, windows in time order; a window is
  kept while any kind it holds is short of its split's target: **30 of each kind in test, 15 in
  validation**, every penalty. 30 is the most this budget renders for every kind. At a detection
  rate of 0.8 its 95% Wilson interval is 0.63 to 0.90, at 0.9 it is 0.74 to 0.97, and at 0.5 it
  is 0.33 to 0.67. A penalty comes about once in four 90-minute matches, so the set holds the few
  the seeds give; they are reported as counts, never as a rate.
- **Written:** `ninety/eval/set_piece_set.py` writes `docs/eval/set-piece-set.json`: each clip's
  split, seed, start and length, and the totals of each kind per split. Which clip holds which
  kind is not written, so the test split's labels stay unread until it is scored. A test checks
  that re-running it on the matches gives the same bytes.
- **Render:** the broadcast with its labels, `stadium=broadcast` (the look the demo shows),
  `dead_ball_cut=true`, no tactical views, the render commit's own renderer and checks:
  `uv run ninety-render --seed <S> --start <start> --seconds <seconds> --set stadium=broadcast
  --set dead_ball_cut=true --out <out>/<split>/seed<S>-<start>`, then
  `uv run ninety-validate <clip>` on every clip. The test split's answer key (`frames.jsonl`,
  `events.jsonl`, `meta.json`) is sealed as the frozen test set's is (`truth-test`), and its
  digests are frozen in `docs/eval/set-piece-set-test-frozen.json`.
- **What is scored:** per kind, the share of restarts detected with the right kind, at the
  fact-checker's gate and without it, with 95% Wilson intervals and each failure listed; false
  restarts per clip; and, where the clip makes a cut, the camera fit's error on the frames either
  side of it.
- **What it cannot show:** a rate for penalties (too few); restarts after minute 32 of a match
  (late-match fatigue); and how often each kind occurs in a match, since the subset caps the
  common kinds.

## Counts

Filled in from `docs/eval/set-piece-set.json` once the chooser has run: windows per split and
restarts of each kind per split, with the windows dropped for overlap.
