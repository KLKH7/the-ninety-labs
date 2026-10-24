# Demo match: pre-registered choice and edit of the condensed full match

Status: **pre-registered, not yet applied.** The rule is fixed and merged here before any match in
its pool is simulated on the final engine. It is applied once, at the engine SHA the Coordinator
names after the last engine merges, and its output is recorded below. If the footage then has a
defect, that is reported and fixed in the renderer; the match is not swapped for a better-looking
seed, and the weights, gates and windows below are not changed after the sweep.

**What it is for:** the live demo plays one whole simulated 90-minute match, condensed to 15 to 20
minutes the way a broadcaster cuts a condensed match: every goal is in it, the clock jumps at each
cut under the existing stinger, and chapter markers let a viewer jump to each moment.

**Rubric:** UX and presentation (the demo feels like watching a match), and honest claims: the
match and the edit are chosen by a rule written before the matches existed, not by browsing.

**Supersedes the demo clip** ([demo-clip.md](demo-clip.md)): on Oct 23 Kian decided the demo plays
this condensed match instead of a 60 s clip. That rule is marked superseded and its script exits
without choosing; a test pins both, so the two rules can never both pick footage.

## The pool

**Seeds 8051 to 8090**, 90 minutes each, simulated only (no render), on the final engine SHA. None
of them has been rendered or watched: seed 8001 was the demo seed for v1 and v2, and 8002 to 8050
belonged to the superseded demo-clip rule. No training, validation, targeted or test run uses this
range. If no seed passes every gate, the pool extends to 8091 to 8130 under the same rule, in a new
commit that says so; nothing else changes.

## Gates (all must pass)

| Gate | Passes when | Source |
|---|---|---|
| G1 contract | `uv run ninety-validate` exits 0 on the 90-minute run | [DATA_CONTRACT.md](../DATA_CONTRACT.md) |
| G2 pass completion | both sides' passes together complete 75% to 88% | GROUNDING R3 (marked *verify* there: competition reports, not yet read from a primary source) |
| G3 football sense | the seed's mean rank across the gated football-sense types is at or below the pool's median mean rank | GROUNDING FS1 to FS9 |
| G4 goals | 1 to 6 goals in the match | *design*: a condensed match without a goal is not a demo; the top keeps a freak score out |

- **G3 in detail.** The gated types are the ones GROUNDING does not mark report only: FS1, FS2, FS3,
  FS5, FS6 (own-box passes), FS8 and FS9, each per 90 minutes from `ninety.eval.football_sense`. FS4
  and FS7 are report only and are not gated. Most gated types have no published real rate (their
  thresholds are the task's definitions or *design*), so G3 compares the pool with itself. Each type ranks the pool, fewest defects first, tied seeds
  sharing the mean of their places; a seed's G3 number is the mean of its ranks. Ranks, not a sum,
  because the types differ in scale by a hundred times (FS6 against FS3), and a sum would be FS6
  alone. With no published bar for a single match, the bar is the pool's own median: the
  cleaner half of the pool passes.
- **Possession losses are not gated.** GROUNDING cites no real range for them, and a range is not
  remembered (AGENTS.md: football is grounded). The count of possession changes is reported in the
  gate table so a reader sees it.
- **G4 is a selection gate, not a realism test.** Lesson 136 keeps a per-match goal bound out of the
  engine's tests; here it only keeps a goalless match off the demo.

## The action score (among the seeds that pass every gate)

| Part | Weight |
|---|---:|
| each goal | 3 |
| contested: both sides scored, or the side with fewer goals had at least 2 shots on target | 4 |
| each keeper save (a shot on target not scored) | 1 |
| each shot on target (goals included) | 1 |
| each corner, and each direct free kick in the taking side's final third (a penalty counts here) | 0.5 |
| each passing move of at least 5 completed passes by one side | 0.2 |

A goal is also a shot on target, so it scores 4; a save scores 2. The highest score wins; **a tie
goes to the lowest seed.** The weights are *design*, fixed here before the sweep: goals lead, a game
both sides are in comes next, then chances, then set pieces and passing play. They were written first, then
checked on matches outside the pool (never a pool seed) to see that no one part swamps the rest. On main `7f3a595`, seed 7 (3-2) scores 66.2: goals 15, contested 4,
saves 10, shots on target 15, set pieces 9, moves 13.2; seed 11 (1-3) scores 43.9.

What the score reads, from `events.jsonl`:
- A corner is a set piece taken within 2 m of the goal line after the ball went out over it (a goal
  kick is taken further out); a free kick is a set piece after a foul (offside gives an indirect one, which does not
  count); the final third is the 35 m nearest the goal the side attacks. The engine plays 90 minutes
  without changing ends.
- A passing move is a run of completed passes by one side. A failed pass, a shot, a stop (out of
  play, foul, offside, goal) or any touch by the other side ends it; pressure, the side's own tackles
  and deflections do not, and a restart may start one.

## The edit (condense rule)

Every moment gets a window of A seconds before it and B after it:

| Moment | A | B |
|---|---:|---:|
| goal | 25 | 20 |
| shot or save | 12 | 6 |
| corner | 2 | 12 |
| direct free kick in the final third | 2 | 12 |
| each of the 8 longest passing moves (N = 8; most passes, a tie the earlier), from its first pass to its last | 2 | 4 |

Always in: the kick-off (the first 20 s), 45:00 (10 s either side) and the last 20 s. The engine has
no half-time interval or second-half kick-off, so 45:00 is marked as a point on the clock, not as a
whistle the engine never blew. Windows that overlap, or are less than 5 s apart, merge into one
segment. Each segment is one cut; the clock jumps between them under the stinger.

**Adjustment, if the total misses 15 to 20 minutes:**
- **Under 15:** add the next-longest passing moves (the 9th, the 10th, ...), one at a time, until
  the total reaches 15 minutes or no move of 5 passes is left. If it is still short, keep it and
  report it.
- **Over 20:** drop moments one at a time until it fits, in tiers: passing moves first (fewest
  passes first, a tie the later), then corners and free kicks, then shots off target or blocked;
  within the last two tiers, the moment that frees the most seconds first (a tie the later). Goals,
  saves, the kick-off, 45:00 and the end are never dropped; if they alone run over 20 minutes, the
  edit keeps them and the overrun is reported.

On main `7f3a595` the rule gives seed 7 a 22.0-minute edit before adjustment, 19.4 after dropping
six passing moves (50 segments), and seed 11 16.7 minutes with no adjustment (34 segments). These
two seeds only checked that the windows land near the target; nothing was tuned on a pool seed.

**Chapter markers:** each segment's chapter is named for its most important moment (goal, save,
shot, corner, free kick, move) with that moment's match clock and the video time where the segment
starts. The kick-off, 45:00 and the end are marked where they fall.

## Output

`uv run python scripts/demo_match.py select` writes (to stdout) the chosen seed and score, the gate
table of every seed, the top 5, the segments (`start_s`, `end_s` in match time, `video_start_s`),
the chapters, the total and every adjustment made, and one render command per segment:

```bash
uv run ninety-render --seed <seed> --start <start_s> --seconds <end_s - start_s> --set dead_ball_cut=true --set kit_contrast=broadcast --set stadium=broadcast --set views=tactical --mp4 --gpu --out runs/demo-match/seed<seed>/seg<NN>
```

Each segment is rendered as its own clip, so each is a window the data contract already covers and
passes `uv run ninety-validate` and `uv run ninety-render-check` on its own; the player joins them in
order with the stinger at each join. Stadium `broadcast` (lesson 185), broadcast kits, and the two
tactical lenses beside the broadcast (`views=tactical`). **`views=tactical` comes from #231 (the tactical
camera's render), which is not on main as this rule merges; #231 merges before the sweep, and
`select` refuses to print render commands until `ninety.render.params` knows the knob.**

## The sweep

```bash
# at most two at once (the Mac crashed on more), each through the machine's slot limit
runs/slot.sh uv run python scripts/demo_match.py measure <seed>   # for each seed 8051 to 8090
uv run python scripts/demo_match.py select > runs/demo-match/result.json
```

`measure` simulates the seed for 90 minutes, validates it, counts its football sense, writes
`measure.json` beside the events and deletes the frames (172 MB a match; the match is re-made from
its seed).

## What this choice is, honestly

The choice of match and the cut points use the simulator's events: an editorial choice, like a TV
director's, made before anything watches the footage. Nothing on the live path reads them. Vision,
the stats it feeds and the agents see only the rendered pixels of the segments shown, and any team
statistic on screen is labelled "from the footage shown", since a condensed match leaves out about
75 minutes of play. The chapter markers come from the edit (the answer key's events) and are shown
as the edit's chapters, never as something the system detected, and are never handed to an agent.

## Result

Applied on Oct 24 at engine `65247ba3` (the freeze: #275 and #276, half-time), unchanged, all 40
seeds simulated through `runs/slot.sh` on two workers.

**Seed 8076 wins with 69.9**: 4-1, both sides scored (contested). Goals 5 x 3 = 15, contested 4,
saves 15 x 1 = 15, shots on target 20 x 1 = 20, set pieces 7 x 0.5 = 3.5, passing moves 62 x 0.2 =
12.4. Pass completion 80.8%; football-sense mean rank 14.5 against the pool's bar of 20.79.

**Gates:** 15 of 40 seeds pass all four. G1 contract 39 (seed 8074 fails P2: the away keeper
accelerates at up to 23 m/s² over frames 78379 to 78383, about 52:15, an engine defect reported,
not part of this rule); G2 completion 31; G3 football sense 20; G4 goals 35.

| Seed | Score | Goals | On target | Saves | Set pieces | Moves | Completion | FS mean rank |
|---|---:|---|---|---:|---:|---:|---:|---:|
| 8076 | 69.9 | 4-1 | 14-6 | 15 | 7 | 62 | 80.8% | 14.5 |
| 8069 | 65.7 | 3-0 | 9-7 | 13 | 15 | 81 | 87.5% | 17.1 |
| 8085 | 60.1 | 3-0 | 7-7 | 11 | 13 | 78 | 87.6% | 15.3 |
| 8080 | 59.5 | 4-1 | 10-3 | 8 | 9 | 75 | 83.2% | 19.7 |
| 8053 | 59.1 | 3-0 | 11-3 | 11 | 13 | 73 | 85.8% | 20.5 |

**The edit:** 17.0 minutes (1,022 s) in 40 segments, inside the target with no adjustment. Chapters:
the five goals (11:24, 18:43, 21:39, 32:19, 40:01), 15 saves, shots, corners, a free kick, passing
moves, the kick-off, 45:00 and the end. All five goals fall in the first half, so the second half of
the edit is saves and chances. The segments, chapters and render commands are in
[demo-match-8076.json](demo-match-8076.json).

**Half-time at the freeze.** This rule was written when the engine had no half-time; at `65247ba3`
the referee ends the first half (the `half_time` event, 2700.04 s here) and the second half kicks
off 5.8 s later, still without a change of ends, so the rule's fixed directions hold. The always-in
45:00 segment therefore shows the real whistle and the restart. The rule reads no `half_time` event
beyond ending a passing move at it, as any other event does.

**Render checks:** filled in when the segments are rendered.
