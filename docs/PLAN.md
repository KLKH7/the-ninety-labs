# Build plan

Submission closes **Oct 27, 2026, 11:59pm PT**. Registration closes Oct 20, 12pm PT.
Submission needs: public repo, video under 2 minutes, a demo link live until Nov 10.

| Days | Milestone | Done when |
|---|---|---|
| 1 | Match engine + truth log | `spotter-sim` writes events + frames for a seeded match; tests pass |
| 2 | Broadcast render | three.js plays a run with a ball-following camera; exports video + per-frame camera matrix |
| 3 | Vision ingest | detections + tracks on rendered frames; pitch homography |
| 4 | Auto-eventing | possession state machine + pass/shot/tackle rules; events stream out |
| 5 | Eval | precision/recall per event type vs truth; seeded benchmark committed |
| 6 | Stats engine | pass difficulty, speeds, xG, control vs chaos |
| 7–8 | Agents | Agent Framework workflow, Verifier veto, MCP tools, Foundry models |
| 9 | Overlays | cues drawn on the video at detected positions |
| 10 | Personalize | personas, player-focus, languages, audio description (Azure Speech) |
| 11 | Data loop | hard-case generator, retrain/re-measure, show the delta |
| 12 | Azure | Container Apps deploy via `azd`, tracing, budget alert |
| 13 | Video + README | 2-minute demo video, numbers in README |
| 14 | Buffer | fix, trim claims to what ships, submit |

Budget: Azure for Students credit. Vision runs on CPU or precomputed; GPU is a stretch goal.
