"""Merge reviewer JSON into canonical defect types, with counts per 90 min and examples.

usage: python aggregate.py  (reads runs/sweep/reviews/*.json, writes runs/sweep/agg.json)
"""

import collections
import glob
import json
import re

# reviewer slug -> canonical type. Order of CANON is only for readability.
CANON = {
    "own_box_recycling": [
        "own_box_recycling", "sterile_possession", "sterile_recycling", "sideways_recycling",
        "team_collapses_to_own_box", "midfield_collapse_into_backline", "defence_collapsed_into_box",
        "retreat_in_possession", "team_retreats_in_possession", "own_throw_retreat", "backward_from_box",
        "no_progress_passing", "no_final_third_entry", "no_attacking_play", "no_attacking_threat",
        "ping_pong_passing", "ping_pong_passes", "sterile_pingpong", "long_ball_pingpong", "no_shots",
    ],
    "no_press_frozen_block": [
        "no_press", "no_pressing", "no_press_static_block", "static_defence_no_press",
        "frozen_defensive_block", "passive_block", "passive_no_press", "static_no_press", "frozen_block",
        "static_defensive_block", "static_defending_block", "block_not_shifting",
    ],
    "dead_ball_wait": [
        "long_dead_ball_wait", "dead_ball_wait", "long_deadball_wait", "long_dead_ball", "slow_restart",
        "throw_in_too_long", "dead_ball_share", "ball_in_play_low", "ball_dead_most_of_match",
        "restart_not_kicked", "restart_never_taken", "free_kick_no_taker",
    ],
    "restart_ball_teleport": [
        "ball_float_teleport", "restart_teleport", "restart_ball_teleport", "ball_rolls_after_whistle",
        "dead_ball_rolls_on", "dead_ball_rolls_away", "throw_in_restart_offset", "penalty_ball_wrong_spot",
        "foul_ball_launched", "keeper_fetches_ball", "keeper_chases_out_ball",
    ],
    "kickoff_teleport": ["kickoff_teleport", "instant_restart_teleport", "teleport_reset"],
    "overlap_stacked": ["overlap_walkthrough", "teammates_stacked"],
    "glued_marking": ["glued_pair", "striker_shadows_striker", "marking_wrong_man", "idle_ball_minder",
                      "marking_keeper_dead_ball"],
    "set_piece_encroachment": [
        "set_piece_encroachment", "setpiece_encroachment", "free_kick_encroachment", "fk_encroachment",
        "encroachment", "restart_encroachment", "goal_kick_encroachment", "goal_kick_opponents_in_box",
        "wall_too_close", "throw_in_encroachment", "set_piece_illegal_positions", "restart_law_violation",
    ],
    "restart_shape_wrong": [
        "restart_shape_tracks_dead_ball", "whole_team_out_of_position", "restart_shape_unreal",
        "restart_shape_wrong", "set_piece_shape", "set_piece_shape_absurd", "set_piece_shape_unreal",
        "set_piece_shape_wrong", "set_piece_nonsense", "corner_no_attackers", "set_piece_no_attackers",
        "pointless_wall", "wall_far_from_goal", "no_defensive_wall", "wrong_spot_setup",
        "attackers_loiter_in_box", "loiter_in_box", "set_piece_wasted", "wrong_taker", "restart_dribbled",
    ],
    "backward_pass_to_own_goal": [
        "absurd_backward_pass", "absurd_backward_pass_out", "absurd_backpass", "absurd_back_pass",
        "absurd_backpass_out", "pass_toward_own_goal", "pass_toward_own_goal_line", "pass_out_own_goal_line",
        "backpass_to_own_corner", "keeper_kicks_over_own_byline", "keeper_pass_out_own_goal_line",
    ],
    "pass_out_unpressured": [
        "pass_out_unpressured", "pass_out_of_play", "pass_into_touch", "overhit_pass", "pass_overhit_out",
        "overhit_pass_out", "pass_out_overhit", "short_pass_rolls_out", "pass_wildly_off_target",
        "aimless_long_ball", "aimless_hoof", "hoof_to_nobody", "pass_to_nobody", "pass_out_pressured",
        "touchline_bias", "dribble_out_of_play", "throw_in_too_hard", "impossible_throw_in",
    ],
    "gift_pass_to_opponent": [
        "keeper_gift", "own_box_gift", "gift_pass_to_opponent", "keeper_pass_to_opponent",
        "keeper_pass_into_pressure", "pass_into_presser", "point_blank_blast", "turnover_pingpong",
    ],
    "shot_silly": [
        "shot_silly_range", "silly_range_shot", "long_range_shot", "shot_from_silly_range",
        "shot_wrong_direction", "tight_angle_goal",
    ],
    "keeper_behaviour": [
        "keeper_wanders", "keeper_wander", "keeper_wanders_with_ball", "keeper_leaves_goal",
        "keeper_dispossessed", "keeper_soft_goal", "keeper_slow_reaction", "keeper_out_of_area",
        "keeper_out_of_box", "keeper_out_of_position", "keeper_not_sweeping", "keeper_walks_back",
        "keeper_position", "keeper_no_save_attempt", "keeper_distribution_odd",
    ],
    "bunching": ["bunching"],
    "static_teammates": ["static_teammates", "drift_away"],
    "no_forward_runs": ["no_forward_runs"],
    "line_shape_broken": ["line_shape_broken", "team_stretched", "team_disconnected", "team_split",
                          "player_out_of_position"],
    "chaser_wrong_way": ["chaser_wrong_way"],
    "unchallenged_dribble": ["unchallenged_dribble", "aimless_dribble"],
    "teammate_steal": ["teammate_steal", "wrong_receiver"],
    "referee_advantage": ["late_whistle_no_advantage", "goal_wiped_by_late_foul"],
    "event_log": ["event_spam"],
    "_tool_artifact": ["clock_format"],
}
SLUG = {s: c for c, ss in CANON.items() for s in ss}


def canon(x):
    t = x.get("type", "")
    if t in SLUG:
        return SLUG[t]
    if t in ("absurd_pass_choice", "absurd_pass"):
        d = x.get("description", "").lower()
        if re.search(r"back|own goal|own corner|own box", d):
            return "backward_pass_to_own_goal"
        return "pass_out_unpressured"
    return t  # broadcast / unknown types keep their slug


def main():
    rows = []
    for f in sorted(glob.glob("runs/sweep/reviews/*.json")):
        for x in json.load(open(f)):
            x["canon"] = canon(x)
            x["file"] = f.split("/")[-1]
            rows.append(x)
    json.dump(rows, open("runs/sweep/agg.json", "w"), indent=1)
    tac_minutes = 30 * 10
    by = collections.defaultdict(list)
    for x in rows:
        by[(x["view"] if x.get("view") == "broadcast" else "tactical", x["canon"])].append(x)
    for (view, c), xs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        sev = sum(float(x.get("severity", 1)) for x in xs) / len(xs)
        seeds = len({x["seed"] for x in xs})
        per90 = len(xs) / tac_minutes * 90 if view == "tactical" else None
        rate = per90 and round(per90, 1)
        print(f"{view[:4]} {c:28s} n={len(xs):4d} seeds={seeds:2d} sev={sev:.2f} per90={rate}")
    unknown = sorted({x["type"] for x in rows if x["canon"] == x["type"] and x["type"] not in CANON})
    print("unmapped:", unknown)


if __name__ == "__main__":
    main()
