# Match engine design

How the engine produces football that is realistic because of its causes, not because its
totals were tuned. This is the design for the next builds; what already runs is in
[GROUNDING.md](GROUNDING.md) and [DATA_CONTRACT.md](DATA_CONTRACT.md).

## Principles

1. **Players decide, physics happens, the referee observes.** Every event is the consequence
   of a player choosing an action from what he perceives, then executing it imperfectly. No
   outcome (a completed pass, a save, a tackle won, a foul, an offside, the ball going out) is
   ever drawn at random or set to a target.
2. **Each player is an agent** with attributes, a role, energy and a limited, noisy picture of
   the pitch. Two players in the same situation can decide differently, and a tired or
   pressured player decides and executes worse.
3. **Tactics are intentions, never results.** A team style weights decisions and shapes
   positions; whether it produces many counter-attacks is measured afterwards.
4. **Data has three permitted uses** (see [Using the research](#using-the-research)):
   physical measurements set parameters; behavioural findings shape decision rules; match
   totals only judge the result.
5. **Every build is audited** by an independent reviewer for scripted outcomes before it
   merges ([LESSONS.md](LESSONS.md), lesson 4).
6. **A seed is the same match on every machine.** The engine draws from `fmath.Random` and
   computes `exp`, `sin`, `atan2` and the normal distribution with `ninety/sim/fmath.py`,
   never the C math library, whose last bit differs between operating systems
   ([LESSONS.md](LESSONS.md), lesson 46).

## The loop

```
every frame (25 per second)
  ball.step()                       flight, drag, bounce, slide then roll
  contact()                         the ball meets bodies, feet and hands on its path
  players move                      toward their chosen targets, within acceleration and energy
  referee.observe()                 out of play, goals, offside at the pass, fouls from contacts
every 0.25 to 0.5 s, staggered per player
  perceive -> list options -> score -> choose -> commit
every 0.5 s per team
  team brain: phase of play, line height, who presses, who covers
```

## Layers

### 1. Ball

Already built: gravity, air drag, bounce, rolling friction, posts and crossbar. Next, from
published measurements: drag that falls sharply above a critical speed (the drag crisis), a
sliding phase before a struck ball starts to roll, and horizontal speed kept in a bounce of
about 0.6. Spin and swerve come later.

### 2. Body

- **Acceleration falls as speed rises**: about 5 m/s² from standing, approaching zero at top
  speed; braking up to about 8 m/s².
- **Top speed per player**, about 8 to 9.5 m/s in matches, from the player's pace.
- **Body shape** for contact: shoulders wide (0.50 m) and chest deep (0.20 m), turned the way he
  faces, the same outline the renderer draws (`ninety/sim/shape.py`, GROUNDING P11).
- **Goalkeeper reach grows during a dive**: about 1 m standing, more as the dive goes on, so a
  save depends on when the keeper started moving and where the ball is.

### 3. Energy (fatigue)

Two reserves: a fast one for sprints that empties in hard spells and refills while jogging,
and a slow one that declines over the match. Low energy lowers top speed and acceleration,
slows recovery runs, widens execution error and makes high-effort options less attractive.
The late-match drop in high-intensity running must **emerge** from the reserves; it is a
check, never a parameter.

### 4. Perception

- A player reacts to a struck ball after a reaction time (about 0.25 to 0.37 s, longer when he
  must also choose a direction); goalkeepers start to move before the strike by reading the
  kicker.
- Each player keeps a **belief** of where others are: updated inside his field of view,
  stale and extrapolated outside it, noisier with distance and fatigue. Decisions use the
  belief, physics uses the truth. A misplaced pass is a pass chosen on a stale belief.

### 5. Team brain

Twice a second per team: the phase of play (build-up, progression, final third, block,
press, counter), the height of the defensive line, who presses and who covers. Assignments
are strong suggestions in each player's scoring, not commands: a low-teamwork player can
ignore one. Positions come from anchor tables for in and out of possession, shifted by the
ball.

### 6. Decisions

On the ball: pass (short, long, through, switch), cross, shoot, dribble, carry, shield, clear,
hold. Off the ball: hold shape, support, run in behind, press, cover, mark, track a runner,
recover, step up or drop.

Each option is scored as a product of 0-to-1 considerations (completion odds from who can reach
the ball first, ground gained, pressure, shot quality from distance, angle, defenders and
keeper), multiplied by the team style, the role and the player's own tendencies, and reduced
for high-effort options when tired. The choice is a softmax: a player with good decisions and
composure almost always takes the best option; one under pressure sometimes takes a worse one.
A small bonus for the current choice stops players flip-flopping. The ball carrier looks one
or two actions ahead.

Game state moves one team value, **risk appetite**: trailing late raises it (more shots, more
pressing), leading lowers it (deeper block).

### 7. Execution

Every action goes through physics with error: direction, speed and height errors grow with
distance, ball speed, pressure, fatigue, weak foot and body angle, and shrink with technique.
A first touch is a cushion, not a gate: the surface takes out what it can kill, the player sends the rest where he chooses with his own error, and a ball he cannot keep at his feet is a heavy touch the race decides (`firsttouch.py`, GROUNDING A4). What makes a touch worse (pressure, body angle, fatigue, speed) comes next.

### 8. Duels

The carrier dribbles by touching the ball ahead in small kicks, keeping it on the side away
from the defender. A defender wins it only by getting a foot to it between touches. A
challenge that reaches the player before the ball is a foul. No tackle has a success rate.

### 9. Referee

Observes, never generates: out of play and the restart (Laws 9, 15 to 17), goals (Law 10),
offside judged from positions when the pass is played (Law 11), fouls from contacts and the
free kick or penalty that follows (Laws 12 to 14), back passes to the keeper (Law 12).

### 10. Set pieces and stoppages

Restart time is how long players take to get into position and the taker to place and strike
the ball, not a timer. Walls at 9.15 m, box occupation at corners, short or long goal kicks
chosen by the decision layer. Ball-in-play time must emerge.

## Styles and matchups

A style is a set of dials, each independent: **directness**, **pressing height and
intensity**, **line height**, **width**, **crossing**, **tempo**, **counter-attacking** on
winning the ball, **counter-pressing** on losing it, and **risk**. Five archetypes are
presets of the dials: high press, possession, counter-attack, low block and direct. Each clip
is a matchup of two styles, mixed across the dataset. Styles also adapt to the score.

Each style has a **fingerprint** measured from the events it produced: pressing intensity
(opposition passes per defensive action), possession share, directness, long-ball share,
crosses, field tilt. A high-press team must come out with intense pressing; if it does not,
a cause is wrong. Fingerprints are measured, never forced.

Dials, presets, strength, predictions and the matchup grid: [decision 0002](decisions/0002-styles-and-matchups.md).

## Using the research

| Kind of data | Permitted use | Example |
|---|---|---|
| Physical measurement | sets a parameter, cited in GROUNDING.md | drag coefficient, acceleration, reaction time |
| Behavioural finding | shapes a decision rule | counter-attacks pay off only against an unbalanced defence |
| Match total | judges the result as a held-out check | passes, shots, goals, restarts, ball-in-play time |

Match totals are never test gates that fail the build: a test that fails when goals leave a
band pushes every future change toward tuning goals. Realism is reported across many patterns
at once (passes, completion, shots, goals, restarts, ball-in-play, distance covered, the late
drop in running, each style's fingerprint) and judged together.

## Build order

Each step is one pull request, checked by the validator, reported against the realism
patterns, and audited independently before it merges.

1. **Body and energy**: acceleration curve, per-player top speed, body size, two-reserve
   energy. Done when every physics check passes and the body model's own tests do. Running
   patterns (distance, sprints, top speeds, the late drop in high-intensity running) are
   reported from this step on, but cannot appear until players choose to run (step 3).
2. **Perception and team brain**: reaction and anticipation, beliefs, phase, line, press and
   cover assignments, anchor tables.
3. **Decisions and execution**: options, utility scoring, softmax, look-ahead, execution error,
   off-the-ball runs. Done when shots, goals and restarts arise from choices and errors with no
   outcome draws, and running patterns (distance, sprints, the late drop) appear in the report.
4. **Duels and the referee**: dribble touches, challenges, fouls, offside, set pieces without
   timers.
5. **Styles and matchups**: dials, archetypes, fingerprints measured per clip.
6. **Ball refinements**: drag crisis, slide then roll, spin.

Batch 1 (contact and perception, built on a branch) merges with step 3, when realistic
decisions replace the scripted ones it removed.
