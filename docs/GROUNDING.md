# Grounding: where every rule comes from

The match engine and the validator both encode football. Neither is built from memory: every
rule, limit and realism band cites a source, and this file is the register. The engine uses it
to *make* football; the validator uses it, through independently written code, to *check* it
([architecture](ARCHITECTURE.md#synthetic-data-pipeline)).

**Status: draft for review.** Values marked *verify* are from general knowledge and must be
checked against the cited source before the check is built.

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
| C3 | same players throughout, **except a substitution at a stoppage** | Law 3 | hard | ⚠️ too strict: fails a legal substitution | ❌ no substitutions |
| C4 | every player in an event is in the frames, on the right team | our schemas | hard | ✅ | ✅ |
| C5 | each event's frame exists and its time matches | CDF | hard | ✅ | ✅ |
| C6 | the ball is where a pass, shot or tackle says it happened | CDF | hard | ✅ | ✅ |
| C7 | a pass or shot reaches its end point in the time its speed allows | physics | hard | ✅ | ✅ |
| C8 | event order makes sense: only the player with the ball passes or shoots; an interception follows a failed pass; a goal follows a shot | Laws 9, 10 | hard | ❌ | partly |
| C9 | the score equals the goal events | Law 10 | hard | ❌ | ✅ |

### Physics: it could happen in the real world

| ID | Check | Source | Kind | Validator | Engine |
|---|---|---|---|---|---|
| P1 | player speed at most about 10.5 m/s | sports science, peak match sprint speeds (*verify*) | hard | ✅ | ❌ receivers jump to the ball |
| P2 | player acceleration at most about 8 m/s² | elite players' maximal acceleration about 6.2 m/s² ([Applied Sciences, 2022](https://doaj.org/article/5a330c62187f431b8d51ae1e9eca156f)) plus margin | hard | ❌ | ❌ no limit |
| P3 | ball speed at most 40 m/s | sports science, fastest recorded shots (*verify*) | hard | ✅ | ❌ goalkeeper takes the ball by jumping it |
| P4 | ball never below the ground | Law 2 (ball radius) | hard | ❌ | ✅ |
| P5 | a ball in the air falls under gravity, then bounces and rolls | physics | hard | ❌ | ❌ fixed arc for every pass |
| P6 | the ball stays at the feet of the player who has it | physics | hard | ❌ | ✅ |
| P7 | two players never overlap (about 0.5 m apart) | physics | warn | ❌ | ❌ |

### Laws of the Game: it is legal football

| ID | Check | Source | Kind | Validator | Engine |
|---|---|---|---|---|---|
| L1 | pitch 105 x 68 m, within the Law's limits; goal 7.32 x 2.44 m | Law 1 | hard | ❌ | ✅ pitch, no goal frame |
| L2 | 11 players a team, exactly one goalkeeper | Law 3 | hard | ❌ | ✅ |
| L3 | two halves of 45 minutes; ends switch at half-time | Law 7, Law 8 | hard | ❌ | ❌ one long half |
| L4 | kick-off: ball on the centre mark, everyone in their own half, opponents 9.15 m away | Law 8 | hard | ❌ | partly |
| L5 | the ball is out only when the whole ball crosses a line | Law 9 | hard | ❌ | ❌ no out of play except missed shots |
| L6 | a goal only when the whole ball crosses the goal line between the posts and under the bar | Law 10 | hard | ❌ | partly |
| L7 | over the touchline: a throw-in to the other team, from where it crossed | Law 15 | hard | ❌ | ❌ |
| L8 | over the goal line, last touched by an attacker: a goal kick from the goal area | Law 16 | hard | ❌ | partly |
| L9 | over the goal line, last touched by a defender: a corner from the corner area | Law 17 | hard | ❌ | ❌ |
| L10 | no completed pass to a player in an offside position | Law 11 | hard | ❌ | ❌ |
| L11 | one referee and two assistants on the pitch | Laws 5, 6 | hard for video | ❌ | ❌ |
| L12 | fouls, free kicks, penalties, cards | Laws 12 to 14 | later | ❌ | ❌ |

### Realism: it looks like a Premier League match (warnings)

| ID | Check | Source | Validator | Engine |
|---|---|---|---|---|
| R1 | ball in play about 55 to 60 of 90 minutes | competition reports (*verify*) | ❌ | ❌ always in play |
| R2 | outfield players cover about 10 to 13 km per 90 minutes | sports science, Premier League samples (*verify*) | ❌ | ❓ |
| R3 | pass completion about 75 to 88 percent | competition reports (*verify*) | ❌ | ✅ tuned |
| R4 | shots and goals per match in the usual range | competition reports (*verify*) | ❌ | ✅ tuned |
| R5 | each position spends its time in realistic areas | sports science (*verify*) | ❌ | ❓ |

### Renderer truth: the labels match the pictures

| ID | Check | Source | Kind | Validator | Renderer |
|---|---|---|---|---|---|
| V1 | each player and the ball projects to within 1 px of its label | [render guide](guides/broadcast-render.md) | hard | ❌ | planned |
| V2 | the same seed renders the same frames | render guide | hard | ❌ | planned |
| V3 | every box has a visibility fraction, so occluded players are not graded as misses | render guide | hard | ❌ | planned |

## Order of work

1. **Fix C3** so a legal substitution passes.
2. **Physics first** (P2, P4 to P6): the vision model is trained on these frames.
3. **Out of play and restarts** (L5, L7 to L9) and **C8, C9**: visible on video, and they create
   the stoppages R1 needs.
4. **Halves and kick-off** (L3, L4), then **offside** (L10) and **officials** (L11).
5. **Realism bands** once the sources are verified.
6. **Renderer checks** with the renderer.
