# "Most involved", as an order without a count: results

These are graded once, on held-out seed 8080 (`runs/demo-8080-hunt`), against
[player-involvement-rank-plan.md](player-involvement-rank-plan.md). The plan (3476d244) and its
addendum (5b3b67e2) were committed before any truth for 8080 was read. The run is at 5b3b67e2,
and the raw output is [player-involvement-rank.json](player-involvement-rank.json). Names cross
the camera join only, because 8080's broadcast vision runs are no longer on the machine (see the
addendum).

| Minute | Club | Our top three, in order | Truth's top three (ties at third included) | Overlap | Leader right |
|---|---|---|---|---|---|
| 45 | London (home) | Toulmore, Tendell, Guddon | Toulmore, Pouvick, Tendell | 2 | yes |
| 45 | Lisbon (away) | Memble, Hourrick, Vaindell | Memble, Hourrick, Rarrick, Korrow | 2 | yes |
| 90 | London (home) | Toulmore, Tendell, Guddon | Toulmore, Pouvick, Tendell | 2 | **no** |
| 90 | Lisbon (away) | Rarrick, Memble, Telby | Memble, Hourrick, Rarrick | 2 | yes |

**Mean overlap is 2.0 of 3, and no case is below 2.** The bar was a mean of at least 2 with no
case below 1, so it is **met, exactly at the line**. The leader is right in 3 of 4 cases (not
barred). `rank:involvement_order` is on.

## What a fan is told

`player_rank(club, "involvement", minute)`: "Of the moves the video picked up, X has been most
involved for <club>, then Y and Z (names: Player ID feed)." No count is given, because the count
missed its bar on 8324 (player-stats.md). This needs a club. Across both clubs, and for "best
player", the answer stays withheld.

## Limits

- One held-out match, four cases, and a pass exactly at the bar. In one of four cases the named
  leader is not the truth's leader. This is "two of the three most involved", not "the single
  most involved".
- Seed 8324 (2.5 of 3 at full time) was seen before this plan, so it is development, not
  evidence.
