# GitHub Copilot instructions

Follow [AGENTS.md](../AGENTS.md) at the repo root. It is the single source of truth for this
project's rules, and it links the challenge brief, the architecture, the plan, the security
policy and the task guides in `docs/guides/`. Read it, and the docs it lists, before changing code.

The rules that apply to every change, in short (AGENTS.md has the full list):

- The repo is public: never add secrets, keys, connection strings or `.env` files.
- Synthetic data only: no real players, clubs, kits, crests or footage.
- Code computes every number; models only explain.
- MIT, Apache-2.0 or BSD dependencies only.
- Run `uv run ruff check .` and `uv run pytest` before proposing a commit.

## When reviewing a pull request

Flag, in this order of severity:

1. **Secrets or credentials**: keys, tokens, connection strings, `.env` files, or code that reads a secret from anywhere but managed identity or Key Vault.
2. **Real-world data**: real players, clubs, kits, crests, sponsors or footage (the rules require synthetic data and forbid third-party trademarks).
3. **Numbers a model wrote**: any statistic that reaches the screen without being computed in code and passing the fact-checking agent.
4. **Prompt injection**: viewer input or event text concatenated into model instructions instead of passed as delimited data.
5. **Licenses**: new dependencies that are not MIT, Apache-2.0 or BSD (no AGPL).
6. **Claims**: README, docs or `docs/CHALLENGE_MAP.md` describing something the code does not do.
7. **Missing tests** for new logic, and anything that would break determinism by seed.
