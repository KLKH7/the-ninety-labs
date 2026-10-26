# Ablation, third arm: one agent with the same tools and the same fact-checker (plan)

Written 2026-10-25, before any run of this arm was scored. Kian approved the run, after its cost estimate. Nothing below changes once a run has been scored; a change made after that is an amendment, dated, with its reason, and the [record](#record) lists every run started, scored or not.

## The question
The committed ablation ([ablation-agents.md](ablation-agents.md), seeds 21 and 33) compared one agent that airs what it writes against the multi-agent graph. A judge's fair objection is that the graph wins because it has a fact-checker, not because it has several agents. The third arm separates the two: **one agent, the same MCP tools, and the same fact-checker as the graph** (code checks, confidence gate, Judge, with rewrites on rejection). If it matches the graph, our claim for the extra agents is only cost; if the graph still wins, the agents earn their place. Either answer is reported.

## The arms
All three are run together, in one run, so they share the engine, the seeds, the Judge and the day.

1. **one agent**: the slice's Analyst writes the minute's claim, and it airs as written. This is the committed arm, run again.
2. **one agent + fact-checker**: the same Analyst, then `ninety/agents/slice.py`'s fact-checker: `check`, the confidence gate and the Judge. A rejection goes back to the Analyst with the reasons, at most `MAX_REWRITES` (2) times, and only a verified claim airs. This is the live path's single-agent fallback, unchanged.
3. **graph**: the workflow (moment Analyst, Tactician, Challenger, the fact-checking agent with the confidence gate and the Judge, Producer). This is the committed arm, run again.

The same inputs go to every arm:
- the minute's events inline, under a match id no server serves;
- the same published agents at their pinned versions;
- `gpt-4.1-mini`.

## Inputs, fixed now
- Simulator seeds **940001 and 940002**, minutes **1 to 5** of each: 10 minutes, for all three arms.
  - Why not 21 and 33: arms 1 and 3 have already been run and committed on them ([ablation-agents.md](ablation-agents.md)), and several agent prompts were compared on them, so a result there is not on unseen matches.
  - Why not 920001 and 920002: [EVALUATION.md](../EVALUATION.md) keeps them for confirming a change to an agent's instructions, once.
  - 940001 and 940002 appear nowhere else in the repo. They sit in the evaluation range (900000 and above, never rendered for training), and no agent has been run or scored on them.
- The engine at the run's commit (the frozen engine). The committed ablation ran on an older engine and other seeds, so its numbers are shown beside the new ones, never mixed with them.
- The output goes to its own files, `docs/eval/ablation-third-arm.{md,json}`, as the run writes them; the committed `ablation-agents.{md,json}` stay as they are.

## Metrics, fixed now
Each is per arm, from the same grader, with no new metric and none dropped.
- **Claims aired.**
- **False on air:** an aired claim that fails the code checks or the published Judge's grading call, split by which check caught it. This is the committed grader, unchanged.
- **Minutes with an insight**, and **minutes lost to a tool call** (an agent that calls the match tools while given its events inline fails that call).
- **Model calls**, and **cost**: estimated as model calls times the per-call price below (about 3,000 tokens in and 150 out, at the rates in [latency-cost.md](latency-cost.md)). The harness does not meter tokens, so this is an estimate, and the report says so.
- **Latency:** wall-clock seconds per minute of match.
- **Held and rejected** (arms 2 and 3): claims the fact-checker sent back, held, or let air after a rewrite.

## Known biases, stated now
- **The grader agrees with arms 2 and 3's filter.** They are graded by the same published Judge their own fact-checker asked, so a false claim on their rows is one the grader's second call disagrees with. The code checks are independent of it, and the table splits false claims by which check caught them.
- **The arms get different budgets:** one call a minute, then up to 3 Analyst calls and their Judge calls, then the graph's many calls. The table compares what each puts on screen at its own cost (both are given), not designs at a matched budget.
- **Live models vary from run to run.** One run is one sample; the report says so and claims nothing past it.

## Reading rule, fixed now
The rule compares the graph (arm 3) with arm 2, on true and false claims on air. Exactly one of the four outcomes holds, checked in this order:
1. **Arm 2 matches the graph:** within one true claim and within one false claim of it. The report then says the fact-checker does the work, and the graph's extra agents buy only coverage, at their cost. A difference of one either way is within what one run of live models varies by, so it is never read as a win.
2. **The graph wins:** not outcome 1, and either the graph airs at least as many true claims with fewer false ones, or more true claims at a false rate (false over aired) no higher than arm 2's.
3. **Arm 2 wins:** not outcome 1, and the same test with the arms swapped.
4. **Mixed:** none of the above (for example, more true claims but a higher false rate). The report gives the table and draws no winner.

Outcomes 2 and 3 cannot both hold: each needs the true count or the false count to move in its own direction. Arm 1, the unchecked agent, is in the table; it takes no part in the rule.

## Exclusions, fixed now
- **No minute is left out for its result.** A minute where an arm's model call fails (a service error, a timeout, an unreadable reply, a call to the match tools) counts for that arm as a minute with nothing aired, and the report lists why.
- **The run is void, and run once more, only if no model answered at all** (for example, the sign-in expired before the first call; the harness then writes no report). A run that wrote a report is the run, whatever it shows.
- An aired claim is graded once, by the grader above. No claim is regraded, relabelled or removed by hand.

## Cost stop, fixed now
The harness keeps a running estimate (all model calls, the grader's included, times the per-call price). If it reaches **$0.50** it starts no further minute. The report then says where the run stopped, and the rule is read on the minutes run, with that stated.

## What this does not claim
- One run on two matches, ten minutes each: the counts are a sample, not rates, and a difference within the rule's margin is reported as no difference.
- It compares designs at their own budgets, not at a matched number of calls. It cannot say the graph would beat a single agent given the graph's budget some other way, for example more rewrites.
- It is graded on simulator events, not on vision's detected events. It says nothing about how either design does on detections from video.
- The grader's Judge is the one the checked arms' fact-checker asked (the bias above). The code checks are the independent half of the grade.
- It does not test the Personalizer, the Producer's wording, or anything after the claim is chosen.

## Cost estimate (for Kian's approval)
- **Calls:**
  - arm 1: 10;
  - arm 2: 20 to 60 (an Analyst call and a Judge call a minute, plus up to 2 rewrites each);
  - arm 3: about 120 (the committed run used 120);
  - the grader: one Judge call per aired claim, about 45.
  - About **195 to 235 calls** in all.
- **Price:** at about 3,000 tokens in and 150 out a call, that is about $0.0014 a call: **about $0.15 to $0.50** for the run. It is billed to the project's Azure OpenAI deployment and logged in the report.

## Record
Every run of this plan, scored or not:
- **Commit `f8b53bbd`, 2026-10-25, seeds 21 and 33** (the seeds this plan named before the review). Stopped by hand before it finished, when the plan's review found the defects fixed above. Its output was not read, it wrote no report, and nothing was scored. Its model calls are billed. They were not counted, so the scored run's report gives an upper bound for them: a full run's estimate.

## Outcome
*Not yet run.*
