"""Match mode (ninety/condensed.py, web/viewer/src/match.ts): a condensed match's chapters, its
scoreline from detected goals, each team's stats from the footage shown, and a "time skip" label
at each cut.

The browser half needs the built viewer and Playwright's Chromium, as tests/test_viewer.py.
"""

from __future__ import annotations

import functools
import json
import os
import re
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ninety import condensed, e2e, footage
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
         "source": "vision", "confidence": confidence, "team_confidence": 0.99}
    if kind == "pass":
        e.update(receiver=None, intended=None, interceptor=None, deflected_by=None)
    return {**e, **more}


EVENTS = [
    event("v1", 60.4, "pass", "home", "success"),
    event("v2", 61.0, "shot", "home", "goal", team_confidence=0.99),
    event("v3", 62.2, "pass", "away", "success"),
    event("v4", 62.5, "shot", "home", "goal", confidence=MIN_CONFIDENCE - 0.2),  # unsure: never counts
    event("v5", 62.8, "shot", "away", "on_target", team_confidence=0.99),  # the clip's last frame is 62.96 s
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


def test_a_goal_on_a_side_not_told_surely_counts_for_no_club():
    unsure = [event("g", 61.0, "shot", "home", "goal", team_confidence=0.3)]
    assert condensed.build(META, unsure)["goals"] == [{"t": 61.0, "team": None, "event": "g"}]


# Lesson 270: a goal is the detected `goal` event (GROUNDING I24); a shot that went in, just before
# it, is the same goal, and the goal event carries the side.
PAIR_AND_LONE = [
    event("s1", 60.6, "shot", "home", "goal", team_confidence=0.2),  # the strike: its side unsure
    event("g1", 61.0, "goal", "home", team_confidence=0.99, ball_speed_kmh=None),  # same goal, sure
    event("g2", 62.4, "goal", "away", team_confidence=0.99, ball_speed_kmh=None),  # its strike unseen
]


def test_a_goal_event_is_the_goal_merged_with_its_shot_and_a_goal_without_a_shot_still_counts():
    body = condensed.build(META, PAIR_AND_LONE)
    assert body["goals"] == [{"t": 61.0, "team": "home", "event": "g1"},
                             {"t": 62.4, "team": "away", "event": "g2"}]
    # Chapters (the scrubber's ticks) are named by the goal event, which carries the side.
    assert [(c["kind"], c["label"], c["event"]) for c in body["chapters"]] == [
        ("goal", "Goal, home", "g1"), ("goal", "Goal, away", "g2")]
    # The reel has each goal once: at its shot, or at the goal event when no strike was seen.
    moments = body["highlights"]["moments"]
    assert [(m["event"], m["kind"], m["team"], m["d_m"] is None) for m in moments] == [
        ("s1", "goal", "home", False), ("g2", "goal", "away", True)]
    assert body["stats"][-1]["home"]["goals"] == 1 and body["stats"][-1]["away"]["goals"] == 1


def test_a_chapter_names_no_club_its_side_was_not_told_surely():
    unsure = [event("g1", 61.0, "goal", "home", team_confidence=0.94),
              event("k1", 62.1, "kickoff", "away", team_confidence=0.5)]
    body = condensed.build(META, unsure)
    assert [c["label"] for c in body["chapters"]] == ["Goal", "Kick-off"]
    assert body["goals"] == [{"t": 61.0, "team": None, "event": "g1"}]


def change(cid, t, team, confidence=0.99):
    return {"id": cid, "t": t, "frame": round(t * FPS), "type": "score_change", "team": team,
            "score": {"home": 1, "away": 0}, "confidence": confidence}


def test_a_goal_its_score_change_confirms_takes_the_scorebug_s_side_and_names_the_club():
    weak = [event("g1", 61.0, "goal", "away", team_confidence=0.94)]  # the tracker's side: unsure
    body = condensed.build(META, weak, scorebug=[change("c1", 61.2, "home")])
    assert body["goals"] == [{"t": 61.0, "team": "home", "event": "g1"}]  # the changed digit's club
    assert body["chapters"][0]["label"] == "Goal, home"
    assert body["highlights"]["moments"][0]["team"] == "home"


@pytest.mark.parametrize("scorebug", [
    None,  # no scorebug read
    [change("c1", 63.0, "home")],  # a change too far from the goal (beyond the reconciler's 1 s)
    [change("c1", 61.2, "home", confidence=MIN_CONFIDENCE - 0.1)],  # a change under the gate
])
def test_a_goal_no_score_change_confirms_keeps_the_tracker_s_gate(scorebug):
    weak = [event("g1", 61.0, "goal", "away", team_confidence=0.94)]
    body = condensed.build(META, weak, scorebug=scorebug)
    assert body["goals"] == [{"t": 61.0, "team": None, "event": "g1"}]
    assert body["chapters"][0]["label"] == "Goal"


def test_a_shot_that_went_in_with_no_goal_event_is_still_a_goal():
    lone_shot = [event("s1", 60.6, "shot", "home", "goal", team_confidence=0.99),
                 event("p1", 61.0, "pass", "away", "success")]
    body = condensed.build(META, lone_shot)
    assert body["goals"] == [{"t": 60.6, "team": "home", "event": "s1"}]
    assert [m["event"] for m in body["highlights"]["moments"]] == ["s1"]


def test_the_scoreline_counts_only_confident_detected_goals():
    body = condensed.build(META, EVENTS)
    assert body["goals"] == [{"t": 61.0, "team": "home", "event": "v2"}]
    assert body["min_confidence"] == MIN_CONFIDENCE


def test_an_event_on_a_side_not_told_surely_is_in_no_club_s_stats():
    """UI inventory #7: Team Stats split by the tracker's side vote; an unsure side counts for no one."""
    unsure = [event("p", 60.5, "pass", "away", "success", team_confidence=0.3),
              event("s", 61.0, "shot", "away", "off_target", team_confidence=0.3)]
    last = condensed.build(META, unsure)["stats"][-1]
    assert last["away"] == last["home"] == dict.fromkeys(condensed.STATS, 0)


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


class RangeHandler(SimpleHTTPRequestHandler):
    """Static files with HTTP Range, as the deployed API serves the bundle (tests/test_api_site.py):
    a browser seeks a <video> only on a server that answers byte ranges."""

    def log_message(self, *args):
        pass

    def do_GET(self):  # noqa: N802
        m = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
        path = self.translate_path(self.path)
        if m is None or not os.path.isfile(path):
            return super().do_GET()
        size = os.path.getsize(path)
        start, end = int(m[1]), min(int(m[2]) if m[2] else size - 1, size - 1)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            self.wfile.write(f.read(end - start + 1))


def silent_wav(path, seconds: float, rate: int = 8000):
    import wave

    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * int(rate * seconds))


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
    runs = (("match", events, True, True), ("standin", standin, True, True), ("plain", events, False, True))
    if footage.can_encode():  # the same match as real web video (ninety/footage.py: video.mp4 + HLS)
        runs += (("video", events, True, False),)
    for out, path, match, frames in runs:
        args = [str(clip), "--out", str(www / out), "--detections", str(detections),
                "--events-file", str(path)] + (["--match"] if match else [])
        args += ["--frames"] if frames else []
        worker = threading.Thread(target=e2e.main, args=(args,))
        worker.start()
        worker.join()
        assert (www / out / "match.json").exists() == match
    # The same match with commentary (src/commentary.ts): two lines and a stadium bed, silent wavs.
    shutil.copytree(www / "match", www / "commentary")
    for name, seconds in (("c1.wav", 1.0), ("c2.wav", 0.6), ("stadium.wav", 4.0)):
        silent_wav(www / "commentary" / name, seconds)
    (www / "commentary" / "commentary.json").write_text(json.dumps({"format": 1, "voice": "test", "lines": [
        {"id": "c1", "t": 60.3, "t_end": 61.3, "text": "Crowmere break at pace",
         "audio": "c1.wav", "event": None},
        {"id": "c2", "t": 61.8, "t_end": 62.4, "text": "Saved", "audio": None, "event": None}]}))
    manifest = json.loads((www / "commentary" / "manifest.json").read_text())
    (www / "commentary" / "manifest.json").write_text(json.dumps({**manifest, "commentary": {"count": 2},
                                                                  "stadium": "stadium.wav"}))
    _hls_bundle(www, "hls")  # the same match as an HLS ladder, where ffmpeg is installed
    handler = functools.partial(RangeHandler, directory=str(www))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


def open_viewer(browser, url, silent=False):  # noqa: F811
    """`silent`: the bundle without its commentary and stadium bed (every ninety-e2e bundle writes
    commentary.json since #328), for the case of a match with no sound to offer."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    if silent:
        def no_sound(route):
            body = route.fetch().json()
            body.pop("commentary", None)
            body.pop("stadium", None)
            route.fulfill(json=body)

        ctx.route("**/manifest.json", no_sound)
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
    first = "Chapter 1 of 2: Goal · Crowmere, match clock 01:00 to 01:01"
    assert chapters.nth(0).get_attribute("aria-label") == first
    assert "Shot saved · Dunhollow" in chapters.nth(1).inner_text()
    line = page.inner_text("#match-honest")
    assert line == ("Condensed match, replayed at real speed. "
                    "Every event and number was computed from the pixels by our pipeline.")
    # The title row names the clubs, never a score counted from detected goals (Kian, Oct 25).
    seek(page, 30)  # 61.22 s: after the detected goal
    assert page.inner_text("#score") == "Crowmere v Dunhollow"
    # scoreAt's rule still holds where code uses it: a goal counts only when confident.
    score = lambda t: page.evaluate(f"window.ninetyMatch.scoreAt({t})")  # noqa: E731
    assert score(60.2) == {"home": 0, "away": 0} and score(61.22) == {"home": 1, "away": 0}
    assert score(62.66) == {"home": 1, "away": 0}  # the unsure second goal at 62.5 never counts
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
    page, _ = open_viewer(browser, site + "?bundle=match/&dev=1")  # the chapter bar's buttons
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
    page, _ = open_viewer(browser, site + "?bundle=match/&dev=1")  # on the big screen they are on the phone
    seek(page, 5)
    rows = page.locator("#stats-table tr")
    assert rows.nth(1).inner_text().split("\t") == ["Shots (on target)", "0 (0)", "0 (0)"]
    seek(page, 74)
    assert rows.nth(1).inner_text().split("\t") == ["Shots (on target)", "1 (1)", "1 (1)"]
    assert rows.nth(2).inner_text().split("\t") == ["Passes completed", "1 of 1", "1 of 1"]
    assert "Goals" not in page.inner_text("#stats-table")  # no goal count: the scorebug carries it


def test_a_bundle_without_match_json_has_no_match_mode(browser, site):  # noqa: F811
    page, errors = open_viewer(browser, site + "?bundle=plain/")
    assert page.get_attribute("body", "data-mode") is None
    for hidden in ("#match", "#chapters", "#match-stats", "#time-skip"):
        assert not page.is_visible(hidden), hidden
    seek(page, 40)  # the cut, with no label: match mode is off
    assert not page.is_visible("#time-skip")
    assert not errors


# ---------------------------------------------------------------- the big screen (R5, Oct 23)

PANELS = ("#radar-section", "#match-stats", "#trace", "#pipeline", "#show-boxes", "#show-radar")


def test_the_pairing_card_is_up_at_kick_off_then_only_behind_the_qr_button(browser, site):  # noqa: F811
    page, errors = open_viewer(browser, site + "?bundle=match/")
    def at(v, **s):
        st = json.dumps({"open": False, "closed": False, **s})
        return page.evaluate(f"window.ninetyMatch.pairCardAt({v}, {st})")

    assert at(0.0) == "up" and at(19.9) == "up"  # PAIR_CARD_S: 20 s from kick-off
    assert at(20.1) == "hidden" and at(600.0) == "hidden"  # never again on its own, not at a chapter
    assert at(5.0, closed=True) == "hidden"  # a fan closed it
    assert at(600.0, open=True) == "up"  # the QR button
    # Kian, Oct 25 (option A): never docked, whatever the page's address says.
    page.goto(site + "?bundle=match/&qr=dock")
    page.wait_for_selector("body[data-state=ready] #overlay[data-t]")
    assert at(600.0) == "hidden"
    assert page.locator(".pair-card[data-at=docked]").count() == 0
    assert not errors
    page.context.close()


def test_the_big_screen_is_the_picture_alone_with_a_player_s_controls(browser, site):  # noqa: F811
    page, errors = open_viewer(browser, site + "?bundle=match/", silent=True)
    assert page.get_attribute("body", "data-screen") == "big"
    for hidden in PANELS:  # on the phone instead
        assert not page.is_visible(hidden), hidden
    # No site header, persona tabs, motion switch, title row or chapter bar: the picture alone.
    for hidden in (".bar", "#persona", "#reduce-motion", ".chapter-bar", ".keys"):
        assert not page.is_visible(hidden), hidden
    stage = page.locator("#stage").bounding_box()
    # Full-bleed beside the companion (src/dock.ts, open by default): it fills what is left one way.
    assert page.locator("#companion").bounding_box()["width"] == 380
    assert stage["width"] == 1280 - 380 or stage["height"] == 900
    # The score is the broadcast's own scorebug; our title row is only for a screen reader.
    assert page.locator("#match").bounding_box()["width"] <= 1
    # The controls are on the picture: play, the clock and the scrubber with the chapters on it.
    for shown in ("#hud", "#play", "#scrub", "#clock", "#hud-qr", "#hud-full"):
        assert page.is_visible(shown), shown
    assert page.locator("#ticks i").count() == 1  # the second chapter's start (the first is 0)
    assert page.locator("#ticks i.goal").count() == 0  # chapter 2 is a save; chapter 1 holds the goal
    # No sound track and no stadium file: the bed is the placeholder murmur, so the control is live.
    assert page.is_visible("#hud-volume")
    assert not page.is_visible("#phone-panel") and page.locator("#pair-card").count() == 1
    assert not page.is_checked("#show-boxes")  # the detector's boxes are not broadcast graphics
    page.keyboard.press("d")
    assert not page.is_checked("#show-boxes")
    page.keyboard.press("2")  # personas are the phone's: the keys do nothing here
    assert page.get_attribute("body", "data-persona") == "casual"
    assert not errors
    page.context.close()  # an open page keeps drawing; the audio tests time real playback


def test_the_big_screen_controls_fade_while_it_plays_and_stay_while_paused(browser, site):  # noqa: F811
    page, errors = open_viewer(browser, site + "?bundle=match/")
    page.mouse.move(400, 300)
    assert page.get_attribute("body", "data-ui") == "on"
    page.wait_for_timeout(3300)  # paused: the controls stay
    assert page.get_attribute("body", "data-ui") == "on"
    page.locator("body").focus()
    page.keyboard.press("Space")
    page.wait_for_function("document.querySelector('#play').dataset.paused === 'false'")
    assert page.get_attribute("#play", "aria-label") == "Pause"
    page.wait_for_function("document.body.dataset.ui === 'off'", timeout=6000)  # faded while playing
    page.mouse.move(420, 320)
    assert page.get_attribute("body", "data-ui") == "on"  # back on a move
    assert not errors
    page.context.close()


def test_the_qr_button_opens_and_closes_the_pairing_card(browser, site):  # noqa: F811
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    ctx.route(re.compile(r".*/api/pair$"), lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({"code": "K7MP3Q", "expires_in": 7200})))
    ctx.route_web_socket(re.compile(r".*/api/pair/.*"), lambda ws: None)
    # The card is for a screen without the companion beside it (src/dock.ts): a viewer who closed it.
    ctx.add_init_script("localStorage.setItem('ninety.dock', 'closed')")
    page = ctx.new_page()
    page.goto(site + "?bundle=match/")
    page.wait_for_selector("#pair-card:not([hidden])")  # up at kick-off
    page.keyboard.press("Escape")
    page.wait_for_selector("#pair-card[hidden]", state="attached")
    page.click("#hud-qr")
    page.wait_for_selector("#pair-card:not([hidden])")
    assert page.get_attribute("#hud-qr", "aria-expanded") == "true"
    page.click("#hud-qr")
    page.wait_for_selector("#pair-card[hidden]", state="attached")
    assert page.get_attribute("#hud-qr", "aria-expanded") == "false"
    ctx.close()


def test_the_dev_flag_keeps_every_panel(browser, site):  # noqa: F811
    page, errors = open_viewer(browser, site + "?bundle=match/&dev=1")
    assert page.get_attribute("body", "data-screen") is None
    for shown in PANELS:
        assert page.is_visible(shown), shown
    assert not errors
    page.context.close()  # an open page keeps drawing; the audio tests time real playback


def test_a_clip_out_of_match_mode_keeps_its_panels(browser, site):  # noqa: F811
    page, errors = open_viewer(browser, site + "?bundle=plain/")
    assert page.get_attribute("body", "data-screen") is None
    assert page.is_visible("#trace") and page.is_visible("#pipeline")
    assert not errors
    page.context.close()  # an open page keeps drawing; the audio tests time real playback


def test_the_big_screen_pairs_at_once_and_sends_the_phone_match_time_across_the_cut(browser, site):  # noqa: F811
    """The QR code is up without a click, names the bundle, and the clock the phone gets is match
    time: past the cut, image 40 shows match frame 1550 (62.02 s), not t_start plus video time."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    sent: list[dict] = []

    def relay(ws):
        ws.on_message(lambda m: sent.append(json.loads(m)))

    ctx.route_web_socket(re.compile(r".*/api/pair/.*"), relay)
    ctx.route(re.compile(r".*/api/pair$"), lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({"code": "K7MP3Q", "expires_in": 7200})))
    page = ctx.new_page()
    page.goto(site + "?bundle=match/")
    page.wait_for_selector("body[data-state=ready] #overlay[data-t]")
    # No click: paired at once. The companion beside the picture is the phone app on this code, and
    # its "Take it to your phone" carries the same code (the picture's own card stays down for it).
    page.wait_for_function(
        "(document.querySelector('#companion-frame').getAttribute('src') || '').includes('code=K7MP3Q')")
    assert "embed=1" in page.get_attribute("#companion-frame", "src")
    assert page.text_content("#companion-code") == "K7M P3Q"
    assert page.text_content("#pair-code") == "K7M P3Q"  # read off a TV in two groups of three
    assert page.locator("#pair-qr svg").count() == 1
    link = page.get_attribute("#phone-link", "href")
    assert "code=K7MP3Q" in link and "bundle=%2Fmatch%2F" in link
    seek(page, 40)
    page.wait_for_function("document.querySelector('#overlay').dataset.t >= 62")
    page.wait_for_timeout(400)
    last = [m for m in sent if m["type"] == "clock"][-1]
    assert last["t"] == pytest.approx((1550 + 0.5) / FPS, abs=0.03)  # mutation: t_start + video time -> 61.62
    ctx.close()


def test_on_the_encoded_video_the_phone_gets_match_time_after_every_seek_across_the_cut(browser, site):  # noqa: F811
    """The footage ninety/footage.py encodes (H.264, a keyframe every 2 s; the viewer plays its HLS ladder,
    or video.mp4 where HLS cannot play): seeking back and forth across the cut, the picture lands on the
    image asked for and the clock sent to the phone is that image's match time."""
    if not footage.can_encode():
        pytest.skip(f"needs ffmpeg with {footage.ENCODER} to encode the video")
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    sent: list[dict] = []
    ctx.route_web_socket(re.compile(r".*/api/pair/.*"),
                         lambda ws: ws.on_message(lambda m: sent.append(json.loads(m))))
    ctx.route(re.compile(r".*/api/pair$"), lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({"code": "K7MP3Q", "expires_in": 7200})))
    page = ctx.new_page()
    fetched: list[str] = []
    page.on("request", lambda r: fetched.append(r.url))
    page.goto(site + "?bundle=video/")
    page.wait_for_selector("body[data-state=ready] #overlay[data-t]")
    # The encoded footage is what plays: the HLS ladder (hls.js, a blob: source) or the MP4.
    assert any("/video/hls/" in u or "/video/video.mp4" in u for u in fetched)
    # Image k is match frame 1500 + k before the cut (40 images), 1550 + (k - 40) after it.
    for image in (60, 10, 45, 30, 70, 0):
        seek(page, image)
        at = (image + 0.5) / FPS
        page.wait_for_function(f"Math.abs(document.querySelector('video').currentTime - {at}) < 0.05")
        page.wait_for_timeout(300)
        frame = 1500 + image if image < 40 else 1550 + image - 40
        last = [m for m in sent if m["type"] == "clock"][-1]
        assert last["t"] == pytest.approx((frame + 0.5) / FPS, abs=0.03), image
    ctx.close()


def test_the_score_carries_each_demo_clubs_crest_and_no_crest_for_another_club(browser, site):  # noqa: F811
    """The dev view's title row (the big screen leaves the score to the broadcast's scorebug)."""
    page, errors = open_viewer(browser, site + "?bundle=match/&dev=1")
    assert page.locator("#score-crest-home svg").count() == 0  # Crowmere has no crest: nothing drawn
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})

    def demo_clubs(route):
        body = route.fetch().json()
        route.fulfill(json={**body, "teams": {"home": "LON", "away": "LIS"}})

    ctx.route("**/match/manifest.json", demo_clubs)
    page = ctx.new_page()
    page.goto(site + "?bundle=match/&dev=1")
    page.wait_for_selector("#score-crest-away svg")
    page.wait_for_function("document.querySelector('#score').textContent === 'London v Lisbon'")
    assert page.locator("#score-crest-home svg").count() == 1
    assert page.inner_text("#score") == "London v Lisbon"
    assert not errors


def test_the_audio_menu_offers_stadium_or_commentary_on_by_default_with_optional_subtitles(browser, site):  # noqa: F811
    page, errors = open_viewer(browser, site + "?bundle=commentary/")
    assert page.is_visible("#hud-audio") and page.is_visible("#hud-volume")  # the bundle has sound
    page.click("#hud-audio")
    assert page.is_checked("input[name=track][value=commentary]")  # on by default (Kian, Oct 26)
    assert page.is_checked("input[name=subs][value=off]")
    assert page.get_attribute("body", "data-bed-source") == "stadium"  # the bundle's bed file
    page.check("input[name=track][value=stadium]")
    seek(page, 20)  # 60.82 s: inside the first line
    assert page.get_attribute("body", "data-commentary") == ""  # stadium only: no line plays
    page.check("input[name=track][value=commentary]")
    page.wait_for_function("document.body.dataset.commentary === 'c1'")
    assert page.get_attribute("body", "data-bed") == "ducked"  # the crowd sits under the line
    assert page.is_hidden("#captions")  # subtitles are a second, separate choice
    page.check("input[name=subs][value=on]")
    page.wait_for_selector("#captions:not([hidden])")
    assert page.inner_text("#captions") == "Crowmere break at pace"
    # 62.28 s (match frame 1557, past the cut): a line not voiced (audio null) is captioned all the same
    seek(page, 47)
    page.wait_for_function("document.querySelector('#captions').textContent === 'Saved'")
    seek(page, 37)  # 61.5 s: between the lines, no subtitle left on screen
    page.wait_for_selector("#captions[hidden]", state="attached")
    assert page.get_attribute("body", "data-commentary") == ""
    assert page.get_attribute("body", "data-bed") == "full"
    page.keyboard.press("Escape")
    assert page.is_hidden("#audio-menu")
    assert not errors
    page.context.close()


def test_audio_description_stays_reachable_from_the_big_screen_through_the_audio_menu(browser, site):  # noqa: F811
    """No commentary in this bundle: the menu offers Stadium and the audio description persona, by
    keyboard as by pointer, and no subtitles (they are the commentary's)."""
    page, errors = open_viewer(browser, site + "?bundle=match/", silent=True)
    assert page.is_visible("#hud-audio") and page.is_visible("#hud-volume")  # the murmur bed
    assert page.get_attribute("body", "data-bed-source") == "murmur"
    page.focus("#hud-audio")
    page.keyboard.press("Enter")
    assert page.is_visible("#audio-menu")
    assert page.is_hidden("#track-commentary") and page.is_visible("#track-described")
    assert page.is_hidden("input[name=subs][value=on]")
    page.focus("input[name=track][value=described]")
    page.keyboard.press("Space")
    page.wait_for_function("document.body.dataset.persona === 'audio'")
    page.keyboard.press("3")  # the persona keys stay the phone's
    page.check("input[name=track][value=stadium]")
    page.wait_for_function("document.body.dataset.persona === 'casual'")
    assert not errors
    page.context.close()


def test_commentary_with_video_times_plays_by_the_video_clock(browser, site):  # noqa: F811
    """A line with v/v_end (#328) is on air by video time: here v says images 0-10 (0-0.44 s), while
    its match time t would put it elsewhere entirely."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    ctx.route("**/commentary/commentary.json", lambda r: r.fulfill(json={"format": 1, "lines": [
        {"id": "cm-v1", "t": 99.0, "t_end": 100.0, "v": 0.0, "v_end": 0.44, "text": "By the video",
         "audio": None}]}))
    page = ctx.new_page()
    page.goto(site + "?bundle=commentary/")
    page.wait_for_selector("body[data-state=ready] #overlay[data-t]")
    page.click("#hud-audio")
    page.check("input[name=track][value=commentary]")
    page.check("input[name=subs][value=on]")
    seek(page, 5)  # 0.22 s of video
    page.wait_for_function("document.querySelector('#captions').textContent === 'By the video'")
    seek(page, 30)
    page.wait_for_selector("#captions[hidden]", state="attached")
    ctx.close()


def test_the_big_screen_airs_only_moments_that_matter_one_every_thirty_seconds_held_eight(browser, site):  # noqa: F811
    """No lower third for a routine pass (that stays in the phone's All plays); a shot, an insight
    or a recap, at most one starting every 30 s, each held 8 s at most; one moment told for two
    personas airs once, and the insight wins a tie."""
    page, errors = open_viewer(browser, site + "?bundle=match/")

    def cue(cid, kind, t, persona="casual", ev="e1"):
        return {"id": cid, "kind": kind, "slot": "lower_third", "persona": persona, "t_in": t, "t_out": t + 8,
                "text": cid, "evidence": [ev], "replaces": None, "anchor": None, "lang": "en"}

    cues = [cue("pass", "pass_arc", 0), cue("shot", "shot_speed", 10, ev="e2"),
            cue("insight", "insight", 10, persona="analyst", ev="e3"),
            cue("shot2", "shot_speed", 25, ev="e4"), cue("recap", "recap", 41, ev="e5"),
            cue("recap-analyst", "recap", 80, persona="analyst", ev="e5"),
            cue("said", "audio_description", 90, persona="audio", ev="e6")]
    out = page.evaluate(f"window.ninetyMatch.broadcastSchedule({json.dumps(cues)})")
    assert [(c["id"], c["t_in"], c["t_out"]) for c in out] == [("insight", 10, 18), ("recap", 41, 49)]
    assert not errors
    page.context.close()


def bar_cue(cid, t, text, ev=(), kind="insight", persona="analyst", hold=8.0, **more):
    return {
        "id": cid,
        "kind": kind,
        "slot": "lower_third",
        "persona": persona,
        "t_in": t,
        "t_out": t + hold,
        "text": text,
        "evidence": list(ev),
        "replaces": None,
        "anchor": None,
        "lang": "en",
        "verified": True,
        **more,
    }


def test_the_big_screen_airs_every_goal_then_insights_then_a_shot_where_there_is_room(browser, site):  # noqa: F811
    """A goal's insight always airs, its own shot's graphic 1.5 s before it never; an insight beats a
    template shot graphic 4 s ahead of it; one on air when the next comes is cut short; and two
    insights read from positions (no event behind them) are two moments, not one."""
    page, errors = open_viewer(browser, site + "?bundle=match/")
    cues = [
        bar_cue(
            "shot-goal", 100, "A London player scores", ["s1"], kind="shot_speed", persona="casual", hold=5
        ),
        bar_cue("insight-goal:s1", 101.5, "London Athletic scored in minute 2.", ["s1"]),
        bar_cue("shot", 200, "a shot", ["s9"], kind="shot_speed", persona="casual", hold=5),
        bar_cue("insight-lb:s10", 204, "In minute 4, a London Athletic player played a pass.", ["s10"]),
        bar_cue("insight-ov:home:a:1", 300, "In minute 5, London Athletic had 6 players against 1.", []),
        bar_cue("insight-ov:home:a:2", 400, "In minute 7, London Athletic had 7 players against 2.", []),
        bar_cue("insight-cp:home:m8-8", 440, "In minute 8, London Athletic won it back.", ["s20"]),
        bar_cue("insight-goal:s21", 444, "London Athletic scored in minute 8.", ["s21"]),
    ]
    out = page.evaluate(f"window.ninetyMatch.broadcastSchedule({json.dumps(cues)})")
    assert [(c["id"], c["t_in"], c["t_out"]) for c in out] == [
        ("insight-goal:s1", 101.5, 109.5),
        ("insight-lb:s10", 204, 212),
        ("insight-ov:home:a:1", 300, 308),
        ("insight-ov:home:a:2", 400, 408),
        ("insight-goal:s21", 444, 452),
    ]
    assert not errors
    page.context.close()


LT_CONTEXT = {
    "teams": {"home": "London", "away": "Lisbon"},
    "names": ["Kai Laiddon", "Ilya Saindell"],
    "nameSides": {"Kai Laiddon": "home", "Ilya Saindell": "away"},
    "goals": [{"t": 2244.2, "team": "home", "event": "g1"}],
    "scorebug": [
        {"type": "score_read", "t": 2000.0, "score": {"home": 0, "away": 1}},
        {"type": "score_change", "t": 2244.3, "team": "home", "score": {"home": 1, "away": 1}},
    ],
}


@pytest.mark.parametrize(
    ("cue", "want"),
    [
        (
            bar_cue(
                "insight-ov:away:middle-left:79185",
                3167.4,
                "In minute 53, Lisbon Esportes had 7 players against 1 player around the ball, "
                "in their middle third on the left.",
            ),
            {
                "label": "Overload · 53′",
                "side": "away",
                "head": "Lisbon Esportes had 7 players against 1 player around the ball",
                "sub": "In their middle third on the left.",
                "score": None,
                "brief": "7 against 1 around the ball",
                "compare": {"key": "overload_moments", "label": "Overloads"},
            },
        ),
        (
            bar_cue(
                "insight-lb:s12-v00010",
                1517.4,
                "In minute 26, a Lisbon Esportes player played a pass that took 3 London Athletic players "
                "out of the game.",
            ),
            {
                "label": "Line break · 26′",
                "side": "away",
                "sub": "",
                "score": None,
                "head": "A Lisbon Esportes player played a pass that took 3 London Athletic players "
                "out of the game",
                "brief": "Pass took 3 players out of the game",
                "compare": None,
            },
        ),
        (
            bar_cue(
                "insight-lb:s1",
                1517.4,
                "In minute 26, Kai Laiddon played a pass that took 4 Lisbon Esportes players "
                "out of the game.",
            ),  # led by a feed name: his side (the line-up's track), not the first club the sentence names
            {"side": "home", "brief": "Kai Laiddon: pass took 4 players out of the game"},
        ),
        (
            bar_cue("insight-spell:s3", 3005.0, "In minute 51, one side strung 8 passes together in a row."),
            {
                "label": "Passing move · 51′",
                "side": None,
                "head": "One side strung 8 passes together in a row",
                "sub": "",
                "brief": "8 passes together in a row",
            },
        ),
        (
            bar_cue(
                "insight-goal:g1",
                2244.2,
                "London Athletic scored in minute 38. Just before it, Kai Laiddon played a pass.",
            ),
            {
                "label": "Goal · 38′",
                "side": "home",
                "goal": True,
                "head": "London Athletic scored",
                "sub": "Just before it, Kai Laiddon played a pass.",
                "score": {"home": 1, "away": 1},
            },
        ),
        (
            bar_cue(
                "insight-goal:g9", 3000.0, "Ilya Saindell scored for Lisbon Esportes in minute 51."
            ),  # no scorebug change: no score
            {"goal": True, "side": "away", "score": None, "scorer": "Ilya Saindell"},
        ),
        (
            bar_cue("cue-s1", 61.0, "A London player takes a shot", kind="shot_speed", persona="casual"),
            {"label": "Shot · 2′", "side": "home", "goal": False},
        ),
    ],
)
def test_the_lower_third_lays_out_the_checked_words_never_new_ones(browser, site, cue, want):  # noqa: F811
    """The label is the fact's kind and minute (from the cue's fact id and its sentence), the club the
    one the sentence names first, the lead and second line the sentence's own words in order; a
    goal's score is only the scorebug's change for it, its scorer only a feed name the sentence says
    scored."""
    page, errors = open_viewer(browser, site + "?bundle=match/")
    got = page.evaluate(f"window.ninetyLowerThird.describe({json.dumps(cue)}, {json.dumps(LT_CONTEXT)})")
    assert {k: got[k] for k in want} == want
    # Every word on screen is the sentence's, in its order; only "in minute N" moves to the label.
    for line in (got["head"] + " " + got["sub"], got["brief"]):
        said = iter(re.findall(r"[\w']+", cue["text"].lower()))
        assert all(w in said for w in re.findall(r"[\w']+", line.lower())), line
    words = lambda s: re.findall(r"[\w']+", s.lower())  # noqa: E731
    said = iter(words(cue["text"]))
    assert all(w in said for w in words(got["head"] + " " + got["sub"]))
    assert not errors
    page.context.close()


def lower_third_page(browser, site, dock: str, cue=None, scorebug=None, image=10):  # noqa: F811
    """The big screen with one line break on air at match time 60.2 s (or `cue`), its passer named by
    the ID feed, between the demo's two clubs (the crests are theirs, src/crests.ts); `scorebug`: the
    bundle's scorebug readings, through a measured reader's gate."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_init_script(f"try {{ localStorage.setItem('ninety.dock', '{dock}'); }} catch (e) {{}}")
    cue = cue or bar_cue(
        "insight-lb:v1",
        60.2,
        "In minute 2, Kai Laiddon played a pass that took 4 Lisbon Esportes players out of the game.",
        ["v1"],
    )

    def cues(route):
        route.fulfill(body=route.fetch().text() + json.dumps(cue) + "\n", content_type="application/x-ndjson")

    def match(route):
        body = route.fetch().json()
        route.fulfill(json={**body, "lineup": [{"id": "h-t1", "name": "Kai Laiddon", "source": "id_feed"}]})

    def manifest(route):
        gate = (
            {"readings": len(scorebug), "measured": True, "min_confidence": MIN_CONFIDENCE}
            if scorebug
            else None
        )
        route.fulfill(
            json={**route.fetch().json(), "teams": {"home": "LON", "away": "LIS"}, "scorebug": gate}
        )

    ctx.route("**/match/manifest.json", manifest)
    if scorebug:
        ctx.route(
            "**/match/scorebug.jsonl",
            lambda route: route.fulfill(
                body="".join(json.dumps(r) + "\n" for r in scorebug), content_type="application/x-ndjson"
            ),
        )
    ctx.route("**/match/cues.jsonl", cues)
    ctx.route("**/match/match.json", match)
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(site + "?bundle=match/")
    page.wait_for_selector("body[data-state=ready] #overlay[data-t]")
    seek(page, image)  # image 10: 60.4 s
    page.wait_for_selector("#lower-third[data-on='1']")
    page.wait_for_function(
        "!document.querySelector('#lower-third .lt-tab').getAnimations().length"
    )  # slid in
    return page, errors


@pytest.mark.parametrize("dock", ["open", "closed"])
def test_the_insight_is_a_slim_tab_attached_under_the_scorebug(browser, site, dock):  # noqa: F811
    """No INSIGHT box and no panel over the play: a slim tab under the bug's clock tab, as wide as
    the bug, with the fact's kind, its club's code and crest, the minute, a check glyph, one short
    line of the sentence's words with the ID feed's name in bold; docked or not."""
    page, errors = lower_third_page(browser, site, dock)
    assert page.get_attribute("body", "data-dock") == dock
    assert page.inner_text("#lower-third .lt-kind") == "LINE BREAK"
    assert page.inner_text("#lower-third .lt-code") == "LON"  # Kai Laiddon's club, by his track
    assert page.inner_text("#lower-third .lt-min") == "2′"
    assert "INSIGHT" not in page.inner_text("#lower-third")
    assert page.inner_text("#lower-third .lt-head") == "Kai Laiddon: pass took 4 players out of the game"
    assert page.inner_text("#lower-third .lt-head b") == "Kai Laiddon"
    assert page.get_attribute("#lower-third .lt-check", "aria-label") == "Fact-checked"
    assert page.locator("#lower-third .lt-label .lt-crest svg").count() == 1
    bug = page.locator("#scorebug").bounding_box()
    clock = page.locator("#clock-tab").bounding_box()
    tab = page.locator("#lower-third .lt-tab").bounding_box()
    assert clock["y"] >= bug["y"] + bug["height"] - 1.5  # the clock's tab hangs under the bug
    assert tab["y"] >= clock["y"] + clock["height"] - 0.5  # the insight tab under that
    assert abs(tab["x"] - bug["x"]) < 1 and abs(tab["width"] - bug["width"]) < 1  # as wide as the bug
    assert tab["height"] <= 0.12 * page.locator("#stage").bounding_box()["height"]  # slim: one line
    assert "insight-lb:v1" in page.get_attribute("#overlay", "data-on-air")  # still said to a screen reader
    assert not errors
    page.context.close()


def test_the_audio_menu_takes_focus_when_opened_and_gives_it_back_on_escape(browser, site):  # noqa: F811
    """WAI-ARIA disclosure: Enter on the Audio button moves focus to the chosen track, Tab moves
    through the menu's choices, and Escape closes it with focus back on the button."""
    page, errors = open_viewer(browser, site + "?bundle=commentary/")
    page.focus("#hud-audio")
    page.keyboard.press("Enter")
    focused = page.evaluate("document.activeElement.name + ':' + document.activeElement.value")
    assert focused == "track:commentary"  # the track that plays
    page.keyboard.press("Tab")  # out of the Audio group into Subtitles (a radio group is one stop)
    assert page.evaluate("document.activeElement.name") == "subs"
    page.keyboard.press("Escape")
    assert page.is_hidden("#audio-menu")
    assert page.evaluate("document.activeElement.id") == "hud-audio"
    assert page.get_attribute("#hud-audio", "aria-expanded") == "false"
    assert not errors
    page.context.close()


def test_the_big_screen_docks_the_companion_and_shows_the_ask_pill_once(browser, site):  # noqa: F811
    """The phone app beside the picture on a computer (src/dock.ts): open by default, closed by its
    own button or the control bar's, remembered; the first-run pill opens it and never returns."""
    page, errors = open_viewer(browser, site + "?bundle=match/")
    assert page.get_attribute("body", "data-dock") == "open" and page.is_visible("#companion-frame")
    assert page.is_visible("#ask-hint")
    assert page.inner_text("#ask-hint").startswith("Ask anything about this match")
    page.click("#companion-toggle")
    assert page.get_attribute("body", "data-dock") == "closed" and page.is_hidden("#companion")
    assert page.locator("#stage").bounding_box()["width"] == 1280  # the picture takes the room back
    page.click("#ask-hint")  # opens it and is used up
    assert page.get_attribute("body", "data-dock") == "open" and page.is_hidden("#ask-hint")
    page.click("#companion-qr")
    assert page.is_visible("#companion-pair")  # "Take it to your phone": the QR code a tap away
    page.reload()
    page.wait_for_selector("body[data-state=ready] #overlay[data-t]")
    assert page.is_hidden("#ask-hint")  # first run only
    page.click("#hud-companion")
    assert page.get_attribute("body", "data-dock") == "closed"
    page.reload()
    page.wait_for_selector("body[data-state=ready] #overlay[data-t]")
    assert page.get_attribute("body", "data-dock") == "closed"  # remembered
    assert not errors
    page.context.close()


def test_below_1000_px_the_companion_is_a_sheet_under_the_picture(browser, site):  # noqa: F811
    page, errors = open_viewer(browser, site + "?bundle=match/")
    page.set_viewport_size({"width": 800, "height": 1000})
    stage, sheet = page.locator("#stage").bounding_box(), page.locator("#companion").bounding_box()
    assert stage["width"] == 800 and sheet["width"] == 800 and sheet["y"] >= stage["y"] + stage["height"]
    page.click("#companion-toggle")
    assert page.locator("#companion").bounding_box()["height"] == 52  # its handle only
    assert not errors
    page.context.close()


def test_full_screen_is_the_player_and_its_companion_with_the_picture_alone_at_first(browser, site):  # noqa: F811
    page, errors = open_viewer(browser, site + "?bundle=match/")
    page.click("#hud-full")
    page.wait_for_function("document.body.dataset.full === 'on'")
    assert page.evaluate("document.fullscreenElement.classList.contains('layout')")
    assert page.get_attribute("body", "data-dock") == "closed"  # the picture alone at first
    page.click("#hud-companion")
    assert page.get_attribute("body", "data-dock") == "open"  # docked beside it, never over the controls
    page.evaluate("document.exitFullscreen()")
    page.wait_for_function("document.body.dataset.full === 'off'")
    assert page.get_attribute("body", "data-dock") == "open"  # as it was before full screen
    assert not errors
    page.context.close()


def test_after_a_server_restart_the_big_screen_claims_its_same_code_back(browser, site):  # noqa: F811
    """A restart loses the rooms (in memory): the relay answers 4404 for the code on screen. The
    big screen asks for that code back (POST /api/pair with it), so its phones rejoin unscanned."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    posts: list[dict] = []
    laptops: list = []

    def pair(route):
        posts.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(status=201, content_type="application/json",
                      body=json.dumps({"code": "K7MP3Q", "clip": "seed42", "expires_in": 7200}))

    def relay(ws):  # closed from the test, not here: a close inside the handler never returns
        if "role=laptop" in ws.url:
            laptops.append(ws)

    ctx.route(re.compile(r".*/api/pair$"), pair)
    ctx.route_web_socket(re.compile(r".*/api/pair/.*"), relay)
    page = ctx.new_page()
    page.goto(site + "?bundle=match/")
    page.wait_for_function("document.querySelector('#companion-code').textContent === 'K7M P3Q'")
    page.wait_for_timeout(300)
    assert len(laptops) == 1 and "code" not in posts[0]
    laptops[0].close(code=4404)  # the server restarted: it does not know the code
    page.wait_for_timeout(1000)
    assert {"clip": "seed42", "code": "K7MP3Q"} in posts[1:]  # the same code, claimed back
    assert len(laptops) == 2  # and the relay joined again
    assert "code=K7MP3Q" in page.get_attribute("#companion-frame", "src")
    ctx.close()


def _hls_bundle(www, out: str) -> bool:
    """The match bundle with an H.264 HLS ladder and MP4 (as #397 writes them), made by ffmpeg with the
    encoder ninety/footage.py uses (VideoToolbox: never the GPL libx264, which this repo does not run)."""
    import subprocess

    if not footage.can_encode():
        return False
    dst = www / out
    if dst.exists():
        return True
    shutil.copytree(www / "match", dst)
    h264 = ["-c:v", footage.ENCODER, "-b:v", "1M", "-pix_fmt", "yuv420p", "-g", "50",
            "-force_key_frames", "expr:gte(t,n_forced*2)"]
    src = ["-f", "lavfi", "-i", "testsrc=size=320x180:rate=25", "-t", "12"]
    rungs = []
    for h in (360, 180):
        (dst / "hls" / f"{h}p").mkdir(parents=True)
        hls = ["-f", "hls", "-hls_time", "2", "-hls_segment_type", "fmp4", "-hls_playlist_type", "vod"]
        subprocess.run(["ffmpeg", "-v", "error", "-y", *src, "-vf", f"scale=-2:{h}", *h264, *hls,
                        str(dst / "hls" / f"{h}p" / "index.m3u8")], check=True, timeout=120)
        rungs.append(f"#EXT-X-STREAM-INF:BANDWIDTH={h * 4000},RESOLUTION={h * 16 // 9}x{h},"
                     f'CODECS="avc1.640028"\n{h}p/index.m3u8\n')
    (dst / "hls" / "master.m3u8").write_text("#EXTM3U\n#EXT-X-VERSION:7\n" + "".join(rungs))
    subprocess.run(["ffmpeg", "-v", "error", "-y", *src, *h264, "-movflags", "+faststart",
                    str(dst / "video.mp4")], check=True, timeout=120)
    m = json.loads((dst / "manifest.json").read_text())
    m["footage"] = {"kind": "video", "src": "video.mp4", "mp4": "video.mp4", "hls": "hls/master.m3u8",
                    "frames": m["footage"]["frames"], "audio": None}
    (dst / "manifest.json").write_text(json.dumps(m))
    return True


def test_the_big_screen_keeps_the_hls_source_and_opens_past_the_stinger(browser, site):  # noqa: F811
    """The big screen opens on its first clean picture (0.34 s, past the stinger) through the player's own
    source: hls.js stays attached (a blob: source), never replaced by the MP4 afterwards, which dropped
    HLS's fast start and self-heal (#390's poster line ran after attachPlayer)."""
    import urllib.error
    import urllib.request

    try:
        urllib.request.urlopen(site + "hls/manifest.json").close()
    except urllib.error.HTTPError:
        pytest.skip("no ffmpeg to encode the ladder")
    try:
        chrome = browser.browser_type.launch(channel="chrome", headless=True)
    except Exception:
        pytest.skip("no Chrome here (Playwright's Chromium cannot play H.264)")
    page = chrome.new_page(viewport={"width": 1280, "height": 900})
    page.goto(site + "?bundle=hls/")  # match mode: the big screen
    page.wait_for_selector("body[data-state=ready][data-screen=big]")
    page.wait_for_function("window.ninetyPlayer && document.querySelector('#video').readyState >= 2")
    page.wait_for_timeout(500)  # anything set after the player attached would have landed by now
    assert page.evaluate("window.ninetyPlayer.state.source") == "hls.js"
    assert page.evaluate("document.querySelector('#video').src").startswith("blob:")
    assert page.evaluate("document.querySelector('#video').currentTime") == pytest.approx(0.34, abs=0.05)
    chrome.close()


def test_hls_playback_starts_low_and_survives_a_forced_media_error(browser, site):  # noqa: F811
    """src/player.ts in Chrome (H.264 needs the branded build; Playwright's Chromium has no
    H.264): hls.js plays the ladder from its lowest rendition, and a fatal media error is
    recovered with the picture playing on, the spinner down."""
    import urllib.error
    import urllib.request

    try:
        urllib.request.urlopen(site + "hls/manifest.json").close()
    except urllib.error.HTTPError:
        pytest.skip("no ffmpeg to encode the ladder")
    try:
        chrome = browser.browser_type.launch(channel="chrome", headless=True)
    except Exception:
        pytest.skip("no Chrome here (Playwright's Chromium cannot play H.264)")
    page = chrome.new_page(viewport={"width": 1280, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(site + "?bundle=hls/")
    page.wait_for_selector("body[data-state=ready]")
    page.wait_for_function("window.ninetyPlayer && document.querySelector('#video').readyState >= 2")
    assert page.evaluate("window.ninetyPlayer.state.source") == "hls.js"
    # The lowest rung first, for a fast first frame; ABR climbs from it.
    assert page.evaluate("(h => h.levels[h.startLevel].height)(window.ninetyPlayer.hls())") == 180
    page.click("#play")
    page.wait_for_function("document.querySelector('#video').currentTime > 1")
    # recoverMediaError detaches and re-attaches the media: without the player holding on to what
    # the viewer wanted, the picture stops here (it did, before want()).
    page.evaluate("window.ninetyPlayer.fail()")
    at = page.evaluate("document.querySelector('#video').currentTime")
    page.wait_for_function(f"document.querySelector('#video').currentTime > {at} + 1")  # it plays on
    assert page.evaluate("window.ninetyPlayer.state.recoveries") >= 1
    assert page.is_hidden("#spinner")
    assert not errors
    chrome.close()


def test_the_demo_passcode_goes_to_the_companion_and_nowhere_else(browser, site):  # noqa: F811
    """?pass= is taken off the address at once and kept on the device; the ••• menu sets or clears
    it; each value is posted to the embedded companion only, and never written into the page."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    ctx.route(re.compile(r".*/api/pair$"), lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({"code": "K7MP3Q", "expires_in": 7200})))
    ctx.route_web_socket(re.compile(r".*/api/pair/.*"), lambda ws: None)
    # A stand-in companion that keeps what its parent posts.
    ctx.route(re.compile(r".*/phone/\?.*"), lambda route: route.fulfill(content_type="text/html", body=(
        "<script>window.got=[];addEventListener('message',e=>{if(e.origin===location.origin)"
        "window.got.push(e.data)})</script>")))
    # Every postMessage the big screen sends into a frame, with its target origin.
    ctx.add_init_script("""(() => { if (window !== window.top) return;
      const get = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentWindow').get;
      Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', { get() {
        const w = get.call(this);
        return w && { postMessage(m, t) {
          (window.__sent ||= []).push([m, typeof t === 'string' ? t : t && t.targetOrigin]);
          return w.postMessage(m, t); } }; } }); })()""")
    page = ctx.new_page()
    page.goto(site + "?bundle=match/&pass=s3cret-pass")
    page.wait_for_selector("body[data-state=ready] #overlay[data-t]")
    assert "pass=" not in page.url and "bundle=match" in page.url  # stripped, the rest kept
    assert page.evaluate("localStorage.getItem('ninety.passcode')") == "s3cret-pass"
    page.wait_for_function("document.querySelector('#companion-frame').getAttribute('src')")
    companion = page.frame_locator("#companion-frame").owner.element_handle().content_frame()

    def last(passcode):  # postMessage is delivered asynchronously
        companion.wait_for_function(f"(window.got || []).at(-1)?.passcode === {json.dumps(passcode)}")
        assert companion.evaluate("window.got.at(-1)") == {"type": "ninety-passcode", "passcode": passcode}

    last("s3cret-pass")
    page.mouse.move(400, 300)
    page.click("#hud-more")
    page.click("#passcode-clear")
    assert page.evaluate("localStorage.getItem('ninety.passcode')") == ""
    last(None)
    page.fill("#passcode", "other-pass")
    page.keyboard.press("Enter")
    last("other-pass")
    assert page.input_value("#passcode") == ""  # not left in the field
    html = page.content()
    assert "s3cret-pass" not in html and "other-pass" not in html  # never written into the page
    assert "pass" not in page.get_attribute("#companion-frame", "src")  # nor into the panel's address
    page.click("#passcode-save")  # an empty Save keeps it: only Clear wipes it
    assert page.evaluate("localStorage.getItem('ninety.passcode')") == "other-pass"
    # Posted to this origin only: never '*', which any page the frame held could read.
    sent = [s for s in page.evaluate("window.__sent || []") if s[0].get("type") == "ninety-passcode"]
    origin = page.evaluate("location.origin")
    assert len(sent) >= 3 and all(target == origin for _, target in sent), sent
    ctx.close()


def test_a_goal_sweeps_the_bug_in_its_club_s_band_then_the_digit_rolls_and_the_tab_says_goal(browser, site):  # noqa: F811
    """The scorebug's read change is the goal: the scoring club's band sweeps the bug with GOAL for
    the moment, then the score the scorebug changed to; the tab under it says GOAL and the club, and
    slides out half a second before its time is up. A reading under the gate gives no change at all."""
    goal = bar_cue("insight-goal:v2", 59.0, "London Athletic scored in minute 1.", ["v2"], hold=4.2)
    reads = [
        {"type": "score_read", "t": 0.0, "score": {"home": 0, "away": 0}, "confidence": 0.99},
        {
            "type": "score_change",
            "t": 59.1,
            "team": "home",
            "score": {"home": 1, "away": 0},
            "confidence": 0.99,
        },
    ]
    page, errors = lower_third_page(browser, site, "closed", cue=goal, scorebug=reads)  # 60.4 s: 1.3 s in
    assert page.get_attribute("#scorebug", "data-goal") == "home"
    assert page.inner_text("#scorebug .sb-goal") == "GOAL"
    assert (
        page.inner_text("#lower-third .lt-kind") == "GOAL"
        and page.inner_text("#lower-third .lt-code") == "LON"
    )
    seek(page, 63)  # 62.94 s: the moment over, within half a second of the tab's end
    assert page.get_attribute("#scorebug", "data-goal") == ""
    digits = page.eval_on_selector_all("#scorebug .sb-now", "els => els.map(e => e.textContent)")
    assert digits == ["1", "0"]
    assert page.get_attribute("#lower-third", "data-on") == "0"
    page.context.close()
    weak = [{**r, "confidence": MIN_CONFIDENCE - 0.1} for r in reads]
    page, errors2 = lower_third_page(browser, site, "closed", cue=goal, scorebug=weak)
    assert page.get_attribute("#scorebug", "data-goal") == ""  # no change the gate does not pass
    assert page.eval_on_selector_all("#scorebug .sb-now", "els => els.map(e => e.textContent)") == ["", ""]
    assert not errors and not errors2
    page.context.close()


READS = [
    {"type": "score_read", "t": 0.0, "score": {"home": 0, "away": 0}},
    {"type": "score_change", "t": 1292.2, "team": "away", "score": {"home": 0, "away": 1}},
    {"type": "score_read", "t": 1377.9, "score": {"home": 0, "away": 1}},
    {"type": "score_change", "t": 2244.2, "team": None, "score": {"home": 1, "away": 1}},
]


@pytest.mark.parametrize(
    ("reads", "t", "half2", "want"),
    [
        # Before the first read, 0-0 only because the first read is 0-0.
        (READS, -1.0, None, {"score": {"home": 0, "away": 0}, "goal": None, "period": None}),
        (
            READS[1:],
            5.0,
            None,
            {"score": None, "goal": None},
        ),  # a clip that starts at 0-1: no digits until read
        (READS, 2000.0, None, {"score": {"home": 0, "away": 1}, "goal": None}),
        # The side whose count rose, half-way through the moment.
        (
            READS,
            2245.2,
            None,
            {
                "score": {"home": 1, "away": 1},
                "goal": {"side": "home", "p": 0.5, "before": {"home": 0, "away": 1}},
            },
        ),
        (READS, 2246.3, None, {"goal": None}),  # past GOAL_S: settled
        (READS, 2800.0, 2900.0, {"period": "HT"}),  # 45:00 to the second half's detected kick-off
        (READS, 2950.0, 2900.0, {"period": None}),
        (READS, 2800.0, None, {"period": None}),  # no kick-off detected: no half-time card invented
        (READS, 5398.9, None, {"period": "FT"}),  # the engine's 90:00 (Law 7, no added time)
    ],
)
def test_the_scorebug_shows_only_what_the_scorebug_read(browser, site, reads, t, half2, want):  # noqa: F811
    page, errors = open_viewer(browser, site + "?bundle=match/")
    got = page.evaluate(f"window.ninetyScorebug.bugAt({json.dumps(reads)}, {t}, {json.dumps(half2)})")
    if got.get("goal"):
        got["goal"]["p"] = round(got["goal"]["p"], 3)
    assert {k: got[k] for k in want} == want
    assert not errors
    page.context.close()


@pytest.mark.parametrize(
    ("size", "dock"), [((1440, 900), "closed"), ((1920, 1080), "closed"), ((1440, 900), "open")]
)
def test_the_baked_scorebug_never_shows_through(browser, site, size, dock):  # noqa: F811
    """The bug covers the baked one's widest box (render.js geometry, 2 source px more each side) at
    every size, docked or not, and is opaque: the box is pixel-identical with the footage shown and
    hidden, on every frame sampled."""
    ctx = browser.new_context(viewport={"width": size[0], "height": size[1]})
    ctx.add_init_script(f"try {{ localStorage.setItem('ninety.dock', '{dock}'); }} catch (e) {{}}")
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(site + "?bundle=match/")
    page.wait_for_selector("body[data-state=ready] #overlay[data-t]")
    stage = page.locator("#stage").bounding_box()
    fx, fy = stage["width"] / 1280, stage["height"] / 720
    box = {"x": stage["x"] + 26 * fx, "y": stage["y"] + 22 * fy, "width": 404 * fx, "height": 44 * fy}
    bug = page.locator("#scorebug").bounding_box()
    assert bug["x"] <= box["x"] and bug["y"] <= box["y"]
    assert bug["x"] + bug["width"] >= box["x"] + box["width"]
    assert bug["y"] + bug["height"] >= box["y"] + box["height"]
    footage = "#frames" if page.is_visible("#frames") else "#video"
    for image in (0, 20, 39, 41, 74):
        seek(page, image)
        shown = page.screenshot(clip=box)
        page.eval_on_selector(footage, "e => (e.style.visibility = 'hidden')")
        hidden = page.screenshot(clip=box)
        page.eval_on_selector(footage, "e => (e.style.visibility = '')")
        assert shown == hidden, f"the footage shows through the scorebug at image {image}"
    assert not errors
    ctx.close()


def stats_match(possession_sure=False, passes=(40, 30)):
    def team(p, shots):
        return {
            "passes_attempted": p,
            "passes_completed": p - 4,
            "shots": shots,
            "shots_on_target": shots,
            "goals": 0,
        }

    def row(key, home, away, confident=True):
        return {
            "group": "x",
            "key": key,
            "label": key,
            "unit": "",
            "series": [{"minute_to": 5, "home": home, "away": away, "confident": confident}],
        }

    return {
        "stats": [{"t": 100.0, "event": None, "home": team(passes[0], 1), "away": team(passes[1], 1)}],
        "insight_stats": {
            "rows": [
                row("possession", 57, 43, possession_sure),
                row("corner", 2, 1),
                row("crosses", 3, 3, confident=False),
            ]
        },
    }


@pytest.mark.parametrize(
    ("match", "score", "want"),
    [
        # Unsure possession and an unsure row are not shown; attempts no fewer than the scorebug's goals are.
        (
            stats_match(),
            {"home": 1, "away": 0},
            [
                ("shots", 1, 1),
                ("on_target", 1, 1),
                ("passes", 40, 30),
                ("accuracy", 90, 87),
                ("corner", 2, 1),
            ],
        ),
        (
            stats_match(possession_sure=True),
            {"home": 0, "away": 0},
            [
                ("possession", 57, 43),
                ("shots", 1, 1),
                ("on_target", 1, 1),
                ("passes", 40, 30),
                ("accuracy", 90, 87),
                ("corner", 2, 1),
            ],
        ),
        # Fewer attempts than the scorebug's goals contradicts it (every goal is an attempt): not shown.
        (stats_match(), {"home": 4, "away": 1}, [("passes", 40, 30), ("accuracy", 90, 87), ("corner", 2, 1)]),
        # No score read: attempts cannot be checked against it, so not shown; accuracy needs 15 passes a side.
        (stats_match(passes=(40, 9)), None, [("passes", 40, 9), ("corner", 2, 1)]),
    ],
)
def test_the_stats_graphics_show_only_rows_the_bundle_measured_surely(browser, site, match, score, want):  # noqa: F811
    page, errors = open_viewer(browser, site + "?bundle=match/")
    rows = page.evaluate(f"window.ninetyScorebug.rowsAt({json.dumps(match)}, 400, {json.dumps(score)})")
    assert [(r["key"], r["home"], r["away"]) for r in rows] == want
    assert not errors
    page.context.close()


@pytest.mark.parametrize(
    ("v", "start", "ended", "want"),
    [
        (600.5, 0, False, {"kind": "card", "minute": 10}),  # every tenth minute, for CARD_S
        (609.0, 0, False, None),
        (2703.0, 0, False, {"kind": "panel", "period": "HT"}),  # the first PANEL_S from 45:00
        (2711.0, 0, False, None),
        (2703.0, 2800, False, None),  # footage that starts after 45:00 has no half-time panel
        (100.0, 0, True, {"kind": "panel", "period": "FT"}),  # the footage played out
        (5399.0, 0, False, {"kind": "panel", "period": "FT"}),  # the engine's 90:00 (Law 7)
    ],
)
def test_the_stats_card_airs_every_ten_minutes_and_the_panel_at_half_and_full_time(
    browser, site, v, start, ended, want  # noqa: F811
):
    page, errors = open_viewer(browser, site + "?bundle=match/")
    got = page.evaluate(
        f"window.ninetyScorebug.statsGraphicAt({v}, {v}, t => t, {start}, {json.dumps(ended)})"
    )
    assert got == want
    assert not errors
    page.context.close()


def test_at_the_footage_s_end_the_full_time_panel_shows_the_match_s_stats_and_the_bug_stays_on(browser, site):  # noqa: F811
    page, errors = open_viewer(browser, site + "?bundle=match/")
    seek(page, 74)  # the last image
    page.wait_for_selector("#period-panel:not([hidden])")
    assert page.get_attribute("#period-panel", "data-period") == "FT"
    assert page.inner_text("#period-panel .sp-period") == "FULL-TIME"
    assert page.locator("#period-panel .srow").count() >= 1
    assert page.inner_text("#clock-tab") == "FT"
    assert page.is_visible("#scorebug")  # the bug stays on over the panel
    assert not errors
    page.context.close()
