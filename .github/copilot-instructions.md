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
