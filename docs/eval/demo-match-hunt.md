# Demo match, re-cut: the footage hunt (seed 8080, Oct 26)

Status: **applied Oct 26. It replaces the edit of [demo-match.md](demo-match.md) for the demo's seed 8080.**
The match stays the same: seed 8080, engine `65247ba3` (unchanged on main), London Athletic 4-1
Lisbon Esportes. The edit is what changed: which stretches of the 90 minutes are shown.

## Why

Kian watched the first cut (34 segments, demo-match.md's rule) and called it unwatchable for three
reasons:
- aimless passes and poor keeper distribution, for example a 53 m ball to nobody at 25:20 and the
  keeper's 5 m pass straight to a forward;
- keepers catching with no dive and no clear contact;
- cuts that landed on the worst bits rather than the play.

demo-match.md's rule windows every shot, save and set piece, whatever surrounds it, so it shows
whatever the match did next to them. This re-cut is done the way a director picks highlights. It
scores every window for how it plays on screen, and keeps only the clean ones.

## What it is, honestly

This is an editorial choice made from the answer key. A broadcast director does the same with the
pictures. Nothing on the live path reads it:
- vision, the stats it feeds and the agents see only the rendered pixels of the segments shown;
- the chapters are the edit's, made from these picks, and are never shown as detections or handed
  to an agent (as in demo-match.md).

It does not touch the engine. It changes what is shown, never what happened. The failure modes it
avoids (aimless long balls, lost keeper passes, odd catches) are still in the match, and they stay
in the engine backlog.

The weights are *design*, set by eye against Kian's complaints, and they were set after watching
this match's first cut. This is a presentation choice, stated as one. It is not a pre-registered
rule.

## The scorer

[scripts/footage_hunt.py](../../scripts/footage_hunt.py) reads a 90-minute run's `events.jsonl`
and `frames.jsonl`.

**Windows.** A window starts as one side gains the ball: a turnover, an interception, a restart, or
a completed pass. It ends:
- 3.5 s after a shot;
- 1 s after the ball goes out, or after the ball is lost;
- just before a pass is struck, or as a pass arrives;
- 12 s after a goal.

Each window is 10 to 40 s of picture once the renderer's own dead-ball cuts are taken out
(`ninety.render.edit.cuts`). The match has 22,007 such windows.

**Score.** The sum of the values of the moments inside the window:

| Moment | Value |
|---|---|
| completed pass | +0.35 |
| completed pass that gains at least 10 m | +0.6 more |
| completed pass into the final third | +0.8 more |
| completed pass into the box | +1.5 more |
| failed pass | -1.5 (-0.3 for an aimed ball into the box) |
| aimless failed pass over 25 m (no intended receiver), or a keeper's pass lost | -4 and **flagged** |
| ball over 25 m straight out of play | -2.5 and **flagged** |
| shot | +4; on target +3; blocked +1; from inside the box +1 |
| save with a dive | +8 |
| catch at 0.3–1.8 m height, within 1.2 m of the keeper | +1.5 |
| any other catch (over the head with no jump, or off the body) | -9 and **flagged** |
| goal | +25 |
| successful tackle or interception | +0.4 |
| foul | -0.5 |
| corner or free kick in the final third | +1 |
| each second the ball sits still in play (under 1.5 m/s) | -0.25 |
| each second of dead ball still on screen | -0.15 |

**Selection:**
1. **Always in:** every goal, with the best window that ends 12 s after it (its build-up, at least
   12 s); the kick-off (the first 14 s); the half-time whistle and card (45:00, 10 s before to 9 s
   after); full time (the last 12 s).
2. **The picks:** windows with no flagged moment and a score of at least 4, densest first (score per
   second, weighted by the square root of the score). No two segments are within 12 s of each
   other, so no jump is a few seconds long. They fill up to 18 minutes.
3. **The reserve:** the next clean windows down to a score of 1.5, mostly passing moves of 5 to 14
   completed passes.

On 8080 this gives 36 picks (12.5 min) and 37 reserve windows (8.3 min). All 73 were rendered.

**What the match itself allows.** The whole match has one diving save (01:16). Every other on-target
save is a flat-footed catch, mostly with the ball over the keeper's head (z ≈ 2.7 m) and no jump, so
the scorer keeps all of those out. It also flags 65 bad moments across the 90 minutes. Clean footage
is scarce. That is an engine finding, not one an edit can fix.

**Which version is which.** v1 (below, "Result (v1)") cut seed 8080 and is what
[demo-match-hunt-8080.json](demo-match-hunt-8080.json) records: 73 candidates rendered, 51 chosen.
v2 is the script on `main`; it was run on 8080 (64 candidates, not rendered) and on the demo seed
8324 (Result (8324)). Every count of rendered and checked clips, and every scorebug and goal reading
below, comes from runs on the render pods and the Mac, run locally and not committed (the footage and
its reports are gigabytes).

**What this footage is not.** The demo match is a director's pick from the answer key, so no number
measured on it (stats, detection rates, the scorebug) generalises; the measured results are on the
held-out sets named in EVALUATION.md. On 8080 the v1 edit shows the match's only diving save and no
carry into the box in 16 minutes, because the engine at the freeze produced almost none (below); that
went to the engine backlog and is what the demo-only engine v2 (#403) addresses.

## v2 (Oct 26, after Kian's notes on the first re-cut)

Three changes, all in `scripts/footage_hunt.py`; the engine is not touched.

1. **Never cut mid-action.**
   - A window opens only where no pass or shot is in flight. A flight runs from the strike to the
     first touch by anyone (the engine's possessor) or the next event. The one exception is the
     moment a side receives a ball it has won.
   - A window closes only once the play has resolved: a pass has arrived and nobody plays the ball
     on for 2.5 s; a shot is over (2.5 s after its first touch); the ball is dead (+1.5 s); or a
     goal's celebration has run (+12 s).
   - The first cut's 12:49 example was h8's 54 m ball at 103 km/h, cut away in flight. It was hit to
     nobody: the keeper collected it and then kicked it out. The re-cut leaves that whole stretch out.
2. **Spectacular passing**, for a completed pass:
   - long (30 m or more): +1.5;
   - a switch of play (30 m or more across): +1.5;
   - through the lines (5 or more opponents between the passer and the target; +1 for 4): +2;
   - in behind (it lands beyond the second-last defender, gaining 8 m or more): +2.5.
3. **Carries and take-ons.** A carry is the stretch where one player touched the ball last, until
   it is struck or touched by someone else (the engine names a possessor only on touch frames).
   - A carry of 10 m or more: +1, plus 0.1 a metre beyond 10 (up to +3).
   - A take-on: a defender within 2 m and goal-side, then more than 1 m behind the carrier, who still
     has the ball and has gone forward: +3 each.
   - A carry into the box: +2.
   - **Must-show moments:** diving saves, take-ons and through balls each get their best clean
     window if no pick already covers them.

**What 8080 has** (`carries.json`), over 90 minutes:
- 23 carries of 10 m or more, 2 of them over 20 m;
- 9 take-ons;
- no carry into the box.

Kian's "they only pass" is the engine, not the edit. v2 shows 5 of the 9 take-ons; the other 4 sit
next to a flagged moment.

**v2 on 8080:** 64 candidates (21.3 min), with an auto-pick of 42 segments (16.1 min). It is not
rendered yet: the final demo may move to an engine-v2 seed. The script and the Mac kit
(~/ninety-notes/footage-hunt/kit) take any seed.

## Result (v1)

**Rendered.** All 73 candidates were rendered on two RunPod RTX PRO 4500 pods at main `6b275a4b`,
with the same renderer bytes as `eb6bd41d` (renderer 0.5.19), and all 73 passed `check_clip`. The
flags are 8080's: broadcast stadium and kits, `dead_ball_cut`, `edge_stingers` (one stinger across
every join), `views=tactical`, and crowd and whistles in each mp4.

**Vision.** It ran on every candidate with main's live_job, using the frozen ours-freeze (broadcast)
and ours-tactical (views, tiles) weights, then the join.

**The edit.** It is the auto-pick, unchanged unless Kian vetoes a segment: all 36 picks plus the
best-scoring reserve windows up to 16 minutes.
- 51 segments, 16.2 minutes (972.9 s).
- Chapters: the 5 goals (21:32, 37:24, 44:31, 67:08, 70:36), the diving save (01:16), one clean
  catch (74:37), 9 shots, a free kick, 31 passing moves, the kick-off, half-time and full time.
- The segments, chapters and render commands are in
  [demo-match-hunt-8080.json](demo-match-hunt-8080.json).
- No segment contains a flagged moment except the goals' own build-ups. The 21:32 goal comes from a
  keeper dispossessed after a long ball, and its window starts as the keeper receives it.

**Read from the pixels of the new edit** (no truth):
- the scorebug reads 0-0 at the start and holds 4-1 at the end;
- its five changes fall on the five goals;
- reconciled with vision's goals: 3 confirmed, 2 added from the scorebug.

**Superseded.** The 34-segment edit in [demo-match-8080.json](demo-match-8080.json) stays in the
repo as the first cut.
