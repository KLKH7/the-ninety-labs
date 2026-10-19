# Challenge map

Every requirement in the challenge brief, and where The Ninety Labs answers it. Keep this file honest:
mark a row `planned` until it runs in the demo. Milestones are defined in [PLAN.md](PLAN.md#milestones).

| Brief | Requirement | The Ninety Labs | Where | Milestone | Status |
|---|---|---|---|---|---|
| (i)(a) | **Ingest** synthetic events as they happen | Events are generated live from the synthetic broadcast by the vision pipeline, streamed as they are detected | `ninety/vision`, `schemas/match_event.schema.json` | M1 | planned |
| (i)(b) | **Interpret** into stats, patterns, context | Deterministic stats engine over the event + tracking stream: pass, shot, possession, pressure and movement facts with cited event ids or frame ranges, and an experimental control-vs-chaos index (running, [INTELLIGENCE.md](INTELLIGENCE.md)); pass difficulty, xG, tempo and pressure windows (planned) | `ninety/intel` | M1 | in progress |
| (i)(c) | **Explain** why a moment matters | Analyst picks up to three moments a minute over MCP, Tactician explains each, Challenger offers another reading, the fact-checking agent (code checks, then the Judge) checks both and sends a rejected claim back to its author, and the Producer airs a verified insight in place of the template graphic; every number from code. Workflow runs with scripted models in tests; live recording pending | `ninety/agents/workflow.py`, `tests/test_workflow.py` | M1 | in progress |
| (i)(d) | **Render** on screen alongside the match | Ledger-backed deterministic template cues provide timed, machine-readable graphics before model explanations; viewer rendering remains planned | `ninety/agents/ledger.py`, `ninety/agents/cues.py`, `ninety/agents/live.py` (cues from detected events; a hand-written stand-in until the detector's events land), `tests/fixtures/cues-seed7.jsonl`, `schemas/overlay_cue.schema.json`, `web` | M1 | in progress |
| (i)(e) | **Personalize**: analyst vs casual, favourite club, favourite player, player cam, language, single metric | Personalizer renders one fact set per viewer profile; player cam follows one player; audio description for blind and low-vision fans | `ninety/agents`, `web` | M2 | planned |
| (ii) | Player identification: live name tags, speed/distance shown past thresholds | Tracker IDs bound to roster, tags drawn on video, speed badge when sprint threshold crossed | `ninety/vision`, `web` | M2 | planned |
| (ii) | Pass quality: distance, accuracy, difficulty | Pass distance and completion from tracking; difficulty model from distance, angle, pressure, lane occupancy | `ninety/intel` | M1 | planned |
| (ii) | Speed metrics: ball speed, shot speed | Ball track in pitch metres, smoothed, speed per frame; shot speed at release | `ninety/vision`, `ninety/intel` | M1 | planned |
| (ii) | **Automatic event detection** from an incoming video feed | The core of The Ninety Labs: detection → tracking → camera-to-pitch mapping → possession → event rules, graded vs truth | `ninety/vision`, `ninety/eval` | M1 | planned |
| (iii) | Narratives, player context, milestones, recaps | Producer + narrator agents; half-time and full-time recaps from the verified fact log | `ninety/agents` | M1 | planned |
| (iv) | Explainability: control vs chaos, pressure changes, rhythm | Control-vs-chaos index, pressing intensity windows, tempo; shift detection fed to the Tactician | `ninety/intel` | M1 | planned |
| (v) | **Data innovation**: create/extend synthetic datasets | Seeded match engine with ground-truth data (running); broadcast renderer with exact camera, boxes, visibility and keypoints, hard-case knobs (kit contrast, kit pattern, crowding, camera, blur, camera cuts; day and clear only, with dusk, night, overcast and rain planned) and a fixed test split (running, [decision 0001](decisions/0001-synthetic-data.md)); referees wait until the engine has an official to draw (the renderer does not invent one); targeted synthetic data: the Data agent queues render requests from failure clusters and an event-driven Azure job renders them, ground truth sealed in its own container (running); the first round on real detector failures (planned) | `ninety/sim`, `ninety/render`, `web/render` | M1 | in progress |
| (vi) | Multi-language storytelling | Localizer agent + Azure Translator; Azure AI Speech voices per language | `ninety/agents` | M2 | planned |

## Judging criteria → evidence

| Criterion (20% each) | What we show |
|---|---|
| Technological implementation | Synthetic video + ground-truth data (render checks in CI), graded automatic event detection, tests, CI, IaC |
| Agentic design & innovation | Multi-agent workflow with a confidence-aware fact-checking agent, Vision Auditor and Data agent loop, MCP tools, A2A Personalizer, ablation and failure table |
| Real-world impact | Removes human event logging; accessible audio description |
| UX & presentation | On-screen graphics drawn on the footage, persona switch, 2-minute video |
| Category adherence | Best Multi-Agent System (primary), Best Use of Foundry (fallback) |
