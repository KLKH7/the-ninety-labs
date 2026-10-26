"""The project page (web/site) cannot drift from the reports it quotes, and every link on it resolves.

Every number on the page sits in a <data> element naming its report and key; these tests read the
report and check the page shows the same value, that a link to the report sits beside it, and that
no other digit appears in the page's prose. Links go to files in this repo (checked to exist here,
so they exist on GitHub once merged), to ids on the page, or to the page's own files.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "web" / "site"
REPO = "https://github.com/KLKH7/the-ninety-labs"

# Text inside these is code, a date or a name, not a claim; any other digit must be a <data> number.
NOT_PROSE = {"code", "pre", "kbd", "time", "abbr", "data", "style", "head"}
BLOCKS = {"li", "p", "table", "figure"}
VOID = {"meta", "link", "img", "br", "hr", "input", "source", "path", "line", "rect"}


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, int | None]] = []  # (tag, block index)
        self.blocks: list[set[str]] = []  # hrefs inside each block
        self.numbers: list[dict] = []
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.tags: list[tuple[str, dict]] = []
        self.prose_digits: list[str] = []
        self._data: dict | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = {k: v or "" for k, v in attrs}
        self.tags.append((tag, a))
        if "id" in a:
            self.ids.add(a["id"])
        for attr in ("href", "src"):
            if attr in a:
                self.links.append(a[attr])
        if tag == "a":
            for _, block in self.stack:
                if block is not None:
                    self.blocks[block].add(a.get("href", ""))
        if tag == "data":
            open_blocks = [b for _, b in self.stack if b is not None]
            self._data = {**a, "text": "", "block": open_blocks[-1] if open_blocks else None}
            self.numbers.append(self._data)
        if tag in VOID or tag.endswith("/"):
            return
        block = None
        if tag in BLOCKS:
            self.blocks.append(set())
            block = len(self.blocks) - 1
        self.stack.append((tag, block))

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if tag == "data":
            self._data = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def handle_data(self, text: str) -> None:
        if self._data is not None:
            self._data["text"] += text
        if not {t for t, _ in self.stack} & NOT_PROSE:
            self.prose_digits += re.findall(r"\S*\d\S*", text)


@pytest.fixture(scope="module")
def page() -> Page:
    p = Page()
    p.feed((SITE / "index.html").read_text())
    return p


# ------------------------------------------------------------------ reading the reports


def fact_checker_metrics(claims: list[dict]) -> dict[str, int]:
    """The counts fact-checker.md states, from the claim list it was generated with."""
    false = [c for c in claims if c["true"] is False]
    true = [c for c in claims if c["true"] is True]
    tone = [c for c in claims if c["true"] is None]  # neither true nor false: counted apart

    def service(c: dict) -> bool:
        return any("service error" in r for r in c["reasons"])

    def rejected(c: dict) -> bool:
        return not c["code_ok"] or not c["judge_ok"]

    answered = [c for c in true if not service(c)]
    return {
        "false_claims": len(false),
        "false_caught_code": sum(not c["code_ok"] for c in false),
        "false_caught_with_judge": sum(rejected(c) for c in false),
        "true_claims": len(true),
        "true_rejected_code": sum(not c["code_ok"] for c in true),
        "true_rejected_with_judge": sum(rejected(c) for c in true),
        "true_claims_excluding_service": len(answered),
        "true_rejected_with_judge_excluding_service": sum(rejected(c) for c in answered),
        "tone_claims": len(tone),
        "tone_aired": sum(not rejected(c) for c in tone),
    }


def lookup(src: str, key: str) -> float:
    report = json.loads((ROOT / src).read_text())
    if src.endswith("fact-checker.json"):
        return fact_checker_metrics(report)[key]
    *path, last = key.split(".")
    for part in path:
        report = report[part]
    return sum(report[k] for k in last.split("+"))


def fmt(value: float, how: str) -> str:
    if how == "int":
        assert value == int(value), value
        return f"{int(value):,}"
    return f"{value:.{int(how)}f}"


def sibling_report(src: str) -> str:
    return src.removesuffix(".json") + ".md"


# ------------------------------------------------------------------ numbers


def test_page_quotes_numbers(page: Page) -> None:
    assert len(page.numbers) >= 20  # a parser that finds nothing must not pass the tests below


def test_every_number_matches_its_report(page: Page) -> None:
    for n in page.numbers:
        expected = fmt(lookup(n["data-src"], n["data-key"]), n["data-fmt"])
        assert n["text"].strip() == expected, (n["data-src"], n["data-key"])
        assert n["value"] == expected.replace(",", ""), (n["data-src"], n["data-key"])


def test_every_number_links_to_its_report(page: Page) -> None:
    for n in page.numbers:
        wanted = {f"{REPO}/blob/main/{n['data-src']}", f"{REPO}/blob/main/{sibling_report(n['data-src'])}"}
        assert n["block"] is not None, n
        assert page.blocks[n["block"]] & wanted, (n["data-src"], n["data-key"], n["text"])


def test_no_unsourced_digits_in_prose(page: Page) -> None:
    assert page.prose_digits == []


def test_fact_checker_summary_agrees_with_its_claims() -> None:
    """The page reads the claim list; the linked summary must say the same."""
    m = fact_checker_metrics(json.loads((ROOT / "docs/eval/fact-checker.json").read_text()))
    text = (ROOT / "docs/eval/fact-checker.md").read_text()
    caught = f"code alone {m['false_caught_code']}/{m['false_claims']}, "
    caught += f"code + judge {m['false_caught_with_judge']}/{m['false_claims']}"
    assert caught in text
    wrong = f"code + judge {m['true_rejected_with_judge']}/{m['true_claims']} "
    wrong += f"(excluding service/timeout holds: {m['true_rejected_with_judge_excluding_service']}"
    wrong += f"/{m['true_claims_excluding_service']})"
    assert wrong in text


def test_lookup_fails_on_a_changed_report(page: Page, monkeypatch: pytest.MonkeyPatch) -> None:
    """A report that moves makes the page wrong, and the check notices."""
    n = next(n for n in page.numbers if n["data-key"] == "by_class.player.recall")
    real = ROOT / n["data-src"]
    report = json.loads(real.read_text())
    report["by_class"]["player"]["recall"] = 0.5
    original = Path.read_text

    def read_text(self: Path, *a, **k) -> str:
        return json.dumps(report) if self == real else original(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", read_text)
    assert fmt(lookup(n["data-src"], n["data-key"]), n["data-fmt"]) != n["text"].strip()


# ------------------------------------------------------------------ links


def test_every_link_resolves(page: Page) -> None:
    assert page.links
    for link in page.links:
        if link == REPO:
            continue
        if link.startswith(f"{REPO}/blob/main/"):
            assert (ROOT / link.removeprefix(f"{REPO}/blob/main/")).is_file(), link
        elif link.startswith(f"{REPO}/tree/main/"):
            assert (ROOT / link.removeprefix(f"{REPO}/tree/main/")).is_dir(), link
        elif link.startswith("#"):
            assert link[1:] in page.ids, link
        else:
            assert "//" not in link and ":" not in link, f"external link or resource: {link}"
            assert (SITE / link).is_file(), link


def test_no_scripts_trackers_or_external_resources(page: Page) -> None:
    tags = {t for t, _ in page.tags}
    assert not tags & {"script", "iframe", "object", "embed", "form"}
    csp = next(a["content"] for t, a in page.tags if t == "meta" and a.get("http-equiv"))
    assert "default-src 'none'" in csp and "script-src" not in csp
    css = (SITE / "site.css").read_text()
    assert "url(" not in css and "@import" not in css


# ------------------------------------------------------------------ accessibility


def test_images_have_alt_text(page: Page) -> None:
    imgs = [a for t, a in page.tags if t == "img"]
    assert imgs
    for a in imgs:
        assert "alt" in a, a["src"]
        decorative = "overlay" in a.get("class", "")
        assert decorative or len(a["alt"]) > 40, a["src"]


def test_landmarks_and_language(page: Page) -> None:
    html = next(a for t, a in page.tags if t == "html")
    assert html.get("lang") == "en"
    tags = [t for t, _ in page.tags]
    assert tags.count("h1") == 1 and "main" in tags and "nav" in tags
    assert any(t == "a" and a.get("href") == "#main" for t, a in page.tags)  # skip link


def test_the_five_stages_each_carry_a_status(page: Page) -> None:
    text = (SITE / "index.html").read_text()
    for stage in ("Ingest", "Interpret", "Explain", "Render", "Personalize"):
        card = text.split(f'<span class="step">{stage}</span>', 1)[1].split("</li>\n\n", 1)[0]
        status = r'<p class="status"><span class="tag (running|local|progress|planned)">'
        assert re.search(status, card), stage


def _luminance(hex_color: str) -> float:
    rgb = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_colour_contrast_meets_wcag_aa() -> None:
    css = (SITE / "site.css").read_text()
    var = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", css))
    backgrounds = ("bg", "band", "surface")
    text = ("text", "muted", "link", "accent", "running", "local", "progress", "planned", "truth")
    for fg in text:
        for bg in (*backgrounds, "tag-bg"):
            assert contrast(var[fg], var[bg]) >= 4.5, (fg, bg)
    assert contrast("#06120e", var["accent"]) >= 4.5  # button text
    for bg in backgrounds:
        assert contrast(var["focus"], var[bg]) >= 3  # focus ring, a non-text contrast


def test_contrast_check_can_fail() -> None:
    assert contrast("#777777", "#888888") < 4.5


# ------------------------------------------------------------------ stills


def test_stills_are_ours_and_recorded() -> None:
    prov = json.loads((SITE / "stills" / "provenance.json").read_text())
    assert (SITE / "stills" / prov["image"]).is_file()
    assert (SITE / "stills" / prov["truth_overlay"]).is_file()
    assert prov["command"].startswith("uv run ninety-render ")
