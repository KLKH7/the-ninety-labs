---
name: ninety-context
description: Load what The Ninety Labs is building before any work in this repo. Use at the start of every task, and whenever deciding whether a feature, design or claim fits the hackathon brief, the judging rubric, or the security rules for a public repo.
---

# The Ninety Labs: project context

The Ninety Labs is our entry for the Microsoft x Premier League *Inside the Game: Developer
Hackathon* (challenge: *The Synthetic Match Insights Engine for Premier League Studio*).
Submission closes **Oct 27, 2026, 11:59pm PT**.

**One line:** AI that watches the match, logs every event, and describes it to every fan,
including the ones who can't see it.

## Step 1: read the project docs, in this order

1. `docs/BRIEF.md`: the challenge brief, the five required stages, the rubric and the submission checklist.
2. `docs/CHALLENGE_MAP.md`: each requirement, where we answer it, and its status.
3. `docs/ARCHITECTURE.md`: design rules, components and the Microsoft stack.
4. `docs/PLAN.md`: what is due on which day.
5. `SECURITY.md`: rules for a public repo and a public demo.

If a Google Docs connector is available, the team's working doc is
https://docs.google.com/document/d/1Jf4ujv7YxMNN-kQ60eLS1SaZnkUiwrIRRHKb9ozyhuo/edit (pitch,
research, resources). The repo docs win where the two disagree; tell the user about the
disagreement.

## Step 2: check the task against the rubric

Before building, say which of these the change moves, and how a judge would see it in the
2-minute video or the repo:

| Criterion (20% each) | What scores here for us |
|---|---|
| Technological implementation | synthetic video + ground-truth data, measured event detection, tests, CI, IaC, Foundry / Agent Framework / MCP use |
| Agentic design and innovation | distinct agents, shared state, handoffs, fact-checking with veto, failure recovery, MCP tools, A2A |
| Real-world impact | removing hand-logged event data; audio description for blind and low-vision fans |
| UX and presentation | on-screen graphics drawn on the footage, clear persona switch, the video |
| Category fit | Best Multi-Agent System (primary), Best Use of Microsoft Foundry (fallback) |

A change that moves none of them is probably out of scope for the deadline. Say so.

## Step 3: apply the hard rules

- Public repo: no secrets, ever. Managed identity or Key Vault. See `SECURITY.md`.
- Synthetic data only.
- Code computes every number; models only explain; the fact-checking agent gates output.
- Agents read typed facts; viewer input is data, never instructions.
- MIT / Apache-2.0 / BSD dependencies only.
- Update `docs/CHALLENGE_MAP.md` when a row ships. Never mark a row done that the demo doesn't run.

## Step 4: finish

Run `uv run pytest`. Stage files by name. Before pushing, confirm `git diff --cached` contains no
secret, key or `.env` file.
