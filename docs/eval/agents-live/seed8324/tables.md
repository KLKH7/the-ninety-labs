| moment | min | graph: anchor given / picked | graph: drafts v/r/h | graph aired | companion tool / args | target given | answer (source, status) |
|---|---|---|---|---|---|---|---|
| goal-1 | 12 | yes / yes | 0/0/1 (0 rewrites) | template stays | yes / yes | yes | "London Athletic scored in minute 12." (model, verified) |
| goal-2 | 35 | yes / yes | 1/0/0 (1 rewrites) | "The goal scored by a-t18090 at 34:01 changed the scoreline in minute 35 and was immediately confirmed at 34:04, underscoring its impact on the match." | yes / yes | yes | "a Lisbon Esportes player scored for Lisbon Esportes in minute 35." (model, verified) |
| goal-3 | 76 | yes / yes | 0/0/2 (0 rewrites) | template stays | yes / yes | yes | "Lisbon Esportes scored in minute 76." (model, verified) |
| goal-4 | 85 | yes / yes | 0/1/1 (2 rewrites) | template stays | yes / yes | yes | "Lisbon Esportes scored in minute 85." (model, verified) |
| line-break | 89 | yes / yes | 0/0/1 (1 rewrites) | template stays | yes / yes | yes | "In minute 89, a Lisbon Esportes player played a pass that took 5 London Athletic players out of the game." (model, verified) |
| overload | 60 | – / – | 0/0/2 (2 rewrites) | template stays | yes / yes | yes | "London Athletic built 6 overloads from minute 46 to minute 61, most often in their middle third in the centre." (model, verified) |
| quiet | 26 | – / – | 0/0/2 (0 rewrites) | template stays | yes / yes | – | "In minute 15, a London Athletic player shot from 36 m out, where the posts were 8 degrees apart." (model, verified) |
| half-time | 45 | – / – | 0/0/2 (0 rewrites) | template stays | yes / yes | – | "Possession can't be split between the clubs yet: vision could not tell surely which side made most of the passes." (code, verified) |

| stage | calls | p50 | max |
|---|---|---|---|
| model:analyst | 11 | 1.4 s | 4.2 s |
| model:challenger | 10 | 1.4 s | 10.8 s |
| model:companion | 18 | 1.3 s | 2.8 s |
| model:judge | 10 | 2.3 s | 4.0 s |
| model:tactician | 14 | 1.4 s | 2.0 s |
| mcp_call | 94 | 0.0 s | 0.0 s |
| graph_minute | 8 | 8.1 s | 19.4 s |
| companion_answer | 8 | 5.7 s | 6.7 s |

| drill | injected | fault hit | ends (v/r/h) | aired | what happened |
|---|---|---|---|---|---|
| drill:judge-down | every Judge call raises ServiceRequestError | **no** | 0/0/1 | nothing | challenger agree m-s07-v00002: ; fact_checker hold m-s07-v00002: tactician's claim: event s07-v00001's ball speed is vision's, whose error is measured only for a pass along the ground (this pass is not marked on the ground): state it without the speed; event s07-v00002's ball speed is vision's, whos |
| drill:judge-down-companion | None | yes | 0/0/0 | nothing | Companion: code answer, ['judge service error; claim held back'] |
| drill:vision-dropout | no detected events in the 60 s around the goal | yes | 0/0/0 | nothing | 8 events dropped; aired cites a dropped id: **no**; aired says goal: **no**. producer templates -: 490 template graphics on air |
| drill:slow-tactician | the Tactician answers after 65.0 s (budget 60.0 s) | yes | 0/0/1 | nothing | analyst pick m-s44-v00017: evidence ['s44-v00017', 's44-v00011', 's44-v00012', 's44-v00013', 's44-v00014', 's44-v00015', 's44-v00016']; tactician fail m-s44-v00017: TimeoutError: ; template stays; producer template m-s44-v00017: cue-s44-v00017-analyst stays: held |
| drill:slow-companion | the Companion answers after 12.0 s (budget 10.0 s) | yes | 0/0/0 | nothing | Companion: code answer, ['model timeout'] |
