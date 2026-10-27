# The agents live on the demo match (seed 8324)

The whole multi-agent graph and the Companion, called live on Microsoft Foundry (the published
agents, gpt-4.1-mini, signed in with `DefaultAzureCredential`, no key), at eight moments of the demo
match, on vision's detected events. Every handoff, model call, MCP tool call, verdict and aired text
is in one JSONL trace. The moments, questions, expected tools, scores and drills were fixed in
[agents-live-plan.md](agents-live-plan.md), committed and pushed (740c65c4, 19:57 EDT) before the first live
call. Run on 2026-10-27 02:35 UTC at d7f22790, on `runs/demo-8324-final/final-work` (built at b8bde434).

**In one line:** the right context reached every agent (8 of 8). The Companion chose the expected
tool 8 times in 8, and its arguments met the pre-registered rule 8 times in 8, but effectively
7: the half-time plan asked for minute 0, and code replaced that window with the default (a plan
flaw the rule missed; fixed in #418). Every claim that aired cites ids its agent was given. The
fact-checker let 1 graph claim in 8 on air; it held most of the rest because vision was unsure of
the side or the detection. All four failure drills recovered with nothing unverified on air, but
the pre-registered graph Judge-down drill never reached the Judge, so it was re-run on another
minute (lesson 281). 72 live calls cost $0.033.

## Results

| measure | result |
|---|---|
| Companion tool choice (expected tool, at most 3 calls) | **8/8** |
| Companion arguments (pre-registered rule, as the model wrote them) | **8/8** by the rule; **7/8** effective (half-time's minute 0 was replaced by the default window: see gaps) |
| Context: the moment's target fact in the Companion's answer prompt | **6/6** (quiet and half-time have no target) |
| Context: the goal's detected event inline to the Analyst | **5/5** graph minutes with an anchor |
| Analyst picked a moment holding the anchor event | **5/5** |
| Tactician prompt carried every evidence id of its moment | **8/8** |
| Analyst tool calls (expected none: events inline) | **0** |
| Grounding: graph claims aired, each citing only ids given | **1/1** |
| Grounding: Companion answers citing only ids its tools returned | **7/7** claims; the 8th (half-time) is code's abstention with no claim |
| Graph drafts (Tactician and Challenger) | 1 verified, 1 rejected, 11 held; 6 rewrites |
| Graph moments ending on air / template stays | 1 / 7 |
| Companion answers by the model, verified | 7 of 8 (half-time: model said unanswerable, code answered) |
| MCP tool calls | 94, every one equal to the in-process result |
| Model calls, tokens, cost | 67 (+5 extra drill), 65,676 in / 4,252 out as reported by the service; $0.0326 (+$0.0007) at the dated retail prices (2026-10-19) |

### Per moment

| moment | min | graph: anchor given / picked | graph drafts v/r/h | graph aired | Companion tool / args | target given | Companion answer (source, status) |
|---|---|---|---|---|---|---|---|
| goal-1 | 12 | yes / yes | 0/0/1 | template stays | yes / yes | yes | "London Athletic scored in minute 12." (model, verified) |
| goal-2 | 35 | yes / yes | 1/0/0 (1 rewrite) | "The goal scored by a-t18090 at 34:01 changed the scoreline in minute 35 and was immediately confirmed at 34:04, underscoring its impact on the match." | yes / yes | yes | "a Lisbon Esportes player scored for Lisbon Esportes in minute 35." (model, verified) |
| goal-3 | 76 | yes / yes | 0/0/2 | template stays | yes / yes | yes | "Lisbon Esportes scored in minute 76." (model, verified) |
| goal-4 | 85 | yes / yes | 0/1/1 (2 rewrites) | template stays | yes / yes | yes | "Lisbon Esportes scored in minute 85." (model, verified) |
| line-break | 89 | yes / yes | 0/0/1 (1 rewrite) | template stays | yes / yes | yes | "In minute 89, a Lisbon Esportes player played a pass that took 5 London Athletic players out of the game." (model, verified) |
| overload | 60 | – | 0/0/2 (2 rewrites) | template stays | yes / yes | yes | "London Athletic built 6 overloads from minute 46 to minute 61, most often in their middle third in the centre." (model, verified) |
| quiet | 26 | – | 0/0/2 | template stays | yes / yes | – | "In minute 15, a London Athletic player shot from 36 m out, where the posts were 8 degrees apart." (model, verified) |
| half-time | 45 | – | 0/0/2 | template stays | yes / yes | – | "Possession can't be split between the clubs yet: vision could not tell surely which side made most of the passes." (code, verified) |

### Latency per stage (warm: the API at minReplicas 1)

| stage | calls | p50 | max |
|---|---|---|---|
| Analyst (moment-analyst) | 11 | 1.4 s | 4.2 s |
| Tactician | 14 | 1.4 s | 2.0 s |
| Challenger | 10 | 1.4 s | 10.8 s |
| Judge | 10 | 2.3 s | 4.0 s |
| Companion (plan, answer) | 18 | 1.3 s | 2.8 s |
| MCP tool call (stdio, local) | 94 | <0.1 s | <0.1 s |
| one graph minute, end to end | 8 | 8.1 s | 19.4 s |
| one Companion answer, end to end | 8 | 5.7 s | 6.7 s |

**Cold vs warm Analyst.** `ninety-moment-analyst` carries the Foundry-hosted MCP tool, so Foundry
contacts the deployed API on every call, even when the events come inline and no tool is called.
With the API at minReplicas 0 (the 8080 dry run, 19:5x EDT) the one Analyst call took **56.3 s**
against a 60 s budget. With minReplicas 1 (this run) it took **1.4 s p50, 4.2 s max** over 11 calls.
The cold figure is a single call on another match; it matches lesson 90's 50.7 and 55.3 s.

## Failure drills (live)

| drill | injected | what happened | as pre-registered? |
|---|---|---|---|
| Judge down, graph (goal-2, min 35) | every Judge call raises a service error | Judge tried twice (one retry), claim **held** (`service`), template stays, minute done in 5.7 s. In the normal run this same minute aired a verified claim | yes, but **re-run on goal-2**: the pre-registered run on goal-1 never reached the Judge (a code check held its claim first: a ball speed vision measures only on ground passes), so it tested nothing (lesson 281). The re-run is labelled in its trace |
| Judge down, Companion (goal-1) | same | Judge tried twice, held; the phone shows code's checked answer (reason `judge service error; claim held back`) | yes |
| Vision dropout (goal-2) | no detected events in the 60 s around the goal (8 dropped) | the Analyst picked no moment; no template, no claim for the missing events; nothing aired says "goal" or cites a dropped id | yes |
| Slow model (line-break, min 89) | the Tactician answers after 65 s (budget 60 s) | cancelled at 60.0 s, claim held (`timeout`), template stays, minute done in 63.6 s | yes |
| Slow Companion (overload) | the planner answers after 12 s (budget 10 s) | cancelled at 10.0 s; code's checked answer within the budget (reason `model timeout`) | yes |

Trace excerpts for the video, one line per step: [agents-live/excerpts.txt](agents-live/excerpts.txt).
They cover goal-2 (draft, rejected for "under pressure" with no pressure event, rewritten, Judge
verified, aired), and each drill.

## Method

- `uv run python -m ninety.eval.agents_live --detected <detected.sided.jsonl> --insights <insights.json> --out <dir> --drills`
  ([ninety/eval/agents_live.py](../../ninety/eval/agents_live.py)); `--score` re-scores a trace offline.
- **The graph** is `workflow.run_live` (Agent Framework `WorkflowBuilder`): Producer templates,
  Analyst, Tactician, Challenger, fact-checker (code checks, confidence gate, Judge), Producer. The
  Ledger records every draft and verdict. One small change: `run_live` takes a `wrap` hook, so the
  harness can observe each published agent (latency, reported tokens, hosted tool calls) or inject
  a fault at the agent itself. The workflow's own guards and timeouts run unchanged.
- **The Companion** is `companion_match.answer_match` at its production 10 s budget, with the Judge.
  The model plans the tools and their arguments. Code runs each tool as an MCP `call_tool` to
  `ninety/mcp/match_server.py` (stdio, the bundle's insights in `NINETY_MATCH_DIR`). The model then
  picks a checked sentence citing fact ids, and the insight check and the Judge gate it.
- **Scores** come only from the trace and the plan (`score`); `tests/test_agents_live.py` checks
  them offline, and each rule's mutant fails a test.
- **Dry run:** 6 live calls on the seed 8080 final bundle ([agents-live/dry-8080](agents-live/dry-8080)).
  It found one harness bug (the trace's scope key overwrote the workflow's `moment` field; fixed
  before the real run, dry traces re-keyed).
- **Traces:** [agents-live/seed8324/trace.jsonl](agents-live/seed8324/trace.jsonl) (with
  `moments.json`, `score.json`, `tables.md`); the re-run drill in
  [agents-live/seed8324-judge-down-goal2](agents-live/seed8324-judge-down-goal2). Synthetic match
  data and the agents' prompts and replies only; no key or credential.

## Honest gaps

- **A demonstration, not a general measure.** Seed 8324 is the edited demo match (the director's
  pick, [demo-match-hunt.md](demo-match-hunt.md)), and its moments come from that cut. This run
  shows the system working live on the match the video shows; it does not measure how it does on
  matches in general.
- **A2A was not used.** The Personalizer (our A2A service) was off for this run; no agent called
  another over A2A.
- **No model agent called an MCP tool through Foundry here.** The Analyst got its events inline,
  because the deployed MCP server serves the deployed image's matches, not 8324 (lesson 90). The
  Companion's 94 MCP calls are real MCP, but code makes them on the model's plan, against a local
  stdio server, not the deployed one.
- **Little of the graph airs on this match.** 1 of 8 moments aired. The holds are the confidence
  gate working as designed: a side told with confidence at or below 0.96, or a detection below
  0.50 (11 held drafts). The graph reads the sided detections (`detected.sided.jsonl`), and
  `compact()` keeps the feed's side: 208 of the 371 agent events carry `team_source: id_feed` with
  side confidence 1.0, and the one claim that aired cites one of them. Every held event is one
  the player-ID feed did not name (`team_source` null, side confidence 0.0 to 0.88), checked event
  by event. It is not a wiring gap, and the gate is right to hold. On this footage, most graph
  moments keep their template graphic.
- **Raw track ids in graph text.** The aired graph claim names "a-t18090". The fact-checker checks
  that player against the cited events, but the graph's text is not rewritten into a fan-facing
  name. The broadcast INSIGHT bar uses the insight check, which bans track ids.
- **Goal answers restate the goal.** For all 4 goals, "What led to that goal?" got the goal fact's
  sentence ("Lisbon Esportes scored in minute 76.") rather than a build-up fact. On the 8080 dry
  run the build-up window held only the other club's facts (the condensed match cuts between
  segments just before a goal). We did not establish the cause on 8324.
- **The half-time question was answered over the wrong minutes.** The model asked for possession over
  minutes 0–45. Minute 0 is out of range, and `companion_match._calls` silently replaced the window
  with its default (31–45), so the model saw no first-half facts and said unanswerable. The
  pre-registered argument rule (minute_from at most 2) counted the plan right; the rule should have
  required minute_from of 1 or more. Fixed in a separate PR (minute 0 read as minute 1).
- **"Last few minutes"** was answered with a shot 11 minutes earlier: the tool's default 15-minute
  window, which the pre-registered rule accepts.
- **One run, eight moments.** The models are not deterministic, and there is no variance estimate.
  The ablation and failure table ([ablation-third-arm.md](ablation-third-arm.md),
  [failure-table.md](failure-table.md)) remain the evidence that the graph and fact-checker beat a
  single agent. This run shows the parts working live on the demo match, not a comparison.
- **Trace order.** The graph's steps are written when its minute finishes (the workflow's own
  trace), each with its own duration. The model and MCP rows are written as they happen.
- **Tokens** are the service's counts for every completed call. Failed or cancelled calls (the
  drills) are estimated and cost $0.
