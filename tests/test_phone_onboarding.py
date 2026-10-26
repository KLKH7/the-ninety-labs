"""The phone's first-run onboarding in Ask (web/phone/src/fan.ts, onboarding.ts): a favourite club,
a mode (the brief's casual fan or analyst) and what matters most, in three taps; the choices order
Ask's questions and set the Story feed's starting filter, stay in this browser only, and can be
changed from the settings sheet. Needs the built phone and Playwright's Chromium (tests/test_phone.py).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ninety.agents.companion_match import route
from tests.test_phone import MOCK_CODE, PHONE_SIZE, browser, watch  # noqa: F401
from tests.test_phone_companion import site  # noqa: F401

FAN_TS = Path(__file__).resolve().parent.parent / "web" / "phone" / "src" / "fan.ts"


def bank() -> list[str]:
    """Every question template in fan.ts's BANK, read from the source the phone ships."""
    src = FAN_TS.read_text()
    block = src[src.index("const BANK"):src.index("};", src.index("const BANK"))]
    return re.findall(r'"([^"]+\?)"', block)


def test_the_bank_is_read():
    assert len(bank()) >= 12


@pytest.mark.parametrize("us,them", [("London", "Lisbon"), ("Lisbon", "London")])
def test_every_suggested_question_reaches_one_of_the_companions_tools(us, them):
    for q in bank():
        filled = q.replace("{us}", us).replace("{them}", them)
        assert route(filled), filled  # a suggestion no tool answers would be a dead end


def test_a_question_no_tool_answers_routes_nowhere():
    assert route("How are the teams moving?") == []  # why the bank has no such question


def open_phone(browser, site, init: str | None = None, bundle: bool = False):  # noqa: F811
    """The phone beside the mock laptop; without `bundle`, the demo's two clubs (London, Lisbon)."""
    ctx = browser.new_context(viewport=PHONE_SIZE, has_touch=True)
    if init:
        ctx.add_init_script(init)
    laptop = ctx.new_page()
    laptop.goto(f"{site}phone/mock-laptop.html?code={MOCK_CODE}")
    laptop.wait_for_function("window.ninetyLaptop")
    page = ctx.new_page()
    errors = watch(page)
    page.goto(f"{site}phone/?mock=1&code={MOCK_CODE}&clip=mock" + ("&bundle=/bundle/" if bundle else ""))
    page.wait_for_selector("body[data-state=live]")
    return ctx, page, errors


def tap(page, label: str):
    page.locator(".onboard-option", has_text=label).click()


def grid(page) -> list[str]:
    return [c.inner_text() for c in page.locator("#ask-grid .chip").all()]


def test_three_taps_choose_club_mode_and_focus_and_order_the_questions(browser, site):  # noqa: F811
    ctx, page, errors = open_phone(browser, site)
    page.click("#tab-button-ask")
    page.wait_for_selector("#onboard:visible")
    assert page.is_hidden("#ask-start") and page.is_hidden("#ask-form")  # no composer while choosing
    assert page.is_hidden("#panel-ask ion-header")  # full-screen: the tiles carry the crests
    assert page.is_visible("#tabs")  # Live and Story stay a tap away
    assert page.inner_text("#onboard-title") == "Your club"
    assert page.locator(".onboard-option .onboard-crest svg").count() == 2
    tap(page, "London Athletic")
    assert page.inner_text("#onboard-title") == "How do you watch?"
    page.click(".onboard-back")
    assert page.get_attribute(".onboard-option[data-value=LON]", "aria-checked") == "true"
    tap(page, "London Athletic")
    tap(page, "Analyst")
    tap(page, "Tactics")
    page.wait_for_selector("#ask-start:visible")
    assert page.is_hidden("#onboard")
    page.wait_for_selector("#ask-form:visible")  # the composer rises in once the choices are made
    assert page.is_visible("#panel-ask ion-header")  # and the match header is back
    qs = grid(page)
    assert qs[0] == "Where are London overloading?" and "Which pass broke Lisbon's lines?" in qs
    saved = json.loads(page.evaluate("localStorage.getItem('ninety.fan')"))
    assert saved == {"club": "LON", "mode": "analyst", "focus": "tactics"}
    assert page.get_attribute("#insights", "data-mode") == "all"  # an analyst opens on every play
    # The next visit remembers: no onboarding, the same order.
    page.reload()
    page.wait_for_selector("body[data-state=live]")
    page.click("#tab-button-ask")
    page.wait_for_selector("#ask-start:visible")
    assert page.is_hidden("#onboard") and grid(page)[0] == "Where are London overloading?"
    assert not errors
    ctx.close()


def test_a_casual_lisbon_fan_gets_lisbons_moments_first_and_the_key_plays(browser, site):  # noqa: F811
    ctx, page, errors = open_phone(browser, site)
    page.click("#tab-button-ask")
    tap(page, "Lisbon Esportes")
    tap(page, "Casual fan")
    tap(page, "Goals and big moments")
    page.wait_for_selector("#ask-start:visible")
    qs = grid(page)
    assert qs[:2] == ["What have I missed?", "How many shots have Lisbon had?"]
    assert page.get_attribute("#insights", "data-mode") == "key"
    page.click("#tab-button-insights")
    assert page.evaluate("document.getElementById('story-mode').value") == "key"
    assert not errors
    ctx.close()


def test_the_settings_row_reopens_the_choices_ticked_and_cancel_keeps_them(browser, site):  # noqa: F811
    fan = json.dumps({"club": "LON", "mode": "analyst", "focus": "players"})
    seed = f"localStorage.setItem('ninety.fan', '{fan}')"
    ctx, page, errors = open_phone(browser, site, init=seed)
    page.click("#tab-button-ask")
    page.wait_for_selector("#ask-start:visible")
    assert page.is_hidden("#onboard")
    page.click("#panel-ask .settings-open")
    page.wait_for_selector("#fan-edit:visible")
    assert page.inner_text("#fan-value") == "London · Analyst"
    page.click("#fan-edit")
    page.wait_for_selector("#onboard:visible")
    assert page.is_hidden("#ask-form")  # changing the choices hides the composer too
    assert page.inner_text(".onboard-skip") == "Cancel"
    assert page.get_attribute(".onboard-option[data-value=LON]", "aria-checked") == "true"
    page.click(".onboard-skip")
    page.wait_for_selector("#ask-start:visible")
    page.wait_for_selector("#ask-form:visible")
    assert json.loads(page.evaluate("localStorage.getItem('ninety.fan')"))["focus"] == "players"
    assert not errors
    ctx.close()


def test_skip_is_remembered_and_brings_the_composer(browser, site):  # noqa: F811
    ctx, page, errors = open_phone(browser, site)
    page.click("#tab-button-ask")
    page.wait_for_selector("#onboard:visible")
    assert page.is_hidden("#ask-form")  # no composer while choosing
    page.click(".onboard-skip")
    page.wait_for_selector("#ask-start:visible")
    page.wait_for_selector("#ask-form:visible")
    assert json.loads(page.evaluate("localStorage.getItem('ninety.fan')")) == {"skipped": True}
    assert grid(page)[0] == "Where are London overloading?"  # the unpersonalised grid, as before
    page.reload()
    page.wait_for_selector("body[data-state=live]")
    page.click("#tab-button-ask")
    page.wait_for_selector("#ask-form:visible")  # skipped: straight to the composer next visit
    assert page.is_hidden("#onboard")
    assert not errors
    ctx.close()


def test_a_browser_that_refuses_storage_still_onboards(browser, site):  # noqa: F811
    refuse = ("Object.defineProperty(window, 'localStorage',"
              " {get() { throw new DOMException('denied', 'SecurityError'); }});")
    ctx, page, errors = open_phone(browser, site, init=refuse)
    page.click("#tab-button-ask")
    page.wait_for_selector("#onboard:visible")
    tap(page, "Lisbon Esportes")
    tap(page, "Analyst")
    tap(page, "Players")
    page.wait_for_selector("#ask-start:visible")
    assert grid(page)[0] == "Who's been Lisbon's best player?"  # chosen, though nothing could be saved
    assert not errors
    ctx.close()


def test_a_match_without_the_favourite_club_keeps_its_own_two_clubs(browser, site):  # noqa: F811
    """The test bundle's clip is two other clubs: a Lisbon fan's questions name them, never Lisbon."""
    ctx, page, errors = open_phone(browser, site, bundle=True)
    page.wait_for_function("window.ninetyPhone.state.match !== null")
    page.click("#tab-button-ask")
    tap(page, "Lisbon Esportes")
    tap(page, "Analyst")
    tap(page, "Tactics")
    page.wait_for_selector("#ask-start:visible")
    home = page.inner_text(".home-name >> nth=0")
    assert home != "Lisbon" and grid(page)[0] == f"Where are {home} overloading?"
    assert not any("Lisbon" in q for q in grid(page))
    assert not errors
    ctx.close()


def test_the_composer_is_one_pill_with_send_inside_centred_and_return_sends(browser, site):  # noqa: F811
    ctx, page, errors = open_phone(browser, site)
    page.click("#tab-button-ask")
    page.click(".onboard-skip")
    page.wait_for_function("!document.getElementById('panel-ask').classList.contains('composer-in')")  # risen
    pill = page.locator(".ask-pill").bounding_box()
    send = page.locator("#ask-button").bounding_box()
    assert pill["x"] < send["x"] and send["x"] + send["width"] <= pill["x"] + pill["width"]  # inside
    gap_top = send["y"] - pill["y"]
    gap_bottom = pill["y"] + pill["height"] - (send["y"] + send["height"])
    assert abs(gap_top - gap_bottom) <= 1  # vertically centred on one line
    empty = page.eval_on_selector("#ask-button", "b => getComputedStyle(b).backgroundColor")
    page.fill("#question", "Who has more of the ball? " * 5)
    tall = page.locator(".ask-pill").bounding_box()["height"]
    assert tall > pill["height"] + 15  # the field grows with the question
    lit = "getComputedStyle(document.querySelector('#ask-button')).backgroundColor === 'rgb(10, 132, 255)'"
    page.wait_for_function(lit)  # blue once there is text
    assert empty != "rgb(10, 132, 255)"  # grey while empty
    page.fill("#question", "Who has more of the ball?")
    page.press("#question", "Enter")  # Return sends
    page.wait_for_selector("#answers .answer:not(.pending)")
    assert page.input_value("#question") == ""
    assert abs(page.locator(".ask-pill").bounding_box()["height"] - pill["height"]) <= 1  # back to one line
    assert not errors
    ctx.close()
