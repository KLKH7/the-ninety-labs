# "Most involved", as an order without a count: plan (pre-registered)

Written and committed before any truth for seed 8080 was read. At the time of writing, the only
things looked at were its file names and its metadata keys. It follows on from
[player-stats.md](player-stats.md). On seed 8324 the per-player involvement **count** missed its
bar (23% of players within it, 484 of 680 involvements found). Its **order** agreed with the
truth's top three 2.5 of 3 per club. That agreement was seen after looking, so 8324 is
development only. This plan tests the order alone, once, on a held-out match.

## The claim

For one club at match minute M, the top three of its players by involvement, in order: the
detected events (pass, shot, goal, possession change, out of play, set piece, kick-off) whose
track the Player ID feed names him on, as player, receiver or interceptor, up to M. **No count
is said.** The wording names its source: "Of the moves the video picked up, X has been most
involved for <club>, then Y and Z (names: Player ID feed)." Ties are broken by more detected
events overall and then by name, as `player_stats.rank` already does.

## The held-out clip

Seed 8080, the earlier demo match (`runs/demo-8080-hunt`, engine 65247ba3). Its live inputs are
`tracked.json`, `association.json`, `detected.jsonl`, `final-work/identity_feed.jsonl` and the
broadcast vision runs in `runs/demo-8080-hunt-work/vision`. Its truth is the same 90-minute run's
events (`~/ninety-notes/footage-hunt/seed8080-v2/events.jsonl`, roster in `meta.json`). The
clip-window truth folders are dangling links, and none are needed, since this grades events only.

## How it is graded

- **Truth involvement.** Each player's count of truth events of the same seven types, as player,
  receiver or interceptor, whose frame falls in a segment of the footage shown (`clip.json`
  segments, `[frame, frame + frames)`), up to minute M. Feed ids are mapped to engine ids by side
  and position, as identity_eval does.
- **Agreement.** The overlap of our top three with the truth's top three. When the truth's third
  place is tied, every player tied with it counts as being in the truth's top three.
- **Cases.** Both clubs, at M = 45 and M = 90: four cases.
- **Bar.** The mean overlap over the four cases is at least 2 of 3, and no case is below 1 of 3
  (*design*, the same 2-of-3 bar as the rankings in [player-stats-plan.md](player-stats-plan.md)).
- **Reported, not barred:** whether the leader is the truth's leader (or tied for it), per case.

If the bar is met, `rank:involvement_order` is set on in `ninety/intel/player_stats_calibration.json`
and `player_rank(club, "involvement", minute)` returns the order with no values. If it is missed,
the result is reported, the flag stays off, and nothing is retuned.

## Addendum, before any truth was read: the broadcast vision runs are gone

`runs/demo-8080-hunt-work/vision/*` link to pod outputs that are no longer on the machine, so
identity's step 6 (naming broadcast tracks directly from the feed) cannot run on 8080. The grade
uses the live path as it runs without `--broadcast-vision`: names cross the camera join only
(`identity.named_broadcast` with no broadcast frames). That names fewer events, so it is a harder
test of the order, not an easier one. Nothing else changes.
