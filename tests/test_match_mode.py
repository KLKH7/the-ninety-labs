"""Match mode (ninety/condensed.py, web/viewer/src/match.ts): a condensed match's chapters, its
scoreline from detected goals, each team's stats from the footage shown, and a "time skip" label
at each cut.

The browser half needs the built viewer and Playwright's Chromium, as tests/test_viewer.py.
"""

from __future__ import annotations

import functools
import json
import re
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
    event("v2", 61.0, "shot", "home", "goal", team_confidence=0.99),
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
    for out, path, match in (("match", events, True), ("standin", standin, True), ("plain", events, False)):
        args = [str(clip), "--out", str(www / out), "--detections", str(detections), "--frames",
                "--events-file", str(path)] + (["--match"] if match else [])
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
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(www))
    handler.log_message = lambda *a: None
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
    assert stage["width"] == 1280 or stage["height"] == 900  # full-bleed: it fills the screen one way
    # The score is the broadcast's own scorebug; our title row is only for a screen reader.
    assert page.locator("#match").bounding_box()["width"] <= 1
    # The controls are on the picture: play, the clock and the scrubber with the chapters on it.
    for shown in ("#hud", "#play", "#scrub", "#clock", "#hud-qr", "#hud-full"):
        assert page.is_visible(shown), shown
    assert page.locator("#ticks i").count() == 1  # the second chapter's start (the first is 0)
    assert page.locator("#ticks i.goal").count() == 0  # chapter 2 is a save; chapter 1 holds the goal
    assert page.is_hidden("#hud-volume")  # the clip has no sound track: no dead control
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
    page.wait_for_selector("#pair-card")  # no click: the TV's pairing card is up at kick-off
    assert page.inner_text("#pair-code") == "K7M P3Q"  # read off a TV in two groups of three
    assert page.locator("#pair-qr svg").count() == 1
    link = page.get_attribute("#phone-link", "href")
    assert "code=K7MP3Q" in link and "bundle=%2Fmatch%2F" in link
    seek(page, 40)
    page.wait_for_function("document.querySelector('#overlay').dataset.t >= 62")
    page.wait_for_timeout(400)
    last = [m for m in sent if m["type"] == "clock"][-1]
    assert last["t"] == pytest.approx((1550 + 0.5) / FPS, abs=0.03)  # mutation: t_start + video time -> 61.62
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


def test_the_audio_menu_offers_stadium_or_commentary_off_by_default_with_optional_subtitles(browser, site):  # noqa: F811
    page, errors = open_viewer(browser, site + "?bundle=commentary/")
    assert page.is_visible("#hud-audio") and page.is_visible("#hud-volume")  # the bundle has sound
    page.click("#hud-audio")
    assert page.is_checked("input[name=track][value=stadium]")  # off by default
    assert page.is_checked("input[name=subs][value=off]")
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
    assert page.is_visible("#hud-audio") and page.is_hidden("#hud-volume")
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


def test_the_big_screen_airs_only_moments_that_matter_one_every_thirty_seconds_held_five(browser, site):  # noqa: F811
    """No lower third for a routine pass (that stays in the phone's All plays); a shot, an insight
    or a recap, at most one starting every 30 s, each held 5 s at most; one moment told for two
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
    assert [(c["id"], c["t_in"], c["t_out"]) for c in out] == [("insight", 10, 15), ("recap", 41, 46)]
    assert not errors
    page.context.close()


def test_the_audio_menu_takes_focus_when_opened_and_gives_it_back_on_escape(browser, site):  # noqa: F811
    """WAI-ARIA disclosure: Enter on the Audio button moves focus to the chosen track, Tab moves
    through the menu's choices, and Escape closes it with focus back on the button."""
    page, errors = open_viewer(browser, site + "?bundle=commentary/")
    page.focus("#hud-audio")
    page.keyboard.press("Enter")
    focused = page.evaluate("document.activeElement.name + ':' + document.activeElement.value")
    assert focused == "track:stadium"
    page.keyboard.press("Tab")  # out of the Audio group into Subtitles (a radio group is one stop)
    assert page.evaluate("document.activeElement.name") == "subs"
    page.keyboard.press("Escape")
    assert page.is_hidden("#audio-menu")
    assert page.evaluate("document.activeElement.id") == "hud-audio"
    assert page.get_attribute("#hud-audio", "aria-expanded") == "false"
    assert not errors
    page.context.close()
