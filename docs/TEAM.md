# Team plan: five roles

Five people, twelve days (Thu Oct 15 to Tue Oct 27, 2026). This file says who owns what, when
each handoff happens, and how we keep five builds from drifting apart. The overall schedule and
milestones are in [PLAN.md](PLAN.md); the design is in [ARCHITECTURE.md](ARCHITECTURE.md). If
this file and PLAN.md disagree on dates, fix both in the same pull request.

## Contents

1. [Roles](#roles)
2. [Who owns which code](#who-owns-which-code)
3. [Handoffs](#handoffs)
4. [Day by day](#day-by-day)
5. [Staying in sync](#staying-in-sync)
6. [Working with coding agents](#working-with-coding-agents)

## Roles

Each role owns one part of the pipeline from end to end: its code, its tests, its row in the
[challenge map](CHALLENGE_MAP.md) and its evidence file. Fill in the names when everyone has
agreed.

| # | Role | Owner | Owns | Best fit |
|---|---|---|---|---|
| R1 | **Football truth**: match engine, validator, stats engine | _name_ | how the match is made and every number computed from it | strong Python, physics and football rules; careful with sources |
| R2 | **Synthetic video and data**: renderer, datasets, targeted data | _name_ | the broadcast video, its exact labels and the train and test sets | three.js or graphics, Playwright, an eye for what looks like TV |
| R3 | **Vision and scoring**: automatic event detection, grading | _name_ | turning pixels into events, and proving how well it works | PyTorch, computer vision, evaluation |
| R4 | **Agents**: Ledger, workflow, fact-checking agent, MCP, A2A | _name_ | everything that turns facts into verified explanations | LLM apps, Agent Framework, async Python |
| R5 | **Experience and platform**: viewer, audio description, Azure, demo | _name_ | what a judge sees and hears, and keeping it live | TypeScript front end, Azure, video editing |

**Why this split.** Each boundary between roles is a schema that already exists
(`frame`, `match_event`, `overlay_cue`), so each person can build against a fixture file
without waiting for anyone. R1 owns the stats engine as well as the simulator because both are
deterministic football code that must cite [GROUNDING.md](GROUNDING.md), and it keeps R4 free
for the agents.

### Captains

- **Integration captain: R5.** Owns the end-to-end run on `main` and the deployed demo. When
  the run breaks, R5 says which role's output broke it; that owner fixes it first.
- **Contract keeper: R4.** Approves every change to `schemas/` and keeps the fixtures in sync
  (see [Contracts](#contracts)).
- **Honesty check: everyone, on their own rows.** You mark your challenge map row `running`
  only when it runs in the demo, and you write your own evidence file.

## Who owns which code

The owner reviews every change to their paths. Anyone may open a pull request anywhere, but a
change outside your own paths needs the owner's approval.

| Path | Owner | Reviewer |
|---|---|---|
| `ninety/sim`, `ninety/validate.py`, `docs/GROUNDING.md`, `docs/ENGINE.md` | R1 | R3 (independent audit for scripted outcomes, [lesson 4](LESSONS.md)) |
| `ninety/intel` | R1 | R4 |
| `ninety/render`, `web/render`, `docs/guides/broadcast-render.md`, `docs/decisions/0001-*` | R2 | R3 |
| `ninety/vision`, `ninety/eval` (except `factcheck_eval.py`) | R3 | R2 |
| `ninety/agents`, `ninety/match`, `ninety/mcp`, `ninety/eval/factcheck_eval.py`, `replays/` | R4 | R1 |
| `web` (except `web/render`), `ninety/speech`, `infra`, `.github/workflows/deploy.yml` | R5 | R4 |
| `schemas/` | R4 | producer and consumer of the schema |
| `.github/workflows/ci.yml`, `pyproject.toml`, `uv.lock` | R5 | whoever's job the change touches |
| `AGENTS.md`, `docs/LESSONS.md`, `docs/PLAN.md`, `docs/TEAM.md`, `README.md` | everyone | one other person |

The reviewer is usually whoever **uses** that output, because they are the person most likely to
notice when it changes under them.

## Handoffs

These are the only points where one role waits on another. Each one is a file committed to the
repo, not a message. If a handoff will be late, tell the person waiting on it the day before, and
give them a stand-in file they can use until then.

| Date | From → to | What | Where |
|---|---|---|---|
| Thu Oct 15 | R4 → R5 | a fixture of `overlay_cue` graphics for one clip | `tests/fixtures/cues-seed7.jsonl` |
| Fri Oct 16 | R1 → R4 | stats engine v1 API: pass distance, completion, ball and shot speed, sprints | `ninety/intel` |
| Fri Oct 16 | R3 → R4 | the scoring harness's output format for detected events | a section in [EVALUATION.md](EVALUATION.md) |
| Sat Oct 17 | R1 → R2 | **engine version for dataset v1** (a git tag) | tag `engine-v1` |
| Sat Oct 17 | R2 → R3 | **dataset v1**: about 20 training clips and the fixed 5-clip test set, rendered from `engine-v1` | `runs/dataset/` on shared storage, manifest committed |
| Mon Oct 19 | R3 → R4 | first detected events from video (`source: detected`, with confidence) | `tests/fixtures/detected-seed900001.jsonl` |
| **Tue Oct 20 · M1** | all | video → detected events → stats → agents → graphics → viewer on one clip | `ninety-e2e` run on `main` |
| Wed Oct 21 | R4 → R2 | Vision Auditor's failure clusters | `runs/round1/clusters.json` |
| Wed Oct 21 | R2 → R3 | round 1 targeted clips | `runs/dataset/round1/` |
| Thu Oct 22 | R5 → R4 | deploy pipeline that can ship the Personalizer container | `infra/`, `deploy.yml` |
| Thu Oct 22 | R1 → R2 | engine version for round 2, if the engine changed | tag `engine-v2` |
| **Fri Oct 23 · M2** | all | `azd up` from a clean clone; live smoke test passes | deployed URL |
| Sat Oct 24 | all → R5 | final evidence files and a 10-second screen recording of your part | `docs/eval/`, shared drive |
| **Sun Oct 25 6 pm · M3** | all | feature freeze | `main` |

**The engine version is pinned for each dataset.** A change to `ninety/sim` changes the truth.
Training data and the test set must come from the same tagged engine, and every vision report
records the tag. R1 keeps working on `main` between tags; R2 renders only from a tag.

## Day by day

What each role ships each day. "Done when" is checked in the evening check-in. Work that only
the cut list allows is marked *(cut 1)* to *(cut 5)*, matching [PLAN.md](PLAN.md#scope-control).

| Date | R1 Football truth | R2 Synthetic video | R3 Vision and scoring | R4 Agents | R5 Experience and platform |
|---|---|---|---|---|---|
| Thu 15 | Stats engine v0 on simulator events: pass distance and completion, ball speed | Realism pass: lighting, kit contrast, crowd, motion blur knobs | Scoring harness: match detected to true events by time and place; precision and recall per type, run on simulator events as fake detections | Ledger interface (in memory); cue fixture for R5 | Viewer skeleton (Vite + TypeScript): video plus canvas overlay from the cue fixture |
| Fri 16 | Stats v1: shot speed, sprints, pass difficulty from distance, angle, pressure | Randomize camera, lighting and kits per clip; render throughput measured | RF-DETR Small baseline on the existing test clips (guide check 2) | Agent Framework workflow v1: Analyst, Tactician, Challenger, Fact-checker, Producer on replayed events | Bicep and `azd` skeleton: Container App, App Insights, OIDC deploy of the viewer |
| Sat 17 | Tag `engine-v1`; engine step 1 (body and energy) PR | **Dataset v1**: ~20 train clips, fixed 5-clip test set, manifest | Fine-tune RF-DETR on dataset v1 | MCP server reads the Ledger; workflow writes `overlay_cue` | Persona switch (analyst, casual); agent trace panel |
| Sun 18 | Control vs chaos, pressing windows, tempo | Second camera angle *(cut 1)* | ByteTrack; team assignment by kit colour | Fact-checker confidence gating: hold back claims built on low-confidence events | Player cam: follow one tracked player; name tags and speed badge |
| Mon 19 | Engine step 2 (perception, team brain) PR | Off-the-shelf detector check in `render-checks.json`; demo clip candidates | Pitch keypoints and homography; possession state machine; event rules; `vision-report-v1` | Agent evaluation on the workflow: planted false claims, catch rate | Describer: Speech SSML, stereo position from ball x |
| **Tue 20 · M1** | Stats run on detected events, not only truth | Render the M1 clip | Detected events feed the Ledger | Switch agents to detected events; test that nothing on the live path reads ground truth | `ninety-e2e` command runs the whole chain; M1 demo in the viewer |
| Wed 21 | Engine step 3 (decisions and execution) PR | Data agent: failure clusters → render parameters; round 1 renders | Retrain on round 1; `vision-report-v2` with before and after | Vision Auditor; Personalizer as a separate service over A2A with in-process fallback | Second language via Translator; latency logging to graphic and to speech |
| Thu 22 | Tag `engine-v2` if changed; realism report across patterns | Round 2 renders *(cut 3)* | Live detection as a Container Apps job on the demo clip | Four injected failures and their fallbacks; OpenTelemetry spans | Deploy the full stack; Replay and passcode-gated Live modes |
| **Fri 23 · M2** | Fix anything the deployed run exposes | Final demo clip at full quality | Round 2 retrain; final vision numbers | Cosmos DB behind the Ledger interface *(cut 5)* | `azd up` from a clean clone; live smoke test in CI |
| Sat 24 | `README` numbers for stats and engine | b-roll renders for the video | `vision-report` final; speed error | `ablation.md`, `failure-table.md`, `fact-checker.md` | Keyboard navigation, reduced motion; WebVTT and audio track export; `latency-cost.md` |
| **Sun 25 · M3** | Bug fixes | Bug fixes | Bug fixes | Bug fixes | Demo script locked; record every shot from the deployed app |
| Mon 26 | Review README and project page | Review video for trademarks and real-world likeness | Review every published vision number against its file | Challenge map statuses | Edit the video; project page |
| **Tue 27 · M4** | | | | | Submit by 12 pm PT; check demo link and budget |

If M1 slips, the cut list applies the same day. The never-cut list in PLAN.md holds for every role.

## Staying in sync

### Contracts

The three schemas in `schemas/` are the only interface between roles. Code never reaches into
another role's internals.

- **Every schema has a fixture** in `tests/fixtures/`, and a test checks that the fixture
  validates. Build against the fixture, not against someone's branch.
- **Changing a schema** takes one pull request with the label `contract` that changes the
  schema, the fixture and both sides' code together, approved by the producer, the consumer and
  R4. Never change a schema in a pull request about something else.
- **Adding an optional field** needs only the consumer's approval. Removing or renaming a field
  needs everyone who reads it.

### Cadence

- **Morning, by 10 am PT, in writing (two minutes):** yesterday's result, today's done-when, and
  who you are waiting on, if anyone.
- **Evening check-in (15 minutes, everyone on a call):** each role shows its done-when running,
  not described. R5 runs `ninety-e2e` on `main` live from M1 onwards.
- **Blocked for more than an hour?** Say so straight away, and say who you are waiting on.
  Don't wait for the check-in.

### Pull requests

- Small and single-purpose, merged the same day. Merge `main` into your branch every morning.
- CI must be green before merge, and its result must be read, not assumed ([LESSONS.md](LESSONS.md)).
- One review from the reviewer in the [ownership table](#who-owns-which-code). Engine pull
  requests also get R3's audit for scripted outcomes.
- A decision that changes more than one role's work gets a short record in `docs/decisions/`.

### One source of truth

| Question | Answered by |
|---|---|
| What are we building and why? | [BRIEF.md](BRIEF.md), [ARCHITECTURE.md](ARCHITECTURE.md) |
| What is due when? | [PLAN.md](PLAN.md), this file |
| What runs today? | [CHALLENGE_MAP.md](CHALLENGE_MAP.md), updated by each row's owner |
| How is a number measured? | [EVALUATION.md](EVALUATION.md) |
| What must never happen again? | [LESSONS.md](LESSONS.md) |

## Working with coding agents

Every teammate works with a coding agent (Copilot, Cursor or Claude Code). They all read
[AGENTS.md](../AGENTS.md), which points here.

- **Tell your agent your role** at the start of a session ("I am R3, vision and scoring"). An
  agent should change only its role's paths, and stop and ask before editing any other path.
- **One task per session and per pull request.** Paste the day's done-when into the prompt.
- **Your agent's code is your code.** You review the diff before you push, and you can explain
  every line of it in the check-in.
- **Reverse-engineering tools** (for example REA) may be used only on software we wrote or are
  licensed to analyse. Never run one on a commercial game: game licences forbid it, and the
  engine must cite sources in GROUNDING.md, not what a game does.
