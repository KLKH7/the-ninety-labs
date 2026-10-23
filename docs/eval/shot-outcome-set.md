# The shot-outcome set: pre-registered before any of its clips is rendered

Automatic event detection is to say when a shot is a goal or a save
([shot-outcomes-plan.md](shot-outcomes-plan.md), the rules and their thresholds). The sets we have
cannot measure that:
- the frozen 30-clip test set shows no goal: seed 900014's only goal is struck at frame 5388 and
  its clip ends at frame 5403, the ball last at x = 92.9 (its `events.jsonl` and `frames.jsonl`);
- it shows one save, seed 900004's shot, `outcome: on_target`;
- dataset v2's 24 validation clips (seeds in [fuse-gate.md](fuse-gate.md)) hold no `shot` event.

So this set is rendered for it, by these rules.

- **Matches:** seeds 910001 to 910016, 90 minutes each, used by nothing else (clear of the frozen
  test sets' 900001 to 900030, the training seeds below 900000 and the demo's 8001). Simulated at
  the render commit `6ea8e37aa7510da6e876f2bbe09d415b7eb5d42f` (the tactical training set's; on
  branch `render/tactical-views`, PR #231), with drawn teams and styles:
  `uv run ninety-sim --seed <S> --minutes 90 --out sims/seed<S>`.
- **Split, fixed now:** 910001 to 910008 are **validation** (the detector is developed and its
  thresholds measured there); 910009 to 910016 are **test**, scored once, at a frozen commit. The
  builder reads the test matches' answer keys to place and pick the windows; it writes only each
  clip's place and length, so the test outcomes are not read until they are scored.
- **Windows:** for every `shot` event, from 3.0 s before the strike to 7.0 s after it (whole frames,
  inside the match), 10 s, as every dataset clip. Windows that overlap join, up to 20 s; a later
  shot starts a new window.
- **The subset** (the render budget: all of a match's windows came to about 475 clips): every
  window holding a goal; the first 6 windows in time holding a save (a shot the answer key calls
  `on_target`); the first 2 windows holding neither, for false goals and saves.
  `ninety/eval/shot_outcome_set.py` writes the list, `docs/eval/shot-outcome-set.json`, which is
  committed with a check that re-running it on the matches gives the same bytes.
- **Render:** the broadcast with its labels, `stadium=broadcast` (the look the demo shows), every
  frame (no dead-ball cut, as datasets), the render commit's own renderer and checks. No tactical
  views: a dataset window ends 7 s after the shot, about a minute before the kick-off they would
  show, so they would add nothing to a goal's evidence here. The test split's answer key is sealed
  as the test set's is.
- **What is scored** (`ninety.eval.shot_outcomes score`, *planned*: on branch
  `claude/shot-outcomes`): goal and save precision and recall with 95% Wilson intervals, at the
  fact-checker's gate (`MIN_CONFIDENCE`, 0.5) and without it, each failure listed. False goals and
  saves are also counted on the frozen 30-clip test set.
- **What it cannot show:** the kick-off after a goal (rule 4 of the plan): the goals here are
  judged on the line and the net alone.
