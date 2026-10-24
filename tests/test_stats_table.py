"""The phone's Stats tab rows: grouped, "so far" per five minutes, from the same tool summaries."""

import json
from pathlib import Path

from ninety.intel.match_insights import MatchInsights
from ninety.intel.stats_table import stats_table

STANDIN = Path(__file__).resolve().parents[1] / "docs" / "eval" / "standin-insights-seed8076.json"


def test_rows_are_grouped_and_so_far():
    mi = MatchInsights.from_dict(json.loads(STANDIN.read_text()))
    table = stats_table(mi)
    groups = {r["group"] for r in table["rows"]}
    assert groups == {"Attack", "Passing", "Pressing", "Shape", "Physical"}
    for r in table["rows"]:
        ends = [s["minute_to"] for s in r["series"]]
        assert ends == sorted(ends) and ends[-1] == mi.minutes
        if r["unit"] in ("turnovers", "regains", "overloads", "one-twos", "counters"):  # counts only grow
            for team in ("home", "away"):
                vals = [s[team] for s in r["series"] if s[team] is not None]
                assert vals == sorted(vals), (r["key"], team)


def test_a_row_agrees_with_the_tool_the_companion_reads():
    mi = MatchInsights.from_dict(json.loads(STANDIN.read_text()))
    row = next(r for r in stats_table(mi)["rows"] if r["key"] == "regains_within_5s")
    last = row["series"][-1]
    summary = {s["team"]: s["value"] for s in mi.counter_press(1, mi.minutes)["summary"]}
    assert (last["home"], last["away"]) == (summary["home"], summary["away"])
