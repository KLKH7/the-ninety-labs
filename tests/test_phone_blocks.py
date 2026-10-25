"""The Stats block's halves and pass network, as the phone reads them (insight_stats)."""

import json

from ninety.eval.companion_tools import STANDIN
from ninety.intel.match_insights import MatchInsights
from ninety.intel.stats_table import pass_network, stats_table


def standin(minutes=None):
    body = json.loads(STANDIN.read_text())
    if minutes:
        body["minutes"] = minutes
    return MatchInsights.from_dict(body)


def test_the_halves_hold_the_same_rows_over_each_half():
    mi = standin()
    st = stats_table(mi)
    first = st["halves"]["first"]
    assert (first["minute_from"], first["minute_to"]) == (1, mi.minutes) and "second" not in st["halves"]
    assert [r["key"] for r in first["rows"]] == [r["key"] for r in st["rows"]]
    # Over the whole of the first half, a row's value is its "so far" at the half's end.
    last = {r["key"]: r["series"][-1] for r in st["rows"]}
    for r in first["rows"]:
        assert (r["home"], r["away"]) == (last[r["key"]]["home"], last[r["key"]]["away"]), r["key"]


def test_the_second_half_starts_at_minute_46():
    st = stats_table(standin(minutes=60))
    assert (st["halves"]["second"]["minute_from"], st["halves"]["second"]["minute_to"]) == (46, 60)


def test_the_pass_network_is_named_players_at_their_average_place():
    mi = standin()
    net = pass_network(mi, 1, mi.minutes)
    names = {w["name"] for w in mi.people.values() if w.get("name")}
    for team in ("home", "away"):
        side = net[team]
        assert side["named_passes_only"]
        ids = {n["id"] for n in side["nodes"]}
        assert ids <= names and all(0 <= n["x"] <= 105 and 0 <= n["y"] <= 68 for n in side["nodes"])
        assert all(link["a"] in ids and link["b"] in ids and link["n"] >= 1 for link in side["links"])


def test_a_halfs_row_counts_only_its_own_minutes():
    body = json.loads(STANDIN.read_text())
    body["minutes"] = 90
    body["facts"]["counter"] = [
        {"id": f"counter:{m}", "kind": "counter", "team": "home", "club": "London Athletic", "minute": m,
         "t": 60.0 * m, "value": 5.0, "unit": "s", "confident": True}
        for m in (10, 30, 50)
    ]
    st = stats_table(MatchInsights.from_dict(body))
    row = {h: next(r for r in st["halves"][h]["rows"] if r["key"] == "counters") for h in ("first", "second")}
    assert (row["first"]["home"], row["second"]["home"]) == (2, 1)
