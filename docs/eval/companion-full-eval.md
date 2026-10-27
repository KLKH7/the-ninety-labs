# The Ask, graded against the answer key (seed 8324)

Every fan question in `ninety/eval/ask_grade/intents.json` (22 intents, at least 10 paraphrases each, the phone's chips marked) asked at 10:00, 33:50, 45:00, 60:00, 85:00 and full time through the Ask's code path (`companion_match.code_match_answer`), each answer graded by `ninety/eval/ask_grade` against the simulator's ground truth: over the footage when the answer says so, else over the whole match. The tolerances were committed before the first graded run (`tolerances.json`, commit 3766efbe). The footage shows 20.9% (1129 s of 5400 in the 46 clip windows) of the match.

**The headline is the core pass rate**: an answer passes the core when it is answered (a verified reply, not a "can't"), relevant (its lead sentence carries the intent's metric), correct (within tolerance of the truth) and no false "not known" (no "can't" while the insights hold the facts). Each other check is its own column: no_future (a real leak: a minute past now said, or a cited fact, or a cited aggregate's source fact, timed after now), span_clipped (the answer's span ends by now; a span to the current minute bin's end with every cited fact before now fails only this), coverage_honest (a figure from part of the match says "in the footage"), natural (no "footage shown", "Esportes's", bare ranges, lower-case starts, "a London Athletic player") and consistent (the same headline as the intent's other paraphrases at that time). The CI ratchet holds every column separately.

## Core pass rate per intent

| Intent | main | #424 |
|---|---|---|
| score | 68% | 68% |
| scorers | 44% | 44% |
| winning | 46% | 46% |
| on_top | 0% | 67% |
| possession | 0% | 83% |
| passes | 0% | 0% |
| completion | 0% | 0% |
| shots | 0% | 0% |
| on_target | 0% | 0% |
| territory | 79% | 79% |
| corners | 0% | 0% |
| out_of_play | 0% | 0% |
| momentum | 0% | 89% |
| best_home | 0% | 0% |
| best_away | 0% | 0% |
| best_overall | 0% | 0% |
| fastest | 0% | 0% |
| distance | 0% | 0% |
| why_goal | 0% | 0% |
| key_moments | 22% | 22% |
| unmeasured | 0% | 0% |
| tactics_chip | 64% | 64% |
| **all** | **15%** | **25%** |
| chips | 36% | 40% |

## Every check, all answers

| Check | main | #424 |
|---|---|---|
| **core** | 15% | 25% |
| answered | 49% | 60% |
| relevant | 64% | 68% |
| correct | 12% | 23% |
| no_false_unknown | 46% | 57% |
| no_future | 97% | 98% |
| span_clipped | 78% | 99% |
| coverage_honest | 16% | 29% |
| natural | 80% | 91% |
| consistent | 69% | 72% |
| all checks | 3% | 21% |

## Each check per intent (main)

| Intent | core | answered | relevant | correct | no_false_unknown | no_future | span_clipped | coverage_honest | natural | consistent |
|---|---|---|---|---|---|---|---|---|---|---|
| score | 68% | 86% | 86% | 68% | 86% | 100% | 100% | – | 48% | 64% |
| scorers | 44% | 74% | 82% | 44% | 74% | 100% | 100% | – | 67% | 56% |
| winning | 46% | 46% | 46% | 46% | 46% | 100% | 100% | – | 76% | 33% |
| on_top | 0% | 17% | 33% | 0% | 17% | 97% | 88% | – | 83% | 44% |
| possession | 0% | 0% | 75% | 0% | 0% | 100% | 100% | – | 100% | 80% |
| passes | 0% | 0% | 0% | 0% | 0% | 100% | 100% | – | 100% | 89% |
| completion | 0% | 29% | 0% | 0% | 29% | 98% | 79% | 0% | 97% | 67% |
| shots | 0% | 86% | 86% | 0% | 86% | 100% | 30% | 0% | 96% | 85% |
| on_target | 0% | 65% | 0% | 0% | 65% | 98% | 41% | 0% | 98% | 54% |
| territory | 79% | 88% | 79% | 79% | 88% | 97% | 28% | 90% | 12% | 79% |
| corners | 0% | 92% | 92% | 0% | 92% | 100% | 23% | 0% | 100% | 92% |
| out_of_play | 0% | 46% | 46% | 0% | 46% | 100% | 62% | 0% | 100% | 60% |
| momentum | 0% | 27% | 82% | 0% | 27% | 91% | 82% | – | 73% | 51% |
| best_home | 0% | 15% | 61% | 0% | 15% | 88% | 86% | 0% | 85% | 80% |
| best_away | 0% | 26% | 83% | 0% | 26% | 99% | 86% | 0% | 74% | 74% |
| best_overall | 0% | 33% | 92% | 0% | 33% | 89% | 78% | 0% | 67% | 71% |
| fastest | 0% | 0% | 83% | 0% | 0% | 100% | 100% | – | 100% | 75% |
| distance | 0% | 0% | 92% | 0% | 0% | 100% | 100% | – | 100% | 92% |
| why_goal | 0% | 83% | 21% | 0% | 83% | 100% | 100% | – | 93% | 92% |
| key_moments | 22% | 92% | 92% | 22% | 92% | 85% | 85% | – | 37% | 86% |
| unmeasured | 0% | 100% | 85% | 0% | – | 100% | 100% | – | 85% | 30% |
| tactics_chip | 64% | 64% | – | – | – | 95% | 63% | – | 72% | 41% |

## Each check per intent (#424)

| Intent | core | answered | relevant | correct | no_false_unknown | no_future | span_clipped | coverage_honest | natural | consistent |
|---|---|---|---|---|---|---|---|---|---|---|
| score | 68% | 86% | 86% | 68% | 86% | 100% | 100% | – | 100% | 64% |
| scorers | 44% | 74% | 82% | 44% | 74% | 100% | 100% | – | 100% | 56% |
| winning | 46% | 46% | 46% | 46% | 46% | 100% | 100% | – | 100% | 33% |
| on_top | 67% | 100% | 100% | 67% | 100% | 100% | 100% | – | 100% | 64% |
| possession | 83% | 83% | 83% | 83% | 83% | 100% | 100% | 100% | 100% | 90% |
| passes | 0% | 0% | 0% | 0% | 0% | 100% | 100% | – | 100% | 89% |
| completion | 0% | 29% | 0% | 0% | 29% | 98% | 100% | 0% | 97% | 67% |
| shots | 0% | 86% | 86% | 0% | 86% | 100% | 100% | 0% | 99% | 85% |
| on_target | 0% | 65% | 0% | 0% | 65% | 98% | 100% | 0% | 98% | 54% |
| territory | 79% | 88% | 79% | 79% | 88% | 97% | 100% | 90% | 92% | 79% |
| corners | 0% | 92% | 92% | 0% | 92% | 100% | 100% | 0% | 100% | 92% |
| out_of_play | 0% | 46% | 46% | 0% | 46% | 100% | 100% | 0% | 100% | 60% |
| momentum | 89% | 96% | 100% | 89% | 96% | 98% | 100% | – | 96% | 87% |
| best_home | 0% | 15% | 61% | 0% | 15% | 88% | 100% | 0% | 85% | 80% |
| best_away | 0% | 26% | 83% | 0% | 26% | 99% | 100% | 0% | 74% | 74% |
| best_overall | 0% | 33% | 92% | 0% | 33% | 89% | 100% | 0% | 67% | 71% |
| fastest | 0% | 0% | 83% | 0% | 0% | 100% | 100% | – | 100% | 75% |
| distance | 0% | 0% | 92% | 0% | 0% | 100% | 100% | – | 100% | 92% |
| why_goal | 0% | 83% | 21% | 0% | 83% | 100% | 100% | – | 93% | 92% |
| key_moments | 22% | 92% | 92% | 22% | 92% | 85% | 86% | – | 38% | 86% |
| unmeasured | 0% | 100% | 85% | 0% | – | 100% | 100% | – | 85% | 30% |
| tactics_chip | 64% | 64% | – | – | – | 95% | 100% | – | 87% | 41% |

Answers per column: main 1554, #424 1554.

- **main**: f34652ed (with #427), cached insights (runs/demo-8324-final/final-work/insights.json)
- **#424**: 4ab06e1e (claude/fervent-mcclintock-303a76), insights rebuilt with its code from runs/demo-8324-final (--rebuild-insights with --rebuild-extra), answers re-graded with this PR's rules (--replay)

## The model path (Foundry gpt-4.1-mini Companion and Judge), on a 10% sample

Run on f9cd73d6 (main 382996dc's Ask) on Oct 27 after Kian approved spend; $1.50 cap per run; three runs, $0.17, $0.23 and $0.21 ($0.61 in all). The table is the third run, re-graded with the current rules and truth (--replay; no new calls). The shared deployment was throttled (HTTP 429) through every run while other sessions called it; the grader backs off on a 429, and those waits count against the Ask's own 10 s timeout as they would on the phone, so "model timeout" is mostly throttling. The sample is stratified by intent: 10% of each intent's (question, time) pairs. Each model answer (`companion_match.answer_match` with the published Companion and the Judge) is graded beside code's answer to the same question. Parity: the same headline. A fallback is code's answer shown in place of the model's, with its reason. Cost is the tokens the service reported, at ninety/eval/latency_cost.PRICES.

| | all sampled | not throttled |
|---|---|---|
| answers | 167 | 119 |
| core pass, model path | 23% | 24% |
| core pass, code, same questions | 16% | 15% |
| headline parity | 57% | 39% |
| fallback rate | 62% | 47% |
| latency p50 / p95 | 6.9 s / 10.0 s | 5.0 s / 9.8 s |
| cost | $0.210 ($0.0013 an answer) | |

Fallback reasons (all sampled): model timeout 48; model: unanswerable 45; not one of the checked sentences of the facts it cites 10; the Judge: unsupported fact 1.

## The 10 worst answers (main), verbatim

1. **territory**, 33:50: “who's been camped in the other half”  
   → “a London Athletic player has taken the most opponents out of the game with passes from minute 20 to minute 34: 4 opponents in 1 pass.”  
   fails: relevant, correct, coverage_honest, no_future, span_clipped, natural, consistent; flags: lowercase start, a <club> player
2. **completion**, 33:50: “passing accuracy so far”  
   → “London Athletic made 4 passes with no open teammate further forward from minute 1 to minute 34.”  
   fails: relevant, correct, coverage_honest, no_future, span_clipped, consistent
3. **on_target**, 33:50: “how many times has the keeper been tested”  
   → “London Athletic played most through the centre: 60% of their passes from minute 20 to minute 34 started there.”  
   fails: relevant, correct, coverage_honest, no_future, span_clipped, consistent
4. **territory**, 85:00: “who's been in the attacking third more”  
   → “a Lisbon Esportes player has taken the most opponents out of the game with passes from minute 72 to minute 86: 4 opponents in 1 pass.”  
   fails: relevant, correct, coverage_honest, span_clipped, natural, consistent; flags: lowercase start, a <club> player
5. **best_away**, 10:00: “who's played well for Lisbon”  
   → “Nothing from minute 1 to minute 11 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
6. **best_away**, 33:50: “who's Lisbon's most involved player”  
   → “Nothing from minute 20 to minute 34 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
7. **best_home**, 45:00: “who's played well for London”  
   → “Nothing from minute 32 to minute 46 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
8. **best_home**, 60:00: “who's London's most involved player”  
   → “Nothing from minute 47 to minute 61 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
9. **best_overall**, 10:00: “motm?”  
   → “I can't answer that one from this match's tracking. Try one of these:”  
   fails: answered, relevant, correct, no_false_unknown, consistent
10. **completion**, 10:00: “who's passing better”  
   → “London Athletic made 4 passes with no open teammate further forward from minute 1 to minute 11.”  
   fails: relevant, correct, coverage_honest, span_clipped, consistent

## The 10 worst answers (#424), verbatim

1. **territory**, 33:50: “who's been camped in the other half”  
   → “a London Athletic player has taken the most opponents out of the game with passes from minute 20 to minute 34: 4 opponents in 1 pass.”  
   fails: relevant, correct, coverage_honest, no_future, natural, consistent; flags: lowercase start, a <club> player
2. **best_away**, 10:00: “who's played well for Lisbon”  
   → “Nothing from minute 1 to minute 11 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
3. **best_away**, 33:50: “who's Lisbon's most involved player”  
   → “Nothing from minute 20 to minute 34 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
4. **best_home**, 45:00: “who's played well for London”  
   → “Nothing from minute 32 to minute 46 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
5. **best_home**, 60:00: “who's London's most involved player”  
   → “Nothing from minute 47 to minute 61 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
6. **best_overall**, 10:00: “motm?”  
   → “I can't answer that one from this match's tracking. Try one of these:”  
   fails: answered, relevant, correct, no_false_unknown, consistent
7. **completion**, 33:50: “who's passing better”  
   → “I can answer about goal build-up, players, style, referee and the team sheets.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
8. **completion**, 33:50: “passing accuracy so far”  
   → “London Athletic made 4 passes with no open teammate further forward from minute 1 to minute 34.”  
   fails: relevant, correct, coverage_honest, no_future, consistent
9. **distance**, 85:00: “who's the hardest working player”  
   → “Nothing from minute 72 to minute 86 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
10. **fastest**, FT: “who's hit the highest speed”  
   → “Nothing from minute 76 to minute 90 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent

Times: 10:00, 33:50, 45:00, 60:00, 85:00, FT. Regenerate with `uv run python -m ninety.eval.ask_grade.report` (command in its docstring).
