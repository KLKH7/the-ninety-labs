# Feed spec: the simulated player-ID feed

**Names come from a simulated tracking-provider ID feed; vision does not identify players.**
Real broadcasts do not read names off pixels: they license identity from an optical tracking
provider, which delivers a live feed of who stands where. We simulate that feed from the match
engine, including the imperfections a real one has, and say so wherever a name is shown
("Player ID feed"). Kian decided this on Oct 26 (AGENTS.md, hard rules; [lesson 269](LESSONS.md)).

- **Writer:** `ninety/sim/identity_feed.py` (`uv run python -m ninety.sim.identity_feed --run <ninety-sim dir> --home-code LON --away-code LIS --out identity_feed.jsonl`).
- **The one reader:** `ninety/intel/identity.py`, for identity and side only. No event, statistic,
  position, outcome or vision evaluation reads the feed (`tests/test_identity_feed.py`).
- **Seeded:** the same match and seed always give the same feed, swaps and dropouts included.
- Every property cites its source in [GROUNDING.md](GROUNDING.md) (rows ID1 to ID9) or is marked *design*.

## File

JSON lines in **delivery order** (not capture order: rows arrive with jitter, so a reader sorts
by the capture time `t`). Line 1 is the match metadata; then frame rows and correction rows.

### Metadata (line 1)

| Field | Meaning |
|---|---|
| `type` | `"metadata"` |
| `schema` | `"ninety-id-feed/2"` |
| `provider`, `fps` | who and how often: 25 Hz (ID1) |
| `pitch` | `{length: 105, width: 68, origin: "centre", units: "m"}` |
| `kickoff` | the fixture's kick-off, UTC (*design*: fictional) |
| `periods` | `[{period, start_t}]`, from the engine's half-time |
| `teams` | per side: club name and scorebug code |
| `players` | the team sheets: `{player_id, team, jersey, name, position}`; `player_id` is the provider's (club code and shirt, `LON09`), not the engine's |
| `latency_s`, `noise_m`, `feed_seed` | the delivery delay, the position error and the seed |

### Frame row (25 per second)

`{"type": "frame", "frame_id", "period", "game_clock", "t", "delivered", "players": [[player_id, team, jersey, x, y, confidence], ...]}`

- `t` is the capture time in match seconds (the picture's clock); `delivered` is when the row
  reaches a live consumer, `t` + `latency_s` + jitter (ID3).
- `x`, `y` are metres from the centre spot, `x` along the length toward the away goal, to the
  centimetre, with the provider's position error (ID2).
- `confidence` is 1, or 0 for a second after a player is picked up again following a dropout (ID5).
- A player the cameras lost (occluded) is missing from the row for a few frames (ID4).

### Correction row

`{"type": "id_correction", "t", "delivered", "player_ids": [a, b], "from_t", "to_t"}`: the
operator found that `a` and `b` were swapped from `from_t` until `to_t` (ID6 to ID8). The frames
already delivered are not re-sent; a consumer applies the correction to what it holds.

## What the feed never carries

No ball, no event, no velocity, no action, no score, no engine id. The reader refuses a file
with any other field (`identity.load`).

## How the live path uses it

1. Align each vision frame to the feed row with the same capture time (never by arrival order).
2. Apply every correction to the frames it covers; skip low-confidence entries.
3. Match the tactical camera's tracks to the feed's players (Hungarian per 10 s window, same
   side, within vision's 1.26 m measured error); a track takes the player it followed for most of
   its frames ([EVALUATION.md](EVALUATION.md#player-names-from-the-id-feed)).
4. Carry the name to the broadcast's tracks through the camera join only (lesson 259).
5. **Side:** an event whose actor is named takes that player's side from the feed
   (`team_source: "id_feed"`, confidence 1.0); every other event keeps vision's side and confidence.

Live, names lag the picture by `latency_s` (15 s): a consumer can name a track only once the
feed rows for its frames have arrived.
