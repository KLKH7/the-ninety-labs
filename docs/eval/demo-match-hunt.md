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

## Result

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
