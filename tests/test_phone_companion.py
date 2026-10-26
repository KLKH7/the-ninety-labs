"""The phone as the product surface (R5, Oct 23): its radar is the viewer's (web/viewer/src/radar.ts)
in step with the big screen across the broadcast's cuts, its answers draw the picture their data
carries, and its insights feed asks "Why?" of the Companion.

The phone's dev bundle (dist-mock) is served beside a ninety-e2e bundle of a clip with a cut (40
images of match frames 1500-1539, a cut, then 1550-1584: tests/test_radar.py), as the API serves the
phone beside the Replay bundle. Needs the built phone and Playwright's Chromium (tests/test_phone.py).
"""

from __future__ import annotations

import functools
import json
import re
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from ninety import e2e
from tests.e2e_clip import H, W, write_clip
from tests.test_phone import (  # noqa: F401
    MOCK_CODE,
    MOCK_DIST,
    PHONE_SIZE,
    browser,
    open_ask,
    open_story,
    tap_player,
    turn_on_read_aloud,
    unavailable,
    watch,
)
from tests.test_radar import FPS, SEGMENTS, observations_clip, tracked_clip

ROOT = Path(__file__).resolve().parent.parent
CUT_T = 1540 / FPS  # match time just past the last frame before the cut (61.56 s is frame 1539)
AFTER_T = 1550 / FPS  # the first frame after it (62.0 s)


@pytest.fixture(scope="module")
def site(browser, tmp_path_factory):  # noqa: F811
    if not (MOCK_DIST / "index.html").exists():
        unavailable(f"{MOCK_DIST} is not built: npm run build:mock --prefix web/phone")
    root = tmp_path_factory.mktemp("phone-site")
    page = browser.new_page(viewport={"width": W, "height": H})
    page.set_content('<body style="margin:0;background:#2e7d32"></body>')
    jpeg = page.screenshot(type="jpeg")
    page.close()
    clip, detections, events = write_clip(tmp_path_factory.mktemp("clip"), jpeg)
    # a-t3's side was told surely (a detected pass of his), so the screens may name his club; the
    # other tracked players are in no event that vouches for their side, so each is "a player".
    sure = {"id": "e4", "t": 62.6, "frame": 1565, "type": "pass", "team": "away", "team_confidence": 0.99,
            "player": "a-t3", "receiver": None, "intended": None, "interceptor": None, "deflected_by": None,
            "x": 70.0, "y": 20.0, "end_x": 60.0, "end_y": 25.0, "outcome": "fail", "ball_speed_kmh": 40.0,
            "source": "vision", "confidence": 0.9}
    # Two passes the detector named nobody for: one side told surely, one not (lesson 245).
    nobody = {**sure, "player": None, "outcome": "success", "end_x": 75.0, "end_y": 22.0, "team": "home"}
    told = {**nobody, "id": "e5", "t": 61.6, "frame": 1540, "team_confidence": 0.99}
    unsure = {**nobody, "id": "e6", "t": 61.8, "frame": 1545, "team_confidence": 0.3}
    # The clip's shot (e2) on a side told surely; a second shot (e7) on a side that was not.
    rows = [json.loads(line) for line in events.read_text().splitlines()]
    rows = [{**r, "team_confidence": 0.99} if r["id"] == "e2" else r for r in rows]
    unsure_shot = {**rows[1], "id": "e7", "t": 62.4, "frame": 1560, "team_confidence": 0.3,
                   "outcome": "off_target"}
    events.write_text("".join(json.dumps(e) + "\n" for e in (*rows, sure, told, unsure, unsure_shot)))
    meta = json.loads((clip / "clip.json").read_text())
    (clip / "clip.json").write_text(json.dumps({**meta, "segments": SEGMENTS}))
    tracked = root / "tracked.json"
    tracked.write_text(json.dumps(tracked_clip()))
    observations = root / "observations.jsonl"
    observations.write_text("".join(json.dumps(r) + "\n" for r in observations_clip()))
    www = root / "www"
    shutil.copytree(MOCK_DIST, www / "phone")
    args = [str(clip), "--out", str(www / "bundle"), "--detections", str(detections), "--frames",
            "--events-file", str(events), "--tracked", str(tracked), "--observations", str(observations),
            "--match"]
    worker = threading.Thread(target=e2e.main, args=(args,))  # Playwright holds this thread's loop
    worker.start()
    worker.join()
    manifest = json.loads((www / "bundle" / "manifest.json").read_text())
    assert manifest["teams"] == {"home": "CRW", "away": "DUN"}
    assert manifest["sides_known"] == ["a-t3"]
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(www))
    handler.log_message = lambda *a: None
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


def phone(browser, site, bundle=True, laptop_t: float | None = None, match=None):  # noqa: F811
    """A mock laptop and the phone in one context; with `bundle`, the phone reads the cut clip's.
    `match` edits the bundle's match.json before the phone reads it (e.g. drop its team sheets)."""
    ctx = browser.new_context(viewport=PHONE_SIZE, has_touch=True)
    if match is not None:
        def edited(route):
            body = route.fetch().json()
            match(body)
            route.fulfill(json=body)

        ctx.route("**/bundle/match.json", edited)
    laptop = ctx.new_page()
    laptop.goto(f"{site}phone/mock-laptop.html?code={MOCK_CODE}")
    laptop.wait_for_function("window.ninetyLaptop")
    if laptop_t is not None:
        laptop.fill("#seek", str(laptop_t))
    page = ctx.new_page()
    errors = watch(page)
    query = f"?mock=1&code={MOCK_CODE}&clip=mock" + ("&bundle=/bundle/" if bundle else "")
    page.goto(f"{site}phone/{query}")
    page.wait_for_selector("body[data-state=live]")
    page.wait_for_function("window.ninetyPhone.state.radar !== null")
    return laptop, page, errors


# --- the radar: the viewer's drawing, the TV's way up, in step across a cut ---------------------


def test_the_phone_draws_the_bundles_tracked_radar_named_by_the_clips_codes(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site)
    assert page.get_attribute("#map", "data-from") == "bundle"
    assert page.get_attribute("#map", "data-source") == "tracked"
    assert page.inner_text(".band .home-name") == "Crowmere"  # the clubs on the clip's scorebug
    assert page.get_attribute("#goals-home", "aria-label") == "Crowmere goals"
    assert page.get_attribute("#goals-away", "aria-label") == "Dunhollow goals"
    assert page.inner_text(".band .away-name") == "Dunhollow"
    state = page.evaluate(f"window.ninetyPhone.radarAt({1505 / FPS})")
    assert {p["id"] for p in state["players"]} == {"h-t1", "h-t2", "h-t4", "a-t3"}
    assert not errors


def test_the_radar_is_drawn_the_way_up_the_tv_shows_it_and_a_tap_finds_the_dot(browser, site):  # noqa: F811
    """a-t3 stands at (70, 20): 20 m from the near touchline, which the broadcast camera stands
    behind, so on the TV and on the radar he is below the middle of the pitch. The old minimap drew
    him above it."""
    laptop, page, errors = phone(browser, site, laptop_t=1505 / FPS)
    page.wait_for_function(f"Math.abs(window.ninetyPhone.laptop.time() - {1505 / FPS}) < 0.05")
    box = page.locator("#map").bounding_box()
    x, y = page.evaluate("window.ninetyPhone.screenOf(70, 20)")
    top = page.evaluate("window.ninetyPhone.screenOf(52.5, 68)[1]")
    bottom = page.evaluate("window.ninetyPhone.screenOf(52.5, 0)[1]")
    assert top < y and y > (top + bottom) / 2 and y < bottom  # below halfway between the touchlines
    assert x > box["width"] / 2  # x runs left to right
    page.wait_for_function("document.querySelector('#map').dataset.dots === '4'")
    page.wait_for_function("document.querySelector('#status').dataset.state === 'paused'")  # settled
    box = page.locator("#map").bounding_box()  # measured once the page has stopped moving
    page.touchscreen.tap(box["x"] + x, box["y"] + y)
    page.wait_for_selector("#player:not([hidden])")
    assert page.inner_text("#player-title") == "Dunhollow player"  # a sure side; no track number
    assert not errors


def test_a_tracked_player_on_an_unsure_side_is_never_named_by_club_on_the_phone(browser, site):  # noqa: F811
    # Dry run of the demo (Oct 24): a track id's letter is the tracker's side vote, which the
    # fact-checker did not pass for h-t1, so his card names no club.
    laptop, page, errors = phone(browser, site, laptop_t=1505 / FPS)
    page.wait_for_function(f"Math.abs(window.ninetyPhone.laptop.time() - {1505 / FPS}) < 0.05")
    page.wait_for_function("document.querySelector('#status').dataset.state === 'paused'")
    x, y = page.evaluate("window.ninetyPhone.screenOf(21, 30)")  # h-t1 at frame 1505
    box = page.locator("#map").bounding_box()
    page.touchscreen.tap(box["x"] + x, box["y"] + y)
    page.wait_for_selector("#player:not([hidden])")
    assert page.inner_text("#player-title") == "A player"  # neither his side nor the tracker's number
    assert not errors


def test_the_phone_clock_jumps_the_cut_with_the_video_and_never_shows_the_gap(browser, site):  # noqa: F811
    """The big screen sends match time (61.50 s, playing) and goes quiet. Between messages the phone
    runs its clock in video time: 0.06 s on is the cut, after which the video shows 62.0 s. Running
    on in match time instead would show 61.6-61.9 s, which the video never shows."""
    laptop, page, errors = phone(browser, site)
    laptop.close()  # no more clock messages: the phone runs on alone
    page.evaluate("window.ninetyPhone.laptop.update({type: 'clock', t: 61.5, playing: true})")
    page.wait_for_timeout(250)
    t = page.evaluate("window.ninetyPhone.laptop.time()")
    assert t >= AFTER_T, t  # mutation: drop `cuts` from LaptopClock.time -> about 61.75
    assert not CUT_T <= t < AFTER_T
    page.wait_for_function(f"Number(document.querySelector('#map').dataset.frame) >= {1550}")
    assert not errors


def test_without_a_bundle_the_phone_runs_on_in_match_time(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False)
    assert page.get_attribute("#map", "data-from") == "minimap"
    laptop.close()
    page.evaluate("window.ninetyPhone.laptop.update({type: 'clock', t: 61.5, playing: true})")
    page.wait_for_timeout(250)
    assert 61.6 < page.evaluate("window.ninetyPhone.laptop.time()") < AFTER_T
    assert not errors


# --- answers: the picture their data carries ------------------------------------------------------

QUESTIONS = [
    ("Where are London overloading?", "overload"),
    ("Which pass broke Lisbon's lines?", "line_break"),
    ("What are London's passing options?", "pass_options"),
    ("How are Lisbon set up?", "shape"),
    ("How are the teams moving?", "wind"),
]


def ask(page, text: str):
    open_ask(page)
    n = page.locator("#answers .answer:not(.pending)").count()
    page.fill("#question", text)
    page.click("#ask-button")
    page.wait_for_function(f"document.querySelectorAll('#answers .answer:not(.pending)').length > {n}")
    return page.locator("#answers .answer").last


def pixel(page, x: float, y: float) -> list[int]:
    """The newest answer picture's pixel at pitch metres (x, y), through radar.ts's projection
    (3 m of grass round the lines, y = 0 at the bottom)."""
    return page.evaluate(f"""(() => {{
        const c = [...document.querySelectorAll('#answers .answer figure canvas')].at(-1);
        const s = c.width / 111;
        const at = [Math.round((3 + {x}) * s), Math.round((71 - {y}) * s)];
        return [...c.getContext('2d').getImageData(at[0], at[1], 1, 1).data];
    }})()""")


@pytest.mark.parametrize(("question", "kind"), QUESTIONS)
def test_an_answer_draws_the_picture_its_visual_names_with_its_numbers(browser, site, question, kind):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False, laptop_t=60)
    answer = ask(page, question)
    picture = answer.locator("figure.picture")
    if kind == "shape":  # the committed schema sends a shape's minute only: nothing to draw, and it says so
        assert picture.get_attribute("data-kind") == "none" and "No picture" in picture.inner_text()
        assert not errors
        return
    assert picture.get_attribute("data-kind") == kind  # mutation: draw every visual as an overload -> fails
    canvas = picture.locator("canvas")
    last = "[...document.querySelectorAll('#answers .answer figure canvas')].at(-1)"
    page.wait_for_function(f"{last}.dataset.drawn === '1'")
    answers = [p for p in page.evaluate("window.ninetyPhone.seen") if p.get("type") == "answer"]
    visual = answers[-1]["answer"]["visual"]  # the agents' shape: schemas/insight_card.schema.json
    geo = visual["geometry"]
    head = picture.get_attribute("data-headline")
    # The headline is the visual's own numbers, never the phone's.
    if kind == "overload":
        n, m = len(geo[visual["team"]]), len(geo["away" if visual["team"] == "home" else "home"])
        assert head == f"{n} v {m}"  # the fact's own points, counted
        # The zone is shaded white over the pitch (DESIGN.md): lighter inside its corner than outside.
        z = geo["zone"]
        x0, y0 = min(z["x0"], z["x1"]), min(z["y0"], z["y1"])
        inside = sum(pixel(page, x0 + 0.6, y0 + 0.6)[:3])
        beside = (x0 - 0.6, y0 + 0.6) if x0 > 2 else (x0 + 0.6, y0 - 0.6)
        outside = sum(pixel(page, *beside)[:3])
        assert inside > outside + 30, (inside, outside)  # mutation: draw an overload as a shape -> no zone
        said = f"{n} players against {m}"
        assert said in canvas.get_attribute("aria-label")
    elif kind == "line_break":
        assert head == f"{len(geo['bypassed'])} bypassed"
        f, t = geo["from"], geo["to"]
        r, g, b, _ = pixel(page, (f[0] + t[0]) / 2, (f[1] + t[1]) / 2)
        assert min(r, g, b) > 200, (r, g, b)  # the white arrow, halfway along the pass
    elif kind == "pass_options":
        assert head == f"{len(geo['open'])} open"
    else:
        assert head == ""
    assert canvas.get_attribute("aria-label").startswith("Picture")
    assert not errors


BANDS = [
    {"channel": "left", "y0": 45.3, "y1": 68, "share": 41},
    {"channel": "centre", "y0": 22.7, "y1": 45.3, "share": 33},
    {"channel": "right", "y0": 0, "y1": 22.7, "share": 26},
]
OFFSIDE = {"line_x": 88.4, "receiver": [88.9, 30, "h-t9"], "second_last": [88.4, 36, "a-t4"],
           "ball": [70, 40, None], "attackers": [[80, 20, "h-t7"]], "defenders": [[90, 25, "a-t2"]]}


def test_an_offside_too_close_to_call_is_never_called_and_headlines_are_the_facts(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False)
    base = {"fact": "f1", "t": 60.0, "team": "home", "club": "London"}

    def preview(kind: str, geometry: dict) -> dict:
        visual = {**base, "kind": kind, "geometry": geometry}
        return page.evaluate("v => window.ninetyPhone.preview(v)", visual)

    close = preview("offside", {**OFFSIDE, "verdict": "too_close", "margin_m": 0.05})
    assert close["headline"] == "Too close to call"
    assert "too close to call" in close["words"]
    assert "onside" not in close["words"] and "offside by" not in close["words"]  # never called either way
    called = preview("offside", {**OFFSIDE, "verdict": "offside", "margin_m": 0.6})
    assert called["headline"] == "Offside by 0.6 m"
    assert preview("channels", {"bands": BANDS})["headline"] == "41% down the left"
    counter = preview("counter", {"from": [30, 30], "to": [95, 34], "seconds": 9.4})
    assert counter["headline"] == "9 s, regain to shot"
    assert not errors


def test_a_visual_missing_its_numbers_draws_no_picture(browser, site):  # noqa: F811
    """The phone never fills in a number: an agents' visual (schemas/insight_card.schema.json) without
    the data its kind needs is not drawn."""
    laptop, page, errors = phone(browser, site, bundle=False)
    base = {"fact": "f1", "t": 60.0, "team": "home", "club": "London"}
    zone = {"x0": 40.0, "x1": 60.0, "y0": 20.0, "y1": 40.0}
    lb = {"from": [40, 30], "to": [70, 30, "h-t9"]}
    press = {"ball": [60, 30], "pressers": [[58, 30]]}
    cases = [
        ({**base, "kind": "overload",
          "geometry": {"zone": zone, "home": [[50, 30], [52, 28]], "away": [[55, 31]]}},
         True),
        ({**base, "kind": "overload", "geometry": {"zone": zone, "home": [[50, 30]]}}, False),  # no away list
        ({**base, "kind": "line_break", "geometry": lb}, False),  # no defenders bypassed
        ({**base, "kind": "line_break", "geometry": {**lb, "bypassed": [[55, 30], [60, 33]]}}, True),
        ({**base, "kind": "pass_options", "geometry": {"open": [[50, 30]]}}, False),  # nobody on the ball
        ({**base, "kind": "pass_options", "geometry": {"passer": [40, 30], "open": [[50, 30]], "marked": []}},
         True),
        ({**base, "kind": "counter_press", "geometry": {**press, "radius_m": 5}}, True),
        ({**base, "kind": "counter_press", "geometry": press}, False),  # no radius
        ({**base, "kind": "shape", "geometry": {"minute": 23}}, False),  # v1: a minute, no lines to draw
        ({**base, "kind": "shape", "geometry": {"minute": 23, "lines": [[[30, 10], [30, 50]]]}}, True),
        ({**base, "kind": "wind_map", "geometry": {"t_from": 30.0, "t_to": 60.0}}, True),
        ({**base, "kind": "overload", "geometry": {"zone": zone, "home": [[400, 30]], "away": []}},
         False),  # off the pitch
        ({**base, "team": None, "kind": "wind_map", "geometry": {"t_from": 30.0, "t_to": 60.0}},
         False),  # no team
        ({**base, "kind": "heatmap", "geometry": {}}, False),  # a kind the phone does not know
        ({**base, "kind": "channels", "geometry": {"bands": BANDS}}, True),
        ({**base, "kind": "channels", "geometry": {"bands": BANDS[:2]}}, False),  # three lanes or none
        ({**base, "kind": "offside", "geometry": {**OFFSIDE, "verdict": "offside", "margin_m": 0.6}}, True),
        ({**base, "kind": "offside", "geometry": {**OFFSIDE, "verdict": "offside"}},
         False),  # a call needs its margin
        ({**base, "kind": "offside", "geometry": {**OFFSIDE, "verdict": "too_close"}}, True),
        ({**base, "kind": "counter", "geometry": {"from": [30, 30], "to": [95, 34], "seconds": 9.4}}, True),
        ({**base, "kind": "counter", "geometry": {"from": [30, 30], "to": [95, 34]}}, False),  # no time
    ]
    for visual, ok in cases:
        assert page.evaluate("v => window.ninetyPhone.drawable(v)", visual) is ok, visual
    assert not errors


def test_a_player_is_named_by_the_answers_names_or_his_club_never_his_id(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False, laptop_t=60)
    label = page.evaluate("[window.ninetyPhone.name('a-t12'), window.ninetyPhone.name('h7'), "
                          "window.ninetyPhone.name('a-t12', {'a-t12': \"Lisbon's left-back\"})]")
    assert label == ["Lisbon player", "London 7", "Lisbon's left-back"]  # never the tracker's number
    assert not errors


# --- insights: pushed cards up to the clock, each with "Why?" ---------------------------------------


def test_story_shows_only_cards_up_to_the_clock_and_how_we_know_holds_why(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False, laptop_t=50)
    requests: list[str] = []
    page.on("request", lambda r: requests.append(r.url))
    page.wait_for_function("window.ninetyPhone.state.insights.length > 0")
    cards = page.evaluate("window.ninetyPhone.state.insights")
    assert cards and all(c["t"] <= 50.2 for c in cards)  # never a card from later in the replay
    open_story(page)
    assert page.get_attribute("#tab-button-insights", "aria-selected") == "true"
    page.wait_for_selector("#insights-title")
    first = page.locator("#insights .moment").first
    assert first.locator("h3").text_content() == cards[0]["headline"]
    assert first.locator(".story-body > figure canvas").count() == 1
    first.locator(".how").click()
    # The Scout's precomputed, fact-checked "why it matters" is in the sheet: no question is sent.
    page.locator("#how-body .stepper").wait_for()
    assert cards[0]["why"]["answer"]["text"] in page.inner_text("#how-body")  # why it matters, first
    # Without the big screen's footage there is no frame to show: what was measured, and the check.
    assert page.inner_text("#how-body .count-line") == "2 checks · all passed"
    assert page.locator("#how-body .step").count() == 2
    assert not [u for u in requests if "/api/ask" in u]
    assert not errors


def test_the_tabs_move_with_the_arrow_keys(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False)
    focused = lambda tab: page.wait_for_function(f"document.activeElement.id === 'tab-button-{tab}'")  # noqa: E731
    assert page.get_attribute("#tab-button-radar", "tabindex") == "0"  # one tab stop for the bar
    assert page.get_attribute("#tab-button-ask", "tabindex") == "-1"
    page.focus("#tab-button-radar")
    page.keyboard.press("ArrowRight")
    focused("ask")
    page.wait_for_selector("#ask-content")
    page.keyboard.press("End")
    focused("insights")
    page.wait_for_selector("#insights-title")
    page.keyboard.press("ArrowRight")  # round to the first
    focused("radar")
    page.wait_for_selector("#insights-title", state="hidden")
    assert page.get_attribute("#tab-button-radar", "aria-selected") == "true"
    assert not errors


def test_every_scorebug_code_has_one_club_name_starting_with_its_letters():
    """The screens name the clubs the picture shows: web/viewer/src/teams.ts maps each of the
    renderer's codes (ninety/render/params.py) to one invented name, and e2e carries the clip's."""
    from pathlib import Path

    from ninety.render.params import TEAM_CODES

    source = (Path(__file__).resolve().parent.parent / "web" / "viewer" / "src" / "teams.ts").read_text()
    clubs = dict(re.findall(r'^\s+([A-Z]{3}): "([^"]+)",(?: //.*)?$', source, re.M))
    # Every code the renderer draws has a club. Kian renamed the demo's two clubs (Oct 24): bundles
    # made before carry OAK / FEN, the renderer's new scorebug LON / LIS; both name the same club.
    assert set(TEAM_CODES) <= set(clubs)
    same = {"OAK": "LON", "FEN": "LIS"}
    assert set(clubs) - set(TEAM_CODES) <= set(same) | set(same.values())
    for old, new in same.items():
        assert clubs[old] == clubs[new], (old, new)
    others = {code: name for code, name in clubs.items() if code not in same}
    assert len(set(others.values())) == len(others)  # one name per club
    for code, name in others.items():
        assert name.upper().startswith(code[0]), (code, name)  # the screens name the club the scorebug shows
    teams = {"home": "FEN", "away": "OAK"}
    assert e2e.teams_of({"params": {"home_code": "FEN", "away_code": "OAK"}}) == teams
    assert e2e.teams_of({"params": {}}) is None


# --- the Insight Scout's cards, in the bundle (schemas/insight_card.schema.json, PR #259) ----------

SCHEMAS = ROOT / "schemas"


def needs_card_schema():
    if not (SCHEMAS / "insight_card.schema.json").exists():
        pytest.skip("schemas/insight_card.schema.json arrives with the Insight Scout's PR #259")


def scout_card(cid: str, t: float, headline: str) -> dict:
    """A card exactly as ninety.agents.scout writes one (its schema), with an overload picture."""
    visual = {"kind": "overload", "fact": f"ov:{cid}", "t": t, "team": "home", "club": "Crowmere",
              "geometry": {"zone": {"x0": 40, "x1": 64, "y0": 22, "y1": 46},
                           "home": [[50, 30], [52, 28], [55, 35]], "away": [[57, 31]]}}
    return {"id": cid, "t": t, "minute": int(t // 60) + 1, "team": "home", "club": "Crowmere",
            "kind": "overload",
            "headline": headline, "text": "Crowmere had three players round the ball against one.",
            "status": "verified", "source": "code", "evidence": [f"ov:{cid}"], "visual": visual,
            "why": {"question": "Why does that matter?",
                    "answer": {"status": "verified", "text": "A spare player to pass to.",
                               "evidence": [f"ov:{cid}"], "visual": visual}},
            "spoken": "Crowmere had three players round the ball against one."}


@pytest.fixture(scope="module")
def cards_site(browser, site, tmp_path_factory):  # noqa: F811
    """The cut clip's bundle again, now with two of the Scout's cards: one before the cut, one after."""
    needs_card_schema()
    root = tmp_path_factory.mktemp("cards")
    cards = root / "cards.json"
    cards.write_text(json.dumps([scout_card("c2", 62.5, "Crowmere overload late"),
                                 scout_card("c1", 60.5, "Crowmere overload early")]))
    page = browser.new_page(viewport={"width": W, "height": H})
    page.set_content('<body style="margin:0;background:#2e7d32"></body>')
    jpeg = page.screenshot(type="jpeg")
    page.close()
    clip, detections, events = write_clip(tmp_path_factory.mktemp("clip"), jpeg)
    www = root / "www"
    shutil.copytree(MOCK_DIST, www / "phone")
    args = [str(clip), "--out", str(www / "bundle"), "--detections", str(detections), "--frames",
            "--events-file", str(events), "--cards", str(cards)]
    worker = threading.Thread(target=e2e.main, args=(args,))
    worker.start()
    worker.join()
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(www))
    handler.log_message = lambda *a: None
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/", www
    server.shutdown()


def test_e2e_writes_the_scouts_cards_oldest_first_and_refuses_an_unchecked_one(cards_site, tmp_path):
    _, www = cards_site
    written = json.loads((www / "bundle" / "cards.json").read_text())
    assert [c["id"] for c in written] == ["c1", "c2"]
    assert json.loads((www / "bundle" / "manifest.json").read_text())["cards"] == {"count": 2}
    held = tmp_path / "held.json"
    held.write_text(json.dumps([{**scout_card("c3", 61.0, "x"), "status": "held"}]))
    with pytest.raises(Exception, match="verified"):  # only verified cards reach a fan
        e2e.read_cards(held)


def test_the_phone_shows_the_bundles_cards_up_to_the_clock_with_their_pictures(browser, cards_site):  # noqa: F811
    url, _ = cards_site
    laptop, page, errors = phone(browser, url, laptop_t=61)
    page.wait_for_function("window.ninetyPhone.state.insights.length > 0")
    assert [c["id"] for c in page.evaluate("window.ninetyPhone.state.insights")] == ["c1"]  # c2 is at 62.5
    open_story(page)
    card = page.locator("#insights .moment").first
    assert card.locator("h3").inner_text() == "Crowmere overload early"
    figure = card.locator(".story-body > figure")
    assert figure.get_attribute("data-headline") == "3 v 1"  # the fact's own points
    assert not errors


def test_the_mocks_answers_and_cards_match_the_agents_schemas(browser, site):  # noqa: F811
    """The mock stands in for the agents, so it must send exactly their shapes."""
    needs_card_schema()
    from ninety.agents.contracts import schema_validator

    card_schema = schema_validator("insight_card")
    answer_schema = schema_validator("viewer_answer")
    laptop, page, errors = phone(browser, site, bundle=False, laptop_t=110)
    page.wait_for_function("window.ninetyPhone.state.insights.length > 0")
    for card in page.evaluate("window.ninetyPhone.state.insights"):
        card_schema.validate(card)
    for question, _ in QUESTIONS[:4]:
        ask(page, question)
    for p in page.evaluate("window.ninetyPhone.seen"):
        if p.get("type") == "answer":
            answer_schema.validate(p["answer"])
    assert not errors


def test_how_do_we_know_shows_the_frame_with_what_the_detector_found_and_the_check(browser, site):  # noqa: F811
    """At 61.2 s the cut clip's detections (tests/e2e_clip.py) are on the bundle's frame: the sheet
    boxes each with its confidence, says so in words, and says which check passed the answer."""
    laptop, page, errors = phone(browser, site, laptop_t=61.2)
    answer = ask(page, "Where are London overloading?")
    answer.locator(".how").click()
    seen = "document.querySelector('#how-body canvas.seen')?.getAttribute('aria-label')"
    page.wait_for_function(f"({seen} || '').includes('percent')")
    words = page.get_attribute("#how-body canvas.seen", "aria-label")
    assert words.startswith("The broadcast picture at 1:01")
    # a code answer: no Judge to claim
    assert "Checked by code before it was shown" in page.inner_text("#how-body")
    assert page.locator("#how-body figure.picture").count() == 1  # what it measured, drawn again
    assert not errors


def test_live_has_a_players_list_and_the_play_in_words_appears_when_focus_reaches_it(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False)
    assert page.is_visible("#lt-players")  # Players: a visible way to any player
    box = page.locator("#now-box").bounding_box()
    assert box["width"] <= 1 and box["height"] <= 1  # the describe controls are off screen...
    page.focus("#now-live")  # ...until a keyboard or screen-reader user reaches them
    box = page.locator("#now-box").bounding_box()
    assert box["width"] > 100 and box["height"] > 40, box
    turn_on_read_aloud(page)  # one control: read aloud, and describe the play as it happens
    assert page.is_checked("#now-live")
    assert not errors



def test_an_answer_headline_reads_naturally_from_its_own_numbers(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False, laptop_t=60)
    answer = ask(page, "Where are London overloading?")
    answers = [p for p in page.evaluate("window.ninetyPhone.seen") if p.get("type") == "answer"]
    visual = answers[-1]["answer"]["visual"]
    g = visual["geometry"]
    n, m = len(g[visual["team"]]), len(g["away" if visual["team"] == "home" else "home"])
    assert answer.locator(".figure").inner_text() == f"{n} v {m} round the ball"
    assert not errors


def test_the_var_check_puts_the_margin_on_a_scale_and_never_calls_inside_the_band(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False)
    base = {"fact": "f1", "t": 60.0, "team": "home", "club": "London", "kind": "offside"}

    def var(geometry):
        page.evaluate("v => window.ninetyPhone.how(v)", {**base, "geometry": geometry})
        page.wait_for_function("document.querySelector('#how-title').textContent === 'VAR check'")
        return page.inner_text("#how-body")

    said = var({**OFFSIDE, "verdict": "too_close", "margin_m": 0.4})
    assert "Too close to call from the cameras" in said and "Offside," not in said
    label = page.get_attribute("#how-body .margin-scale", "aria-label")
    assert label.startswith("0.40 metres ahead") and "within 1.78 metres" in label
    page.click("#close-how")
    said = var({**OFFSIDE, "verdict": "unsure"})
    assert "a defender was out of the cameras' view" in said
    assert page.locator("#how-body .margin-scale").count() == 0  # no margin to put on a scale
    assert not errors


def test_live_shows_just_now_and_match_stats_from_the_bundle_only(browser, cards_site):  # noqa: F811
    url, www = cards_site
    laptop, page, errors = phone(browser, url, laptop_t=61)
    page.wait_for_function("window.ninetyPhone.state.insights.length > 0")
    assert "Crowmere had three players" in page.inner_text("#just-now")  # the newest card up to the clock
    # No match.json in this bundle: no stats are shown rather than any invented.
    assert page.locator("#live-stats").is_hidden() and page.locator(".side-goal").count() == 0
    assert not errors


def test_live_match_stats_are_match_json_s_numbers_as_mirrored_rows(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, laptop_t=62.8)
    page.click("#lt-stats")
    page.wait_for_selector("#live-stats:not([hidden])")
    stats = json.loads(page.evaluate("fetch('/bundle/match.json').then(r => r.text())"))["stats"]
    last = [s for s in stats if s["t"] <= 62.8][-1]
    rows = page.locator("#stat-rows .stat-row")
    labels = [rows.nth(i).get_attribute("aria-label") for i in range(rows.count())]
    assert f"Shots seen: Crowmere {last['home']['shots']}, Dunhollow {last['away']['shots']}" in labels
    home, away = last["home"]["passes_completed"], last["away"]["passes_completed"]
    assert f"Passes completed: Crowmere {home}, Dunhollow {away}" in labels
    assert not errors



def test_the_player_sheet_compares_two_players_from_their_own_cards(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False, laptop_t=60)
    page.click("#lt-players")
    page.get_by_role("button", name="London 7", exact=True).click()
    page.wait_for_function("document.querySelector('#speed').textContent !== '–'")
    assert "average position" in page.inner_text("#avg-pos")
    names = [c.inner_text() for c in page.locator("#compare-chips button").all()]
    assert names[:3] == ["London 1", "London 2", "London 3"] and "London 10" in names  # 3 before 10
    assert names.index("London 11") < names.index("Lisbon 1")  # his own club first
    page.locator("#compare-chips").get_by_role("button", name="Lisbon 7", exact=True).click()
    page.wait_for_selector("#compare-rows:not([hidden]) .stat-row")
    labels = [page.locator("#compare-rows .stat-row").nth(i).get_attribute("aria-label") for i in range(3)]
    assert labels[0].startswith("Speed now (km/h): London 7 ") and ", Lisbon 7 " in labels[0]
    assert not errors


def test_the_territory_strip_is_match_json_s_and_rewinding_it_moves_the_whole_screen(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, laptop_t=62.8)
    match = json.loads(page.evaluate("fetch('/bundle/match.json').then(r => r.text())"))
    (b,) = match["territory"]["bins"]  # the clip's few seconds are one 5-minute spell
    # A few seconds of seen ball is too little to show: the card stays hidden.
    assert b["seen_s"] < 30 and page.locator("#momentum").is_hidden()
    # The same spell as a longer match would have it (40 s of seen ball): the strip shows.
    b["seen_s"] = 40.0
    page.context.route("**/bundle/match.json", lambda route: route.fulfill(json=match))
    page.reload()
    page.wait_for_selector("body[data-state=live]")
    page.wait_for_selector("#momentum:not([hidden])")
    assert match["territory"]["source"] == "tracked"
    strip = page.locator("#momentum-strip")
    said = strip.get_attribute("aria-valuetext")
    assert said.startswith("Live. Minute 2: ")
    if b["home"] is not None and b["home"] != 0.5:
        share = round(max(b["home"], 1 - b["home"]) * 100)
        assert f"{share}% of territory" in said
    # Home rewinds to the first moment the footage shows; the clock, pitch and status follow it.
    first = match["chapters"][0]["t"]
    strip.focus()
    page.keyboard.press("Home")
    page.wait_for_function(f"Math.abs(Number(document.querySelector('#map').dataset.t) - {first}) < 0.05")
    assert page.text_content("#clock") == f"{int(first) // 60}:{int(first) % 60:02d}"
    assert page.text_content("#status") == f"Rewound to {int(first) // 60 + 1}′"
    assert page.locator("#to-live").is_visible()
    assert not strip.get_attribute("aria-valuetext").startswith("Live.")
    # End is live again.
    page.keyboard.press("End")
    page.wait_for_function("document.querySelector('#to-live').hidden")
    page.wait_for_function("!document.querySelector('#status').textContent.startsWith('Rewound')")
    assert not errors


def test_the_shot_map_draws_detected_shots_up_to_the_clock_toward_one_goal(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, laptop_t=62.8)
    # Rewinding goes through the territory strip, shown once it rests on 30 s of seen ball.
    match = json.loads(page.evaluate("fetch('/bundle/match.json').then(r => r.text())"))
    match["territory"]["bins"][0]["seen_s"] = 40.0
    page.context.route("**/bundle/match.json", lambda route: route.fulfill(json=match))
    page.reload()
    page.wait_for_selector("body[data-state=live]")
    page.click("#lt-stats")
    page.wait_for_selector("#shot-map:not([hidden])")
    # The clip's one shot: home's, from (80, 34), saved. Home attacks x = 105, so it is 25 m out, central.
    dot = page.locator("#shots circle.shot")
    assert dot.count() == 1
    assert dot.get_attribute("class") == "shot home on"
    assert float(dot.get_attribute("cx")) == 34 and float(dot.get_attribute("cy")) == 25
    listed = page.locator("#shot-list li").all_inner_texts()
    assert len(listed) == 2 and "saved" in listed[0]
    # e7's side was not told surely (lesson 245): listed with no zone and drawn nowhere, as where it
    # sits on the half pitch is read from the direction its side attacks.
    assert "from the" not in listed[1] and "off target" in listed[1]
    page.locator("#shot-filter ion-segment-button[value=away]").click()
    page.wait_for_function("document.querySelectorAll('#shots circle.shot').length === 0")
    page.locator("#shot-filter ion-segment-button[value=home]").click()
    page.wait_for_function("document.querySelectorAll('#shot-list li').length === 1")  # no club claims e7
    # Rewound to before the shot (61.2 s), there is none to show.
    page.click("#lt-pitch")
    page.locator("#momentum-strip").focus()
    page.keyboard.press("Home")
    page.wait_for_selector("#shot-map[hidden]", state="attached")
    assert not errors


def test_read_aloud_is_off_until_tapped_and_an_automated_browser_never_speaks(browser, site):  # noqa: F811
    """Kian heard the system voice from a test run (Oct 24): read-aloud starts only on a tap, and
    under automation (navigator.webdriver) a line is recorded, never handed to speechSynthesis."""
    laptop, page, errors = phone(browser, site, bundle=False)
    page.evaluate("() => { window.__spoke = 0; speechSynthesis.speak = () => { window.__spoke += 1; }; }")
    assert page.get_attribute("#settings-sheet .speak", "aria-pressed") == "false"
    page.evaluate("window.ninetyPhone.announce('A line with read-aloud off')")  # words on screen, no voice
    assert page.text_content("#announce") == "A line with read-aloud off"
    assert page.evaluate("window.ninetySpokenAloud") is None
    turn_on_read_aloud(page)
    page.evaluate("window.ninetyPhone.announce('A line with read-aloud on')")
    page.wait_for_function("(window.ninetySpokenAloud || []).length > 0")
    # mutation: call speechSynthesis.speak in speakAloud under webdriver -> __spoke > 0
    assert page.evaluate("window.__spoke") == 0
    assert not errors


def test_listening_settings_set_the_rate_the_transcript_and_the_text_size(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False)
    page.click(".settings-open >> nth=0")
    page.wait_for_selector("#settings-sheet #rate")
    page.fill("#rate", "1.4")
    assert page.text_content("#rate-value") == "1.4x"
    page.locator("#text-sizes [role=radio]", has_text="Large").first.click()
    assert page.evaluate("document.documentElement.dataset.text") == "large"
    assert page.get_attribute("#text-sizes [role=radio] >> nth=1", "aria-checked") == "true"
    page.click("#close-settings")
    # The choices hold across a reload (this browser only).
    page.reload()
    page.wait_for_selector("body[data-state=live]")
    assert page.evaluate("document.documentElement.dataset.text") == "large"
    # Read-aloud on, with the transcript on (the default): the line is shown as it is said.
    turn_on_read_aloud(page)
    page.evaluate("window.ninetyPhone.announce('London break forward')")
    page.wait_for_selector("#caption:not([hidden])")
    assert page.text_content("#caption") == "London break forward"
    assert page.evaluate("window.ninetySpokenAloud") == ["London break forward"]  # recorded, never voiced
    assert not errors


def test_team_stats_add_the_scouts_rows_so_far_at_the_clock_marking_unsure_and_hiding_null(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, laptop_t=62.8)  # minute 2
    match = json.loads(page.evaluate("fetch('/bundle/match.json').then(r => r.text())"))
    match["insight_stats"] = {"bin_min": 5, "rows": [
        {"group": "Pressing", "key": "turnovers", "label": "Turnovers", "unit": "turnovers", "series": [
            {"minute_to": 1, "home": 1, "away": 0, "confident": True},
            {"minute_to": 2, "home": 3, "away": 1, "confident": True},
            {"minute_to": 3, "home": 9, "away": 9, "confident": True}]},  # still to come: never shown
        {"group": "Shape", "key": "width", "label": "Width", "unit": "m", "series": [
            {"minute_to": 2, "home": 41, "away": 38, "confident": False}]},
        {"group": "Shape", "key": "length", "label": "Length", "unit": "m", "series": [
            {"minute_to": 2, "home": None, "away": 30, "confident": True}]}]}
    ctx = page.context
    ctx.route("**/bundle/match.json", lambda route: route.fulfill(json=match))
    page.reload()
    page.wait_for_selector("body[data-state=live]")
    page.click("#lt-stats")
    page.wait_for_selector("#stat-rows .stat-row")
    labels = [page.locator("#stat-rows .stat-row").nth(i).get_attribute("aria-label")
              for i in range(page.locator("#stat-rows .stat-row").count())]
    home_and_away = " 3, Dunhollow 1"
    assert any(label.startswith("Turnovers: ") and label.endswith(home_and_away) for label in labels), labels
    assert any(label.startswith("Width (m): ") and label.endswith("(unsure)") for label in labels), labels
    assert not any(label.startswith("Length") for label in labels)  # null is not measurable
    assert page.locator("#stat-rows .stat-group h3", has_text="Pressing").count() == 1
    assert not errors


@pytest.mark.parametrize(("question", "headline", "shown"), [
    ("Who has run the furthest?", "a7", "Lisbon 7"),  # who: a name (ids named like the sentence)
    ("How many passes have London completed?", "12 passes", "12 passes"),  # how many: a number, a unit
    ("Where are London overloading?", "Their right, middle third", "Their right, middle third"),  # where
])
def test_an_answer_headline_is_codes_direct_answer(browser, site, question, headline, shown):  # noqa: F811
    """Kian's rule (#294): the headline answers the question; code computes it from the question's kind."""
    laptop, page, errors = phone(browser, site, bundle=False)
    page.click("#tab-button-ask")
    answer = {"status": "verified", "text": "A sentence.", "metric": None, "value": 99, "unit": "km/h",
              "evidence": ["f1"], "t_from": 60.0, "t_to": 61.0, "headline": headline}
    page.evaluate("([q, a]) => window.ninetyPhone.answer(q, a)", [question, answer])
    # mutation: ignore `headline` in renderAnswer -> the figure "99 km/h" shows instead
    assert page.locator("#answers .answer .figure").last.inner_text() == shown
    assert not errors


def test_without_a_headline_an_answer_falls_back_to_its_pictures_headline(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False)
    page.click("#tab-button-ask")
    visual = {"kind": "overload", "fact": "f1", "t": 60.0, "team": "home", "club": "Crowmere",
              "geometry": {"zone": {"x0": 40, "x1": 64, "y0": 22, "y1": 46},
                           "home": [[50, 30], [52, 28], [55, 35]], "away": [[57, 31]]}}
    answer = {"status": "verified", "text": "A sentence.", "metric": None, "value": None, "unit": None,
              "evidence": ["f1"], "t_from": 60.0, "t_to": 60.0, "visual": visual, "headline": None}
    page.evaluate("([q, a]) => window.ninetyPhone.answer(q, a)", ["Where are Crowmere overloading?", answer])
    assert page.locator("#answers .answer .figure").last.inner_text() == "3 v 1 round the ball"
    assert not errors


def test_team_distance_says_how_close_it_is_measured(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, laptop_t=62.8)
    match = json.loads(page.evaluate("fetch('/bundle/match.json').then(r => r.text())"))
    distance = {"home": {"km": 4.1, "coverage": 0.93}, "away": {"km": 3.8, "coverage": 0.9}}
    match["team_stats"] = {"from_footage": True, "within_pct": 15, "distance": distance}
    page.context.route("**/bundle/match.json", lambda route: route.fulfill(json=match))
    page.reload()
    page.wait_for_selector("body[data-state=live]")
    page.click("#lt-stats")
    row = page.locator("#stat-rows .stat-row", has_text="Distance (km)")
    row.wait_for()
    assert row.locator(".within").inner_text().strip() == "±15%"  # quiet, after the label; no caption
    assert row.get_attribute("aria-label").endswith(", measured to within 15 percent")
    assert not errors


def test_a_question_already_asked_is_not_suggested_again(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False, laptop_t=60)
    page.click("#tab-button-ask")
    first = page.locator("#ask-chips .chip").first.inner_text()
    ask(page, first)
    suggested = [c.inner_text() for c in page.locator("#ask-chips .chip").all()]
    assert first not in suggested and len(suggested) == 3
    assert not errors


# --- thin real data: an empty card is hidden, never a dash, an error or a guess -----------------


def test_a_player_without_numbers_shows_no_dashes_heat_map_or_error_and_his_chip_dims(browser, site):  # noqa: F811
    """The cut clip's tracks have no player card in the mock feed, as a real track fragment can
    have none: the sheet keeps its name and hides what it cannot fill."""
    laptop, page, errors = phone(browser, site, laptop_t=1505 / FPS)
    tap_player(page)
    page.wait_for_timeout(300)  # the card request has failed by now
    assert page.locator("#so-far-box").is_hidden() and page.locator("#heat-box").is_hidden()
    chips = page.locator("#compare-chips button")
    assert 0 < chips.count() <= 22  # who is on the pitch now, never every fragment
    chips.first.click()
    page.wait_for_selector("#compare-chips button[aria-disabled=true]")
    assert page.locator("#compare-rows").is_hidden()
    assert "Could not" not in page.inner_text("#player")
    assert not errors


def test_the_band_is_crests_and_names_with_no_score_and_no_scorer_lines_before_a_goal(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, laptop_t=1505 / FPS)
    page.wait_for_selector(".band .home-name")
    goals = json.loads(page.evaluate("fetch('/bundle/match.json').then(r => r.text())"))["goals"]
    assert not [g for g in goals if g["t"] <= 1505 / FPS]
    assert page.locator(".side-goal").count() == 0 and "%" not in page.inner_text(".band")
    assert page.locator("#teams-note").is_hidden()  # the clip names both clubs
    assert not errors


def test_a_bundle_that_names_no_clubs_shows_neutral_sides_and_says_teams_are_not_confirmed(browser, site):  # noqa: F811
    ctx = browser.new_context(viewport=PHONE_SIZE, has_touch=True)

    def no_teams(route):
        body = route.fetch().json()
        body.pop("teams", None)
        route.fulfill(json=body)

    ctx.route("**/bundle/manifest.json", no_teams)
    laptop = ctx.new_page()
    laptop.goto(f"{site}phone/mock-laptop.html?code={MOCK_CODE}")
    page = ctx.new_page()
    errors = watch(page)
    page.goto(f"{site}phone/?mock=1&code={MOCK_CODE}&clip=mock&bundle=/bundle/")
    page.wait_for_selector("#teams-note:not([hidden])")
    assert page.inner_text(".band .home-name") == "Home" and page.inner_text(".band .away-name") == "Away"
    assert page.get_attribute("#goals-home", "aria-label") == "Home goals"  # the clubs on screen
    assert "London" not in page.inner_text(".band") and "Lisbon" not in page.inner_text(".band")
    assert not errors


def test_a_row_where_neither_club_has_any_yet_is_a_grey_track(browser, site):  # noqa: F811
    ctx = browser.new_context(viewport=PHONE_SIZE, has_touch=True)

    def no_shots(route):
        body = route.fetch().json()
        for s in body["stats"]:
            for side in ("home", "away"):
                s[side]["shots"] = s[side]["shots_on_target"] = 0
        route.fulfill(json=body)

    ctx.route("**/bundle/match.json", no_shots)
    laptop = ctx.new_page()
    laptop.goto(f"{site}phone/mock-laptop.html?code={MOCK_CODE}")
    laptop.fill("#seek", "62.8")
    page = ctx.new_page()
    errors = watch(page)
    page.goto(f"{site}phone/?mock=1&code={MOCK_CODE}&clip=mock&bundle=/bundle/")
    page.click("#lt-stats")
    page.wait_for_selector("#live-stats:not([hidden]) .stat-row")
    rows = page.locator("#stat-rows .stat-row")
    empty = {}
    for i in range(rows.count()):
        row = rows.nth(i)
        empty[row.get_attribute("aria-label").split(":")[0]] = "empty" in row.get_attribute("class").split()
    assert empty["Shots seen"] and empty["Shots on target seen"] and not empty["Passes completed"]
    assert not errors


def test_the_play_by_play_names_a_club_only_for_a_side_told_surely(browser, site):  # noqa: F811
    # Merge-queue review of #319: an event with no player was said as its club from its own team
    # field, whatever its side confidence. Now only above the fact-checker's threshold.
    laptop, page, errors = phone(browser, site, laptop_t=62.8)
    open_story(page)
    page.wait_for_selector("#insights .play")
    plays = {li.get_attribute("data-event"): (li.inner_text(), li.get_attribute("class"))
             for li in page.locator("#insights .play").all()}
    assert "Crowmere completes a pass." in plays["e5"][0] and "home" in plays["e5"][1].split()
    assert "A player completes a pass." in plays["e6"][0] and "neutral" in plays["e6"][1].split()
    assert not errors


def test_a_bundle_that_does_not_carry_the_threshold_names_no_detected_side(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, laptop_t=62.8)
    manifest = json.loads(page.evaluate("fetch('/bundle/manifest.json').then(r => r.text())"))
    del manifest["min_team_confidence"]
    page.context.route("**/bundle/manifest.json", lambda route: route.fulfill(json=manifest))
    page.reload()
    page.wait_for_selector("body[data-state=live]")
    open_story(page)
    page.wait_for_selector("#insights .play")
    told = page.locator("#insights .play[data-event=e5]").inner_text()
    assert "A player completes a pass." in told  # fail closed: e5's 0.99 counts for nothing without it
    assert not errors


def test_a_goal_on_an_unsure_side_is_a_goal_for_no_club(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, laptop_t=62.8)
    match = json.loads(page.evaluate("fetch('/bundle/match.json').then(r => r.text())"))
    match["goals"] = [{"t": 61.0, "team": None, "event": "e6"}]  # condensed.build: an unsure side, no player
    page.context.route("**/bundle/match.json", lambda route: route.fulfill(json=match))
    page.reload()
    page.wait_for_selector("body[data-state=live]")
    page.wait_for_selector("#goals-unsure .side-goal")
    assert page.inner_text("#goals-unsure .side-goal") == "Goal 2′"  # under the clock, under no club
    assert page.locator("#goals-home .side-goal, #goals-away .side-goal").count() == 0
    assert not errors


# --- density (Kian, Oct 24): one scroll packed with cards, each hidden while it has nothing --------


def test_live_is_one_feed_in_apple_sports_order_and_see_all_opens_the_full_section(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, laptop_t=62.8)
    # Without a persona (#362's choices) the focus strips are no cards; the feed is Apple Sports' order.
    sections = "#pane-pitch > section:not(.focus-strip)"
    js = f"[...document.querySelectorAll('{sections}')].map(s => s.id || s.className)"
    order = page.evaluate(js)
    assert order == ["card pitch-card", "just-now", "momentum", "live-summary", "live-shots", "key-moments",
                     "lineups-teaser"]
    page.wait_for_selector("#live-summary:not([hidden])")
    page.click("#live-summary .see-all")
    assert page.get_attribute("#lt-stats", "aria-selected") == "true" and page.is_visible("#live-stats")
    assert not errors


def test_key_moments_on_live_are_the_newest_moments_and_see_all_opens_story(browser, cards_site):  # noqa: F811
    url, _ = cards_site
    laptop, page, errors = phone(browser, url, laptop_t=63)
    page.wait_for_selector("#key-moments:not([hidden])")
    rows = page.locator("#key-rows .moment-row")
    assert rows.first.locator(".text").inner_text() == "Crowmere overload late"  # newest first
    assert rows.first.locator(".min").inner_text() == "2′"
    page.click("#key-moments .see-all")
    page.wait_for_selector("#panel-insights:not(.tab-hidden) #insights .moment")
    assert not errors


def test_players_shows_the_pass_network_and_top_performers_only_from_the_match_s_numbers(browser, site):  # noqa: F811
    ctx = browser.new_context(viewport=PHONE_SIZE, has_touch=True)

    def squads(route):
        body = route.fetch().json()
        body.pop("sheets", None)  # the bundle's own fictional sheets would list eleven shirts
        body["lineup"] = [{"id": "h-t1", "number": 4, "confident": True},
                          {"id": "a-t3", "number": 9, "confident": True}]
        body["player_stats"] = [{"id": "h-t1", "distance_km": 6.2, "top_speed_kmh": 30.1, "involvements": 12},
                                {"id": "a-t3", "distance_km": 7.4, "top_speed_kmh": None, "involvements": 20}]
        # The Scout's block (#338): the network's nodes are the players' names, as the video named them.
        body["insight_stats"] = {"bin_min": 5, "rows": [], "pass_network": {
            side: {"named_passes_only": True, "nodes": [{"id": f"{p} Keeper", "x": 30, "y": 30, "passes": 10},
                             {"id": f"{p} Nine", "x": 50, "y": 40, "passes": 8}],
                   "links": [{"a": f"{p} Keeper", "b": f"{p} Nine", "n": 6}]}
            for side, p in (("home", "Abel"), ("away", "Bruno"))}}
        route.fulfill(json=body)

    ctx.route("**/bundle/match.json", squads)
    laptop = ctx.new_page()
    laptop.goto(f"{site}phone/mock-laptop.html?code={MOCK_CODE}")
    page = ctx.new_page()
    errors = watch(page)
    page.goto(f"{site}phone/?mock=1&code={MOCK_CODE}&clip=mock&bundle=/bundle/")
    page.wait_for_selector("#lineups-teaser:not([hidden])")  # Live's teaser: the shirts the sheet is sure of
    assert page.inner_text("#teaser-rows .teaser.home .teaser-shirts") == "4"
    page.click("#lt-players")
    page.wait_for_selector("#top-players:not([hidden])")
    lists = page.locator("#top-lists .top-list")
    titles = [lists.nth(i).locator("h3").text_content() for i in range(lists.count())]
    assert titles == ["Distance", "Top speed", "Most involved"]
    assert lists.nth(1).locator("li").count() == 1  # a top speed not measured is not listed
    assert page.locator("#network .node").count() == 2 and page.locator("#network .link").count() == 1
    assert page.inner_text("#network-rows .who-name >> nth=0") == "Abel Keeper and Abel Nine"
    assert "6 passes" in page.inner_text("#network-rows")
    page.click("#network-side ion-segment-button[value=away]")  # the other club's network
    page.wait_for_function("document.querySelector('#network-rows').textContent.includes('Bruno')")
    assert page.locator("#network .node.away").count() == 2
    assert page.is_visible("#network-named")  # said so, as the Scout's named_passes_only asks
    assert not errors
    ctx.close()


def test_a_match_without_squad_numbers_shows_no_empty_squad_cards(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, laptop_t=62.8)
    page.click("#lt-players")
    assert page.is_hidden("#pass-network") and page.is_hidden("#top-players")
    assert not errors


def test_ask_opens_on_a_grid_of_questions_then_recent_answers(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False, laptop_t=60)
    page.click("#tab-button-ask")
    page.click(".onboard-skip")  # a first visit opens on the onboarding (tests/test_phone_onboarding.py)
    page.wait_for_selector("#ask-start:visible")
    assert page.locator("#ask-grid .chip").count() >= 4
    assert page.is_hidden("#ask-chips") and page.is_hidden("#recent-title")  # one set of suggestions
    page.locator("#ask-grid .chip").first.click()
    page.wait_for_selector("#answers .answer:not(.pending)")
    assert page.is_hidden("#ask-start") and page.is_visible("#recent-title")
    assert not errors


def test_the_stats_period_toggle_shows_a_half_on_its_own_only_when_the_scout_wrote_halves(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, laptop_t=62.8)
    page.click("#lt-stats")
    assert page.is_hidden("#stats-period")  # no halves in this bundle: no toggle
    page.context.close()
    ctx = browser.new_context(viewport=PHONE_SIZE, has_touch=True)

    def halves(route):
        body = route.fetch().json()
        row = {"group": "Pressing", "key": "turnovers", "label": "Turnovers", "unit": "turnovers"}
        first = {"minute_from": 1, "minute_to": 45,
                 "rows": [{**row, "home": 7, "away": 3, "confident": True}]}
        body["insight_stats"] = {"bin_min": 5, "rows": [], "halves": {"first": first}}
        route.fulfill(json=body)

    ctx.route("**/bundle/match.json", halves)
    laptop = ctx.new_page()
    laptop.goto(f"{site}phone/mock-laptop.html?code={MOCK_CODE}")
    laptop.fill("#seek", "62.8")
    page = ctx.new_page()
    errors = watch(page)
    page.goto(f"{site}phone/?mock=1&code={MOCK_CODE}&clip=mock&bundle=/bundle/")
    page.click("#lt-stats")
    page.wait_for_selector("#stats-period:not([hidden])")
    assert page.is_hidden("#stats-period ion-segment-button[value=second]")  # before minute 46
    page.click("#stats-period ion-segment-button[value=first]")
    page.wait_for_function("document.querySelectorAll('#stat-rows .stat-row').length === 1")
    assert page.get_attribute("#stat-rows .stat-row", "aria-label") == "Turnovers: Crowmere 7, Dunhollow 3"
    assert page.locator("#summary-rows .stat-row").count() > 1  # Live's summary stays the whole match
    page.click("#stats-period ion-segment-button[value=match]")
    page.wait_for_function("document.querySelectorAll('#stat-rows .stat-row').length > 1")
    assert not errors
    ctx.close()


def test_live_s_shot_card_draws_only_shots_on_a_side_told_surely(browser, site):  # noqa: F811
    """e2 is on a side told surely, e7 on one that was not: Live draws e2 only, as Stats does."""
    laptop, page, errors = phone(browser, site, laptop_t=62.8)
    page.wait_for_selector("#live-shots:not([hidden])")
    assert page.locator("#live-shots-svg circle.shot").count() == 1
    assert page.locator("#shots circle.shot").count() == 1  # the Stats map agrees
    assert not errors


def test_a_key_moment_goal_on_an_unsure_side_carries_no_club_s_colour(browser, site):  # noqa: F811
    ctx = browser.new_context(viewport=PHONE_SIZE, has_touch=True)

    def unsure_goal(route):
        rows = [json.loads(line) for line in route.fetch().text().splitlines() if line.strip()]
        rows = [{**r, "outcome": "goal"} if r["id"] == "e7" else r for r in rows]
        route.fulfill(body="".join(json.dumps(r) + "\n" for r in rows), content_type="application/x-ndjson")

    ctx.route("**/bundle/events.jsonl", unsure_goal)
    laptop = ctx.new_page()
    laptop.goto(f"{site}phone/mock-laptop.html?code={MOCK_CODE}")
    laptop.fill("#seek", "62.8")
    page = ctx.new_page()
    errors = watch(page)
    page.goto(f"{site}phone/?mock=1&code={MOCK_CODE}&clip=mock&bundle=/bundle/")
    page.wait_for_selector("#key-moments:not([hidden]) .moment-row.goal")
    row = page.locator("#key-rows .moment-row.goal").first
    assert "neutral" in row.get_attribute("class").split()  # not the tracker's side vote
    assert not errors
    ctx.close()


# How a scoreline or a goal count is written: "2 – 1", "2-1", "2 · 1", "2:1" (a clock is m:ss, so a
# colon needs one digit after it), "3 goals", or the words of a score.
SCORELINE = re.compile(r"\b\d{1,2}\s*[-–·]\s*\d{1,2}\b|\b\d{1,2}:\d\b|\b\d+ goals?\b"
                       r"|\b(ahead|level|leads|leading)\b", re.I)


def test_no_scoreline_from_detected_goals_shows_anywhere_on_the_phone(browser, site):  # noqa: F811
    """Kian, Oct 25: vision finds 2 of the demo's 3 goals, so a score counted from them would
    contradict the broadcast's scorebug. Three detected goals here (two home, one away): no text and
    no accessible name on any screen counts them."""
    ctx = browser.new_context(viewport=PHONE_SIZE, has_touch=True)

    def goals(route):  # e2 (home, told surely) went in, and two goals more
        if route.request.url.endswith("match.json"):
            body = route.fetch().json()
            body["goals"] = [{"t": 61.2, "team": "home", "event": "e2"},
                             {"t": 61.9, "team": "home", "event": "e2"},
                             {"t": 62.4, "team": "away", "event": "e4"}]
            return route.fulfill(json=body)
        rows = [json.loads(line) for line in route.fetch().text().splitlines() if line.strip()]
        rows = [{**r, "outcome": "goal"} if r["id"] == "e2" else r for r in rows]
        route.fulfill(body="".join(json.dumps(r) + "\n" for r in rows), content_type="application/x-ndjson")

    ctx.route("**/bundle/match.json", goals)
    ctx.route("**/bundle/events.jsonl", goals)
    laptop = ctx.new_page()
    laptop.goto(f"{site}phone/mock-laptop.html?code={MOCK_CODE}")
    laptop.fill("#seek", "63")
    page = ctx.new_page()
    errors = watch(page)
    page.goto(f"{site}phone/?mock=1&code={MOCK_CODE}&clip=mock&bundle=/bundle/")
    page.wait_for_selector("#goals-home .side-goal")
    page.wait_for_selector("#goals-away .side-goal")
    assert page.inner_text("#goals-home .side-goal").endswith(" 2′")  # under the club's crest
    assert "%" not in page.inner_text(".band")  # the confidence lives behind a tap
    page.click("#goals-home .side-goal")
    page.wait_for_function("(document.querySelector('#how-body')?.textContent || '').includes('% sure')")
    assert "The score is the broadcast's" in page.inner_text("#how-body")
    page.click("#close-how")
    # No scorebug reading in this bundle: no numerals, whatever the goals (#356 is the only source).
    assert page.locator("#score-home:visible, #score-away:visible, .mh, .ma, .tally").count() == 0
    # Every screen's text and every accessible name, the shot map's and Live's shot card's among them.
    js = """() => [document.body.innerText,
        ...[...document.querySelectorAll('[aria-label]')].map((el) => el.getAttribute('aria-label')),
        ...[...document.querySelectorAll('.sr-only')].map((el) => el.textContent)]"""
    screens = (("radar", "pitch"), ("radar", "stats"), ("radar", "players"),
               ("insights", None), ("ask", None))
    for tab, pane in screens:
        page.click(f"#tab-button-{tab}")
        if pane:
            page.click(f"#lt-{pane}")
        page.wait_for_timeout(300)
        for text in page.evaluate(js):
            hit = SCORELINE.search(text or "")
            assert not hit, (tab, pane, hit.group(0), (text or "")[max(0, hit.start() - 60):hit.end() + 60])
    open_story(page)
    assert page.locator("#insights .goal-card, #insights .play.goal").count() >= 1  # no running score
    assert not errors
    ctx.close()


def test_an_answer_about_the_score_never_shows_a_count(browser, site):  # noqa: F811
    """#350 sends no score metric; should one come, the phone still prints no count from it."""
    laptop, page, errors = phone(browser, site, bundle=False, laptop_t=60)
    page.click("#tab-button-ask")
    page.evaluate("""() => window.ninetyPhone.answer("What's the score?", {status: "verified",
      text: "The broadcast's scorebug shows the score; vision does not keep one.", metric: "score", value: 2,
      unit: "goals", evidence: ["score:all"], t_from: 0, t_to: 60})""")
    page.wait_for_selector("#answers .answer:not(.pending) .how")
    page.locator("#answers .how").first.click()  # How we know: What and Over
    page.wait_for_selector("#how-body .evidence dd")
    what = page.locator("#how-body .evidence dd").first.text_content()
    assert not re.search(r"\d", what), what
    assert not errors



def test_a_scorer_vision_could_not_name_is_his_club_s_goal_never_a_track_id(browser, site):  # noqa: F811
    """video-prep, Oct 25: the scorer lines read "Player 7240 22′". A tracked scorer nobody names is
    his club's goal; the shot list says the club; no screen shows the tracker's number."""
    ctx = browser.new_context(viewport=PHONE_SIZE, has_touch=True)

    def goal(route):
        if route.request.url.endswith("match.json"):
            body = route.fetch().json()
            body["goals"] = [{"t": 61.2, "team": "home", "event": "e2"}]
            return route.fulfill(json=body)
        rows = [json.loads(line) for line in route.fetch().text().splitlines() if line.strip()]
        rows = [{**r, "outcome": "goal", "player": "h-t7240"} if r["id"] == "e2" else r for r in rows]
        route.fulfill(body="".join(json.dumps(r) + "\n" for r in rows), content_type="application/x-ndjson")

    ctx.route("**/bundle/match.json", goal)
    ctx.route("**/bundle/events.jsonl", goal)
    laptop = ctx.new_page()
    laptop.goto(f"{site}phone/mock-laptop.html?code={MOCK_CODE}")
    laptop.fill("#seek", "63")
    page = ctx.new_page()
    errors = watch(page)
    page.goto(f"{site}phone/?mock=1&code={MOCK_CODE}&clip=mock&bundle=/bundle/")
    page.wait_for_selector("#goals-home .side-goal")
    assert page.inner_text("#goals-home .side-goal") == "Crowmere goal 2′"
    for tab in ("radar", "insights"):
        page.click(f"#tab-button-{tab}")
        page.wait_for_timeout(300)
        assert "7240" not in page.evaluate("document.body.innerText"), tab
    assert not errors
    ctx.close()


def test_unnamed_players_read_apart_and_a_button_s_name_contains_what_it_shows(browser, site):  # noqa: F811
    """Merge-queue review of #371 (WCAG 2.5.3): with track numbers gone, every unnamed player was
    "London player" or "A player" in a screen reader's ear while the screen showed where he plays."""
    laptop, page, errors = phone(browser, site, laptop_t=1505 / FPS)
    tap_player(page)
    chips = [c.inner_text() for c in page.locator("#compare-chips button").all()]
    bare = {"A player", "Crowmere player", "Dunhollow player"}
    assert chips and not bare & set(chips), chips
    assert len(set(chips)) == len(chips), chips  # one chip a label (UI inventory #11)
    assert not errors


def scorebug_phone(browser, site, readings, goals, measured=True, at="61", more=None):  # noqa: F811
    """The cut clip's bundle with the scorebug's readings (#356's scorebug.jsonl, behind the
    manifest's gate, as ninety-e2e --scorebug writes it) and these detected goals."""
    ctx = browser.new_context(viewport=PHONE_SIZE, has_touch=True)

    def manifest(route):
        body = route.fetch().json()
        body["scorebug"] = {"readings": len(readings), "measured": measured, "min_confidence": 0.5}
        route.fulfill(json=body)

    def match(route):
        body = route.fetch().json()
        body["goals"] = goals
        body.update(more or {})
        route.fulfill(json=body)

    ctx.route("**/bundle/manifest.json", manifest)
    ctx.route("**/bundle/match.json", match)
    body = "".join(json.dumps(e) + "\n" for e in readings)
    ctx.route("**/bundle/scorebug.jsonl", lambda r: r.fulfill(body=body))
    laptop = ctx.new_page()
    laptop.goto(f"{site}phone/mock-laptop.html?code={MOCK_CODE}")
    laptop.fill("#seek", at)
    page = ctx.new_page()
    errors = watch(page)
    page.goto(f"{site}phone/?mock=1&code={MOCK_CODE}&clip=mock&bundle=/bundle/")
    page.wait_for_selector("body[data-state=live]")
    return ctx, laptop, page, errors


def reading(t, kind, home, away, team=None, confidence=0.95):
    """One line of #356's scorebug.jsonl: a start reading (score_read) or a change (score_change, +1
    on its side)."""
    return {"id": f"s{int(t * 100):06d}", "t": t, "frame": int(t * 25), "type": kind, "team": team,
            "player": None, "x": 52.5, "y": 34.0, "source": "vision", "confidence": confidence,
            "score": {"home": home, "away": away}}


def test_the_score_shows_only_as_read_off_the_broadcast_scorebug_never_from_goal_counts(browser, site):  # noqa: F811
    """#356: a scoreline only from the scorebug's readings. Three goals detected (two home, one away),
    but the scorebug reads 0-0 from kick-off and 0-1 from 61.5 s: the band shows 0 0, then 0 1."""
    goals = [{"t": 61.2, "team": "home", "event": "e2"}, {"t": 61.3, "team": "home", "event": "e2"},
             {"t": 61.4, "team": "away", "event": "e4"}]
    readings = [reading(60.0, "score_read", 0, 0), reading(61.5, "score_change", 0, 1, team="away")]
    ctx, laptop, page, errors = scorebug_phone(browser, site, readings, goals)
    page.wait_for_selector("#score-home:visible")
    page.wait_for_function("document.querySelector('#score-home').textContent === '0'")
    assert page.text_content("#score-away") == "0"  # two goals detected by 61 s; the scorebug says 0-0
    laptop.fill("#seek", "63")
    page.wait_for_function("document.querySelector('#score-away').textContent === '1'")
    assert page.text_content("#score-home") == "0"  # never 2, the count of detected home goals
    assert "read from the broadcast's score graphic" in page.text_content("#score-read")
    page.click("#score-home")
    page.wait_for_function("(document.querySelector('#how-body')?.textContent || '').includes('graphic')")
    assert not errors
    ctx.close()


def test_a_goal_vision_gave_no_side_goes_under_the_club_whose_scorebug_count_rose(browser, site):  # noqa: F811
    """Demo audit row 3: every detected goal had team null and sat under neither club. The scorebug
    (the broadcast's own graphic, read from pixels) changed for one side 0.2 to 1.6 s after each:
    the goal goes under that club, and the numerals follow the scorebug, from its 0-0 start reading."""
    readings = [reading(60.0, "score_read", 0, 0), reading(61.9, "score_change", 0, 1, team="away")]
    sideless = [{"t": 61.2, "team": None, "event": "e6"}]
    ctx, laptop, page, errors = scorebug_phone(browser, site, readings, sideless, at="61.6")
    page.wait_for_function("document.querySelector('#score-away').textContent === '0'")
    # With readings, the lines are the scorebug's goals (they agree with the numerals): none at 0-0.
    assert page.locator(".side-goal").count() == 0
    laptop.fill("#seek", "63")
    page.wait_for_function("document.querySelector('#score-away').textContent === '1'")
    assert page.text_content("#score-home") == "0"
    page.wait_for_selector("#goals-away .side-goal")
    assert page.inner_text("#goals-away .side-goal") == "Dunhollow 2′"  # the club, the minute it rose
    assert page.locator("#goals-unsure .side-goal, #goals-home .side-goal").count() == 0
    assert not errors
    ctx.close()


def test_the_band_lists_every_goal_the_scorebug_counted_so_the_lines_agree_with_the_score(browser, site):  # noqa: F811
    """Coordinator, Oct 26: the band read 3-1 over one line each. Every rise in a side's count is a goal
    under its crest, in minutes ("2′ 2′"), whether or not vision spotted it; a jump of two is two."""
    readings = [reading(60.0, "score_read", 0, 0), reading(61.9, "score_change", 1, 0, team="home"),
                reading(62.5, "score_change", 3, 0, team="home"),
                reading(62.8, "score_change", 3, 1, team="away")]
    ctx, laptop, page, errors = scorebug_phone(browser, site, readings, [], at="63")
    page.wait_for_function("document.querySelector('#score-home').textContent === '3'")
    page.wait_for_selector("#goals-away .side-goal")
    assert page.inner_text("#goals-home .side-goal") == "Crowmere 2′ 2′ 2′"  # 61.9 s, and two at 62.5 s
    assert page.inner_text("#goals-away .side-goal") == "Dunhollow 2′"
    assert not errors
    ctx.close()


def test_an_unmeasured_scorebug_reader_shows_no_score_and_places_no_goal(browser, site):  # noqa: F811
    """The Companion's gate (scoring.SCOREBUG_MEASURED), carried by the bundle: until the reader is
    measured, no numerals, and a sideless goal stays under the clock."""
    readings = [reading(60.0, "score_read", 0, 0), reading(61.9, "score_change", 0, 1, team="away")]
    sideless = [{"t": 61.2, "team": None, "event": "e6"}]
    ctx, laptop, page, errors = scorebug_phone(browser, site, readings, sideless, measured=False, at="63")
    page.wait_for_selector("#goals-unsure .side-goal")
    assert page.locator("#score-home:visible, #score-away:visible").count() == 0
    assert page.locator("#goals-away .side-goal").count() == 0
    assert not errors
    ctx.close()


def test_a_low_confidence_or_falling_scorebug_reading_is_never_shown(browser, site):  # noqa: F811
    """A reading below the fact-checker's confidence is skipped, and so is one that takes a goal away
    (a misread): the band stays at the last sound reading."""
    readings = [reading(60.0, "score_read", 0, 0),
                reading(60.8, "score_change", 1, 0, team="home", confidence=0.2),
                reading(61.2, "score_change", 0, 1, team="away"), reading(62.0, "score_read", 0, 0)]
    ctx, laptop, page, errors = scorebug_phone(browser, site, readings, [], at="63")
    page.wait_for_function("document.querySelector('#score-away').textContent === '1'")
    assert page.text_content("#score-home") == "0"  # never the 0.2 reading's 1, never back to 0-0
    assert not errors
    ctx.close()
def test_a_shot_whose_end_vision_did_not_read_is_said_as_taken_never_wide(browser, site):  # noqa: F811
    """#368: a detected save is written as a shot with outcome null (saves are not read from video).
    The phone says only that it was taken, and marks it apart on the shot map, never as wide."""
    ctx = browser.new_context(viewport=PHONE_SIZE, has_touch=True)

    def unread(route):
        rows = [json.loads(line) for line in route.fetch().text().splitlines() if line.strip()]
        rows = [{**r, "outcome": None} if r["id"] == "e2" else r for r in rows]
        route.fulfill(body="".join(json.dumps(r) + "\n" for r in rows), content_type="application/x-ndjson")

    ctx.route("**/bundle/events.jsonl", unread)
    laptop = ctx.new_page()
    laptop.goto(f"{site}phone/mock-laptop.html?code={MOCK_CODE}")
    laptop.fill("#seek", "62.8")
    page = ctx.new_page()
    errors = watch(page)
    page.goto(f"{site}phone/?mock=1&code={MOCK_CODE}&clip=mock&bundle=/bundle/")
    page.wait_for_selector("body[data-state=live]")
    page.click("#lt-stats")
    page.wait_for_selector("#shots circle.shot.open", state="attached")  # a small mark
    assert page.locator("#shots circle.shot.off").count() == 0  # e2 is the clip's one sure shot
    open_story(page)
    page.wait_for_selector("#insights .play[data-event=e2]")
    said = page.inner_text("#insights .play[data-event=e2]")
    assert "takes a shot." in said and "wide" not in said
    assert not errors
    ctx.close()


def test_a_saved_shot_by_a_player_vision_cannot_name_reads_lower_case_mid_sentence(browser, site):  # noqa: F811
    """Demo audit, Oct 25: "Shot saved, from A player." The unnamed player is 'a player' mid-sentence."""
    ctx = browser.new_context(viewport=PHONE_SIZE, has_touch=True)

    def saved(route):
        rows = [json.loads(line) for line in route.fetch().text().splitlines() if line.strip()]
        unsure = {"outcome": "on_target", "player": None, "team_confidence": 0.1}
        rows = [{**r, **unsure} if r["id"] == "e2" else r for r in rows]
        route.fulfill(body="".join(json.dumps(r) + "\n" for r in rows), content_type="application/x-ndjson")

    ctx.route("**/bundle/events.jsonl", saved)
    laptop = ctx.new_page()
    laptop.goto(f"{site}phone/mock-laptop.html?code={MOCK_CODE}")
    laptop.fill("#seek", "62.8")
    page = ctx.new_page()
    errors = watch(page)
    page.goto(f"{site}phone/?mock=1&code={MOCK_CODE}&clip=mock&bundle=/bundle/")
    page.wait_for_selector("body[data-state=live]")
    open_story(page)
    page.wait_for_selector("#insights .play[data-event=e2]")
    assert "Shot saved, from a player." in page.inner_text("#insights .play[data-event=e2]")
    assert not errors
    ctx.close()


def test_players_is_the_team_sheet_eleven_a_side_and_never_lists_a_track(browser, site):  # noqa: F811
    """Demo audit: Players listed track fragments (12 London, 6 centre forwards, Lisbon with no keeper).
    With the team sheet (match.json `sheets`, names-by-role), it lists each club's eleven: shirt, name,
    position. Without one, a tracked player is never listed as a player."""
    # The bundle now carries team sheets (ninety-e2e writes fictional ones, #374): drop them here.
    laptop, page, errors = phone(browser, site, laptop_t=1505 / FPS, match=lambda b: b.pop("sheets", None))
    page.wait_for_selector("#lt-players", state="hidden")  # nothing to list: no tab (audit 2, row 1)
    assert page.locator("#roster .who").count() == 0  # the cut clip has tracks only and no sheet
    page.context.close()
    ctx = browser.new_context(viewport=PHONE_SIZE, has_touch=True)
    lines = ["goalkeeper"] + ["defender"] * 4 + ["midfielder"] * 3 + ["forward"] * 3
    sheet = {side: [{"number": n + 1, "name": f"{side.title()} Player{n + 1}", "position": line, "line": line}
                    for n, line in enumerate(lines)] for side in ("home", "away")}

    def match(route):
        body = route.fetch().json()
        body["sheets"] = sheet
        route.fulfill(json=body)

    ctx.route("**/bundle/match.json", match)
    laptop = ctx.new_page()
    laptop.goto(f"{site}phone/mock-laptop.html?code={MOCK_CODE}")
    page = ctx.new_page()
    errors = watch(page)
    page.goto(f"{site}phone/?mock=1&code={MOCK_CODE}&clip=mock&bundle=/bundle/")
    page.wait_for_selector("body[data-state=live]")
    page.click("#lt-players")
    page.wait_for_selector("#roster .who.sheet")
    for side in ("home", "away"):
        rows = page.locator(f"#roster .who.sheet.{side}")
        assert rows.count() == 11
        assert rows.first.locator(".num").inner_text() == "1"
        assert rows.first.locator(".name").inner_text() == f"{side.title()} Player1"
        assert rows.first.locator(".where").inner_text() == "Goalkeeper"
    assert page.locator("#roster .lineup-pitch .shirt").count() == 22
    assert not errors
    ctx.close()


def test_a_line_up_name_labels_the_event_s_track_never_the_radar_s_same_string(browser, site):  # noqa: F811
    """names-by-role, Oct 25: the line-up names BROADCAST tracks (events, highlights); the radar and the
    player card use TACTICAL tracks, and the same string can be another man. a-t3 is named in the
    line-up: his detected pass says the name, while the radar's a-t3 stays his club's player."""
    ctx = browser.new_context(viewport=PHONE_SIZE, has_touch=True)

    def match(route):
        body = route.fetch().json()
        named = {"id": "a-t3", "name": "Dee Named", "number": 9, "position": "striker", "confident": True}
        body["lineup"] = [named]
        route.fulfill(json=body)

    ctx.route("**/bundle/match.json", match)
    laptop = ctx.new_page()
    laptop.goto(f"{site}phone/mock-laptop.html?code={MOCK_CODE}")
    laptop.fill("#seek", str(round(1505 / FPS, 1)))
    page = ctx.new_page()
    errors = watch(page)
    page.goto(f"{site}phone/?mock=1&code={MOCK_CODE}&clip=mock&bundle=/bundle/")
    page.wait_for_selector("body[data-state=live]")
    page.wait_for_function("window.ninetyPhone.state.match !== null")  # the line-up has loaded
    assert page.evaluate("window.ninetyPhone.name('a-t3')") == "Dunhollow player"  # the radar's a-t3
    laptop.fill("#seek", "63")
    open_story(page)
    page.wait_for_selector("#insights .play[data-event=e4]")
    assert "Dee Named" in page.inner_text("#insights .play[data-event=e4]")  # the event's a-t3
    assert not errors
    ctx.close()


def test_a_sheet_never_names_an_event_and_a_line_up_entry_without_confident_names_nobody(browser, site):  # noqa: F811
    """Merge-queue review of #376: the team sheet names nobody on the pitch (no line-up, or an entry
    that does not say it is confident), so the detected pass stays the club's player."""
    ctx = browser.new_context(viewport=PHONE_SIZE, has_touch=True)
    lines = ["goalkeeper"] + ["defender"] * 4 + ["midfielder"] * 3 + ["forward"] * 3
    sheet = {side: [{"number": n + 1, "name": f"{side.title()} Player{n + 1}", "position": line, "line": line}
                    for n, line in enumerate(lines)] for side in ("home", "away")}

    def match(route):
        body = route.fetch().json()
        body["sheets"] = sheet
        body["lineup"] = [{"id": "a-t3", "name": "Dee Named", "number": 9, "position": "striker"}]
        route.fulfill(json=body)

    ctx.route("**/bundle/match.json", match)
    laptop = ctx.new_page()
    laptop.goto(f"{site}phone/mock-laptop.html?code={MOCK_CODE}")
    laptop.fill("#seek", "63")
    page = ctx.new_page()
    errors = watch(page)
    page.goto(f"{site}phone/?mock=1&code={MOCK_CODE}&clip=mock&bundle=/bundle/")
    page.wait_for_selector("body[data-state=live]")
    page.wait_for_function("window.ninetyPhone.state.match !== null")
    open_story(page)
    page.wait_for_selector("#insights .play[data-event=e4]")
    said = page.inner_text("#insights .play[data-event=e4]")
    assert "Dee Named" not in said and "Player" not in said.replace("player", ""), said
    assert not errors
    ctx.close()


def test_story_opens_on_key_plays_and_each_goal_is_a_larger_card_with_its_club_and_minute(browser, site):  # noqa: F811
    """Demo audit 2, rows 8 and 10: goals had a pass's weight in Story, and the shot list said
    "A player, goal". Story opens on Key plays; each of the match's goals (match.json, reconciled with
    the scorebug) is a card with the club's crest, "Goal" and "Crowmere · 2′"; its shot is not told
    twice; and the shot list names the club and minute, a goal vision saw no shot for among them."""
    ctx = browser.new_context(viewport=PHONE_SIZE, has_touch=True)

    def goals(route):  # e2 (home, told surely) went in; an away goal vision saw no shot for
        if route.request.url.endswith("match.json"):
            body = route.fetch().json()
            body["goals"] = [{"t": 61.3, "team": "home", "event": "e2"},
                             {"t": 62.5, "team": "away", "event": "e4"}]
            return route.fulfill(json=body)
        rows = [json.loads(line) for line in route.fetch().text().splitlines() if line.strip()]
        rows = [{**r, "outcome": "goal"} if r["id"] == "e2" else r for r in rows]
        route.fulfill(body="".join(json.dumps(r) + "\n" for r in rows), content_type="application/x-ndjson")

    ctx.route("**/bundle/match.json", goals)
    ctx.route("**/bundle/events.jsonl", goals)
    laptop = ctx.new_page()
    laptop.goto(f"{site}phone/mock-laptop.html?code={MOCK_CODE}")
    laptop.fill("#seek", "63")
    page = ctx.new_page()
    errors = watch(page)
    page.goto(f"{site}phone/?mock=1&code={MOCK_CODE}&clip=mock&bundle=/bundle/")
    page.wait_for_selector("#goals-away .side-goal")
    page.click("#tab-button-insights")
    assert page.get_attribute("#insights", "data-mode") == "key"
    page.wait_for_selector("#insights .goal-card")
    cards = page.locator("#insights .goal-card")
    assert cards.count() == 2
    newest, first = cards.nth(0), cards.nth(1)
    assert newest.locator(".goal-head").inner_text().endswith("Goal")  # after the crest
    assert newest.locator(".goal-head svg").count() == 1
    assert "Dunhollow · 2′" in newest.inner_text() and "Crowmere · 2′" in first.inner_text()
    assert page.locator("#insights .play.goal").count() == 0  # e2's goal card tells it
    assert page.evaluate("getComputedStyle(document.querySelector('.goal-head')).fontSize") == "28px"
    page.click("#tab-button-radar")
    page.click("#lt-stats")
    shots = page.locator("#shot-list li").all_inner_texts()
    assert any(s.startswith("Crowmere · 2′, goal") for s in shots), shots
    assert "Dunhollow · 2′, goal" in shots, shots
    assert not errors
    ctx.close()


def test_live_s_team_stats_follow_the_clock_after_a_seek_made_while_on_another_tab(browser, site):  # noqa: F811
    """Demo audit 2, row 4: Live's Team Stats read 20/24 against 0 at 45′ while Stats read 67/80."""
    laptop, page, errors = phone(browser, site, laptop_t=60.4)
    page.wait_for_selector("#summary-rows .stat-row")
    rows = "s => [...document.querySelectorAll(s + ' .stat-row')].map((l) => l.getAttribute('aria-label'))"
    before = page.evaluate(rows, "#summary-rows")
    moved = f"({rows})('#summary-rows').join() !== {json.dumps(','.join(before))}"
    page.click("#tab-button-ask")
    laptop.fill("#seek", "63")
    page.wait_for_timeout(1500)
    page.click("#tab-button-radar")
    page.click("#lt-pitch")
    page.wait_for_function(moved)
    live = page.evaluate(rows, "#summary-rows")
    assert live == page.evaluate(rows, "#stat-rows")[: len(live)]
    assert not errors


def test_names_from_the_player_id_feed_label_tactical_tracks_and_say_their_source(browser, site):  # noqa: F811
    """Lesson 269 (identity-feed, Oct 26): `lineup_tactical` names the radar's, the card's and the
    answers' tracks; `lineup` the events'. The same string in the other space stays unnamed; a name
    says it came from the Player ID feed, never vision; a scorebug answer says so."""
    ctx = browser.new_context(viewport=PHONE_SIZE, has_touch=True)

    def match(route):
        body = route.fetch().json()
        body["lineup"] = []
        body["lineup_tactical"] = [{"id": "a-t3", "name": "Tac Named", "number": 9, "position": "Striker",
                                    "confident": True, "source": "id_feed"},
                                   {"id": "h-t4", "name": "Not Sure", "number": 4, "source": "id_feed"}]
        body["identity"] = {"source": "id_feed", "label": "Player ID feed", "provider": "sim",
                            "note": "Names come from a simulated tracking-provider ID feed."}
        route.fulfill(json=body)

    ctx.route("**/bundle/match.json", match)
    laptop = ctx.new_page()
    laptop.goto(f"{site}phone/mock-laptop.html?code={MOCK_CODE}")
    laptop.fill("#seek", "63")
    page = ctx.new_page()
    errors = watch(page)
    page.goto(f"{site}phone/?mock=1&code={MOCK_CODE}&clip=mock&bundle=/bundle/")
    page.wait_for_selector("body[data-state=live]")
    page.wait_for_function("window.ninetyPhone.state.match !== null")
    assert page.evaluate("window.ninetyPhone.name('a-t3')") == "Tac Named"  # the radar's a-t3
    assert page.evaluate("window.ninetyPhone.name('h-t4')") != "Not Sure"  # a row not marked confident
    open_story(page)
    page.wait_for_selector("#insights .play[data-event=e4]")
    assert "Tac Named" not in page.inner_text("#insights .play[data-event=e4]")  # the event's a-t3
    page.click("#tab-button-ask")
    page.evaluate("""() => window.ninetyPhone.answer("Who has the ball most?", {status: "verified",
      text: "a-t3 has been on the ball most.", headline: "Tac Named", metric: null, value: null, unit: null,
      evidence: ["involvements:player_a-t3"], t_from: 0, t_to: 63})""")
    named = page.locator("#answers .answer:not(.pending)").last
    named.wait_for()
    assert named.locator(".badge").text_content() == "Player ID feed"
    assert "Tac Named" in named.inner_text()
    named.locator(".how").click()
    page.wait_for_selector("#how-body .stepper")
    how = page.inner_text("#how-body")
    assert "Who the players are" in how and "Player ID feed" in how
    page.click("#close-how")
    page.evaluate("""() => window.ninetyPhone.answer("What's the score?", {status: "verified",
      text: "The broadcast's scorebug shows London 1, Lisbon 0.", metric: "scorebug", value: null, unit: null,
      evidence: ["scorebug:sb-3"], t_from: 0, t_to: 63})""")
    badges = page.locator("#answers .answer:not(.pending) .badge")
    page.wait_for_function("document.querySelectorAll('#answers .answer:not(.pending) .badge').length >= 2")
    assert badges.last.text_content() == "Read from the broadcast's scorebug"
    assert not errors
    ctx.close()


def test_the_shot_map_is_no_card_while_it_draws_no_shot(browser, site):  # noqa: F811
    """UI inventory #8: a shot is placed only on a side told surely; with none, the card was empty."""
    ctx = browser.new_context(viewport=PHONE_SIZE, has_touch=True)

    def unsure(route):
        rows = [json.loads(line) for line in route.fetch().text().splitlines() if line.strip()]
        rows = [{**r, "team_confidence": 0.3} if r["type"] == "shot" else r for r in rows]
        route.fulfill(body="".join(json.dumps(r) + "\n" for r in rows), content_type="application/x-ndjson")

    ctx.route("**/bundle/events.jsonl", unsure)
    laptop = ctx.new_page()
    laptop.goto(f"{site}phone/mock-laptop.html?code={MOCK_CODE}")
    laptop.fill("#seek", "63")
    page = ctx.new_page()
    errors = watch(page)
    page.goto(f"{site}phone/?mock=1&code={MOCK_CODE}&clip=mock&bundle=/bundle/")
    page.wait_for_selector("body[data-state=live]")
    page.wait_for_function("window.ninetyPhone.state.match !== null")
    page.click("#lt-stats")
    page.wait_for_selector("#live-stats:not([hidden])")
    assert page.is_hidden("#shot-map") and page.is_hidden("#live-shots")
    assert not errors
    ctx.close()


def persona_phone(browser, site, fan, goals=None, more=None):  # noqa: F811
    """The cut clip's phone as London v Lisbon, with #362's stored choices (`fan`) set before it loads."""
    ctx = browser.new_context(viewport=PHONE_SIZE, has_touch=True)
    ctx.add_init_script(f"localStorage.setItem('ninety.fan', {json.dumps(json.dumps(fan))})")

    def manifest(route):
        body = route.fetch().json()
        body["teams"] = {"home": "LON", "away": "LIS"}
        route.fulfill(json=body)

    def match(route):
        body = route.fetch().json()
        if goals is not None:
            body["goals"] = goals
        body.update(more or {})
        route.fulfill(json=body)

    ctx.route("**/bundle/manifest.json", manifest)
    ctx.route("**/bundle/match.json", match)
    laptop = ctx.new_page()
    laptop.goto(f"{site}phone/mock-laptop.html?code={MOCK_CODE}")
    laptop.fill("#seek", "63")
    page = ctx.new_page()
    errors = watch(page)
    page.goto(f"{site}phone/?mock=1&code={MOCK_CODE}&clip=mock&bundle=/bundle/")
    page.wait_for_selector("body[data-state=live]")
    page.wait_for_function("window.ninetyPhone.state.match !== null")
    page.wait_for_selector("#summary-rows .stat-row", state="attached")
    return ctx, page, errors


def top(page, sel):
    return page.locator(sel).bounding_box()["y"]


def test_casual_live_leads_with_moments_and_analyst_live_with_the_pitch_and_every_number(browser, site):  # noqa: F811
    """Kian, Oct 26 ("make personalisation more visible"): the same moment, two layouts at a glance."""
    goals = [{"t": 61.3, "team": "away", "event": "e2"}]
    fan = {"club": "LIS", "mode": "casual", "focus": "moments"}
    ctx, page, errors = persona_phone(browser, site, fan, goals)
    page.wait_for_selector("#key-moments:not([hidden])")
    assert page.evaluate("[document.body.dataset.mode, document.body.dataset.us]") == ["casual", "away"]
    assert top(page, "#key-moments") < top(page, ".pitch-card")  # moments first, the pitch at the foot
    assert page.is_hidden("#live-summary") and page.is_hidden("#momentum")  # fewer numbers
    assert "Lisbon goal" in page.inner_text("#key-rows")  # the club, in the third person (Kian, Oct 26)
    sides = page.locator(".band .fixture > .side")
    assert sides.nth(1).bounding_box()["x"] < sides.nth(0).bounding_box()["x"]  # your club on the left
    assert not errors
    ctx.close()
    fan = {"club": "LON", "mode": "analyst", "focus": "moments"}
    ctx, page, errors = persona_phone(browser, site, fan, goals)
    page.wait_for_selector("#live-summary:not([hidden])")
    assert top(page, ".pitch-card") < min(top(page, "#live-summary"), top(page, "#key-moments"))
    assert page.locator("#summary-rows .stat-row").count() == page.locator("#stat-rows .stat-row").count() > 4
    assert "Lisbon goal" in page.inner_text("#key-rows") and "You" not in page.inner_text("#key-rows")
    sides = page.locator(".band .fixture > .side")
    assert sides.nth(0).bounding_box()["x"] < sides.nth(1).bounding_box()["x"]
    assert not errors
    ctx.close()


def test_the_persona_switches_in_one_tap_from_the_more_sheet(browser, site):  # noqa: F811
    ctx, page, errors = persona_phone(browser, site, {"club": "LON", "mode": "casual", "focus": "tactics"})
    page.click(".settings-open >> nth=0")
    page.wait_for_selector("#persona-mode")
    page.click("#persona-mode ion-segment-button[value=analyst]")
    page.wait_for_function("document.body.dataset.mode === 'analyst'")
    page.click("#persona-club ion-segment-button[value=LIS]")
    page.wait_for_function("document.body.dataset.us === 'away'")
    saved = json.loads(page.evaluate("localStorage.getItem('ninety.fan')"))
    assert saved == {"club": "LIS", "mode": "analyst", "focus": "tactics"}  # #362's choices, kept
    assert not errors
    ctx.close()


def test_the_focus_leads_live_tactics_with_its_moments_and_players_with_their_cards(browser, site):  # noqa: F811
    """Coordinator, Oct 26: two analysts must not look alike. Tactics: the latest overload, line break
    and shape as large cards above the pitch. Players: the players most in the game, named by the ID
    feed, above the pitch; a tap opens his card."""
    ctx, page, errors = persona_phone(browser, site, {"club": "LON", "mode": "analyst", "focus": "tactics"})
    page.wait_for_selector("#tactics-strip .focus-row")
    assert page.is_hidden("#players-strip")
    assert top(page, "#tactics-strip") < top(page, ".pitch-card")
    kinds = page.locator("#tactics-strip .focus-label").all_inner_texts()
    assert len({k.split(" · ")[0] for k in kinds}) == len(kinds) <= 3, kinds  # one card a kind
    assert not errors
    ctx.close()
    more = {"lineup_tactical": [{"id": "a-t3", "name": "Tac Named", "number": 9, "position": "Striker",
                                 "confident": True, "source": "id_feed"}],
            "player_stats": [{"id": "a-t3", "involvements": 12}, {"id": "h-t4", "involvements": 7}]}
    fan = {"club": "LON", "mode": "analyst", "focus": "players"}
    ctx, page, errors = persona_phone(browser, site, fan, more=more)
    page.wait_for_selector("#players-strip .player-row")
    assert page.is_hidden("#tactics-strip")
    assert top(page, "#players-strip") < top(page, ".pitch-card")
    first = page.locator("#players-strip .player-row").first
    assert first.locator(".focus-text").inner_text() == "Tac Named"
    assert first.locator(".shirt-dot").inner_text() == "9"
    assert first.locator(".focus-label").inner_text() == "Striker · 12 involvements"
    # Apple Sports' restraint (Kian, Oct 26): 17 pt regular rows, 13 pt labels, no coloured borders.
    style = first.evaluate("""(b) => { const t = getComputedStyle(b.querySelector('.focus-text'));
      const l = getComputedStyle(b.querySelector('.focus-label'));
      return [t.fontSize, t.fontWeight, l.fontSize]; }""")
    assert style == ["17px", "400", "13px"], style
    first.click()
    page.wait_for_selector("#player:not([hidden])")
    assert page.inner_text("#player-title").startswith("Tac Named, #9 · Striker")
    assert not errors
    ctx.close()


def test_a_team_stats_row_on_fewer_than_ten_events_is_not_drawn(browser, site):  # noqa: F811
    """Coordinator, Oct 26 (inventory #7): counted only on sides told surely, a row of 0 and 1 says
    nothing; under MIN_ROW_EVENTS (10) events a row of counts is not drawn. The clip has a few."""
    ctx = browser.new_context(viewport=PHONE_SIZE, has_touch=True)
    laptop = ctx.new_page()
    laptop.goto(f"{site}phone/mock-laptop.html?code={MOCK_CODE}")
    laptop.fill("#seek", "63")
    page = ctx.new_page()
    errors = watch(page)
    page.add_init_script("delete window.__ninetyMinRowEvents")  # the phone's own threshold
    page.goto(f"{site}phone/?mock=1&code={MOCK_CODE}&clip=mock&bundle=/bundle/")
    page.wait_for_function("window.ninetyPhone.state.match !== null")
    page.wait_for_timeout(500)
    rows = "[...document.querySelectorAll('#stat-rows .stat-row')]"
    labels = page.evaluate(f"{rows}.map((l) => l.getAttribute('aria-label'))")
    assert not [x for x in labels if x.startswith(("Shots", "Passes", "Pass accuracy"))], labels
    assert not errors
    ctx.close()


def test_a_goal_under_the_score_names_its_scorer_from_the_player_id_feed(browser, site):  # noqa: F811
    """Kian, Oct 26: "Rondell 38′" where the player-ID feed names the scorer (#389's line-up of
    broadcast tracks), the club otherwise; never a label made from the tracker's id."""
    readings = [reading(60.0, "score_read", 0, 0), reading(61.9, "score_change", 1, 0, team="home"),
                reading(62.5, "score_change", 2, 0, team="home")]
    goals = [{"t": 61.2, "team": "home", "event": "e2"}]
    more = {"lineup": [{"id": "h8", "name": "Zane Rondell", "number": 2, "position": "Right-back",
                        "confident": True, "source": "id_feed"}]}
    ctx, laptop, page, errors = scorebug_phone(browser, site, readings, goals, at="63", more=more)
    page.wait_for_function("document.querySelector('#score-home').textContent === '2'")
    lines = page.locator("#goals-home .side-goal").all_inner_texts()
    assert lines == ["Rondell 2′", "Crowmere 2′"], lines  # e2's scorer h8 by name; the other by club
    assert not errors
    ctx.close()


def test_embedded_beside_the_big_screen_the_phone_opens_on_live_silent_and_answers_its_parent(browser, site):  # noqa: F811
    """desktop-companion, Oct 26: the big screen docks the phone in an iframe (?embed=1), already
    paired, the big screen playing every sound. No pairing screen, no sound controls, no first-run
    choices over Live; tab changes go to the parent page, and the parent can open Ask."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    src = f"phone/?mock=1&code={MOCK_CODE}&clip=mock&bundle=/bundle/&embed=1"
    host = f"""<!doctype html><body style="margin:0;background:#000">
      <iframe id="phone" src="{site}{src}" style="width:380px;height:860px;border:0"></iframe>
      <script>window.got = []; addEventListener("message", (e) => got.push(e.data));</script></body>"""
    ctx.route("**/embed-host.html", lambda r: r.fulfill(body=host, content_type="text/html"))
    laptop = ctx.new_page()
    laptop.goto(f"{site}phone/mock-laptop.html?code={MOCK_CODE}")
    laptop.fill("#seek", "63")
    page = ctx.new_page()
    errors = watch(page)
    page.goto(f"{site}embed-host.html")
    phone = page.frame_locator("#phone")
    frame = page.frame(url=lambda u: "embed=1" in u)
    frame.wait_for_selector("body[data-state=live][data-embed='1']")
    assert frame.is_hidden("#pair") and frame.locator(".speak:visible, .listening:visible").count() == 0
    assert frame.is_hidden("#onboard")  # a first visit, yet Live is not covered by the choices
    assert frame.evaluate("document.body.dataset.tab") in ("radar", None)
    page.evaluate("document.getElementById('phone').contentWindow"
                  ".postMessage({type: 'ninety-open', tab: 'ask'}, location.origin)")
    frame.wait_for_function("document.body.dataset.tab === 'ask'")
    page.wait_for_function("got.some((m) => m && m.type === 'ninety-tab' && m.tab === 'ask')")
    phone.locator("#tab-button-insights").click()
    page.wait_for_function("got.some((m) => m && m.type === 'ninety-tab' && m.tab === 'insights')")
    # A message from anywhere but the parent page opens nothing.
    frame.evaluate("window.postMessage({type: 'ninety-open', tab: 'ask'}, '*')")
    page.wait_for_timeout(300)
    assert frame.evaluate("document.body.dataset.tab") == "insights"
    assert not errors
    ctx.close()
