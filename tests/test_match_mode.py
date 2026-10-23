"""Match mode (ninety/condensed.py, web/viewer/src/match.ts): a condensed match's chapters, its
scoreline from detected goals, each team's stats from the footage shown, and a "time skip" label
at each cut.

The browser half needs the built viewer and Playwright's Chromium, as tests/test_viewer.py.
"""

from __future__ import annotations

import functools
import json
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ninety import condensed, e2e
from ninety.agents.factcheck import MIN_CONFIDENCE
from ninety.intel.stats import calculate_facts
from tests.e2e_clip import H, W, write_clip
from tests.test_radar import browser  # noqa: F401  (the shared Chromium fixture)

FPS = 25
# 40 images of match frames 1500-1539 (60.0-61.56 s), a cut, then 35 of 1550-1584 (62.0-63.36 s).
# tests/e2e_clip.py's clip.json says it ends at 62.96 s, so ninety-e2e keeps events up to there.
SEGMENTS = [{"index": 0, "frame": 1500, "frames": 40}, {"index": 40, "frame": 1550, "frames": 35}]
META = {"fps": FPS, "t_start": 60.0, "frames": 75, "segments": SEGMENTS}


def event(eid, t, kind, team, outcome=None, confidence=0.9, **more):
    e = {"id": eid, "t": t, "frame": round(t * FPS), "type": kind, "team": team, "x": 60.0, "y": 34.0,
         "end_x": 100.0, "end_y": 34.0, "player": None, "outcome": outcome, "ball_speed_kmh": 60.0,
         "source": "vision", "confidence": confidence}
    if kind == "pass":
        e.update(receiver=None, intended=None, interceptor=None, deflected_by=None)
    return {**e, **more}


EVENTS = [
    event("v1", 60.4, "pass", "home", "success"),
    event("v2", 61.0, "shot", "home", "goal"),
    event("v3", 62.2, "pass", "away", "success"),
    event("v4", 62.5, "shot", "home", "goal", confidence=MIN_CONFIDENCE - 0.2),  # unsure: never counts
    event("v5", 62.8, "shot", "away", "on_target"),  # the clip's last frame is 62.96 s
]


# ---------------------------------------------------------------- match.json


def test_a_chapter_per_segment_named_from_its_most_telling_confident_event():
    body = condensed.build(META, EVENTS)
    ch = body["chapters"]
    assert [(c["index"], c["t"], c["t_end"]) for c in ch] == [(0, 60.0, 61.56), (40, 62.0, 63.36)]
    assert [(c["kind"], c["label"], c["event"]) for c in ch] == [
        ("goal", "Goal, home", "v2"),
        ("save", "Shot saved, away", "v5"),  # the unsure goal in it does not make it a goal
    ]


@pytest.mark.parametrize("events, kind", [
    ([], "build_up"),
    ([event("p", 60.5, "pass", "home", "success")], "build_up"),
    ([event("k", 60.1, "kickoff", "away"), event("p", 60.5, "pass", "away", "success")], "set_piece"),
    ([event("k", 60.1, "set_piece", "home"), event("s", 61.0, "shot", "home", "off_target")], "shot"),
    ([event("s", 60.5, "shot", "home", "off_target"), event("o", 61.0, "shot", "away", "on_target")], "save"),
    ([event("o", 60.5, "shot", "away", "on_target"), event("g", 61.2, "shot", "home", "goal")], "goal"),
])
def test_the_kinds_rank_goal_save_shot_set_piece_build_up(events, kind):
    assert condensed.build(META, events)["chapters"][0]["kind"] == kind


def test_the_scoreline_counts_only_confident_detected_goals():
    body = condensed.build(META, EVENTS)
    assert body["goals"] == [{"t": 61.0, "team": "home", "event": "v2"}]
    assert body["min_confidence"] == MIN_CONFIDENCE


def test_the_stats_are_the_agents_team_facts_over_the_confident_events_so_far():
    body = condensed.build(META, EVENTS)
    sure = [e for e in EVENTS if e["confidence"] >= MIN_CONFIDENCE]
    facts = {(f.metric, f.scope): f.value for f in calculate_facts(sure)}
    last = body["stats"][-1]
    for team in ("home", "away"):
        for metric in condensed.STATS:
            assert last[team][metric] == facts[(metric, f"team:{team}")], (team, metric)
    # Before anything happened, nothing; after the goal, one; never the unsure second goal.
    assert body["stats"][0]["home"]["goals"] == 0 and body["stats"][0]["t"] == 60.0
    assert [s["home"]["goals"] for s in body["stats"]] == sorted(s["home"]["goals"] for s in body["stats"])
    assert max(s["home"]["goals"] for s in body["stats"]) == 1
    assert [s["t"] for s in body["stats"]] == sorted(s["t"] for s in body["stats"])


def test_a_clip_without_segments_is_one_chapter():
    body = condensed.build({"fps": FPS, "t_start": 60.0, "frames": 75}, EVENTS)
    assert len(body["chapters"]) == 1 and body["chapters"][0]["t_end"] == pytest.approx(62.96)


# ---------------------------------------------------------------- in the browser


@pytest.fixture(scope="module")
def site(browser, tmp_path_factory):  # noqa: F811
    """dist/ with the cut clip in match mode at match/, the same with its events named a
    hand-written stand-in at standin/, and without match mode at plain/."""
    from tests.test_viewer import DIST

    root = tmp_path_factory.mktemp("match-site")
    page = browser.new_page(viewport={"width": W, "height": H})
    page.set_content('<body style="margin:0;background:#2e7d32"></body>')
    jpeg = page.screenshot(type="jpeg")
    page.close()
    clip, detections, _ = write_clip(tmp_path_factory.mktemp("clip"), jpeg)
    meta = json.loads((clip / "clip.json").read_text())
    (clip / "clip.json").write_text(json.dumps({**meta, "segments": SEGMENTS}))
    events = root / "detected-seed42.jsonl"
    events.write_text("".join(json.dumps(e) + "\n" for e in EVENTS))
    standin = root / "detected-standin-seed42.jsonl"
    shutil.copyfile(events, standin)
    www = root / "www"
    shutil.copytree(DIST, www)
    for out, path, match in (("match", events, True), ("standin", standin, True), ("plain", events, False)):
        args = [str(clip), "--out", str(www / out), "--detections", str(detections), "--frames",
                "--events-file", str(path)] + (["--match"] if match else [])
        worker = threading.Thread(target=e2e.main, args=(args,))
        worker.start()
        worker.join()
        assert (www / out / "match.json").exists() == match
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(www))
    handler.log_message = lambda *a: None
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


def open_viewer(browser, url):  # noqa: F811
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url)
    page.wait_for_selector("body[data-state=ready] #overlay[data-t]")
    return page, errors


def seek(page, image: float):
    """Pause and put the clip at the middle of image `image`; wait for a frame drawn there."""
    v = (image + 0.5) / FPS
    page.evaluate(f"""(() => {{ const s = document.querySelector('#scrub');
        s.step = 'any'; s.value = {v}; s.dispatchEvent(new Event('input')); }})()""")
    page.wait_for_function(f"Math.abs(document.querySelector('#scrub').value - {v}) < 0.001")
    page.wait_for_timeout(150)


def test_match_mode_shows_the_chapters_the_score_and_the_honest_line(browser, site):  # noqa: F811
    page, errors = open_viewer(browser, site + "?bundle=match/")
    assert page.get_attribute("body", "data-mode") == "match"
    chapters = page.locator("#chapters .chapter")
    assert chapters.count() == 2
    first = "Chapter 1 of 2: Goal, home, match clock 01:00 to 01:01"
    assert chapters.nth(0).get_attribute("aria-label") == first
    assert "Shot saved, away" in chapters.nth(1).inner_text()
    line = page.inner_text("#match-honest")
    assert line == ("Condensed match, replayed at real speed. "
                    "Every event and number was computed from the pixels by our pipeline.")
    seek(page, 5)  # 60.2 s: before the goal
    assert page.get_attribute("#match", "data-score") == "0-0"
    assert page.inner_text("#score") == "Home 0 – 0 Away"
    seek(page, 30)  # 61.22 s: after it
    assert page.get_attribute("#match", "data-score") == "1-0"
    seek(page, 66)  # 62.66 s: after the unsure second goal at 62.5, which never counts
    assert page.get_attribute("#match", "data-score") == "1-0"
    assert not errors


def test_a_stand_in_bundle_says_so_instead_of_claiming_the_pixels(browser, site):  # noqa: F811
    page, _ = open_viewer(browser, site + "?bundle=standin/")
    line = page.inner_text("#match-honest")
    assert "hand-written stand-in" in line and "computed from the pixels" not in line


def test_the_clock_jumps_at_the_cut_under_a_time_skip_label(browser, site):  # noqa: F811
    page, _ = open_viewer(browser, site + "?bundle=match/")
    seek(page, 39)
    assert not page.is_visible("#time-skip")
    assert page.inner_text("#clock") == "01:01"
    seek(page, 40)  # the first image after the cut: match frame 1550
    assert page.is_visible("#time-skip")
    assert page.inner_text("#time-skip") == "Time skip · 01:01 → 01:02"
    assert page.get_attribute("#match", "data-chapter") == "2"
    assert "Time skip to 01:02" in page.inner_text("#match-live")
    # The label is up for SKIP_LABEL_S (2.5 s) after the cut, longer than this clip's 1.4 s second
    # segment, so its end is asked of the function that decides it.
    up = page.evaluate(f"window.ninetyMatch.skipAt({(40 + 2.4 * FPS) / FPS})")
    assert up == {"from": 61.56, "to": 62.0}
    assert page.evaluate(f"window.ninetyMatch.skipAt({(40 + 2.6 * FPS) / FPS})") is None
    assert page.evaluate(f"window.ninetyMatch.skipAt({39.5 / FPS})") is None


def test_chapters_from_the_keyboard(browser, site):  # noqa: F811
    page, _ = open_viewer(browser, site + "?bundle=match/")
    seek(page, 10)
    page.locator("body").focus()
    page.keyboard.press("]")
    page.wait_for_function("document.querySelector('#match').dataset.chapter === '2'")
    assert page.evaluate("document.activeElement.dataset.n") == "2"  # focus follows to its button
    page.keyboard.press("[")  # less than a second in: to the previous chapter
    page.wait_for_function("document.querySelector('#match').dataset.chapter === '1'")
    seek(page, 60)
    page.locator("#chapters .chapter").nth(0).focus()
    page.keyboard.press("Enter")  # a chapter button seeks to its start
    page.wait_for_function("document.querySelector('#match').dataset.chapter === '1'")
    assert float(page.evaluate("document.querySelector('#scrub').value")) < 0.1


def test_the_stats_follow_the_clock(browser, site):  # noqa: F811
    page, _ = open_viewer(browser, site + "?bundle=match/")
    seek(page, 5)
    rows = page.locator("#stats-table tr")
    assert rows.nth(1).inner_text().split("\t") == ["Goals", "0", "0"]
    seek(page, 74)
    assert rows.nth(1).inner_text().split("\t") == ["Goals", "1", "0"]
    assert rows.nth(2).inner_text().split("\t") == ["Shots (on target)", "1 (1)", "1 (1)"]
    assert rows.nth(3).inner_text().split("\t") == ["Passes completed", "1 of 1", "1 of 1"]


def test_a_bundle_without_match_json_has_no_match_mode(browser, site):  # noqa: F811
    page, errors = open_viewer(browser, site + "?bundle=plain/")
    assert page.get_attribute("body", "data-mode") is None
    for hidden in ("#match", "#chapters", "#match-stats", "#time-skip"):
        assert not page.is_visible(hidden), hidden
    seek(page, 40)  # the cut, with no label: match mode is off
    assert not page.is_visible("#time-skip")
    assert not errors
