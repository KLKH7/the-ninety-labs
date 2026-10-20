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

### 95. A pattern that reads numbers must read every way a number is written
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
  clearly smaller, quote the unpaired one.

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
- **Rule:** every fallback claimed in docs/eval/failure-table.md is a row produced by injecting
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
