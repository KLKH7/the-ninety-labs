# The Ask, graded against the answer key (seed 8324)

Every fan question in `ninety/eval/ask_grade/intents.json` (22 intents, at least 10 paraphrases each, the phone's chips marked) asked at 10:00, 33:50, 45:00, 60:00, 85:00 and full time through the Ask's code path (`companion_match.code_match_answer`), each answer graded by `ninety/eval/ask_grade` against the simulator's ground truth: over the footage when the answer says so, else over the whole match. The tolerances were committed before the first graded run (`tolerances.json`, commit 3766efbe). The footage shows 20.9% (1129 s of 5400 in the 46 clip windows) of the match.

An answer passes when every check that applies passes: answered (not a "can't"), relevant (the lead sentence carries the intent's metric), correct (within tolerance of the truth), consistent (the same headline as the intent's other paraphrases at that time), coverage-honest (a figure from part of the match says so), no window past now, no false "not known", natural (no "footage shown", "Esportes's", bare ranges, lower-case starts, "a London Athletic player").

## Pass rate per intent

| Intent | main | #423 | #424 |
|---|---|---|---|
| score | 21% | 27% | 64% |
| scorers | 20% | 20% | 26% |
| winning | 14% | 41% | 35% |
| on_top | 0% | 0% | 0% |
| possession | 0% | 0% | 0% |
| passes | 0% | 0% | 0% |
| completion | 0% | 0% | 0% |
| shots | 0% | 0% | 0% |
| on_target | 0% | 0% | 0% |
| territory | 0% | 0% | 0% |
| corners | 0% | 0% | 0% |
| out_of_play | 0% | 0% | 0% |
| momentum | 0% | 0% | 0% |
| best_home | 0% | 0% | 0% |
| best_away | 0% | 0% | 0% |
| best_overall | 0% | 0% | 0% |
| fastest | 0% | 0% | 0% |
| distance | 0% | 0% | 0% |
| why_goal | 0% | 0% | 0% |
| key_moments | 0% | 0% | 0% |
| unmeasured | 0% | 0% | 0% |
| tactics_chip | 3% | 3% | 3% |
| **all** | **2%** | **4%** | **5%** |
| chips answered | 64% | 61% | 67% |
| chips passed | 1% | 1% | 1% |

## Answered and correct per intent

Answered: a verified reply that is not a "can't". Correct: within tolerance of the truth (an unanswered question counts as not correct).

| Intent | main answered | main correct | #423 answered | #423 correct | #424 answered | #424 correct |
|---|---|---|---|---|---|---|
| score | 86% | 68% | 89% | 83% | 86% | 68% |
| scorers | 74% | 44% | 74% | 44% | 74% | 44% |
| winning | 46% | 35% | 82% | 41% | 46% | 35% |
| on_top | 17% | 0% | 50% | 0% | 67% | 19% |
| possession | 0% | 0% | 0% | 0% | 75% | 62% |
| passes | 0% | 0% | 0% | 0% | 0% | 0% |
| completion | 29% | 0% | 27% | 0% | 29% | 0% |
| shots | 86% | 0% | 85% | 0% | 86% | 0% |
| on_target | 65% | 0% | 65% | 0% | 65% | 0% |
| territory | 88% | 67% | 83% | 69% | 88% | 67% |
| corners | 92% | 0% | 100% | 0% | 92% | 0% |
| out_of_play | 46% | 0% | 46% | 0% | 46% | 0% |
| momentum | 27% | 0% | 18% | 0% | 46% | 20% |
| best_home | 15% | 0% | 0% | 0% | 15% | 0% |
| best_away | 26% | 0% | 0% | 0% | 26% | 0% |
| best_overall | 33% | 0% | 0% | 0% | 33% | 0% |
| fastest | 0% | 0% | 0% | 0% | 0% | 0% |
| distance | 0% | 0% | 0% | 0% | 0% | 0% |
| why_goal | 83% | 0% | 83% | 0% | 83% | 0% |
| key_moments | 92% | 22% | 92% | 22% | 92% | 22% |
| unmeasured | 100% | 0% | 100% | 0% | 100% | 0% |
| tactics_chip | 64% | – | 67% | – | 64% | – |

Answers per column: main 1554, #423 1554, #424 1554.

- **main**: 382996dc, cached insights (runs/demo-8324-final/final-work/insights.json; rebuilding them with main's code gives the same file and the same grades)
- **#423**: 9c2cd777 (claude/dreamy-bassi-380a97), the same cached insights (it changes no insight)
- **#424**: ff0a17eb (claude/fervent-mcclintock-303a76), insights rebuilt with its code from runs/demo-8324-final (--rebuild-insights; its possession is computed into them)

## Each check, per intent (main)

| Intent | answered | relevant | correct | consistent | coverage_honest | no_future | no_false_unknown | natural |
|---|---|---|---|---|---|---|---|---|
| score | 86% | 86% | 68% | 64% | – | 100% | 86% | 48% |
| scorers | 74% | 82% | 44% | 56% | – | 100% | 74% | 67% |
| winning | 46% | 46% | 35% | 33% | – | 100% | 46% | 76% |
| on_top | 17% | 33% | 0% | 44% | – | 88% | 17% | 83% |
| possession | 0% | 75% | 0% | 80% | – | 100% | 0% | 100% |
| passes | 0% | 0% | 0% | 89% | – | 100% | 0% | 100% |
| completion | 29% | 0% | 0% | 67% | 0% | 79% | 29% | 97% |
| shots | 86% | 86% | 0% | 85% | 0% | 30% | 86% | 96% |
| on_target | 65% | 0% | 0% | 54% | 0% | 41% | 65% | 98% |
| territory | 88% | 79% | 67% | 79% | 90% | 28% | 88% | 12% |
| corners | 92% | 92% | 0% | 92% | 0% | 23% | 92% | 100% |
| out_of_play | 46% | 46% | 0% | 60% | 0% | 62% | 46% | 100% |
| momentum | 27% | 82% | 0% | 51% | – | 82% | 27% | 73% |
| best_home | 15% | 61% | 0% | 80% | 0% | 86% | 15% | 85% |
| best_away | 26% | 83% | 0% | 74% | 0% | 86% | 26% | 74% |
| best_overall | 33% | 92% | 0% | 71% | 0% | 78% | 33% | 67% |
| fastest | 0% | 83% | 0% | 75% | – | 100% | 0% | 100% |
| distance | 0% | 92% | 0% | 92% | – | 100% | 0% | 100% |
| why_goal | 83% | 21% | 0% | 92% | – | 100% | 83% | 93% |
| key_moments | 92% | 92% | 22% | 86% | – | 85% | 92% | 37% |
| unmeasured | 100% | 85% | 0% | 30% | – | 100% | – | 85% |
| tactics_chip | 64% | – | – | 41% | – | 63% | – | 72% |

## The 10 worst answers (main), verbatim

1. **territory**, 33:50: “who's been camped in the other half”  
   → “a London Athletic player has taken the most opponents out of the game with passes from minute 20 to minute 34: 4 opponents in 1 pass.”  
   fails: relevant, correct, coverage_honest, no_future, natural, consistent; flags: lowercase start, a <club> player
2. **territory**, 85:00: “who's been in the attacking third more”  
   → “a Lisbon Esportes player has taken the most opponents out of the game with passes from minute 72 to minute 86: 4 opponents in 1 pass.”  
   fails: relevant, correct, coverage_honest, no_future, natural, consistent; flags: lowercase start, a <club> player
3. **best_away**, 10:00: “who's played well for Lisbon”  
   → “Nothing from minute 1 to minute 11 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
4. **best_away**, 33:50: “who's Lisbon's most involved player”  
   → “Nothing from minute 20 to minute 34 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
5. **best_home**, 45:00: “who's played well for London”  
   → “Nothing from minute 32 to minute 46 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
6. **best_home**, 60:00: “who's London's most involved player”  
   → “Nothing from minute 47 to minute 61 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
7. **best_overall**, 10:00: “motm?”  
   → “I can't answer that one from this match's tracking. Try one of these:”  
   fails: answered, relevant, correct, no_false_unknown, consistent
8. **completion**, 10:00: “who's passing better”  
   → “London Athletic made 4 passes with no open teammate further forward from minute 1 to minute 11.”  
   fails: relevant, correct, coverage_honest, no_future, consistent
9. **completion**, 33:50: “passing accuracy so far”  
   → “London Athletic made 4 passes with no open teammate further forward from minute 1 to minute 34.”  
   fails: relevant, correct, coverage_honest, no_future, consistent
10. **completion**, 33:50: “how good is the passing”  
   → “I can answer about goal build-up, players, style, referee and the team sheets.”  
   fails: answered, relevant, correct, no_false_unknown, consistent

## The 10 worst answers (#423), verbatim

1. **on_target**, 10:00: “who's had more shots on target”  
   → “In minute 4, a London Athletic player shot from 73 m out, where the posts were 6 degrees apart. London Athletic had 1 shot from minute 1 to minute 11, and took 0 shots from inside the penalty area.”  
   fails: relevant, correct, coverage_honest, no_future, natural, consistent; flags: a <club> player
2. **territory**, 45:00: “who's been in the attacking third more”  
   → “I can't single out the most dangerous player from minute 1 to minute 46: tracking missed too many players, or too many are level, to rank them surely. What I can say: a Lisbon Esportes player scored for Lisbon Esportes in minute 35.”  
   fails: answered, relevant, correct, no_false_unknown, natural, consistent; flags: a <club> player
3. **best_away**, 10:00: “who's played well for Lisbon”  
   → “Nothing from minute 1 to minute 11 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
4. **best_away**, 33:50: “who's Lisbon's most involved player”  
   → “Nothing from minute 20 to minute 34 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
5. **best_home**, 45:00: “who's played well for London”  
   → “Nothing from minute 32 to minute 46 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
6. **best_home**, 60:00: “who's London's most involved player”  
   → “Nothing from minute 47 to minute 61 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
7. **best_overall**, 10:00: “motm?”  
   → “I can't answer that one from this match's tracking. Try one of these:”  
   fails: answered, relevant, correct, no_false_unknown, consistent
8. **completion**, 10:00: “who's passing better”  
   → “The match tracking can't tell that: it sees where the players and the ball are, not names, money, the crowd or the weather. Try one of these:”  
   fails: answered, relevant, correct, no_false_unknown, consistent
9. **completion**, 33:50: “passing accuracy so far”  
   → “There were 8 long passes from minute 1 to minute 34. There were 5 passes intercepted from minute 1 to minute 34.”  
   fails: relevant, correct, coverage_honest, no_future, consistent
10. **completion**, 33:50: “how good is the passing”  
   → “There were 5 long passes from minute 20 to minute 34. There were 3 passes intercepted from minute 20 to minute 34.”  
   fails: relevant, correct, coverage_honest, no_future, consistent

## The 10 worst answers (#424), verbatim

1. **territory**, 33:50: “who's been camped in the other half”  
   → “a London Athletic player has taken the most opponents out of the game with passes from minute 20 to minute 34: 4 opponents in 1 pass.”  
   fails: relevant, correct, coverage_honest, no_future, natural, consistent; flags: lowercase start, a <club> player
2. **territory**, 85:00: “who's been in the attacking third more”  
   → “a Lisbon Esportes player has taken the most opponents out of the game with passes from minute 72 to minute 86: 4 opponents in 1 pass.”  
   fails: relevant, correct, coverage_honest, no_future, natural, consistent; flags: lowercase start, a <club> player
3. **best_away**, 10:00: “who's played well for Lisbon”  
   → “Nothing from minute 1 to minute 11 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
4. **best_away**, 33:50: “who's Lisbon's most involved player”  
   → “Nothing from minute 20 to minute 34 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
5. **best_home**, 45:00: “who's played well for London”  
   → “Nothing from minute 32 to minute 46 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
6. **best_home**, 60:00: “who's London's most involved player”  
   → “Nothing from minute 47 to minute 61 answers that yet.”  
   fails: answered, relevant, correct, no_false_unknown, consistent
7. **best_overall**, 10:00: “motm?”  
   → “I can't answer that one from this match's tracking. Try one of these:”  
   fails: answered, relevant, correct, no_false_unknown, consistent
8. **completion**, 10:00: “who's passing better”  
   → “London Athletic made 4 passes with no open teammate further forward from minute 1 to minute 11.”  
   fails: relevant, correct, coverage_honest, no_future, consistent
9. **completion**, 33:50: “passing accuracy so far”  
   → “London Athletic made 4 passes with no open teammate further forward from minute 1 to minute 34.”  
   fails: relevant, correct, coverage_honest, no_future, consistent
10. **completion**, 33:50: “how good is the passing”  
   → “I can answer about goal build-up, players, style, referee and the team sheets.”  
   fails: answered, relevant, correct, no_false_unknown, consistent

Times: 10:00, 33:50, 45:00, 60:00, 85:00, FT. Regenerate with `uv run python -m ninety.eval.ask_grade.report` (command in its docstring).
