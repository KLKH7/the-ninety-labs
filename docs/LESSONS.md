# Lessons

Mistakes this project has already made, so no tool or person makes them twice. Read it before
every task. Each lesson says what went wrong, the rule now, and how to check you are not
repeating it.

**When you catch a mistake, add a lesson here in the same pull request as the fix.** Keep it
short and actionable. This file is public: no research sources, product names or strategy.

## Simulation: results must emerge

### 1. Never script a result
- **What happened:** the match engine decided outcomes and then arranged the world to match: a
  pass was rolled "completed" or "intercepted" at the kick and the interceptor told where to
  stand; a saved shot was aimed at the keeper; a tackle succeeded on a dice roll; "on target"
  was read from where the shot was aimed. It passed every check without being football.
- **Rule:** model the cause (a kick with a velocity, players who react and reach the ball, a
  foot that meets the ball between touches) and let the outcome be observed. Event fields
  (outcome, receiver, end point) are filled from what happened, never from intention.
- **Check:** for every outcome, ask "where in the code is this decided?" If the answer is a
  random draw or a target, it is scripted.

### 2. Never tailor a number to a check
- **What happened:** engine constants sat just under the validator's limits (a tackle distance
  equal to the "ball at feet" limit; a keeper reach just under the hands limit).
- **Rule:** a threshold comes from a cited source or from measurement precision, set before
  looking at the engine's numbers. Never loosen a check or add an exemption to turn it green.
  Calibrating a physical parameter is allowed only within its sourced range.
- **Check:** every constant has a source or a "verify" note in `docs/GROUNDING.md`.

### 3. When removing a script makes things worse, add the missing cause
- **What happened:** honest contact physics dropped goals to zero and restarts to almost none.
  The scripts had been propping up the numbers.
- **Rule:** do not put the script back. Find the missing mechanism (decisions: shooting,
  crossing, clearing, going long) and add it.
- **Check:** realism is judged on several held-out patterns at once (passes, shots, restarts,
  ball-in-play time, pass length), never on the one number being chased.

### 4. The author is the worst auditor of their own scripting
- **What happened:** after "fixing" the engine, an independent audit found 21 more scripted or
  unrealistic shortcuts the author had missed.
- **Rule:** every engine change gets an independent review (a separate agent or person, given
  the code and the rule, not the author's reasoning) before it merges.

### 5. A hard clamp on position is a teleport
- **What happened:** a wall at the touchline stopped players dead; overlapping players were
  pushed apart in one frame. Both broke the acceleration check.
- **Rule:** change position only through velocity, within acceleration limits. Bodies avoid
  each other ahead of time and brace on contact.

### 6. Update order hides state gaps
- **What happened:** a player froze for exactly one frame when winning the ball, because the
  carrier was skipped in the general movement step and only moved by the carrier step from the
  next frame.
- **Rule:** in each tick, every entity is moved exactly once. Track who has already moved.

### 7. Judge a touch on the ball as it arrived
- **What happened:** "was this shot heading on target?" was computed after the deflection had
  already changed the ball's velocity.
- **Rule:** read the state for any judgement before mutating it.

## Checks that prove something

### 8. A check must be able to fail
- **Rule:** every validator check has a test that plants a defect and requires it to fail, and
  every legal case (a kick-off reset, a lofted pass, a substitution at a stoppage) has a test
  that requires it to pass, so no check is stricter than the Laws.
- **What happened:** a planted "ball never arrives" defect showed the ball-path check could
  never fail on short clips. Later, a new braking test stayed green with the braking limit set
  to infinity: an independent reviewer found it by breaking the limit on purpose.
- **Check (mutation test):** for every new check or test, break the thing it guards (set the
  limit to infinity, remove the line) and confirm exactly the intended test goes red; then
  restore and confirm green.

### 9. Passing the validator is not being realistic
- **What happened:** a run where every pass was intercepted met the data contract.
- **Rule:** the validator checks that football is possible; realism is a separate layer of
  pattern checks (`docs/GROUNDING.md`, R rows).

### 10. Margins come from physics and precision, not taste
- **What happened:** the gravity check ignored air drag, and its margin was smaller than the
  rounding error of positions stored to 1 mm (up to 1.25 m/s² on a second difference at 25 fps).
- **Rule:** derive every tolerance and write the derivation next to it.

### 11. Measure both kinds of error
- **What happened:** the first fact-checker judge caught every false claim but also rejected
  18 of 48 true ones, because it treated commentary ("a crucial intervention") as a false fact.
- **Rule:** an evaluation reports misses and false rejections, tunes on one seed and is
  confirmed on a held-out one.

## Working in the repo

### 12. "No checks yet" is not "checks passed"
- **What happened:** a pull request was merged before CI had started on its last commit,
  because the wait loop treated an empty check list as finished.
- **Rule:** wait until every required check has reported, then merge.

### 13. Keep diffs to what you meant to change
- **What happened:** a one-word schema change rewrote 131 lines because a tool reformatted the
  whole file.
- **Rule:** edit the line; check `git diff --stat` before committing.

### 14. Look at the rendered result
- **What happened:** an architecture diagram looked fine as source but GitHub cut it off at a
  fixed height; the next version was too small to read.
- **Rule:** open the rendered page after pushing any diagram.

### 15. A pipeline's exit code is its last command's
- **What happened:** a secret scan written as `grep ... | head; echo $?` reported success, but
  `$?` was `head`'s exit code, so it would have said the same whether or not anything matched.
- **Rule:** test the command whose answer you need on its own (`grep -c`, then its exit code),
  and add a positive control: something you know is there must be found.

## Data and grounding

### 16. Read the primary source
- **What happened:** "well-known" Laws in a draft were wrong or incomplete (throw-in distance,
  goal-kick position, corner distance, which Law covers switching ends).
- **Rule:** check each rule against the current Laws of the Game; implement it in our own
  words; never commit the Laws' text.

### 17. The ground truth is the answer key
- **Rule:** ground truth is used only for training labels and scoring. Nothing on the live path
  reads it. Whatever makes the video must also write the truth, so no generative video.

### 18. A published average already contains the typical situation
- **What happened:** shot estimates started from published scoring rates by distance (averages
  over real shots, most of which face a defender and a keeper on his line), then cut them again
  for every defender and for a keeper on the line. A normal shot was valued at about a fifth of
  the published rate, so players almost never shot.
- **Rule:** adjust a published average only for how a situation differs from the typical one it
  already contains. **Check:** the typical situation must reproduce the published number.

### 19. A quantile of where something happens is not where it starts
- **What happened:** "90% of a team's presses happen within X m of its own goal" was used as the
  line where the team starts pressing. Every team then pressed almost everywhere, turnovers
  doubled and players ran out of energy, while the headline numbers looked near-real.
- **Rule:** before using a number, check that it measures the behaviour it will drive, not a
  neighbouring one. A strong result built on a misread input is worse than a weak honest one.

### 20. Free to download is not free to use
- **What happened:** a table derived from a free but non-open dataset (non-commercial, no
  redistribution) went into the engine and was pushed before its terms were checked against
  our licence and synthetic-data rules; it had to be removed and the branch history rewritten.
- **Rule:** check a data source's licence against the hard rules before its first number goes
  anywhere near the repo. Data that fails them may inform understanding privately, never the
  engine.

### 21. Every engine change gets an independent audit for hard-coding
- **What happened:** fixes made with good intentions repeatedly hid constants tuned toward a
  check, outcomes decided rather than produced, and tests that passed with the change reverted;
  independent audits caught them, the author did not.
- **Rule:** after every engine change, an independent reviewer with no knowledge of the
  author's intent first lists every constant and special case as sourced, design-marked or
  neither, flags anything fitted to a check or scripted, and mutation-tests the new tests,
  before merging.

### 22. When two reviewers disagree about a source, read the source
- **What happened:** one review said our "screened shot" definition differed from the study it
  came from and should change; the change was made. The next review said the opposite. The
  study's own text settled it in a minute: the first review had measured our engine and read
  the result as a statement about the study.
- **Rule:** before acting on a claim about what a source says, read the passage itself, and keep
  "the engine measures X" separate from "the source defines Y".

### 23. An estimate of what the engine does must run the engine's own rules
- **What happened:** the passer's estimate of a pass raced each opponent against the ball reaching
  his own nearest point, even after a team-mate would already have taken it, and left out how the
  engine really loses passes (a body in the lane, a heavy first touch, the passer's own kick
  error, the ball going out). Forced passes it rated 3% arrived about a quarter of the time, so risky passes
  looked worse than they were.
- **Rule:** an estimate of an engine outcome calls the engine's own definitions (the reach test,
  the contact rule, the kick-error model), moved where both can import them, never a copy.
- **Check:** `uv run python -m ninety.sim.calibration` on forced choices, not only chosen ones:
  chosen options hide a pessimistic estimate, because nobody picks what it underrates.

### 24. A trigger guarded only by "not busy now" fires again when the busy state ends
- **What happened:** a keeper's dive was allowed whenever he was not diving and not on the
  ground. A slow shot was still on its way after he had dived, landed and got up, so he dived a
  second time at the same ball. Every condition checked the present; none remembered that the
  touch had already set off a dive.
- **Rule:** an action that happens once per cause records the cause it answered (here the touch,
  `kicked_at`) and checks it, rather than relying on a temporary state to block a repeat.
- **Check:** for each once-per-cause action, write a test where the cause outlives the action's
  own busy state (dive, land, get up, ball still coming) and require no repeat; and one where a
  new cause (a deflection) is allowed to trigger it again.

### 25. Keep every dimension a source measured
- **What happened:** the kick-error source measured a tilted ellipse of where shots cross the goal
  line (a long and a short axis). The engine kept one number, their geometric mean (3°), as the
  sideways error, and gave the up-and-down error a fixed 2° that did not grow with speed, pressure
  or fatigue. Close shots almost never missed: none of 25 unblocked shots inside 25 m in one sample.
- **Rule:** when a source reports a shape (axes, a covariance, a distribution), derive each
  component the engine uses from it, in code, with the derivation beside it. A number that
  summarises a measurement is not the measurement.
- **Check:** for each sourced constant, ask "what did the source actually measure, in how many
  dimensions?" and test the derived values against the source's own figures.

### 26. A committed report must come from the committed code
- **What happened:** two commits regenerated `docs/eval/funnel.md` (1.8 goals a team), yet the
  code of the later one, re-run on a clean checkout of that commit, produced 2.5; the realism test went red with nobody noticing. Twelve
  matches also hide a change of 0.3 goals a team in noise (standard error about 0.27).
- **Rule:** regenerate a report from the exact tree being committed, after the last code change,
  and state how big a difference the sample can resolve.
- **Check:** re-run the report on a clean checkout of the commit and compare before merging.
