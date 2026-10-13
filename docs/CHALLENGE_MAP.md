# Challenge map

Every requirement in the challenge brief, and where The Ninety Labs answers it. Keep this file honest:
mark a row `planned` until it runs in the demo.

| Brief | Requirement | The Ninety Labs | Where | Status |
|---|---|---|---|---|
| (i)(a) | **Ingest** synthetic events as they happen | Events are generated live from the synthetic broadcast by the vision pipeline, streamed as they are detected | `ninety/vision`, `schemas/match_event.schema.json` | planned |
| (i)(b) | **Interpret** into stats, patterns, context | Deterministic stats engine over the event + tracking stream | `ninety/intel` | planned |
| (i)(c) | **Explain** why a moment matters | Tactician proposes, Verifier rejects unsupported claims, every number from code | `ninety/agents` | planned |
| (i)(d) | **Render** on screen alongside the match | Timed, machine-readable overlay cues drawn on the footage at detected positions | `schemas/overlay_cue.schema.json`, `web` | planned |
| (i)(e) | **Personalize**: analyst vs casual, favourite club, favourite player, player-focus mode, language, single metric | Personalizer renders one fact set per viewer profile; player-focus crops the camera to one player; audio description for blind and low-vision fans | `ninety/agents`, `web` | planned |
| (ii) | Player identification: live name tags, speed/distance shown past thresholds | Tracker IDs bound to roster, tags drawn on video, speed badge when sprint threshold crossed | `ninety/vision`, `web` | planned |
| (ii) | Pass quality: distance, accuracy, difficulty | Pass distance and completion from tracking; difficulty model from distance, angle, pressure, lane occupancy | `ninety/intel` | planned |
| (ii) | Speed metrics: ball speed, shot speed | Ball track in pitch metres, smoothed, speed per frame; shot speed at release | `ninety/vision`, `ninety/intel` | planned |
| (ii) | **Auto-eventing** from an incoming video feed | The core of The Ninety Labs: detection → tracking → homography → possession → event rules, graded vs truth | `ninety/vision`, `ninety/eval` | planned |
| (iii) | Narratives, player context, milestones, recaps | Producer + narrator agents; half-time and full-time recaps from the verified fact log | `ninety/agents` | planned |
| (iv) | Explainability: control vs chaos, pressure changes, rhythm | Control-vs-chaos index, pressing intensity windows, tempo; shift detection fed to the Tactician | `ninety/intel` | planned |
| (v) | **Data innovation**: create/extend synthetic datasets | Seeded match engine with truth log; broadcast renderer; hard-case generator that targets vision failures | `ninety/sim`, `web/render` | in progress |
| (vi) | Multi-language storytelling | Localizer agent + Azure Translator; Azure AI Speech voices per language | `ninety/agents` | planned |

## Judging criteria → evidence

| Criterion (20% each) | What we show |
|---|---|
| Technological implementation | Synthetic video + truth log, graded auto-eventing, tests, CI, IaC |
| Agentic design & innovation | Multi-agent workflow with Verifier veto, MCP tools, A2A Personalizer |
| Real-world impact | Removes human event logging; accessible audio description |
| UX & presentation | Overlays on real footage, persona switch, 2-minute video |
| Category adherence | Best Multi-Agent System (primary), Best Use of Foundry (fallback) |
