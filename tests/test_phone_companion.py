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
from tests.test_phone import MOCK_CODE, MOCK_DIST, PHONE_SIZE, browser, unavailable, watch  # noqa: F401
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
    assert page.inner_text(".band .home-name") == "Crowmere"  # the clubs on the clip's scorebug
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
    page.click("#tab-button-ask")
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
    base = {"fact": "f1", "t": 60.0, "team": "home", "club": "Oakfield"}

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
    base = {"fact": "f1", "t": 60.0, "team": "home", "club": "Oakfield"}
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
                          "window.ninetyPhone.name('a-t12', {'a-t12': \"Fenwick's left-back\"})]")
    assert label == ["Fenwick player 12", "Oakfield 7", "Fenwick's left-back"]
    assert not errors


# --- insights: pushed cards up to the clock, each with "Why?" ---------------------------------------


def test_story_shows_only_cards_up_to_the_clock_and_how_we_know_holds_why(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False, laptop_t=50)
    requests: list[str] = []
    page.on("request", lambda r: requests.append(r.url))
    page.wait_for_function("window.ninetyPhone.state.insights.length > 0")
    cards = page.evaluate("window.ninetyPhone.state.insights")
    assert cards and all(c["t"] <= 50.2 for c in cards)  # never a card from later in the replay
    page.click("#tab-button-insights")
    assert page.get_attribute("#tab-button-insights", "aria-selected") == "true"
    page.wait_for_selector("#insights-title")
    first = page.locator("#insights .insight").first
    assert first.locator("h3").text_content() == cards[0]["headline"]
    assert first.locator(".story-body > figure canvas").count() == 1
    first.locator(".how").click()
    # The Scout's precomputed, fact-checked "why it matters" is in the sheet: no question is sent.
    page.locator("#how-body .stepper").wait_for()
    assert cards[0]["why"]["answer"]["text"] in page.inner_text("#how-body")  # why it matters, first
    assert page.inner_text("#how-body .count-line") == "3 checks · all passed"
    assert page.locator("#how-body .step").count() == 3
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
    page.wait_for_selector("#ask-form")
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
    clubs = dict(re.findall(r'^\s+([A-Z]{3}): "([^"]+)",$', source, re.M))
    assert set(clubs) == set(TEAM_CODES)
    assert len(set(clubs.values())) == len(clubs)
    for code, name in clubs.items():
        assert name.upper().startswith(code[0]), (code, name)
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
                               "evidence": [f"ov:{cid}"], "visual": visual}}}


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
    page.click("#tab-button-insights")
    card = page.locator("#insights .insight").first
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
    answer = ask(page, "Where are Oakfield overloading?")
    answer.locator(".how").click()
    seen = "document.querySelector('#how-body canvas.seen')?.getAttribute('aria-label')"
    page.wait_for_function(f"({seen} || '').includes('percent')")
    words = page.get_attribute("#how-body canvas.seen", "aria-label")
    assert words.startswith("The broadcast picture at 1:01")
    assert "no AI wrote it" in page.inner_text("#how-body")  # a code answer: no Judge to claim
    assert page.locator("#how-body figure.picture").count() == 1  # what it measured, drawn again
    assert not errors


def test_live_has_a_players_list_and_the_play_in_words_appears_when_focus_reaches_it(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False)
    assert page.is_visible("#roster-box summary")  # Players: a visible way to any player
    box = page.locator("#now-box").bounding_box()
    assert box["width"] <= 1 and box["height"] <= 1  # the describe controls are off screen...
    page.focus("#now-live")  # ...until a keyboard or screen-reader user reaches them
    box = page.locator("#now-box").bounding_box()
    assert box["width"] > 100 and box["height"] > 40, box
    page.click(".speak >> nth=0")  # one control: read aloud, and describe the play as it happens
    assert page.is_checked("#now-live")
    assert not errors



def test_an_answer_headline_reads_naturally_from_its_own_numbers(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False, laptop_t=60)
    answer = ask(page, "Where are Oakfield overloading?")
    answers = [p for p in page.evaluate("window.ninetyPhone.seen") if p.get("type") == "answer"]
    visual = answers[-1]["answer"]["visual"]
    g = visual["geometry"]
    n, m = len(g[visual["team"]]), len(g["away" if visual["team"] == "home" else "home"])
    assert answer.locator(".figure").inner_text() == f"{n} v {m} round the ball"
    assert not errors


def test_the_var_check_puts_the_margin_on_a_scale_and_never_calls_inside_the_band(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False)
    base = {"fact": "f1", "t": 60.0, "team": "home", "club": "Oakfield", "kind": "offside"}

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
    assert page.locator("#live-stats").is_hidden() and page.locator("#scorers").is_hidden()
    assert not errors


def test_live_match_stats_are_match_json_s_numbers_as_mirrored_rows(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, laptop_t=62.8)
    page.wait_for_selector("#live-stats:not([hidden])")
    stats = json.loads(page.evaluate("fetch('/bundle/match.json').then(r => r.text())"))["stats"]
    last = [s for s in stats if s["t"] <= 62.8][-1]
    rows = page.locator("#stat-rows .stat-row")
    labels = [rows.nth(i).get_attribute("aria-label") for i in range(rows.count())]
    assert f"Shots: Crowmere {last['home']['shots']}, Dunhollow {last['away']['shots']}" in labels
    home, away = last["home"]["passes_completed"], last["away"]["passes_completed"]
    assert f"Passes completed: Crowmere {home}, Dunhollow {away}" in labels
    assert not errors



def test_the_player_sheet_compares_two_players_from_their_own_cards(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, bundle=False, laptop_t=60)
    page.click("#roster-box summary")
    page.get_by_role("button", name="Oakfield 7", exact=True).click()
    page.wait_for_function("document.querySelector('#speed').textContent !== '–'")
    assert "average position" in page.inner_text("#avg-pos")
    page.locator("#compare-chips").get_by_role("button", name="Fenwick 7", exact=True).click()
    page.wait_for_selector("#compare-rows:not([hidden]) .stat-row")
    labels = [page.locator("#compare-rows .stat-row").nth(i).get_attribute("aria-label") for i in range(3)]
    assert labels[0].startswith("Speed now (km/h): Oakfield 7 ") and ", Fenwick 7 " in labels[0]
    assert not errors


def test_the_territory_strip_is_match_json_s_and_rewinding_it_moves_the_whole_screen(browser, site):  # noqa: F811
    laptop, page, errors = phone(browser, site, laptop_t=62.8)
    page.wait_for_selector("#momentum:not([hidden])")
    match = json.loads(page.evaluate("fetch('/bundle/match.json').then(r => r.text())"))
    (b,) = match["territory"]["bins"]  # the clip's few seconds are one 5-minute spell
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
    page.wait_for_selector("#shot-map:not([hidden])")
    # The clip's one shot: home's, from (80, 34), saved. Home attacks x = 105, so it is 25 m out, central.
    dot = page.locator("#shots circle.shot")
    assert dot.count() == 1
    assert dot.get_attribute("class") == "shot home on"
    assert float(dot.get_attribute("cx")) == 34 and float(dot.get_attribute("cy")) == 25
    assert "saved" in page.inner_text("#shot-list")
    page.locator("#shot-filter ion-segment-button[value=away]").click()
    page.wait_for_function("document.querySelectorAll('#shots circle.shot').length === 0")
    # Rewound to before the shot (61.2 s), there is none to show.
    page.locator("#momentum-strip").focus()
    page.keyboard.press("Home")
    page.wait_for_selector("#shot-map", state="hidden")
    assert not errors
