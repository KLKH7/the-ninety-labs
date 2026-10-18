# 0002: A keeper's dive as a body in the world

- **Status:** accepted, Oct 18, 2026 (open questions answered below).
- **Rubric:** technological implementation (a match engine whose outcomes emerge from grounded
  physics). It also matters for the demo video: a keeper who dives realistically is what a viewer
  sees.
- **Measured by:** the held-out checks below. None of them is a target.

## The problem

The engine's keeper keeps out too much (GROUNDING P15, A2):

| | Engine (280e277) | Published |
|---|---|---|
| Penalties kept out, of those on target | 30.9% | 14.7% (42 of 286, Bar-Eli et al. 2007, Table 2) |
| Penalties kept out, by height (low, middle, high) | 25.5%, 32.1%, 40.0% | 16.5%, 33.5%, 9.1% (Higueras-Herbada et al. 2020) |
| Open-play saves, of shots on target, in matches | 86.9% | 76.5% (Pérez-Arroniz et al. 2025, P15) |

KLKH7/the-ninety-labs#93 tried to close the penalty gap step by step and was closed unmerged
(lesson 36). It still left a clear diagnosis, cell by cell against Bar-Eli's Table 2. The keeper:

1. **never commits.** His read of the kicker only steers his sideways run. After his reaction time
   he dives toward where the ball really crosses, so the read calibrated to Bar-Eli barely matters
   (lesson 35).
2. **reaches as far behind a dive as ahead of it.** His reach is a circle round his body.
3. **is a column 1.8 m tall in the air.** Mid-dive his body blocks a ball at any height.
4. **still catches chest-high balls while lying on the ground** after landing.
5. **faces no penalties down the middle.** Every aim is 0.5 to 3.2 m off centre; real kicks end in
   the middle third 28.7% of the time (Bar-Eli, Table 1). Keepers stay in the middle 6.3% of the
   time.

Fixing 1 alone raised penalty saves to 46%. Fixing 2, 4 and part of 3 brought them to 28.5%. The
audit then found the fixes physically wrong or inconsistent (lesson 36).

## The sources

| What | Source | Says |
|---|---|---|
| Where penalties end, where keepers go, what they stop | Bar-Eli et al. 2007, *J. Economic Psychology* 28:606, Tables 1 and 2 (MPRA working paper 4477) | 286 kicks on target. Middle third 82, keeper stayed 18. On side kicks, right way 113, wrong way 83, stayed 8. Stops: right way 29.6% / 25.4%, wrong way 0%, middle when staying 60%, middle when jumping 9.8% / 3.2%. |
| When keepers commit and decide height | Higueras-Herbada et al. 2020, *Front. Psychol.* 11:311 | Hands differ for left and right at least 115 ms before contact, and for low and high about 245 ms after it. Saves: 16.5% low, 33.5% middle, 9.1% high. Lab study, 5 non-professional keepers, 25 Hz video. |
| Movement onset | reviews cited in Frontiers 2024 (fspor.2024.1356340) | Keepers start sideways 50 to 350 ms before contact. Skilled keepers time their dive to the kicker's planting foot. |
| How far and fast a dive goes | Monteiro et al. 2022, *Sci. Rep.* 12:18493; Ibrahim et al. 2019 (already P15) | Centre of mass 1.36 to 1.54 m, peak 3.6 to 4.0 m/s, push-off about 0.48 s. |
| Body lengths | P11 | Hips to fingertips about 1.8 m; arm reach standing 1.0 m. |
| Kicks aimed down the middle | The Analyst (Opta), Feb 2024 | 21.2% of Premier League penalties aimed down the middle (35 of 165). Keepers "move late" and "can't move too early". |
| Penalty save rate | premierleague.com | 17.7% of all penalties saved (407 of 2,296); 7.5% to 26.3% by season. *Verify.* |

## Proposed model

One mechanism, built whole, with every estimate of the keeper updated in the same change (lesson 23).

1. **A dive is a body moving in the world, not a clock.**
   - Its centre of mass travels sideways as P15 has it, and it also has a height over time.
   - It covers a footprint: the trunk along the dive line, the hands stretching ahead in the dive
     direction, and the trailing leg behind.
   - Both hands and body are bounded in height by where the body actually is.
   - Once he has landed he is on the ground and covers only what a body lying there can.
   - Sources: P11, P15, Monteiro.
   - *Design, needs a source:* the height of the body over the dive, and how fast the hands can
     move up or down once the height is known.
2. **One function says where his hands and body can be at time t.** The touch, the body contact,
   the dive planner (`keeper_dive`'s `need`), the shooter's judgement (`offball.keeper_reach_m`, O1)
   and the passer's race (`reach_for`) all use it.
3. **At a penalty he commits before the strike, in the world.**
   - The taker's aim is chosen when his windup starts, before the strike.
   - The keeper reads it then and sets off at the measured lead before contact: at least 115 ms,
     inside the reviewed 50 to 350 ms. *Design:* the value within that range.
   - He chooses his height from the ball's flight from about 245 ms after contact (Higueras-Herbada).
   - Open-play dives stay reactive.
4. **Penalty aims and stays reproduce Bar-Eli at the outcome.**
   - The aim mix is derived so that, through the engine's own execution error, kicks end in the
     middle third 28.7% of the time. That is derived from the source, as the read spread already is
     (lesson 32).
   - The keeper stays 18 times in 286, and more often on middle kicks (10 of 82) than side ones
     (8 of 204). *Design:* how that dependence arises.

## Held-out checks, never targets

- Bar-Eli Table 2, cell by cell, and the 14.7% overall.
- The Premier League range of 7.5% to 26.3% of all penalties saved.
- Open-play saves against 76.5% (P15). Saves by distance stay a report (`ninety.sim.saves`).
- Shots and goals over the 24 seeds (R4).
- Higueras-Herbada's saves by height. These are not independent of item 3's height timing, which
  comes from the same paper, so they are reported, not counted as evidence.

## Order of work: one PR each, each audited (lesson 21), measured from clean worktrees (lesson 34)

1. **Report:** commit the cell-by-cell penalty rig as `ninety.sim.penalties`, writing
   `docs/eval/penalties.md`, so every later PR measures the same table.
2. **The dive body and the shared reach function (items 1 and 2), for every dive.**
3. **The penalty commit, aims and stays (items 3 and 4).**

## Open questions, answered on approval

- **The body's height during a dive, and how fast the hands can move up or down:** look for
  measured kinematics first. Use *design* values only where none can be found, and mark them.
- **Whether a keeper stays more on middle kicks:** keep staying independent of the kick for now
  (*design*). Bar-Eli shows 10 of 82 on middle kicks against 8 of 204 on side kicks; the cue that
  would cause the difference is not modelled.
