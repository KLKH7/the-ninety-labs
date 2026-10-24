# Read-aloud: latency and cost in the pinned voice

Measured Oct 23, 2026 against `ninety-labs-speech` (North Central US, F0) in
en-GB-OllieMultilingualNeural (ninety/speech/voice.py, lesson 232), MP3 at 24 kHz / 48 kbit/s.
Raw numbers: [speech-latency.json](speech-latency.json). To reproduce (a live Azure call, a few
cents at most):

    NINETY_SPEECH_RESOURCE_ID=$(az cognitiveservices account show -n ninety-labs-speech -g ninety-labs --query id -o tsv) \
      uv run python -m ninety.speech.measure --bundle runs/replay --out docs/eval/speech-latency.json

Requests are spaced 3.1 s apart, so F0's limit of 20 a minute never makes one wait, and no number
includes a 429 retry.

## Latency

| Path | What is timed | n | p50 | p95 |
|---|---|---|---|---|
| Build time (`ninety-e2e --voice-audio`) | one Speech request per line, 20 lines shaped like the phone's (`measure.LINES`) | 20 | 0.54 s | 0.85 s |
| Build time, the Replay bundle (seed900001) | its 2 audio description lines | 2 | 0.64 s | n too small for a p95 |
| Live (`POST /api/live/speak`, in process) | request to audio, after sign-in, for 9 answer-shaped texts (`measure.ANSWERS`) | 9 | 0.44 s | 0.76 s (n = 9: this is the maximum) |
| Live, first request | the same, including the credential's first token | 1 | 2.35 s | |

A fan never waits on build time: those lines ship in the bundle and play with no request at all.
On the Live path, a spoken answer starts about half a second after its text appears. The route
measured here runs on this laptop, not in Azure, so the Container App's numbers still need a run
after deploy. The voice samples chose Ollie partly because it is fast: the two HD voices took
2.2 to 2.6 s a line (`~/ninety-notes/voice-samples/results.json`).

## Cost

Azure AI Speech S1 neural text to speech is $15 per million characters (Azure Retail Prices API,
"S1 Neural Text To Speech Characters", northcentralus, read 2026-10-23). Our resource is F0, whose
first 0.5 M characters a month are free.

| What | Characters | At S1 |
|---|---|---|
| The Replay bundle as it is (2 lines) | 112 | $0.002 |
| The 20 measured lines | 1,219 | $0.018 |
| A full 90-minute match, estimated | about 68,000 | about $1.02 |
| Live: a day at the route's cap (`speak.DAY_CHARS`) | 50,000 | $0.75 |

The full-match estimate is an upper bound, not a measurement. It assumes the Replay clip's rate of
2 description lines in 10 s (12 a minute) holds for all 90 minutes, at that clip's 56 characters a
line (about 60,000), plus at most 30 cards (the Scout's one per three minutes), each said three
ways (spoken, "New insight: " and spoken, its Why? answer) at about 250 characters (about 7,500).
A rebuilt bundle pays only for lines it has not said before (the cache in `runs/speech-cache`).

Size: a line is about 26 KB of MP3 (514,944 bytes for the 20), so a full match at that rate would
add about 30 MB to the bundle. The demo's condensed match is much shorter.
