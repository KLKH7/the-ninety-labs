# The Ask, graded against the answer key (seed 8324)

Every fan question in `ninety/eval/ask_grade/intents.json` (22 intents, at least 10 paraphrases each, the phone's chips marked) asked at 10:00, 33:50, 45:00, 60:00, 85:00 and full time through the Ask's code path (`companion_match.code_match_answer`), each answer graded by `ninety/eval/ask_grade` against the simulator's ground truth: over the footage when the answer says so, else over the whole match. The tolerances were committed before the first graded run (`tolerances.json`, commit 3766efbe). The footage shows 20.9% (1129 s of 5400 in the 46 clip windows) of the match.

**The headline is the core pass rate**: an answer passes the core when it is answered (a verified reply, not a "can't"), relevant (its lead sentence carries the intent's metric), correct (within tolerance of the truth) and no false "not known" (no "can't" while the insights hold the facts). Each other check is its own column: no_future (a real leak: a minute past now said, or a cited fact, or a cited aggregate's source fact, timed after now), span_clipped (the answer's span ends by now; a span to the current minute bin's end with every cited fact before now fails only this), coverage_honest (a figure from part of the match says "in the footage"), natural (no "footage shown", "Esportes's", bare ranges, lower-case starts, "a London Athletic player") and consistent (the same headline as the intent's other paraphrases at that time). The CI ratchet holds every column separately.

## Core pass rate per intent

| Intent | main | #423 | #424 |
|---|---|---|---|
| score | 68% | 83% | 68% |
| scorers | 44% | 44% | 44% |
| winning | 46% | 82% | 46% |
| on_top | 0% | 0% | 19% |
| possession | 0% | 0% | 62% |
| passes | 0% | 0% | 0% |
| completion | 0% | 0% | 0% |
| shots | 0% | 0% | 0% |
| on_target | 0% | 0% | 0% |
| territory | 67% | 69% | 67% |
| corners | 0% | 0% | 0% |
| out_of_play | 0% | 0% | 0% |
| momentum | 0% | 0% | 20% |
| best_home | 0% | 0% | 0% |
| best_away | 0% | 0% | 0% |
| best_overall | 0% | 0% | 0% |
| fastest | 0% | 0% | 0% |
| distance | 0% | 0% | 0% |
| why_goal | 0% | 0% | 0% |
| key_moments | 22% | 22% | 22% |
| unmeasured | 0% | 0% | 0% |
| tactics_chip | 64% | 67% | 64% |
| **all** | **14%** | **16%** | **19%** |
| chips | 35% | 36% | 38% |

## Every check, all answers

| Check | main | #423 | #424 |
|---|---|---|---|
| **core** | 14% | 16% | 19% |
| answered | 49% | 49% | 56% |
| relevant | 64% | 66% | 65% |
| correct | 11% | 14% | 16% |
| no_false_unknown | 46% | 45% | 53% |
| no_future | 97% | 99% | 97% |
| span_clipped | 78% | 78% | 72% |
| coverage_honest | 16% | 20% | 14% |
| natural | 80% | 77% | 83% |
| consistent | 69% | 73% | 68% |
| all checks | 3% | 6% | 6% |

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
| territory | 67% | 88% | 79% | 67% | 88% | 97% | 28% | 90% | 12% | 79% |
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

## Each check per intent (#423)

| Intent | core | answered | relevant | correct | no_false_unknown | no_future | span_clipped | coverage_honest | natural | consistent |
|---|---|---|---|---|---|---|---|---|---|---|
| score | 83% | 89% | 91% | 83% | 89% | 100% | 100% | – | 42% | 82% |
| scorers | 44% | 74% | 82% | 44% | 74% | 100% | 100% | – | 67% | 56% |
| winning | 82% | 82% | 82% | 82% | 82% | 100% | 100% | – | 100% | 78% |
| on_top | 0% | 50% | 75% | 0% | 50% | 100% | 58% | – | 50% | 50% |
| possession | 0% | 0% | 67% | 0% | 0% | 100% | 100% | – | 100% | 70% |
| passes | 0% | 0% | 0% | 0% | 0% | 100% | 100% | – | 100% | 89% |
| completion | 0% | 27% | 14% | 0% | 27% | 100% | 77% | 0% | 100% | 67% |
| shots | 0% | 85% | 85% | 0% | 85% | 100% | 30% | 0% | 96% | 83% |
| on_target | 0% | 65% | 0% | 0% | 65% | 98% | 39% | 0% | 98% | 54% |
| territory | 69% | 83% | 83% | 69% | 83% | 100% | 31% | 100% | 11% | 83% |
| corners | 0% | 100% | 100% | 0% | 100% | 100% | 17% | 0% | 100% | 100% |
| out_of_play | 0% | 46% | 46% | 0% | 46% | 100% | 62% | 0% | 100% | 60% |
| momentum | 0% | 18% | 46% | 0% | 18% | 96% | 86% | – | 76% | 47% |
| best_home | 0% | 0% | 83% | 0% | 0% | 100% | 100% | – | 100% | 82% |
| best_away | 0% | 0% | 83% | 0% | 0% | 100% | 100% | – | 44% | 82% |
| best_overall | 0% | 0% | 92% | 0% | 0% | 100% | 100% | – | 39% | 92% |
| fastest | 0% | 0% | 83% | 0% | 0% | 100% | 100% | – | 100% | 75% |
| distance | 0% | 0% | 92% | 0% | 0% | 100% | 100% | – | 100% | 92% |
| why_goal | 0% | 83% | 0% | 0% | 83% | 100% | 100% | – | 100% | 98% |
| key_moments | 22% | 92% | 92% | 22% | 92% | 85% | 85% | – | 37% | 86% |
| unmeasured | 0% | 100% | 77% | 0% | – | 100% | 100% | – | 77% | 32% |
| tactics_chip | 67% | 67% | – | – | – | 95% | 55% | – | 63% | 31% |

## Each check per intent (#424)

| Intent | core | answered | relevant | correct | no_false_unknown | no_future | span_clipped | coverage_honest | natural | consistent |
|---|---|---|---|---|---|---|---|---|---|---|
| score | 68% | 86% | 86% | 68% | 86% | 100% | 100% | – | 100% | 64% |
| scorers | 44% | 74% | 82% | 44% | 74% | 100% | 100% | – | 100% | 56% |
| winning | 46% | 46% | 46% | 46% | 46% | 100% | 100% | – | 100% | 33% |
| on_top | 19% | 67% | 67% | 19% | 67% | 100% | 44% | – | 58% | 39% |
| possession | 62% | 75% | 75% | 62% | 75% | 100% | 38% | 0% | 100% | 80% |
| passes | 0% | 0% | 0% | 0% | 0% | 100% | 100% | – | 100% | 89% |
| completion | 0% | 29% | 0% | 0% | 29% | 98% | 79% | 0% | 97% | 67% |
| shots | 0% | 86% | 86% | 0% | 86% | 100% | 30% | 0% | 99% | 85% |
| on_target | 0% | 65% | 0% | 0% | 65% | 98% | 41% | 0% | 98% | 54% |
| territory | 67% | 88% | 79% | 67% | 88% | 97% | 28% | 90% | 12% | 79% |
| corners | 0% | 92% | 92% | 0% | 92% | 100% | 23% | 0% | 100% | 92% |
| out_of_play | 0% | 46% | 46% | 0% | 46% | 100% | 62% | 0% | 100% | 60% |
| momentum | 20% | 46% | 82% | 20% | 46% | 97% | 64% | – | 55% | 42% |
| best_home | 0% | 15% | 61% | 0% | 15% | 88% | 86% | 0% | 85% | 80% |
| best_away | 0% | 26% | 83% | 0% | 26% | 99% | 86% | 0% | 74% | 74% |
| best_overall | 0% | 33% | 92% | 0% | 33% | 89% | 78% | 0% | 67% | 71% |
| fastest | 0% | 0% | 83% | 0% | 0% | 100% | 100% | – | 100% | 75% |
| distance | 0% | 0% | 92% | 0% | 0% | 100% | 100% | – | 100% | 92% |
| why_goal | 0% | 83% | 21% | 0% | 83% | 100% | 100% | – | 93% | 92% |
| key_moments | 22% | 92% | 92% | 22% | 92% | 85% | 85% | – | 38% | 86% |
| unmeasured | 0% | 100% | 85% | 0% | – | 100% | 100% | – | 85% | 30% |
| tactics_chip | 64% | 64% | – | – | – | 95% | 63% | – | 72% | 41% |

Answers per column: main 1554, #423 1554, #424 1554.

- **main**: 382996dc, cached insights (runs/demo-8324-final/final-work/insights.json; rebuilding them with main's code gives the same file and the same grades)
- **#423**: 9c2cd777 (claude/dreamy-bassi-380a97), the same cached insights (it changes no insight)
- **#424**: ff0a17eb (claude/fervent-mcclintock-303a76), insights rebuilt with its code from runs/demo-8324-final (--rebuild-insights; its possession is computed into them)

## The model path (Foundry gpt-4.1-mini Companion and Judge), on a 10% sample

Run on main 382996dc (this branch) on Oct 27 ~03:10 PT after Kian approved spend; $1.50 cap; two runs, $0.17 and $0.23 ($0.39 in all). The first lost 64 answers to HTTP 429 throttling of the shared deployment (other sessions were calling it), and its grader scored the scorebug's per-club wording as no score (fixed, lesson 293); the table is the second run, with backoff on 429, whose waits count against the Ask's own 10 s timeout as they would on the phone. The sample is stratified by intent: 10% of each intent's (question, time) pairs. Each model answer (`companion_match.answer_match` with the published Companion and the Judge) is graded beside code's answer to the same question. Parity: the same headline. A fallback is code's answer shown in place of the model's, with its reason. Cost is the tokens the service reported, at ninety/eval/latency_cost.PRICES.

| | all sampled | not throttled |
|---|---|---|
| answers | 167 | 128 |
| core pass, model path | 22% | 23% |
| core pass, code, same questions | 16% | 14% |
| headline parity | 52% | 38% |
| fallback rate | 57% | 45% |
| latency p50 / p95 | 5.8 s / 10.0 s | 5.0 s / 9.2 s |
| cost | $0.225 ($0.0013 an answer) | |

Fallback reasons (all sampled): model: unanswerable 47; model timeout 39; not one of the checked sentences of the facts it cites 8; the Judge: unsupported fact 2.

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

## The 10 worst answers (#423), verbatim

1. **on_target**, 10:00: “who's had more shots on target”  
   → “In minute 4, a London Athletic player shot from 73 m out, where the posts were 6 degrees apart. London Athletic had 1 shot from minute 1 to minute 11, and took 0 shots from inside the penalty area.”  
   fails: relevant, correct, coverage_honest, span_clipped, natural, consistent; flags: a <club> player
2. **on_target**, 33:50: “how many times has the keeper been tested”  
   → “London Athletic played most through the centre: 60% of their passes from minute 20 to minute 34 started there.”  
   fails: relevant, correct, coverage_honest, no_future, span_clipped, consistent
3. **territory**, 45:00: “who's been in the attacking third more”  
   → “I can't single out the most dangerous player from minute 1 to minute 46: tracking missed too many players, or too many are level, to rank them surely. What I can say: a Lisbon Esportes player scored for Lisbon Esportes in minute 35.”  
   fails: answered, relevant, correct, no_false_unknown, natural, consistent; flags: a <club> player
4. **best_away**, 10:00: “who's played well for Lisbon”  
   → “Nothing from minute 1 to minute 11 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
5. **best_away**, 33:50: “who's Lisbon's most involved player”  
   → “Nothing from minute 20 to minute 34 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
6. **best_home**, 45:00: “who's played well for London”  
   → “Nothing from minute 32 to minute 46 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
7. **best_home**, 60:00: “who's London's most involved player”  
   → “Nothing from minute 47 to minute 61 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
8. **best_overall**, 10:00: “motm?”  
   → “I can't answer that one from this match's tracking. Try one of these:”  
   fails: answered, relevant, correct, no_false_unknown, consistent
9. **completion**, 10:00: “who's passing better”  
   → “The match tracking can't tell that: it sees where the players and the ball are, not names, money, the crowd or the weather. Try one of these:”  
   fails: answered, relevant, correct, no_false_unknown, consistent
10. **completion**, 33:50: “passing accuracy so far”  
   → “There were 8 long passes from minute 1 to minute 34. There were 5 passes intercepted from minute 1 to minute 34.”  
   fails: relevant, correct, coverage_honest, span_clipped, consistent

## The 10 worst answers (#424), verbatim

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

Times: 10:00, 33:50, 45:00, 60:00, 85:00, FT. Regenerate with `uv run python -m ninety.eval.ask_grade.report` (command in its docstring).
