Review media for the restart-walk PR (lesson 174, branch engine/restart-walk). Synthetic matches.

The same minute of seed 200, 0:45 to 1:45, from two engines: main's (drawn at `aea01f4`; its engine
is main's since `807bde2`) and this branch's (`0f23e9b`, engine as at `00d5c41`). The ball goes out
for a corner at 0:47 and the corner is taken at 1:21 on both (R1's wait is drawn the same). Both
drawn by renderer 0.5.9 (main's) with the dead-ball cut off, so the whole stoppage shows;
re-encoded at 960x540.

- `seed200-0045-corner-main.mp4`, `seed200-0045-corner-this-branch.mp4`: the minute on broadcast
  camera. On main the players creep into the area for the whole half minute and are still walking in
  when the kick is taken. On this branch they walk in, are set and marked by about 1:02, and stand
  until the kick. Here the corner is then played short at 1:26, and a foul at 1:27 starts a free
  kick's wait to the end of the clip (players standing: the dead-ball cut is off).
- `seed200-0045-main-sheet-NN.jpg`, `seed200-0045-this-branch-sheet-NN.jpg`: contact sheets, 2 frames
  a second, 16 to a sheet (8 s), left to right then top to bottom.
- `seed200-0047-main-trails.jpg`, `seed200-0047-this-branch-trails.jpg`: the attacking third from
  above, from the ground truth, one panel every 2 s from 0:49 to 1:21, each player with his trail
  over the 2 s before it (red home, blue away, orange and cyan the keepers, white the ball). A short
  trail is a creep, a long one a walk, none a player standing.

A fresh critic shown both without being told which was which preferred this branch's set-up,
clearly, and main's minute as a whole, clearly: this branch's 15 s of standing through the free
kick's wait after the corner read as a frozen game (docs/eval/restarts.md, "Walking to restart
positions").
