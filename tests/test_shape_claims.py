"""The planted shape-claim evaluation (ninety/eval/shape_claims.py): its report is current, every
planted false claim is caught, no true one is stopped, and every claim on an unsure fact is held."""

import json

from ninety.eval import shape_claims


def test_the_committed_report_is_what_the_committed_facts_give():
    assert shape_claims.REPORT.read_text() == shape_claims.build()


def test_every_planted_false_claim_is_caught_and_every_true_one_airs():
    results = shape_claims.evaluate(json.loads(shape_claims.ROWS.read_text()))
    families = {r["family"] for r in results}
    assert {"true", "wrong number", "opposite direction", "other team", "no shape fact cited",
            "one player untracked"} <= families
    assert len([r for r in results if r["expect"] == "rejected"]) >= 100
    assert [r for r in results if r["got"] != r["expect"]] == []


def test_every_true_claim_s_guard_holds_on_its_fact():
    # Lesson 34: a true label is true by the fact's fields, checked here apart from the checker.
    data = json.loads(shape_claims.ROWS.read_text())
    for d in data.values():
        rows = {r["id"]: r for r in d["full"] if r["confident"]}
        for kind, text, (fact,) in shape_claims.true_claims(rows):
            r = rows[fact]
            assert str(r["value"]) in text or (r["change"] is not None and str(abs(r["change"])) in text) \
                or kind in ("high line", "deep block", "narrow", "compact")
            if kind == "line pushed up":
                assert r["change"] > 0
            if kind == "high line":
                assert r["value"] > 28


def test_the_facts_come_from_every_player_seen_and_the_thinned_copy_misses_one_a_team():
    data = json.loads(shape_claims.ROWS.read_text())
    for d in data.values():
        assert all(r["confident"] for r in d["full"])
        assert not any(r["confident"] for r in d["one_missing"])
        assert {r["tracked"] for r in d["one_missing"]} == {10}
