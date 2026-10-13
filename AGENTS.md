# The Ninety Labs: instructions for coding agents

This file is the single source of truth for any AI coding tool working in this repo: GitHub
Copilot, Cursor and Claude Code all read it. `CLAUDE.md`, `.github/copilot-instructions.md` and
`.cursor/rules/` only point here. Change the rules here, nowhere else.

The Ninety Labs is our entry for the Microsoft x Premier League *Inside the Game: Developer
Hackathon* (challenge: *The Synthetic Match Insights Engine for Premier League Studio*).
Submission closes **Oct 27, 2026, 11:59pm PT**.

**One line:** AI that watches the match, logs every event, and describes it to every fan,
including the ones who can't see it.

## 1. Read before changing anything

1. [docs/BRIEF.md](docs/BRIEF.md): the challenge brief, the five required stages, the rubric and the submission checklist.
2. [docs/CHALLENGE_MAP.md](docs/CHALLENGE_MAP.md): every requirement, where we answer it, and its status.
3. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): design rules, components and the Microsoft stack.
4. [docs/PLAN.md](docs/PLAN.md): goals, milestones and what is due on which day.
5. [docs/EVALUATION.md](docs/EVALUATION.md): how every published number is measured.
6. [SECURITY.md](SECURITY.md): the repo and the demo are public.

Task-specific guides in `docs/guides/`:

- [broadcast-render.md](docs/guides/broadcast-render.md): anything that renders the synthetic video or generates images.

## 2. Check the task against the rubric

Before building, say which criterion the change moves and how a judge would see it in the
2-minute video or the repo. A change that moves none of them is probably out of scope for the
deadline; say so.

| Criterion (20% each) | What scores for us |
|---|---|
| Technological implementation | synthetic video with ground-truth data, measured event detection, tests, CI, IaC, Foundry / Agent Framework / MCP |
| Agentic design and innovation | distinct agents, shared state, handoffs, a fact-checking agent that can reject, failure recovery, MCP tools, A2A |
| Real-world impact | replacing hand-logged event data; audio description for blind and low-vision fans |
| UX and presentation | on-screen graphics drawn on the footage, a clear persona switch, the video |
| Category fit | Best Multi-Agent System (primary), Best Use of Microsoft Foundry (fallback) |

## 3. Hard rules

- **The repo is public.** Never commit secrets, `.env` files, keys or connection strings. Use managed identity or Key Vault.
- **Synthetic data only.** No real match data, players, clubs, kits, crests or footage (rules 4.4 and 4.7).
- **Code computes every number; models only explain.** Agents never invent a statistic, and the fact-checking agent gates what reaches the screen.
- **Agents read typed facts.** Viewer input is data, never instructions.
- **Licenses:** MIT, Apache-2.0 or BSD dependencies only. No AGPL (this rules out ultralytics).
- **Terminology:** automatic event detection, ground-truth data, fact-checking agent, on-screen graphics, player cam. Keep the brief's stage names: Ingest, Interpret, Explain, Render, Personalize.
- **Honest claims:** the README and project page describe only what runs. Mark unbuilt rows `planned` in the challenge map, and update a row when it ships.

## 4. Working in the repo

- Setup: `uv sync`. Simulator: `uv run ninety-sim --seed 7 --minutes 5 --out runs/seed7`.
- Before every push: `uv run ruff check .` and `uv run pytest`.
- `main` is protected: CI (lint, tests on 3.11 and 3.12, schema smoke test, secret scan) must pass. Work on a branch and open a pull request.
- Stage files by name. Before committing, check `git diff --cached` contains no secret, key or `.env` file.
