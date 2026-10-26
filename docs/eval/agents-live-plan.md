# The agents live on the demo match: pre-registration

Written and committed on 2026-10-26, before any live call of `ninety/eval/agents_live.py`. Nothing
here changes after a score is seen; anything learned from the run goes into
[agents-live.md](agents-live.md) as a finding, not as an edit to this plan.

## Question

Does the multi-agent system work end to end, live, on the demo match's own detected events: the
right context reaches each agent, the Companion calls the right tools with the right arguments,
every aired claim is grounded in a fact id, the fact-checker holds or rejects what it should, and
the system recovers when a part fails?

## What runs

For each moment below, with the published Foundry agents at the versions pinned in
`ninety/agents/foundry_agents.json` (gpt-4.1-mini), signed in with `DefaultAzureCredential`:

1. **The graph** (`workflow.run_live`), on the moment's match minute: Producer templates, Analyst,
   Tactician, Challenger, fact-checker (code checks, confidence gate, Judge), Producer. Events are
   the demo bundle's detected events, inline under an id no server serves (lesson 90: the deployed
   MCP server serves the deployed image's matches, and through Foundry took ~50 s a minute). The
   minute's confident team-shape facts go to the writers as evidence (`shape`), as in the demo.
2. **The Companion** (`companion_match.answer_match`, production timeout 10 s, with the Judge),
   asked the moment's pre-registered fan question 20 s after the moment. Every insight tool it
   chooses is executed **through the real MCP server** (`ninety/mcp/match_server.py`, stdio, the
   match's precomputed insights in `NINETY_MATCH_DIR/insights/`), so each tool call is an MCP
   `call_tool` with its name, arguments and result size logged.

Every model call, tool call, trace step (handoff), verdict and aired text goes to one JSONL trace.

## Moments (rules fixed before looking at seed 8324's data)

From the bundle's detected events and its insights (`MatchInsights`):

| key | rule |
|---|---|
| `goal-1..n` | every goal fact (`facts["goal"]`), in time order; the graph runs the goal's minute |
| `line-break` | the confident line-break fact with the highest value (ties: earliest), not in a goal's minute |
| `overload` | the confident overload with the highest value (ties: longest `duration_s`, then earliest), not in a goal's minute |
| `quiet` | the minute with the fewest detected agent events (at least 3), with no shot or goal within 2 minutes either side (ties: earliest) |
| `half-time` | the last minute at or before 45 with detected events; the question is asked 5 s after its last event |

Two moments in one minute share one graph run.

## Expected tools (the pre-registered table)

`{club}` is the moment's club (the scorer's, the passer's, the overloading club's); `{other}` the
other club. Club names come from the bundle's fixture by code.

| moment | question | expected tool | argument rule |
|---|---|---|---|
| goal | What led to that goal? | `goal_build_up` | `minute_to` at or after the goal's minute; `club` null or `{club}` |
| line-break | Which pass cut through {other}'s lines just now? | `line_breaks` | window contains the moment's minute; `club` null or `{club}` |
| overload | Where are {club} outnumbering {other}? | `overloads` | window contains the moment's minute; `club` null or `{club}` |
| quiet | Has anything happened in the last few minutes? | `key_moments` | window contains the moment's minute |
| half-time | Who had more of the ball in the first half? | `possession` | `minute_from` at most 2; `minute_to` at least the asked minute minus 1 |

The Analyst in the graph is given its events inline, so its expected tool calls are **none**; a
call to the match tools fails that call (`foundry.ReadTheTools`) and counts as a wrong tool call.

## Scores

- **Tool choice**: right when the plan calls the expected tool in at most three calls
  (`companion_tools.right`, the rule of the held-out tool evaluation). **Arguments**: right when
  the expected tool's call, as the model wrote it (before `_calls` drops or defaults anything),
  meets the rule above. A plan the model never returned (timeout, service error) is counted apart,
  never as a wrong plan (lesson 131).
- **Context correctness** (code): the Analyst's inline events contain the moment's anchor event
  (goal moments: the goal's detected event); the Tactician's prompt carries every evidence id of
  its moment; the Companion's tool results contain the moment's target fact (goal: its goal fact;
  line-break and overload: the chosen fact; quiet and half-time: no target, not scored).
  **Analyst pick** (model): for a goal moment, the Analyst picks a moment whose evidence holds the
  goal's event.
- **Grounding**: every aired claim cites at least one id, and every cited id is one that agent
  was given (the moment's evidence, or the Companion's tool results). Target: 100 %; anything
  less is a bug.
- **Hold and reject**: verdicts per draft (verified, rejected, held), rewrites, and how each moment
  ended (insight aired, template stays).
- **Latency** per stage: each model call by role, each MCP call, each graph minute, each Companion
  answer (p50 and max).
- **Cost**: tokens as the service reports them, priced at `latency_cost.PRICES` (the dated Azure
  retail prices); stop when the run's estimate passes $4.

## Failure drills (expected outcomes fixed now)

| drill | injected | where | expected |
|---|---|---|---|
| Judge down | every Judge call raises a service error | graph on goal-1's minute + its Companion question | the Judge is retried once, every claim is **held**, nothing unverified airs, templates stay; the Companion answers with code's checked answer |
| Vision dropout | no detected events in the 60 s around goal-2 | graph on goal-2's minute | no template and no claim for the missing events; no aired claim cites a dropped id or says "goal" |
| Slow model | the Tactician answers after 65 s (budget 60 s) | graph on the line-break minute | the call times out, the claim is held, the templates stay, the minute completes |
| Slow Companion | the Companion's planner answers after 12 s (budget 10 s) | the overload question | code answers with its own checked answer, reason `model timeout` |

## Dry run and budget

Developed on the seed 8080 final bundle with at most 10 live model calls, then run once on the
seed 8324 bundle. Total model spend at most ~$5. The trace and report are committed unedited.
A2A is not part of this run (the Personalizer is off): said in the report.
