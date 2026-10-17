"""The R7 protocol's statistic and verdict (docs/EVALUATION.md), on hand-made drops."""

import math
import re
from pathlib import Path

from ninety.sim import late_drop
from ninety.sim.late_drop import BAND, SEEDS, summarise, verdict

ROOT = Path(__file__).resolve().parents[1]


def test_the_protocol_is_the_one_written_down():
    text = (ROOT / "docs/EVALUATION.md").read_text()
    m = re.search(r"(\d+) full matches, seeds (\d+) to (\d+), 90 minutes", text)
    assert m, "EVALUATION.md must state the R7 seeds"
    n, first, last = map(int, m.groups())
    assert len(SEEDS) == n >= 30
    assert SEEDS == tuple(range(first, last + 1))
    assert late_drop.MINUTES == 90
    assert BAND == (0.20, 0.45) and "20 to 45%" in text


def test_summary_by_hand():
    drops = [0.1, 0.2, 0.3, 0.4]  # mean 0.25, sample SD sqrt(0.05 / 3)
    s = summarise(drops)
    sd = math.sqrt(0.05 / 3)
    assert math.isclose(s["mean"], 0.25) and math.isclose(s["sd"], sd)
    assert math.isclose(s["hi"] - s["mean"], 1.96 * sd / 2)
    assert (s["min"], s["max"]) == (0.1, 0.4)


def test_thirty_matches_use_students_t():
    drops = [0.3 + 0.01 * (i % 5 - 2) for i in range(30)]
    s = summarise(drops)
    assert math.isclose(s["hi"] - s["mean"], 2.045 * s["sd"] / math.sqrt(30))


def test_verdict_reads_the_mean_against_the_band():
    firm = {"mean": 0.30, "lo": 0.27, "hi": 0.33}
    assert verdict(firm) == "inside the published band"
    assert verdict({"mean": 0.46, "lo": 0.43, "hi": 0.49}) == "outside the published band"
    assert verdict({"mean": 0.19, "lo": 0.16, "hi": 0.22}) == "outside the published band"
    edge = verdict({"mean": 0.21, "lo": 0.18, "hi": 0.24})
    assert edge.startswith("inside") and "crosses an edge" in edge
