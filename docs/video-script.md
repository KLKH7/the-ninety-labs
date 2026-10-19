# Demo video script (draft)

The 2-minute video, beat by beat, following the outline in [PLAN.md](PLAN.md#demo-video).
Recorded Oct 25 (M3, feature freeze), edited Oct 26, uploaded before submission on Oct 27.

Rules for every shot, from [BRIEF.md](BRIEF.md#submission-checklist) and
[PLAN.md](PLAN.md#building-in-public):

- Under two minutes; about 215 spoken words.
- Every shot from the deployed app, or from a command in this repo when the shot is a terminal.
- Synthetic footage, clubs and players only. No league, club, sponsor or broadcaster marks, no
  copyrighted music (silence or music we made).
- Every number on screen or in the voice-over comes from a committed evaluation file, named in the
  beat. A number marked `[from …]` is filled in from that file when the script is locked; until
  then it is not said.
- Never show the demo passcode, keys, connection strings or Azure resource names.

Status of each shot was checked against `main` at `b4d9402` (Oct 19, after the viewer and vision-report-v2 merged). **Capturable** means it can
be recorded from `main` today; **not yet** names what has to land first.

## Beats

### 1. The problem, and detection graded live (0:00 to 0:15)

**Picture.** The synthetic broadcast plays. Detected events appear as a list beside the ground-truth
events, with precision and recall updating as the clip runs.

**Voice (32 words).** "Every pass in professional football is still logged by hand. People watch,
click, and disagree. The Ninety Labs watches the video instead, and grades itself against an answer
key it never sees."

**Needs.** Events detected from pixels (tracking, camera-to-pitch mapping, possession and event
rules in `ninety/vision`); a scoring panel fed by `ninety/eval/event_score.py`, kept outside the
live path, shown in the viewer (`web/viewer`). Numbers `[from vision-report with event scores]`.

**Status: not yet.** Events from pixels are not on `main`; the live path reads a hand-written
stand-in. **Fallback if events are not measured by M3:** detector boxes against ground-truth boxes
on a test clip, drawn by `ninety/eval/draw.py`, with the object numbers from the latest merged
vision report (v2 today: players 0.994 recall, ball at least half visible 0.964). Say "players and
ball", never "events", in that case.

### 2. Targeted synthetic data raises recall (0:15 to 0:35)

**Picture.** A miss cluster (for example, balls mostly hidden in a crowded box), the Data agent's
render request, new renders of exactly that scene, then the before and after score on the same
frozen test set.

**Voice (37 words).** "Our match engine plays the football and writes the truth for every frame.
Where the detector fails, a Data agent orders more of exactly those scenes. One round on hidden
balls lifts recall from `[before]` to `[after]`."

**Needs.** Targeted round 1 with its before and after on the frozen test set (PLAN, Oct 21); the
Vision Auditor's failure clusters; the Data agent and render job (on `main`). Numbers
`[from the round-1 vision report]`.

**Status: not yet.** The Data agent and render job run; no targeted round has a result. Note that
[vision-report-v2](eval/vision-report-v2.md) is a matched-engine retrain, not a targeted round: it
may be shown as "training on footage from the same engine cut false detections from 121 to 27",
but never voiced as the targeted round.

### 3. The fact-checker rejects a planted claim (0:35 to 1:00)

**Picture.** The agent trace in the viewer: the Analyst's draft with a planted wrong number, the
fact-checking agent's rejection with the event it cites, the rewrite, the accepted graphic. Then
the same moment as the analyst sees it (number and evidence) and as the casual fan sees it (one
line).

**Voice (46 words).** "An Analyst agent drafts a claim. We plant a wrong number. The fact-checking
agent rejects it, cites the event, and sends it back. The rewrite passes. In testing it caught all
136 planted false claims. The analyst gets the evidence; the casual fan gets one line."

**Needs.** `ninety-e2e <clip> --out <bundle> --plant` opened in the viewer, or
`ninety-slice --replay replays/slice-minute2-plant.json` for the Foundry recording (both on `main`);
per-persona variants (#131) if more than the template
cues' analyst and casual wording is shown. Number from [fact-checker.md](eval/fact-checker.md)
(136 / 136; re-read it at lock in case a newer run is committed).

**Status: capturable locally.** `ninety-e2e --plant` shows the rejection in the viewer's agent
trace, and the viewer switches analyst and casual. Two caveats: offline, the Analyst is a
deterministic stand-in and the Judge does not run (code checks only), so for the Foundry agents use
`--replay` with a recording; and the events are the hand-written stand-in, which the viewer names.
Not from the deployed app until the viewer is deployed.

### 4. Screen dark: audio description only (1:00 to 1:15)

**Picture.** Black. Only the spoken description plays, panned left or right to where the ball is.
A caption at the end: "Audio description for blind and low-vision fans."

**Voice (narrator, 15 words, then the description itself).** "For fans who can't see the screen,
the same verified facts, spoken as they happen."

**Needs.** The Describer (#129) with Azure AI Speech, stereo position and the speech fallback;
latency logged (`docs/eval/latency-cost.md`, planned) if a latency figure is voiced.

**Status: not yet.** Speech synthesis runs (`ninety/speech/tts.py`, used by `ninety-slice
--speak`); the Describer is in #129.

### 5. Graphics on the footage, player cam, two languages, a failure recovered (1:15 to 1:40)

**Picture.** Graphics drawn at the players they describe (pass arc, shot speed, lower third).
Switch to player cam on one player. Switch the language to Spanish. Then cut the model service on
screen: the code-written line airs in its place and the trace shows the fallback.

**Voice (43 words).** "Graphics sit on the footage, at the players they describe. Player cam
follows one player. Switch to Spanish. Now we cut the model service: the code-written line airs
instead, and the match never goes silent. Every number on screen was computed by code."

**Needs.** The viewer drawing cues at detected positions (on `main`); player tags and player cam
(planned); Spanish variants (#131); an injected failure with its fallback, from the failure table
(`docs/eval/failure-table.md`, planned); the template cues (on `main`).

**Status: partly capturable.** The viewer draws graphics on the footage locally (from the
stand-in events); player cam, Spanish and the failure table are not on `main`.

### 6. Results and the Microsoft stack (1:40 to 2:00)

**Picture.** A results card, each number with the file it comes from; the stack; the repo and
demo links.

**Voice (41 words).** "Player recall `[0.994]` on footage the model never saw. Every claim checked
before it airs. Built on Microsoft Foundry, Agent Framework, MCP and Azure AI Speech, deployed on
Azure Container Apps. Code computes every number; agents only explain. The Ninety Labs."

**Needs.** The final merged vision report (v2 today) and, if available, the
event-level scores and the ablation; the deployed demo link (M2).

**Status: capturable** as a card, with v2's numbers. Update the numbers and links at lock.

## Word count

Narration totals 214 words (32 + 37 + 46 + 15 + 43 + 41). Trim beat 3 first if a read-through
runs long.

## What has to land before recording (Oct 25)

| Shot | Blocking work | Where |
|---|---|---|
| 1 | events detected from pixels, scored; scoring panel | `ninety/vision`, `ninety/eval`, viewer |
| 2 | targeted round 1 with a before and after | Vision Auditor, Data agent, a vision report |
| 3 | the viewer deployed; Personalizer variants if shown | M2, #131 |
| 4 | Describer with speech | #129 |
| 5 | player cam, Spanish, failure table | #131, planned work |
| all | the viewer deployed, so shots come from the deployed app | M2 |

## Submission checklist: still missing

From [BRIEF.md](BRIEF.md#submission-checklist), as of Oct 19:

| Item | State |
|---|---|
| Public GitHub repo | done: the repo is public |
| Project page naming the Microsoft and Azure technologies | missing: not drafted (PLAN, Oct 26) |
| Demo video under 2 minutes, public YouTube or Vimeo URL, no third-party marks or music | missing: this script is a draft; recording Oct 25 to 26 |
| Working demo link, free to use, live until Nov 10 | missing: only the API (`/api/health`, and `/mcp` for Foundry) deploys from `main`; the viewer runs locally only, so there is nothing public to link |
| Built after Sep 29; dependencies used under their licences | on track: the first commit is Oct 13; licences recorded in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md); re-check at submission for any dependency added since |
| Submitted by Oct 27, 11:59 pm PT | pending: we submit by 12 pm PT |
