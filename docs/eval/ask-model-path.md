# The Ask's model path: step budgets, the Judge, the trace (demo match, seed 8324)

The phone's Ask in Live mode (the `x-ninety-passcode` header). The match Companion
(`ninety-companion-match:4`) plans tools, then picks one of code's checked sentences; until this change
the Judge (`ninety-judge:4`) then judged that sentence, all under one 10 s limit. An audit on Oct 27
found five problems with this harness. This report measures it and records what changed.

Agent definitions: `ninety-companion-match:4` definition `b06b66dd6637d0b5`, `ninety-judge:4` definition `2b04c8ad1ac3c950`.
The judge set (section 2) ran two local Judge definitions on the same model: the published
instructions (the same text as `ninety-judge:4`) and `judge.MATCH_INSTRUCTIONS`, which is not published.

Reproduce (the first two call Foundry and cost model tokens):

    uv run python -m ninety.eval.ask_model_path latency --insights <insights.json> --arm before|after
    uv run python -m ninety.eval.ask_model_path judge --insights <insights.json>
    uv run python -m ninety.eval.ask_model_path report     # writes ask-model-path/report.json

`<insights.json>` is the demo match's insight bundle (`seed8324-match`, the one the deployed Ask serves).
Raw rows: [ask-model-path/](ask-model-path/) (`latency-before.jsonl`, `latency-after.jsonl`,
`judge.jsonl`, `report.json`). The latency runs ran from a Mac against the Foundry project in North
Central US, so network time is a laptop's, not the Container App's.

## 1. Each model step's latency, and its budget

The samples are every model call on the demo match: 8 questions from the agents-live run (#417, same
published agent versions, its injected-fault drills left out), 3 asked here before the change and 3
after. The budget rule was set before reading these numbers: **1.5 × the step's p95, rounded up to
0.5 s** (*design*). The p95 is the nearest-rank value, so with this few samples it is the slowest call.

| step | n | p50 | p95 (= max) | budget (`companion.STEP_S`) |
|---|---|---|---|---|
| plan (match Companion) | 14 | 2.34 s | 3.47 s | 5.5 s |
| answer (match Companion; the player draft borrows it) | 14 | 1.02 s | 1.39 s | 2.5 s |
| Judge | 9 | 2.06 s | 3.95 s | 6.0 s |

Each path's steps sum under the 10 s an answer may take (`TIMEOUT_S`, kept as the backstop over the
whole answer and its tools): the match path's plan and answer 8 s, the player path's draft and Judge
8.5 s. A step past its budget gives code's answer with the step named in the reason
(`model timeout (plan)`). Before, a slow first step could eat the whole 10 s: the agents-live drill
that slowed the Companion answered in 10.04 s. Now a slow plan is cut at 5.5 s.

`tests/test_api_companion.py::test_the_step_budgets_are_the_measured_ones_and_fit_the_answers_limit`
re-derives the budgets from `report.json` and fails if `STEP_S` drifts from them.

**Not measured:** the player path (a question about one tapped player, answered by the player Companion). Its
draft borrows the answer step's budget (same model, a one-sentence reply from a smaller prompt).

## 2. The Judge on the match path

**What it could block.** On the match path the model's text must be exactly one of the checked
sentences code wrote for a fact it cites (`say_as`, v4). If the Judge rejected it, the phone showed
code's answer, which is another of those sentences and is never judged. So the Judge could only swap
one code sentence for another, never keep a wrong one off the screen.

**Labelled set.** 99 claims on the demo match's insight facts. The true claims are code's first
sentence for up to 4 confident facts of each kind (67). The planted claims are those sentences with
one defect each, up to 4 per defect kind (32): number, number in words, clubs swapped, "the home side",
a track id for the name, another fact's evidence, the minute, the direction. They come from
`ninety/eval/insight_claims.py`, the sample ordered by a sha256 of each fact's id (salted 8324). Every claim went through the code
check (`_verify`) and to the Judge twice, both as local definitions on gpt-4.1-mini: once under its
published instructions (written for events, ids like h7, home/away) and once under
`judge.MATCH_INSTRUCTIONS` (rewritten for insight facts: club names, names only from the Player ID
feed's `*_is` fields, `also` figures, minute ranges, counts of the tracked footage).

| claims | n | Judge rejects (event instructions) | Judge rejects (insight instructions) |
|---|---|---|---|
| true, code check passed (what the match path can air) | 66 | **2** | **0** |
| true, code check rejected | 1 | 0 | 0 |
| planted, code check rejected | 32 | 26 | 25 |
| planted, code check passed | 0 | – | – |

The code check caught every planted defect, so there was nothing left for the Judge to catch. Under
the published instructions, the Judge's two wrong rejects were "In minute 89, a London Athletic
player lost the ball with no teammate free further up the pitch" (it read the fact as not saying the
ball was lost) and "4 opponents in 1 pass" (it read the total as spread over passes).

**Choice: run no Judge on the match path; keep it where the model writes its own words** (a player
question, `ninety/agents/companion.py`). On this set the Judge caught nothing the code check missed
(no planted claim got past the code check). Under the instructions it is published with, it rejected
2 of 66 airable true sentences (3%). Each call costs about 2.1 s (p50) and $0.0006. Running it on the final
answer instead would put that wait and that false-reject rate on every Live answer, code's included,
to block nothing more. `MATCH_INSTRUCTIONS` fixes the false rejects (0 of 67) but is not published:
no live path needs it while the match Companion only picks code's sentences. If it ever writes its own
words again, publish it and gate that path with it.

**Also found:** some of code's own first sentences for confident facts fail code's own check, so
code never says them. Here 1 of 67 does ("lost the ball and had 2 players near it"). A superseded
sample (below) had 8 of 67: two offside margins, two pass-option lines, a 0–0 scorebug, a one-player
line break, a regain-to-shot and a shot angle. This is outside this change; it is listed as a
follow-up.

## 3. Before and after

Every model answer is one budget take, with a ~1,000–3,000-token prompt per step at gpt-4.1-mini's list
price (Azure Retail Prices, read 2026-10-19). Latency is the whole `answer_match` call.

| | questions | code fallbacks | p50 | p95 | cost per answer |
|---|---|---|---|---|---|
| before (plan, answer, Judge; one 10 s limit) | 11 | 2 (both "model: unanswerable") | 5.50 s | 6.67 s | $0.00195 |
| after (plan, answer; per-step budgets) | 3 | 1 ("model: unanswerable") | 4.21 s | 4.66 s | $0.00151 |

The same three questions, before → after: "What led to that goal?" 5.36 → 4.66 s; "Where are London
Athletic outnumbering Lisbon Esportes?" 5.49 → 3.34 s; "Who had more of the ball in the first half?"
2.00 → 4.21 s. The last went to code both times: the possession figure is held because vision could
not tell the sides apart, so the model declined and code's answer says why. After, its plan alone took 3.16 s; that is plan-step
variance, not the change. Three questions after are too few for a fallback rate. What the change
removes per model-answered question is the Judge's call, measured above: 2.06 s p50 (3.95 s p95) and
about $0.0006.

## 4. The rest of the harness

- **Match time clamped on the server.** A question is answered at the earliest of the time the phone
  sent, the room's playhead plus 2 s (GROUNDING I27), and the clip's end. Before any clock from the big
  screen, the playhead is 0. Tests: `test_a_phone_cannot_ask_past_the_big_screens_playhead`,
  `test_before_the_big_screen_sends_a_clock_nothing_has_been_shown`,
  `test_a_question_past_the_clip_is_answered_at_its_end`.
- **The budget is taken at the first model call**, so small talk and code's overview spend none
  (`test_small_talk_and_code_only_answers_spend_no_model_budget`). One question takes one, however many
  steps it runs (`test_a_model_answer_takes_one_from_the_budget_and_none_once_it_is_spent`).
- **One trace record per question** (`ninety/agents/telemetry.py`): path, Live or not, source, the
  reasons a draft was dropped, the tools, each model step's time, outcome and reported tokens, total
  tokens and cost, the asked and used match time. The viewer's words never reach it, only their length
  and a 16-hex sha256. With `APPLICATIONINSIGHTS_CONNECTION_STRING` set it is a `ninety.ask` span in
  Azure Monitor. Otherwise it is one JSON line in the console log, which the Container App's log keeps,
  and in `NINETY_ASK_TRACE` (default `runs/ask-trace.jsonl`). The deployed API does not set the
  connection string today, so its records are console log lines.

## Spend

$0.310 on model calls in all: latency before $0.0052 (8 calls), after $0.0045 (6 calls), the committed
judge set $0.112 (198 calls). Two earlier judge-set runs are not the committed rows:
- $0.077 on a run that hit its call cap. It gathered every call at once, so the cap discarded every
  answer (lesson 295).
- $0.112 on a complete run whose sample was drawn with `random.Random`, which the portability check
  (`tests/test_fmath.py`) bans in evaluation code. It was re-run with the hash order. That run gave
  the same conclusion: 3 of 59 true sentences rejected under the published instructions, 0 under the
  insight-fact ones, and no planted defect past the code check that was false.
