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

import pytest

from ninety import e2e
from tests.e2e_clip import H, W, write_clip
from tests.test_phone import MOCK_CODE, MOCK_DIST, PHONE_SIZE, browser, unavailable, watch  # noqa: F401
from tests.test_radar import FPS, SEGMENTS, observations_clip, tracked_clip

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
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(www))
    handler.log_message = lambda *a: None
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


def phone(browser, site, bundle=True, laptop_t: float | None = None):  # noqa: F811
    """A mock laptop and the phone in one context; with `bundle`, the phone reads the cut clip's."""
    ctx = browser.new_context(viewport=PHONE_SIZE, has_touch=True)
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
    assert page.inner_text("#legend-home") == "Crowmere →"
    assert page.inner_text("#legend-away") == "← Dunhollow"
    assert page.is_visible("#legend-view")  # the TV camera's footprint, from vision's own camera fit
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
    page.touchscreen.tap(box["x"] + x, box["y"] + y)
    page.wait_for_selector("#player:not([hidden])")
    assert page.inner_text("#player-title") == "Dunhollow player 3"
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
    ("Where are Oakfield overloading?", "overload"),
    ("Which pass broke Fenwick's lines?", "line_break"),
    ("What are Oakfield's passing options?", "pass_options"),
    ("How are Fenwick set up?", "shape"),
    ("How are the teams moving?", "wind"),
]


def ask(page, text: str):
    page.click("#tab-ask")
    n = page.locator("#answers .answer:not(.pending)").count()
    page.fill("#question", text)
    page.click("#ask-button")
    page.wait_for_function(f"document.querySelectorAll('#answers .answer:not(.pending)').length > {n}")
    return page.locator("#answers .answer").first


def pixel(page, x: float, y: float) -> list[int]:
    """The newest answer picture's pixel at pitch metres (x, y), through radar.ts's projection
    (3 m of grass round the lines, y = 0 at the bottom)."""
    return page.evaluate(f"""(() => {{
        const c = document.querySelector('#answers .answer figure canvas');
        const s = c.width / 111;
        const at = [Math.round((3 + {x}) * s), Math.round((71 - {y}) * s)];
        return [...c.getContext('2d').getImageData(at[0], at[1], 1, 1).data];
    }})()""")


@pytest.mark.parametrize(("question", "kind"), QUESTIONS)
def test_an_answer_draws_the_picture_its_visual_names_with_its_numbers(browser, site, question, kind):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False, laptop_t=60)
    answer = ask(page, question)
    picture = answer.locator("figure.picture")
    assert picture.get_attribute("data-kind") == kind  # mutation: draw every visual as an overload -> fails
    canvas = picture.locator("canvas")
    page.wait_for_function("document.querySelector('#answers .answer figure canvas').dataset.drawn === '1'")
    answers = [p for p in page.evaluate("window.ninetyPhone.seen") if p.get("type") == "answer"]
    visual = answers[-1]["answer"]["visual"]
    head = picture.get_attribute("data-headline")
    # The headline is the visual's own numbers, never the phone's.
    if kind == "overload":
        assert head == f"{visual['count']['for']}v{visual['count']['against']}"
        # The zone is shaded in the team's colour: blue for Oakfield, inside its corner.
        z = visual["zone"]
        r, g, b, _ = pixel(page, min(z["x0"], z["x1"]) + 0.6, min(z["y0"], z["y1"]) + 0.6)
        assert b > r + 40, (r, g, b)  # mutation: draw an overload as a shape -> plain grass
        said = f"{visual['count']['for']} players against {visual['count']['against']}"
        assert said in canvas.get_attribute("aria-label")
    elif kind == "line_break":
        assert head == f"{visual['bypassed']} bypassed"
        f, t = visual["pass"]["from"], visual["pass"]["to"]
        r, g, b, _ = pixel(page, (f["x"] + t["x"]) / 2, (f["y"] + t["y"]) / 2)
        assert min(r, g, b) > 200, (r, g, b)  # the white arrow, halfway along the pass
    elif kind == "pass_options":
        assert head == f"{sum(p.get('role') == 'open' for p in visual['players'])} open"
    else:
        assert head == ""
    assert canvas.get_attribute("aria-label").startswith("Picture")
    assert not errors


def test_a_visual_missing_its_numbers_draws_no_picture(browser, site):  # noqa: F811
    """The phone never fills in a number: a picture without the data its kind needs is not drawn."""
    laptop, page, errors = phone(browser, site, bundle=False)
    base = {"t": 60.0, "team": "home", "players": [{"id": "h7", "team": "home", "x": 50.0, "y": 30.0}]}
    zone = {"x0": 40.0, "x1": 60.0, "y0": 20.0, "y1": 40.0}
    PASS = {"from": {"x": 40, "y": 30}, "to": {"x": 70, "y": 30}}  # noqa: N806
    cases = [
        ({**base, "kind": "overload", "zone": zone, "count": {"for": 4, "against": 2}}, True),
        ({**base, "kind": "overload", "zone": zone}, False),  # no count: no "4v2" to draw
        ({**base, "kind": "line_break", "pass": PASS}, False),  # no count of the defenders bypassed
        ({**base, "kind": "line_break", "pass": PASS, "bypassed": 6}, True),
        ({**base, "kind": "pass_options"}, False),  # nobody on the ball
        ({**base, "kind": "shape", "lines": [[{"x": 30, "y": 10}]]}, False),  # a line of one point
        ({**base, "kind": "wind", "t_from": 30.0, "t_to": 60.0}, True),
        ({**base, "kind": "overload", "zone": zone, "count": {"for": 4, "against": 2},
          "players": [{"id": "h7", "team": "home", "x": 400.0, "y": 30.0}]}, False),  # off the pitch
        ({**base, "kind": "heatmap"}, False),  # a kind the phone does not know
    ]
    for visual, ok in cases:
        assert page.evaluate("v => window.ninetyPhone.drawable(v)", visual) is ok, visual
    assert not errors


def test_a_player_is_named_by_the_answers_names_or_his_club_never_his_id(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False, laptop_t=60)
    label = page.evaluate("[window.ninetyPhone.name('a-t12'), window.ninetyPhone.name('h7'), "
                          "window.ninetyPhone.name('a-t12', {'a-t12': \"Fenwick's left-back\"})]")
    assert label == ["Fenwick player 12", "Oakfield 7", "Fenwick's left-back"]
    assert not errors


# --- insights: pushed cards up to the clock, each with "Why?" ---------------------------------------


def test_insights_show_only_cards_up_to_the_clock_and_why_asks_the_companion(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False, laptop_t=50)
    page.wait_for_function("window.ninetyPhone.state.insights.length > 0")
    cards = page.evaluate("window.ninetyPhone.state.insights")
    assert cards and all(c["t"] <= 50.2 for c in cards)  # never a card from later in the replay
    page.click("#tab-insights")
    assert page.get_attribute("#tab-insights", "aria-selected") == "true"
    assert page.is_visible("#panel-insights")
    first = page.locator("#insights .insight").first
    assert first.locator("figure canvas").count() == 1
    first.locator(".why").click()
    assert page.get_attribute("#tab-ask", "aria-selected") == "true"
    answer = page.locator("#answers .answer:not(.pending)").first
    answer.wait_for()
    assert cards[0]["question"] in answer.locator(".asked").inner_text()
    assert not errors


def test_the_tabs_move_with_the_arrow_keys(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False)
    page.focus("#tab-radar")
    page.keyboard.press("ArrowRight")
    assert page.evaluate("document.activeElement.id") == "tab-ask" and page.is_visible("#panel-ask")
    page.keyboard.press("End")
    assert page.evaluate("document.activeElement.id") == "tab-insights"
    page.keyboard.press("ArrowRight")  # round to the first
    assert page.evaluate("document.activeElement.id") == "tab-radar" and page.is_hidden("#panel-insights")
    assert not errors


def test_every_scorebug_code_has_one_club_name_starting_with_its_letters():
    """The screens name the clubs the picture shows: web/viewer/src/teams.ts maps each of the
    renderer's codes (ninety/render/params.py) to one invented name, and e2e carries the clip's."""
    from pathlib import Path

    from ninety.render.params import TEAM_CODES

    source = (Path(__file__).resolve().parent.parent / "web" / "viewer" / "src" / "teams.ts").read_text()
    clubs = dict(re.findall(r'^\s+([A-Z]{3}): "([^"]+)",$', source, re.M))
    assert set(clubs) == set(TEAM_CODES)
    assert len(set(clubs.values())) == len(clubs)
    for code, name in clubs.items():
        assert name.upper().startswith(code[0]), (code, name)
    teams = {"home": "FEN", "away": "OAK"}
    assert e2e.teams_of({"params": {"home_code": "FEN", "away_code": "OAK"}}) == teams
    assert e2e.teams_of({"params": {}}) is None
