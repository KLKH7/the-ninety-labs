# 0002: Team styles, team strength and matchups

- **Status:** proposed, Oct 17, 2026 (R1)
- **Rubric:** technological implementation (synthetic data a judge can believe) and UX (each
  clip says what it is, and the viewer shows that the setting came out in the play). It also
  helps vision: a high press makes crowded frames and a low block makes crowded boxes.
- **Builds:** [ENGINE.md, styles and matchups](../ENGINE.md#styles-and-matchups) (build step 5)
- **Measured by:** the style report and matchup grid below, reported beside
  [GROUNDING.md](../GROUNDING.md) R rows, never used as a gate

## What we need

Every team wants to score more than the other, but teams go about it differently. That
difference, and the difference between a strong side and a weak one, has to show in the
synthetic data for three reasons:

1. **Realism.** A dataset where every match is the same mid-block game against an equal side
   is not football.
2. **The demo.** A judge should be able to pick "possession side against counter-attacking
   side" or "strong against weak", see the setting on screen, and see that the play and the
   numbers fit it.
3. **Vision.** Different styles put the ball and players in different places (crowded boxes,
   high turnovers, long balls), so the detector sees more varied scenes.

We cannot simulate live in the demo: one 90-minute match takes about 3 CPU-minutes to simulate
(seed 7: 19 s CPU per simulated 10 minutes on a 4-core session container), before rendering. So the
library is generated in advance. The brief allows this: it asks the pipeline to take in events
"as they happen" and produce real-time insights ([BRIEF.md](../BRIEF.md)), which is about the
pipeline, not the simulator. A pre-generated match played back at match speed is our live feed;
detection, stats, agents and graphics still run live on it.

## Options

| Option | For | Against | Result |
|---|---|---|---|
| A. An exhaustive list of named tactics (tiki-taka, gegenpress, catenaccio, ...), each coded on its own | names fans know | each one is a separate code path; combinations explode; names mean different things to different people | rejected |
| B. **Independent dials, with a few named presets** | one code path; any mix is possible; a preset is just values; each dial maps to a decision weight or a team-brain setting that already exists or is planned | presets need sensible values (*design*) | **chosen** |
| C. Styles learned from real tracking or event data | realistic mixes | rule 4.7: no real match data | rejected |
| D. Set outcomes by matchup ("two counter-attacking teams score 3.5 goals on average") | easy to show the pattern we want | scripting a result ([LESSONS.md](../LESSONS.md), lessons 1 and 2); the realism claim would be false | rejected |

## Decision

A **style** is a set of dials, each from 0 to 1. A dial only changes what players *intend*:
where the team stands, when it presses, how it weights each option in its decisions. Whether a
pass is completed, a press wins the ball or a shot goes in is still decided by perception,
physics and execution error. A **preset** is a named set of dial values. A **matchup** is two
styles and two team strengths.

### Dials

| Dial | What it changes in the engine | Exists today |
|---|---|---|
| Line height | the block the team brain picks (`BLOCKS`, T2) | yes, fixed at `mid` |
| Pressing height | the line of engagement (`ENGAGE_FROM_GOAL_M`, T3), set separately from the line | yes, tied to the block |
| Pressing intensity | how many players go to the ball and how close the presser stands (`PRESS_GAP_M`) | partly: one presser and one cover |
| Counter-pressing | whether the team presses in the transition window after losing the ball (`TRANSITION_S`, T1) | yes, always on |
| Counter-attacking | in the window after winning the ball, more weight on forward passes, forward runs and carries | no |
| Directness | weight on ground gained against keeping the ball, in option values (D1, D4) | no |
| Risk | the cost of losing the ball in option values (D1); the game state moves it too (ENGINE.md §6) | no |
| Tempo | how soon the carrier releases the ball once settled (D5), and the bonus for holding it | no |
| Width | how far the shape spreads across the pitch in possession (R8) | no |
| Crossing | weight on crosses from wide areas | no: the engine has no crosses yet (R1) |

### Presets

Values are *design*: low 0.2, mid 0.5, high 0.8. Brackets give the common names.

| Dial | High press (gegenpress) | Possession (tiki-taka) | Counter-attack | Low block | Direct |
|---|---|---|---|---|---|
| Line height | high | high | mid | low | mid |
| Pressing height | high | mid | low | low | mid |
| Pressing intensity | high | mid | mid | low | mid |
| Counter-pressing | high | high | low | low | mid |
| Counter-attacking | high | low | high | mid | mid |
| Directness | mid | low | high | mid | high |
| Risk | mid | low | mid | low | high |
| Tempo | high | mid | high | low | high |
| Width | mid | high | mid | low | high |
| Crossing | mid | low | mid | mid | high |

### Strength

Already built: `Match(seed, strengths=...)` takes each team's strength in player-quality SDs
(A6), and players are generated around it. Stars on screen are a display band of that value
(*design*: 1 star below −1.0, then bands of 0.5 SD up to 5 stars above +0.5). Strength never
changes a style or physical limits (A1); stronger players simply decide and execute better.
Whether a style is "more sophisticated" for a strong side is left to the players: a team of
good decision-makers runs any preset better, and we do not give strong sides special tactics.

### Fingerprint

Each team in each match gets a fingerprint, computed by code from the simulator's events after
the match (`ninety/sim/patterns.py`, extended):

| Measure | Definition |
|---|---|
| Pressing intensity (PPDA) | opponent passes in their own 60% of the pitch, divided by our tackles, interceptions and challenges in that zone (metric definition as commonly used in industry analysis; tier 4: structure only, no numbers taken from it) |
| Where the ball is won | median distance from our own goal of possession regains |
| Possession share | share of ball-in-play time with the ball |
| Directness | metres gained toward goal per pass; share of passes over 32 m |
| Tempo | passes per minute of possession |
| Field tilt | our share of both teams' passes in the attacking third |
| Fast attacks | possessions that reach the attacking third within 10 s of a regain, and their shots |
| Shots | count, and count by distance band (the stats engine has no xG model) |

The fingerprint is the check that a preset does what its name says. If a high-press side does
not come out with low PPDA and high regains, a cause is wrong, and we fix the cause rather than
push PPDA toward a number.

## Predictions, written before running

These are written down **before** any styled match has been run, and published with the
result whether it agrees or not. They are directional and held out: none of them is a test, a
target or a reason to change a value (ENGINE.md, "Using the research"). Sources marked *verify*
must be read before the result is published.

| ID | Prediction | Basis |
|---|---|---|
| H1 | the stronger side wins more often, more so as the gap grows, and the weaker side still wins some matches | team-strength models of match outcomes (Dixon and Coles 1997, *Applied Statistics*; *verify*) |
| H2 | a high-press side has lower PPDA and wins the ball further from its own goal than the same squad playing low block | follows from the preset; pressing as a style factor (Fernandez-Navarro et al. 2016, *J Sports Sci*; *verify*) |
| H3 | a possession side has a higher possession share and more passes per possession than the same squad playing direct | follows from the preset; possession against direct play as a style factor (Fernandez-Navarro et al. 2016; *verify*) |
| H4 | a counter-attacking side creates more of its shots from fast attacks, and its fast attacks produce more shots per attack than its slower ones | counter-attacks are more effective than elaborate attacks against an unbalanced defence (Tenga et al. 2010, *J Sports Sci*; *verify*) |
| H5 | at equal strength, possession share alone does not decide who wins: the possession preset does not beat the counter-attacking preset most of the time | possession is weakly related to success once team quality is accounted for (Collet 2013, *J Sports Sci*; *verify*) |
| H6 | low block against low block has the fewest shots of any pairing | our reasoning, no source: few high turnovers, and space is given only far from goal |
| H7 | high press against high press has the most turnovers in the attacking thirds | our reasoning, no source |
| H8 | counter-attack against counter-attack: **no prediction**. More goals (both sides break) and fewer (both wait for the other to commit) are both plausible; we report what happens | none |
| H9 | once game state moves risk: the leading side has less possession late on | leading teams keep less of the ball (Lago and Martín 2007, *J Sports Sci*; *verify*) |

## Precondition: the baseline must be realistic first

The engine today produces 47 to 56 shots and 13 to 19 goals a match (GROUNDING.md R4). Against
that baseline, differences in goals between styles mean nothing. So:

- **Fingerprints (H2 to H4) can be reported as soon as the dials are wired:** they test intent,
  not totals.
- **The matchup grid is not published until R4 is in the published range**, reached by fixing
  causes (defending, keepers, option values), never by tuning toward it (lesson 2). If R4 is
  still out of range at feature freeze, the grid ships with that caveat in its header, or not
  at all.

## The matchup grid

Simulation only, no rendering. Run by `ninety.sim.patterns` (extended) and written to
`docs/eval/sim-styles.md`.

- **Style grid:** the five presets against each other, 15 pairings (mirror matches included),
  both sides at strength 0, 20 seeds each, home and away swapped on alternate seeds.
- **Strength sweep:** the same preset on both sides, strength gaps 0, 0.5, 1.0 and 1.5 SD,
  20 seeds each.
- **Why 20 seeds:** shots, at about 25 a match (Poisson SD 5), separate a difference of 3 shots
  per match between two cells at about two standard errors with 20 to 25 matches each. Goals,
  at about 2.7 a match, would need roughly 90 matches per cell for a difference of half a goal,
  so goals are reported with intervals and not claimed as a finding.
- **Cost:** 380 matches at about 3 CPU-minutes each, about 19 CPU-hours: about 5 hours on a
  4-core container, less as a Container Apps job.
- **Each cell shows:** mean and 95% interval for shots, goals, possession share, PPDA, field
  tilt and fast-attack shots, plus win/draw/loss counts for the strength sweep.

## What the judges see

1. **A library of rendered matches**, each with a corner card: "Possession ★★★★ vs Low block
   ★★". Under it, the setting next to what came out: "set: high press → measured: PPDA 7.9,
   regains 41 m from own goal". The card is labelled *simulator setting*, so nobody mistakes it
   for something the system inferred.
2. **The matchup grid** as a page in the viewer: style against style, with the predictions
   above beside the results, including any that missed.
3. **Demo clips are chosen fairly.** Seeds for the rendered library are fixed before the grid
   runs (the first seed of each chosen cell). Picking whichever seed happened to tell the story
   would be scripting the presentation.

### Ground truth stays off the live path

The configured style and strength are simulator inputs, so they are ground truth. The corner
card may show them as the scenario's label, but **no agent on the live path reads them**. The
Tactician has to work out a team's style from detected events and the stats computed from them.
That makes a measurable claim possible: **style recognition accuracy**, the Tactician's call
against the configured preset over the grid, shown as a confusion matrix. This is a proposal
to R4 and R3 and is not part of this build.

## Rules

- A dial changes intention only. A test checks that every dial at its default reproduces
  today's engine exactly (same events for the same seed), so wiring the dials changes nothing
  until a style is chosen.
- No dial, preset value or engine constant is changed to make a prediction come true or a grid
  cell look better. A missed prediction is reported and its cause investigated.
- Every dial that ships gets a GROUNDING.md row (a T row) saying what it changes and where its
  values come from, before it merges. The independent audit for scripted outcomes (lesson 4)
  applies to this build like any other engine step.

## Plan

| Date | Work | Done when |
|---|---|---|
| Oct 17 | `engine-v1` is tagged **without** styles; dataset v1 is not disturbed | tag exists |
| Oct 18 to 19 | `Style` dataclass and presets; wire line height, pressing height, pressing intensity and counter-pressing; CLI `--home-style --away-style --home-strength --away-strength`; defaults reproduce today | default-identity test passes; a high-press run shows a high line in the tracking |
| Oct 20 to 21 | counter-attacking, directness, risk and tempo in option values; fingerprint measures; grid runner | H2 to H4 reported on 5 seeds per preset |
| Oct 22 | `engine-v2` with styles (R1 → R2 handoff); grid runs as a job | `docs/eval/sim-styles.md` committed |
| Oct 23 to 24 | corner card and grid page (R5, from a JSON fixture R1 provides on Oct 21) | the viewer shows a matchup card on a library clip |

**Cut list, in order:** crossing (needs crosses first), width, score-state adaptation (H9),
tempo. The minimum that still tells presets apart is line height, pressing height,
counter-pressing, counter-attacking, directness and risk.

## Open questions

- Should mirror matches (high press against high press) be shown in the demo, or only in the
  grid? They are the clearest test of H6 and H7 but the least varied viewing.
- Do teams switch style mid-match beyond score-state risk (for example, a strong side dropping
  into a low block when leading by two)? Not planned before freeze.
