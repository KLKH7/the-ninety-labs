# The possession set: pre-registered before any of its clips is chosen or rendered

Automatic event detection is being extended to possession changes, interceptions and tackles. The
frozen test set's 10 s windows are chosen for the ball on the pitch, not for turnovers, so they
hold too few to give any of these a rate with a usable interval. So this set is rendered for it, by
these rules, written before any of its matches was simulated, together with the set-piece set
([set-piece-set.md](set-piece-set.md)).

- **Matches and split:** the set-piece set's: seeds 920101 to 920115 (**validation**) and 920201 to
  920230 (**test**), the first 35 minutes of each, at the same render commit
  (`ac21ccc76e815d308490eaf6aa73fb199324affa`, renderer 0.5.17), simulated once for both sets. A
  match is in the same split for both, so nothing developed on one set's validation has seen the
  other's test matches.
- **Windows:** the match cut into consecutive 10 s windows from its first frame (frames 0 to 249,
  250 to 499, ...), whole frames, as every dataset clip; only windows ending by minute 32 (the
  render's simulation margin, lesson 140). A fixed grid, so no window is placed around an event.
- **Score:** the window's `possession_change`, `interception` and `tackle` events, counted
  together (the answer key's own events, Data contract). Ties go to the window with more
  `interception` and `tackle` events, then to the earlier one.
- **The subset** (the render budget): the **2 highest-scoring windows of each match**, so 60 test
  windows and 30 validation windows. A turnover-rich window is what makes the rates measurable at
  this budget; it is also busier than the average 10 s of a match, so what this set measures is
  recall and timing on turnovers, and false events per clip in busy play; a false-event rate for
  ordinary play comes from the frozen test set.
- **Written:** `ninety/eval/possession_set.py` writes `docs/eval/possession-set.json`: each clip's
  split, seed, start and length, and per split the totals of each event type the windows hold.
  Which clip holds what is not written. A test checks that re-running it on the matches gives the
  same bytes.
- **Render:** the broadcast with its labels, `stadium=broadcast`, every frame
  (`dead_ball_cut=false`, as datasets and the shot-outcome set), no tactical views:
  `uv run ninety-render --seed <S> --start <start> --seconds 10 --set stadium=broadcast
  --set dead_ball_cut=false --out <out>/<split>/seed<S>-<start>`, then
  `uv run ninety-validate <clip>` on every clip. The test split's answer key is sealed as the
  frozen test set's is, and its digests are frozen in `docs/eval/possession-set-test-frozen.json`.
- **What is scored:** recall of each type (a detected event of that type within the scorer's time
  and place tolerance, `ninety/eval/event_score.py`), the winning side's accuracy, and false events
  per clip, with 95% Wilson intervals, at the fact-checker's gate and without it.
- **Targets, set now:** 60 of each type in test, where the per-type 95% Wilson interval at a rate
  of 0.8 is 0.68 to 0.88. Possession changes far exceed it; whether interceptions and tackles reach
  it is reported from the counts, never fixed by choosing more windows after the fact.

## Counts

Filled in from `docs/eval/possession-set.json` once the chooser has run.
