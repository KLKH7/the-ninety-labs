# Architecture

## Design rules

1. **Code computes every number. Models only explain.** Agents read typed facts with ids; the
   fact-checking agent rejects any sentence whose numbers or entities are not in the evidence.
2. **Facts before words.** Every insight is a timestamped fact before it becomes text, so one fact
   renders to any persona or language without recomputing.
3. **Graded perception.** The simulator's ground-truth data is never visible downstream; it is only used
   by `ninety/eval` to score what the vision pipeline produced.
4. **Nothing waits on a model.** A template cue airs the moment an event is detected; the verified
   agent cue replaces it in the same slot.

## Components

| Stage | Component | Tech |
|---|---|---|
| Data | `ninety/sim` match engine, `web/render` broadcast renderer | Python, three.js |
| Ingest | detection, tracking, camera-to-pitch mapping, possession, event rules | roboflow/sports + supervision (MIT), RF-DETR (Apache-2.0), ByteTrack |
| Interpret | stats engine | Python, socceraction/kloppy for SPADL + xT |
| Explain | Analyst, Tactician, Fact-checker, Producer | Microsoft Agent Framework (Python), Microsoft Foundry models |
| Render | on-screen graphics timeline | JSON Schema, WebSocket, web viewer |
| Personalize | Personalizer (A2A), Localizer, Describer | Foundry agent, Azure Translator, Azure AI Speech |
| Tools | match stats tools for agents | MCP server |
| Eval | precision/recall vs truth, Foundry groundedness evals | Python, Foundry Evaluations |
| Ops | containers, events, state, tracing | Azure Container Apps, Cosmos DB, App Insights, `azd`, GitHub Actions |

## Data contracts

- `schemas/match_event.schema.json`: one detected or simulated event.
- `schemas/frame.schema.json`: per-frame positions (ground-truth data and tracker output share it).
- `schemas/overlay_cue.schema.json`: one timed, machine-readable on-screen graphic.
