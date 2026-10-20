Review media for PR #156 (engine restarts). Synthetic match, seed 110, match time 0:18 to 1:18,
rendered with `uv run ninety-render --seed 110 --start 18 --seconds 60 --mp4` at commit d9adf76.
0:22 goal; players walk back and the ball is fetched from behind the goal; 0:38 kick-off once
Law 8's positions hold; 0:47 the ball goes out; it is fetched and the throw-in is taken at 1:02.

Second clip (owner feedback on the free kick): seed 103, match time 6:29 to 7:29, rendered at
commit 45a2d0d. 6:33 foul; the ball is fetched to the spot; the wall stands 9.15 m off; 7:04.8 the
free kick is struck once from its spot by the taker and goes in at 7:06.5; players walk back and the
kick-off is taken at 7:26.7. The ~31 s wait between foul and free kick is the grounded real wait
(GROUNDING R1); cutting it on screen is a separate renderer change.

## Overnight loop clips (branch at bca5579, merged with main 618fd7a)
`loop-bca5579/`: four 60 s clips (960 px, denoised for size) and their contact sheets (2 frames a second,
16 to a sheet), the sheets a fresh critic reviewed.
- seed7-0017-goalkick-goal-kickoff: goal kick fetched and taken (0:48.9), goal (0:51.3), walk back, kick-off (1:07.2)
- seed106-0235-throwin-freekick: throw-in fetched and thrown (2:37.8 to 2:57.7), foul (3:02.6), free kick shot 19 m out (3:34.1)
- seed106-0115-corner: corner wait and delivery (1:47.2)
- seed21-0045: the Coordinator's standard window (open play, then a throw-in wait from 1:32)
