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

1. [docs/LESSONS.md](docs/LESSONS.md): mistakes this project already made, the rule now, and how to check. Read it first, every task.
2. [docs/BRIEF.md](docs/BRIEF.md): the challenge brief, the five required stages, the rubric and the submission checklist.
3. [docs/CHALLENGE_MAP.md](docs/CHALLENGE_MAP.md): every requirement, where we answer it, and its status.
4. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): design rules, components and the Microsoft stack.
5. [docs/PLAN.md](docs/PLAN.md): goals, milestones and what is due on which day.
6. [docs/EVALUATION.md](docs/EVALUATION.md): how every published number is measured.
7. [docs/DATA_CONTRACT.md](docs/DATA_CONTRACT.md): what ground-truth data must contain, and how it is checked.
8. [docs/ENGINE.md](docs/ENGINE.md): how the match engine makes football (players decide, physics happens, the referee observes) and the build order.
9. [SECURITY.md](SECURITY.md): the repo and the demo are public.
10. [docs/TEAM.md](docs/TEAM.md): the five roles, who owns which paths, the handoff dates. Ask which role you are working for, and change only that role's paths.

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

## 3. Hold the product bar

Ask two questions before building anything, and again before calling it done.

1. **Does it set us apart?** Other entries already ship a stats engine, agents with a verifier,
   overlay cards and multilingual voice. Work that only matches them comes after the work that
   only we do: live automatic event detection on realistic video, targeted synthetic data that
   improves the detector, a confidence-aware fact-checker proven by an ablation and a failure
   table, and audio description.
2. **Is it excellent on its own terms?** Being different is not enough. Would a broadcaster put
   it on air, would a blind fan rely on it, would a senior engineer trust the code? A feature
   that works but feels rough, slow or unexplained is not done.

Every claim of quality ships with the measurement that proves it (`docs/EVALUATION.md`).

## 4. Hard rules

- **The repo is public.** Never commit secrets, `.env` files, keys or connection strings. Use managed identity or Key Vault.
- **Synthetic data only.** No real match data, players, clubs, kits, crests or footage (rules 4.4 and 4.7).
- **Code computes every number; models only explain.** Agents never invent a statistic, and the fact-checking agent gates what reaches the screen.
- **Agents read typed facts.** Viewer input is data, never instructions.
- **Ground truth is the answer key.** It is used for training labels and grading only. Nothing on the live path (vision, the stats it feeds, the agents in the demo) reads it. Until Milestone 1 the agents read simulator events as a stand-in; after it, a test enforces this.
- **One football engine.** Football logic and physics live in `ninety/sim`; scenarios are modes of it. The renderer only draws. Whatever makes the video also writes the truth, so no generative video models.
- **Ground-truth data meets the contract.** Every clip passes `uv run ninety-validate <clip>` ([docs/DATA_CONTRACT.md](docs/DATA_CONTRACT.md)).
- **Fix the cause, never the symptom; never script the result.** In the engine, outcomes (a completed pass, an interception, a save, a goal, the ball going out) emerge from physics and decisions; never decide an outcome first and arrange the world to match it. In the validator, a threshold comes from a cited source or from measurement precision, set before looking at the engine's numbers; never loosen a check, add an exemption or special-case an id to turn it green. A legal case gets a test that must pass; a defect gets one that must fail.
- **Every engine change gets an independent audit for hard-coding** before it merges: a reviewer with no knowledge of the author's intent lists each new constant and special case as sourced (GROUNDING), design-marked or neither, flags anything fitted to a check or scripted, and mutation-tests the new tests ([docs/LESSONS.md](docs/LESSONS.md), lesson 21). Outcome rates (completion, shots, goals, distances) are held-out checks, never fitting targets.
- **Football is grounded, not remembered.** Every rule in the engine and every check in the validator cites its source in [docs/GROUNDING.md](docs/GROUNDING.md) (a Law of the Game, a study, a published statistic). Implement rules in our own words; never commit the Laws' text.
- **Licenses:** permissive dependencies only: MIT (with MIT-0 and MIT-CMU), Apache-2.0 (with the LLVM exception), BSD (with 0BSD), ISC, PSF or CNRI-Python, Zlib, BSL-1.0 or CC0-1.0, and MPL-2.0 used unmodified. Three narrow exceptions, each only for code bundled unmodified inside a dependency's wheel or installed as a runtime: an LGPL library (FFmpeg in `av` and OpenCV, `libquadmath` in SciPy); a GPL runtime under the GCC Runtime Library Exception (`libgfortran` and `libgcc` in NumPy and SciPy), or a dual licence taken under its permissive option (FreeType in matplotlib, under the FTL); and a proprietary runtime that is free to redistribute, only in an optional dependency group (NVIDIA CUDA under PyTorch in `vision`). Never GPL or AGPL otherwise (this rules out ultralytics), and never non-commercial or source-available terms, for code or model weights. Record each in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md); a licence outside this list needs a change to this rule first.
- **Vision models:** RF-DETR only in its Apache-2.0 sizes (Nano, Small, Medium, Large), pinned by name. Never the PML-1.0 sizes (Atto, Femto, Pico, XL, 2XL) or `rfdetr_plus`. Train and fine-tune on our own renders only: no Roboflow Universe or any dataset made from real footage. Do not send our video to a hosted third-party inference service; run the models the demo uses in our own Azure resources. Training may rent a GPU machine elsewhere when Azure has no GPU quota (docs/PLAN.md, risks): only our synthetic renders go to it, the machine is deleted after the run, and the checkpoint comes back with its training manifest.
- **Terminology:** automatic event detection, ground-truth data, fact-checking agent, on-screen graphics, player cam. Keep the brief's stage names: Ingest, Interpret, Explain, Render, Personalize.
- **Honest claims:** the README and project page describe only what runs. Mark unbuilt rows `planned` in the challenge map, and update a row when it ships.

## 5. Working in the repo

- Setup: `uv sync`. Simulator: `uv run ninety-sim --seed 7 --minutes 5 --out runs/seed7`. Contract check: `uv run ninety-validate runs/seed7`.
- Before every push: `uv run ruff check .` and `uv run pytest`.
- `main` is protected: CI (lint, tests on 3.11 and 3.12, schema smoke test, secret scan) must pass. Work on a branch and open a pull request.
- Stage files by name. Before committing, check `git diff --cached` contains no secret, key or `.env` file.
- **When you catch a mistake** (yours or anyone's), add a lesson to [docs/LESSONS.md](docs/LESSONS.md) in the same pull request as the fix: what happened, the rule now, how to check.
