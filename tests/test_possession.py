"""The phone's possession layer (ninety/intel/possession.py) and its grader
(ninety/eval/possession_score.py): the rule from the video alone, the gate measured on validation
clips (docs/eval/possession-calibration.md), and the layer off while the gate is unset."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from ninety.eval import possession_score as score
from ninety.intel import possession as ps
from ninety.vision import track as tr

ROOT = Path(__file__).resolve().parents[1]
M1 = tr.read_observations(ROOT / "tests" / "fixtures" / "observations-seed900001.jsonl")
PHASES = ps.timeline(M1)


# --- the rule -----------------------------------------------------------------------------------

@pytest.mark.parametrize("x, team, third", [
    (80.0, "home", "final"), (80.0, "away", "own"),  # home attacks toward x = 105
    (20.0, "home", "own"), (20.0, "away", "final"),
    (52.5, "home", "middle"), (52.5, "away", "middle"),
])
def test_the_third_is_along_the_direction_the_team_attacks(x, team, third):
    assert ps.third_of(x, team)[0] == third


def test_a_ball_near_a_third_s_line_is_not_plainly_in_it():
    line = 2 * ps.THIRD_M  # 70 m along
    assert ps.third_of(line + ps.EDGE_M + 0.01, "home") == ("final", True)
    assert ps.third_of(line + ps.EDGE_M - 0.01, "home") == ("final", False)
    assert ps.third_of(line - ps.EDGE_M + 0.01, "home") == ("middle", False)


def test_one_phase_per_phone_frame_and_confidence_within_bounds():
    step = round(ps.STEP_S * tr.FPS)  # 5 frames
    assert len(PHASES) == (M1[-1]["frame"] - M1[0]["frame"]) // step + 1
    gaps = {round(b.t - a.t, 2) for a, b in zip(PHASES, PHASES[1:], strict=False)}
    assert gaps == {ps.STEP_S}
    assert all(0.0 <= p.confidence <= 1.0 for p in PHASES)
    assert all((p.team is None) == (p.third is None) for p in PHASES)
    assert all(p.confidence == 0.0 for p in PHASES if p.team is None)


def test_the_m1_clip_reads_as_its_play_goes():
    # Away passes deep in their own half, home win it and shoot (home attacks toward x = 105),
    # then away's keeper has it: the clip's play, read from the video alone.
    at = {p.t: p for p in PHASES}
    assert (at[68.0].team, at[68.0].third) == ("away", "own")
    assert (at[71.0].team, at[71.0].third) == ("home", "final")
    assert (at[74.0].team, at[74.0].third) == ("away", "own")


def test_confidence_falls_while_nobody_is_seen_with_the_ball():
    # After a spell ends the side is held, its confidence falling over HOLD_S, then let go.
    spells = [(p.t, p.team, p.confidence) for p in PHASES if p.team == "away" and 68.0 <= p.t <= 70.4]
    confidences = [c for _, _, c in spells]
    assert confidences == sorted(confidences, reverse=True) and confidences[0] > confidences[-1]


def test_the_side_is_let_go_after_hold_s(monkeypatch):
    monkeypatch.setattr(ps, "HOLD_S", 0.4)
    short = ps.timeline(M1)
    assert sum(p.team is not None for p in short) < sum(p.team is not None for p in PHASES)


# --- the gate -----------------------------------------------------------------------------------

SURE_PHASE = ps.Phase(71.0, "home", "final", True, 0.95)


@pytest.mark.parametrize("show, sure, attacking, phase, label, is_sure", [
    (None, None, True, SURE_PHASE, "unknown", False),  # no gate measured: nothing at all
    (0.96, None, True, SURE_PHASE, "unknown", False),  # below SHOW
    (0.5, None, True, SURE_PHASE, "possession", False),  # shown, never sure: "likely"
    (0.5, 0.96, True, SURE_PHASE, "possession", False),  # below SURE: "likely"
    (0.5, 0.9, True, SURE_PHASE, "attacking", True),  # its bar open, sure, plainly in the final third
    (0.5, 0.9, False, SURE_PHASE, "possession", True),  # its own bar closed: never "attacking"
    (0.5, 0.9, True, ps.Phase(71.0, "home", "final", False, 0.95), "possession", True),  # near the line
    (0.5, 0.9, True, ps.Phase(71.0, "home", "middle", True, 0.95), "possession", True),
    (0.5, 0.9, True, ps.Phase(71.0, None, None, False, 0.0), "unknown", False),
])
def test_what_the_phone_may_draw(show, sure, attacking, phase, label, is_sure):
    shown = ps.on_screen(phase, show, sure, attacking)
    assert shown["label"] == label and shown["sure"] is is_sure
    assert (shown["team"] is None) == (label == "unknown")


def test_while_the_gate_is_unset_the_layer_shows_nothing():
    # docs/eval/possession-calibration.json: no cut-off reached its target on validation clips.
    show, sure, attacking = ps.gates()
    assert (show, sure, attacking) == (None, None, False)
    assert {ps.on_screen(p, show, sure, attacking)["label"] for p in PHASES} == {"unknown"}


def test_the_committed_calibration_states_its_targets_and_its_evidence():
    body = json.loads(ps.CALIBRATION.read_text())
    assert (body["show_target"], body["sure_target"]) == (score.SHOW_TARGET, score.SURE_TARGET)
    assert (body["attacking_target"], body["evidence_lower"], body["min_clips"]) == (
        score.ATTACKING_TARGET, score.EVIDENCE_LOWER, score.MIN_CLIPS)
    assert all(c["team_agreement"] is None or c["team_agreement"] < score.SHOW_TARGET for c in body["curve"])
    assert len(body["observations_sha256"]) == 13 and len(body["commit"]) == 40
    assert ROOT.joinpath("docs/eval/possession-calibration.md").read_text() == score.calibration_md(body)


# --- the grader ---------------------------------------------------------------------------------

def sample(conf, team, truth_team, seed=1, spell=1, third="middle", truth_third="middle"):
    return {"seed": seed, "t": 0.0, "team": team, "third": third, "plainly": True, "confidence": conf,
            "truth": {"team": truth_team, "third": truth_third, "spell": spell}}


def spells(right: int, wrong: int, conf: float, clips: int = 3, first: int = 0) -> list[dict]:
    """One sample per possession spell (numbered from `first`), spread over `clips` clips."""
    out = []
    for i in range(right + wrong):
        truth = "home" if i < right else "away"
        out.append(sample(conf, "home", truth, seed=i % clips, spell=first + i))
    return out


def test_the_gate_is_the_lowest_cut_off_that_reaches_its_target_on_enough_evidence():
    # 30 spells at 0.3, all right; 10 more at 0.1, all wrong: from 0.1 up it is 75%, but over 40
    # spells its lower Wilson bound is 0.598, under 0.60; from 0.3 up it opens.
    assert score.lowest_cut(spells(30, 0, 0.3) + spells(0, 10, 0.1, first=100), 0.75) == 0.3
    # The lowest cut that opens, not just any: from 0.2 up is 30 of 39 (bound 0.617), and 0.3 too.
    assert score.lowest_cut(spells(30, 0, 0.3) + spells(0, 9, 0.2, first=100), 0.75) == 0.2


def test_a_bar_needs_the_evidence_floor_as_well_as_its_target():
    assert score.opens(spells(41, 0, 0.5), 0.75, score.team_right)
    assert not score.opens(spells(5, 0, 0.5), 0.75, score.team_right)  # 100%, but 5 spells
    assert not score.opens(spells(60, 0, 0.5, clips=2), 0.75, score.team_right)  # 2 clips
    assert not score.opens(spells(30, 10, 0.5), 0.75, score.team_right)  # 75% of 40: bound 0.598
    assert score.opens(spells(31, 10, 0.5), 0.75, score.team_right)  # 76% of 41
    assert score.lowest_cut(spells(5, 0, 0.5), 0.75) is None  # the preview's kind: right, too little
    # Many samples in few spells are few spells: one spell of 50 right samples does not open it.
    one = [sample(0.5, "home", "home", seed=s % 3, spell=0) for s in range(50)]
    assert not score.opens(one, 0.75, score.team_right)


def test_attacking_has_its_own_bar_on_its_own_samples():
    final = dict(third="final", truth_third="final")
    good = [sample(0.95, "home", "home", seed=i % 3, spell=i, **final) for i in range(41)]
    assert score.attacking_opens(good, 0.9)
    wrong_third = [sample(0.95, "home", "home", seed=i % 3, spell=i, third="final", truth_third="middle")
                   for i in range(41)]
    assert not score.attacking_opens(wrong_third, 0.9)  # the team right, the third not: closed
    assert not score.attacking_opens(good, None)  # never sure: never "attacking"
    middle = [sample(0.95, "home", "home", seed=i % 3, spell=i) for i in range(41)]
    assert score.attacking_rows(middle, 0.9) == []  # not in the final third: not its samples
    unsure = [sample(0.5, "home", "home", seed=i % 3, spell=i, **final) for i in range(41)]
    assert score.attacking_rows(unsure, 0.9) == []  # below SURE: never called "attacking"


def test_samples_count_only_where_the_truth_names_a_team():
    rows = [sample(0.5, "home", "home"), {**sample(0.5, "home", "home"), "truth": None}]
    assert score.drawn(rows, 0.0) == rows[:1]


def test_intervals_count_possession_spells_not_samples():
    # Ten right samples in one spell are one spell: the interval is as wide as one observation's.
    one_spell = [sample(0.5, "home", "home", spell=1) for _ in range(10)]
    m = score.measure(one_spell, score.team_right)
    assert (m["samples"], m["spells"]) == (10, 1)
    assert m["wilson_95_spells"] == score.wilson(1, 1)
    assert score.wilson(1, 1)[0] < 0.25 < score.wilson(10, 10)[0]


def test_the_third_counts_as_right_only_with_the_team():
    assert not score.third_right(sample(0.5, "away", "home", third="final", truth_third="final"))
    assert score.third_right(sample(0.5, "home", "home", third="final", truth_third="final"))


def test_the_truth_carries_the_possessor_forward_and_numbers_its_spells(tmp_path):
    frames = [{"frame": i, "t": round(i / 25, 2), "ball": {"x": 80.0, "y": 34.0}, "possessor": who}
              for i, who in enumerate([None] * 5 + ["h7"] + [None] * 4 + ["a3"] + [None] * 9)]
    path = tmp_path / "frames.jsonl"
    path.write_text("\n".join(json.dumps(f) for f in frames) + "\n")
    phases = [ps.Phase(round(i / 25, 2), None, None, False, 0.0) for i in range(0, 20, 5)]
    truth = score.truth_samples(path, phases)
    assert truth[0] is None  # nobody named yet
    assert [t["team"] for t in truth[1:]] == ["home", "away", "away"]
    assert [t["spell"] for t in truth[1:]] == [1, 2, 2]
    assert truth[1]["third"] == "final" and truth[2]["third"] == "own"  # x = 80 along each side


# --- the live path ------------------------------------------------------------------------------

def test_the_rule_reads_no_answer_key():
    # The live module imports only the vision pipeline: never the grader, the simulator or the
    # renderer, which write or read the ground truth (AGENTS.md).
    tree = ast.parse((ROOT / "ninety/intel/possession.py").read_text())
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not {m for m in imported if m and m.startswith(("ninety.eval", "ninety.sim", "ninety.render"))}
    assert "possessor" not in (ROOT / "ninety/intel/possession.py").read_text()
