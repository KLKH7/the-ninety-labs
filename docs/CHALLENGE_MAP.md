# Challenge map

Every requirement in the challenge brief, and where The Ninety Labs answers it. Keep this file honest:
mark a row `planned` until it runs in the demo. Milestones are defined in [PLAN.md](PLAN.md#milestones).

| Brief | Requirement | The Ninety Labs | Where | Milestone | Status |
|---|---|---|---|---|---|
| (i)(a) | **Ingest** synthetic events as they happen | Events are generated live from the synthetic broadcast by the vision pipeline, streamed as they are detected | `ninety/vision`, `schemas/match_event.schema.json` | M1 | planned |
| (i)(b) | **Interpret** into stats, patterns, context | Deterministic stats engine over the event + tracking stream | `ninety/intel` | M1 | planned |
| (i)(c) | **Explain** why a moment matters | Tactician proposes, fact-checking agent rejects unsupported claims, every number from code | `ninety/agents` | M1 | planned |
| (i)(d) | **Render** on screen alongside the match | Timed, machine-readable on-screen graphics drawn on the footage at detected positions | `schemas/overlay_cue.schema.json`, `web` | M1 | planned |
| (i)(e) | **Personalize**: analyst vs casual, favourite club, favourite player, player cam, language, single metric | Personalizer renders one fact set per viewer profile; player cam follows one player; audio description for blind and low-vision fans | `ninety/agents`, `web` | M2 | planned |
| (ii) | Player identification: live name tags, speed/distance shown past thresholds | Tracker IDs bound to roster, tags drawn on video, speed badge when sprint threshold crossed | `ninety/vision`, `web` | M2 | planned |
| (ii) | Pass quality: distance, accuracy, difficulty | Pass distance and completion from tracking; difficulty model from distance, angle, pressure, lane occupancy | `ninety/intel` | M1 | planned |
| (ii) | Speed metrics: ball speed, shot speed | Ball track in pitch metres, smoothed, speed per frame; shot speed at release | `ninety/vision`, `ninety/intel` | M1 | planned |
| (ii) | **Automatic event detection** from an incoming video feed | The core of The Ninety Labs: detection → tracking → camera-to-pitch mapping → possession → event rules, graded vs truth | `ninety/vision`, `ninety/eval` | M1 | planned |
| (iii) | Narratives, player context, milestones, recaps | Producer + narrator agents; half-time and full-time recaps from the verified fact log | `ninety/agents` | M1 | planned |
| (iv) | Explainability: control vs chaos, pressure changes, rhythm | Control-vs-chaos index, pressing intensity windows, tempo; shift detection fed to the Tactician | `ninety/intel` | M1 | planned |
| (v) | **Data innovation**: create/extend synthetic datasets | Seeded match engine with ground-truth data; broadcast renderer; targeted synthetic data generation where vision fails | `ninety/sim`, `web/render` | M1 | in progress |
| (vi) | Multi-language storytelling | Localizer agent + Azure Translator; Azure AI Speech voices per language | `ninety/agents` | M2 | planned |

## Judging criteria → evidence

| Criterion (20% each) | What we show |
|---|---|
| Technological implementation | Synthetic video + ground-truth data, graded automatic event detection, tests, CI, IaC |
| Agentic design & innovation | Multi-agent workflow with a confidence-aware fact-checking agent, Vision Auditor and Data agent loop, MCP tools, A2A Personalizer, ablation and failure table |
| Real-world impact | Removes human event logging; accessible audio description |
| UX & presentation | On-screen graphics drawn on the footage, persona switch, 2-minute video |
| Category adherence | Best Multi-Agent System (primary), Best Use of Foundry (fallback) |
