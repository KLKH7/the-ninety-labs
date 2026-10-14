---
name: ninety-lessons
description: The Ninety Labs' lessons from past mistakes (scripted simulation outcomes, checks that cannot fail, thresholds tailored to tests, merging before CI reports). Load before any change to the match engine, validator, evaluation or CI, and whenever you catch a mistake, to record it.
---

# Lessons from past mistakes

1. Read `docs/LESSONS.md` in full. It is the single source; this skill only points to it, so
   Cursor and Copilot (which read `AGENTS.md`) get the same lessons.
2. Before finishing, check your change against every lesson that applies, and say which ones.
3. If you caught a mistake (yours or anyone's), add a lesson to `docs/LESSONS.md` in the same
   pull request as the fix: what happened, the rule now, how to check. Public file: no
   research sources, product names or strategy.
