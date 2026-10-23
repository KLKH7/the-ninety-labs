# The shot-outcome set: pre-registered before any of its matches is simulated or rendered

Automatic event detection is to say when a shot is a goal or a save
([shot-outcomes-plan.md](shot-outcomes-plan.md)). The sets we have cannot measure that. The frozen
30-clip test set shows no goal (seed 900014's goal is struck 15 frames before its clip ends) and one
save (900004), and dataset v2's 24 validation clips hold no shot. So this set is rendered for it:
every shot of whole matches, decided by these rules before anything is simulated.

- **Matches:** seeds 910001 to 910016, 90 minutes each, simulated at the render commit
  `6ea8e37aa7510da6e876f2bbe09d415b7eb5d42f` (the tactical training set's), drawn teams and
  styles as any seed. They are new seeds, used by nothing else.
- **Split, fixed now:** 910001 to 910008 are **validation** (the detector is developed and its
  thresholds measured there); 910009 to 910016 are **test**, scored once, at a frozen commit, and
  not opened before.
- **Windows:** for every `shot` event in the match's answer key, from 3.0 s before the strike to
  7.0 s after it (whole frames, inside the match), 10 s, as every dataset clip. Windows that
  overlap are joined into one longer window. No shot is left out and none is chosen by hand.
  `ninety/eval/shot_outcome_set.py` turns the matches' events into the list of windows,
  `docs/eval/shot-outcome-set.json`, which is committed before the render starts.
- **Render:** broadcast plus the two tactical views (`--views tactical`), `stadium=broadcast` (the
  look the demo shows), every frame (no dead-ball cut, as datasets), the render commit's own
  renderer and checks. Session A renders it on the rented machine after the tactical fine-tune.
  The test split's answer key is sealed as the test set's is.
- **What is scored:** goal and save precision and recall with 95% Wilson intervals, at the
  fact-checker's gate (0.5) and without it, each failure listed
  (`uv run python -m ninety.eval.shot_outcomes score`). False goals and saves are also counted on
  the frozen 30-clip test set.
- **What it cannot show:** the kick-off after a goal. Dataset windows show every frame, and the
  kick-off comes about a minute later, so the goals here are judged on the line and the net alone
  (the plan's rule 4 adds evidence only where the clip shows it).
