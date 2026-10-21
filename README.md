Review media for the restart-walk PR (lesson 174, branch engine/restart-walk). Synthetic matches.

The same minute of seed 200, 0:45 to 1:45, from two engines: main's (`807bde2`, drawn at main
`5b40c65`, whose engine is the same) and this branch's (`b090877`). The ball goes out for a corner at
0:47 and the corner is taken at 1:21 on both (R1's wait is drawn the same). Both drawn by the same
renderer (main's 0.5.5 camera, merged into this branch) with the dead-ball cut off, so the whole
stoppage shows; re-encoded at 960x540.

- `seed200-0045-corner-main.mp4`, `seed200-0045-corner-this-branch.mp4`: the minute on broadcast
  camera. On main the players creep into the area for the whole half minute and are still walking in
  when the kick is taken. On this branch they walk in, are set by about 1:05, and stand until the
  kick.
- `seed200-0045-main-sheet-NN.jpg`, `seed200-0045-this-branch-sheet-NN.jpg`: contact sheets, 2 frames
  a second, 16 to a sheet (8 s), left to right then top to bottom.
- `seed200-0047-main-trails.jpg`, `seed200-0047-this-branch-trails.jpg`: the attacking third from
  above, from the ground truth, one panel every 2 s from 0:49 to 1:21, each player with his trail
  over the 2 s before it (red home, blue away, orange and cyan the keepers, white the ball). A short
  trail is a creep, a long one a walk, none a player standing.

A fresh critic shown the main and this-branch versions without being told which was which (this
branch at `094c4e3`, whose corner plays out the same, both drawn by the earlier 0.5.3 camera)
preferred this branch's, slightly: the walk-in and the set area read as a corner, while the area
then stands still for about 16 s until the kick, which looks artificial (docs/eval/restarts.md,
"Walking to restart positions").
