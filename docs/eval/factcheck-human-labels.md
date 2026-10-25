# The fact-checker against one human's blind labels

Kian labelled 23 of the fact-checker's decisions blind on 2026-10-25. For each one he saw the sentence and its cited facts in plain words, and never the verdict. The sample was drawn by a rule written and hashed before the run it samples was read ([RULE.md](factcheck-human-labels/RULE.md): 8 passed, 5 rejected by the code checks, 6 rejected by the Judge, 1 held by the confidence gate, 3 rewritten after a rejection). The pool:
- the fact-checker run on the published Judge (`ninety-judge:4`, [fact-checker.md](fact-checker.md));
- the confidence gate on the 8080 dry run's vision detections;
- the recorded live workflow (seed 7).

It holds 23 items, not 25, because only one held decision exists on today's vision output, and the rule takes a short stratum whole. The scores come from [score.py](factcheck-human-labels/score.py) over [labels.json](factcheck-human-labels/labels.json), with each item's stratum and verdict in [key.json](factcheck-human-labels/key.json). L05 has a note but no answer and counts as unlabelled; 4 "unsure" answers are left out of every rate.

**With about 20 items the intervals are wide. This is a check on the checker, not a measurement of its rates.**

## The checker as a whole
- **Agreement:** 15 of 18 (83%, 95% Wilson interval 61% to 94%).
- **False passes** (aired, Kian: not supported): 1 of 9 (11%, 2% to 43%). This is L19, below.
- **False holds** (kept off air, Kian: supported): 2 of 9 (22%, 6% to 55%). These are L15 (the Judge rejected "a patient pass") and L06 (the gate held a pass detected at 0.39).

## By layer
Each layer is judged only on the items it decided.
- **Code checks:** they rejected 4 items, and Kian rejected all 4. They passed 13, of which Kian rejected 4. Those 4 are interpretation claims ("deliberately", "the best player", a pass called cut out). The code checks pass these by design and hand them to the Judge, and the Judge rejected 3 of them; the fourth, "cut out", was a planted false claim the Judge also rejected. So the code checks are not where these were meant to be caught.
- **Judge:** agreement 11 of 13 (85%, 58% to 96%).
  - False passes 1 of 9 (11%, 2% to 43%).
  - False holds 1 of 4 (25%, 5% to 70%).
- **Confidence gate:** 1 item, which Kian would have aired ("a-t11 plays a pass, but it doesn't arrive", detected at 0.39). The gate holds on detection confidence, not on whether the sentence follows from the facts, so this is expected. No rate is read from one item.

## Findings from Kian's notes
These are for the sentence writers.
1. **A sequence word joining a pass and its own interception (L19, the one false pass).** "The interception by a8 at 01:35 came immediately after h7's failed long pass at 01:33".
   - In the events, a8 cut out that very pass: e00049, interceptor a8. The interception (e00050) is the same ball arriving, 1.9 s later. "After" makes one act two.
   - "Long" is wrong for a 21 m pass: a long ball is 32 m or more by Opta's definition, which GROUNDING I11 cites (*verify*).
   - The Judge passed it. It is a live model rewrite, not a template.
2. **"Forward" and tone words claimed without a fact that shows them (L12, L20, L21, L10).** The evaluation's *true* templates say "a confident ball forward", "a risky tackle" and "a cautious pass" whenever its own rule fits.
   - No cited fact gives a direction, so "forward" has no basis. Kian was unsure or said no on each.
   - The 14 true claims the Judge rejected in the run are all tone words. The human sides with the Judge on some of them (L12, L21) and against it on one (L15, "patient").
   - So some of the evaluation's "true" labels are themselves doubtful.
3. **"Pressure" said without a cited pressure fact (L16).** "despite pressure": the seven facts the claim cites are all passes. The match does hold two pressure events in that window (on h10 at 01:13 and on h11 at 01:21), but the claim does not cite them. A claim stands only on what it cites, so "despite pressure" was unsupported, and the Judge passed it. Kian said yes, but "idk for sure about there being pressure", so it is not counted as a false pass; it is one in spirit.
4. **Claims about a whole match from one moment (L01 "the most important intervention", L11 "the best player" after 9 s, L23 "deliberately").** These are the evaluation's planted false claims. The Judge rejected all three, and Kian agreed or was unsure. No change is needed; the checker does what he asked.
5. **"Finds" for a pass the opponent cut out (L14, L22).** Planted false claims, which the code checks rejected; Kian agreed. The on-air templates already say "finds" only for a completed pass (`ninety/agents/cues.py`).
6. **L09** ("h7 plays a 17 m pass to h3"; the facts say h2) is not a data error. It is a planted wrong-player claim, rejected by the code checks, as Kian rejected it.
7. **Too long (L03, "bit too much").** A Challenger rewrite that restates five events. True, but not how a commentator would say it.

## What changes in code, and what waits
None of the objected sentences come from an on-air template. 1, 3 and 7 are live model writing (and 1 and 3 are passes the Judge should have caught); 2 and 4 to 6 are the evaluation's own claims. The fixes that follow are proposals, waiting on a decision, because each changes the published evaluation and needs a re-run of it on the Judge:
- a code check that "long ball" or "long pass" cites a distance of at least 32 m (GROUNDING I11). The evaluation's own `LONG_PASS_M` is 30 m, design, and moves to it;
- dropping "forward" from the evaluation's true template, since no cited fact shows a direction;
- re-labelling, or removing, the tone kinds whose truth only the evaluation's rule decides.

The live writing (1, 3, 7) is the Tactician's and Challenger's. Their instructions change only with a republish and a live run.
