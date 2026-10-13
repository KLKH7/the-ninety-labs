# The Ninety Labs: agent instructions

Before changing anything, load the project context with the `ninety-context` skill
(`.claude/skills/ninety-context/SKILL.md`). It points at the files below.

1. [docs/BRIEF.md](docs/BRIEF.md): the challenge brief and judging rubric. What we build must map to it.
2. [docs/CHALLENGE_MAP.md](docs/CHALLENGE_MAP.md): every requirement and where we answer it. Update its status column when a row ships.
3. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): design rules and the Microsoft stack.
4. [docs/PLAN.md](docs/PLAN.md): the day-by-day plan to Oct 27.
5. [SECURITY.md](SECURITY.md): the repo is public. Follow it for every change.

## Hard rules

- **The repo is public.** Never commit secrets, `.env` files, keys or connection strings. Use managed identity or Key Vault.
- **Synthetic data only.** No real match data, players, clubs or footage (rule 4.7).
- **Code computes every number; models only explain.** Agents never invent a statistic.
- **Licenses:** MIT, Apache-2.0 or BSD dependencies only. No AGPL (this rules out ultralytics).
- **Terminology:** automatic event detection, ground-truth data, fact-checking agent, on-screen graphics, player cam. Keep the brief's stage names: Ingest, Interpret, Explain, Render, Personalize.
- **Honest claims:** the README and project page describe only what runs. Mark unbuilt rows `planned`.
- Run `uv run pytest` before every push.
