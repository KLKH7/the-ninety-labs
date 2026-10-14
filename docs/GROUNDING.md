# Grounding: where every rule comes from

The match engine and the validator both encode football. Neither is built from memory: every
rule, limit and realism band cites a source, and this file is the register. The engine uses it
to *make* football; the validator uses it, through independently written code, to *check* it
([architecture](ARCHITECTURE.md#synthetic-data-pipeline)).

**Status: draft for review.** Every Law row was checked on 2026-10-13 against the Laws as
published on [theifab.com](https://www.theifab.com/laws/latest/the-field-of-play/) (the site
lists the 2026/27 edition first). Values still marked *verify* come from general knowledge and
must be checked against the cited source before their check is built.

## Sources, by reliability

| Tier | Source | What it gives us | How we use it |
|---|---|---|---|
| 1 | **IFAB Laws of the Game** (current edition, [theifab.com](https://www.theifab.com)) | the rules, definitively | rules (hard checks), dimensions |
| 2 | **Peer-reviewed sports science**, preferring elite or Premier League samples, larger samples, recent, open access | physical limits, with ranges | physics limits, with generous margins |
| 3 | **Official competition reports** (league and UEFA technical reports) | season averages | realism bands (warnings) |
| 4 | **Industry standards and preprints**, e.g. the [Common Data Format](https://arxiv.org/abs/2505.15820) | how match data is structured and synchronised | structure of our data, never numbers |
| not used | stats websites, AI-generated summaries | | methods unclear, terms often forbid scraping |
| ask first | real match datasets, even free open ones | | rule 4.7 requires synthetic data; ask the organisers before any use, even offline |

## What we may and may not do with each

| Source | Allowed | Not allowed |
|---|---|---|
| IFAB Laws | read the official PDF; implement each rule as code; cite the Law and section; summarise in our own words | committing or reproducing the text: IFAB's notice requires its authorisation to reproduce or translate the Laws, in whole or in part |
| Sports science papers | cite figures with a link; prefer open access | copying text, tables or figures |
| Competition reports | cite a handful of published averages | scraping, bulk copying |
| CDF, kloppy | read; use kloppy's code (BSD-3) if it earns its place | |

Rules and facts are implemented, never copied. This is our reading of the licences and the
hackathon rules, not legal advice; when unsure, ask the organisers.

## How a source becomes a check

1. **Read** the primary source (for a rule, the Law in the current IFAB edition).
2. **Register** it below: one row, in our own words, with the citation.
3. **Make it measurable.** "The whole ball crosses the line" becomes "the ball's centre is past
   the line by more than its radius (0.11 m)".
4. **Plant a defect** in a test clip and require the check to fail on it.
5. **Build the check** in `ninety/validate.py`. Shared *facts* (pitch size, ball radius) may live
   in one constants module both sides import; the *logic* is written separately.
6. **Run it on the engine.** A failure is the engine's to-do list; the check stays forever.

## The checklist

Kind: **hard** fails the clip; **warn** is reported. Columns show what exists today.

### Consistency: the events and frames tell one story

| ID | Check | Source | Kind | Validator | Engine |
|---|---|---|---|---|---|
| C1 | files present, `fps` positive, every row matches its schema | our schemas | hard | ✅ | ✅ |
| C2 | frames consecutive, `t = frame / fps` | CDF (event and tracking in sync) | hard | ✅ | ✅ |
| C3 | same players throughout, except a substitution: only during a stoppage, at most five a team | Law 3 | hard | ✅ | ❌ no substitutions |
| C4 | every player in an event is in the frames, on the right team | our schemas | hard | ✅ | ✅ |
| C5 | each event's frame exists and its time matches | CDF | hard | ✅ | ✅ |
| C6 | the ball is where a pass, shot or tackle says it happened | CDF | hard | ✅ | ✅ |
| C7 | a pass or shot reaches its end point before anything else happens to the ball (no assumption about speed: a rolling ball slows) | CDF | hard | ✅ | ✅ |
| C8 | event order makes sense: only the player with the ball passes or shoots; an interception follows a failed pass; a goal follows a shot | Laws 9, 10 | hard | ✅ | ✅ |
| C9 | the score equals the goal events | Law 10 | hard | ✅ | ✅ |

### Physics: it could happen in the real world

| ID | Check | Source | Kind | Validator | Engine |
|---|---|---|---|---|---|
| P1 | player speed at most about 10.5 m/s | sports science, peak match sprint speeds (*verify*) | hard | ✅ | ✅ receivers run to the ball |
| P2 | speeding up at most 8 m/s² (a design margin over the 5.2 m/s² measured from standing, not derived); braking and turning at most 10 m/s² (peak braking 8.5 m/s², SD 1.1: mean plus one SD, rounded), measured over 0.2 s | [Hermosilla-Palma 2023](https://pmc.ncbi.nlm.nih.gov/articles/PMC9819841/); [Harper 2020](https://knowledge.lancashire.ac.uk/id/eprint/33971/1/33971%20Manuscript%20-%20Measuring%20Max%20Decel%20%28AAM%29.pdf). Before running the validator on real tracking data, base the braking limit on a measured maximum | hard | ✅ | ✅ force-velocity acceleration, braking up to 7 m/s², braking and turning share one grip limit |
| P3 | ball speed at most 40 m/s, except a new ball placed while out of play | sports science, fastest recorded shots (*verify*); Law 9 | hard | ✅ | ✅ |
| P4 | ball never below the ground (circumference 68 to 70 cm, so radius about 0.11 m) | Law 2 | hard | ✅ | ✅ |
| P5 | a ball in the air falls under gravity and air drag (drag coefficient up to 0.5, *verify*); the margin is the measurement precision of 1 mm positions. Frames within one frame of a recorded touch (which P14 must prove possible) or within 0.6 m of a post or the crossbar are contacts, not free flight | physics | hard | ✅ | ✅ |
| P6 | the ball stays at the feet of the player who has it (1.5 m), or in a goalkeeper's hands in a penalty area (2 m, *verify*) | Law 12 | hard | ✅ | ✅ |
| P8 | a free ball bounces (keeps about 60 percent of its vertical speed, *verify*) and rolls to a stop on grass (about 1.2 m/s², *verify*) | ball physics; Law 2 (size, mass) | hard | ❌ | ✅ |
| P7 | two players never overlap (about 0.5 m apart) | physics | warn | ❌ | ❌ |
| P9 | each player has a top-speed capability (about 10 m/s, SD 0.3) and acceleration falls linearly from about 5.2 m/s² at rest to zero at that speed; match peaks are measured (R6), never set | force-velocity profile of professionals ([Hermosilla-Palma 2023](https://pmc.ncbi.nlm.nih.gov/articles/PMC9819841/)) | engine | n/a | ✅ |
| P10 | energy: running above critical speed (about 3.9 m/s) spends a reserve of about 225 m; running below it refills it in 120 to 340 s, faster at a walk; a low reserve lowers top speed and, once moving, acceleration (from standing a tired player still pushes off at full force; design). Accelerating costs extra (*design* factor); the slow store wearing down over a match is *design* | critical speed from match data ([Lord 2020](https://johk.pl/wp-content/uploads/2023/03/10078-73-2020-v73-2020-09.pdf)); refill time constants ([Vassallo 2020](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6969867/)) | engine | n/a | ✅ |
| P11 | body: radius about 0.26 m, shoulder to shoulder about 0.52 m between centres; a keeper's reach is about 1 m standing and grows over a dive to about 1.8 m; jumping hand reach about 2.8 m | shoulder width of adult men scaled to footballers ([NC State anthropometry](https://ergocenter.ncsu.edu/wp-content/uploads/sites/358/2026/02/01-Anthropometry-Summary-Tables.pdf)); keeper dive time about 1 s ([Ibrahim 2019](https://www.frontiersin.org/journals/sports-and-active-living/articles/10.3389/fspor.2019.00015/full)) | engine | n/a | ✅ |
| P12 | reaction to a struck ball: a choice reaction (he must also pick a direction) of 0.32 to 0.41 s across footballers, set per player by reflexes. A keeper facing a shot also reads the kicker and starts toward where he thinks it is going (A2); the read can be wrong, and his reaction to the real ball still takes his full reaction time | footballers' simple and choice reaction ([Lesiakowski 2017](https://wnus.usz.edu.pl/cejssm/file/article/download/8620.pdf)); keepers' anticipation ([Frontiers 2024](https://www.frontiersin.org/journals/sports-and-active-living/articles/10.3389/fspor.2024.1356340/pdf)) | engine | n/a | ✅ |
| P13 | perception: each player decides on his own picture; he sees within about 60° either side of where he faces and anyone within 3 m, refreshes everyone when he scans (every 1.5 to 3.5 s), and his error grows by about 2 cm (and 0.02 m/s of speed) per metre of distance; an unseen player is carried forward at his last seen velocity for at most 1 s, then held; a still player keeps facing the way he faced when the ball is at his own feet. All values *design*; scanning varies with role and pressure | scanning research ([Jordet 2020](https://pmc.ncbi.nlm.nih.gov/articles/PMC7573254/)) | engine | n/a | ✅ |
| P14 | a deflection or interception names a player who could have touched the ball: within a foot's reach (1 m) or, for a keeper in his box, a dive's (1.8 m), plus one frame of motion, and the ball was not moving away from him. In the engine a ball meets a body only while closing on it, and only the part of its velocity into the body rebounds | physics; P11 for reach | hard | ✅ | ✅ |
| T1 | the team brain marks a transition for about 5 s after the ball changes hands (counter-pressing is measured over about 5 to 6 s) | counter-pressing in the Bundesliga ([Vogelbein 2014](https://lida.sport-iat.de/dfb/Record/4032298?lng=en)) | engine | n/a | ❌ defined, not yet used (counter-press is step 3c) |
| T2 | the defensive line stands within its block (low 12 to 22 m from own goal, mid 25 to 35, high 35 to 50), following the ball; with the ball inside the block the line drops to stay 5 m goal-side of it, no deeper than the goal area; out of possession the shape narrows and shifts to the ball side. Block ranges and line spacing are *design* | — | engine | n/a | ✅ mid block only so far |

### Player profiles: attributes change causes, never outcomes

Each attribute is 0 to 1 (shown 1 to 20) and maps to a parameter; none sets the chance of an
outcome. Players are synthetic (`ninety/sim/profiles.py`).

| ID | Attribute | What it changes | Source | Status |
|---|---|---|---|---|
| A1 | pace, acceleration, stamina | each is a percentile of its sourced distribution: acceleration from standing (P2, mean 5.18, SD 0.46 m/s²), top-speed capability (P9, mean 10.0, SD 0.3 m/s), critical speed (P10, mean 3.9, SD 0.2 m/s). Role shifts are in standard deviations (*design*), so a role with no shift keeps the sourced mean and spread | as P2, P9, P10. *Verify:* a 10 m sprint from standing takes 2.36 s at the mean, slower than elite times of about 1.8 s; the 5.2 m/s² may be an in-match peak rather than a sprint-test start | ✅ |
| A2 | anticipation, reflexes, vision | reflexes set the choice reaction within 0.32 to 0.41 s (the measured range); anticipation narrows a keeper's read of a shot's aim (spread 1.5 m at average, *design*), and never speeds the reaction; field of view 50° to 70° either side and scan interval (*design*) | as P12, P13 | ✅ |
| A3 | passing, crossing, finishing, composure, weak foot | kick error: about 3° of direction at average skill, preferred foot, penalty speed; wider with ball speed, pressure (unless composed), fatigue (about 25% when the slow store, P10, is spent) and the weaker foot (about 27% wider, about 12% slower), chosen by the kick's direction against the way he faces. A struck ball is capped at 36 m/s (*design*) | penalty precision by foot ([Frontiers 2024](https://www.frontiersin.org/journals/sports-and-active-living/articles/10.3389/fspor.2024.1434096/full)); the skill and pressure scaling and speed and launch errors are *design* | ✅ |
| A4 | first touch, handling | the fastest ball a touch can kill (8 to 16 m/s) and a keeper can hold (16 to 28 m/s); no study measures either, so *design* | — | ✅ |
| A5 | decisions, composure, work rate, aggression, dribbling, tackling, traits | decision temperature, pressing and sprint willingness, duel commitment, option biases | *design*; used from step 3b and step 4 | planned |
| A6 | role tendencies | each role's attributes shift from the average (strikers finish better, centre-backs tackle better) | *design* | ✅ |

### Decisions: the player's own estimates for choosing

These are estimates a player uses to choose, from his own picture of the pitch; the outcome of
the chosen action is decided by physics and execution error, so an estimate can be wrong.

| ID | Rule | Source | Status |
|---|---|---|---|
| D1 | each option scores expected value: the chance it works times the value of what follows, minus the chance it fails times the cost of losing the ball there; a pass lane is open if no opponent can reach the ball's path first (each opponent assumed to react in about 0.37 s with an average body) | decision rule from performance-analysis research (expected-value and pass-lane models) | ✅ |
| D2 | pressure is felt in a zone longer in front of the player than behind (about 9 m and 3 m) | pressure thresholds reported from tracking data | ✅ |
| D3 | the player's estimate of a shot is 0.75 × (the angle of the goal)², about 0.3 from 11 m central and 0.03 from 35 m: the published shape of shot quality; halved for each defender in the cone, reduced by a well-placed keeper (*design*) | published shot-quality shape | ✅ |
| D4 | choice by softmax: a good decision-maker almost always takes the best option, pressure loosens the choice unless composed; trailing late raises the appeal of shooting; a trait that likes long shots raises it from distance (*design*) | expected-value plus softmax approach from the research; values *design* | ✅ |
| D5 | the carrier settles the ball (0.3 to 0.6 s, quicker with a good first touch) then decides about 4 times a second; a throw goes only to a team-mate | *design* | ✅ |

### Laws of the Game: it is legal football

| ID | Check | Source | Kind | Validator | Engine |
|---|---|---|---|---|---|
| L1 | pitch 105 x 68 m (international limits: 100 to 110 by 64 to 75); goal 7.32 x 2.44 m; centre circle 9.15 m | Law 1 | hard | ❌ | ✅ pitch, no goal frame |
| L2 | 11 players a team, exactly one goalkeeper | Law 3 | hard | ❌ | ✅ |
| L3 | two equal halves of 45 minutes plus added time; teams switch ends for the second half | Laws 7, 8 | hard | ❌ | ❌ one long half |
| L4 | kick-off: ball still on the centre mark, every player but the kicker in their own half, opponents 9.15 m away; after a goal the conceding team kicks off | Law 8 | hard | ❌ | partly |
| L5 | the ball is out only when the whole ball has crossed a goal line or touchline, on the ground or in the air | Law 9 | hard | ❌ | ✅ |
| L6 | a goal only when the whole ball crosses the goal line between the posts and under the bar | Law 10 | hard | ❌ | ✅ |
| L7 | over the touchline: a throw-in to the opponents of the last player to touch it, from where it crossed; opponents 2 m away | Law 15 | hard | ❌ | ✅ thrown, not dribbled; ✅ the presser stands off 2 m |
| L8 | over the goal line, no goal, last touched by an attacker: a goal kick from inside the goal area; opponents outside the penalty area | Law 16 | hard | ❌ | ✅ awarded; 🟡 the presser stands outside the penalty area; other players are not yet kept out |
| L9 | over the goal line, no goal, last touched by a defender: a corner from the corner area on that side; opponents 9.15 m from the corner arc | Law 17 | hard | ❌ | ✅ awarded; 🟡 the presser stands off 9.15 m; other players are not yet kept away |
| L10 | a player who receives a team-mate's pass while in an offside position (in the opponents' half, nearer the goal line than the ball and the second-last opponent; level is onside) is penalised; never from a goal kick, throw-in or corner | Law 11 | hard | ❌ | ❌ |
| L11 | one referee and two assistants on the pitch | Laws 5, 6 | hard for video | ❌ | ❌ |
| L12 | fouls, free kicks, penalties, cards | Laws 12 to 14 | later | ❌ | ❌ |

### Realism: it looks like a Premier League match (warnings)

| ID | Check | Source | Validator | Engine |
|---|---|---|---|---|
| R1 | ball in play about 55 to 60 of 90 minutes | competition reports (*verify*) | ❌ | ❌ only 4 to 8 restarts a match: passes are aimed at team-mates and there are no clearances or crosses, so the ball rarely goes out |
| R2 | outfield players cover about 9 to 11 km per 90 minutes, by position | World Cup tracking ([Ortega 2022](https://www.wbc.poznan.pl//Content/522956/2_Ortega_TSS_2022_292_51-56.pdf)) | ❌ (report: `ninety.sim.patterns`) | 🟡 10.3 to 11.1 km for defenders and midfielders; wingers 13.2 and forwards 14.3 km, above the published 9.6 (players do not yet choose when to stand still) |
| R3 | pass completion about 75 to 88 percent | competition reports (*verify*) | ❌ | ❌ 53 to 58 percent: passes are chosen at random among seen team-mates, without checking the lane (step 3b chooses) |
| R4 | shots and goals per match in the usual range | competition reports (*verify*) | ❌ | ❌ 1 to 3 shots, 0 to 1 goals: a pressed carrier stands still and nothing yet decides to shoot from range (step 3b) |
| R5 | each position spends its time in realistic areas | sports science (*verify*) | ❌ | ❓ |
| R6 | match top speed by position about 7.9 to 8.6 m/s (capability is higher; few sprints last long enough to reach it) | World Cup tracking ([Ortega 2022](https://www.wbc.poznan.pl//Content/522956/2_Ortega_TSS_2022_292_51-56.pdf)) | ❌ (report) | 🟡 6.3 to 7.8 m/s, below the published 7.9 to 8.6 |
| R7 | high-intensity running in the last 15 minutes about 20 to 45 percent below the first 15 | Premier League tracking ([Bradley 2009](https://sure.sunderland.ac.uk/id/eprint/3478/)) | ❌ (report) | 🟡 53 percent lower, above the published 20 to 45 |
| R8 | team length about 31 to 46 m and width about 35 to 48 m, more compact out of possession | systematic review of professional positional data ([Rico-González](https://www.termedia.pl/Reference-values-for-collective-tactical-behaviours-based-on-positional-data-in-professional-football-matches-a-systematic-review,78,43095,0,1.html)) | ❌ (report) | ✅ in possession 41 × 36; out of possession 37 × 34, more compact |

### Renderer truth: the labels match the pictures

| ID | Check | Source | Kind | Validator | Renderer |
|---|---|---|---|---|---|
| V1 | each player and the ball projects to within 1 px of its label | [render guide](guides/broadcast-render.md) | hard | ❌ | planned |
| V2 | the same seed renders the same frames | render guide | hard | ❌ | planned |
| V3 | every box has a visibility fraction, so occluded players are not graded as misses | render guide | hard | ❌ | planned |

## Order of work

1. ~~Fix C3 so a legal substitution passes.~~ Done.
2. ~~Physics first.~~ Done: the engine passes P1 to P6 over full matches, with bounce and roll,
   and outcomes emerge from the ball rather than being decided at the kick. P8 needs its check.
3. **Out of play and restarts** (L5, L7 to L9) and **C8, C9**: visible on video, and they create
   the stoppages R1 needs.
4. **Halves and kick-off** (L3, L4), then **offside** (L10) and **officials** (L11).
5. **Realism bands** once the sources are verified.
6. **Renderer checks** with the renderer.
