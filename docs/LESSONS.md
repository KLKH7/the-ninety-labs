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

## Set pieces and tests

### 24. A placed ball must start outside every body
- **What happened:** a corner's new ball was placed at the taker's centre, so the struck ball
  "touched" him on its way out: a fake deflection and a 0.4 m jump in the ground truth on 39
  of 60 corners. The validator exempts deflection frames, so nothing failed.
- **Rule:** place a restart ball where it will be struck, with the taker behind it; a struck
  ball must leave its kicker without a contact.
- **Check:** after any kick, no deflection by the kicker within a few frames (a test runs many
  seeds).

### 25. A test that changes the whole random stream cannot prove one cause
- **What happened:** "the delivery is struck with error" compared two runs with different seeds;
  the choice and timing differed anyway, so removing the error left it green.
- **Rule:** hold everything else fixed (state, choice) and vary only the cause under test;
  then mutate the cause and require the test to fail.

### 26. A rule must check what its name says
- **What happened:** a goal-credit rule described as "the last player to touch it" was built
  from a short list of event types. It missed a team-mate controlling a pass and a defender
  winning the ball, so it accepted wrong scorers and would have rejected right ones; the engine
  produced one of them (a shot deflected in by a team-mate, credited to the shooter).
- **Rule:** build the quantity the rule names from every source of it (here: who had the ball at
  each frame, plus every touch event), and plant one case of each way it can be wrong.
- **Check:** for each rule, list the ways the data can make it true, and test each one.

### 27. A fixture must look like the real output
- **What happened:** goal-credit tests built clips with nobody on the ball at the goal frame,
  but the engine writes the kick-off reset into that frame (the next taker on the centre spot).
  The rule counted that taker as the last toucher of every real goal: every own goal passed,
  and a correct team-mate's goal failed, while every test was green.
- **Rule:** build fixtures from real output (or copy its shape exactly: what the goal frame,
  the restart frame and the first frame contain), and run each rule on real engine clips that
  contain the case, not only on fixtures.
- **Check:** for a new rule, find real clips where it applies (a scan over seeds) and assert on
  them in a test.

### 28. "All mutations caught" is only as wide as the list
- **What happened:** a report said 23 of 23 mutations were caught; an auditor found six more,
  near the same code, that survived (dropped conditions, a tolerance ten times too wide).
- **Rule:** for every condition and every constant in a check, mutate it (drop it, widen it
  tenfold) and require a test to fail; report the list, not just the count.

### 29. A plan must not stand the receiver where the ball is aimed
- **What happened:** the corner routine put each attacker on the exact spot the taker could aim
  at, standing still, so a delivery's target and its receiver were the same point decided in
  advance. Defenders marked a stationary man; the run, the timing and the space (what decides a
  real corner) were missing. The scenario also placed a defender by the line and recorded him as
  the last touch, so the corner's cause was staged. Every test was green: they checked the plan
  was carried out, not whether the plan itself decided the play.
- **Rule:** a plan gives players intentions (where to wait, where to run, when), never the point
  where the ball meets them; the taker aims at space and times it on his runner, and contact
  emerges from the run and the flight. When a cause cannot yet be played, say so in GROUNDING as
  an open issue rather than calling it modelled.
- **Check:** for each set piece, ask what is decided before the ball moves; anything that is a
  meeting point or a cause, not an intention, is scripting. Measure before and after a change
  (here: first contact, goals, wait to the kick over 200 corners).

### 30. A rule that never fires is not a model; a number without its script is not a result
- **What happened:** after lesson 29, the taker was meant to time his cross on his runner. An
  audit measured it: in 293 of 300 corners he struck in the same frame he signalled, because
  the cross's long flight meant every runner "arrived in time"; the rule's unit test passed
  only with a runner placed 25 m away. The same pull request published first-contact numbers
  (156 to 36) counted from events alone, which miss clean receptions; the real split was 106 to
  93. Then letting the taker choose freely with the shared pass estimates made 199 of 200
  corners ground passes into the box, which no test noticed and only the report showed.
- **Rule:** for every new decision rule, measure how often each branch fires on real engine
  output and what the output looks like (here: kick timing, delivery height, end points),
  before and after. Publish a number only from a committed script that anyone can rerun
  (`ninety/sim/corner_report.py` writes `docs/eval/sim-corners.md`).
- **Check:** a test that pins a branch with a hand-built state must be paired with a
  measurement showing the branch happens in real clips.


### 31. A seed's outcome is not the same on every Python
- **What happened:** a test counted the goals in the first 32 scenario corners and asked for at
  least 3. Locally (Python 3.13) there were 4; CI (3.12) found 2 and failed. Same seeds, same
  code: tiny floating-point differences between versions grow over a chaotic simulation.
- **Rule:** never assert how many times something happens over a fixed set of seeds. Scan until
  enough cases are found (with a cap far above the expected need), and assert the rule on each.
  Determinism holds within one Python version, not across them.
- **Check:** before pushing a test that runs the engine over seeds, run it on every Python
  version CI uses (`UV_PROJECT_ENVIRONMENT=<dir> uv run --python 3.11 pytest`).

### 32. For a rare event, select among played situations; never stage its cause
- **What happened:** to get corner clips, the scenario placed a defender by the goal line and
  recorded him as the last touch, because open play rarely reached the line. The corner itself
  was played, but its cause was written into the data without happening.
- **Rule:** start from a situation that can plausibly lead to the event (here, a winger on the
  ball in the final third), play it out, and keep the runs where play produces the event; give
  each run its own seed and record it. Say in GROUNDING that this is selection, so nobody reads
  the scenario's numbers as how often the event happens.
- **Check:** in a scenario clip, every event before the one you wanted must have been played:
  nothing at frame 0 except the opening state, and the cause (the exit and the touch it came
  off) present in the data.

### 33. When a check rejects real output, find out what happened before changing the check
- **What happened:** the goal-mouth check rejected an engine goal: a ball deflected along the
  goal line from outside the post that went in inside it. The check was wrong in one way (it
  aimed at where the ball's centre met the line; Law 10 needs the whole ball over), so it was
  "fixed" and the goal called legal. An independent audit then found two things: the fix let
  slow balls up to 1 m wide or over the bar count as goals (its error allowance grew with how far
  it extrapolated), and the ball in that goal had passed through the post, because the engine
  only tests the woodwork where the ball's path crosses the line. The original rejection was
  right for a reason nobody looked for, and a test was written that enshrined the bad goal.
- **Rule:** when a check fails real output, trace the whole event frame by frame (where was the
  ball relative to the posts, the bar, the line?) before deciding which side is wrong. Write the
  check on exactly what the Law states, bound how far it extrapolates by what the engine can do
  (a goal is recorded in the frame the whole ball goes over), and add a check for the physical
  impossibility you find (P16: the ball never passes through the woodwork).
- **Check:** for each geometric check, have fixtures for each way the ball can approach (straight,
  along the line, dropping, slow, fast), confirm each fails on the old code where it should, and
  build them with the speeds real output has.

### 34. An exemption must use the same geometry as the rule it lifts; a contact must use the moment of contact
- **What happened:** to allow a goal in off the post, the goal check skipped its path test when
  the ball came near "the woodwork", but measured the post without its height and the bar without
  its length: a ball a metre over the post, or level with the bar but well wide, counted as a
  goal. In the engine, a ball that started a frame overlapping the bar was put back where it began
  but kept the speed it had gained over the whole frame, so a ball resting on the bar gained
  energy without limit.
- **Rule:** model the object once (here, the goal frame as three bars, corners included) and use
  that one model wherever it matters: the engine's rebound, the check that the ball never passes
  through it, and any exemption. Resolve a contact with the state at the moment of contact.
- **Check:** for every exemption, build an illegal case that sits just inside it and must still
  fail; for every collision, a test that energy never rises and a resting ball comes to rest.

### 35. A new motion must be checked against every existing rule, in the scenes where it happens
- **What happened:** a keeper's dive was added with a cited peak speed and duration, and the
  push-off between them was derived to fit: 16 m/s², twice the acceleration check's limit. The
  dive also started from rest whatever the keeper was doing, played short dives faster and
  stopped him dead in the air. Every test and full-match clip passed, because few full-match
  shots made a keeper dive; the first scenario that made keepers dive often failed two thirds of
  its clips.
- **Rule:** model a motion as the force that makes it, applied to the body's current state, with
  each part of its profile from a source; never derive an unsourced part of a profile so that
  two cited numbers fit. Then run the motion through the scenes that exercise it and the whole
  contract, not only its own tests.
- **Check:** for a new movement, a test that the body's velocity never changes faster than its
  limit from any starting velocity, and a contract run over clips where it happens often.

### 36. When sources disagree, the reading that passes your check is not evidence
- **What happened:** a keeper's dive broke the acceleration check. Two cited sources pointed
  opposite ways: one implied a push of about 0.2 s (the fast dive the engine had), the other, read
  only from search results, a push of about 0.44 s. The slower one was chosen; it also happened to
  fit under the check, and it cut keepers' saves at 16 m from 74 to 55 percent. An audit pointed
  out that the choice had been made on the number that passed, not on the source.
- **Rule:** when sources disagree, read both and record why one is right before building on
  either; until then mark the conflict as unresolved where the number is used, with what it
  changes, and never let "it passes the check" decide.
- **Check:** for each new constant, can you quote the passage it comes from? If not, it is
  *verify*, and GROUNDING says what it would change if the other reading is right.

### 37. A new way to touch the ball must be checked from every body near it, and decided once
- **What happened:** heading was added and passed its own tests, but an audit found a header met
  the ball at its closest point to the player, so it left from inside his body and could deflect
  off him; a ball he chose to let drop passed through his chest, because declining the header
  skipped the body test; and the passer's estimate disagreed with the engine in three places (how
  far ahead a player judges letting the ball drop, the launch of a header away, a header at goal
  valued as a kick). Half the new tests compared a constant with itself, so changing it changed
  the expectation too.
- **Rule:** for a new contact, check the toucher's own body after his touch, a player who declines
  the touch, and everyone else the ball passes; put any rule the estimate shares with the engine
  in one helper or one constant both use; pin sourced numbers in tests as numbers.
- **Check:** a test that the ball never passes through or rebounds off the player who just played
  it, over many random cases; a test that runs the estimate and the engine on one scene; mutation
  results reported per mutation, with which test caught it, and incidental catches named as such.
