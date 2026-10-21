# Blind critic: player bodies and motion, X against Y (seed 21, 5:40, 40 s)

Unblinded after the report: **X is 0.5.3 (#188), Y is 0.5.2 (main after #180).** The critic was given images and labels only, no code, and was told neither version was newer.

## Verdict (critic's words, condensed)

**X is better for bodies and motion, by a clear margin.**
- Y has one severity-4 and five severity-3 defects that X does not have.
- X has three extra defects of its own, all severity 2.
- Everything else is identical: the same animation clock and the same cadence at every speed.

The three clearest differences:

1. **Stature.** Y is X scaled uniformly by 0.914, so Y's players are 9% short.
   - Median standing height, hair included: X 1.83 m, Y 1.68 m. The goalkeeper is 1.85 m in X and 1.69 m in Y.
   - Against a 1.8 m pole projected at his feet next to the goal (image 600), X's keeper reaches the top and Y's falls about 10 cm short.
   - Evidence: `work/stature_goal_600.jpg`, `work/cu_a6_h2_350.jpg`.
2. **The running strike.** h7, images 169–173, at 3.4 m/s.
   - X: the plant foot is on the grass beside the ball.
   - Y: both legs trail behind and no foot touches the ground, 13–18 cm up for 5 frames.
   - Strike frames more than 6 cm off the ground: X 11%, Y 67%.
   - Evidence: `work/h7_strike_pairs_169.jpg`, `work/airborne_pairs.jpg`.
3. **Planted feet.**
   - X's boot stays on a pitch-fixed marker for 4 frames (a6, 319–322).
   - Y's creeps about 0.4 m while in contact, and a8 skids 0.21 m on touchdown.
   - h9's slow walk in Y shuffles: the rear toe slides about 25 cm. X holds within 1–2 px for 8–10 frames.
   - Evidence: `work/a6_feet_317zz.jpg`, `work/a8_feet_93z.jpg`, `work/h9_slowfeet_X.jpg`, `work/h9_slowfeet_Y.jpg`.

## Defects only in X (0.5.3), all severity 2

- **Jogging at 3–4 m/s** (images 566–581, 90–99) is a high-knee march, then long "power-walk" strides. At the run-to-walk switch (94→95) the swing leg jumps from knee-up to planted far ahead in one frame. Evidence: `work/h2_jog_566.jpg`, `work/h2_pop_92.jpg`.
- **Stopping** (316–322): h2 holds a crossed-legs mid-stride pose for 7 frames while the engine flickers between walk and stand. Evidence: `work/h2_twitch_316.jpg`.
- **Toe-off** (377→378, close-up): h9's push-off toe moves 13 px (about 11 cm) in one frame before lifting. Evidence: `work/h9_toeoff_372.jpg`.

## In both versions (not changed by #188)

| Severity | Images | Defect | Evidence |
|---|---|---|---|
| 4 | 498–509 | Throw-in: the arms snap overhead in one frame, the ball rises into the hands by itself, and the ball leaves with no throwing motion. | `work/a6_throw_496.jpg`, `work/throw_hands_505.jpg` |
| 3 | 350–455 | Statue close-up: standing players hold one pose for 4.2 s. | |
| 3 | 600–606 | A standing clearance: the foot passes the ball 3–4 frames before the ball leaves. | |
| 3 | 663–671 | Two bodies overlap, because their engine positions are 0.1–0.4 m apart. | |
| 2 | | The kicker's body spins about 85° and back. | |
| 2 | | White-kit blotches in close-ups. | |
| 1 | | Blob shadows. | |

The critic's top three fixes, assuming X:
1. The throw-in.
2. Strikes: ball contact timing, a planted support foot, no body spin.
3. Idle life in close-ups, then a real jog cycle for 2.5–4 m/s.
