# Architecture

The Ninety Labs turns synthetic broadcast video into explained, personalized match intelligence.
This document describes the system as designed. What already runs is tracked in
[CHALLENGE_MAP.md](CHALLENGE_MAP.md); the delivery schedule is in [PLAN.md](PLAN.md).

## Contents

1. [Design rules](#design-rules)
2. [System overview](#system-overview)
3. [Synthetic data pipeline](#synthetic-data-pipeline)
4. [Agent design](#agent-design)
5. [One moment, end to end](#one-moment-end-to-end)
6. [Deployment on Azure](#deployment-on-azure)
7. [Technology decisions](#technology-decisions)
8. [Data contracts](#data-contracts)

## Design rules

1. **Code computes every number. Models only explain.** Agents read typed facts with ids; the
   fact-checking agent rejects any sentence whose numbers or entities are not in the evidence.
2. **Facts before words.** Every insight is a timestamped fact before it becomes text, so one fact
   renders to any persona or language without recomputing.
3. **Scored perception.** The simulator's ground-truth data is never visible downstream. It is used
   only by `ninety/eval` to score what the vision pipeline produced.
4. **Nothing waits on a model.** A template graphic airs the moment an event is detected; the
   verified graphic replaces it in the same slot.
5. **Every failure has a fallback.** Model outage, remote agent down or low vision confidence
   degrade the output; they never stop it.

## System overview

The five stages named in the challenge brief, with the scoring loop that sets this project apart.

```mermaid
flowchart LR
    SIM["Synthetic match<br/>and video"] --> INGEST["1 Ingest"] --> INTERPRET["2 Interpret"] --> EXPLAIN["3 Explain"] --> RENDERSTAGE["4 Render"] --> PERSONALIZE["5 Personalize"]
    SIM --> TRUTH[("Ground truth<br/>sealed")]
    INGEST -.-> SCORE["Scoring"]
    TRUTH -.-> SCORE
    SCORE --> GEN["Targeted<br/>data"] --> SIM
```

| Stage | What happens | Code |
|---|---|---|
| Synthetic data | a seeded match engine plays the match; a broadcast renderer turns it into video and records exact ground truth | `ninety/sim`, `ninety/render`, `web/render` |
| 1 Ingest | detection, tracking and camera-to-pitch mapping turn the video into events (automatic event detection) | `ninety/vision` |
| 2 Interpret | pass distance, accuracy and difficulty, ball and shot speed, sprint speed, xG, control vs chaos | `ninety/intel` |
| 3 Explain | agents explain why a moment matters; the fact-checking agent gates every claim | `ninety/agents` |
| 4 Render | timed on-screen graphics drawn on the video at detected positions | `web`, `schemas/overlay_cue.schema.json` |
| 5 Personalize | analyst, casual, favourite club, player cam, languages, audio description | `ninety/agents`, `web` |
| Scoring | detected events are scored against the sealed ground truth: precision and recall per event type | `ninety/eval` |
| Targeted data | where detection fails, more footage of exactly that situation is generated, then scored again | `ninety/sim`, `web/render` |

## Synthetic data pipeline

How a match becomes video with known truth, and how failures in vision turn into new data.
Solid lines run every time; dotted lines are the answer key, which only training and scoring
may read.

```mermaid
flowchart TB
    ENG["Match engine<br/>football logic, physics"] -- "ground truth:<br/>events, frames" --> VAL["Validator<br/>laws, physics, consistency"]
    VAL -- "fails: fix the engine" --> ENG
    VAL -- passes --> REN["Renderer (three.js)"]
    REN -- "broadcast video" --> VIS["Vision pipeline"]
    REN -. "render labels,<br/>training only" .-> VIS
    VIS -- "detected events" --> SC["Scoring"]
    ENG -. "answer key" .-> SC
    SC --> LOOP["Vision Auditor, Data agent"]
    LOOP -- "new scenarios" --> ENG
```

Every check in the validator, and every rule the engine follows, cites its source: a Law of
the Game, a sports-science measurement or a published match statistic ([GROUNDING.md](GROUNDING.md)).

| Part | Job | Code | Status |
|---|---|---|---|
| Match engine | **makes** the match: applies football logic and physics every 1/25 s and writes each frame and event | `ninety/sim` | running, physics gaps |
| Ground truth | the engine's output: the synthetic data itself | `events.jsonl`, `frames.jsonl` | running |
| Validator | **inspects** the output, independently of the engine's code: a clip that breaks a law, physics or its own events never reaches the renderer | `ninety/validate.py` | running, engine fails it today |
| Renderer | draws the frames as broadcast video; decides nothing about football | `web/render`, `ninety/render` | running |
| Render labels | each player's and the ball's box, projected through the camera, so labels are exact | `web/render` | running |
| Vision pipeline | sees pixels only: detection, tracking, camera-to-pitch mapping, event rules | `ninety/vision` | planned |
| Scoring | compares detected events with the answer key: precision and recall per event type | `ninety/eval` | planned |
| Vision Auditor, Data agent | find where vision fails and ask the engine for more of exactly those scenes | `ninety/agents` | planned |

The engine and the validator are separate on purpose. The engine encodes *how to make* a
moment happen; the validator encodes *what must be true* of the result. Written independently
from the same source, a bug in one is caught by the other, and a law the engine does not model
yet shows up as a failing check, which is the engine's to-do list.

## Agent design

Each agent has one job and reads and writes a shared, versioned Ledger. Code agents are
deterministic; model agents run on Microsoft Foundry deployments and are orchestrated with
Microsoft Agent Framework.

```mermaid
flowchart LR
    DETECTOR["Detector<br/><i>code</i>"] --> LEDGER[("Ledger<br/>facts, source,<br/>confidence, evidence")]
    LEDGER <--> MCP{{"MCP server<br/>read-only tools"}}
    MCP --> ANALYST["Analyst<br/>what changed"]
    ANALYST --> TACTICIAN["Tactician<br/>why it matters"]
    TACTICIAN <--> CHALLENGER["Challenger<br/>alternative view"]
    TACTICIAN --> CHECKER{"Fact-checker<br/><i>code + agent</i>"}
    CHECKER -- rejected --> TACTICIAN
    CHECKER -- verified --> PRODUCER["Producer<br/>screen and voice"]
    PRODUCER -- A2A --> PERSONALIZER["Personalizer<br/><i>remote service</i>"]
    PRODUCER --> DESCRIBER["Describer<br/>audio description"]
    CHECKER -- low confidence --> AUDITOR["Vision Auditor<br/>failure clusters"]
    AUDITOR --> DATAAGENT["Data agent<br/>targeted renders"]
    DATAAGENT -. retrain .-> DETECTOR
```

| Agent | Kind | Reads | Writes | On failure |
|---|---|---|---|---|
| Detector | code | video frames | detected events with confidence | event marked low confidence |
| Analyst | model | Ledger via MCP tools | candidate moments | template graphic only |
| Tactician | model | moment + stats | explanation with cited evidence ids | template graphic only |
| Challenger | model | explanation + evidence | alternative explanation | skipped |
| Fact-checker | code + model | claim + evidence + confidence | verdict | claim held back |
| Producer | code | verified claims | graphic and voice schedule | template graphic only |
| Personalizer | model, remote (A2A) | verified claim + viewer profile | per-persona text | in-process default persona |
| Describer | model + Speech | verified events | spoken description | short code-written line |
| Vision Auditor | model | low-confidence and mismatched events | failure clusters | skipped |
| Data agent | code | failure clusters | render parameters for new scenes | skipped |

## One moment, end to end

What happens between a pass on screen and the graphic and spoken line that explain it.

```mermaid
sequenceDiagram
    autonumber
    participant V as Video frame
    participant D as Detector
    participant L as Ledger
    participant S as Stats engine
    participant A as Analyst and Tactician
    participant F as Fact-checker
    participant P as Producer
    participant R as Personalizer (A2A)
    participant U as Viewer

    V->>D: frame
    D->>L: pass detected, confidence 0.91
    L->>S: new event
    S->>L: pass difficulty, speed, pressure
    P->>U: template graphic, instantly
    L->>A: moment worth explaining
    A->>F: claim with evidence ids
    alt claim not supported
        F-->>A: rejected with reason
        A->>F: revised claim
    end
    F->>P: verified claim
    P->>R: claim + viewer profile
    R-->>P: analyst and casual versions
    P->>U: verified graphic replaces template
    P->>U: spoken description (audio mode)
```

## Deployment on Azure

All resources live in one resource group. Services authenticate with managed identity, and
GitHub deploys with OpenID Connect, so no key or secret is stored in the repo or in GitHub.

```mermaid
flowchart LR
    GH["GitHub Actions<br/>CI then deploy"] -- OIDC, no secrets --> RG

    subgraph RG["Resource group: ninety-labs"]
        APP["Container App<br/>viewer + API"]
        PERS["Container App<br/>Personalizer (A2A)"]
        JOB["Container Apps job<br/>vision on CPU"]
        COSMOS[("Cosmos DB<br/>Ledger")]
        INSIGHTS["Application Insights<br/>traces and latency"]
    end

    FOUNDRY["Microsoft Foundry<br/>model deployments,<br/>evaluations, tracing"]
    SPEECH["Azure AI Speech<br/>and Translator"]

    USER["Viewer in a browser"] --> APP
    APP --> COSMOS
    JOB --> COSMOS
    APP -- managed identity --> FOUNDRY
    APP -- A2A --> PERS
    PERS -- managed identity --> FOUNDRY
    APP -- managed identity --> SPEECH
    APP --> INSIGHTS
    PERS --> INSIGHTS
```

The public demo has two modes. **Replay** serves a cached match and costs nothing per view.
**Live** re-runs the agents and speech on the demo clip and is passcode-gated. A $20 monthly
budget alert covers the subscription. See [SECURITY.md](../SECURITY.md).

## Technology decisions

| Area | Decision | Reason |
|---|---|---|
| Renderer | three.js scene driven by `ninety-sim`, captured headless with Playwright at 1280x720, 25 fps; Python computes the camera and body geometry, the page draws it and counts an object-id pass | exact camera matrix per frame and visibility counted from what was drawn ([decision 0001](decisions/0001-synthetic-data.md)) |
| Frame data | compact JSON lines per clip today (about 4.4 KB a frame); Parquet (pyarrow) planned for long clips | a 90-minute match was 180 MB as JSON lines |
| Clip length | 2 to 5 minutes | render and training time |
| Detection | RF-DETR (Apache-2.0) fine-tuned on our renders; ByteTrack via supervision (MIT) | permissive licences only |
| Camera-to-pitch mapping | keypoint heatmap model (PyTorch) trained on render keypoints; homography with RANSAC (OpenCV) | labels come free from the renderer |
| Team assignment | kit-colour clustering on player crops; referee as a third cluster | simple and reliable on synthetic kits |
| Event detection | possession state machine on pitch coordinates; one rule per event type with a confidence | measurable, explainable |
| Training compute | Apple GPU (MPS) or free Colab | no GPU quota assumed |
| Agents | Microsoft Agent Framework (Python), models on Microsoft Foundry | multi-agent orchestration with handoffs and recovery |
| Shared state | Ledger in Cosmos DB (free tier) | one versioned record every agent reads |
| Agent tools | MCP server, read-only | standard tool interface, safe by construction |
| Personalizer | separate Container App over A2A, in-process fallback | a real process boundary |
| Speech | Azure AI Speech neural voices with SSML; stereo position from ball x in the browser | audio description |
| Viewer | Vite + TypeScript; video with a canvas overlay synced to the graphics timeline | graphics drawn on the footage |
| Observability | OpenTelemetry to Application Insights; Foundry tracing | latency and failure evidence |
| Infrastructure | Bicep + `azd`; GitHub Actions with OIDC | one-command deploy, no secrets |
| Not used | Event Hubs, Fabric, GPU | cost and scope for a 14-day build |

## Data contracts

The schemas are the interface between the two build tracks. Changing one needs agreement in the
pull request.

| Schema | Describes | Produced by | Consumed by |
|---|---|---|---|
| [`match_event.schema.json`](../schemas/match_event.schema.json) | one event, from ground truth or detected (`source`, `confidence`) | match engine, vision | stats engine, agents, scoring |
| [`frame.schema.json`](../schemas/frame.schema.json) | positions at one frame | match engine, renderer, tracker | renderer, scoring |
| [`overlay_cue.schema.json`](../schemas/overlay_cue.schema.json) | one timed on-screen graphic | Producer, Personalizer | viewer, WebVTT export |

What a ground-truth clip must contain, and the validator that checks it: [DATA_CONTRACT.md](DATA_CONTRACT.md).
