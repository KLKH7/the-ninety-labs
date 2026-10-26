"""The made-up advertisers on the broadcast boards (web/render/render.js, BROADCAST_BRANDS) must not
promote what the hackathon rules forbid (rule 4.4: alcohol, gambling, tobacco and the like). A
"BEER" sub-label shipped on the demo footage until Oct 26; this keeps it from coming back."""

import re
from pathlib import Path

RENDER = Path(__file__).resolve().parents[1] / "web" / "render" / "render.js"
FORBIDDEN = ("BEER", "LAGER", "ALE", "WINE", "VODKA", "WHISKY", "SPIRITS", "GIN", "RUM", "CIDER", "BREWERY",
             "BET", "BETS", "BETTING", "CASINO", "POKER", "LOTTERY", "SLOTS", "TOBACCO", "CIGARETTES", "VAPE",
             "VOTE", "PARTY")
ALLOWED = {"BETTING-FREE ZONE"}  # a responsible-gambling message, not an advert for betting


def brands() -> list[tuple[str, str]]:
    m = re.search(r"const BROADCAST_BRANDS = \[(.*?)\];", RENDER.read_text(), re.S)
    assert m, "BROADCAST_BRANDS not found in render.js"
    return re.findall(r"\['([^']+)', '([^']+)'\]", m.group(1))


def test_no_board_promotes_forbidden_products():
    pairs = brands()
    assert len(pairs) >= 10
    for name, line in pairs:
        if line in ALLOWED:
            continue
        words = set(re.findall(r"[A-Z]+", f"{name} {line}"))
        assert not words & set(FORBIDDEN), f"board {name} / {line} promotes a forbidden product"
