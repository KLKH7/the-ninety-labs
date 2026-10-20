# Defect sweep: reviewer brief

You are reviewing synthetic football matches made by a match engine (The Ninety Labs). The
goal is to find every defect a football fan, coach or TV viewer would notice: places where it
does not look like real football. Be a harsh, specific critic. Do NOT fix anything, do NOT edit
any repo file; only write your output file.

## Tactical view (top-down contact sheets)

Each PNG is a 4x4 grid = 16 consecutive seconds of one match. Each panel shows the moment at
the END of that second, with a 1-second trail behind every player (faint line) and the ball
(thin white line).

- Home outfield = red dots, home keeper = orange. Away outfield = blue dots, away keeper = cyan.
  Number = shirt (1 GK, 2 RB, 3 RCB, 4 LCB, 5 LB, 6 RCM, 7 CM, 8 LCM, 9 RW, 10 ST, 11 LW).
- White ring = the player in possession. White disc = ball (bigger = higher in the air).
- Arrows = actions struck during that second, from strike point to end point:
  yellow = completed pass, magenta = failed pass, white = shot.
- Header: seed, match clock mm:ss, possessor id (h = home, a = away), ball height z (m), event
  types that happened in that second.
- Home attacks LEFT-TO-RIGHT in the first half (goal at x=105, right). Away attacks right-to-left.
  Pitch is 105 x 68 m. Clips are 10 minutes, so all first half.

## Broadcast view (rendered TV frames)

Each PNG is 6 frames, 0.5 s apart, from a 3D broadcast render. Label = seed, match clock,
frame index in the clip. Full-resolution frames are in the clip's images/ folder
(images/00000.jpg ... at 25 fps), which you may Read for a closer look.

## Data you may query (optional, to confirm or measure what you see)

`runs/sweep/m/seed<N>/frames.jsonl` (one row per 1/25 s: ball x,y,z,vx,vy,vz; possessor;
players with id, team, role, x, y, vx, vy, heading, action, dive) and `events.jsonl` (pass, shot,
out_of_play, set_piece, etc. with t, player, receiver, x, y, end_x, end_y, outcome). frame index
= t * 25. For broadcast clips the clip folder has its own frames.jsonl with pixel boxes.
Use `uv run python` from the repo root
(`/Users/kianlakhani/the-ninety-labs/.claude/worktrees/agitated-bell-e11adc`). Keep queries
small; never load more than one match at a time; do not run the simulator or renderer.

## Starting taxonomy (use these type slugs; ADD NEW TYPES FREELY with a new slug)

Football sense:
- `bunching` - many players (both teams) crowd around the ball, leaving huge empty areas
- `static_teammates` - players stand still while their team attacks / has the ball
- `own_box_recycling` - passes go round in or near the team's own box with no progress
- `pass_out_unpressured` - a pass goes out of play with no opponent near the passer
- `chaser_wrong_way` - the nearest player to a loose ball moves away from it or does not go for it
- `keeper_stays_home` - keeper does not come out when he would clearly win the race to the ball
- `no_forward_runs` - attackers never run in behind / into space
- `line_shape_broken` - defensive line is not held: staggered, gaps, players out of shape
- `overlap_walkthrough` - two players occupy the same spot or pass through each other
- `ball_float_teleport` - ball hangs, jumps, or moves impossibly
Rendering (broadcast view):
- `foot_not_at_ball` - a touch/kick happens with no foot at the ball
- `spin_slide` - bodies spin, moonwalk, or slide without stepping
- `mirrored_text` - advertising board text reversed
- `lighting_blotch` - odd lighting, dark/bright pitch blotches
- `camera_framing` - camera loses the ball, cuts badly, frames empty grass

Other ideas to watch for: whole team out of position after a restart, both teams' shape
swapping, wingers abandoning width, nobody marking, players running off the pitch, absurd pass
choices (backwards from the opponent's box), shots from silly range, long dead-ball waits,
offside line nonsense, kit colours too similar, scorebug wrong, players' feet floating.

Do not flag things real football also does (players standing still at a dead ball or a set
piece is normal; a keeper staying home when an attacker would win the race is correct).

## Output

Write a JSON array to your assigned output file. One object per defect instance:

```json
{"seed": 7, "match_time": "03:12", "view": "tactical", "sheet": "seed7_t0192.png",
 "type": "bunching", "description": "12 players within 15 m of ball at halfway; both full-backs tucked in; right flank empty", "severity": 2,
 "players": ["h2", "a5"]}
```

severity: 1 = noticeable to an expert, 2 = a fan would notice, 3 = embarrassing on air.
List EVERY instance you see, not one per type: counts per type are what we rank by. A
sustained defect lasting several seconds is one instance with match_time = its start and
"duration_s". Be concrete about who (player ids) and where (pitch coordinates or area).

When finished, reply with a short summary: count per type, and the three worst moments.

Note: the tactical sheet header clock can read e.g. "01:60" (a rounding bug in the sheet tool,
not the product). Ignore it; do not report it.
