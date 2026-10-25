# Highlights: which saves make the reel, and the measurement that decides if the rule goes live

*Status: pre-registered, nothing built or measured.* Written 2026-10-23 on branch
`claude/highlights-plan` from main at 0af9fd4 (committed on a7ed113, whose engine and vision
constants cited here are unchanged), before any highlight code exists and before any
shot speed, distance or flight time from vision has been compared with the answer key. Results
go at the end, under "Outcome", without editing what is above. A change to a rule or a number
above is an amendment: a new dated section that says what changed and why, never an edit.

**What it is for:** a highlights reel from the condensed demo match (`docs/eval/demo-match.md`)
that a fan would put on YouTube: every goal, and the saves worth watching, but not the shot that
rolls into the keeper's arms. Each one is named the way fans name it (a rocket, a screamer, a
reflex save), and only when a number vision measured earns the word.

**Rubric:** UX and presentation (the reel is the spine of the 2-minute video); real-world impact
(clipping highlights from detected events instead of by hand). Honest claims: the rule is fixed
here before any number from it is seen.

## The rule

1. **A goal** is always in the reel (a confident detected shot with `outcome: goal`).
2. **A save** (a confident detected shot with `outcome: on_target`, `docs/eval/shot-outcomes-plan.md`
   rule 5) is in the reel when the ball reaches goal faster than a keeper can complete a dive:
   its **flight time** `T = d / v` is at most `T_DIVE = 0.97 s`, where
   - `d` is the straight-line distance from where the shot was struck to the centre of the goal
     it attacks, in metres (the quantity GROUNDING D3 and lesson 138 use for shot range), and
   - `v` is the shot's `ball_speed_kmh` from vision (`ninety/vision/events.py`, `_speed_kmh`),
     in metres a second.
3. **Everything else** (off target, blocked, and saves with `T > T_DIVE`) is left out. The reel
   says how many saves it left out.
4. Each highlight carries why it is in (`goal` or `beat_the_dive`), `d`, `v` and `T`, and the
   ids of the events it rests on. Confident means at or above the fact-checker's `MIN_CONFIDENCE`
   (0.5), as for every graphic.
5. The live path reads detected events only; nothing here opens the answer key
   (`tests/test_live_reads_no_truth.py` is extended to cover it).

### Why one flight time and not separate speed and distance cuts

The aim was to combine speed and distance. Flight time is that combination in one physical
quantity, and it is the quantity a keeper actually faces:

- a fast shot from range and a slower shot from close in can be equally hard to save, and
  `d / v` ranks them the same;
- a slow shot from range takes long enough for the keeper to get across, and is left out;
- it needs one threshold, and that threshold has a published source (below). Separate cuts need
  two: we found a published speed distribution for saved shots, but **no published save or
  conversion rate for on-target shots by distance** (searched: Opta and The Analyst articles,
  StatsBomb, MDPI, arXiv, ResearchGate; only all-shot conversion or goals-by-zone counts turned
  up). A distance cut would be *design* with nothing behind it.

What the rule means in kilometres an hour (`v = d / 0.97 s`), worked out from the rule and not
from any of our data: from 6 m a save is in at 22 km/h or more; from 11 m (the penalty spot), at
41 km/h; from 17 m, at 63 km/h; from 25 m, at 93 km/h.

## The sources

| Constant | Value | Source | Status |
|---|---|---|---|
| `T_DIVE` | 0.97 s | Ibrahim, Kingma, de Boode, Faber and van Dieën, *The Effect of Preparatory Posture on Goalkeeper's Diving Save Performance in Football*, Frontiers in Sports and Active Living 1:15 (2019), [doi:10.3389/fspor.2019.00015](https://doi.org/10.3389/fspor.2019.00015), CC BY 4.0: 10 elite male keepers diving to low balls from their fastest preparatory posture averaged 0.972 s (high balls 1.050 s). We take the low-ball figure, the faster of the two, so a save is in only if the ball beat even the quickest dive measured. | *verify*: the paper's Methods define dive time from the light signal to ball contact (reaction included), but its Figure 1 caption says from movement onset; the target ball hung 1 m in front of the goal line, and how far to the side it hung is not given in the text read |
| context only | saved shots 85.52 ± 32.20 km/h (mean ± SD, 318 shots); all shots 80.00 ± 34.95 km/h (1,305) | *The Role of Shot Velocity in Advanced Post-Shot Metrics: Evidence from the UEFA European Football Championships*, Data 11(2):39 (2026), [doi:10.3390/data11020039](https://doi.org/10.3390/data11020039), CC BY: men's EURO 2024, StatsBomb open data, Table 2. Its velocity is "the average velocity of the ball". | not used by the rule; quoted so a reader can see where the cut falls against real saves. *verify*: how the average velocity was computed from event data is not stated in the text read |
| `d` | distance to the goal's centre | GROUNDING D3, lesson 138 | as used in the engine |
| `MIN_CONFIDENCE` | 0.5 | `ninety/agents/factcheck.py` | existing gate |

Rows go into `docs/GROUNDING.md` when the code lands (R1's file; one other person reviews):
`T_DIVE` with the citation above, the rule's use of `d` (D3's quantity), and each label's
threshold with its source (the labels section below).

**Not a source:** the engine's own save rates by distance (GROUNDING P15: 3% at 8 m to 98% at
30 m). They are an outcome of our keeper model, a held-out check (AGENTS.md), and using them to
set the rule would fit the reel to our own engine.

**Known differences in what is measured**, reported by the measurement below, not corrected for:
- The engine's `ball_speed_kmh` is the 3D speed at the strike (`ninety/sim/engine.py`, `shoot`).
  Vision's is the median ground-plane speed over the first `SHOT_LOOK_S` (0.3 s) after the strike,
  with the ball taken to be on the ground (ball height is not yet known on the live path).
- The EURO paper's speed is an average over the flight, so lower than a launch speed for the same
  shot. It is context, not the threshold, so this does not move the rule.
- `T = d / v` assumes the ball keeps its speed and flies straight at the goal's centre. The true
  flight time (below) is measured from the ball's own path.

## The measurement (offline grading, before the rule goes live)

Ground truth is used here only to grade, as for every detector (AGENTS.md).

- **Clips:** the validation split of the shot-outcome set, seeds 910001 to 910008
  (`docs/eval/shot-outcome-set.md`). Its test split, 910009 to 910016, is scored once, at a frozen
  commit, after the rule is final. No test clip is opened before then.
- **Detections:** the demo detector's detected shots on those clips (`ninety/vision/events.py`).
  The measurement does not need the shot-outcome detector: every detected shot is matched to its
  true shot with the existing matcher (`ninety/eval/event_score.py`, `match`, strict rules), and
  the answer key says which were saves.
- **For each matched shot, reported:** vision `v` against the truth's `ball_speed_kmh`; vision `d`
  against the truth's (from the true shot's `x, y`); the shot's `x` and `y` against the truth's,
  along and across the pitch (for the labels' markings); vision `T` against the truth's `d / v`;
  and against the **true flight time**, from the truth's `frames.jsonl`: the frames from the strike to
  the first frame the ball reaches the goal line or is touched by anyone, over `FPS` (25). Each as
  the median and 95th percentile of the absolute error, and the signed median (bias). Ground shots
  and lifted shots (the true ball's peak height over 0.5 m before the line, the scorers' cut-off)
  are reported apart, and on saves alone as well as all shots.
- **Agreement:** for each matched true save, whether vision's rule (2) and the same rule on the
  truth's `d` and `v` put it on the same side of `T_DIVE`. Count, share, 95% Wilson interval, and
  every disagreement listed with its numbers.
- **Unmatched shots** are counted (missed true shots, false detected shots), not dropped silently.
- The script and its output: `ninety/eval/shot_flight.py`, `docs/eval/shot-flight.md` and `.json`.

## The go/no-go rule (fixed now)

The filter goes live in the reel only if both hold on validation:

1. the 95th percentile of `|T_vision − T_truth|` (truth by `d / v`) on matched saves is at most
   **0.10 s** (*design*: about a tenth of `T_DIVE`, two and a half frames at 25 fps), and
2. vision and truth agree on at least **90%** of matched saves (*design*).

If either fails, the reel shows **every** confident detected save, ordered by `T` (fastest
first), with `v` on the graphic marked as an estimate, and the reel says the speed filter is off.
`T_DIVE` and these two gates are not changed after the measurement. If fewer than 20 true saves
are matched, the gates are not judged: the filter stays off and the count is reported.

## What the reel is graded on (offline)

The same rule over the answer key's events makes the true reel for each clip. The detected reel
is scored against it: precision and recall of highlights, a highlight matching when its shot
matches (the matcher above), each miss and false highlight listed. On validation while building;
on the test split once.

## Labels: the words fans use, each from a number on screen

A highlight in the reel gets one headline label, the first of these that applies, drawn as the
big word on its graphic with the number that earned it underneath ("ROCKET · 112 km/h"). Code
computes the label; the agents may use the word, and the fact-checker rejects a label word the
code did not give that highlight (as it rejected "powerful" for a 59 km/h shot,
`docs/eval/ablation-agents.md`). With none of them, the label is plain `GOAL` or `SAVE`.

| Label | Applies to | When | Source |
|---|---|---|---|
| `THUNDERBOLT` | a goal | both `SCREAMER` and `ROCKET` apply | the word is *design*; its two parts are sourced below |
| `SCREAMER` | a goal | struck outside the penalty area (Law 1: more than 16.5 m from the goal line, or more than 20.16 m from the goal's centre line across the pitch) **and** `d` at least 25 m | outside the area is Opta's long range: 31.7% of 2024/25 Premier League shots, 4.2% of them scored against 14.7% inside (David Segar, [*Why are players shooting less from long range this season?*](https://www.premierleague.com/en/news/4272809), premierleague.com, 29 March 2025). The 25 m is *design* (the "25-yarder" of commentary is 22.9 m; 25 m keeps the word for the far end of long range) |
| `LONG-RANGE` | a goal | outside the penalty area, `d` under 25 m | Opta's long range, as above |
| `ROCKET` | a goal or a save | `v` at least 100 km/h | the Bundesliga's broadcast graphic calls a shot over 100 km/h "fast": its peak speed on 25 Hz optical tracking from when it leaves the foot, headers and blocked shots left out; 263 players had at least one in about 215 matches of 2022/23, 3.47 each on average (Haschemi, Eluère, Lourier and Poveda-Panter, [*Bundesliga Match Facts Shot Speed*](https://aws.amazon.com/blogs/machine-learning/bundesliga-match-facts-shot-speed-who-fires-the-hardest-shots-in-the-bundesliga), AWS Machine Learning Blog, 3 November 2023) |
| `REFLEX SAVE` | a save | `T` at most 0.41 s: the ball arrived before even the slowest footballer's choice reaction would have let him move | GROUNDING P12 (0.32 to 0.41 s, [Lesiakowski 2017](https://wnus.usz.edu.pl/cejssm/file/article/download/8620.pdf)) |
| `TAP-IN` | a goal | struck inside the goal area (Law 1: within 5.5 m of the goal line and 9.16 m of the goal's centre line) | Law 1 |

- **Areas, not radii** (lesson 138): "outside the penalty area" and "inside the goal area" are
  tested on the shot's `x, y` against the markings, the quantity Opta and Law 1 use; only the
  25 m is a distance, `d`.
- **Speed in the source's quantity:** the Bundesliga's figure is the peak speed after the foot,
  which for a struck ball is its speed just after the strike; vision's `v` is the median over the
  first 0.3 s, the nearest quantity we have. The measurement below reports the gap to the engine's
  launch speed.
- **No label near its line:** a highlight gets a label only if its number clears the threshold by
  more than the measured 95th percentile error of that number (`v`, `d` or `T`, on validation,
  below), or its `x, y` lies further inside or outside the marking than the 95th percentile error
  of the shot's position. Closer than that, it is plain `GOAL` or `SAVE`. So a label is never
  shown on a shot vision cannot place on the right side of its line, and until the measurement is
  done no label is shown at all.
- **Labels are graded** as the reel is: each label's precision and recall against the same label
  computed from the answer key, on validation and then on the test split once. Rare labels
  (`SCREAMER`, `THUNDERBOLT`) may have no true case in the set; that is reported, not padded.

### Football words left out, and why

Each needs something vision does not measure yet, so using it would be a guess on screen:

- **"Chip", "lob":** the ball's height in mid-flight (not known on the live path; PR #226 is
  an open draft). Where the ball crossed the goal mouth ("top bins", "off the bar") is added in
  Amendment 1 below.
- **"Header", "volley", "bicycle kick", "half-volley":** which body part struck it and whether the
  ball was in the air.
- **"Curler", "banana shot":** the ball's curve (it could come from the path's curvature later;
  not measured now).
- **"Free-kick goal", "solo goal", "counter-attack goal":** how the attack started, the amendment
  below.
- **"Worldie", "wondergoal":** no number defines them; they stay out rather than be applied by
  taste.

## Not in this plan

- **How each attack started** (corner, throw-in, free kick, open play, kick-off): it needs its own
  threshold for "led to the shot", to be sourced in an amendment before that code is written.
- **Placement and the keeper's position:** a fast shot straight at the keeper is easier than `T`
  says. Vision does not yet give where a shot crosses the line or the keeper's reach. The rule
  says so on screen only through `T`; it does not claim a save was hard.

## Depends on

- `claude/shot-outcomes` (unmerged, unmeasured): without detected `outcome`s, rules 1 and 2 find
  nothing. The measurement above does not wait for it; the live reel does.
- The shot-outcome set's validation clips rendered.

## Amendment 1 (2026-10-23): where the ball crossed the goal mouth, and the woodwork

Added before this plan was committed and before any number in it was measured. It adds three
labels and one way into the reel; nothing above changes.

### Why it can be done from one camera

A pixel fixes the ball only along the camera's line of sight. Vision places a ball by assuming it
is on the grass (`ninety/vision/events.py`), which is wrong in the air. At the goal line the ball's
`x` is known: the goal line. Vision's camera is a full 3D fit from the markings (pan, tilt and
focal length on a fitted gantry, `ninety/vision/pitch.py`), so the line of sight from the ball's
pixel meets the plane of the goal line at one point, which gives the ball's `y` (across the goal)
and `z` (height). The posts and bar are fixed by Law 1 (7.32 m by 2.44 m).

### The labels

| Label | Applies to | When | Source |
|---|---|---|---|
| `TOP BINS` | a goal | the ball's centre crossed the line in an upper corner: above two thirds of the bar's height (1.63 m) and more than 1.22 m from the goal's centre line (the outer thirds) | the goal mouth cut in thirds each way is the nine-zone grid of penalty analysis ([Northwestern Sports Analytics, World Cup shoot-outs 1982 to 2018](https://sites.northwestern.edu/nusportsanalytics/2020/12/04/the-numbers-behind-penalty-shootout-in-world-cup/)); which zones count as a corner is *design*: the grid is a convention, and no source fixes where a corner starts |
| `BOTTOM CORNER` | a goal | below one third of the bar's height (0.81 m) and in an outer third | as above |
| `OFF THE BAR`, `OFF THE POST` | any shot | the ball met the crossbar or a post (Law 1 woodwork, `ninety/sim/engine.py`, `woodwork`) | Law 1 |

- **On the graphic:** a goal's placement is a second tag beside its headline label
  ("SCREAMER · TOP BINS"). A woodwork shot's headline is `OFF THE BAR` or `OFF THE POST`.
- **Into the reel (new rule 2b):** a confident detected shot that hits the woodwork is in the
  reel, whatever happened next. Rule 3 now leaves out off-target and blocked shots that did not.
- **Saves get no placement tag** in this amendment: the keeper meets the ball in front of the
  line, where its `x` is not known.
- **In our engine** a ball off the woodwork always comes back out (`woodwork` reverses its
  speed along the pitch), so "in off the post" never happens and is not a label.

### How vision finds them (fixed now)

1. **The crossing frame:** the first frame the shot's ground-plane ball position is beyond the
   goal line (the shot-outcome plan's rule 1 frame) and the frame before it.
2. **Method A (one camera, the goal plane):** in both frames, the ball's pixel ray meets the plane
   of the goal line; the crossing point is the two points weighted by where the ground-plane
   positions put the line between them (linear, as the engine itself does at the line).
   **Method B (the ball's flight):** where the ball's fitted 3D path (PR #226, if merged and
   validated by then) crosses the goal line. Whichever has the lower 95th percentile crossing
   error on validation (below) is used; a tie, or #226 not merged, means A.
3. **Woodwork:** within 3 frames of the crossing (*design*), the ball's direction along the pitch
   reverses, with its crossing point within the ball's radius plus a post's (0.17 m) plus the 95th
   percentile crossing error of a post or the bar, and no player within `events.CONTROL_M` of
   the ball (a keeper's touch is a save, not the woodwork).

### How the error is measured (offline, the same clips and split as above)

- **The true crossing point:** from the truth's `frames.jsonl`, the ball's centre where it crosses
  the goal line, interpolated linearly between the frames either side (the engine's own method).
- **Crossings measured:** every matched shot whose true ball crosses the goal line within 2 m of
  the goal frame (*design*: off-target shots that cross wide or over add samples near the posts
  and bar), each method, reported as median and 95th percentile of the absolute error in `y` and
  in `z`, and the signed median, ground and lifted shots apart.
- **The true woodwork hits:** the engine's own test (`woodwork`) re-run on the true frames.
- **Graded:** each placement label's precision and recall against the same label from the true
  crossing point; woodwork precision and recall against the true hits; each failure listed.

### Go/no-go (fixed now)

- **Placement labels:** shown only on a crossing point inside its zone by more than the 95th
  percentile error on both `y` and `z` (as every label above); not shown at all if fewer than 20
  crossings are matched on validation.
- **Woodwork:** goes live only if, on validation, at least 10 true hits are matched and the
  precision is at least 90% (*design*). The shot-outcome set's windows were chosen for goals and
  saves (`docs/eval/shot-outcome-set.md`), so they may hold too few woodwork hits; then the
  woodwork stays off and the count is reported. A set chosen for woodwork would be its own
  pre-registered window list, not an edit of that one.

## Amendment 2 (2026-10-24): how the attack that led to the shot started

Added after the plan was merged (#278) and before any origin was measured. The plan's "Not in this
plan" asked for this amendment before the code; the code was drafted alongside it, in the same pull
request, and nothing has been run on a clip. It adds one field to each moment, `origin`, and the
words a caption may use for it; nothing above changes.

*Revised 2026-10-24, before this amendment merged and before any origin was measured:* Kian's
restart detector (#320 kick-offs, #325 corners, goal kicks, throw-ins, free kicks and penalties;
`ninety/vision/restarts.py`) sees restarts directly, including the free kicks and penalties the
first version could not give. The rule now takes a detected restart first and keeps the inference
from the ball going out as the fallback. The source and the absence of a time threshold are
unchanged. The same revision names a moment's side and player only when the side was told surely
(below).

*Revised again 2026-10-25, before merge, after a development run on seed 8080's answer key over
the demo edit's segments (no detection, no measurement):* every origin came out null, because the
rule stopped at event types it did not know. Main's vision now writes `possession_change` (#289),
and the answer key also has presses, touches, tackles, interceptions, fouls and offsides, and set
pieces with no kind. The rule now reads those (rules 1 to 5 below). The same run found a wrong
origin: a ball seen going out before a cut was read as the restart after it, when the condensed
match's cut had skipped minutes and a foul; nothing before a cut is read now. With those fixes the
run gave 7 open-play origins that agree with the full answer key and 6 nulls (set pieces whose
stoppage the edit cut away, which only the restart detector can see), and no wrong origin.

### Honest status of "pre-registered" (added at merge-queue review)

This amendment was not fixed before the code. It was written together with the code, revised once
for Kian's restart detector, and revised a second time after a development run on seed 8080's
answer key (above), which changed the rules: the possession_change, press, tackle, foul and
kindless set piece rules (1 to 5 and 4a) and the nothing-across-a-cut rule. Seed 8080 is the demo
match, not a sealed seed and not a validation or test clip. The rules below are the ones as of the
pull request; they are frozen from here, and nothing has been scored on a validation or test clip,
so "pre-registered" here means *stated in this plan before any validation or test scoring*, not
before every look at output.

### The source, and why there is no time threshold

StatsBomb's open data specification (*Open Data Events v4.0.0*, statsbomb/open-data on GitHub,
`doc/`) defines a possession as a period of play in which the ball is in play and one team
controls it, and gives every event a play pattern: the event was part of the passage of play that
followed a corner, a free kick, a throw-in, a goal kick or a kick-off, or none of those ("Regular
Play"). A same-team restart starts a new possession (its example: a blocked pass that goes out for
the same team's throw-in). So "this corner led to the shot" means the shot is in the possession the
corner began. That is the source's definition, and it needs no number of seconds or passes: adding
one would be our own threshold with nothing behind it, so there is none.

### The rule (fixed now)

Walking back from the shot through the confident detected events, the shooting side's possession:

0. **began at the restart the detector saw**, if the side took it: a `kickoff` is `kick_off`
   (Law 8, after a goal or at the start of a half), a `set_piece` is its `restart` (`corner`,
   `throw_in`, `goal_kick`, `free_kick`, `penalty_kick`). A restart taken by the strike itself (a
   direct free kick, a penalty) may be timed up to a frame after the shot (25 frames a second, the
   broadcast's precision) and counts. A restart the other side took, or a set piece with no kind,
   means the side's start was not seen. The rules below apply only where no restart was seen;
1. **goes on** through its own completed passes and its own earlier shots (a rebound); a press on
   the carrier and a touch that does not take the ball (`pressure`, `deflection`) change nobody's
   possession and are passed over;
2. **began in open play** (`open_play`) where the ball was won back: an opponent's failed pass,
   the side's interception or won tackle, or a `possession_change` to the side that no stoppage
   came just before (one that did is the restart's, and the stoppage before it decides);
3. **began at a restart** at a detected ball out of play (`ninety/vision/events.py` names the side
   that touched it last), if the restart is the shooting side's, by the Laws:
   - over a touchline: a **throw-in** (`throw_in`) for the side that did not touch it last (Law 15);
   - over the goal line the side attacks, touched last by a defender: a **corner** (`corner`, Law 17);
   - over its own goal line, touched last by an attacker: a **goal kick** (`goal_kick`, Law 16);
   - a ball out over a goal line straight after a detected goal is that goal (below);
   - which line it went over is the one it is further over, as the engine judges a ball out at a
     corner flag (`ninety/sim/decisions.py`, `restart_cost`);
4. **began at a kick-off** (`kick_off`) after a goal the other side scored (Law 8);
4a. a **set piece of no kind** (the answer key's) is read from what stopped play before it: a ball
   out of play (rule 3), or the other side's foul (`penalty_kick` inside the area the side
   attacks, Law 14, else `free_kick`, Law 13) or offside (`free_kick`, Law 11). A foul with no set
   piece of the side after it was play on (advantage), and gives nothing;
5. otherwise its start **was not seen**: `origin` is null. That covers an opponent's completed pass
   or shot, the side's own failed pass, the side's own goal, a restart that was the opponent's, no
   event before it, and any broadcast cut between an event and the shot: nothing before a cut is
   read (a restart after it is the detector's to see, rule 0).

**Free kicks, penalties and the kick-offs that start a half** come only from the restart detector
(rule 0): nothing else in the video shows them. StatsBomb's "From Keeper" and "From Counter" are
not tried.

**Side.** A moment's `team` and `player` are null unless the shot's side was told surely
(`factcheck.side_known`, the gate every writer uses), since a track id (`h-t12`) names a side too.
`origin` still compares the detector's sides; how often that is wrong is part of what is graded.

### What the captions may say

A caption may say a moment came from a corner, a throw-in, a goal kick, a free kick, a penalty, a
kick-off or a set piece only when its `origin` says so (`factcheck.origin_reasons`). Counter-attacks
are never given, so their words are refused for every moment. "Top corner" and the other placement
words stay refused as before. A caption names no player whose side was not told surely
(`captioner.unsure_players`), and one naming a team on an unsure side is held by the confidence gate.

### Graded (offline)

The same rule over the answer key's events gives each true shot its true origin. The answer key's
`set_piece` carries no kind, so for it the kind comes from #299's `restart_kind` where its event
sets give one, else from the fallback rules. On the matched
shots of the measurement above (validation, then the test split once): how often the detected origin
equals the true one, per origin, with Wilson intervals, each disagreement listed, and how often the
detected origin is null where the truth has one.

## Outcome

*Not yet measured.*
