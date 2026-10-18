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

### 29. A trigger guarded only by "not busy now" fires again when the busy state ends
- **What happened:** a keeper's dive was allowed whenever he was not diving and not on the
  ground. A slow shot was still on its way after he had dived, landed and got up, so he dived a
  second time at the same ball. Every condition checked the present; none remembered that the
  touch had already set off a dive.
- **Rule:** an action that happens once per cause records the cause it answered (here the touch,
  `kicked_at`) and checks it, rather than relying on a temporary state to block a repeat.
- **Check:** for each once-per-cause action, write a test where the cause outlives the action's
  own busy state (dive, land, get up, ball still coming) and require no repeat; and one where a
  new cause (a deflection) is allowed to trigger it again.

### 30. Keep every dimension a source measured
- **What happened:** the kick-error source measured a tilted ellipse of where shots cross the goal
  line (a long and a short axis). The engine kept one number, their geometric mean (3°), as the
  sideways error, and gave the up-and-down error a fixed 2° that did not grow with speed, pressure
  or fatigue. Close shots almost never missed: none of 25 unblocked shots inside 25 m in one sample.
- **Rule:** when a source reports a shape (axes, a covariance, a distribution), derive each
  component the engine uses from it, in code, with the derivation beside it. A number that
  summarises a measurement is not the measurement.
- **Check:** for each sourced constant, ask "what did the source actually measure, in how many
  dimensions?" and test the derived values against the source's own figures.

### 31. A committed report must come from the committed code
- **What happened:** two commits regenerated `docs/eval/funnel.md` (1.8 goals a team), yet the
  code of the later one, re-run on a clean checkout of that commit, produced 2.5; the realism test went red with nobody noticing. Twelve
  matches also hide a change of 0.3 goals a team in noise (standard error about 0.27).
- **Rule:** regenerate a report from the exact tree being committed, after the last code change,
  and state how big a difference the sample can resolve.
- **Check:** re-run the report on a clean checkout of the commit and compare before merging.

### 32. A measured spread already holds every cause; an extra error source must take its share
- **What happened:** the kick's vertical error was set to the whole measured vertical spread at
  the goal, and the engine then added its own speed spread on top. A slower ball drops more, so
  the speed spread moved the ball up and down again: kicks scattered about 7% wider vertically than
  the measurement they were built from.
- **Rule:** when the engine draws several independent errors that each move the same measured
  quantity, derive each one's share through the engine's own physics so that together they
  reproduce the measurement, never set one of them to the whole of it.
- **Check:** reproduce the source's measurement end to end through the engine (here, kicks fired at
  the paper's setup land in the paper's ellipse), with a tolerance from the sample size, and remove
  any known bias of the derivation (a linear split left the vertical about 1% wide) rather than
  spend the tolerance on it.


### 33. Say what an exemption is about; never infer it from a coincidence
- **What happened:** the rule that a kick needs the kicker facing its line (P16) exempted a
  throw-in by testing "the ball is within 0.1 m of his centre", meaning "in his hands". Every dead
  ball the restart code places at the taker's centre (kick-offs, free kicks, corners, goal kicks)
  passed the same test, and so did a penalty whenever the taker had walked onto the mark, so takers
  struck at once with their back to the target. In matches penalties scored 6 of 17 against the
  published 75 to 90%. The first fix had two more faults, both caught by the audit. The flag that
  replaced the test outlived the throw when the ball was knocked from his hands. And a taker who
  now had to turn carried the dead ball off its spot as he turned, because the turn code was
  written for a ball in play. A third audit found that, once the turn took time, the restart's
  rules had already lapsed: opponents could close on a ball not yet kicked.
  The pass estimate already exempted only throw-ins, so the two disagreed (lesson 23).
- **Rule:** an exemption names the case it is for (here, an explicit "thrown" flag from the
  throw-in in progress), never a geometric stand-in that other cases can also satisfy.
- **Check:** for each exemption, list every state in which its condition holds and confirm each
  belongs to it; test one case that should be exempt and one that looks alike and should not.
  When removing an exemption, follow every case it covered through the code it now reaches
  (here a dead ball reaching the in-play turn) and test it through the match loop, not just the
  rule's function.

### 34. Never measure from a tree someone is mutating
- **What happened:** a 24-match comparison ran in the background while the author and an
  independent auditor mutation-tested the same checkout by editing `engine.py` in place and
  restoring it. Whichever version was on disk when the run imported the engine is what it
  measured: seed 11 scored 4 goals in that run and 7 on the committed code. The same overlap may
  have touched the previous pull request's 24-match numbers.
- **Rule:** run measurements from a separate worktree checked out at the exact commit being
  measured, and do mutation testing in a different checkout, or never at the same time.
- **Check:** before trusting a run, re-run one of its seeds on a clean checkout of the commit and
  compare; record the commit and worktree with the numbers.
## Set pieces and tests

### 35. A placed ball must start outside every body
- **What happened:** a corner's new ball was placed at the taker's centre, so the struck ball
  "touched" him on its way out: a fake deflection and a 0.4 m jump in the ground truth on 39
  of 60 corners. The validator exempts deflection frames, so nothing failed.
- **Rule:** place a restart ball where it will be struck, with the taker behind it; a struck
  ball must leave its kicker without a contact.
- **Check:** after any kick, no deflection by the kicker within a few frames (a test runs many
  seeds).

### 36. A test that changes the whole random stream cannot prove one cause
- **What happened:** "the delivery is struck with error" compared two runs with different seeds;
  the choice and timing differed anyway, so removing the error left it green.
- **Rule:** hold everything else fixed (state, choice) and vary only the cause under test;
  then mutate the cause and require the test to fail.

### 37. A rule must check what its name says
- **What happened:** a goal-credit rule described as "the last player to touch it" was built
  from a short list of event types. It missed a team-mate controlling a pass and a defender
  winning the ball, so it accepted wrong scorers and would have rejected right ones; the engine
  produced one of them (a shot deflected in by a team-mate, credited to the shooter).
- **Rule:** build the quantity the rule names from every source of it (here: who had the ball at
  each frame, plus every touch event), and plant one case of each way it can be wrong.
- **Check:** for each rule, list the ways the data can make it true, and test each one.

### 38. A fixture must look like the real output
- **What happened:** goal-credit tests built clips with nobody on the ball at the goal frame,
  but the engine writes the kick-off reset into that frame (the next taker on the centre spot).
  The rule counted that taker as the last toucher of every real goal: every own goal passed,
  and a correct team-mate's goal failed, while every test was green.
- **Rule:** build fixtures from real output (or copy its shape exactly: what the goal frame,
  the restart frame and the first frame contain), and run each rule on real engine clips that
  contain the case, not only on fixtures.
- **Check:** for a new rule, find real clips where it applies (a scan over seeds) and assert on
  them in a test.

### 39. "All mutations caught" is only as wide as the list
- **What happened:** a report said 23 of 23 mutations were caught; an auditor found six more,
  near the same code, that survived (dropped conditions, a tolerance ten times too wide).
- **Rule:** for every condition and every constant in a check, mutate it (drop it, widen it
  tenfold) and require a test to fail; report the list, not just the count.

### 40. A plan must not stand the receiver where the ball is aimed
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

### 41. A rule that never fires is not a model; a number without its script is not a result
- **What happened:** after lesson 40, the taker was meant to time his cross on his runner. An
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


### 42. A seed's outcome is not the same on every Python
- **What happened:** a test counted the goals in the first 32 scenario corners and asked for at
  least 3. Locally (Python 3.13) there were 4; CI (3.12) found 2 and failed. Same seeds, same
  code: tiny floating-point differences between versions grow over a chaotic simulation.
- **Rule:** never assert how many times something happens over a fixed set of seeds. Scan until
  enough cases are found (with a cap far above the expected need), and assert the rule on each.
  Determinism holds within one Python version, not across them.
- **Check:** before pushing a test that runs the engine over seeds, run it on every Python
  version CI uses (`UV_PROJECT_ENVIRONMENT=<dir> uv run --python 3.11 pytest`).

### 43. For a rare event, select among played situations; never stage its cause
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

### 44. When a check rejects real output, find out what happened before changing the check
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
  impossibility you find (P17: the ball never passes through the woodwork).
- **Check:** for each geometric check, have fixtures for each way the ball can approach (straight,
  along the line, dropping, slow, fast), confirm each fails on the old code where it should, and
  build them with the speeds real output has.

### 45. An exemption must use the same geometry as the rule it lifts; a contact must use the moment of contact
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

### 46. A new motion must be checked against every existing rule, in the scenes where it happens
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

### 47. When sources disagree, the reading that passes your check is not evidence
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

### 48. A new way to touch the ball must be checked from every body near it, and decided once
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

### 49. A drawn opening is a hidden cause
- **What happened:** after lesson 43 the corner scenario played its attacks out instead of staging
  the corner, but it opened every attack with a winger on the ball at a drawn spot, facing a drawn
  way, and kept only corners within 20 s. Four corners in five were then a blocked shot: the
  opening chose the kind of play, the window kept only the quick outcomes, and the report blamed
  the engine's shooting.
- **Rule:** a scenario that selects a rare event opens from a moment the full engine reaches by
  itself (here: play from the kick-off until the home side has the ball in its final third), and
  branches its attempts from there; nothing about the opening is drawn.
- **Check:** compare the scenario's mix of causes with the same causes in full matches, and list
  every parameter of the opening: each one that is drawn rather than played is a suspect.

### 50. A merge that ports a rule into new code must keep every branch of it
- **What happened:** merging the body outline (lesson 24) into heading, the contact loop was
  rewritten to take each player's earliest reach. A ball he chose to let drop past his head then
  ended his turn in that step, so the foot touch later in the same step was lost, and a ball
  dropping straight down inside his outline passed through him. The old loop had a separate
  branch for that case; the port kept only the first chance. Both sides' tests caught it.
- **Rule:** when a merge moves a rule into rewritten code, list the old rule's branches (here:
  heads it, lets it drop to his feet, cushions it on his body) and show each one in the new code.
- **Check:** run both branches' tests on the merge before resolving any test conflict, and read
  each failure as a possible regression before treating it as an outdated expectation.

### 51. A belief is one state: everything read from it must agree
- **What happened:** a team's own passes rolled out for corners, about 3.75 a match, 70 percent of
  all corners. A player unseen for over a second was believed to stand where he was last carried
  to, but his believed velocity was still the old one, so a pass led him into the space he had run
  from, often toward his own goal line; the passer's race rated it 0.7 to 0.99. The pass was also
  aimed at the spot chosen before the passer turned, though turning had just shown him where the
  receiver was. An audit then found the new tests checked the belief, not the four places that
  read it, and that mutation runs in a copy were importing the original through the editable
  install, so every mutant "survived".
- **Rule:** every quantity read from a belief (position, velocity, age) is derived from the same
  model of it; a choice that waits on a turn acts on what is believed when it is carried out.
  For mutation runs in a copy, set `PYTHONPATH` to the copy and check `ninety.__file__`.
- **Check:** a test that the believed velocity is the rate of change of the believed position, and
  tests on each caller; for a rate like own-pass corners, look at what the passer believed against
  what was true at the kick.

### 52. A structural change chosen from a report, justified by half the engine, is tailoring
- **What happened:** a full-match pass count was over a test's limit. Calibration showed forward
  passes rated too low, and the passer's estimate raced every opponent while the engine sends
  one chaser, so the estimate was changed to race only the first. It made calibration look
  better and turned the failing seed green. An audit found the engine lets any opponent take the
  ball by contact and re-plans its chaser every 4 frames, so the change was not the engine's rule
  but a different way to combine uncertainty, optimistic wherever two opponents contest; where
  play happens did not change at all. It was reverted. A shape change tried before it (attackers
  on the defenders' line) cut passes only through 12 offsides a match, and was reverted too.
- **Rule:** before changing how an estimate combines its parts, read every path in the engine
  that decides the same outcome (here `plan_chase` and `contact`), not only the one that fits.
  A rate that moves for the wrong reason (passes down because offsides went up), or a check that
  turns green while the behaviour behind it does not move, is not a fix.
- **Check:** for any change that moves a held-out check, list what else moved (stoppages, where
  play happens) and say what did not.

### 53. Seven fixes to how options are valued, when the cause was where team-mates stood
- **What happened:** possession seldom reached the final third, and seven attempts changed how a
  carrier values his options (holding, lookahead, measured tables and others). None worked. The
  option values were all about the same because the options themselves were all about the same: the
  in-possession shape set every role's height behind the ball, so whoever had it found every
  non-forward level with or behind him (all seven within 5 m of a centre-back on the ball) and the front
  three 27 m ahead, with nobody between the lines. Set in lines from the team's own back line
  instead, own-third possession fell from 56 to 39 percent and final-third entries rose from 46 to
  66 a match, though shots rose too (26 to 35), so the work is not finished. Separately, the shot
  estimate judged defenders where they stood, though a shooter facing away turns before he strikes
  (P16), which the pass estimate already counted: shots from outside the box after a turn were
  blocked 21 percent of the time against an estimated 8 (docs/eval/play.md).
- **Rule:** before changing how a decision weighs its options, measure what options it is offered
  (who is where, relative to the man on the ball) and whether each estimate matches what the engine
  then does. A flat set of values can be a flat set of choices.
- **Check:** for any rate about where play happens, tabulate the options offered per decision
  (count, direction, value) and each estimate against its measured outcome, split by the conditions
  the engine treats differently (here: facing the goal or turning).

### 54. A rule written for the player's estimate that the engine never plays
- **What happened:** holding the ball was valued as losing it "half the time he is pressed" (D9),
  a guess written for the estimate alone. Measured, the engine never took a held ball within a
  decision interval at any pressure (0 of 1,029 holds), because its defenders commit only within
  lunge reach and a presser jockeys outside it. The guess made every hold, and every cross held
  for a timed run, look far riskier than play made it. The first replacement copied D8's reach
  and win chance but left out who may commit, how often, and that a defender tries every decision
  interval; an audit caught it, and the commit rule now lives in one function both call.
- **Rule:** every risk an estimate charges comes from the engine rule that produces it, called,
  not copied; a rule that exists only in the estimate is a defect.
- **Check:** for each estimated chance, tabulate it against what the engine then did, in the
  conditions the estimate distinguishes (here: pressure, and holds of one interval against
  several), before trusting it.
