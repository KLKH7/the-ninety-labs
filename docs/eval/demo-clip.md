# Demo clip: pre-registered choice of the match footage

Status: **pre-registered, not yet applied.** The rule is fixed here, before any candidate from its
range is rendered or watched. (Seed 8001 is outside it: it was the demo seed for v1 and v2, was
watched, and the engine was fixed on it.) It is applied once at the final freeze commit, and its output is recorded below. If the
footage then has a defect, that is reported and fixed in the renderer; the footage is not swapped
for a better-looking seed.

The live demo's condensed full match is chosen and cut by its own rule: [demo-match.md](demo-match.md).

**Rubric:** UX and presentation (the 2-minute video's footage, `docs/video-script.md`), and honest
claims: the clip shows what the system does on footage chosen by a rule, not on the best take.

## The rule (`scripts/demo_clip.py`)

1. **Seeds 8002 to 8050, in order.** Seed 8001 was the demo seed for v1 and v2 and has been watched, so
   the rule starts after it. No training, validation, targeted-round or test run uses 8002 to 8050,
   so the detector has never seen this footage, and it is not a test seed, which stays
   uninspected.
2. **Simulate the first half** (45 minutes) of each seed at the freeze commit.
3. **The window** is the first 60 s of match time, starting at a multiple of 5 s from kick-off,
   that holds all of:
   - a goal at least 15 s into the window, so its build-up is on screen;
   - a set piece other than a kick-off (a corner, free kick or throw-in);
   - at least 3 passes.
4. **The first seed with such a window is the demo clip.** The selection uses the engine's events
   only. Whether the detector finds the passes is never part of the choice: what it detects on this
   clip is what the video shows and the evaluation reports.

## The render

The broadcast cut is on (the dead-ball cut of #180), the stadium is `broadcast` (a crowd and dressing;
the default `plain` stands scored 2/10 with the blind critic, lesson 185), and hardware GL is used, since this clip is
footage, not data.

**Kits:** `kit_contrast=broadcast` (#209). A seed's own draw may be the training hard case
`low`, and demo v1 (seed 8001, not in the rule's range) drew it: black against navy, which Kian found too similar to follow.
The demo's kits are drawn from the seed under a stated rule, never picked by eye:
- the two outfield shirts meet WCAG 2.1's 3:1 contrast floor for graphical objects (SC 1.4.11);
- unless one shirt is white, black or grey, they are at least 60° apart in hue.

The low-contrast kits stay in training only.

```bash
uv run ninety-render --seed <seed> --start <start> --seconds 60 --set dead_ball_cut=true --set kit_contrast=broadcast --set stadium=broadcast --mp4 --gpu --out runs/demo/seed<seed>
```

Then `uv run ninety-validate runs/demo/seed<seed>` and `uv run ninety-render-check runs/demo/seed<seed>`.

## Result

Filled in when the rule is applied at the freeze commit:
- the commit;
- the seed and window;
- the qualifying events;
- the render checks;
- what the detector found on it.
