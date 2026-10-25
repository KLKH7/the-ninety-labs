# Ablation, third arm: one agent with the same tools and the same fact-checker (plan)

Written 2026-10-26, before any run of this arm. Kian approved the run for 2026-10-27, after its cost estimate. Nothing below changes once a run has started; a change made after that is an amendment, dated, with its reason.

## The question
The committed ablation ([ablation-agents.md](ablation-agents.md)) compared one agent that airs what it writes against the multi-agent graph. A judge's fair objection is that the graph wins because it has a fact-checker, not because it has several agents. The third arm separates the two: **one agent, the same MCP tools, and the same fact-checker as the graph** (code checks, confidence gate, Judge, with rewrites on rejection). If it matches the graph, our claim for the extra agents is only cost; if the graph still wins, the agents earn their place. Either answer is reported.

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
- Held-out simulator seeds **21 and 33**, minutes **1 to 5** of each: 10 minutes. These are the committed ablation's seeds and minutes, so the two runs line up.
- The engine at the run's commit (the frozen engine). The committed ablation ran on an older engine, so its numbers are shown beside the new ones, never mixed with them.

## Metrics, fixed now
Each is per arm, from the same grader, with no new metric and none dropped.
- **Claims aired.**
- **False on air:** an aired claim that fails the code checks or the published Judge's grading call, split by which check caught it. This is the committed grader, unchanged.
- **Minutes with an insight**, and **minutes lost to a tool call** (an agent that calls the match tools while given its events inline fails that call).
- **Model calls**, and **cost**: tokens counted and priced at the Azure retail rates in [latency-cost.md](latency-cost.md).
- **Latency:** wall-clock seconds per minute of match.
- **Held and rejected** (arms 2 and 3): claims the fact-checker sent back, held, or let air after a rewrite.

## Known biases, stated now
- **The grader agrees with arms 2 and 3's filter.** They are graded by the same published Judge their own fact-checker asked, so a false claim on their rows is one the grader's second call disagrees with. The code checks are independent of it, and the table splits false claims by which check caught them.
- **The arms get different budgets:** one call a minute, then up to 3 Analyst calls and their Judge calls, then the graph's many calls. The table compares what each puts on screen at its own cost (both are given), not designs at a matched budget.
- **Live models vary from run to run.** One run is one sample; the report says so and claims nothing past it.

## Reading rule, fixed now
- **The graph wins** only if it airs at least as many true claims as arm 2 with fewer false ones on air, or more true claims at the same false rate.
- **Arm 2 matches** if it is within one false claim and one true claim of the graph; then the report says the fact-checker does the work and the graph's extra agents buy only coverage, at their cost.
- Anything else is reported as it falls.

## Cost estimate (for Kian's approval)
- **Calls:**
  - arm 1: 10;
  - arm 2: 20 to 60 (an Analyst call and a Judge call a minute, plus up to 2 rewrites each);
  - arm 3: about 120 (the committed run used 120);
  - the grader: one Judge call per aired claim, about 45.
  - About **195 to 235 calls** in all.
- **Price:** at about 3,000 tokens in and 150 out a call, that is about $0.0014 a call: **about $0.15 to $0.50** for the run. It is billed to the project's Azure OpenAI deployment and logged in the report.

## Outcome
*Not yet run.*
