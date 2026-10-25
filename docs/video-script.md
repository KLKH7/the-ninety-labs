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

Status of each shot was re-checked against `main` at `76e91265` (Oct 24; first written at `b4d9402`, Oct 19).
**Capturable** means it can be recorded from `main` today; **not yet** names what has to land first.
Beats 2 and 3 were reworded on Oct 24 so the voice says no more than its evidence file; each
beat's status says why.

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

**Status: not yet.** Events from pixels run on `main` (the M1 clip's events come from its video),
and pass F1 was measured once on the frozen test set (0.67, below the 0.70 target), but before
the camera fit's blur (#250) and band (#270); not re-measured on `main` (open #298 re-measures it).
The viewer has no scoring panel: nothing in `web/viewer` shows precision or recall. **Fallback:**
detector boxes against ground-truth boxes on a test clip, drawn by `ninety/eval/draw.py`, with the
broadcast detector's numbers on the look-freeze test set (ours-freeze: ball recall 0.884, player
recall 0.997, [finetune-v2freeze](eval/finetune-v2freeze/PLAN.md)). Say "players and ball", never
"events", in that case.

### 2. Targeted synthetic data raises recall (0:15 to 0:35)

**Picture.** A miss cluster (for example, balls mostly hidden in a crowded box), the Data agent's
render request, new renders of exactly that scene, then the before and after score on the same
frozen test set.

**Voice (47 words).** "Our match engine plays the football and writes the truth for every frame.
Where the detector fails, a Data agent orders more of exactly those scenes. More synthetic footage
lifts hidden-ball recall from 0.50 to 0.58; aiming it at the failures has not beaten random scenes
yet."

**Needs.** Targeted round 1 with its before and after on the frozen test set (PLAN, Oct 21); the
Vision Auditor's failure clusters; the Data agent and render job (on `main`). Numbers
`[from the round-1 vision report]`.

**Status: capturable.** Round 1 has a
result ([round1/RESULT.md](eval/round1/RESULT.md)): more synthetic data from our engine lifted
mostly hidden ball recall from 0.500 to about 0.58 and cut false positives from 125 to about 40,
but **targeting added nothing measurable**: the targeted model (0.573) and an untargeted control
(0.585) are within noise on 82 labels. The voice used to credit targeting
with the lift ("one round on hidden balls lifts recall"), a gain the control also got; it now
says both halves. 0.50 and 0.58 are the file's 0.500 and "about 0.58" (0.573 targeted, 0.585
control). Round 2 is pre-registered, not run: if it beats its control, the last clause changes.
[vision-report-v2](eval/vision-report-v2.md) is a matched-engine retrain, not a targeted round:
never voice it as one.

### 3. The fact-checker rejects a planted claim (0:35 to 1:00)

**Picture.** The agent trace in the viewer: the Analyst's draft with a planted wrong number, the
fact-checking agent's rejection with the event it cites, the rewrite, the accepted graphic. Then
the same moment as the analyst sees it (number and evidence) and as the casual fan sees it (one
line).

**Voice (48 words).** "An Analyst agent drafts a claim. We plant a wrong number. The fact-checking
agent rejects it, cites the event, and sends it back. The rewrite passes. In testing, none of 136
planted false claims reached the screen. The analyst gets the evidence; the casual fan gets one line."

**Needs.** `ninety-e2e <clip> --out <bundle> --plant` opened in the viewer, or
`ninety-slice --replay replays/slice-minute2-plant.json` for the Foundry recording (both on `main`);
per-persona variants (#131) if more than the template
cues' analyst and casual wording is shown. Number from [fact-checker.md](eval/fact-checker.md)
(136 / 136; re-read it at lock in case a newer run is committed).

**Why "none reached the screen", not "caught all 136":** of the 136 kept off air, 9 were held by a
Judge service error, not judged (127 of 127 caught where a check decided), so "caught" overstates
the file. The run used `ninety-judge:1`; the Judge is now version 4 and the report is listed as
stale (`ninety/agents/evidence.py`). Re-read the file at lock in case the re-run on the current
Judge is committed.

**Status: capturable locally.** `ninety-e2e --plant` shows the rejection in the viewer's agent
trace, and the viewer switches analyst and casual. Offline the writers are stand-ins and the Judge
does not run (code checks only); for the Foundry agents use
`ninety-workflow --replay replays/workflow-minute2-plant.json` (the multi-agent graph, recorded live)
or `ninety-slice --replay`. The M1 clip's events come from its video. The viewer ships in the image
every green `main` deploys (`Dockerfile`), but its Replay bundle is the M1 clip built at `0f101db`
(Oct 22), so a planted-claim shot needs a local bundle.

### 4. Screen dark: audio description only (1:00 to 1:15)

**Picture.** Black. Only the spoken description plays, panned left or right to where the ball is.
A caption at the end: "Audio description for blind and low-vision fans."

**Voice (narrator, 15 words, then the description itself).** "For fans who can't see the screen,
the same verified facts, spoken as they happen."

**Needs.** The Describer with Azure AI Speech, stereo position and the speech fallback (#129,
merged); a latency figure, if one is voiced, from
[speech-latency.md](eval/speech-latency.md) (0.54 s p50, 0.85 s p95 a line, pre-generated).

**Status: capturable locally.** `ninety-e2e --voice-audio` pre-generates every description line in
the pinned voice (#279). The deployed Replay bundle predates it and carries no audio, and the phone
reads aloud in the device's own voice. The Describer's lines on the M1 clip: 2 of its 4 confident
events get a line, and only 1 of the 3 real ones ([describe.md](eval/describe.md)); pick a moment
the line describes correctly.

### 5. Graphics on the footage, player cam, two languages, a failure recovered (1:15 to 1:40)

**Picture.** Graphics drawn at the players they describe (pass arc, shot speed, lower third).
Switch to player cam on one player. Switch the language to Spanish. Then cut the model service on
screen: the code-written line airs in its place and the trace shows the fallback.

**Voice (43 words).** "Graphics sit on the footage, at the players they describe. Player cam
follows one player. Switch to Spanish. Now we cut the model service: the code-written line airs
instead, and the match never goes silent. Every number on screen was computed by code."

**Needs.** The viewer drawing cues at detected positions (on `main`); player tags and player cam
(planned); Spanish variants from the Personalizer (on `main`, off in `ninety-e2e`); an injected
failure with its fallback ([failure-table.md](eval/failure-table.md): 4 of 4 recovered offline, with
stand-in models); the template cues (on `main`).

**Status: partly capturable.** The viewer draws graphics on the footage from the M1 clip's detected
events. Not capturable: player cam (planned), and Spanish on screen (the Personalizer is not in
`ninety-e2e` or the viewer). The failure is capturable only as the failure table or a test run,
not cut live in the viewer.

### 6. Results and the Microsoft stack (1:40 to 2:00)

**Picture.** A results card, each number with the file it comes from; the stack; the repo and
demo links.

**Voice (41 words).** "Player recall `[0.997]` on footage the model never saw. Every claim checked
before it airs. Built on Microsoft Foundry, Agent Framework, MCP and Azure AI Speech, deployed on
Azure Container Apps. Code computes every number; agents only explain. The Ninety Labs."

**Needs.** The final merged vision report (ours-freeze today, [finetune-v2freeze](eval/finetune-v2freeze/PLAN.md):
player recall 0.997 on 7,500 test frames) and, if shown, the agent ablation
([ablation-agents.md](eval/ablation-agents.md): false claims on air, one agent 7 of 10, the graph
1 of 24); the deployed demo link (M2).

**Status: capturable** as a card. Update the numbers and links at lock.

## Word count

Narration totals 226 words (32 + 47 + 48 + 15 + 43 + 41), 11 over the 215 budget since beats 2
and 3 were reworded to match their evidence. Trim beat 3 first if a read-through runs long, but
keep both halves of beat 2's last sentence.

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

From [BRIEF.md](BRIEF.md#submission-checklist), as of Oct 24 (`76e91265`):

| Item | State |
|---|---|
| Public GitHub repo | done: the repo is public |
| Project page naming the Microsoft and Azure technologies | drafted: `web/site/index.html` (its claims are being brought up to date in open #317) |
| Demo video under 2 minutes, public YouTube or Vimeo URL, no third-party marks or music | missing: this script is a draft; recording Oct 25 to 26 |
| Working demo link, free to use, live until Nov 10 | in progress: every green `main` deploys one image with the API, the viewer, the phone at `/phone/` and the M1 clip's Replay bundle (`Dockerfile`, `deploy.yml`); neither the README nor the project page gives the public link yet, and the demo match (seed 8080) is not rendered |
| Built after Sep 29; dependencies used under their licences | on track: the first commit is Oct 13; licences recorded in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md); re-check at submission for any dependency added since |
| Submitted by Oct 27, 11:59 pm PT | pending: we submit by 12 pm PT |
