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

### 40. A constant defined twice keeps only the last value
- **What happened:** the engine defined the same constant name twice for two different ideas: how
  far goal-side of the ball the covering player stands (8 m), and the radius within which a
  team-mate counts as cover for a tackle (10 m). The second silently replaced the first, so the
  cover stood 10 m from the ball. Lint did not flag it.
- **Rule:** one name, one meaning. Name a constant after what it measures, not the word it shares
  with another rule.
- **Check:** `tests/test_constants.py` fails if any module in `ninety/` assigns a top-level name
  twice.

### 46. Same seed, same match, on every machine
- **What happened:** seed 7 simulated a different match on macOS from the one on Linux, so the cue
  fixture test failed on a Mac and "156 cues" could not be reproduced there. The engine was
  deterministic; the C math library was not. Apple's `exp`, `erf`, `sin` and the rest disagree
  with glibc's in the last bit for some inputs, a player's profile differed by one bit, and a
  chaotic match grew that into different events within two minutes. A report already noted "the
  same seed can simulate a slightly different match on another operating system" without
  anyone tracing it. Review of the fix then found its helpers silently wrong outside the range
  the engine uses (`sin(1e20)` gave 2.7e27; the inverse cdf gave -14.06 for p = 1e-100), and
  the check blind to `from random import Random`.
- **Rule:** code that writes ground truth or a published number computes with operations IEEE
  754 rounds exactly (+, -, *, /, `sqrt`) and `ninety/sim/fmath.py`, never `math.exp`,
  `math.sin`, `**`, `random.gauss` or `NormalDist`. A difference between machines is a defect
  to trace, not a caveat to print. A numerical helper computes its whole stated domain or
  refuses what it cannot.
- **Check:** `tests/test_fmath.py` fails if `ninety/sim`, `ninety/match` or `ninety/eval` calls
  the C math library, and pins `fmath`'s results bit for bit; CI runs it and the cue fixture on
  Linux and macOS.

## Checks that prove something

### 8. A check must be able to fail
- **Rule:** every validator check has a test that plants a defect and requires it to fail, and
  every legal case (a kick-off reset, a lofted pass, a substitution at a stoppage) has a test
  that requires it to pass, so no check is stricter than the Laws.
- **What happened:** a planted "ball never arrives" defect showed the ball-path check could
  never fail on short clips. Later, a new braking test stayed green with the braking limit set
  to infinity: an independent reviewer found it by breaking the limit on purpose.
  Again in the throw-in fix (#44): every test stayed green with the spot tolerance widened to
  1 m, the settle speed raised to 1 m/s, or a snap to the spot put back; each now has its own test.
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

### 41. A check that never meets the case cannot fail
- **What happened:** the throw-in taker was moved the last metre to his spot in one frame (about
  22 m/s) and stopped dead with the ball. The validator's speed check catches it, but CI validates
  only a 3-minute clip, and the first throw-in of that seed comes after 5 minutes. The realism
  report showed full-backs and wingers at 20 to 24 m/s, and nothing failed.
- **Rule:** a check runs on data that contains the case it guards, and the test says so.
- **Check:** `tests/test_engine_rules.py::test_a_throw_in_taker_runs_to_his_spot_and_stops_there`
  asserts a throw-in happened before checking speeds; it fails on the old engine.

### 48. Score only what was run
- **What happened:** the vision scorer built labels from every row of `frames.jsonl`, and
  flattening the detections dropped frames with an empty list, so it could not tell "ran and
  found nothing" from "never ran". Detecting every 25th frame of a 250-frame clip with the COCO
  RF-DETR checkpoint scored player recall 0.04 (TP 89, FN 2102); on the 10 frames actually run it
  is 0.99 (TP 89, FN 1). The detections contract already said an empty list marks a run frame;
  the scorer did not read it.
- **Rule:** an evaluation scores only the inputs the system was given. Read the set of run
  frames before any step that can drop empty records, and report how many were scored and
  skipped, so a denominator is visible rather than assumed.
- **Check:** `tests/test_vision_score.py::test_only_frames_the_detector_ran_on_are_scored`
  fails on the original code (FN 6 instead of 3). The overlay tool (`ninety/eval/draw.py`) had
  the same flaw and drew unrun frames as misses;
  `tests/test_draw.py::test_only_frames_the_detector_ran_on_are_drawn_and_counted` fails on it
  (4 misses over 3 frames instead of 2 over 2).

### 72. A rule for every clip must run on every kind of clip
- **What happened:** AGENTS.md says every clip passes `ninety-validate`, but the renderer wrote
  `clip.json` and never the contract's `meta.json`, so the validator rejected every rendered clip
  ("missing meta.json") and no training clip was ever checked against the contract. The render
  checks passed, because they checked pixels and boxes, not the contract. Given a `meta.json`, 10 of
  25 training and test windows still failed, each on what lay beyond its cut: a pass still in the
  air at the last frame, an interception whose pass came before the first, a restart for a ball
  that went out before the window.
  The first fix withheld a judgement whenever the event that settles it was missing from the
  clip; an independent review then passed five planted defects whose evidence was inside the
  window (a pass to a player who held the ball, an interception from a man in possession). The
  owner's review of the second version found four more: a ball heading 60° wide of its end point
  counted as "closing", a pass held mid-window then let go counted as unfinished, a ball at rest
  for four seconds counted as a pass in flight, and open play after a substitution did not count
  as play. One "legal" goal fixture gave a goal with the ball at rest 55 m out.
  Backfilling the first Azure top-up then showed the reverse: a pass struck on a clip's last frame
  failed C7, judged on the dribble before the kick, because none of its flight was in the clip.
- **Rule:** a contract every clip must meet is run by the code that makes clips, as part of the
  check that decides whether a clip ships. A clip that is part of something larger says so in
  its metadata, and a check withholds a judgement only when the clip's own frames show the play
  from beyond the cut still running (the ball loose since the first frame, a pass still closing
  on its end at the last). A missing event alone is never a reason. Each condition is the strict
  physical one (the ball's path meets the end point, the ball is moving), not a proxy for it
  (getting closer, nobody touching it). A legal fixture must itself be football. A test asserts the
  message it expects, not only the check's key, so another problem filed under that key cannot
  turn it red.
- **Check:** `tests/test_render_clip.py::test_a_rendered_clip_meets_the_data_contract` fails on
  the old renderer; `check_clip` reports `data_contract`, so the render job refuses a clip that
  fails it; the window tests in `tests/test_validate.py` pass each cut case, fail the same clip
  without `window`, and fail each planted defect from both reviews. 26 mutations of the rule:
  all killed except one equivalent mutant (a ball at rest within reach already meets C7).

### 73. Test each half of a guard with a case only that half catches
- **What happened:** the export's leak guard refuses a clip if its seed is not a training seed *or*
  its `clip.json` does not say `train`. The test's bad clips were wrong both ways at once, so
  either half could be deleted and the test still passed (#76 review).
- **Rule:** a guard made of several conditions gets one case per condition that is wrong in that
  way only.
- **Check:** delete each condition in turn; a test must fail each time (lesson 21's mutation test).
- **Also:** a guard's fallback is part of the guard. `train-on-gpu.sh` fell back to our real
  storage account's name when none was set, putting it in a public repo. A missing setting stops
  the script with what to set; it never falls back to a real resource name.

### 74. A before-and-after changes one thing
- **What happened:** the COCO baseline ran at rfdetr's default input size, 512, and the fine-tuned
  model at 640, so any gain mixed the training with the input size (#76 review).
- **Rule:** a comparison changes only the thing it measures; everything else (input size, frames,
  scorer, threshold) is the same on both sides, and the default that would differ is set
  explicitly.
- **Check:** the two `detections.jsonl` runs are made by one command with only `--checkpoint` and
  `--weights` different; `tests/test_vision_finetune.py` pins the baseline to finetune.json's size.

### 82. A structural change chosen from a report, justified by half the engine, is tailoring; and a lesson only on a side branch protects nothing
- **What happened:** a full-match pass count was over a test's limit. Calibration showed forward
  passes rated too low. The passer's estimate raced every opponent while the engine sends one
  chaser, so the estimate was changed to race only the soonest. That made the calibration look
  better and turned the failing seed green. An audit found that the engine lets any opponent take
  the ball by contact and re-plans its chaser every 4 frames. So the change was not the engine's
  rule but an optimistic way of combining uncertainty wherever two opponents contest the ball,
  and where play happens did not move at all. It was reverted on the R3 line (Oct 17), but the
  lesson stayed on that branch. The same change, ported earlier from another branch, rode into
  the forward-play port on main's line (#103) unchecked. There it was a prime suspect when goals
  doubled (2.63 a team over 8 seeds, against 1.4 real).
- **Rule:**
  - Before changing how an estimate combines its parts, read every path in the engine that
    decides the same outcome (here `plan_chase` and `contact`), not only the one that fits.
  - A rate that moves for the wrong reason, or a check that turns green while the behaviour
    behind it does not move, is not a fix.
  - A lesson lands on main as soon as it is learned, in its own small pull request if its fix is
    still on a branch.
  - An audit of a port also reads the source line's LESSONS.
- **Check:**
  - For any change that moves a held-out check, list what else moved (stoppages, where play
    happens) and say what did not.
  - `git log --all -- docs/LESSONS.md` shows no lesson that exists only on an unmerged branch
    older than a day.
  - A port's audit names the branches whose lessons it read.

### 130. A pattern that reads numbers must read every way a number is written
- **What happened:** the fact-checker's number pattern refused a digit followed by a letter, so it
  would not read "h7" as a number. That also skipped every English ordinal: "in the 9th minute"
  passed for an event in minute 2, and "his 97th pass" passed with no such count in the evidence,
  although the clock rule tells the agents to write minutes as ordinals. The minute pattern
  already knew the "9th minute" form; it was never reached. Found by the Personalizer's tests,
  when a planted "7th pass" in a variant aired.
- **Rule:** a check that reads values out of text is tested on every form the writers are told
  to use, and on the forms a translation or rewording produces, with a defect planted in each.
- **Check:** `tests/test_factcheck.py::test_an_ordinal_minute_must_be_the_cited_minute` and
  `test_an_ordinal_count_must_be_in_the_evidence` fail on the old pattern.

## Working in the repo

### 12. "No checks yet" is not "checks passed"
- **What happened:** a pull request was merged before CI had started on its last commit,
  because the wait loop treated an empty check list as finished.
- **Rule:** wait until every required check has reported, then merge.

### 45. Green CI on an old base is not green on main
- **What happened:** #55 changed the seed-7 match and merged at 05:55 UTC. #61 merged three
  minutes later on CI that had run against the main before #55, because branch protection does
  not require a branch to be up to date. Main went red: the recorded slice cited an event id
  (`e00051`) that the new match no longer has.
- **Rule:** if main has moved since a pull request's checks ran, merge main into the branch and
  wait for CI again before merging, even when the files don't overlap. A recording or fixture
  depends on the whole engine, not on the files its pull request touched.
- **Check:** branch protection on `main` requires branches to be up to date (on since
  2026-10-17), so GitHub will not merge until CI has passed on the branch with main merged in.

### 49. A deploy is done when the live URL answers with the new commit
- **What happened:** the first `azd provision` and deploy of the API failed three times, and each
  earlier step said it had passed. A role id written from memory did not exist (`what-if` does not
  check role ids). Leaving the Container Apps environment's mode unset gave an Express
  environment, which cannot run jobs or OpenTelemetry. And an image built by Docker's legacy
  builder on a Mac looked amd64 when inspected locally, but in Azure even `/bin/sh` failed with
  `exec format error`. `azd` reported success every time.
- **Rule:** look up every Azure id (`az role definition list --name ...`); set every mode the
  platform would otherwise default; build images with BuildKit, never the legacy builder. A
  deploy counts as done only when the public URL answers with the commit just deployed.
- **Check:** the deploy workflow's smoke test passes only when `/api/health` reports the commit
  it deployed.

### 50. A merge from main is a code change: test it before pushing
- **What happened:** #80 pinned lighting and weather to day and clear; #70 merged into main
  with tests that pushed `lighting=night` and `weather=rain` under their floors. Merging main
  into #80 had no conflict, and it was pushed after only ruff and one manual run, so two tests
  failed on the pushed head: correct code, tests written for the old knobs.
- **Rule:** after merging main into a branch, run the full `uv run pytest` before pushing. A
  clean merge only means no lines overlapped, not that the two changes agree.
- **Check:** the merge commit's CI is green, and it was green locally before the push.

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
- **Again (Oct 23):** `uv run ruff check . | tail -1 && git commit ... && git push` committed and
  pushed a branch with 2 lint errors: `tail` succeeded, so `&&` went on. Gate on the command itself
  (`uv run ruff check . && ...`), never on a pipe that trims its output.

### 30. Run the commands you document
- **What happened:** the data contract told readers to run `ninety-sim` without `--out`, which
  the CLI requires, so the first command a newcomer copied failed.
- **Rule:** every command in a doc is copied from a run that worked, with all required
  arguments.
- **Check:** paste each documented command into a fresh shell before merging.

### 31. Evidence has to fit in an agent's context
- **What happened:** frame-based stats cited every frame they used, so one 90-minute match
  produced 85 MB of facts (9.3 million source ids), too large for any agent or fact-checker.
- **Rule:** cite frames as a range (`frames:<first>-<last>`); cite events by id; a value of zero
  cites nothing.
- **Check:** a test requires frame-based facts to cite one range, and caps the size of a clip's facts.

### 83. Admin pushes skip the gate
- **What happened:** four commits went straight to main without CI (an admin can bypass branch
  protection). They broke lint, the fmath ban (a `math.atan2` in the engine) and the cue fixture,
  and every open pull request was blocked until a repair landed.
- **Rule:** every change reaches main through a pull request whose CI has passed, admins included.
- **Check:** `git log --first-parent origin/main` shows only pull-request merge commits.

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

### 24. What collides is what is drawn
- **What happened:** the engine's body was a round cylinder 0.52 m across; the renderer drew a
  round trunk 0.32 m across (deeper than a real chest), turned by its own smoothing of the motion
  rather than the engine's heading, and drew a carried ball 0.55 m ahead of where the engine had
  it. Balls bounced off players in empty air, and the
  labels showed contacts that the pixels did not.
- **Rule:** one body shape (`ninety/sim/shape.py`), oriented by the engine's heading (which turns
  at a sourced rate, never in a jump), is used by the contact physics and the renderer; the
  renderer draws the ball where the engine has it. Where drawn and simulated bodies still differ
  (the legs, running arms and lean), say so in GROUNDING rather than claim they match. Measure a
  change's "before" from a clean worktree of the base commit, never from the tree being edited.
- **Check:** `tests/test_body_shape.py` checks cross-sections of the drawn body against the shape
  over its whole area at chest height (nothing outside it, the share it fills as GROUNDING
  states), the clip's gaits take the engine's heading, and `drawn_ball` returns the engine's
  position.

### 25. A new limit breaks every rule that assumed the old instant behaviour
- **What happened:** turning was made to take time, but the strike still fired as soon as the
  ball was on the target's side of the body, which with a slow turn meant striking along the
  chest; passers knocked their own passes off themselves, and deflections doubled. The tests
  read the new constant back, so they could not see it.
- **Rule:** when a change makes something take time (a turn, a reaction), find every rule that
  waited for it and make it wait for the real state, with a sourced threshold. Pin a sourced
  constant with a test that states the source's number (180° in about 0.52 s), not the constant.
- **Check:** before and after, measure the outcomes the change could disturb (here: kick angle
  off the body, self-deflections, deflections, interceptions) on the same seeds.

### 26. A limit on angle is not a limit on distance
- **What happened:** a carried ball was sent round the carrier's body with its turn per frame
  limited, but its distance from him was set straight onto his outline, so a ball a metre away
  jumped up to 1.24 m in one frame, through him. It was under every validator limit, and the
  test started with the ball already on the outline.
- **Rule:** bound what actually moves (the distance per frame), and test from a state that is
  not already the answer.
- **Check:** a test measures per-frame movement from awkward starting places (ahead, beside,
  behind) against the speed limit it claims.

### 27. A contact must not swallow the rest of the frame
- **What happened:** a deflected ball was put back where it met the player and the rest of that
  frame's travel was dropped. A ball he kept failing to control hovered at knee height for
  seconds while its falling speed grew, touched again every frame; the gravity check let it
  through, because a touch excuses the frames around it. Short runs never showed it; a full
  match did (one player "deflected" it 96 times in a row).
- **Rule:** after a contact, spend the rest of the frame: the ball flies on, and whoever it meets
  next in that time is resolved too. Measure on full-length matches, not only short clips.
- **Check:** the longest run of consecutive deflection events by one player over 90 minutes
  (seeds 7, 11, 21, other events between them ignored) is a few, not dozens (1 to 4 measured; base 9 or 10).

### 28. A comment that names a physical rule is a claim to measure
- **What happened:** the keeper's dive said "a shorter dive is the same push, over sooner", but
  the code replayed the full dive's timing sped up, so a 0.5 m dive launched at about 46 m/s²
  against 16 for a full one, and every dive ended by setting him down from full speed in one
  frame. Tests checked where the dive ended, never how hard it pushed, so both passed for months.
- **Rule:** when a comment or GROUNDING row states how a body moves (the same push, braking as
  legs allow), a test measures that quantity frame by frame (speed gained or lost per frame),
  not only where the movement ends.
- **Check:** for any motion profile, a test sweeps its inputs (here, every dive length) and
  bounds the per-frame change in speed; mutate the profile's scaling and the test must fail.

### 29. A reach is a shape in time and height, not a number
- **What happened:** a keeper's reach was 1.45 m of travel plus 1.8 m of arms, at any height up
  to 2.8 m, at every moment of the dive. In an experiment where his dive started at a penalty's
  strike, as keepers' do, he stopped 72% of the kicks he guessed right against about 27% in real
  penalties. The arms'
  1.8 m and the 2.8 m height were also not one body: arms that long would put his standing reach
  above his jumping one.
- **Rule:** a reach is an envelope built from one body (stature, centre of mass, standing reach,
  jump) and the timing of each part of the movement (sideways from the dive, upward only once he
  can see the ball's height), defined once and called by everything that asks where a player can
  touch the ball.
- **Check:** `uv run python -m ninety.sim.penalties`, read beside Bar-Eli et al. 2007 by
  direction and by stop, never fitted to it; a test that a ball at his waist is touched where one
  under the bar at the same moment is not.

### 32. Persisted replay prompts are an interface
- **What happened:** making a rejection reason more specific changed the Analyst retry prompt,
  so an existing recorded slice stopped replaying even though the workflow behavior was valid.
- **Rule:** re-record the replay in the same pull request as any change to text that reaches a
  recorded prompt (fact-checker reasons, agent instructions). Never make the replayer tolerate a
  changed prompt: a shim that rewrites new wording back to old pairs an old answer with a new
  question.
- **Check:** `test_every_committed_replay_still_replays` runs every committed replay (lesson 44).

### 44. A committed recording must be replayed by a test, or it rots silently
- **What happened:** the fact-checker started also reporting "clock 01:00 is not a cited clock",
  which changed the Analyst's retry prompt, and `replays/slice-minute2-plant.json` stopped
  replaying on main. Lesson 32's check was a manual step nobody ran, and
  `tests/test_slice_replay.py` passed because it only built synthetic recordings.
- **Rule:** every file in `replays/` is replayed by a test in CI. When that test fails, re-record
  (lesson 32); never edit the JSON by hand.
- **Check:** `tests/test_slice_replay.py::test_every_committed_replay_still_replays` fails on the
  stale recording and passes on the re-recorded one.

### 80. A replay pins the interface it tests, not the engine underneath
- **What happened:** `replays/slice-minute2-plant.json` held only the models' answers, and the
  replay rebuilt the fact-checker's events from the local engine. Every engine change changed the
  checker's rejection reasons, so the Analyst's retry prompt changed and the replay failed, even
  though no prompt or check had changed. Each break needed a live Foundry re-record from the
  owner's Mac and a manual deploy of the branch's API.
- **Rule:** a recording carries every input it was made against that is not under test (here the
  match events the checker read), and the replay uses those. It still fails on a change to what
  it tests (a prompt, a check's message, a handoff); a changed engine only warns that the
  recording is stale.
- **Check:** `tests/test_slice_replay.py::test_the_committed_replay_survives_an_engine_change`
  plants an engine change and expects the same outcome and a `StaleRecording` warning;
  `test_a_changed_analyst_prompt_still_fails_the_committed_replay` and
  `test_a_changed_fact_check_message_still_fails_the_committed_replay` must still fail the replay.

### 33. One clock for viewers and agents
- **What happened:** agent-facing minute and second values were rounded and combined differently
  from the scorebug's floored elapsed clock, producing off-by-one timestamps and occasional
  second 60 values.
- **Rule:** build the displayed clock in one shared function, and keep football's ordinal minute
  as a separate field.
- **Check:** compare every compact event's clock and seconds with the scorebug clock at its event
  timestamp, including fractional seconds near a minute boundary.

### 34. An evaluation's true labels must be true, and must not be quoted in the prompt
- **What happened:** the fact-checker evaluation put "cautious" on every completed pass,
  including one of 42 m at 96 km/h, and labelled the claim true; the Judge rejecting it was
  counted as an error. The tone words being tested were also listed in the Judge's own
  instructions, so a good score partly measured the quote.
- **Rule:** attach a descriptive word only to events whose fields fit it, with the condition
  written before reading any model output; test generalisation on words the prompt never uses.
- **Check:** `tests/test_judge.py` fails if an evaluated tone word appears in the instructions,
  or a tone claim is built on an event outside its condition.

### 35. A graphic's words must follow the outcome, not just its numbers
- **What happened:** the first template graphics wrote "h10 finds h6" for every pass with a
  receiver, including the 10 failed passes in seed 7's first five minutes. The fact-checker's
  code half passed them, because it checks numbers and player ids, not verbs. The Ledger also
  dropped any fact source id it could not find, so a fact citing a missing event would have been
  stored with less evidence instead of failing.
- **Rule:** a word that states a result ("finds", "scores", "blocked") comes from the event's
  `outcome` field. A citation that does not resolve is an error, never filtered out.
- **Check:** `tests/test_cues.py::test_failed_pass_never_says_it_found_the_receiver` and
  `tests/test_ledger.py::test_load_match_refuses_a_fact_citing_a_missing_event` fail on the
  original code.

### 36. A test's numbers come from the constants it tests
- **What happened:** merging `main` into the engine branches, `main`'s high-ball tests used 6 and
  12 m/s because they sat either side of `main`'s first-touch limits (8 + 8 × skill). The engine
  branches had moved those limits to 12 + 12 × skill, so the same numbers now tested nothing: a
  "poor" chest killed the ball. Both branches had also numbered new lessons 18 to 23.
- **Rule:** a test that checks a threshold derives its inputs from the constant (`FOOT_ABSORB_MPS`,
  `firsttouch.CUSHION`), so a change to the constant moves the test with it. A new lesson takes the next
  number on `main` at merge time.
- **Check:** `tests/test_engine_rules.py` high-ball tests build their speeds from the profile
  constants; `grep '^### ' docs/LESSONS.md` shows no number twice.

### 37. A check narrowed in a merge needs its cause measured
- **What happened:** merging `main` turned the camera test red: 75% of frames had the ball in
  shot against a 97% bar. The failing frames were a dead ball lying 4 m beyond the touchline for
  the sourced restart time. `main` never hit this because its restarts took 1 to 2 s. The test was
  narrowed to the ball on the pitch. The independent audit then swapped the halves and found the
  cause: `main`'s camera, which never aims nearer a touchline than 12 m, not the engine.
- **Rule:** before narrowing a check, find which side of the merge causes the failure (swap the
  halves) and write the measurement next to the narrowed check. Keep the threshold.
- **Check:** `tests/test_render_camera.py` states the measured in-shot counts, both on the pitch and
  off it.

### 38. A scorer has to know every event the engine can emit
- **What happened:** after the merge, `main`'s event scorer judged a goal against the ball on the
  centre spot, because the goal's own frame already shows the kickoff. It also judged a foul against
  the ball, where the engine places it at the fouled player. Neither case had come up on `main`: no
  goal in its five-minute test windows, and no fouls at all.
- **Rule:** when the engine gains an event kind, or changes where it places one, the scorer's
  reference for it is set in the same pull request. A goal is read from the frame before its own,
  as the renderer reads it.
- **Check:** `tests/test_event_score.py::test_each_event_spot_is_at_its_reference_object` runs over
  windows that contain a goal and a foul (seed 11).

### 39. Run the reports after a reconcile, not only the tests
- **What happened:** reconciling the engine branches combined #31's body outline with the
  penalty code from `engine/passes`. The penalty taker walked onto the mark itself. The strike rule
  exempted a ball at his centre ("in his hands") and the kick was taken at once, so a quarter of
  penalties came straight off his own body. On-target fell from 90% to 65%. No test covered it.
  The penalty report showed it only when the save rates were re-measured, after two audits.
- **Rule:** after merging engine branches, rerun the reports (`ninety.sim.penalties`,
  `ninety.sim.funnel`) and compare them with the parents before calling the merge done. A behaviour
  the report shows breaking gets a test.
- **Check:** `tests/test_penalties.py::test_a_penalty_never_comes_off_the_man_who_took_it`.

### 42. One field, one meaning: who a pass was for is not who got it
- **What happened:** a pass event's `receiver` meant the team-mate who got a completed pass and,
  on a failed one, the opponent who cut it out. The cue template read it as the target, so 12 of
  the 15 failed-pass cues in the seed-7 fixture said things like "a2 looks for h8", h8 being the
  home player who intercepted it. Lesson 23's checks passed: the verb followed the outcome, the
  name did not.
- **Rule:** a pass records each person in their own field: `intended` (whom the passer chose),
  `receiver` (the team-mate who got it, completed passes only), `interceptor` (the opponent who won
  a failed one) and `deflected_by` (an opponent who only touched it, which says nothing about where
  it went next). Never reuse a field for a different role depending on the outcome. A word that
  states a role ("finds", "cut out by") reads the field for that role, in the cue and in the
  fact-checker.
- **Check:** the validator's C4 fails a pass whose receiver or intended is an opponent, whose
  interceptor or deflector is a team-mate, or whose receiver is set on a failed pass;
  `tests/test_cues.py::test_no_cue_in_the_fixture_names_an_opponent_as_a_pass_target` fails on
  the old fixture; `tests/test_factcheck.py::test_a_pass_finds_only_its_receiver` fails without
  the fact-checker's role check.

### 43. A report another program reads must be strict JSON
- **What happened:** the event scoring harness used infinity for "the detected time is past the
  last frame, so the place cannot be right". That is correct inside the matching, but it was also
  written into the report, and Python's `json.dumps` writes it as `Infinity`, which JavaScript's
  `JSON.parse` and most other parsers reject. The report format even documented it, so the
  agents (R4) could have failed on one late detection.
- **Rule:** a value that only steers a computation stays inside it; what is written out is plain
  JSON, with `null` plus a named flag (here `outside_frames`) for a case that has no number.
  Files are written with `allow_nan=False`, so a stray infinity or NaN fails at the source.
- **Check:** `tests/test_event_score.py::test_a_time_outside_the_clip_still_gives_strict_json`
  fails on the original code.

### 47. A test's premise holds by construction, not by a seed's draw
- **What happened:** porting the portable math onto the engine branch changed `gauss`, so every
  drawn player changed. `test_a_dribbler_whose_touch_is_declined_still_decides` assumed h6 in
  `Engine(1)` "could not run onto" a push from standing. That was true only of the old draw of him
  (acceleration 0.41, dribbling 0.30); the new one (0.51, 0.24) can, so the touch was taken and the
  test failed on behaviour it was never about.
- **Rule:** the situation a test is about is set directly (a stubbed method, a set attribute), never
  left to what a seed happens to draw. A test that means to cover a draw says so and checks it.
- **Check:** the test sets `e.touch_speed` to decline; it still fails when a declined touch skips
  the decision (mutation run on the merge of `main`'s portable math).

### 69. A rule two places use lives in one place
- **What happened:** when the engine began taking a high ball on the thigh, chest or head, at half
  a foot's pace (A4), the passer's estimate kept judging every reception by the foot. Passers
  thought lofted passes were safer than the engine made them, for every pass since. Nothing failed:
  each half was tested on its own.
- **Rule:** a rule that both the engine and a player's estimate apply (the first touch, the kick
  error, the reach) is one function in one module that both call. Never two copies kept in step by
  hand.
- **Check:** `grep` the rule's constants: they appear in one module and its tests, nowhere else;
  a test feeds the same case to the engine's function and to the estimate.

### 51. A band is only as good as the sources that make it
- **What happened:** R7's published band, 20 to 45%, was cited to one Premier League study, which
  reports about 20%; the 35 to 45% came from a second study that was not cited. The same row still
  showed a 62% late drop measured on an engine two rebuilds old, and the late drop that did exist
  came from a design constant, not from players pacing themselves.
- **Rule:** each end of a band names the source it comes from. A realism number is judged by a
  protocol written before it is measured (matches, seeds, statistic, spread, band), and the row
  records the engine commit the number came from.
- **Check:** `uv run python -m ninety.sim.late_drop` prints the commit in `docs/eval/late-drop.md`;
  `tests/test_late_drop.py` fails if the seeds or band drift from `docs/EVALUATION.md`.

### 70. What is labelled as drawn must be the shape that is drawn
- **What happened:** `body_parts` labels each part a capsule, `parts_box` bounds it as one and
  the body-shape tests measure it as one, but `web/render` drew each part as a lathe that closed
  to a point at both joints. Between the top of the trunk and the base of the neck nothing was
  drawn, so a player cut by the bottom of the frame at that height was a floating head with a box
  ending at his chin (seed 900002 at `443c4d5`). The render check caught it only because his foot
  happened to fall outside that box, and every Python test passed because none of them looked at
  the drawn pixels.
- **Rule:** the renderer draws the shape the labels and tests describe, and a test checks the
  drawn pixels, not the Python model of them. The same goes for any summary number: the player
  height percentiles counted boxes cut by the image edge as players, so a 19 px "player" was 19 px
  of one.
- **Check:** `tests/test_render_body.py` slides the bottom image edge from a player's shins to his
  chin and fails if his drawn box ever stops short of it; `tests/test_render_checks.py` checks
  that the height percentiles skip boxes cut by an edge.

### 71. Select hard cases by their cause, not by something that travels with it
- **What happened:** `occlusion=crowded` chose the clip window with the most players within 4 m
  of the ball. A crowd on the far side of the ball hides nothing, so crowded clips reached only
  4.0% mostly hidden balls in render run v1, and no number of them could lift the training set
  to the 5% floor. The proposed fix was to render more of them.
- **Rule:** a knob that targets a hard case selects on the geometry that makes it hard (here, a
  player on the line from the camera to the ball). Before rendering a round, measure the knob's
  own rate on two or three clips: a mix can never beat its best part.
- **Check:** `tests/test_render_scene.py::test_the_crowded_window_is_the_one_where_the_ball_is_hidden`
  builds two windows where counting players near the ball picks the wrong one. Before a batch,
  `uv run ninety-data-stats <2-3 crowded clips> --stride 5 --input 640x640` shows the share.

### 75. A trigger guarded only by "not busy now" fires again when the busy state ends
- **What happened:** a keeper's dive was allowed whenever he was not diving and not on the
  ground. A slow shot was still on its way after he had dived, landed and got up, so he dived a
  second time at the same ball. Every condition checked the present; none remembered that the
  touch had already set off a dive.
- **Rule:** an action that happens once per cause records the cause it answered (here the touch,
  `kicked_at`) and checks it, rather than relying on a temporary state to block a repeat.
- **Check:** for each once-per-cause action, write a test where the cause outlives the action's
  own busy state (dive, land, get up, ball still coming) and require no repeat; and one where a
  new cause (a deflection) is allowed to trigger it again.

### 76. Keep every dimension a source measured
- **What happened:** the kick-error source measured a tilted ellipse of where shots cross the goal
  line (a long and a short axis). The engine kept one number, their geometric mean (3°), as the
  sideways error, and gave the up-and-down error a fixed 2° that did not grow with speed, pressure
  or fatigue. Close shots almost never missed: none of 25 unblocked shots inside 25 m in one sample.
- **Rule:** when a source reports a shape (axes, a covariance, a distribution), derive each
  component the engine uses from it, in code, with the derivation beside it. A number that
  summarises a measurement is not the measurement.
- **Check:** for each sourced constant, ask "what did the source actually measure, in how many
  dimensions?" and test the derived values against the source's own figures.

### 77. A committed report must come from the committed code
- **What happened:** two commits regenerated `docs/eval/funnel.md` (1.8 goals a team), yet the
  code of the later one, re-run on a clean checkout of that commit, produced 2.5; the realism test went red with nobody noticing. Twelve
  matches also hide a change of 0.3 goals a team in noise (standard error about 0.27).
- **Rule:** regenerate a report from the exact tree being committed, after the last code change,
  and state how big a difference the sample can resolve.
- **Check:** re-run the report on a clean checkout of the commit and compare before merging.

### 78. A test's sample must survive a change that does not touch what it tests
- **What happened:** merging the measured kick error, which changes only where a struck ball
  goes, broke two tests that check something else. A styles test read the defensive line over
  three minutes of one seed: the gap between a high press and a low block fell from 7.8 m to
  5.0 m, against a 5 m margin, while over ten minutes it was 15.7 m and 12.7 m. A fact-checker
  test needed some player to be absent from every event in a five-minute clip; after the change
  all 22 took part, so it had nobody to plant.
- **Rule:** a test that reads a match measures enough of it that an unrelated change cannot move
  the result across its margin, and a test that needs a case builds that case itself rather than
  waiting for the match to produce it. Lengthen the sample or build the case; never move the
  margin.
- **Check:** before trusting a match-reading test, run its measurement on a longer window and a
  second engine version, and write both numbers next to it.

### 81. Read a model's class ids from a trained model, by what the boxes look like
- **What happened:** to map RF-DETR's class ids to player and ball, `detect.py` was checked
  against a checkpoint trained for one epoch on 10 images. Its ids (1 and 2) were taken to mean
  player and ball, but that model's output was noise. A trained model returns indices into
  `class_names`: 0 player, 1 ball. So the merged mapping labelled every ball a player and
  dropped every player. A validation check on ours-v2 caught it before any number was
  published: one clip scored 0 true positives, 48 ball-sized "players" and 2,007 misses.
- **Rule:** decide what each class id means with a trained model, from the boxes it draws (size,
  shape, how many a frame), never from a smoke run's id counts. Then pin that measurement in a
  test, with the numbers in its comment.
- **Check:** `tests/test_vision_finetune.py::test_our_checkpoint_maps_by_index_into_class_names`
  records the ours-v2 measurement (id 0: 32 x 71 px, about 6 a frame; id 1: 9 x 9 px, one a
  frame). Before scoring a new checkpoint, run `detect.py` on one validation clip and score it.
  Precision near zero with ball-sized boxes labelled player means the mapping is wrong.

### 84. Everything the picture draws in front of an object hides it in the labels
- **What happened:** the id pass, which counts each object's visible pixels, hid all scenery. In
  seed 900003 of the frozen test set (`engine-v1`) a dead ball rested 0.5 m behind the far
  advertising boards for 110 frames. The picture showed only boards, and the labels said
  visibility 1.0. Every render check passed, because each one compared the labels with the id
  pass, not with the picture. The detector found it by missing a ball that the picture does not
  show.
- **Rule:** anything opaque that the beauty pass draws is an occluder in the full id pass, unless
  it is listed as an exception with a reason (sky, ground, see-through nets, shadow decals). Before
  re-rendering, measure the scope over every split, not only the frames a model missed.
- **Check:** `tests/test_render_occlusion.py` puts a ball 0.5 m behind the far boards and fails if
  any of it is labelled visible (52 pixels on the old id pass). A ball in front of the boards must
  stay visible.

### 85. A scorer reads labels by the rule written down, not by which fields are filled
- **What happened:** EVALUATION.md says boxes with visibility zero are not labels, but
  `vision_score.ground_truth()` kept any label with a box. When the re-frozen test set marked
  balls behind the advertising boards as visibility 0 and kept their boxes, the scorer counted
  113 balls in shot and fully hidden as misses, and ball recall read 0.846 instead of 0.930. It was found after
  the results were in; the rule it applies was written before them.
- **Rule:** a scorer decides what counts as a label from the documented rule, in one function,
  and never from whether a field happens to be present. A data change that fills a field it once
  left empty must not change what is scored.
- **Check:** `tests/test_vision_score.py::test_a_box_with_visibility_zero_is_not_a_label` gives
  a player and a ball boxes at visibility 0 with no detection and fails if either counts as a miss.

### 86. Measure the worker count; a CI runner's threads are not cores
- **What happened:** the test jobs took 15 to 40 minutes, so every merge left the other ready
  pull requests another half hour behind. `pytest -n auto` started 4 workers on GitHub's 4-vCPU
  runner, which has 2 physical cores, and the job took 22 minutes, against 13 with `-n 2` and 41
  in one process (measured on the same tree, 2026-10-18). Full-match simulations also slow each
  other down: `test_judge`'s two simulations took 498 s alone on a runner and 978 s next to the
  90-minute realism test. Split over three runners per Python version, the jobs took 12 and 13
  minutes against 29 and 30 in one process (main at `1f0b74c`), and the slowest shard is the one
  with `test_judge`, which simulates 120 match minutes in one test.
- **Rule:** choose the worker count from a measured run on the real runner, not from `auto`.
  Spread the slowest tests over separate machines (`--shard`, `tests/conftest.py`), and keep the
  required check names as a gate that is green only when every shard passed. Every pull request
  still runs every test.
- **Check:** `tests/test_shard.py` fails if a test lands in no part or two, if the `--shard`
  hook drops or repeats a test across K, or if the slowest tests share a part. Each shard prints
  its 10 slowest tests; when one shard runs much longer than the others, update `SLOWEST` in
  `tests/conftest.py`.

### 87. Re-rendering part of a run copies the run's settings, and is checked against it
- **What happened:** to fix 30 v3 clips I launched the re-render with seed ranges only. v3 had
  rendered its 2000s and 4000s with `occlusion=crowded` and its 3000s with `kit_contrast=low`, so
  16 of the 30 came back with different parameters, and 5 of them filmed a different window.
  Nothing failed: the job rendered exactly what it was asked for.
- **Rule:** a partial re-render takes each seed's overrides from the original run's `clip.json`,
  and before the new clips replace the old, their `params` and `overrides` must equal the
  originals and their engine positions must match frame for frame.
- **Check:** `docs/eval/dataset-v1.json` lists the run, commit and overrides of every clip; for
  each replaced seed, compare `params` and `overrides` in both `clip.json` files.

### 88. A ported rule keeps its condition, not just its threshold
- **What happened:** porting `main`'s aerial touches, the engine flagged every touch in foot reach
  above 0.45 m as a thigh or chest, at half a foot's first touch. `main` applied that only to a ball
  coming into the body; the engine's foot reaches to 1 m. A knee-high pass met beside a player was
  miscontrolled and popped up beside him to be miscontrolled again: before the cushioned touch, 158
  deflections in 30 minutes of seed 7, 52 by the same player straight after his own, against 35
  before the port, and about 80 fewer passes a team per match over 24 matches. The cushioned touch
  then copied the same height-only test into the shared first-touch rule; there it made such a ball
  a heavy touch. The first fix also let the passer's estimate judge "into his body" from where the
  receiver stood, but receivers run onto the ball's path: passers then over-rated dropping balls
  and receivers kept fewer of them (89.5% against 94.2% on the base, seeds 40 to 47). The estimate
  keeps the thigh for a dropping ball, as a cautious bound, and the calibration report (forced
  passes) checks that it under-estimates rather than fits.
- **Rule:** when porting a rule between engines, carry over every condition it was guarded by (here,
  "into his body"), and check it against the receiving engine's own definitions (here, foot reach).
- **Check:** after a port, compare event counts by kind (deflections, passes) with the parent on the
  same seed, and rerun the touch report: an estimate made more optimistic shows there before it shows
  in goals. `tests/test_engine_rules.py::test_a_ball_he_reaches_beside_him_below_his_foot_reach_is_a_foot_touch`
  fails with the height-only test restored;
  `tests/test_decisions.py::test_the_passer_expects_a_dropping_ball_into_his_man_to_meet_the_thigh`
  fails if the estimate takes it on the foot.

### 89. A rate that swings match to match needs enough matches before it is read
- **What happened:** the touch report's eight seeds put the engine at 1.0 goals a team after "what
  makes a touch worse", and the pull request, GROUNDING A4 and EVALUATION recorded it as a held-out
  miss against the published 1.4. A match's goals run from 0 to 8, so eight matches cannot measure
  goals a team to better than about ±0.3. Over 24 seeds the same engine gave 1.44, and the change
  against the engine before it was -0.25 ± 0.18: noise.
- **Rule:** before calling a per-match rate (goals, penalties, cards) a hit or a miss against a
  published figure, give its standard error and use enough matches that the error is smaller than
  the gap being claimed; compare two engines on the same seeds. A rate measured on too few matches is
  reported with its error, never as a hit or a miss.
- **Check:** every goals-per-team figure in GROUNDING and EVALUATION says how many matches it is
  over; a before-and-after claim on goals gives the paired difference and its standard error.

### 90. The same seed does not pair two engines
- **What happened:** #90 was measured against main on seeds 40 to 47 and the per-seed differences
  gave -1.0 goals a team with a "paired" standard error of 0.34, reported as likely real. But any
  engine change makes the two matches part within about a minute (seed 7's events differ from
  73 s on), so a seed's two matches are independent draws, not a pair. Over 24 seeds the
  difference was -0.44 with a standard error of 0.28, and the paired and unpaired errors agreed
  (0.276 and 0.279).
- **Rule:** treat two engines on the same seeds as independent samples. Give the unpaired
  standard error, and use enough matches that it is smaller than the gap being claimed. Running
  the same seeds still matters, for reproducing a run, not for cancelling noise.
- **Check:** for a before-and-after on a match rate, report both errors; if the paired one is not
  clearly smaller, quote the unpaired one. On the agent side too, one seed is one match only if one
  engine made it. The deployed match tools serve the matches the deployed image simulated, so in
  an evaluation graded against this commit's simulation every agent gets the minute's events
  inline, under a match id no server serves, and an agent that calls the tools anyway fails the
  call. A prompt alone does not enforce it: the tools are called inside Foundry. The live
  ablation's one-agent arm once read the tools and aired a goal on seed 33 that had no shot here.
  `tests/test_agent_ablation.py::test_both_arms_read_the_match_the_grader_grades`,
  `::test_a_live_arm_that_calls_the_match_tools_fails_that_call` and
  `tests/test_workflow.py::test_an_agent_given_its_events_inline_that_calls_the_match_tools_fails_its_call`.

### 91. When the data moves, the code that reads it moves in the same change
- **What happened:** sealing the ground truth (0fda1f8) moved frames.jsonl and events.jsonl from
  the `renders` container to `truth`. The training fetcher still read frames.jsonl from `renders`,
  so a fetch of any later run would have downloaded images with no labels, and coco_export would
  have stopped on the first clip. Separately, dataset v1 picks each clip's run and drops seed 111,
  but the fetcher took whole runs, and the pinned validation seeds still named 111. Both were found
  by reading the dataset definition against the tools before renting a GPU, not on the GPU.
- **Rule:** a change to where data lives lists every reader of it and updates them, or names the
  ones left behind. Before a paid training run, dry-run the launcher against the exact dataset
  definition it will train on.
- **Check:** `tests/test_vision_fetch_clips.py` takes labels from `truth` and each seed from the run
  the list names; `tests/test_vision_finetune.py` checks the short fine-tune's validation seeds are
  all in `docs/eval/dataset-v1.json`.

### 92. A count is not a cause: look at where the errors land before naming one
- **What happened:** two explanations were passed on before anyone checked them. "The detector
  fires on 45 of 113 fully hidden balls" was read as the model seeing balls behind the boards,
  learned from the boards defect in its training labels. Checking where those detections were
  showed none on the hidden ball (median 43 px away), 39 at a player's feet, 44 in one clip.
  "Crowded scenes are the weakness (0.72 recall on validation)" was scored before #119, when
  fully hidden objects counted as misses, which crowded windows have most of. On the test set the
  crowded clips score within a few points of the others.
- **Rule:** before a number becomes a finding or a plan, check what it counts: where the errors
  sit, and which scorer and labels produced it. A cause is named only after looking at the
  errors themselves; a number from before a scorer or label fix is re-measured or marked as such.
- **Check:** `docs/eval/vision-report-v1.json` reports `hidden_ball_frames.on_the_hidden_ball`
  and the median distance, not just the count, and `by_knob` gives the crowded clips on the test
  set; `tests/test_vision_report.py` checks a detection at a player's feet is not counted as
  on the hidden ball.

### 93. A dependency that needs a rule change merges after the rule
- **What happened:** #63 added rfdetr and PyTorch, which bring in tqdm (MPL-2.0), pillow
  (MIT-CMU), FFmpeg inside `av` (LGPL) and NVIDIA CUDA (proprietary). The licence rule in
  `AGENTS.md` still said "MIT, Apache-2.0 or BSD only", and #68, which widened it, sat in draft.
  #63 merged anyway, so `main` broke its own written rule for a day. An audit of all 179 locked
  packages then found licences the rule never named (Zlib, BSL-1.0, CC0-1.0, CNRI-Python) and GPL
  runtimes bundled inside numpy, scipy and matplotlib wheels.
- **Rule:** a PR that adds a dependency outside the written rule waits for the rule change to
  merge first. Every locked package is listed with its licence in `THIRD_PARTY_NOTICES.md`.
- **Check:** `tests/test_third_party_notices.py` fails when a locked package (name and version) is
  missing from the notices, or when its licence is not one the rule allows. It was mutation-checked:
  removing a row and relabelling a package GPL each make it fail.

### 94. Copy an identity string from the system, not from the docs
- **What happened:** the `agents-live` setup told the maintainer to trust the OIDC subject
  `repo:KLKH7/the-ninety-labs:environment:agents-live`, the format GitHub's docs show. This repo's
  tokens carry the owner and repo ids (`repo:KLKH7@210092633/the-ninety-labs@1417939631:...`),
  as the existing `main` credential already showed. The credential was created, `az` reported
  success, and no run could ever have signed in with it.
- **Rule:** an identifier another system must match exactly (an OIDC subject, a role id, a
  resource id) is read from that system or copied from a working sibling, never written from
  memory or a generic doc (as lesson 49). Setup steps say how to see the value in use.
- **Check:** `az ad app federated-credential list --id "$CLIENT_ID" --query "[].subject"` shows
  every subject with the same prefix; the setup is done only when the first approved
  `agents-live` run passes `azure/login`.

### 95. A mutation run that turns nothing red may not have run the tests
- **What happened:** a shell loop mutated nine lines of the M1 live path and reported "none red"
  for every one. zsh does not split an unquoted `$T` into words, so pytest got one path that did
  not exist and ran no test. Nine "surviving" mutations in a row looked like nine weak tests.
- **Rule:** a mutation harness prints the test run's own pass and fail counts next to each
  mutation, and a run with no "passed" count is a broken harness, not a surviving mutation.
- **Check:** the harness line for every mutation shows "N failed, M passed". Run one mutation by
  hand first and watch it go red before trusting the loop.

### 96. A fallback is real only when a test injects the failure through the live path
- **What happened:** the M1 live path had fail-closed Judge handling and a single status mapping
  (`contracts.status_for`), and both looked done. Injecting each failure through `live.run` for
  the failure table showed two gaps: the workflow kept its own mapping, so a Judge outage ended
  as `rejected` (the claim is wrong) instead of `held` (it could not be checked); and an Analyst
  that failed, hung on an MCP call or replied with prose raised out of `live.run`, taking the
  template graphics down with it.
- **Rule:** every fallback claimed in a failure table (docs/eval/failure-table-m1.md, and the
  multi-agent workflow's docs/eval/failure-table.md) is a row produced by injecting
  that failure into the real path, asserted by a test with the expected outcome written in the
  test. A status is computed by `status_for`, never re-derived.
- **Check:** `uv run pytest tests/test_failure_table.py`; removing the `live.run` fallback or
  restoring the old status line turns a row red.

### 97. A robust loss pulls only from as far as its scale reaches
- **What happened:** the camera search (`ninety/vision/pitch.py`) ranked its coarse grid of views
  with the fine fit's Cauchy loss, 3 px. A grid view sits tens of pixels from the right one, where
  that loss is flat, so the ranking was close to noise: with the true gantry held fixed, 3 of 10
  frames of seed 900001 fitted, and the gantry search settled 20 m from the truth. The objective
  was not at fault: the true camera scored 3.8 against the search's 24. The grid also aimed only at
  points on the pitch, while the broadcast camera looks beyond the far touchline.
- **Rule:** before blaming an objective, score it at the answer. A coarse-to-fine search uses at
  each stage a loss scale that matches how far its starts are from the answer (here 20 px to rank,
  then 12 and 3 px to refine), and its grid covers the whole space the answer can be in.
- **Check:** `tests/test_vision_pitch.py` recovers known cameras from their own markings, at four
  pans including a midfield view the old grid could not reach.

### 98. Cluster on what does not change with the light
- **What happened:** teams came from 2-means on each track's shirt colour. In seed 900001 the stand's
  shadow covers half the pitch, and the two clusters learned were two greys (#292c3f and #666374)
  for a maroon and a blue kit: players were split by light, both away passes were labelled home,
  and every pass matched its true event in time and place but not in team.
- **Rule:** make a feature that tells objects apart invariant to what varies within one of them
  before clustering it (here chromaticity, each channel over their sum, which shadow leaves
  alone), and check the clusters against labels on one clip before trusting them.
- **Check:** `tests/test_vision_events.py::test_one_kit_in_sun_and_in_shadow_is_one_side` fails
  when the feature is raw colour.

### 99. A scorer reads a clip the way the data contract writes it
- **What happened:** `ninety/eval/event_score.py` found a frame by its position from 0, which holds
  for a whole match. The test set's clips are windows that keep the match's frame numbers
  (docs/DATA_CONTRACT.md), so the first detected events graded on one were refused.
- **Rule:** a scorer takes its inputs' layout from the contract (here, a window starts at its own
  first frame) and is tested on that layout, not only on whole matches.
- **Check:** `tests/test_event_score.py::test_a_window_cut_from_a_match_is_graded_by_frame_number`
  and `::test_a_window_with_a_missing_frame_is_refused` fail on the old code.

### 100. A file the code reads at run time must be in the image, and CI must build the image
- **What happened:** #128 made `ninety/match/detected.py` read `schemas/match_event.schema.json` at
  import and the MCP server load `tests/fixtures/detected-standin-seed900001.jsonl`. The Dockerfile
  never copied `schemas/`, and `.dockerignore` drops `tests/`. Every test passed, because tests run
  from a checkout; the first place the image was built was the deploy after merge, which failed, and
  `main` could no longer deploy.
- **Rule:** a change that makes the code read a file outside `ninety/` at run time adds it to the
  Dockerfile in the same pull request. The image is built and called in CI on every pull request,
  not first at deploy.
- **Check:** the CI `image` job builds the Dockerfile, runs it, and calls `/api/health` and an MCP
  tool on every kind of served match; the Dockerfile itself loads every served match after the
  precompute. Mutation-checked: removing `COPY schemas` fails the build at the precompute step.

### 101. A drawn body moves the way its markers move, frame by frame
- **What happened:** the skinned mesh was turned as one rigid object by the engine's heading. A
  player turning on the spot spun on his base, both feet sweeping 5 cm a frame across the grass;
  a strike was a stored pose wherever the ball was, its foot about 0.5 m off it. Running plants
  were placed up to 0.58 m ahead of the hips, where the mesh's leg cannot put a flat foot (it
  reaches 0.30 m), so the drawn foot landed short and slid onto its plant. The test of that
  ("the planted foot does not skate") passed only because the leg search was coarse enough that
  the foot missed by about the same amount on both frames it compared.
- **Rule:** judge motion on the skinned markers the page draws, over consecutive frames: a foot
  on the grass does not move, and a moving foot is lifted; a touch puts the named part on the
  ball on the contact frame. Place targets where the drawn limb can reach (measure the reach on
  the asset), and make a search fine enough that a test cannot pass by its error.
- **Check:** `tests/test_render_motion.py` (turns on the spot, run touchdowns, kicks, thigh, chest
  and header touches), each mutation-checked against the old behaviour; `tests/test_render_mesh.py`
  holds the page's markers to the Python ones for the same poses.

### 102. A change to the picture bumps the renderer version in the same commit
- **What happened:** the skinned kit mesh (a3d228e) replaced the capsule players and left
  `RENDERER_VERSION` at 0.3.2. Dataset v1's clips at `cca498c` (capsules) and every clip rendered
  from main since (mesh) both record renderer 0.3.2, so `clip.json` cannot say which body a
  detector was trained or tested on. Found while planning targeted round 1, which renders from
  main and would have mixed the two looks under one version.
- **Rule:** any change to what `web/render` draws or how labels are counted bumps
  `ninety/render/__init__.py`'s `RENDERER_VERSION` in the same commit; a dataset or test-set
  manifest names the version, and two looks never share one.
- **Check:** `git log -p -- web/render ninety/render/scene.py ninety/render/meshpose.py` since the
  last bump shows no picture change without a version change; a dataset manifest's `renderers`
  lists one version per look.

### 104. "Never imported" is only tested in a fresh interpreter
- **What happened:** a test meant to prove the default `ninety-e2e` run never loads the Azure
  Speech client deleted it from `sys.modules` and ran the bundle. With the import moved to the top
  of the Describer, it stayed green: the module was already loaded when the test file was, so
  nothing imported it again. The mutation run caught it.
- **Rule:** a test that a module stays unloaded imports the code under test in a new Python
  process and reads `sys.modules` there.
- **Check:** `tests/test_describe.py::test_the_default_run_makes_no_azure_call`; mutate by adding
  the import at module top and watch it go red.

### 106. Look for an open pull request on the same task before building it
- **What happened:** a session was handed "build the Personalizer over A2A" and built it, tests and
  mutation run included, before it noticed that draft #131 was the same task, further along. Two
  Personalizers with different packages, interfaces and fallback rules were then one merge away.
  The overlap showed up only when another PR's challenge map named #131.
- **Rule:** before writing code for a task, search the open pull requests and the session notes for
  it (`gh pr list --search "<task words>"`, the notes folder). If one exists, extend it with a PR
  stacked on its branch, or ask the Coordinator. Never build a second one.
- **Check:** the PR description names the search run and what it found. This PR is stacked on #131
  (base `agents/personalizer`) and adds only what #131 lacks.

### 107. Outcome numbers can look right while the football looks dumb: watch clips and count the nonsense
- **What happened:** goals, shots, saves and pass completion sat inside their published bands
  for weeks, so the engine was judged good. When the owner finally watched review clips, the play
  was poor across the board: passes into touch with nobody near the passer, a chaser running away
  from a loose ball, teams passing among themselves inside their own box, defenders standing
  still. Every engine change had been measured by outcome rates; nobody watched a clip, and
  nothing counted the play itself. On engine `7ee8720` the football-sense checker found 202 passes
  a 90 from a team's own box into its own box, and the team without the ball with eight or more
  outfield players standing for almost a quarter of open play.
- **Rule:** an outcome rate is a held-out check, not proof the football is sensible. Every engine
  pull request posts a watched 60-second clip and the football-sense counts (FS1 to FS9) on seeds
  7, 11, 21 and 42 at 20 minutes, before and after; a fix names the type it targets and shows that
  count fall without another rising. When someone watching finds a new kind of nonsense, it
  becomes a defect type with a must-fail scene before it is fixed.
- **Check:** the pull request has a clip link and the `ninety-football-sense` table for both
  commits ([EVALUATION.md](EVALUATION.md#football-sense-fs1-to-fs9)).

### 103. An argmin over a flat or bimodal objective is a coin toss between its ends
- **What happened:** the keeper set his depth as the one, of 1 to 6 m, that left the least of the
  goal open. Against a central ball he stood 6 m off his line at 8 and 10 m, 1 m at 12 m, 6 m at
  18 m and 1 m at 20 m; from 14 m wide and 8 m out he stood 10.7 m off the goal's centre, outside
  his post. The objective was sampled at a few shot speeds and heights, so it zigzagged between
  neighbouring depths; integrated finely it was still bimodal, with the two ends nearly equal and
  the middle worst, because nothing in it made coming out costly. The argmin picked whichever end
  won by a hair, and a metre's change in the ball flipped it. The rule's own source (keepers come
  off their line on 3.4% of shots, close in) had been read as support for a set position.
- **Rule:** before trusting an optimised choice, plot the objective over the whole range at the
  situations that matter; if it is flat, jagged or has several minima, the choice is not a model of
  behaviour. Use a smooth rule (marked *design*) until the missing cost is modelled, and read the
  source's own numbers before citing it for a direction.
- **Check:** a test that the choice is monotonic and has no jump over the range it is used on, and
  one for the geometry it must respect (here within the posts):
  `tests/test_decisions.py::test_the_keeper_sets_himself_deeper_the_further_the_ball_and_smoothly`
  and `::test_the_keeper_never_sets_himself_outside_his_posts`.

### 105. A mutation run against a red baseline catches everything
- **What happened:** the mutation harness for the window stats ran with `-x` over two test files
  while an existing test (`test_passes_a_minute_and_the_window_edges`) was already failing after
  the merge. Every mutation reported "caught", including one that no test guarded (allowing a
  stat's event count as a claim number); the same failure was catching them all.
- **Rule:** run the suite the harness uses, unmutated, and see it green before the first
  mutation; a mutation counts as caught only if a test that passes on the baseline fails on it.
- **Check:** the harness's first line is the baseline run's "N passed, 0 failed"; with lesson 95,
  each mutation line names the test that went red.

### 108. Money is computed exactly and rounded half up
- **What happened:** the latency-cost report summed prices as floats. The per-clip upper bound is
  exactly $0.00535, and Python 3.12's `sum()` of floats is compensated while 3.11's is not, so the
  total fell either side of the half: the report rendered $0.0054 on 3.12 and $0.0053 on 3.11, and
  CI failed on 3.11 only.
- **Rule:** money is computed exactly (`Decimal` from the quoted price strings, or integer
  micro-dollars) and rounded half up when shown. A float total on a half boundary renders
  differently across Python versions and sum orders.
- **Check:** `uv run pytest tests/test_latency_cost.py -k half_boundary`; its case of 13,327 input
  and 12 output tokens fails on float arithmetic.

### 109. A defect seen by eye is a lead until the data and the grounding confirm it
- **What happened:** in the defect sweep (`docs/eval/defect-sweep-7ee8720.md`) 30 reviewers
  watched top-down sheets of 300 match minutes. The two most reported types were wrong:
  - "Long dead-ball waits" (70 per 90 minutes): the waits match GROUNDING R1.
  - "Bunching around the ball": the data shows 6-7 players within 15 m, never the 13-14
    reported. The sheets' 2.3 m dots made players 2-3 m apart look like one crowd.
  The owner had reported bunching from watching clips too. A ranking by raw report counts would
  have put both above the stalemate that is the real worst defect.
- **Rule:** a visual review produces candidates. Before a type ranks work, a second reviewer
  measures examples in `frames.jsonl` against `docs/GROUNDING.md`. The catalogue shows each
  type's verdicts, and refuted types are listed as refuted, not dropped silently.
- **Check:** every row of the sweep's ranked table has a "verified" entry, and the "What did not
  hold up" section names each refuted type with the numbers that refuted it.

### 110. A workflow's queue is part of what it does: read how the platform queues it
- **What happened:** `agents-live.yml` put every run in one concurrency group, `agents-live`, with
  `cancel-in-progress: false`, read as "runs wait their turn". GitHub keeps at most one pending
  run per group, and a newer dispatch cancels the pending one whatever that setting says. Runs
  from four sessions' branches each waited for approval, and each was cancelled by the next
  session's dispatch. They showed only as `cancelled`, and the approver approved only the one
  still alive.
- **Rule:** a concurrency group is chosen for what must never run at the same time (here one
  branch's runs), not for the whole workflow, and a setting's meaning is read in the platform's
  documentation, not inferred from its name. A cancelled run nobody cancelled is a defect to trace.
- **Check:** `.github/workflows/agents-live.yml` groups by `inputs.ref`. Dispatch from two
  branches before approving either: both stay `waiting`.

### 111. A shape measured only from the ball collapses onto it; instrument a choice before blaming its value
- **What happened:** every in-possession spot was metres behind the ball, floored 12 m from goal.
  With the ball 20 m out, both centre-backs, both full-backs and the holding midfielder shared that
  floor inside the box, and the team passed around there: 224 own-box passes a 90 (seeds 7, 11, 21,
  42). The investigation also named the pass value as a separate cause (forward passes never win).
  Logging every choice showed otherwise: forward options in the own third were 30 m long with a
  0.68 completion estimate against 16 m and 0.99 for square ones, because the shape left nobody at
  a reachable forward distance. Bounding the team's length by R8 instead cut own-box passes to 33,
  own-box camping (FS9) from 70 to 0 and the square-pass count (FS7) from 488 to 224 a 90, with no
  change to how passes are valued.
- **Rule:** a positional rule relative to a moving point needs a bound from the team's own measured
  shape (length, width), not a floor that every role shares. Before changing how an option is
  valued, log the options at each choice and see which term loses it; fix the upstream cause first
  and re-measure.
- **Check:** `tests/test_shape.py::test_the_team_is_never_longer_than_the_published_range_and_the_back_line_never_ahead_of_the_ball`
  sweeps ball and line positions; on the old rule it fails (48 m long with the ball 35 m out).

### 112. Every kick the decision layer aims is judged by the same Laws as a pass
- **What happened:** the pass estimate counted a ball leaving the pitch (Law 9), but the clearance,
  added separately, was aimed at one fixed spot 4 m from the touchline with no such check. With the
  passer's own kick error, about a third of clearances went straight out with nobody near.
- **Rule:** an option that sends the ball somewhere is valued over the strikes the kicker's error
  allows, with the pass estimate's own pieces (`decisions.clear_value` reuses `strike_nodes`,
  `flight`, `out_of_play`, `reach_time` and the P16 turn); where it simplifies them (a hard race, no
  body in the way), the row says so (GROUNDING D9). A new kind of kick does not get its own physics.
- **Check:** `tests/test_decisions.py::test_an_unpressed_clearance_is_not_aimed_where_his_kick_error_puts_it_out`.

### 113. A test over a folder says which files are its own
- **What happened:** two tests read every file in `replays/` as a slice recording (`*.json`):
  the committed-replay test and the byte-for-byte round trip. Both passed while the folder held
  only slice files. The first workflow recording (format 1) turned them red with "format 1 slice
  recording", though nothing was wrong with either file.
- **Rule:** a test that loops over a folder selects the files of its own kind by name
  (`slice-*.json`, `workflow-*.json`), and fails when the folder holds a file no kind claims, so a
  new file is never skipped in silence.
- **Check:** `tests/test_replay.py::test_every_committed_recording_round_trips_byte_for_byte`
  fails with an unclaimed file in `replays/`, and fails when a workflow recording no longer saves
  byte for byte.

### 120. An exemption in a check is where a defect hides: reach the state, do not place it
- **What happened:** the engine placed a new ball at the taker's feet at every restart and reset
  all 22 players at every goal. The validator exempts dead-ball windows from the ball-speed check
  and kickoff frames from the player-speed check, so nothing failed. The ball jumped more than
  3 m in one frame about 70 times per 90 minutes (median 7.5 m), and every goal reset the pitch
  in one frame. Viewers saw it; no test did.
- **Rule:** a state the match needs (the ball on the restart spot, the teams in kick-off shape)
  is reached by the engine's own movement: players go there and fetch the ball, within their
  bodies and the ball's physics (lesson 5). An exemption in a check is allowed only for a real
  discontinuity in the broadcast (a cut) and is listed as a known gap until the engine no longer
  needs it.
- **Check:** `uv run pytest tests/test_restarts.py` records every frame from before the stop to
  the kick, including the frame the restart is given, and fails on a ball or player step faster
  than the validator's limits. `scripts/defect_sweep/restarts.py` counts ball jumps over 3 m per
  90 minutes (0 over 16 matches of 20 minutes, `docs/eval/restarts.md`).

### 121. A Law is all of its clauses: read the whole restart, not the part the defect named
- **What happened:** the restart fix enforced the distances and "in play when kicked and clearly
  moves", and took any movement of the set ball as the kick. The taker could then carry the set
  ball off and pass it, touching it twice before anyone else (55 of 340 restarts). The owner saw it
  in a clip as "he passed to himself". The same Laws (8, 13 to 17) say the taker may not touch it
  again until another player has; that clause was never implemented, so no test asked for it.
- **Rule:** when implementing a Law, list every clause of it in the GROUNDING row and give each a
  test, including the clauses no defect report mentioned.
- **Check:** `uv run pytest tests/test_restarts.py -k "dribble or first_touch or again"`; on the
  engine before the fix the set ball's first movement is not a pass or shot by the taker.

### 122. A rule every kind of case shares is tested on every kind, run to the end
- **What happened:** moving the restart taker a ball's width behind the ball was tested on a
  free kick only. At a corner the readiness check still measured from the corner point, the taker
  stood 1.09 m from it, and the corner was never taken: 7 of 16 measured matches froze for the
  rest of their 20 minutes. Every unit test passed; only the 16-match measurement showed it.
- **Rule:** a change to a rule that every restart (or every kind of any case) goes through gets a
  test that runs each kind to completion. A measurement counts stuck states as a defect, not as
  quiet time.
- **Check:** `uv run pytest tests/test_restarts.py -k every_kind`; `scripts/defect_sweep/restarts.py`
  reports `stuck_restarts`, which must be 0.

### 123. An async client handed a sync credential signs in late and blocks the loop
- **What happened:** the slice, the fact-checker evaluation and the Analyst evaluation each made
  a sync `DefaultAzureCredential` and passed it to Foundry's async clients, and
  `foundry.chat_client` made one by default. A sync credential fetches its token on the event
  loop's thread, stalling every concurrent call. It fetches it only at the first model call,
  after the evaluation has simulated its matches, by which time agents-live's five-minute OIDC
  sign-in can have expired. The fact-checker evaluation lost 19 of 251 Judge calls, most likely to
  this (not yet confirmed by a rerun). The workflow
  (W1) had already fixed this for itself; the rest never took the fix.
- **Rule:** every live run makes one aio credential (`credentials.new_credential`), signs in
  (`credentials.sign_in`) before anything slow, and passes that object to the chat client and
  every agent. A client factory takes no default credential.
- **Check:** `tests/test_credentials.py`. Each site takes the token before it simulates, and
  hands the same `SignedIn` credential to every client; deleting any `sign_in` turns its test
  red. An AST check keeps `azure.identity.DefaultAzureCredential` out of the live modules.
### 124. Judge a drawn motion over the frames around the moment, and watch the clip
- **What happened:** #146 made the foot reach the ball on the contact frame and its tests measured
  exactly that, so they passed while the kick lost its swing: the foot was eased in from at most
  0.4 m behind the ball, and a pass looked like a player standing still with the ball between his
  feet. A lunge dropped the hips 0.24 m and snapped them back in two frames. Since the skinned
  mesh (a3d228e) every stored pose bent both elbows about 80 degrees, so the forearms were held out
  in front whatever the player did; and since Oct 15 the boards behind the goals had their print
  flipped and read mirrored. No test looked at any of it; the owner found all four by watching
  review clips. Measuring every limb frame by frame then found a fifth, in every run since #146: the
  stride planted each foot a quarter of a cycle away from where the gait has it on the grass, so on
  about one player-frame in five a foot jumped 0.3 to 1 m at a landing or lift-off.
- **Rule:** a change to how a body moves is tested over the frames around the event, not only on
  it: the swing before, the follow-through after, the rest pose's joints, and how far anything
  moves in one frame. Every printed surface has a test that it reads left to right from each camera
  that sees its print. A before/after clip goes on the pull request and someone watches it before
  merge.
- **Check:** `tests/test_render_motion.py` (arms hang and swing, the kick's backswing and
  follow-through, the lunge's pace, the keeper's hands on the ball) and
  `tests/test_render_stadium.py` each fail on `e50440c` and pass with the fix, and so do
  `test_setting_off_running_and_pulling_up_moves_no_limb_in_a_jump` and the tackle test, which cap
  how far any limb moves relative to the body in one frame.

### 125. A check that fails on a few frames names a class of defect: sweep every frame for it
- **What happened:** render-check failed `player_feet_in_boxes` at 0.4.2 on 2 foot checks each of
  seeds 7 and 11. The 0.4.3 fix traced those four frames to three causes and tested each, and the
  re-render of seed 7 failed 7 checks in two other sequences: a pass cushioned with one foot and
  struck with the other on the move left the first foot's plant where it stood before the touch,
  2 m behind by the strike, and the mesh hung both feet in the air. Fixing that sequence (0.4.4)
  left 1 failure. A sweep of every player-frame of both clips then found 21 frames with both mesh
  feet above 0.2 m and the body not jumping, in four players and two more causes: a touch that had
  faded before the next one still let its foot go from the old plant, and a foot the touch caught
  mid-stride came down over a whole slow step. The frames were instances; the class was a foot
  the body has left behind.
- **Rule:** when a picture check fails on a few frames, name the class of defect, measure it over
  every player-frame of the clips in Python (no render needed: the mesh's markers come from
  `meshpose`), and fix every sequence that shows it before re-rendering.
- **Check:** `test_a_first_touch_then_a_strike_on_the_move_keeps_a_foot_on_the_grass` (both
  cases) and `test_a_thigh_touch_on_the_move_keeps_a_foot_on_the_grass` fail on `0312d60` and
  pass; removing any one of the three parts of the fix fails one of them or the tackle's limb cap.
  The sweep at 0.4.5: 0 such player-frames on seeds 7 and 11 (worst 0.18 m), from 21.

### 126. A legal exception in the contract is an exception in every reader of the same data
- **What happened:** after a goal the kickoff puts every player back in his own half in one frame.
  The data contract allows it, and the validator's speed check and the late-drop report both skip
  it. The stats engine did not: `player_movement_facts` counted the reset as running, so seed 7's
  h7 had a 4,739 km/h peak speed and 52 m of extra distance in the Ledger's facts. No test failed,
  because the movement tests were built by hand and never contained a kickoff. It came to light
  when the phone companion first showed the number.
- **Rule:** when the contract makes an exception (a kickoff reset, a dead ball being replaced),
  every computation over the same frames applies it in the same place, and one shared function
  (`stats.player_steps`) decides which steps count as movement.
- **Check:** `tests/test_stats.py::test_a_kickoff_reset_is_not_movement` puts a reset into a
  kickoff frame (legal under the contract) and fails on the old code;
  `test_no_player_outruns_the_contract_over_a_restart_after_a_goal` runs the engine's own restart
  partway through a match and holds every player's peak speed under the validator's limit. (The
  engine teleported players at a kickoff until #156; they now walk back, so the engine case is the
  walk, and the reset is pinned by the hand-built frames.)

### 127. A test that waits for its rule hangs when the rule breaks, and a hang is not a red test
- **What happened:** two WebSocket tests on the phone relay checked their rule by waiting for a
  message (a close, the room's latest state). With the rule mutated, the message never came and
  pytest blocked for about 40 minutes, until the process was killed by hand. A CI job would have waited
  out its timeout rather than failing on the test that names the rule.
  The same tests then hung CI's full run with the rule intact: Starlette's TestClient gives each
  WebSocket its own thread and event loop, so the laptop's relay wrote into another thread's
  socket, and under load a message was lost. uvicorn never does that; but the same tests, moved
  onto one loop, showed a real bug: a laptop message relayed while a joining phone was still
  being sent the latest state could overtake it, leaving the phone on a stale clock.
- **Rule:** a test that waits for a message sends a sentinel the broken code would deliver first,
  or tests the rule directly, so a broken rule fails the test at once. Every receive has a
  deadline. Concurrency is tested the way the server runs it (one event loop for every
  connection), never through a harness that adds threads the server does not have.
- **Check:** each mutation of the relay (`ninety/api/companion.py`) fails with pytest's own
  counts within seconds, never times out. `tests/test_api_companion.py` drives the relay on one
  loop with a 5 s deadline per receive, and 150 repeats on 4 workers under full CPU load pass;
  `test_a_newer_clock_never_overtakes_a_phones_catch_up` fails without the single flusher.

### 128. A refusal a browser cannot read is no refusal: close a WebSocket after accepting it
- **What happened:** the phone relay refused a join (unknown code, room full, laptop taken) by
  closing the WebSocket before accepting it, and its tests read the close codes 4404, 4409 and 4429
  from an ASGI harness. A browser never sees a close sent before the handshake completes: uvicorn
  answers it with a 403 and the page reads 1006, so the phone could not say "unknown code" or
  "room full". W6 found it by running the phone in a real browser (#162).
- **Rule:** a WebSocket refusal the client must act on is sent after `accept()`, with its code; a
  refusal takes no slot, so accepting first changes nothing else. A test of a refusal checks that
  the accept came first, not only the code.
- **Check:** `tests/test_api_companion.py`'s `refused()` fails when the server closes before the
  accept, and every refusal test goes through it; moving `_refuse` back to a bare close turns them red.

### 129. A number check that reads one written form lets every other form through
- **What happened:** the fact-check read a number only when no letter followed it, to skip ids
  like "e00042". So "50km/h", "50kph" and "9999m" were never read, nor was "fifty km/h": a model
  following an injected instruction could air a number the evidence does not hold. The phone
  companion made that reachable from a viewer's text, and its evaluation missed it because the
  scripted attacker wrote only the spaced form and the leak count used the check's own pattern.
  The reviewer's audit found it on #145.
  The first fix then summed any run of number words, so "a one-two" read as 3 and "a one-on-one"
  as a count of 1, and true commentary from every agent was rejected (the reviewer again).
- **Rule:** a check on what a writer says reads every form a writer can produce: a unit glued on
  or spaced, digits or words. It reads words only as English writes one number, and an idiom
  ("one-two", "one-touch", "no one") is no number. An evaluation of that check plants each form
  and counts leaks with its own reader, never the check's pattern, and a change to the reader is
  measured for false rejections too (lesson 11).
- **Check:** `tests/test_factcheck.py::test_a_planted_number_in_any_written_form_is_rejected`
  plants each form; `docs/eval/companion.md` plants the glued and spelled forms, and on the old
  check its count shows 4 of them airing on seed 7.
  `test_football_idioms_are_words_not_counts` passes each idiom with its passes cited. Measured
  for false rejections: the 412 recorded claim texts in `replays/`, `docs/eval/` and the fixtures
  read the same numbers as before, and `fact_checker_proof --check` and both replays pass.

### 131. An evaluation that measured an outage must not publish a number
- **What happened:** the first live Personalizer evaluation reported "0 of 160 variants air"
  and a p95 of 11.6 s against a 3 s budget. Neither described the Personalizer. The run simulated
  matches for twenty minutes before its first model call, and by then GitHub's five-minute sign-in
  had expired, so every call failed and every profile got the verified text. The fallback worked;
  the report still looked like a result. The 11.6 s came from the sync Azure credential, which
  runs `az` on the event loop and so stalls the client's own deadline in the same process; in the
  deployed server it would stall every other request too.
- **Rule:** an evaluation of a model counts the requests the model never answered apart from the
  ones the checks rejected, and writes no report when it answered none. A live caller signs in
  before its slow work, and async code uses the async credential (`azure.identity.aio`).
- **Check:** `tests/test_personalizer.py::test_a_run_in_which_the_model_never_answered_writes_no_report`,
  `test_the_evaluation_signs_in_before_it_simulates_the_claims` and
  `test_published_ask_signs_in_with_the_async_credential_before_anything_else` each fail when
  their rule is removed.

### 132. A WebSocket tested only through the test client is untested in the server a browser reaches
- **What happened:** the phone relay's tests all passed through Starlette's TestClient, which
  speaks WebSocket in process. The first time a real browser joined through uvicorn, every
  connection answered 404: uvicorn upgrades a WebSocket only when a WebSocket library is
  installed, and none was locked, so the deployed image could never have served the relay. The
  same run found lesson 128's unreadable refusals.
- **Rule:** a feature a browser uses over the network is tested once through the real server and a
  real browser, not only through an in-process client. (A close code the client must read is sent after the accept: lesson 128.)
- **Check:** `tests/test_phone.py` runs the companion routes in uvicorn and joins from Chromium;
  CI's `image` job asks the built image for a WebSocket upgrade and needs `101` (it answers 404
  without `websockets` in `uv.lock`). The phone still reads a close before the accept as "unknown
  code or unreachable" (`web/phone/src/feed.ts`), for a server that refuses that way.

### 133. Positions from a fit, summed frame to frame, read the fit's jitter as running
- **What happened:** the phone's speed and distance come from the companion's window facts, which
  sum each player's frame-to-frame steps. On simulator positions that is exact. On positions
  tracked from the video, the camera fit moves a foot point by up to about 0.5 m between
  neighbouring frames, more than a sprinter covers in one (0.34 m). Every tracked player's top
  speed read 53 to 89 km/h, and a player standing still read 16 km/h. The numbers would have
  passed the fact-checker, because they were the cited facts.
- **Rule:** before a stat computed for exact positions reads measured ones, grade it against the
  ground truth on the measured data (offline), and smooth at the stat's own time scale if the
  noise demands it. Choose the width from the stat's definition, not from the error it gives.
- **Check:** `docs/eval/companion-tracked.md` grades speed now, top speed and distance with and
  without the smoothing (top speed 55.6 against 1.9 km/h median error).
  `tests/test_tracked_frames.py::test_smoothing_turns_jitter_back_into_standing_and_keeps_running`
  fails with the smoothing removed, and
  `test_a_track_ends_at_the_speed_its_player_was_running` fails with a plain average, which lags
  at a track's end.

### 134. `sum()` of floats is not the same number on every Python
- **What happened:** the phone's tracked frames file is committed, and a test rebuilds it and needs
  the same bytes. It passed on Python 3.12 and failed on 3.11. Python 3.12 made `sum()` of floats
  use compensated addition, so a smoothed position's last digit moved, and a rounding at 0.01 m
  went the other way.
- **Rule:** code whose output is committed and compared byte for byte adds floats with
  `math.fsum` (one exact rounding, the same everywhere), or rounds well away from the noise.
  This is lesson 46's rule for the engine, applied to every committed output.
- **Check:** CI's pytest matrix runs 3.11 and 3.12. `tests/test_tracked_frames.py` rebuilds
  `tests/fixtures/tracked-seed900001.json` on both; with `sum` in `tracked_frames.smooth` it
  fails on 3.11.

### 135. Noise in a belief is a misjudgement that persists, not a fresh draw every look
- **What happened:** the team chose its chaser for a loose ball from each player's estimate of where
  the ball was going, with an error redrawn every four frames. Two players about as near swapped the
  chase back and forth; the one dropped went back to his shape and turned away from the ball, a fan
  sees a player run away from a loose ball (FS1). The flicker came from the redraw, not from anything
  either player saw.
- **Rule:** a perception error is held for as long as what is perceived has not changed (here, one
  strike or touch of the ball) and shrinks with what he sees (distance), so a decision built on it
  changes only when the situation does.
- **Check:** `tests/test_engine_rules.py::test_a_chaser_is_not_swapped_by_a_fresh_guess_while_nothing_changes`
  fails when the misjudgement is redrawn on every plan.

### 136. One match's goals are a draw: check a rare outcome over many matches
- **What happened:** CI's full-match test bounded one match's goals at 1 to 6. The chaser's pull
  request (#160) failed it: seed 11 ended 0-0 with 27 shots and 1,116 passes, where main's engine
  had won the same seed 3-0, and two engines on the same seed are not a pair (lesson 90). Over 20
  matches of 20 minutes it scored 1.46 goals a team per 90 against main's 1.91 (difference -0.45,
  standard error 0.68), and on the base before main 1.57 against 1.12 (+0.45, 0.60): no settled
  difference either way. A match's goals are close to Poisson around 2.8 (GROUNDING R4), so an
  engine that scores like the real league failed that bound about one change in twelve, and one
  scoring half as often still passed it three times in four.
- **Rule:** a test bounds one match's count only where a realistic engine is almost never outside
  it (passes, tackles, pressures, counted in tens or hundreds). A rare outcome (goals, penalties,
  cards) is checked over many matches against the range a real sample of that many matches shows,
  computed from the source's figures and the outcome's distribution before any engine number is
  read. When those matches cost too much for every pull request, the check runs on demand, on the
  same matches as the report that measures the outcome, and the pull request that changes the
  engine posts its result.
- **Check:** for each per-match bound in `tests/`, work out how often a league at the source's
  figure falls outside it; above 1%, it moves to a many-match check. Goals:
  `NINETY_HELD_OUT=1 uv run pytest tests/test_sim.py -k twelve` runs the funnel's 12 matches (R4);
  `tests/test_funnel.py` pins the range and its arithmetic in every CI run.

### 137. A random choice scaled by the spread of all options loosens when a bad option is added
- **What happened:** the carrier's softmax took its randomness as a share of the spread of all his
  options' values, so a choice between close options would be loose and one between clearly
  different options would not. The spread included the hopeless options (a 50 m pass into a crowd, a
  shot from 44 m), so every bad option widened it and made the choice between the good ones looser.
  Choices logged on seeds 7 and 21 showed him taking his best option in about a third of decisions,
  against the rule's own "a good decision-maker almost always takes the best option".
- **Rule:** in a choice rule, the odds between two options depend only on those two and on the
  chooser; a scale for the randomness is fixed in the options' own units, never taken from the set
  of options on offer. A habit is a pull in units of that randomness, not a bonus in the options'
  units, or changing the scale turns it into a command. A choice asked again before anything new is
  seen is the same choice: hold the random draw, or repeated asking makes a rejected option certain.
  Check a stated intent ("almost always the best") against logged choices.
- **Check:** `tests/test_decisions.py::test_a_hopeless_option_does_not_loosen_the_choice_between_two_good_ones`.

### 138. A range named as a distance is measured as one
- **What happened:** the shot option was offered "inside 40 m of the goal" (`SHOT_RANGE_M`'s own
  comment), but the code compared only the distance along the pitch. From out wide, players were
  offered and took shots 40 to 50 m from goal, judged by a rate table that is only an unsourced tail
  beyond 40 m: 22 of 156 shots in 20 matches (seeds 3 to 112 at 20 minutes) came from beyond 40.5 m,
  none after the fix.
- **Rule:** a threshold is applied in the quantity its comment and its source use (here the distance
  to the goal's centre, as D3's rates are). Search for every use of a constant when its meaning is fixed.
- **Check:** `tests/test_decisions.py::test_a_shot_is_an_option_only_within_range_of_the_goal_straight_line`.

### 139. Knowing where the ball is going is only useful if you go there
- **What happened:** O8 said the team-mate a pass is played to "knows where it was meant", and the
  engine used that only to set his shape: he took up his slot around the target, not the target, and
  a short pass struck slightly off often ran past him into touch. The chase, which takes over once he
  reacts, was planned on the ball's predicted path past the touchline, on points up to 20 m off the
  pitch, while `ball_destination` stopped the same path at the line. The first fix cut the true path,
  but each player then adds his own misjudgement of it, so his judged points could still fall past
  the line: an audit found the test passing on only 91 of 100 seeds.
- **Rule:** when a rule gives a player knowledge, check what he does with it in the movement code, not
  only in the estimate. A limit on what a player can do (Law 9 here) is applied to the path as he
  judges it, where he makes the choice, and tested over many seeds, not one.
- **Check:** `tests/test_engine_rules.py::test_the_team_mate_a_pass_is_played_to_goes_to_meet_it` and
  `::test_nobody_is_sent_to_chase_a_ball_beyond_the_touchline`.

### 146. A detector that starts naming players turns its false events into false evidence
- **What happened:** detected passes began to name their passer and receiver by track (`h-t12`) so
  the agents could talk about them. Scoring the names against the truth found both of seed 900004's
  false passes were one player in two tracks: the tracker lost a dribbler for a frame and picked him
  up as a new track, so his own touch read as "h-t6 finds h-t12". The fact-checker cannot catch that:
  the claim matches its evidence, and the evidence is wrong. Matched events alone would have shown
  every name right.
- **Rule:** when a detected event gains a field the agents will repeat (a name, a team, an outcome),
  grade that field on the false events too, and leave it null, or the event out, wherever the
  footage cannot tell. A pass between two tracks never seen together, the second starting within
  reach of where the first ended, is not recorded. That rule's form was found on a test clip, and
  its distance first came from one: both were then decided on validation clips only, with the
  plan committed first (docs/eval/attribution-plan.md). A constant read off a test clip is tuned to it.
- **Check:** `docs/eval/attribution.md` lists every unmatched detected event with the players its
  names really are; `tests/test_vision_events.py::test_a_dribbler_the_tracker_loses_and_picks_up_again_is_not_a_pass_to_himself`
  fails without the rule.

### 147. A budget is set from the call it bounds, measured; and a cancelled request is awaited
- **What happened:** the live Personalizer evaluation (run 39429424313, at 0689342) answered none of
  its 20 requests: all 160 variants were "fallback: timeout" at 3002 to 3274 ms. The 3 s budget was a
  design share of the 8 s target, never measured against the call. Locally, the published
  `ninety-personalizer:1` on gpt-4.1-mini took 3.2 to 4.7 s (median 4.0 s) for one claim's 8
  variants, over A2A as well as direct. Two more defects hid behind it. First, the server's model
  deadline equalled the client's budget, so the client always gave up first and the server's
  fallback, with its reasons, never got back. Second, the client cancelled a request at the deadline
  and never awaited it. In process, that cancellation ran on into a2a-sdk 1.2.3's server code, which
  swallows it (`ActiveTask.subscribe` catches CancelledError) and waits forever for a task a
  message-only agent never creates. Those tasks were destroyed when the loop closed, and that
  produced the "Task was destroyed but it is pending" and OpenTelemetry "created in a different
  Context" errors at exit. Those errors came after every request, so they did not block a response.
- **Rule:** a latency budget cites a measurement of the call it bounds, and a test holds it above
  the slowest measured call. A layer's own deadline ends inside its caller's
  (`SERVER_MARGIN_S`), so the inner fallback answers rather than the outer timeout. A task cancelled
  at a deadline is kept and awaited before the client closes. An in-process server runs each request
  in its own task (`server.InProcess`), as uvicorn does, so a client's cancellation never enters the
  server.
- **Check:** `tests/test_personalizer.py::test_the_budget_is_over_the_slowest_measured_model_call`,
  `::test_a_slow_model_is_answered_by_the_server_with_its_reasons_not_cut_off_by_the_client`,
  `::test_a_request_cut_off_at_the_deadline_is_awaited_on_close` and
  `::test_the_evaluation_leaves_no_request_running_when_the_client_gives_up`.

### 148. A trust test that checks what the fit minimised trusts a wrong fit
- **What happened:** the camera fit minimises how far the image's white marking pixels lie from
  the projected pitch lines, and a frame was trusted when half of them lay within 1.5 px. A fit
  that settles on the wrong camera also lines its markings up, so the test passed it. On
  validation it trusted 198 frames whose ground was more than 1 m wrong: seed 109's by about
  125 m, all of seed 108's by about 2 m. It also rejected 11% of good frames.
- **Rule:** judge a fit by something it did not optimise. A consequence it must get right is
  enough, here that players come out the height people are. Measure the test against the truth
  on validation clips before trusting it.
- **Check:** `tests/test_vision_observe.py` (players made too tall or too short by the camera are
  not trusted, whatever the markings say); `docs/eval/detector-derive.md` (each gate's bad frames
  trusted and good frames kept).

### 149. A rule that counts errors cannot see how large they are, and a detector built on its only clip is tuned to it
- **What happened:** the M1 event detector was built while test seed 900001 was its only clip, so
  its published numbers were partly tuned to the test set. Re-deriving it on validation clips, the
  new camera trust test was chosen by a rule fixed in advance: the most bad frames rejected,
  keeping 90% of good ones. It won on counts (175 bad frames trusted against 198). But it trusts a
  few frames on clips the old test rejected entirely, some 47 to 80 m wrong, where the
  alternative's worst was 6.6 m. On the test set it trusts 1 and 7 such frames on the two clips
  with camera cuts.
- **Rule:** a detector is developed on validation clips from the start, and the test set is scored
  once, at the end. A rule that adopts a gate or a threshold also bounds the size of the errors it
  lets through (the worst, or a high percentile), not only their number, stated before choosing.
- **Since, on validation:** a neighbour check added afterwards (docs/eval/camera-bound-plan.md,
  lesson 159) brings the worst trusted frame there to 8.2 m (observed), under 8.5 m set before
  measuring. It is not a bound (lesson 159), and on the test set 4 frames about 46 m wrong are still
  trusted.
- **Check:** `docs/eval/detector-plan.md` (the plan, its amendment and the outcome, in commit
  order); `docs/eval/detector-derive.md`, "Worst trusted" for each gate;
  `tests/test_vision_observe.py::test_a_frame_whose_camera_disagrees_with_its_neighbours_is_not_trusted`.
### 140. A clip's truth must not depend on how long the match was simulated
- **What happened:** `ninety-render` simulated the match to the end of the window it chose (240 s
  plus the clip), but its own determinism check re-rendered the same window with `--start`, which
  simulated only to the window's end plus a second. The engine settles some outcomes after the fact
  (a tackle is won or lost when someone next controls the ball), so a tackle near the end of crowded
  seed 11's window was `fail` in the clip and `null` in its re-render: frames and images identical,
  `events.jsonl` not. Found while adding the broadcast's dead-ball cuts, which make a clip span more
  of the match than its length.
- **Rule:** the simulation's horizon is fixed by the latest frame a clip could need, never by how
  its start was found: `max(latest start, start) + length + SIM_MARGIN_S` (`ninety/render/clip.py`),
  long enough for the outcomes and the dead balls after it.
- **Check:** `ninety-render-check --determinism` on a window with a tackle near its end compares
  `events_identical`; `tests/test_render_clip.py` renders the same seed twice.

### 141. A camera rule is judged by what the viewer sees over whole matches, not by the shot that prompted it
- **What happened:** the gantry was aimed 4.5 m above the play after a review found the stand a
  thin lip under the sky, and second angles were added one at a time (high behind the goal when
  the ball is in a box, the far stand when play is on the far side, a low angle for a shot
  arriving). Each fixed the shot it was made for. Nobody measured the whole broadcast: the stands
  filled 40 to 75% of the picture with the players small at the bottom (the pitch over 60% of the
  picture with the ball central in 13 to 47% of live frames on seeds 7, 21 and 42), and with second
  angles on the viewpoint changed 8.8 times a minute, with shots as short as 0.6 s, between
  opposite sides of the ground. The owner found both by watching clips.
- **Rule:** a change to how the camera is pointed is measured over whole simulated matches before
  and after it: the share of live frames that are well framed, the shots per minute against
  broadcast practice (SoccerNet-v2: one change every 9 s) and the shortest shot, and how fast the
  pan gathers speed. The numbers go in the pull request.
- **Check:** `tests/test_render_camera.py` measures all three on seeds the design was not tuned on
  (`test_the_gantry_frames_the_play_with_the_pitch_filling_the_picture`,
  `test_the_viewpoint_changes_no_faster_than_a_broadcast_and_never_flickers`,
  `test_a_pan_eases_in_and_out`); each fails on the 0.5.0 director.

### 142. A figure keeps the case it was measured for
- **What happened:** GROUNDING R1 cited Opta's guide to time-wasting for "a goal's celebration,
  about 72 s", and the restart work planned the kick-off after every goal around it. Read again,
  the article gives 72 s for the celebration after a penalty goal, in its paragraph on penalties;
  it gives no figure for goals in general. A general figure was then found in a different source
  (FIFA's referees' chief: a celebration "may last one, one and a half minutes").
- **Rule:** when a number moves from a source into GROUNDING, the row names the case it was
  measured for (which restart, which competition, which seasons) and quotes the sentence it
  comes from; a number used for a wider case needs a source for that case.
- **Check:** every row of GROUNDING that cites a time or a rate names its case; R1 and L4 now cite
  the penalty figure as a penalty figure and the goal figure from its own source.

### 143. Players sent to one point end up inside each other: give each his own place
- **What happened:** the goal celebration sent every team-mate to the scorer's own position. Steering
  bends a run round another player but does not slow it, and bodies in contact brace only with the
  grip steering leaves, so ten players arriving at one point at a sprint ended up in each other: in
  32 to 63% of celebration frames two bodies overlapped by more than 5 cm. The tests counted players
  within 3 m of the scorer, a distance between centres, and passed.
- **Rule:** when several players head for the same spot (a huddle, a wall, a queue), each gets a
  place of his own, at least a shoulder's breadth from the next (P11), chosen so that no two runs
  to them cross. A test of a crowd measures the clearance between bodies (`shape.between`), not
  the distance between centres.
- **Check:** `uv run pytest tests/test_restarts.py -k "overlap or side_they_come_from or once_a_frame"`;
  with every team-mate sent to the scorer's centre the overlap test fails (none ever stands at a
  place of his own), and with places worked out one player at a time, in the order they move, the
  once-a-frame test fails. `scripts/defect_sweep/huddle.py` counts the frames with bodies in each
  other over a whole celebration (`docs/eval/restarts.md`, "The huddle").

### 150. Build a media branch from an empty tree, and look at what it holds before pushing
- **What happened:** review clips for the camera pull request went on a new orphan branch made by
  `git checkout --orphan`, which keeps the whole working tree staged. The `git rm` meant to empty
  it refused, but the shell line went on past it (`;` after `&&`), so the push carried a copy of
  every tracked file with the media. It was public code, with no secrets and no untracked files,
  and the branch was rebuilt within minutes; the clips themselves were left out, ignored by the
  copied `.gitignore`.
- **Rule:** start a media branch empty (`git switch --orphan`, or `git rm -rf --cached .`), add the
  files by name (`git add -f` when `.gitignore` covers them), and list the commit's tree before
  pushing. A multi-step shell line that changes a repository stops at its first failure.
- **Check:** `git ls-tree -r --name-only origin/pr-assets/<name>` lists only the media.

### 151. A new check of what a model writes starts from the reader we already have
- **What happened:** the Vision Auditor's rationale check (#140) read numbers as digit runs only,
  written fresh beside the fact-checker's reader, which lesson 129 had already widened to number
  words and glued units. "Ninety of these were missed", "sixty percent", "one in three" and "-38"
  all passed a check the docs called "number-checked". The reviewer's audit found it.
- **Rule:** a check on what a model may write reuses the fact-checker's reader
  (`factcheck.spelled_as_digits`) and adds only what its own text needs (here: digits glued to
  words, a sign, thousands commas, and refusing words for a share or a multiple). Its tests plant
  every written form, and a true number in each form must still stand.
- **Check:** `tests/test_vision_auditor.py::test_a_planted_number_in_any_written_form_is_refused`
  and `::test_the_cluster_s_own_numbers_in_any_form_stand`.

### 152. A handoff checked only by its writer is not a contract
- **What happened:** the Auditor validated its own `clusters.json` against the schema, but the Data
  agent read the file without checking it. A hand-edited file with test seed 900001 in its sources,
  a shifted seed range or another render setting was planned as if typed. Removing the writer's
  check turned no test red, because the writer never produces a bad file. Two writers also made two
  shapes under one file name: the committed round-1 file failed the new schema with 83 errors.
- **Rule:** the agent that acts on a handoff validates it on receipt (schema, then each rule it
  relies on) and is tested with tampered input. One file name has one writer and one shape.
- **Check:** `tests/test_vision_auditor.py::test_the_data_agent_checks_a_typed_handoff_on_receipt`,
  `::test_the_committed_clusters_json_is_the_auditor_s_code_output_and_the_data_agent_takes_it`.

### 153. A light module imports only light modules
- **What happened:** the live API scales to zero, and its cold start was about 50 s, about 33 s of
  it Python start-up on a fractional vCPU. `import ninety.api.app` loaded the agent framework, the
  Foundry project client, the OpenAI client and the blob storage SDK. The cause was that
  `ninety.agents.contracts`, which only declares types, imported three short names from
  `ninety.agents.slice`, a live entry point that loads them all at its top. Locally the import
  took 3.28 s (median of five fresh interpreters), against 1.00 s once they load on first use.
- **Rule:** a module that only declares (contracts, rules, types) imports nothing that talks to a
  service. A name two layers share lives in the lower one, and the entry point re-exports it. An
  SDK that only a live call needs is imported inside that call.
- **Check:** `tests/test_api_startup.py::test_importing_the_api_loads_no_model_sdk` reads
  `sys.modules` in a fresh interpreter (lesson 104); `::test_the_check_sees_an_sdk_when_one_is_imported`
  shows the check can go red.

### 154. A check that measures a defect also stops it where it airs
- **What happened:** #182 taught the failure table to fail a baseline whose Spanish profile read as
  English, but the on-air gate (`personalizer/cues.verify`) still held only text byte-identical to
  the verified English. A live Personalizer writing English with one word changed would have aired,
  marked verified, to a Spanish viewer, and only the evaluation would have noticed. The
  first version of the gate also passed the mock translator's English: its `[es]` label counted as
  the Spanish word "es".
- **Rule:** when an evaluation learns to catch a defect, the same check guards the live path, and
  the evaluation keeps measuring independently of the gate. An exemption names both the mode and
  the mark: the mock airs only in a run that asked for it (`NINETY_TRANSLATOR=mock`) and only with
  its label on screen, so a model cannot exempt itself by writing the label. Labels and quotes are
  not words of the text.
- **Check:** `tests/test_personalizer_live.py::test_english_for_a_spanish_profile_never_airs`,
  `::test_the_labelled_mock_airs_only_in_mock_mode`,
  `::test_spanish_with_an_english_name_or_quote_still_airs`; and
  `tests/test_workflow_failures.py::test_the_baseline_fails_when_a_spanish_profile_reads_english_with_a_word_changed`
  shows the table still catches it with the gate removed.

### 155. A test of a library's message shape goes through the library's own parser
- **What happened:** #182 made a published agent's call to the match tools fail the call, keyed on
  the content type `mcp_server_tool_call` in its reply. The tests built that content by hand with
  `Content.from_mcp_server_tool_call`. Had a framework upgrade renamed the type, or stopped turning
  Foundry's `mcp_call` output item into it, the guard would pass every call and the tests would
  stay green. The review caught it. Separately, a tool call made a minute air nothing, but only the
  ablation's JSON counted such minutes.
- **Rule:** when code keys on the shape a third-party library produces, at least one test feeds the
  library the service's raw payload (here a Responses API reply as Foundry returns it) and lets the
  installed parser build the shape. A failure that costs one arm output is counted in the report a
  reader sees, not only in the data.
- **Check:** `tests/test_workflow.py::test_inline_only_reads_a_foundry_reply_as_foundry_sends_it`;
  `tests/test_agent_ablation.py::test_a_live_arm_that_calls_the_match_tools_fails_that_call` reads
  the "Minutes lost to a tool call" column.

### 156. An exemption is stated in what the clip shows at both ends, and attacked with planted clips
- **What happened:** the contract check for a broadcast cut (C2) accepted a gap when the last stoppage
  or restart before it was a stoppage, or when a window opened on a loose ball, and looked at no
  other event. An independent review's planted clips found two holes. A pass after the stoppage put
  the ball back in play unseen by it. A window of open play with a gap and no event at all passed.
  The renderer only made legal cuts, so no clip was wrong, but the validator would have passed a
  wrong one. The cut was also on by default, so dataset and test-set renders would have cut too.
- **Rule:** an exemption in a contract check is stated in what the clip itself shows, here both the
  stoppage and the restart as events of the clip with nothing live between them. It is tested with
  planted clips that try to abuse it, written by someone other than its author. A feature that
  changes what a dataset contains is off by default and turned on where it is wanted.
- **Check:** `tests/test_validate.py` (the planted cut clips; they fail on `aef43f5`) and
  `test_every_check_the_validator_reports_has_a_planted_defect`;
  `tests/test_render_params.py::test_only_a_broadcast_clip_cuts_through_dead_balls`.

### 157. Measure an asset before scaling by it, and drive feet by place, not by pose
- **What happened:** two defects in how the skinned players were drawn, both since the mesh
  (a3d228e), both invisible to every test because each test measured the code against itself.
  The body asset is 1.684 m to the top of its skull, but every scale treated it as 1.84 m, so each
  player was drawn at 91.5% of his height: short and stocky next to the goal and the capsules he
  replaced. And the stride swung each leg between two stored poses, which moves a foot back and
  forth along one path: there is no low stance and high swing, so a walking foot skimmed along the
  grass and a landing foot was blended onto its plant: a quarter of the frames a foot was on the
  grass it slid more than 2 cm, up to 23 cm.
- **Rule:** a constant taken from an asset is measured from the asset and tested against it. A
  drawn body is checked against the world, not against its own constants: as tall as the player,
  joints where a man's are (a cited table). Feet are placed: fixed where they land, carried on an
  arc to where they will land, and judged frame by frame on the skinned markers.
- **Check:** `tests/test_render_mesh.py::test_a_player_is_drawn_as_tall_as_he_is` and
  `tests/test_render_motion.py::test_a_foot_on_the_grass_does_not_slide_from_a_standstill_to_a_sprint_and_back`
  fail on the code before; `test_the_body_has_a_mans_proportions_and_its_stature_is_the_scale` holds
  the scale to the asset and its joints to the table.

### 158. A point one rule puts exactly on a boundary is on it for every other rule
- **What happened:** the keep-off rule moves an opponent's target to the edge of the 9.65 m circle,
  and the wall stands on that edge. A second rule sends a player round the circle while his
  straight way "comes closer than 9.65 m". For a place on the edge, straight in from further out,
  the closest point of that way is the place itself, and rounding put it a hair inside: the player
  was sent round the circle at his own distance, which is where he already stood. He stood 7 m
  from the wall through the whole stoppage. No test placed a target exactly on the edge.
- **Rule:** where one rule produces points on a boundary that another rule tests, the test allows
  for rounding (a named tolerance), and a test puts a point exactly on the boundary.
- **Check:** `uv run pytest tests/test_restarts.py -k edge_of_the_circle`; it fails with the
  tolerance set to 0.

### 159. A check of one frame against another cannot see an error the frames share
- **What happened:** the camera trust test (players' heights) let through frames up to 55 m wrong on
  validation. A check that each trusted frame's camera agrees with a trusted neighbour's (image
  centre within 2 m, within 5 frames) brought the worst down to 8.2 m there, under a bound set
  beforehand. On the test set it removed 4 of the 8 far-wrong frames on the two clips with camera
  cuts. The other 4, on seed 900003, are about 46 m wrong but agree with each other: a run of
  frames the fit got wrong the same way. Validation's seed 108 is the same failure, milder: a whole
  clip offset 2 to 8 m.
- **Rule:** before adopting a consistency check, say which errors it can see. Comparing frames
  catches an isolated error, never one that frames share: two adjacent frames wrong the same way
  pass together, and a wrong frame can make its good neighbour fail. So its worst on validation is
  an observation, not a bound. A shared error needs an
  absolute reference: the pitch markings, a known landmark, or a source independent of the fit.
  Report what the check leaves, by the size of what it lets through, on the clips it is scored on.
- **Check:** `tests/test_vision_observe.py`:
  - `::test_a_frame_whose_camera_disagrees_with_its_neighbours_is_not_trusted` passes;
  - `::test_a_whole_clip_in_the_wrong_place_is_not_trusted` is a strict expected failure, the
    shared-error case;
  - `docs/eval/camera-bound-plan.md`, Outcome, has the test set's frames left per clip.
### 160. A pass or shot ends at the next thing that happens to the ball, however long it stays open
- **What happened:** the engine keeps a shot open after a block, so a deflected shot can still count
  as the shooter's goal, and closed it only when someone controlled the ball, at a foul, an offside,
  or when it went out. On seed 21, the demo window, a10's shot at 4:37 was blocked; he got back to
  the ball and h4 poked it loose at 4:39 (a tackle). The shot stayed open until h8 controlled the
  ball at 4:41 and its end point was written there, after the tackle, so the data contract's C7
  (the ball reaches the end point before anything else happens to it) failed.
- **Rule:** keeping an event open for one purpose (crediting a goal) never lets it outlive the next
  on-ball event. A touch ends it (`touched`); every other path that records an on-ball event while a
  kick may be open ends it first, where the ball is (`Engine.end_kick`: a tackle's poke, a foul, an
  offside), judged on the ball's own flight before anything changes it.
- **Check:** `tests/test_shot_end.py`: seed 21's case, asserted to occur (lesson 41), with C7 and
  "no carrier strikes with a kick still open" checked on the real match; a poke on an open shot; and
  an untouched shot judged on its own flight, not the tackle's push.

### 161. A claim about how players move is checked on the paths they walk
- **What happened:** the free-kick wall's players shared out its places by the least total of
  straight lines from where they stood, and GROUNDING, the report and a docstring said that no two
  runs to the wall cross; the test checked the straight lines. A focused audit followed the runs
  frame by frame: players go round the 9.65 m keep-off circle at their own distance from the ball
  and come in behind the wall, and two runs crossed within a second of each other in 22 of 72
  planted kicks. The fix estimated each walk the way it goes, round the circle at the walker's own
  distance from the ball: that changed who stands in the wall and how fast they walk there, but not
  the crossings (that walk is not the shortest way, so the uncrossing argument does not hold for it,
  and two coming round the same side share the way behind the wall). And it repeated the mistake:
  its docs said the estimate followed `keep_off`, and a second audit, frame by frame, found the
  walked paths round the circle 6 to 24% shorter, because `keep_off`'s aiming walks a spiral in
  toward the circle. It is now stated, and tested, as an estimate from above.
- **Rule:** a claim about movement (no crossing, no contact, in place in time) is measured on the
  walked paths, frame by frame, before it is written down; a property of the plan is stated as one.
- **Check:** `uv run python scripts/defect_sweep/wall.py --planted` reports the walked crossings for
  each kick; `uv run pytest tests/test_restarts.py -k estimated_from_above` follows the walks frame by
  frame against their estimate.

### 164. A pose keyed to an action ignores the truth it stands for; a limit marked "measured" is re-measured where the defect shows
- **What happened:** a blind critic of 0.5.3 found four body defects. A throw-in drew its stored
  pose, arms over the head, from the frame the engine named the thrower, while the engine's ball
  was still at his feet; the ball then rose into empty hands and left with no throw. The jog was
  a march: the stride's stance share was a guess, and the swing peaked under the hips. A
  stride's swing read its progress straight off the shared phase, so a change of pace moved a
  foot in a frame. And the push-off toe slid up to 17 cm a frame because the stance was allowed
  0.45 m behind the hips, a limit commented "measured" that the asset's leg reaches only to 0.30.
  Two old tests also held design as truth ("walking at 3 m/s, a foot is always on the grass").
  The first fix passed every steady-speed test, and a blind critic still preferred 0.5.3: speeding
  up, slowing and drifting, its players hopped with both feet tucked, because a foot lifted early
  for reach started its swing count from zero, both feet left the grass together setting off, and
  a pose flickering between walk and stand restarted a stride that never landed. The next draft
  drew the runners' knee fold whole (to 109 degrees at 3.5 m/s, Fukuchi 2017): true to the
  source, and a third blind critic still preferred 0.5.3 on the jog clip, because at broadcast
  size a heel at the seat with a level pelvis and no bob reads as prancing. Only the timing went
  in (highest a third of the way through the swing, behind him); the height stayed 0.5.3's.
- **Rule:** a drawn action follows the truth it shows, frame by frame: hands go where the
  engine's ball is, from before it moves until after it leaves. A gait's numbers come from a
  cited source, and a swing keeps its own progress so a change elsewhere changes where it lands,
  never where it is. A constant marked measured carries the measurement (what, how, the number)
  and is re-measured when a defect points at it; a test's premise that a source contradicts is
  rewritten to what it was protecting. A gait change is judged blind on clips where players
  change pace, not only on steady-speed tests, and a sourced angle is drawn only as far as the
  rest of the body (pelvis, bob) can carry it.
- **Check:** `tests/test_render_motion.py`: `test_a_throw_in_keeps_both_hands_on_the_ball_from_the_grass_to_the_throw`,
  `test_a_throw_in_moves_no_limb_in_a_jump`, `test_a_running_foot_is_highest_early_in_its_swing`,
  `test_the_push_off_toe_does_not_slide_before_it_lifts` and
  `test_a_player_stopping_does_not_stand_with_his_legs_crossed` each fail on 0.5.3 (mutation runs
  with main's stride and throw restored); `test_a_player_drifting_while_the_pose_flickers_keeps_his_feet_down`,
  `test_setting_off_from_standing_lifts_one_foot_at_a_time` and
  `test_setting_off_the_feet_do_not_leave_the_grass_together` fail with each hop's cause put back.

### 166. A wait for something to happen ends when it can no longer happen
- **What happened:** a throw-in released behind the touchline counts as still coming in while it
  moves toward the field, judged by the sign of its speed across the line alone. In the wall's
  16-match re-measure (seed 101) a throw drifted along the outside of the touchline, a centimetre a
  second inward: it stayed in play past the end of the touchline and over the end boards, which only
  a dead ball meets, rolled on 14 m beyond them, and when it stopped the retake snapped it back to
  the boards, a 14.6 m jump in one frame. The restart sweep then counted the retakes as free kicks
  taken from the touchline with opponents inside 9.15 m, and the retaken throw as the taker's second
  touch.
- **Rule:** a state that waits for an event (coming in, arriving, landing) also ends when the event
  can no longer happen where it is allowed to (here, past the end of the touchline); a measurement
  counts a restart taken again as the same restart.
- **Check:** `uv run pytest tests/test_restarts.py -k past_the_end_of_the_touchline`; on the engine
  before it, the ball runs on to 127 m and jumps 18 m in a frame.

### 172. A score called a confidence is measured before a gate is built on it
- **What happened:** the phone's possession layer was designed to show a team only above a
  confidence: the detector's side confidence times an age factor. Measured on 13 validation clips
  before any UI was built, team agreement fell as the cut-off rose (65 % at 0.2, 30 % at 0.7, 0 %
  at 0.9), because the side is decided once per clip, and a flipped clip is wrong throughout, one
  of them at 0.88 to 0.97. `Track.side_confidence` says it is "a score, not a probability"; the
  design treated it as one.
- **Rule:** before a confidence gates what a viewer sees, measure agreement against it on
  validation data: the curve by cut-off, and per clip, since errors that share a cause share a
  clip. If no cut-off reaches the target, the gate stays shut and the feature stays off; never
  move the target to open it. Build the screen only after the gate can open.
- **Check:** `tests/test_possession.py::test_while_the_gate_is_unset_the_layer_shows_nothing` and
  `::test_the_committed_calibration_states_its_targets_and_its_evidence`;
  docs/eval/possession-calibration.md.

### 173. A label check written for one pose fails the first body drawn in another
- **What happened:** to make fouls legible (the fouled player goes down at the foul, the fouler's
  foot meets his shins), the renderer tipped the fouled player's body over his feet. Render-check's
  `player_feet_in_boxes` then failed 49 frames of seed 7's foul, all on the player lying down: it
  required his ground point at the bottom of his box, with slack scaled by box height over 1.8 m,
  and a lying body's box is neither 1.8 m tall nor has his feet at its bottom (fallen toward the
  camera, they are at its top). His feet were inside the box on every one of those frames.
- **Rule:**
  - A check on the labels states the pose it assumes. When the picture draws a new pose, the label
    data says so (`fall` in the frame row, an optional field) and the check judges that pose by
    what is true of it, with a planted failing case.
  - It never skips the player or widens the slack for everyone.
  - Upright players are checked exactly as before.
- **Check:** `uv run pytest tests/test_render_checks.py tests/test_render_fouls.py`. A fallen player
  passes toward the camera, away from it and sideways. A box beside or above his feet still fails,
  and so does a row with no `fall` and a lying player's box.

### 174. A player with time to spare walks there and waits, rather than creeping in just in time
- **What happened:** at restarts the engine paced every player to reach his place just as the
  kick could come. At a corner that is about half a minute off (R1: Opta's mean is about 30 s), so
  the players crept in below a walk for most of the wait: 72% of the outfielders' time after the
  ball was fetched was at 0.2 to 1.2 m/s, over 25 corners in 20 matches. The corner's length
  matched Opta's, but twenty players drifting slowly for 20 s read as "a long time to take a
  corner". The first fix, a walking floor on every move through the wait, made them shuffle
  instead: the audit counted 10.4 direction reversals per outfielder-minute against main's 0.7.
  The creep had hidden four loops, each between two rules: every small shift of a place that
  moves (a man marked, a slot) walked to and back; keep_off sending a player who had stopped a
  hair short of his place on the keep-off circle's edge back out past it, every half second; the
  floor holding a player going round another who stood on his place, so he circled him at a walk,
  0.2 m off, for half a minute; and the defending side's brain naming its presser and cover again
  at every look, by an order that the two roles' own walks changed, so two players swapped roles
  twice a second through the whole wait. Two of those fixes then put opponents inside 9.15 m at the
  kick, in 7 and then 10 restarts of 20 matches against none on main: the roles were kept only while
  the restart waited, and the cover's spot was worked out as in play, so as the taker stood over the
  ball the cover was sent in from 11 m; and the straight way through keep_off's 0.5 m margin let
  players walk in the margin that takes up a bend or a step too far. The second audit still counted
  twice main's to-and-fro (1.43 reversals a minute against 0.70): the floor walked every jump of a
  place by more than a stride, and at a dead ball places jump with what players see and whom they
  mark, so the kicking side's back line, following an onside line read from noisy sightings, stepped
  1 to 3.5 m back and forth every second or two through free kicks. And kept roles kept a clash that
  asking again had moved from player to player: at a free kick with a wall, the presser's place is
  where the wall stands, and the same presser was pushed in and out of 9.15 m by the wall's players
  for the whole wait, 6 cm inside it at the kick. And near a line, the way round the keep-off circle,
  aimed off the pitch and kept on it, fell inside the circle: a defect main has at a creep, walked
  into 9.15 m more often (10 entries near a line in 20 matches, against 4), once at the kick. The
  third audit found settling had brought the creep back: 42 of 144 free kicks had a player creeping
  more than 10 m in one spell (the version before settling had none). "The ball set" was checked as
  the ball within a foot's reach of its spot, true at the whistle with the ball still rolling and
  before the fetch; a settled player then followed every later shift of his place at his own pace,
  however far (up to 42 m, as the restart's shape formed); and settling was judged on keep_off's
  first step out of the circle, not on his place, so one settled 18 m from it. The hold near a line
  that fixed the cut-through stranded players 20 to 52 m from their places for up to 41 s, and one
  between the ball and the line inside the circle for the whole wait. And going round the circle,
  each chord's dip into the 0.5 m margin sent the player straight out, so he stopped short every
  few strides and went round at about 1.1 m/s: below a walk, on every version since the margin.
  Walking a big shift again then showed one more loop the creep had hidden: the defending side
  picked up the attackers near its goal afresh at every look, so men changed markers from look to
  look, and three defenders walked out and back up to 19 times through one free kick's wait; the
  taker's marker was placed where the wall stands. And a settled presser at a goal kick, bent off
  his place by a team-mate beside it, went back at his pressing pace and sprang back and forth,
  28 times in one wait.
- **Rule:** "just in time" is a pace for play, where arriving early costs something; with time to
  spare at a dead ball a player walks to his place (L4's normal walking pace) and stands there; once
  there with the ball still on its spot, he has settled, and he follows a small shift of his place
  (what he sees, whom he marks) at his own pace, but walks a big one. A state that turns a rule off
  ("settled") names the condition that ends it as well as the one that starts it, and each is
  checked as the code checks it ("set" is still, on the spot, at nobody's feet but the taker's).
  A rule about where a player stands is judged on where he stands, not on a waypoint on the way.
  A head is measured, rendered and published only once `uv run pytest` passes on it: two heads
  here were measured before it did (one called the C library's acos, one let a presser leave the
  area late at a goal kick), and their numbers had to be measured again.
  A realism complaint is measured in parts (fetch, arrivals,
  wait, speeds) before the total is blamed. A change that makes players move faster is also
  measured for to-and-fro (reversals, the distance walked to and fro, waits with three or more
  reversals) and for creep spells (a player at 0.2 to 1.2 m/s for more than 5 or 10 m in one
  go): a slow pace hides a target that flips, and a rule that turns the floor off can bring the
  creep back. A loop between two rules is fixed where they meet, not by slowing the player down.
  And a change to how players move near the ball goes through the restart sweep (the Laws'
  distance at the kick) after every fix, not only the first.
- **Check:** `uv run pytest tests/test_restarts.py -k "walk_to_their_places or fetching_a_dead_ball_keeps
  or hair_inside or stands_at_his_place or does_not_circle or keeps_its_presser or stand_off_it
  or he_settles or settles_only_at or nobody_else_is_named or never_cuts_inside or by_a_line
  or short_way_is_open or keeps_his_man or kept_man_stays or does_not_settle_while
  or spring_about or judged_on_his_place_not or aim_is_off_the_pitch"`; each fails on the engine
  before its fix (`brought_onto_it` is a guard).
  `scripts/defect_sweep/creep_spells.py` counts creep spells through the waits.
  `scripts/defect_sweep/restart_moves.py` reports speeds, reversals and to-and-fro per
  outfielder-minute through every restart wait, `scripts/defect_sweep/corners.py` the corners, and
  `scripts/defect_sweep/restarts.py` the Laws' distance at the kick (nobody inside, as on main).

### 175. A held-out seed that passes may hold none of the cases the rule gets wrong
- **What happened:** the broadcast camera (#180) passed its framing test on held-out seeds 3 and 5
  at 98%. With #179's engine, seed 3's window held three corners and two balls run to the byline,
  and it fell to 58%. Two causes:
  - The test simulated only 2 minutes, so a dead ball at the window's end counted as live (lesson
    140, applied to the clip but not to the test).
  - The camera had real misses that main's seed 3 never showed:
    - the restart's close-up zoomed out on a spring that took 3 s and more, so a corner was played
      through the close-up;
    - the aim stopped 8 m short of each goal line;
    - nothing kept the pitch filling the picture when aimed into a corner.
- **Rule:**
  - A camera rule gets a test for each situation it must handle, built on purpose (a restart taken
    early, a ball run to the byline, play at a corner flag), not left to whatever a held-out seed
    happens to contain.
  - A test's simulation runs past its window as the render's does.
  - The held-out number is reported, never tuned toward.
- **Check:** `tests/test_render_camera.py`:
  - `test_a_restart_taken_during_the_close_up_is_watched_on_the_wide_shot`,
    `test_a_ball_run_to_the_byline_stays_in_the_middle_of_the_picture` and
    `test_play_near_a_corner_flag_is_framed_with_the_pitch_filling_the_picture`, each of which fails
    on the 0.5.3 camera;
  - `_match` simulates SIM_MARGIN_S past the window.

### 176. A bound that held by 7 mm in one scenario is not a bound
- **What happened:** a test from #183 claimed that no wall player walks further than
  walk_to_wall's estimate of his walk, followed frame by frame in two scenarios that come out of a
  minute of play. It held by 7 mm in one of them. Lesson 174's change altered that minute (lesson
  90), and in the new scenario a wall player walked 15.24 m against an estimate of 15.11 m. All of
  the 0.22 m extra was bending round others who stood in his way (avoid), which the estimate never
  modelled: without his own bending he walked 15.02 m. Measured, as it should have been first, over
  60 walks in 15 scenarios with that bending left out: on main all 60 were within the estimate, the
  closest by 2 cm; on lesson 174's branch at `b090877`, 58, and two over it, by up to 0.18 m in
  15.4 m. Those two are walks main's engine walks the same from the same start: a walker still
  moving at the whistle, whose stopping distance the estimate has no term for, and one going round
  the keep-off circle who stepped out past it and spiralled back in, which its spiral leaves out.
  At `00d5c41`, where going round from the circle's margin heads out as well as round, 59 are
  within it and one over, by 1.04 m in 28.3 m: a walker running at 3.2 m/s at the whistle, who
  spent his first second turning (1.5 m walked, 0.5 m gained). At `304fffe`, 58, and two over by
  up to 0.27 m in 36.6 m, both moving at the whistle; at `ba23065`, all 60 within it. Without such
  a start the estimate is within about 1% of the walk, not a strict bound.
- **Rule:** a bound measured on a few scenarios is reported with its margin and with what it
  covers, and a check that passes by a hair in a chaotic scenario is measured over more scenarios
  before it is called a bound. When a check fails because its claim was too broad, the claim is
  corrected where it is written and the check narrowed to it, openly; it is never re-seeded or
  loosened until it passes.
- **Check:** `uv run pytest tests/test_restarts.py -k estimated_from_above` pins the estimate on
  his own route (the wall players' bending switched off) in its two scenarios, not a bound;
  `uv run python scripts/defect_sweep/wall_walks.py` measures the 60-walk margins
  (docs/eval/restarts.md, "Walking to restart positions"). No test sees a wall player bending round
  others on his way in: a gap.

### 177. A coarse search proves a case unframeable only where it searched
- **What happened:** after #198, #179's seed 3 still missed the camera's 85% framing bar.
  - A corner rule (framed from the taker inward, its shot held against pumping) fixed what the blind
    critic saw: near corners went from 26% to 34% pitch, far corners to 79%.
  - It did not move seed 3's score. I reported its misses as live play near the near flag that no
    gantry shot could frame. That claim rested on a coarse search (3 m aims, a few lenses) that had
    shown only the corner flag itself to be unframeable; I extended it to points it never covered.
  - The oracle the Reviewer asked for (the gantry camera itself, 1 m aims, every lens in 1-degree
    steps) found 1 of seed 3's 201 live frames unframeable. The rest were the director's misses.
- **Rule:**
  - A claim that something cannot be done is checked by a search at the resolution of the claim,
    on the system's own model, before it is reported.
  - An exclusion that excludes almost nothing buys nothing: the bar stays raw (the fine oracle,
    tried and dropped, excluded 1 of 201 frames).
  - The Reviewer then found the corner rule's own hold made the delivery worse than no rule (a
    long cross 0 of 88 frames well framed against 41) and its ball-position trigger caught open
    play on the goal line. The rule now runs only from the engine's corner set piece to the kick.
- **Check:** `tests/test_render_camera.py::test_after_the_kick_the_corner_rule_frames_no_worse_than_no_rule`
  (red on af7e439), `::test_a_corner_is_framed_from_the_taker_inward`,
  `::test_each_corner_has_its_own_shot_and_the_ball_stays_in_it` and
  `::test_the_corner_shot_holds_until_the_kick`; the framing bar is raw.

### 180. A motion keyed to the stride's clock is checked against the contacts it is drawn over
- **What happened:** #197 left the runner's hips level, so a jog read as a power-walk. The bob
  went in from a sourced table by speed, keyed to the stride's phase.
  - Three existing tests failed, and each failure was a real defect the phase hid.
  - Where the phase said flight, the drawn push-off foot was still on the grass: the hips rose,
    the leg could not reach it, and the toe hung 3 cm up and slid.
  - The flight's free fall counted from a swing's first frame, which still draws the foot on the
    grass, so the hips jumped 4 cm across the push-off at 2.5 m/s.
  - That first frame was itself the sprint's flicker a blind critic saw (round 4): drawn where it
    lifted, a sprinter's foot hung 40 to 56 cm behind the hips, beyond the leg, for a frame. Both
    feet were seen off the grass in one frame a step.
  - The bob's dip let a walking leg reach its swing target. A foot 1 cm up in its landing frame
    then counted as "on the grass" in the slide test, which had been passing only because the
    stretched leg held it higher.
  - The lean with acceleration took the engine's speed, eased over 5 frames. At a steady jog the
    engine's speed rises and brakes back every 9 frames (seed 21's a5, 3.2 to 4.0 m/s), so the
    blind critic saw the trunk nod every step, plus a stoop and a sideways topple turning on the
    spot. The lean now takes the change between two 8-frame mean velocities, along the way he faces.
  - Blind critic round 2 found the bob, sent in the body's lift, tripped the lunge's rule (a
    lowered body reaches for an out-of-reach plant above the grass): braking to a stop, a planted
    foot was drawn 25 to 38 cm up for 8 frames, a freeze. The round 1 critic had missed it in the
    same code. The bob is its own pose field now. The lean from boxes behind him came 5 frames
    late, pitched forward while braking; it now looks 8 frames ahead, as the hips' lead already did.
  - The independent audit found a sprint swing height (0.45 at 7 m/s) with no source that only
    kept an old test green, and tests that read their bounds from the code's own tables: with the
    tables zeroed they passed, 0 within 0.
- **Rule:**
  - A body motion keyed to a clock (the stride's phase) rises or falls only where the drawn
    contacts allow it: the free fall runs from the frame both drawn feet are off the grass to the
    frame the swing's own count lands one.
  - A foot that leaves the grass between two frames is drawn a frame into its swing.
  - A sourced angle (Fukuchi's knee fold) goes in only with the rest of the body that carries it
    (the bob), measured on the drawn mesh, and as far as the drawn leg reaches (111 degrees, not
    119).
  - A test's selection that a better drawing newly meets (a landing foot inside the slide test's
    2 cm) is narrowed to what it protects, with the reason in its docstring, and the bound stays.
  - A renderer reading the engine's motion reads its trend over a stride, not its per-frame
    controller steps, and centred on the frame it draws, never only behind it.
  - A new quantity is sent in its own field, never folded into one whose value already means
    something to a rule (a negative lift means a lunge).
  - The same held for a keeper's dive (demo v1, Kian: "keeps diving"): drawn as the engine's
    per-frame pose, a dive the engine turned on the grass spun and dived again to the other side,
    and one that began at full stretch popped in and out. A one-off action is drawn once, from
    its start to its end, its side and facing held, and fades into what follows.
  - A test's expected value is the source's number written in the test, never the code's table.
- **Check:** `tests/test_render_motion.py`. Each of these fails on 0.5.9 (main's drawing, with
  the new names shimmed in):
  - `test_a_runners_hips_are_lowest_on_the_grass_and_rise_in_the_air`;
  - `test_a_walkers_hips_are_highest_over_the_standing_leg`;
  - `test_a_running_knee_folds_as_far_as_a_runners`;
  - `test_the_trunk_leans_into_a_sprint_start_and_comes_up_braking`;
  - `test_the_arms_swing_wider_toward_a_sprint`;
  - `test_a_sprints_flight_is_seen_over_two_frames_or_more`.
  - `test_the_push_off_toe_does_not_slide_before_it_lifts` fails with the free fall keyed to the
    phase; `test_a_player_braking_to_a_stop_keeps_his_planted_feet_on_the_grass` (seed 21's a4)
    fails with the bob sent in the lift, and the trunk test with the lean from boxes behind only.
  - `test_a_keepers_dive_is_drawn_once_to_one_side` and
    `test_a_dive_that_starts_at_full_stretch_grows_and_gets_up` (demo v1's keeper) fail on 0.5.12.
  - Each mechanism was put back to 0.5.9 alone (bob tables zeroed, swing height, the frame-ahead
    swing, the lean, the speed lean, the arm pump), and its test fails.

### 184. What the picture draws as solid, the engine treats as solid
- **What happened:** the renderer drew a net behind each goal, but the engine had none. After a
  goal the dead ball rolled on through the back of the net to the advertising boards, 4 m behind
  the goal line, and the keeper walked through the net to fetch it. On demo v2's seed 8001 the
  ball came to rest at (109.0, 35.7) after the goal at 155.3 s. Over 20 matches on main it
  happened after all 16 goals. Players walked through a net 66 times, 61 of them keepers, all while
  the ball was dead: 27 after goals and 39 at other stoppages.
- **Rule:**
  - Every structure the renderer draws that a ball or a player can meet has the same geometry
    in the engine's physics, citing the drawing where it takes its shape from it: the boards,
    and now the net (L1).
  - For the net that now means no player passes through it, and a ball that goes in stays in the
    goal. A ball meeting it from outside (wide of a post, or dropping over the bar) still passes
    through; that is the next step.
- **Check:** `uv run pytest tests/test_goal_net.py`. On main the ball goes 4 m deep, through the
  roof and through the side netting, and the keeper walks through the net.

### 185. Footage a viewer watches and data a model learns from are dressed apart, and the dressing is proved label-free
- **What happened:** the demo clip (seed 8001, v1) was rendered with the training look: seats with no
  one in them, beige run-off and black ground behind the goals, four repeated boards, stark mowing.
  The blind critic scored it 2/10 and ranked empty stands and bare ground at severity 4. The look
  was built for the detector, where a crowd is only clutter that could change what a dataset
  measures, so nothing ever dressed the footage a person watches.
- **Rule:**
  - Dressing for viewers sits behind a knob that no seed draws (`stadium=broadcast`, like
    `kit_contrast=broadcast`): training, validation and test renders stay byte-identical.
  - Dressing is scenery: never labelled, and in the id pass it hides what is behind it exactly as
    the picture does. The fans are drawn there with the same billboards, cut-outs and motion code.
    A first version left the crowd out of the id pass, which labelled a ball among the fans as
    visible while the picture hid it (lesson 84; the Reviewer caught it).
  - A test proves both sides with a case where they matter: a ball in the stands behind fans.
- **Check:**
  - `uv run pytest tests/test_render_stadium.py -k crowd`. It fails with the fans left out of the
    id pass (the ball among them stays visible). It also fails with their picture colours drawn
    into it, where the fans' pixels counted as 52,436 visible pixels of one player.
  - `tests/test_render_params.py::test_only_footage_asks_for_a_broadcast_stadium`.
  - Plain stills from main and from the change are byte-identical under software GL.

### 187. A shot built to pass a framing metric can still be dead air to a viewer
- **What happened:** the restart close-up (#198, lesson 175) passed every framing test: the ball
  central, the pitch filling the picture after the ease out. On demo v1, a blind critic watching as a
  viewer found it the worst part of the edit. For 4.4 s before each restart, one player stood still
  beside the ball, then the camera pulled out. After the goal, a fixed low shot beside the net showed
  the keeper fetching the ball, never the scorer. The clock also jumped at every cut with nothing on
  screen to explain it. Each shot met its rule, and the sequence was dead air.
- **Rule:** an edit or camera rule is judged on what a viewer sees across the cut, not only on the
  framing of each frame:
  - who is in the shot (the scorer, not the keeper);
  - whether anything moves;
  - whether a jump in time is marked (a stinger).

  A rule's bounds come from the critic's complaint and are written as tests before the change.
- **Check:** `uv run pytest tests/test_render_edit.py tests/test_render_camera.py -k "imminent or
  celebration or stinger or opens_on_the_wide or scorer"`. Each test fails on 0.5.9, the version
  before demo v2.

### 162. A player off the ball answers the players around him, not only the ball
- **What happened:** fans and clip critics saw the team without the ball stand between actions. On
  seed 21 most standing spells of 3 s or more were block defenders whose place did not move while
  they stood. Every place off the ball (block slots, the attacking shape, all but the carrier's
  nearest two) depended on the ball's position alone, so when the ball paused both teams froze. A
  walking floor did not fix it (standing 22% to 20%, one seed). The first fix for attackers chose
  the most open spot, then the one a pass is worth most at, and drew them toward the carrier: a spot
  nearer the ball is always safer, so passes shortened and square passes with a free option ahead
  (FS7) rose by about 40%. Holding pass length and FS7 out as checks caught it.
- **Rule:** a target off the ball reacts to the players he sees. An attacker steps to where a pass
  from the carrier is worth most, across his lane or further out, never nearer (O3). A block
  defender tracks the attacker in his zone, goal-side, without leaving it (O2). Each decides again
  only when he scans and holds his choice between scans. When a value always rises in one
  direction, limit the candidates by what football allows; never tune its weights to the held-out
  checks.
- **Check:** `tests/test_open_space.py::test_a_defender_in_his_lane_moves_an_attacker_once_he_scans`,
  `::test_he_never_comes_nearer_the_carrier_to_be_open`, and
  `tests/test_zone_tracking.py::test_a_defender_follows_the_attacker_in_his_zone_once_he_scans`; the
  held-out measures in the pull request.

### 189. A sentence beside a number is not its mark
- **What happened:** the goal-net change merged while its review check was skipped, so the
  hard-coding audit (lesson 21) ran after the merge. Two new factors had a sentence beside them
  and were still neither. The net-touch slack is two roundings of a written millimetre, and the
  comment said "measurement precision", but the grounding row's source cell said only "physics".
  A step through a corner of the net meets the side and the back, and the comment said so, with
  no *design* on the count of two.
- **Rule:** the mark sits on the constant. A margin from how positions are written names
  measurement precision in the grounding source cell, with the derivation beside the value
  (lesson 10). A choice carries the word *design* on its own line. A sentence that only describes
  the number is neither. The audit runs before the merge.
- **Check:** the audit's neither list. A constant on it is marked in a follow-up that does not
  change the value.

### 188. Two scorers of one group share one cut-off and one comparison
- **What happened:** EVALUATION.md puts a ball in the air when its centre is above 0.5 m. The
  pitch-level vision scorer used `z > 0.5`, but the position scorer (`pitch_score.py`) used
  `z < 0.5` for the ground, so a ball at exactly 0.5 m was on the ground in one report and in the
  air in the other. Both had the same constant; nothing checked the comparison, and no test put a
  ball exactly on the cut-off in the position scorer.
- **Rule:** a difficulty group's cut-off and its comparison are defined once (`IN_AIR_Z`,
  `height_group`, `BLUR_PX`, `blur_group` in `ninety/eval/vision_score.py`) and imported
  everywhere; each scorer has a test with a value exactly on the cut-off (lesson 158).
- **Check:** `uv run pytest tests/test_pitch_score.py tests/test_vision_score.py
  tests/test_fake_box_detections.py -k "cut_off"`; the pitch_score test fails with `z < 0.5` put back.

### 200. A surface is solid from both sides, and only where the ball is not going through its opening
- **What happened:** the goal-net change (lesson 184) gave the net an inside only. Over 20 matches
  of 20 minutes on main (`0f101db`) the ball went into a goal through its net twice: a high shot
  over the bar dropped through the roof and out through the side netting (seed 115 at 15:51), and a
  dead ball behind the goal was knocked to the goal-kick spot straight through the back of the net
  and the goal (seed 102 at 5:17). Two of the net tests could not fail: nobody's way to the ball
  after the planted goals crossed a net, and the goal test stopped on the goal event before the net
  acted. The first fix stopped every step at the net's outside, and the independent audit found it
  erased goals: a ball crossing the line between the posts from wide of one, or dropping in under the
  bar, was held at the outside of the side netting or the roof. Once the net was solid from outside,
  a ball knocked from behind the goal toward the spot stopped against it and was fetched and knocked
  into it again. And main's seed 116 failed P2: a keeper going round his goal to the ball behind it
  aimed at a point on the goal line beside the post, was carried over the line by his run and met the
  side netting, which stopped him dead (2.2 m/s in a frame). Moving that point in front of the line
  fixed the case but not the class: the third audit still found 6 of 100 starts behind or beside a
  goal stopped dead, where a way flipped between a post and a back corner or grazed one.
- **Rule:** a structure that stops the ball from one side stops it from every side it can be met
  from, in the engine and in the validator's list of contacts, and never where the ball is going
  through the structure's opening (a goal is judged first). Whatever plays the ball near the
  structure (a knock-on, a pass) checks that its way is clear of it. A wall that stops a body is
  approached no faster than the body can stop before it (the boards' rule, now the nets'), so the stop
  is never a teleport of velocity (lesson 5). A test of "nobody does X" plants a case whose straight
  way does X and asserts that it would; a test whose scene is a moment of a seeded match finds that
  moment by its premises, since any earlier change moves it (lesson 78).
- **Check:** `uv run pytest tests/test_goal_net.py`: the outside, roof, wide-of-the-post,
  carried-round and never-turns-away tests fail with `off_the_net` returning its step unchanged,
  with the goal guard in `Engine.woodwork` removed, or with the knock-on's clear way forced;
  `flies_on_freely` fails with the ball moved to the back of the net as it goes in;
  `stopped_dead` and `never_runs_into` fail with the net speed cap in `steer` removed.
  `scripts/defect_sweep/nets.py` counts balls through a net over a sweep.

### 202. A set piece is a moment players build up to, not a pose held until a timer runs out
- **What happened:** at a corner the taker stood over the ball and struck it from a standstill
  (0.27 m covered in the 2 s before the kick, 18 corners over 20 matches on main `0f101db`); the box
  stood still for the wait and the delivery, the post runners already at the posts; and the defending
  side matched rather than outnumbered the attackers in its area at 4 of 18 kicks. The causes were in
  the set-up, not the totals: the presser's cover was sent to the corner flag (goal-side of a presser
  held 9.15 m off the arc is the goal line by the flag), two free defenders held block slots just
  outside the area, and the kick was taken at R1's drawn time while team-mates heading "in time" for a
  pass after it were still walking up, so their markers were named late and sprinted in. Fixing the
  run-up first left the taker standing over the ball for 3 s after it: holding was still an option.
- **Rule:** a set piece is set up by the players' own reasons: the taker places, steps back and runs
  up when his team is in position (never past a bound, so nothing can hang); the attack starts its
  runs with the run-up; the defence sets up where the delivery comes (a near-post guard, the area
  defended, no cover where a cover has nothing to cover). A rate (corners, shots from corners, how
  long a corner takes) is reported as a held-out check, never tuned. A test planted at one kind of
  restart for a rule shared with others names the kind its premise needs.
- **Check:** `uv run pytest tests/test_set_pieces.py` (each fails on main);
  `scripts/defect_sweep/setpieces.py` reports defenders minus attackers in the area, box speeds
  in the second before and after the kick, and the taker's run-up, over a sweep.

### 207. A restart is played from its spot: set the shape there, and keep everyone off the set ball
- **What happened:** two leftovers of lesson 174's walking. While a restart waited, every player's
  place was set from wherever the dead ball was, so as it rolled on to the boards and was carried
  back, the places moved with it and were walked to and back. And once the ball was set on its spot,
  only opponents kept off it (the Laws' distance): a team-mate of a free kick's taker walked over it
  to his place, and a player walking back for a kick-off after a goal walked over the ball on the
  centre spot (2 walks over the set ball in 20 matches on main `0f101db`, counted after the first
  second of each stoppage, which is the fouler's own momentum). Setting places from the spot also
  removed the scene a lesson 174 test was planted in, so its premise search moved to another seed.
- **Rule:** while a restart waits, play is at its spot; anything a player does "relative to the ball"
  at a restart is relative to where it will be taken. A set ball is solid for everyone but its taker:
  a way past it keeps the taker's own clearance.
- **Check:** `uv run pytest tests/test_restarts.py -k "walks_over_a_set_ball or places_are_set_from"`
  (each fails on main); `scripts/defect_sweep/crossball.py` counts walks over the set ball over a sweep.

### 213. A match has two halves: build what the Laws require, and say plainly what is still missing
- **What happened:** the engine played 90 minutes as one long half: no whistle at 45:00, no
  second-half kick-off. For a demo cut from a full match, a judge would see play run straight through
  half-time. Switching ends was out of reach for the deadline: the attacking direction is fixed by
  team in about 60 places in the engine and in at least ten readers of its data (the stats, vision,
  evaluation, the validator), so it needs a direction field in the contract before the engine can
  change it. The first version also ended the half between a penalty being taken and its shot
  being struck, because "in progress" was read from the shot alone.
- **Rule:** a rule of the game is built as far as can be done right, and the rest is written down as
  a gap in GROUNDING with its reason, never left to look as if it is there. A direction (or any
  other per-period fact) that many readers derive from the team is a contract field before it is a
  variable. A state that extends a time limit ("a penalty in progress") names every phase it covers:
  awarded, taken, struck, until completed.
- **Check:** `uv run pytest tests/test_half_time.py` (each fails on main); the 90-minute sweep in
  the pull request: the half-time whistle in every match, the second-half kick-off by the other
  team, nothing in play across it, the contract met.

### 190. A test that reads its constant back cannot pin it
- **What happened:** the foul pose asserted `foul_fall_deg(...) == FALL_DOWN_DEG` and `peak >= 80`.
  A lie of 80° left both green, and so did rewriting the pose times, because the test added those
  constants up and compared the curve to them. The planted clips sat 0.4 s and 1.6 s from the
  restart, so a floor of 0.5 s and a floor of 1.5 s both passed.
- **Rule:** an expected output that pins a design value is the number that design produces, written
  out. A test that reads the constant moves with the bug. Lesson 36 is the other half: an input
  that has to sit beside a threshold is derived from that threshold. A bound is planted on a case
  the looser value lets through, and the tighter value does not.
- **Check:** `tests/test_fouls.py` and the P18 tests in `tests/test_validate.py`. A lie of 80°, a
  pose time rewritten, and a floor of 0.5 s each fail one of them.

### 191. A live output named like an answer-key file looks like a truth read
- **What happened:** the first draft of the live detection job (`ninety/vision/live_job.py`) wrote
  its detected events to `events.jsonl`, the name of the answer key's event file. The live-path
  checks went red: the static one found the name in the code, and the runtime one saw the job open
  a file by that name. Nothing read ground truth, but a reader of the output folder, or a later
  packer, could not tell detected events from true ones. Separately, `detect.frame_rows` falls
  back to the labelled frame file when a clip has no labels-free index, so a job handed a whole
  rendered clip would have read it.
- **Rule:** live outputs never take an answer-key file name (detected events are `detected.jsonl`).
  A job on the live path takes an allow-list of inputs (the index and the images) and refuses
  anything else before a model loads, rather than trusting a fallback not to run.
- **Check:** `tests/test_vision_live_path.py` lists `live_job.py` among the live modules;
  `tests/test_vision_live_job.py::test_a_clip_folder_holding_anything_else_is_refused_before_the_model_loads`
  (each answer-key file planted), and `::test_a_clean_clip_runs_the_whole_live_path_and_opens_no_truth`.

### 192. A seal that matches a file by where it sits misses the same file one folder down
- **What happened:** the render job sealed the answer key by name and place: `frames.jsonl` and
  `events.jsonl` went to the private `truth` container only when they sat at the top of the clip
  folder (`f.parent == clip_dir` in `ninety/render/job.py`). The tactical views write a complete
  clip under `views/tac-l/` and `views/tac-r/`, answer key included, so the first Azure render
  with views would have put true positions, boxes and events in the readable `renders` container,
  next to the images vision reads. The plan for the views caught it before any render ran.
  The same review found the job's failure reports going to `renders` too: a report's contract
  messages quote true events and positions.
- **Rule:** a file is answer key by what it is, wherever it sits: the seal matches the name at any
  depth, and anything built from the key (a check report) is sealed with it. A change that adds a
  folder to a clip plants that folder's answer key in the seal's tests.
- **Check:** `tests/test_render_job.py::test_a_views_answer_key_is_sealed_with_the_clips` (fails
  on the old seal), and `infra/check_truth_sealed.py` (CI), which runs the job's own `upload_dir`
  on a planted clip with views and fails if a `frames.jsonl` or `events.jsonl` reaches `renders`
  (`tests/test_truth_sealed.py::test_a_seal_that_matches_only_the_clips_top_level_is_caught`).

### 194. An allow-list of a folder's top level lets anything through one level down
- **What happened:** the live detection job refused an input folder holding anything but
  `index.jsonl` and `images/`, but it checked only the folder's own entries, and inside `images/`
  it looked only at `*.jpg`. A `frames.jsonl` placed in `images/` passed the check, and so would a
  whole rendered clip nested there. Found while adding the tactical camera's `views/<name>/`
  layout, which made the job look one level deeper and asked what else could sit there.
- **Rule:** an allow-list of inputs is checked over the whole tree, every file and folder at every
  depth: what is not named is refused. A new level of layout (views, tiles) gets its own planted
  answer-key files at each depth it adds.
- **Check:** `tests/test_vision_live_job.py::test_an_answer_key_file_anywhere_in_a_views_clip_is_refused_before_the_model_loads`
  (each answer-key file planted at the clip, in `views/`, in a view, in its `images/` and in a
  folder under it) and `::test_a_planted_frame_file_in_a_single_clip_s_images_is_refused`.

### 196. A new file is written only to a path nothing holds yet
- **What happened:** the team-shape tests were written to `tests/test_shape.py`, a name that sounded
  free. It held the engine's attacking-shape tests (O6, O7), 129 lines, and the write replaced them
  without a warning: the editor said "updated", not "created". The suite still passed, because a
  deleted test cannot fail. It was caught only because `git status` showed the file as modified
  (`M`) where a new one shows `??`.
- **Rule:** before writing a file meant to be new, check that its path is not tracked
  (`git ls-files <path>` prints nothing). Name a module's tests after the module's own words
  (`test_team_shape.py` for `ninety/intel/shape.py`, whose subject is the team's shape), and read
  `git status --short` before every commit: a file you meant to create must show `??`.
- **Check:** `git diff --stat origin/main -- tests/test_shape.py` is empty on this branch; the shape
  tests are in `tests/test_team_shape.py`.

### 203. CI built the image with a stand-in, so the real pin was never tried
- **What happened:** the demo image downloads its Replay bundle from a release asset pinned by URL
  and SHA-256 in the Dockerfile. CI's image job builds with a fixture bundle instead, so it stayed
  green while the Dockerfile still pinned a bundle that had been superseded and never published.
  Merging would have started a deploy whose build fails on a 404. The same review found the
  passcode gate checked HTTP requests only: a WebSocket handshake behind it went through unchecked.
- **Rule:** when CI substitutes an input for speed or isolation, it still checks the real one
  exists and is what the pin says. A gate covers every kind of connection that can reach what it
  guards, and its test tries each kind.
- **Check:** the CI `image` job's step "The Dockerfile's pinned Replay bundle exists and matches its
  hash"; `tests/test_api_site.py::test_a_websocket_behind_the_gate_needs_the_key_too` fails with the
  WebSocket branch of `RequireKey` removed.

### 205. A spring that trails its target is fed where the target will be, not where it is
- **What happened:** #220 changed how keepers play, and two broadcast camera tests failed on
  held-out seeds the new play reached. On seed 43 a long ball (17 to 20 m/s, 7 m up) left the side
  of the picture: the gantry's aim is a spring that trails a target moving at the ball's pace by
  `pan_lag_s`, about 14 m at 0.83 s. When the ball and where it would be a lag on did not fit one
  shot, the director aimed at the ball itself, so the picture ran a lag behind it. On seed 53 a free
  kick scored 0.44 s after it was taken; the goal started the low angle at once, over the hold the
  edit cut had just set, so the restart's shot lasted 2.4 s.
- **Rule:** a follow with a known lag is aimed at where the followed thing will be after that lag.
  An edit cut is a change of shot: no rule, a goal included, starts another within `CUT_HOLD_S`
  of it.
- **Check:** `tests/test_render_camera.py::test_a_long_ball_stays_in_the_picture_across_it` and
  `::test_a_goal_soon_after_the_restart_waits_for_the_edits_hold` both fail on the old camera. The
  held-out framing (`test_the_gantry_frames_the_play_with_the_pitch_filling_the_picture`) holds
  on main and with #220 merged.

### 163. A rule every writer follows goes into every writer's instructions
- **What happened:** the live Personalizer evaluation (agents-live 39514003721) aired its casual
  persona in only 12 of 20 claims. For a claim at 00:03 the model wrote "At 3 seconds" (in Spanish
  "A los 3 segundos"), turning the clock into plain words as "no jargon" seemed to ask. The re-check
  dropped every one, as it should, since the claim's clock is a number to keep. The Analyst,
  Tactician and Challenger all carry the one-clock rule (lesson 33); the Personalizer's
  instructions never did. On the live path each drop then read "no translation", which pointed at
  the translator rather than the model.
- **Rule:** a rule the code checks on every writer's text is stated in every writer's instructions,
  including a persona's style line ("plain words go around the claim's facts, never in place of
  them"). A fix to model behaviour is measured on the model before publishing: here, unpublished,
  6 of 24 variants dropped with the old wording and 0 of 24 with the new. A hold says which check
  made it.
- **Check:** `tests/test_personalizer.py::test_the_instructions_keep_the_claim_s_clock_for_every_persona`;
  `tests/test_personalizer_live.py::test_a_variant_the_personalizer_s_re_check_replaced_is_held_with_its_reason`.

### 212. A tolerance converted to pixels for one camera is wrong for the next
- **What happened:** the feet-in-box check (GROUNDING V6) allows 0.45 m between a player's tracked
  ground point and the bottom of his box. It converted that to pixels as box height / 1.8, a
  scale that holds for a camera looking across the pitch. On a touch, the renderer draws the foot
  at the ball, up to about 0.9 m out. From the broadcast gantry, about 25 degrees down, a reach
  toward the lens moved the box bottom only about 0.42 m in that scale, so the check never failed.
  From the tactical lens, 35 to 40 degrees down, the same reach is about 0.65 to 0.75 m. Dataset
  tactical lost training clips 70 and 79, and possibly test clip 900004, to frames whose drawing
  was right.
- **Rule:** a tolerance stated in metres is measured in metres, through the frame's own camera
  matrix, never with a pixel scale fitted to one camera. An allowance for a real motion is bounded
  by the drawing's own limit (here the leg's reach), so it cannot excuse a drawing beyond it.
- **Check:** the V6 high-lens tests in `tests/test_render_checks.py`.
  - A 1.0 m reach to a touched ball passes, though the side-on slack alone fails it.
  - These all fail:
    - the same foot with no touch;
    - a 2.5 m "reach";
    - a 0.3 m touch with a 1.0 m box;
    - a floating body;
    - a box moved sideways;
    - a chest or thigh touch;
    - rows far from the touch, or after an edit cut.
  - Fourteen mutations each turn a test red; one more is equivalent.
  - Two independent reviews, both cited in the PR, found holes in the earlier drafts:
    - the first draft's ground disc excused floating and sideways boxes and spilled across cuts;
    - the second still let a body rise on a touch away from the camera.
    The rule now only extends the bottom down the picture, toward the foot drawn at the ball.


### 217. The demo runs the system the pitch describes
- **What happened:** the pitch and the challenge map describe a multi-agent graph (an Analyst picks
  moments, a Tactician explains, a Challenger offers another reading, the fact-checking agent sends
  wrong claims back), and the ablation measured it. But `ninety-e2e`, which builds the bundle the
  viewer and the video show, ran the single Analyst -> fact-checker slice. A judge watching the
  demo would have seen a different system from the one the README claims. The audit found it by
  reading `ninety/e2e.py`, not the docs. The graph also checked a Challenger's reading after the
  Tactician's claim was already verified, and rewrote it when it failed: three model calls in the
  committed recording spent on a claim that could not air.
- **Rule:** the path that makes the demo is the path the claims describe; a fallback is named in
  the bundle and the trace whenever it ran. A check whose outcome cannot change what airs is not
  run.
- **Check:** `tests/test_e2e.py::test_the_claim_is_about_the_shot_and_carries_its_numbers` asserts
  the bundle's trace has the graph's roles in order; `::test_a_minute_the_graph_fails_on_falls_back_to_the_single_analyst`
  and `tests/test_workflow.py::test_a_wrong_alternative_after_a_verified_claim_costs_no_rewrite`.

### 218. A confidence the agents never see protects nothing
- **What happened:** detected events carried `team_confidence`, how firmly the side was told from
  the kit, and the evaluation reported it. But `facts.compact`, which shapes every event an agent
  or the fact-checker reads, dropped it. A claim naming the wrong team passed every check whenever
  the detector had the side wrong (5 of 16 validation passes), because the evidence agreed with the
  claim and nothing said how unsure that evidence was. Lesson 146 is the same failure for names.
- **Rule:** an uncertainty the detector measures travels with the fact to the fact-checker. A claim
  that rests on it is held below a threshold set from the measured reliability, and the threshold's
  source and n are written beside it.
- **Check:** `tests/test_confidence_gate.py::test_the_agents_see_how_firmly_the_side_was_told` and
  `::test_a_claim_naming_a_team_on_an_unsure_side_is_held_not_rejected` fail if `compact` drops the
  field or the gate ignores it.

### 208. A script inside YAML is code: parse it before a run is approved
- **What happened:** resolving a merge conflict in `agents-live.yml`, two new `case` branches were
  joined and the `;;` closing one was lost. The YAML still loaded and the merge was checked only
  with a YAML parser, so the defect reached a live run: Kian approved it, it signed in to Azure,
  and then failed on `syntax error near unexpected token ')'` without publishing anything.
- **Rule:** a change to a workflow's `run:` block is checked as the shell it is, not only as YAML.
  An approval for a live run is spent only on a script that parses.
- **Check:** `tests/test_workflows.py` runs `bash -n` on every bash `run:` step of every workflow;
  it fails on the shipped `agents-live.yml` (`7e76d15`) and passes on the fixed one.

### 216. Evidence says which agent produced it, or it rots without a sound
- **What happened:** the agents' committed reports named a published version (`ninety-judge:1`) in
  their prose, and nothing compared it with the code. The Judge moved to version 4, the
  Personalizer to version 2, and `fact-checker.md`, `personalizer.md` and the planted-claim set
  kept describing agents that no longer ran; the nightly that re-measured the Judge wrote only to
  `runs/eval/`, so its numbers never reached a file anyone reviews. The published 136/136 also
  counted 9 false claims held back by Judge service errors as catches, and `analyst.md` graded
  drafts against this commit's match after the Analyst had read the deployed one (lesson 90).
- **Rule:** every agent report and replay records each agent's version and `definition_sha` as the
  run wrote it, and CI compares them with the code: a mismatch fails unless the file is listed as
  stale with why and the run that replaces it, and the list fails when an entry is fresh again.
  A file from before fingerprints is read through the registry's history, never given an invented
  fingerprint, and an agent a file names without a definition is unknown, never fresh. A hold the
  service caused is counted apart from a rejection a check made, and a run the model mostly did
  not answer writes no report. A nightly lands as a pull request of dated, unedited reports.
- **Check:** `tests/test_evidence_fresh.py` (a planted fingerprint in a copied report, replay or
  Markdown line fails; an unknown version fails; a listing without a reason, or for a fresh file,
  fails, a listing whose stale agents differ fails); `tests/test_live_eval_outage.py` (an
  all-service-error run writes nothing); `tests/test_nightly.py` (a report without fingerprints
  is not archived; the workflow's writing job has no Azure sign-in and opens a PR against main).
  The first version passed a report with an empty definitions line as fresh; review caught it, and
  23 mutants of the rules are now each killed by a test.

### 193. Score a claimed tie at the answer before adding an input to break it
- **What happened:** building the fixed-camera fit, I reasoned that the pitch markings are
  symmetric about halfway, so a lens and its mirror across halfway would see the same picture, and
  made the lens's side a required input to break the tie. The test written to prove the tie
  failed: the mirror lens sees the picture flipped left to right, which no camera without that
  flip draws, so the two fit 0.0 px and 68 px apart. The input would have been a needless
  dependency every caller had to get right. The same fit, freed in all six parameters, stalled a
  metre from the true camera at 2.6 times its cost; the objective was right (lesson 97), the step
  was not.
- **Rule:** a claimed ambiguity is checked by scoring both candidates at the answer, as an
  objective is (lesson 97), before any interface is built around it. A reflection is not a camera
  move.
- **Check:** `tests/test_vision_pitch_fixed.py::test_a_lens_and_its_mirror_across_halfway_do_not_tie`
  (the true lens fits, its mirror does not, the flipped picture does);
  `::test_the_compass_search_walks_on_where_the_free_step_stalls` fails with the compass search
  removed from `pitch.settle` (a half-size scene did not stall, so the stalled view is a fixture).

### 199. A role named afresh every look is a role nobody holds
- **What happened:** the team brain named its presser and cover afresh at every look, twice a
  second, from who could reach the ball soonest, and the cover was simply the second soonest to the
  ball. Two players about as near swapped the job, and the cover often came from beyond the ball:
  at shots from 25 to 40 m he had held the job a median 0.7 s and stood a median 9.2 m from
  his place, 8 m goal-side of the ball. #160 found the same churn in the chase, lesson 174 at
  restarts.
- **Rule:** a job answers a piece of play and lasts as long as it does: the presser and cover are
  held while the same carrier has the ball or the same kick is in flight, and named again when that
  changes or the man cannot do the job. The cover is whoever reaches the cover's place soonest, not
  the next man to the ball. When a role keeps changing hands, check how long its holder has held it
  before tuning where he stands; and check that the measure the fix was for moved: here the cover held his job longer (0.7 to 1.0 s) and stood nearer his place (9.2 to 5.4 m), yet the share of long shots with nobody in the triangle to the posts did not move (84% to 87%), so the churn was real but was not what left shots unscreened.
- **Check:** `tests/test_press_hold.py`; in the pull request, the cover's tenure and distance from
  his place at long shots, and the share of shots with nobody in the triangle to the posts, held out
  against the tracking-data share in GROUNDING D3.

### 201. A rule written for one phase of play leaves the other phase without it
- **What happened:** the length cap (46 m, deepest outfield player to most advanced) was written for
  the team on the ball, after it camped in its own box. The team without the ball had no cap, so a
  high press up to a goal kick stood its forwards at the ball and its line at its block, 49 m apart
  (77 m with a low line), with the midfield 12 m ahead of the line wherever the ball was, behind
  the play once the ball came inside the block.
- **Rule:** when a shape rule is fixed for one phase (in possession, out of possession, restarts),
  ask whether the other phases need the same rule, and test each phase.
- **Check:** `tests/test_block_length.py`; in the pull request, the team's length while the
  opponent waits to take a goal kick.

### 198. An action that commits the body is weighed against the cheaper one, at the moment it must start, and tested on a ball that moves
- **What happened:** Kian saw the keeper "dive at the completely wrong time". The engine dived as soon
  as he had reacted to any shot crossing beyond his hands: at balls a few centimetres out that a step
  would have reached (3 of 11 measured dives travelled 9 cm or less, then he lay down for 0.8 s), and
  at long shots still up to 1.7 s away, so he landed before the ball arrived. Watching the first clip of
  the fix then showed a third cause nobody had listed: he dived at a shot heading 12 m wide, because
  nothing asked whether the ball was going in. The dive tests froze the
  ball and moved only the clock, so a launch "on reacting" was the only one they could see, and one
  of them (a high ball needs a longer dive) held only because the frozen ball made his arms look
  fully stretched at an arrival that, in flight, comes 0.35 s earlier.
- **Rule:** an action that puts a player on the ground (a dive, a slide) is chosen only when the
  cheaper movement cannot do the job in the time left, judged by the engine's own reach test
  (`body.can_get_to`), and it starts no sooner than it must, judged again every frame. A test of when
  something starts lets the ball fly by its own physics, frame by frame; a test that moves the clock
  alone measures a ball that never arrives.
- **Check:** `uv run pytest tests/test_keeper_dive.py`. A ball 0.55 m beyond his hands that his legs
  get him to, and one 5.4 m wide with two seconds to run, are taken standing; main dived at both, and
  a keeper who only waits for the last moment, without asking whether his legs will do, dives at the
  first. A 1.2 m dive with time to spare is launched after he reacts and lands as the ball arrives;
  main launched it as he reacted. Removing the step test turns the first red, removing the launch
  timing turns the long-shot and run-up tests red, and removing both turns all four red;
  `test_he_does_not_dive_at_a_shot_going_wide` is red without the on-target condition, and
  `test_he_does_not_dive_at_a_shot_going_over_the_bar_within_his_reach` with a check of the posts
  alone; every shot in these tests that he should dive at, or take standing, is asserted to be going in. A clip of the
  change is watched before it is called done (lesson 107). The
  dive tests in `tests/test_engine_rules.py` fly the shot (`_until_he_dives`).

### 197. A rule the renderer has to draw must be in the truth first
- **What happened:** Kian saw that a keeper never seemed to hold the ball and throw or kick it.
  The engine settled every caught ball to the keeper's feet, and he played it from there like an
  outfielder, by a ground pass or a dribble. The renderer could only draw what the truth said: a
  ball on the grass. Law 12 (six seconds in his hands, no challenge) was only half in the engine:
  nobody challenged him, but nothing held the ball in his hands.
- **Rule:** when footage looks wrong, check the engine's truth before the renderer. A caught ball
  stays at the keeper's chest (L15). He lets it go within Law 12's six seconds: by a throw to a
  team-mate in range, by a kick from his hands, or by putting it down to play with his feet. He
  chooses by the same estimate as any pass. The rate of kicks from his hands is a held-out check
  against a published count, never a target. Leaving the put-down out made him kick from his
  hands 10.6 times a match against the 0.66 published: when a held-out number is far off, look for
  an option the Laws allow that the engine lacks. And before changing an option, log what
  each release was chosen over: every kick from his hands (19 of 19 on three seeds) was the long
  clear, chosen when every pass he had was valued below zero near his own goal, so the count is
  set by the shared pass value there, not by the keeper's options. Widening his options (a throw
  as far as a ball can be thrown, a kick from his hands to any team-mate) left it unchanged.
- **Check:** `tests/test_keeper_hands.py`. Three of its tests go red when a catch does not put
  the ball in his hands. Two more are red on the first version: there a lunge already on its way
  knocked the ball out of his hands, and a drop kick took the ball from his chest to the grass in
  one frame. The held-out counts then showed the decisions: no throws, holds of about 0.7 s, and
  kicks from the hands far above the published count. The throw had only the throw-in's lofted
  way, and he released on the first look. `test_he_waits_out_the_window_while_the_team_sets` is
  red if he decides before `KEEPER_RELEASE_S`. `test_a_keepers_throw_may_roll_and_a_throw_in_stays_in_the_air`
  is red if his throw cannot roll or a throw-in can.
  `test_he_throws_no_faster_than_a_ball_can_be_thrown_and_may_kick_to_anyone` is red without the
  throw's speed limit, or if a kick from his hands can roll. The 5 s window is the design value
  written before the measurement; the 30 m split is gone. The kick count stays a check, never a target.

### 206. When two parts split a job, both read the split from one definition
- **What happened:** the free-kick wall was built to hide the goal from the near post to a third
  past its centre, its comment saying "the keeper covers the rest". The keeper never read the
  wall: he set himself on the bisector of the whole goal, as at any other moment, so he stood
  behind the middle of his own wall and left the open part to nobody. Each half was tested on its
  own, so nothing failed.
- **Rule:** when a rule hands part of a job to another (the wall and the keeper, a presser and his
  cover), the split is one function both call (`Engine.wall_cover`), and a test sets up the shared
  case and checks the second part takes what the first leaves. A comment that assigns work to
  another part names the code that does it.
- **Check:** `uv run pytest tests/test_keeper_setpiece.py`: with the wall up he stands on the
  bisector of the open part (red on main); his spots at three kicks are written out, so a change
  to the wall's cover moves them; he keeps the cover while the set ball waits and drops it after
  the kick; at his own side's free kick nothing changes.
### 204. A pose that names the action's mechanics, not its kind, draws one action as another
- **What happened:** #216 gave keepers a throw from the hands: a roll is bowled, the ball brought
  down in his hands to the grass and released from there. The engine named every wind-up `strike`,
  so the renderer drew a kicking leg winding up and the ball meeting his boot. Through the 4.7 s
  he held the ball before it his pose read `stand`, so nothing put his hands on it either. The
  engine knew both (`windup[3] == "bowl"`, `held_by`) and exported neither.
- **Rule:** the pose the engine exports names what the body does with the ball, from the engine's
  own state; the renderer draws that name and never guesses it from where the ball goes next.
- **Check:** `tests/test_render_motion.py::test_a_bowled_ball_is_brought_down_in_both_hands_with_no_kick`
  fails on the old renderer (the hold ends before the bowl). A clip of an engine that names no bowl
  renders byte-identical (seed 122 at main, frames, events, meta and images).

### 227. A confidence is compared only with a threshold measured on the same reading
- **What happened:** active perception re-runs the event detector on another camera, or on a 3 s
  window, to re-read a side the fact-checker holds. The first version let any look re-read the side.
  On the M1 clip a 3 s window read the side of v00003, a false detection (a shot read as a pass), at
  1.0; the whole clip had read it at 0.529. A side vote over a few frames is more one-sided than the
  clip's, whoever is right, and the 0.96 threshold was measured on whole-clip votes. The look would
  have aired a team claim on an event that never happened. The evaluation's own fixture test caught
  it before any number was published. The second version still let a tactical lens's whole-clip vote
  re-read the side, although 0.96 was measured on the broadcast's (the independent review caught it:
  wrong sides reach 0.994 on the lenses). Now a look never re-reads a side.
- **Rule:** a score is compared only with a threshold measured on the same kind of reading. A
  shorter window, another camera or another model is a new reading, and needs its own measurement
  before it can open a gate. Until then it may only confirm what does not depend on it (here, that
  the event was seen).
- **Check:** `tests/test_perceive.py::test_a_look_never_re_reads_a_side_so_a_team_claim_on_an_unsure_side_stays_held`
  and `::test_a_real_camera_look_runs_inside_the_workflow`.

### 215. A detector tuned on one look is re-checked on the look the renderer draws now
- **What happened:** the camera fit's marking detector (`ninety/vision/pitch.py`, `line_mask`) was
  set on renders without sensor grain. The renderer later added grain (`params.noise`). On dataset
  v2's validation clips only 0.39 of the marked pixels then lay on a marking, the fitted gantry
  sat on its search grid's corners 10 to 20 m away, and no frame passed the markings test.
  Nothing placed anything, and it read at first as a stale height band. No check ran the fit on a
  current render: its tests draw clean scenes, and the scored observations were older looks'.
- **Rule:** when the renderer's look changes, every vision stage tuned on pixels is re-measured on
  a clip of the new look against its true camera before any number from it is read. A stage's
  tests plant the look's own noise, at the renderer's own amplitude, not a clean image.
- **Check:** `tests/test_vision_pitch.py::test_sensor_grain_is_not_a_marking_and_a_far_line_with_a_gap_still_is`
  (grain at params.noise's top, 0.02) fails with the blur removed; the before and after on
  validation clips are in `docs/eval/marking-grain.md`.

### 230. A threshold measured on one look is re-measured when the look changes, by the same rule
- **What happened:** the camera trust test's height band (0.901 to 1.002) was measured on renderer
  0.3's validation clips. On today's renders (0.5.x) the players' height ratio through a right
  camera is 1.00 to 1.11, so the band rejected every correctly fitted frame: nothing was placed on
  the pitch, and with the grain defect (lesson 215) hiding behind it, the cause looked like one
  thing when it was two.
- **Rule:** a threshold derived from rendered data carries the look it was measured on; when the
  renderer's look changes, it is re-derived by its own pre-registered rule on new validation clips
  before any number that passes through it is read, and the new value cites both.
- **Check:** `tests/test_vision_observe.py::test_the_band_is_the_committed_validation_measurement`
  holds HEIGHT_BAND to `docs/eval/band-broadcast.json` (tactical1's validation clips only), and
  `ninety/eval/band_derive.py` re-derives it.
- **And:** re-derived, the heights alone trusted a clip whose camera was 28 m wrong in every frame on
  dataset v2 (and 48.9 m on tactical1): the marking fit's own verdict is required again on the
  broadcast (gate B3, `docs/eval/gate-b3.md`), chosen on validation;
  `tests/test_vision_observe.py::test_a_whole_clip_through_a_wrong_camera_whose_markings_do_not_fit_is_never_trusted`.

### 221. A number matched by value and unit alone passes in the wrong role
- **What happened:** the insight fact-check let a sentence state any number a cited fact held,
  written with that number's unit. A planted claim "6 players against 1 player" passed when the
  true count was 5 against 1, because the fact's other number, 5 extra players, was also in
  players; "won it back 5 seconds after losing it" passed because the fact also held the 5-second
  counter-press window. Both numbers were on the fact; neither was the number the sentence said.
- **Rule:** a fact's numbers carry their role: a distinct unit where they measure different things
  (`extra players`), and a context where one unit serves two (the other side's count after
  "against", the window after "within" or "next"). A number written in a context may stand only
  for a number of that context, and a number of a context only where it is written in it. The same holds for a fact's direction: a sentence that says it went the other way (won back or not,
  lost or kept, to an open teammate or not, nobody open) is checked against the fact's own field, and the
  evaluation plants each reversal (the merge queue's review found them passing). A list of wrong phrasings fails open (a second review found 27 of 61
  paraphrases passing it), and so does a list of direction words (a third found 27 of 64 more): the
  check is closed by construction now. For a fact whose direction matters, the fact's own phrases,
  numbers, names and a short list of glue words are taken out of the sentence, and any word left
  holds it. True sentences in other words are held too; that cost is measured, not hidden. The rule
  covers only the facts it names; any other fact's direction words are left to the Judge, and the
  docs say so.
- **Check:** `uv run python -m ninety.eval.insight_claims` (the `number` and `spelled` plants on
  overloads and counter-presses are caught); `tests/test_insight_check.py` (the window said as
  the regain, the extra players said as the own count, both rejected).

### 222. A floor on how many there are can make a share impossible to reach
- **What happened:** the Insight Scout pushed a fact only when it ranked above 90% of its kind so
  far, among at least 5. Among 5, the best rank is 4 of 5, 80%, so no fact could ever be pushed
  until there were 10: the floor and the share were each sensible, and together they made the
  first cards of every match impossible. A test that expected a card found none.
- **Rule:** when a gate combines a least count and a share, check that the count can reach the
  share (a share s needs at least 1 / (1 - s) items), and set the floor from the share.
- **Check:** `ninety/agents/scout.py` `MIN_SO_FAR` is 10 for `NOTABLE` 0.9;
  `tests/test_companion_match.py::test_scout_cards_are_verified_and_spaced` plants a notable fact
  and requires its card.

### 223. A rule about who acted, tested on sentences that start with the club, rejects the ones that start with the player
- **What happened:** the insight fact-check took the first club a sentence named as the side that
  acted. Every test sentence began with the club. On the stand-in match, every true line break said
  by name, "Ben Raimble played a pass that took 6 Fenwick players out of the game", was rejected:
  the first club named was the opponents, who were counted, not acting.
- **Rule:** a rule that reads roles out of a sentence is tested on every sentence shape the writers
  produce (lesson 130): a club written straight after a number is what was counted, and the side
  is the first club named otherwise; for a line break, the counted club must be the other side.
- **Check:** `tests/test_insight_check.py` (a named passer with the counted opponents passes; the
  counted club being the passing side is rejected); `insight_claims` reports no true claim stopped.

### 228. A new test file named after a word another module already owns overwrites that module's tests
- **What happened:** adding tests for the playing-style tool (`ninety/intel/style.py`), a new file
  was written to `tests/test_style.py`, which already held the engine's team-style tests. The write
  replaced them; `git status` showed `M` where a new file shows `??`. This is lesson 196 again.
- **Rule:** before writing a test file, check that its path is free (`git ls-files tests/<name>`),
  and name a new test file after its own module's full purpose (`test_playing_style.py`), never a
  word another package also uses.
- **Check:** `git status --short tests/` after creating test files: every new file shows `??`.

### 229. Prose a number reader will check is tested through that reader
- **What happened:** the Referee's summary of Law 11 said "being in an offside position is not an
  offence by itself; it becomes one when he gets involved". The fact-checker reads number words,
  so "one" was a number no fact held, and every answer that quoted the summary was refused and fell
  back to a shorter one. A test that the summaries hold no digits passed: it read the text, not what
  the checker reads.
- **Rule:** text that the fact-checker will read (code's sentences, the Law summaries) is tested by
  running it through the checker's own reader (`factcheck.spelled_as_digits`, then `check`), not by
  a separate look at the characters.
- **Check:** `tests/test_referee_offside.py::test_the_laws_carry_no_numbers` reads each summary through
  `spelled_as_digits`; `::test_the_referee_answers_offside_from_the_reading_and_the_law` quotes them.

### 232. A voice a fan hears is chosen by listening, and the device's voice is only the fallback
- **What happened:** the phone's read-aloud spoke through the browser's `speechSynthesis`, so a fan
  heard whatever system voice their device had. On Kian's Mac that was a robotic voice he called
  creepy, in the one feature built for fans who listen instead of watch. Meanwhile we had an Azure AI
  Speech resource, and the Describer pinned a neural voice (Ryan) that nothing on the phone used.
  Nobody had chosen either voice by listening.
- **Rule:** the voice is picked by ear from samples made in the voices that could ship (Oct 23:
  all 17 British neural voices and two HD voices; Kian chose en-GB-OllieMultilingualNeural). It is
  pinned in one place (`ninety/speech/voice.py`), and every path that speaks reads it: the bundle's
  pre-generated lines, the Live route and the Describer. The phone plays the bundle's audio first,
  then the Live route, and uses the device's voice only when neither has the line.
- **Check:** `tests/test_speech.py::test_every_path_that_speaks_reads_the_one_pinned_voice`,
  `::test_the_phone_plays_the_bundles_audio_before_any_other_voice` and
  `::test_the_device_voice_is_the_last_resort_in_voice_ts`. Point voice.ts at the device's voice
  first and the second and third tests fail.

### 224. Every picture of the pitch goes through one projection, and its words follow the engine
- **What happened:** the phone's minimap drew pitch metres with its own projection, y = 0 at the
  top, while the TV picture and the viewer's radar put the y = 0 touchline at the bottom, where the
  broadcast camera stands. The phone showed the match upside down beside the screen it follows,
  and its heat map and wind map with it. Its "left" and "right" flank words had been written to
  match that drawing, so they were wrong too: the engine starts a home left-back at 0.85 of the
  width, which the phone called the right. Its tests tapped dots with the same y-down formula, so
  they agreed with the bug.
- **Rule:** every drawing of the pitch on any screen (radar, heat map, wind map, answer pictures)
  goes through `web/viewer/src/radar.ts`'s `projection`, and taps are hit-tested through it. Words
  for a place on the pitch are grounded in the engine's own coordinates, not in a drawing. A test
  that finds a dot asks the page where it drew it, and checks which way up that is.
- **Check:** `tests/test_phone_companion.py::test_the_radar_is_drawn_the_way_up_the_tv_shows_it_and_a_tap_finds_the_dot`
  (a player 20 m from the near touchline is below halfway); `tests/test_phone.py`'s tap test asks
  `ninetyPhone.screenOf` and asserts the same.

### 225. A second screen runs on the first screen's clock, cuts included
- **What happened:** the viewer sent the phone `t_start` plus the video's time, which is the match
  time only while the clip has no cut; a condensed match is all cuts. Between messages the phone
  ran its clock on in match time, so even with the right message it slid into the stretch of the
  match the broadcast skipped, drawing the radar where the video never was for up to a second.
- **Rule:** one clock for every screen (lesson 33): the big screen sends match time from the same
  function the graphics use, and the phone reads the bundle's cuts and runs on in video time
  between messages, as the video does.
- **Check:** `tests/test_match_mode.py::test_the_big_screen_pairs_at_once_and_sends_the_phone_match_time_across_the_cut`
  fails with `t_start + video time`; `tests/test_phone_companion.py::test_the_phone_clock_jumps_the_cut_with_the_video_and_never_shows_the_gap`
  fails with the cuts dropped from `LaptopClock.time`.

### 236. A late joiner is sent the state as it stands now, not as it was last stored
- **What happened:** the companion relay stored the big screen's once-a-second clock and replayed
  it unchanged to a phone that joined late. A phone could start up to a second behind the screen it
  follows until the next message; the phone clock test failed two runs in three, and the mock relay
  did the same.
- **Rule:** state that runs on by itself (a playing clock) is advanced by how long it was held
  before it is replayed; state that does not (a paused clock, a focus) is replayed as stored. The
  mock relay asks the laptop for its clock as it stands now, as the server computes it.
- **Check:** `tests/test_api_companion.py::test_a_late_phone_gets_a_playing_clock_as_it_stands_now`
  (fails with the stored message replayed); `tests/test_phone.py::test_the_phone_clock_stays_within_tolerance_of_the_laptop`.

### 237. Tests and screenshot runs never speak aloud
- **What happened:** browser tests and screenshot scripts turned read-aloud on and the headless
  browser spoke with the Mac's system voice; Kian heard it from a test run.
- **Rule:** every voice the screens use goes through one function (`web/viewer/src/speech.ts`,
  `speakAloud`), which under automation (`navigator.webdriver`) records the line instead of
  speaking it; recorded audio and tones stay silent too. Read-aloud is off until a fan turns it on.
- **Check:** `tests/test_phone_companion.py::test_read_aloud_is_off_until_tapped_and_an_automated_browser_never_speaks`
  (fails if `speakAloud` calls `speechSynthesis` under webdriver).

### 234. A foul that only the data knows about is not a foul on screen
- **What happened:** Kian watched a test clip with a foul in it and could not tell a foul had
  happened. The engine had stopped play: within 0.5 s of each whistle on seed 7, at most one of 22
  players was still running. But the picture showed players drifting to a stop, no whistle and no
  one reacting. The fall itself (#223) was not in that clip's render yet.
- **Rule:** an event a viewer must follow gets a cue they can see or hear, drawn from the engine's
  own record of it (the foul's frame, its fouler and the fouled player, their positions), never by
  moving anyone. A cue that would contradict a truth field, such as turning a body away from its
  `heading`, is drawn where the truth says nothing: here the head turns, and the hand goes up.
- **Check:**
  - `tests/test_render_fouls.py`: the reactions start at the foul frame, are gone after REACT_S,
    reach the three nearest team-mates and not the fouled man, and the head turns toward him;
    nothing happens without a foul.
  - `tests/test_render_mesh.py`: the page and Python draw the raised hand and the turned head the
    same way, within 1.5 cm on every marker.
  - A clip with no foul renders byte-identical to the renderer before this change, given the same
    two team codes. The rename to LON and LIS changes the scorebug text in every render with
    graphics on. Labels and `frames.jsonl` are unchanged. The frozen test sets recorded the old
    codes in their params, so re-rendering one differs in the scorebug only.

### 238. A model's reply is read as the first object it writes, and the live eval keeps what it parsed
- **What happened:** the published match Companion (v2) answered a plan step with the plan and then
  kept going: an "answer" step of its own, with facts and fact ids it made up, in the same reply. The
  plan parser took everything from the first `{` to the last `}`, which is not one JSON object, so
  every such plan failed. In the first live run (40066697726) 22 of 32 plans were unparseable and 27
  of 32 answers fell back to code's checked answer. The fan saw only verified text, and the stand-in
  tests passed, because every scripted reply was exactly one object.
- **Rule:** a model's plan is the first JSON object in its reply (`companion_match.first_object`), and
  nothing after it is read, so the made-up facts never reach the tools. The eval reads plans through
  the same function as the service. A scripted reply in a test includes what the live model actually
  sent, not only the ideal shape.
- **Check:** `tests/test_companion_match.py::test_a_plan_followed_by_an_answer_the_model_made_up_is_read_as_the_plan_only`
  and `::test_the_eval_reads_a_plan_as_the_service_does` fail when the parse goes back to first `{` to
  last `}`.

### 239. A sentence template is tested through the checker it must pass, and a fallback row answers only what it is about
- **What happened:** the team-sheet sentence ("X plays left-back for London Athletic, by the team
  sheet") had never passed the fact-checker. Its name gate counted only the tracked players the facts
  were about, not the sheet row being cited. So no "who plays where" question was ever answered, and
  the router's lineup score (2/4) measured routing to a tool that could not answer. Meanwhile "who is
  the best player?" routed to the sheet as well, and with no confident leader the first sheet row
  answered: the goalkeeper. On the phone, the answer's headline was taken from the picture's number
  ("6 moves") rather than from what the fan asked.
- **Rule:** every code template is run through `verify` on the stand-in in a test, not only read. A
  cited sheet row vouches for its own name, position and club, and a name said with another row's
  position is refused. A sheet row answers only a question that names a position. The answer carries
  a `headline` computed by code from the question's kind: a name (or the role, or the club) for who,
  the number with its unit for how many, the place for where; the supporting number stays in the
  sentence.
- **Check:** `tests/test_companion_match.py::test_who_plays_a_position_is_answered_from_that_row_of_the_sheet`,
  `::test_a_sheet_row_says_only_its_own_name_position_and_club`,
  `::test_who_is_best_is_never_answered_with_a_name_off_the_sheet` and
  `::test_every_held_out_answer_is_headed_by_what_its_question_asks`. Each fails when its rule is
  mutated (eleven mutations, all caught).

### 235. Every live_job mode gets an end-to-end test on a real clip of its camera type
- **What happened:** `observe` gained `fixed=True` for the tactical camera's lenses, but the views
  mode of `ninety/vision/live_job.py` never passed it. Each lens was searched frame by frame as the
  broadcast's moving gantry, and the fit failed on every frame: on validation seed108, camera OK on
  0 of 250 frames and no player placed. Its unit tests passed because they ran on a synthetic clip
  drawn through a broadcast camera, which the broadcast search fits. A phone fixture built from
  views runs on main (12–17 players, no events) carried the defect downstream.
- **Rule:** any live_job mode (broadcast, views, and any added later) has an end-to-end test on a
  real rendered clip of that camera type, at the renderer's own image quality. The test asserts a
  non-zero placement rate, not only that the run finished.
- **Check:** `tests/test_vision_live_job.py::test_each_view_is_placed_as_a_fixed_lens_and_the_broadcast_is_not`
  (the flag), and `test_a_real_tactical_clip_places_players_from_every_view` and
  `test_a_real_broadcast_clip_places_players` in the same file, on two frames of each camera
  (`tests/fixtures/tactical-seed108`, `broadcast-seed108`). The tactical test fails without the fix.

### 219. A number reader must read every language and every unit our writers produce, and bind a number to its player
- **What happened:** an audit of the fact-checker's code half found four forms it still let
  through, each re-verified on main with a planted claim. Spanish, which the Personalizer writes and
  `check` re-checks, was not read at all: "cincuenta km/h" and "treinta y uno" were no numbers, and
  "50 kilómetros por hora" or "minuto 50" read as a bare 50, which any cited distance let through.
  Ordinals in words ("his seventh pass", "the ninth minute") were missed although lesson 130 fixed
  "7th". A number in a unit we never publish passed when its digits matched a field ("50 yards" for
  a 50 m pass, "31 mph" for 31 km/h), and so did "a 2-metre pass" (read bare, passed by the minute).
  And a number only had to be in some cited event: "h7's 30 m pass" passed when h7's was 12 m and
  30 m was h4's. The review of the first fix found it too loose and too strict at once: "his" bound
  to a player named after it, only the first number after a verb was bound, and Spanish idioms
  ("se va de uno", "cien por cien", "con los dos pies") were read as numbers that main had passed.
- **Rule:** the reader reads every language a writer is told to use (number words, ordinals and
  units), refuses a unit no fact of ours is in rather than converting it, and checks a distance or
  speed the sentence gives to one player against that player's own cited events. Words that are no
  number stay words in every language ("first time", "the final third", "a two-on-one", "el once
  inicial", "uno contra uno", "a mil por hora", English "once"), and a pitch marking ("the six-yard
  box") is a name, not a measurement. A binding starts only at a named form, never reaches forward
  for its player, holds every distance and speed up to the next player or the end of the clause,
  and says what it does not cover; any other wording falls back to the check against all cited
  events.
- **Check:** `tests/test_factcheck.py::test_a_planted_spanish_number_is_rejected`,
  `::test_an_ordinal_in_words_must_be_in_the_evidence`,
  `::test_a_number_in_a_unit_we_do_not_publish_is_rejected`,
  `::test_a_number_bound_to_a_player_must_be_from_his_cited_event` fail on the old check, and each
  has a true-form twin that passes; `tests/test_personalizer.py` drops each form from a Spanish
  variant. Measured for false rejections: the verdicts on every recorded claim with its evidence in
  `replays/`, `docs/eval/` and the fixtures are unchanged from main's check on the same texts.

### 240. A measurement is re-run on the engine the demo uses, and a fixed sentence in a report becomes a computed one
- **What happened:** the insight, roles and team-distance evaluations ran on runs/u7, seed11 and
  c21, simulated on Oct 13–14, before the engine fixes. The u7 run logged 22 of 265 passes from a
  player to himself; the validator's C8 now rejects these. Re-run on the freeze engine (65247ba3:
  the demo's seed 8076 and seeds 7, 11 and 21), the fact-checker missed 9 planted false claims and
  stopped 16 true ones that u7 never produced:
  - a back line's change and height, both in metres, were not bound to their roles ("pushed up
    21 m, to 21 m");
  - one name could be said as both players of a one-two;
  - a regain that led to a shot was stopped by the counter-press's words, and its reversal
    ("never won the ball back and had a shot") passed.

  Name precision fell from 0.999 to 0.939–0.975, and with full tracking team distance read
  0.967–1.204 of the truth, not "within a few percent". A step rule fixed before measuring found no
  step that tames the error, so the phone now labels the distance with its measured worst over
  every freeze match graded (±21%, the demo's own match; one held-out match alone gave ±15%, narrower
  than the demo's, caught in review). Two report texts were fixed strings: the
  roles report named runs/u7 whatever it ran on, and the team-distance report kept its "few
  percent". Both stayed true-sounding after the numbers changed.
- **Rule:** an evaluation quoted in the docs runs on a match simulated at the engine the demo uses,
  and its report states the runs it read and the range it measured, computed, never typed. When the
  engine moves, the evaluations are re-run before their numbers are quoted.
- **Check:** `docs/eval/roles.md`, `team-distance.md` and `insight-claims.md` name their runs (the
  `f*-65247ba3` folders). `tests/test_insight_check.py::test_a_line_moves_by_its_change_to_its_height_never_the_other_way_round`,
  `::test_one_name_said_as_both_players_of_a_one_two_is_refused` and
  `::test_a_regain_that_led_to_a_shot_is_said_in_its_own_words_and_never_reversed` fail when their
  rule is mutated.

### 241. A name is one player at a time
- **What happened:** the players ranking listed one starter's name twice: two tracks were both
  assigned his role and both passed the name gate. The first rule proposed, "if two tracks claim a
  name, neither gets it", named nobody on the stand-in: the tracker breaks every player into
  several tracks over a match, so every name had several claimants (742 named tracks became 0).
- **Rule:** tracks that claim one name and are never on the pitch together are one player in
  pieces, and keep it; two that are there at the same time lose it and fall back to their role
  (`roles.one_track_per_name`). The ranking merges one named player's pieces into one row. On the
  freeze stand-in (gates 0.203) this keeps 612 of 742 names and lifts their precision from 0.930 to
  0.977; 38 of the 130 names it removes were wrong.
- **Check:** `tests/test_insights.py::test_a_name_binds_to_one_player_at_a_time` and
  `tests/test_companion_match.py::test_one_players_pieces_of_track_are_one_row_of_the_ranking` fail
  when the overlap test or the merge is mutated.

### 242. On a machine other sessions share, stop your own processes by id, never by a pattern
- **What happened:** three sessions simulated and rendered on one laptop at once. To stop its own
  background wait loops, one session ran `pkill -f "until \["`. The pattern matches every process
  whose command line holds `until [`, so the other sessions' wait loops alive then were killed
  too, each reporting a failure (exit 144) that looked like its own job had failed.
- **Rule:** stop a process you started by the id you were given when it started (the task id, or
  `$!` saved at launch), or by a pattern that only your own command can match (its seed range, its
  output folder). Before any `pkill -f`, run `pgrep -fl` with the same pattern and read every line.
- **Check:** `pgrep -fl '<pattern>'` lists only processes whose command lines name your own seeds or
  folders; if it lists anything else, narrow the pattern or use the ids.

### 243. An id that is a place in an order moves when anything is added before it
- **What happened:** adding possession changes to the detected events regenerated the M1 clip's
  fixture, and every event after the first change moved up one id. The failure table pinned its
  evidence pass as `SIDE = "v00005"`, "a second completed pass in the minute": that id became the
  out of play, which the agents' view drops, and every CI shard failed with `KeyError: 'v00005'`.
  The PR's local run covered the vision tests, not the workflow tests that read the same fixture.
- **Rule:** an event is chosen by what it is (its type, outcome, minute, order among its kind),
  never by a detected id, which is only its place in the clip. When a fixture is regenerated,
  every reader of it is found (`grep -rn <fixture name>` and the modules those tests call) and
  their tests are run in the same change (lesson 91).
- **Check:** `tests/test_workflow_failures.py::test_the_ground_picks_its_passes_by_what_they_are_not_by_id`
  plants an event before the side pass and still finds the passes at 66.88 s and 73.72 s; with
  the old fixed ids put back, the file fails to collect.
- **Again, the next day:** `ninety/eval/describe_eval.py` (#268, merged after the fixture changed)
  read which detections are real from event-report-v2's pairs, whose ids are the older detector's.
  Its own guard refused them (`v00005 is not the event it matched`), as it should. The fix grades
  the current detector (`docs/eval/event-report-v3.json`, written by `possession_report` beside its
  report, passes checked equal to v2) and reads that; the guard is unchanged. A merge from main is
  where a new reader of a changed fixture arrives: rerun every test that reads it after each one.

### 244. A camera fitted from symmetric markings has a twin; and a band measured on one look misjudges another
- **What happened:** the broadcast fit was made to follow camera cuts (`observe --cuts`). On the
  test set every cut was found, and the old 46 m-wrong frames of seed 900003 went. But that clip's
  last shot is a reverse angle (a camera in the far stand). Law 1's markings are the same after a
  half turn about the centre spot, so the near gantry turned that way draws identical lines. The fit
  found that twin, the markings and the players' heights both passed, and 20 frames were trusted
  about 44 m wrong. Validation had 5 cuts and no reverse angle, so nothing there could show it.
  Scoring it also showed main's own baseline had moved: #270's height band, measured on renderer
  0.5.15, rejects most right frames on the frozen test set (renderer 0.3.2). Main's pass F1 there is
  0.25, while the docs still said 0.67.
- **Rule:**
  - Before a fit is trusted on a new kind of view, list the views its model cannot tell apart (here,
    any camera and its half turn about the centre spot). Each needs a cue the symmetry changes, or
    is refused.
  - Validation for a change must hold every kind of case the change opens up (here, every kind of
    second angle), not just whichever ones the seeds happened to draw.
  - A threshold measured on one look is re-measured before it judges clips of another, and a
    published number is re-run when a change to its pipeline lands (lesson 215).
- **Check:**
  - `tests/test_vision_pitch.py::test_a_reverse_angle_draws_the_same_markings_as_the_main_camera_turned_about_the_centre_spot`.
  - `docs/eval/camera-cuts-plan.md`, Outcome: the test set re-judged three ways, and the cut
    following off by default until it passes its bar.

### 245. A side the voice holds is held on the screens too, or the gate protects only one of them
- **What happened:** the side gate (lesson 218) kept unsure sides out of the Describer's voice and
  out of the agents' claims, but the screens named them anyway. The viewer and the phone turn a
  track id into a club from its first letter (`h-t8` became "a London player"), and that letter is
  only the tracker's side vote. The offline dry run on two demo segments found it: every side there
  was told at 0.18, so the voice said "a player" while the screen named a club.
- **Rule:** the bundle lists the track ids whose side the gate vouches for (`sides_known`: each the
  actor of an event told surely, and named by no event that did not vouch for him). The viewer and
  the phone name a club only for those ids; every other tracked player is "a player" ("Player 12"
  as a title). An event's own side (`team`) is named the same way: the bundle carries the
  fact-checker's threshold (`min_team_confidence`), and the phone's play-by-play, story colours and
  shot list name a club only above it ("A player completes a pass"; an unsure shot is in "All"
  only, listed but not drawn; an unsure goal is "Goal 43′" and in no club's score). A writer that
  names a side and a screen that names it ask the same rule; what still reads the tracker's vote is
  listed in EVALUATION.md as a residual, not left unsaid.
- **Check:** `tests/test_viewer.py::test_a_tracked_player_on_an_unsure_side_is_a_player_on_screen`
  and `tests/test_phone_companion.py::test_a_tracked_player_on_an_unsure_side_is_never_named_by_club_on_the_phone`
  fail when the screens ignore the list, and
  `tests/test_phone_companion.py::test_the_play_by_play_names_a_club_only_for_a_side_told_surely`
  when the phone reads an event's side without the threshold;
  `tests/test_e2e.py::test_only_a_track_whose_side_was_told_surely_may_be_named_by_club` pins the list.

### 246. Two kits are told apart by what the camera sees, not by their base colours
- **What happened:** the demo match (seed 8080) passed the broadcast kit rule on shirt colour alone:
  purple against near-white, a WCAG contrast of 14:1. But the page draws each shirt's pattern in its
  trim, here white. Home was purple hoops in white over white shorts; away was a white shirt with
  white shorts. Seen from the broadcast camera, the shirts' contrast was 1.9:1, and the team split
  failed on every segment. The preflight audit found it after the render, so a pod run was lost.
- **Rule:** a rule meant to keep two things apart on screen tests them as drawn, with every element
  that changes what is seen (here the pattern, its colour and its area), not the parameter that seeds
  them.
- **Check:** `tests/test_render_params.py::test_seed_8080s_broadcast_kits_look_apart_once_the_pattern_is_on`
  and `::test_every_broadcast_seed_is_told_apart_as_seen_and_a_passing_seed_keeps_its_draws`. Both
  fail with the redraw off, or with the pattern's share set to 0.

### 247. A paid machine's cap runs on the machine, and its results leave it as they are made
- **What happened:** on Oct 24–25 two rented GPU hosts ran past their hard caps. Each cap was a
  timer on the maintainer's laptop. The first fired 14 min late with the laptop asleep, hit a DNS
  failure, and exited. The second retried with the laptop kept awake, but the laptop was offline
  for about 1 h 40 min, so the host billed about 1.5 h past its 2 h cap. Each time, finished work
  that had not been copied back was lost when the host was finally deleted: the shot-outcome set's
  renders and its validation scoring.
- **Rule:** the cap is enforced on the host itself: the first thing a rented host runs is its own
  deletion at the cap, started before any other work. The laptop's retrying timer is only a second
  line. Every finished result (a clip's report, a score, a set list) is copied off the host as it
  is written, never in a batch at the end.
- **Check:** a plan for a rented host (docs/PLAN.md, risks) states both before it is approved: the
  deadline the host enforces on itself, and the cadence at which results are copied back (every
  couple of minutes from the first). A run that keeps either on the laptop alone is not approved.
- **And (Oct 25, the next host):** the self-deletion worked; the host removed itself at exactly its
  cap. But the demo's frames were still lost:
  - the laptop's free disk was smaller than the copy;
  - the copy was held for an approval, and the answer came after the host was gone;
  - 12 vision lanes ran the host's 32 GB GPU out of memory on 9 of 34 segments.

  So, before a host is created, the receiving disk is checked against the expected copy-back. No
  copy waits on a question while the host runs, and GPU lanes are sized to the card's memory.

### 248. A place along the pitch is checked against the pitch before it is cut into thirds
- **What happened:** territory (#314) cut the pitch's length into thirds with `int(depth // THIRD_M)`,
  capped at 2. A ball in the net or behind a goal line has a depth below 0 or past 105 m. A negative
  depth gives index -1, and `THIRDS[-1]` is "final", so a ball behind one goal counted as the final
  third for both clubs at once. The merge queue's review caught it (x = 108 gave both 100%); no test
  had a ball off the pitch.
- **Rule:** a position is checked against the pitch (0 to 105 m along it) before it is cut into
  zones. One off the pitch is out of play and in no zone. A capped index is not a clamp: capping
  the top end still leaves Python's negative indices at the bottom.
- **Check:** `tests/test_possession_territory.py::test_a_ball_beyond_a_goal_line_is_in_no_third`
  (x = -3, -0.5, 106, 108) fails when the check is removed.

### 249. A phrase that states a direction is bound to the fact's own role, not only approved
- **What happened:** the closed direction check (lesson 221) approved a sentence when every word
  was one of the cited fact's own phrases. The phrases were approved as words, though, not as this
  fact's values. The merge queue's reviews of #321, #323 and #326 got these through:
  - "Hugo passed to Sami" against Sami-to-Hugo (both names, the same words);
  - "did not sprint" against a count of 4 (the zero phrase is one of the fact's phrases);
  - "their final third on the left" against own-third-right (any third matched);
  - a recap's twelve-moment cap dropping a goal.
  Numbers already had roles (lesson 221); orders, zeros and places did not.
- **Rule:** wherever a phrase carries a fact's value, the check binds it to that value:
  - a pair is said passer-to-receiver;
  - a zero phrase only of a zero;
  - a zone only as the fact's own third and channel.
  A cap on a list never drops the kind the list exists for (goals in a recap). A review probe that
  differs from the fact only in who, where or whether is a test.
- **Check:** `tests/test_passing_network.py::test_a_pair_is_said_in_its_order_and_with_its_caveat`,
  `tests/test_player_running.py::test_a_zero_or_a_zone_is_said_only_as_the_fact_has_it` and
  `tests/test_halves_and_moments.py::test_a_recap_never_drops_a_goal_however_many_moments_follow`
  fail when their binding is removed.


### 250. A guard on what a fan asked is a list of words, so every phrasing it misses gets an answer

- **What happened:** while a named player's running figures were held, the physical tool still
  said the zone each player was in most (#323). A guard (`held_ask`) matched "distance", "fastest",
  "sprint" and a few more, and refused those questions. Every other phrasing got the first zone
  fact, verified, with a player's name as the headline: "Who looks most tired?", "Who ran the
  furthest?", "How many km has Kai done?". Then "who is on the left?" got the zone of someone who
  played on the right, and "Where does Alex play?" got one of three Alexes. Three reviews found
  more phrasings each time. The fact-check never sees the question, so a true sentence that does
  not answer the question passes it.
- **Rule:** gate on the kind of answer the question asks for, and refuse anything else:
  - a figure, at its highest, or of the one player the question names;
  - the zone, only for a question of where, about one named player.
  
  Several players fitting are named back to the fan, never picked for him. A side or a third alone is not
  a question of where. The model path is held to the same target: an answer about another player,
  or not the figure asked, falls back to code.
- **Check:** `tests/test_player_running.py::test_the_zone_is_never_another_players_or_an_answer_to_a_side`
  and `::test_a_held_figure_asked_for_is_not_available_never_another_answer` (the reviewers'
  phrasings) fail when the gate's zone, ambiguity or player filter is removed.
