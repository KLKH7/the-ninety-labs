# The Ninety Labs

**AI that watches the match, logs every event, and describes it to every fan, including the ones who can't see it.**

The Ninety Labs is an entry for the Microsoft x Premier League *Inside the Game: Developer Hackathon*
(challenge: *The Synthetic Match Insights Engine for Premier League Studio*). It starts one step
earlier than an event feed: from **video**. A computer-vision pipeline watches a synthetic
broadcast and detects every event automatically. Its output is scored against hidden ground-truth
data, explained by a team of agents, drawn back onto the footage as on-screen graphics, and
personalized for every viewer, including live audio description for blind and low-vision fans.

All clubs, players and matches are synthetic. No real match data or footage is used.

## Why

Football event data is still typed by hand. Opta assigns three analysts per match, StatsBomb two
per match with delivery inside 12 hours, and contract taggers are paid around $70 a match to log
up to 3,000 actions ([Rest of World, 2026](https://restofworld.org/2026/fifa-world-cup-ai-data-workers/)).
Humans also disagree: providers' shot locations differed by more than five yards on 30% of shots
at the 2018 World Cup ([ASA](https://americansocceranalysis.com/home/2019/9/30/shots-in-the-dark-how-data-providers-tell-us-different-versions-of-what-happened)).
That cost is why data stops at the top flight. Downstream, every viewer gets the same on-screen graphics,
and blind and low-vision fans depend on human describers available in only some stadiums.

## The pipeline

```
 synthetic match engine ──► broadcast render (video)          hidden ground-truth data
                                   │                                     │
 INGEST       computer vision: detect → track → map to pitch → events    │
 INTERPRET    stats: pass quality, ball & shot speed, sprint speed, xG,  │
              control vs chaos                                           │
 EXPLAIN      agents: Analyst → Tactician ⇄ Fact-checker → Producer      │
 RENDER       on-screen graphics drawn on the footage                    │
 PERSONALIZE  analyst / casual / club / player cam / language / audio    │
                                                                         ▼
 SCORE        live precision and recall per event vs ground truth
 IMPROVE      generate more footage where vision fails, measure again
```

The challenge brief and rubric: [docs/BRIEF.md](docs/BRIEF.md).
How every requirement of the brief maps to code: [docs/CHALLENGE_MAP.md](docs/CHALLENGE_MAP.md).
Architecture and Microsoft stack: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Build plan: [docs/PLAN.md](docs/PLAN.md).
Security (this repo and the demo are public): [SECURITY.md](SECURITY.md).

## Repo layout

| Path | What lives there |
|---|---|
| `ninety/sim` | Seeded match engine: events + per-frame positions (the ground-truth data) |
| `web/render` | Broadcast-style three.js renderer that turns a sim run into video |
| `ninety/vision` | Detection, tracking, camera-to-pitch mapping, possession, event rules |
| `ninety/intel` | Deterministic stats engine (code computes every number) |
| `ninety/agents` | Agent Framework workflow: Analyst, Tactician, Fact-checker, Producer, Personalizer, Describer |
| `ninety/mcp` | MCP server exposing match tools to the agents |
| `ninety/eval` | Grades automatically detected events against the ground-truth data |
| `schemas` | JSON Schemas: match event, frame, on-screen graphic |
| `web` | Viewer: video + overlays + persona controls |
| `infra` | `azd` / Bicep for Azure Container Apps |

## Quick start

```bash
uv sync
uv run ninety-sim --seed 7 --minutes 5 --out runs/seed7
uv run pytest
```

## Status

Day 1 of the build. See [docs/PLAN.md](docs/PLAN.md). Claims in this README describe the design;
the demo and the measured numbers are the source of truth once they exist.

## License

MIT. Detection uses Apache-2.0 / MIT models only (no AGPL dependencies) so the project stays MIT.
