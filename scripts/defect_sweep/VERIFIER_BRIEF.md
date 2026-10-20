# Defect sweep: verifier brief

Reviewers watched top-down contact sheets of synthetic matches and reported defects. Your job is
to check, independently and sceptically, whether each claimed example is REAL, using the
numbers in the match data, and whether it is actually wrong compared with real football. Do NOT
edit any repo file. Do not run the simulator or renderer.

Repo root: `/Users/kianlakhani/the-ninety-labs/.claude/worktrees/agitated-bell-e11adc` (use
`uv run python` from there). Data per seed: `runs/sweep/m/seed<N>/frames.jsonl` (25 rows per s:
`t`, `ball` {x,y,z,vx,vy,vz}, `possessor`, `players` [{id, team, role, x, y, vx, vy, heading,
action, dive}]) and `events.jsonl` (`t`, `type`, `team`, `player`, `receiver`, `x`, `y`, `end_x`,
`end_y`, `outcome`, ...). Pitch 105 x 68 m; home attacks +x (goal at x=105) in these clips;
match_time mm:ss = t. Load one match at a time; stream lines rather than holding all if you
can.

What real football looks like is in `docs/GROUNDING.md` (cited sources). Check it before
calling something unrealistic: for example row R1 grounds restart waits (throw-in ~16 s, goal
kick ~29-30 s, free kick ~31-41 s, corner ~30 s), so a wait of that length is NOT a defect by
itself, while what happens during it (everyone frozen, nobody fetching the ball, the ball
jumping to the spot) may be. Also look at `ninety/sim/engine.py` if it helps explain the cause,
but judge by data.

For each example you are given:
1. Measure the claim from the data (distances, speeds, durations, counts) around the time.
2. Verdict: `confirmed` (the data shows it and real football would not), `partly` (the data
   shows something, but the description overstates it or part is normal football), or
   `refuted` (data does not show it, or it is normal football).
3. One line of the key numbers.
4. The likely engine or renderer area causing it (file and function if you can find it
   quickly; grep is fine), as a cause, not a fix.

Write a JSON array to your output file:
```json
{"type": "own_box_recycling", "seed": 23, "match_time": "04:33", "verdict": "confirmed",
 "evidence": "41 s spell, 17 passes all x<22, nearest away player median 24 m, away mean speed 0.6 m/s",
 "real_football": "build-up in own third under no press lasts ~5-15 s before progressing or going long",
 "likely_cause": "ninety/sim/decisions.py pass scoring ... (one line)"}
```
Then reply with a short summary of verdicts per type and anything that changes how the type
should be described.
