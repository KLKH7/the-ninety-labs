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
- **Check:** run the committed replay fixture after changing fact-checker diagnostics.

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
  `AERIAL_ABSORB`), so a change to the constant moves the test with it. A new lesson takes the next
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

### 47. A rule two places use lives in one place
- **What happened:** when the engine began taking a high ball on the thigh, chest or head, at half
  a foot's pace (A4), the passer's estimate kept judging every reception by the foot. Passers
  thought lofted passes were safer than the engine made them, for every pass since. Nothing failed:
  each half was tested on its own.
- **Rule:** a rule that both the engine and a player's estimate apply (the first touch, the kick
  error, the reach) is one function in one module that both call. Never two copies kept in step by
  hand.
- **Check:** `grep` the rule's constants: they appear in one module and its tests, nowhere else;
  a test feeds the same case to the engine's function and to the estimate.
