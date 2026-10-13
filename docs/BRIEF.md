# Challenge brief and rubric

The source of truth for what we are building. Quoted from the official
[Inside the Game rules](https://github.com/microsoft/insidethegamehackathon/blob/main/OFFICIAL%20RULES.md)
(MIT, Copyright 2026 Microsoft Corporation). If this file and the official rules disagree, the
official rules win.

## Challenge: The Synthetic Match Insights Engine for Premier League Studio

> An AI insights engine runs on Azure that explains the game beyond the stats, turning football
> events into real-time insights, key narratives and recaps, personalized for every fan, for
> studio and streaming use.

Projects must use **synthetic, football-realistic data**. No real Premier League match data is
redistributed to participants.

### Required: one pipeline with five stages

| Stage | The project should |
|---|---|
| Ingest | take in synthetic match events as they happen (passes, shots, tackles, possession changes, pressure events, match metadata) |
| Interpret | turn them into meaningful football statistics, patterns and the context behind them |
| Explain | explain why a moment matters, not only report that it happened |
| Render | turn the insight into something that can sit on screen alongside the match |
| Personalize | make the same intelligence reach a data-hungry analyst and a casual fan as two genuinely different experiences: modes, favourite clubs, favourite players, a player-focused mode, language, a single metric the viewer cares about |

Output should be timed and machine-readable enough to render as synchronized graphics over a live
match feed. A project that only generates metrics has no audience; one that only personalizes has
nothing to personalize.

### Features to consider

- **Player identification:** live player name tags, with speed and distance shown when thresholds are reached
- **Pass quality:** pass distance, pass accuracy, pass difficulty rating
- **Speed metrics:** ball speed and shot speed
- **Automatic event detection:** running a model over an incoming video feed to generate the pass and speed metrics automatically, rather than tagging them by hand
- **Narrative generation:** key narratives, player-performance context, milestones, match recaps
- **Explainability:** why moments matter, such as control vs chaos, tactical pressure changes, game rhythm
- **Data innovation:** create or extend synthetic football-realistic datasets
- **Multi-language storytelling:** clear natural-language output for global audiences

## Judging (equal weight, 20% each)

1. **Technological implementation:** creative, optimized synthetic data creation; quality software practices; effective use of Microsoft Foundry, Agent Framework, Azure MCP, GitHub Copilot Agent Mode, Fabric, GitHub SDK/CLI, Azure apps, AI services and databases; well-structured, documented, maintainable code.
2. **Agentic design and innovation:** creative agentic patterns; sophisticated orchestration, MCP integration or multi-agent collaboration; novel, or a meaningful improvement on existing approaches.
3. **Real-world impact:** significance of the problem; could it run in production; impact on developers, businesses or users.
4. **User experience and presentation:** intuitive design; the demo video (under 2 minutes) communicates the value; balanced frontend and backend.
5. **Category fit:** matches the description of the category entered.

Stage one is pass/fail: the project must fit the theme and use the required technologies.

## Categories

- **Best Use of Microsoft Foundry**
- **Best Enterprise Solution:** ready for enterprise deployment; reliability, transparency, controls
- **Best Multi-Agent System** (our target): specialized agents with distinct roles, shared state, effective handoffs, recovery from failure, and an end-to-end outcome a single agent could not reach as well
- **Best Azure Cloud Native Integration:** AKS, Container Apps, Functions, Logic Apps, event-driven design, operational excellence

## Submission checklist

- [ ] Public GitHub repo
- [ ] Project page: pitch naming the Microsoft and Azure technologies used
- [ ] Demo video under 2 minutes, public URL (YouTube or Vimeo), no third-party trademarks or copyrighted music
- [ ] Working demo link, free to use, live until Nov 10, 2026
- [ ] Everything built after Sep 29, 2026; open-source dependencies used under their licenses
- [ ] Submitted by Oct 27, 2026, 11:59pm PT
