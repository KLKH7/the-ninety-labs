"""The Ask grader's rules: one answer's checks, from its text, the intent and the truth table.

Each check is True (passed), False (failed) or None (does not apply). An answer passes when every
check that applies passes. The checks, fixed with intents.json and tolerances.json before any run:

- answered: a verified answer that is not a "can't" (for the unmeasured intent, any plain reply).
- relevant: the lead sentence carries the intent's metric (catches total shots for "on target?").
- correct: the stated number, club or player is within tolerance of the truth, over the footage
  when the answer says it is about the footage, else over the match. For counts and completion the
  claim is graded (grade_claim): a comparison by its direction and any figures it states; the old
  number-only rule stays beside it as correct_strict.
- consistent: the same headline as the other paraphrases of the intent at that time (run.summarise).
- coverage_honest: where the footage shows part of the match, a stated figure says it is about the
  footage ("in the footage we've seen").
- no_future: no leak from after now: no stated minute past now, and no cited fact (or a cited
  aggregate's source fact) timed after now (run.leaks). A real leak.
- span_clipped: the answer's own span ends by now. A span that runs to the end of the current
  minute's bin while every fact it cites is before now is a wording/span defect, not a leak.
- no_false_unknown: no "can't" when the insights hold the intent's facts at that time.
- natural: none of the robotic forms below.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).parent
HALF_S = 45 * 60.0
FULL_MIN = 90
WORD_N = {"five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30}

CANT = re.compile(
    r"\b(?:can't|cannot|couldn't|could not|can not|not known|isn't (?:known|available)|not available|unknown"
    r"|no answer|don't know|doesn't know|unable|nothing (?:from|in) .{0,60}answers"
    r"|not (?:yet )?(?:measured|tracked)"
    r"|isn't (?:measured|tracked)|not one it can|no (?:reading|data))\b",
    re.I,
)
FOOTAGE = re.compile(
    r"\b(?:footage|we've seen|we have seen|on camera|cameras? (?:saw|caught|showed)|shown|in the clips"
    r"|vision (?:has )?(?:seen|counted|spotted|saw|caught)|spotted|has seen|it saw)\b",
    re.I,
)
NATURAL = {
    "footage shown": re.compile(r"\bfootage shown\b", re.I),
    "s's": re.compile(r"\b\w+s's\b"),
    "bare range": re.compile(r"\bbetween \d+(?:\.\d+)?\s*%? and \d+(?:\.\d+)?\s*%", re.I),
    "lowercase start": re.compile(r"(?:^|[.!?]\s+)[a-z]"),
    "a <club> player": re.compile(r"\ban? (?:London Athletic|Lisbon Esportes) player\b"),
    "minute 0": re.compile(r"\bminute 0\b"),
}
NO_GOAL = re.compile(
    r"\b(?:no goals?|goalless|0\s*[-–]\s*0|nil[- ]nil|not scored|haven't scored|hasn't scored"
    r"|yet to score|no goal)\b",
    re.I,
)
LEVEL = re.compile(
    r"\b(?:level|all square|drawing|draw|goalless|0\s*[-–]\s*0|nil[- ]nil|even|neither|evenly)\b", re.I
)
METRIC_NOUN = {
    "passes": r"pass(?:es)?",
    "shots": r"(?:shots?|attempts?|efforts?)",
    "on_target": r"(?:shots? on target|on target|efforts? on target)",
    "corners": r"corners?",
    "out_of_play": r"(?:times?|throw-?ins?|goal kicks?|corners?|stoppages?|restarts?)",
}


def load_intents(path: Path = HERE / "intents.json") -> tuple[list[dict], dict]:
    d = json.loads(path.read_text())
    for it in d["intents"]:
        it["questions"] = [q if isinstance(q, dict) else {"q": q} for q in it["questions"]]
    return d["intents"], d["clubs"]


def with_questions(intents: list[dict], path: Path) -> list[dict]:
    """The intents (metric, scope, window rule, relevance) with their questions replaced by another
    set's: a held-out file shaped like intents.json ({"intents": [{"id", "questions"}]}) or a flat
    list ([{"intent", "q"}], "question" or "text" for "q"). An intent the file does not name keeps
    no question; an id the intents do not know is an error. The questions are never printed."""
    d = json.loads(path.read_text())
    got: dict[str, list[dict]] = {}
    if isinstance(d, dict) and "intents" in d:
        for it in d["intents"]:
            got.setdefault(it["id"], []).extend(
                q if isinstance(q, dict) else {"q": q} for q in it["questions"]
            )
    else:
        rows = d["questions"] if isinstance(d, dict) else d
        for r in rows:
            q = r.get("q") or r.get("question") or r.get("text")
            got.setdefault(r["intent"], []).append({"q": q, **({"chip": r["chip"]} if r.get("chip") else {})})
    unknown = set(got) - {it["id"] for it in intents}
    if unknown:
        raise ValueError(f"{path}: intents not in intents.json: {sorted(unknown)}")
    return [{**it, "questions": got[it["id"]]} for it in intents if got.get(it["id"])]


def load_tolerances(path: Path = HERE / "tolerances.json") -> dict:
    return {k: v["value"] for k, v in json.loads(path.read_text()).items() if isinstance(v, dict)}


def now_minute(t: float) -> int:
    return min(FULL_MIN, int(t // 60) + 1)


def window_of(it: dict, q: str, t: float) -> tuple[float, float]:
    """The stretch the question asks about: one it names, else the intent's rule."""
    s = q.lower()
    m = re.search(r"\blast (\d+|five|ten|fifteen|twenty|thirty)\b(?: ?min\w*)?", s)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else WORD_N[m.group(1)]
        return max(0.0, t - 60 * n), t
    if re.search(r"\b(?:since|in) the half hour\b", s) and t > 1800:
        return 1800.0, t
    if re.search(r"\bfirst half\b", s):
        return 0.0, min(t, HALF_S)
    if re.search(r"\bsecond half\b", s) and t > HALF_S:
        return HALF_S, t
    if re.search(r"\bthis half\b", s):
        return (HALF_S if t > HALF_S else 0.0), t
    rule = it["window"]
    if rule.startswith("last:"):
        return max(0.0, t - 60 * int(rule.split(":")[1])), t
    if rule.startswith("since:"):
        return min(t, 60.0 * int(rule.split(":")[1])), t
    return 0.0, t


def windows(it: dict, t: float) -> list[tuple[float, float]]:
    return sorted({window_of(it, q["q"], t) for q in it["questions"]})


def wkey(it: dict, t: float, w: tuple[float, float]) -> str:
    return f"{it['id']}|{t:g}|{w[0]:g}-{w[1]:g}"


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def lead(text: str) -> str:
    s = sentences(text)
    return s[0] if s else ""


def club_spans(text: str, clubs: dict) -> list[tuple[int, str]]:
    """(position, side) of each club named, the long name first so 'London Athletic' is one."""
    out, taken = [], []
    for side, names in clubs.items():
        for name in sorted(names, key=len, reverse=True):
            for m in re.finditer(rf"\b{re.escape(name)}\b", text):
                if not any(a <= m.start() < b for a, b in taken):
                    out.append((m.start(), side))
                    taken.append((m.start(), m.end()))
    return sorted(out)


def clubs_in(text: str, clubs: dict) -> list[str]:
    seen = []
    for _, s in club_spans(text, clubs):
        if s not in seen:
            seen.append(s)
    return seen


def club_before(text: str, pos: int, clubs: dict) -> str | None:
    before = [s for p, s in club_spans(text, clubs) if p < pos]
    return before[-1] if before else None


def minutes_said(text: str) -> list[int]:
    """The match minutes an answer names, explicit forms only: "minute 34", "minutes 35, 76 and 85",
    "minutes 20 to 34", "from minute 20 to 34", "34′" or "34'", "the 34th minute", a clock time
    "33:50" (minute 34). A bare
    number is never a minute: "15% to 20%", "up to 28", "the last 15 minutes" (a stretch) are not."""
    out = [int(x) for x in re.findall(r"\bminutes? (\d{1,3})\b(?!\s*%)", text, re.I)]
    for run in re.findall(r"\bminutes ((?:\d{1,3}(?:, | and |,? and | to | ?[-–] ?))+\d{1,3})\b", text, re.I):
        out += [int(x) for x in re.findall(r"\d{1,3}", run)[1:]]  # "minutes 35, 76 and 85": the rest
    out += [int(x) for x in re.findall(r"\bto minute (\d{1,3})\b", text, re.I)]
    # a range's end after one "minute": "from minute 20 to 34", "minute 34 to 40", "minute 41 until 43"
    out += [
        int(x)
        for x in re.findall(r"\bminutes? \d{1,3} ?(?:to|until|through|-|–) ?(\d{1,3})\b(?!\s*%)", text, re.I)
    ]
    out += [int(x) for x in re.findall(r"\b(\d{1,3})(?:′|')", text)]
    out += [int(x) for x in re.findall(r"\b(\d{1,3})(?:st|nd|rd|th) minute\b", text, re.I)]
    out += [int(m) + 1 for m in re.findall(r"\b(\d{1,2}):[0-5]\d\b", text)]
    return out


def goals_said(text: str, clubs: dict) -> list[tuple[str | None, int]]:
    """(side, minute) for each goal a sentence states."""
    out = []
    for s in sentences(text):
        if not re.search(r"\b(?:scor\w*|goal|netted|equali[sz]\w*|found the net)\b", s, re.I):
            continue
        if re.search(r"\b(?:no goal|not scored|haven't scored|without|spotted no goal)\b", s, re.I):
            continue
        cs = clubs_in(s, clubs)
        for m in minutes_said(s):
            out.append((cs[0] if len(cs) == 1 else None, m))
    return sorted(set(out), key=lambda g: g[1])


def scoreline(text: str, clubs: dict) -> dict | None:
    """The score an answer states: "London Athletic 1-3 Lisbon Esportes", or each club's goals
    ("London Athletic 1 goal, Lisbon Esportes 3 goals"), else None."""
    m = re.search(r"\b(\d+)\s*[-–]\s*(\d+)\b", text)
    if not m:
        each = {}
        for g in re.finditer(r"\b(\d+) goals?\b", text):
            side = club_before(text, g.start(), clubs)
            if side is not None and side not in each:
                each[side] = int(g.group(1))
        return each if set(each) == {"home", "away"} else None
    a, b = int(m.group(1)), int(m.group(2))
    first = club_before(text, m.start(), clubs) or next(
        (s for p, s in club_spans(text, clubs) if p > m.end()), None
    )
    if first == "away":
        return {"home": b, "away": a}
    return {"home": a, "away": b}


def percents(text: str, clubs: dict) -> list[tuple[str | None, float]]:
    """(side, value) for each percentage, a range said as its middle."""
    out = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*%(?:\s*(?:to|-|–|and)\s*(\d+(?:\.\d+)?)\s*%)?", text):
        v = float(m.group(1)) if m.group(2) is None else (float(m.group(1)) + float(m.group(2))) / 2
        rng = re.search(r"between\s*$", text[max(0, m.start() - 9) : m.start()])
        if m.group(2) is not None and not rng:
            # "London 63% to Lisbon 37%"-style pairs are two values, not a range
            v = float(m.group(1))
            out.append((club_before(text, m.start(), clubs), v))
            out.append((club_before(text, m.start(2), clubs), float(m.group(2))))
            continue
        out.append((club_before(text, m.start(), clubs), v))
    return out


def counts_said(text: str, metric: str) -> list[int]:
    noun = METRIC_NOUN[metric]
    out = [int(x) for x in re.findall(rf"\b(\d+)\s+(?:[\w-]+\s+){{0,2}}?{noun}\b", text, re.I)]
    out += [int(x) for x in re.findall(rf"\b{noun}\W{{0,3}}(\d+)\b", text, re.I)]
    word = {
        "no": 0,
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    for w, n in word.items():
        if re.search(rf"\b{w}\s+(?:[\w-]+\s+){{0,2}}?{noun}\b", text, re.I):
            out.append(n)
    return out


def names_said(text: str, roster: list[list]) -> list[str]:
    hits = [(text.find(n), n) for n, _ in roster if n and n in text]
    return [n for _, n in sorted(hits)]


def _leader(h: float | None, a: float | None, margin: float) -> str | None:
    if h is None or a is None:
        return None
    if abs(h - a) <= margin:
        return "either"
    return "home" if h > a else "away"


def claimed_side(text: str, clubs: dict) -> str | None:
    s = lead(text)
    if LEVEL.search(s) and not re.search(r"\b(?:more|ahead|on top|edge)\b", s, re.I):
        return "level"
    cs = clubs_in(s, clubs) or clubs_in(text, clubs)
    return cs[0] if cs else None


def correct(
    it: dict, q: str, text: str, tv: dict, tol: dict, clubs: dict, roster: list[list]
) -> tuple[bool | None, str]:
    """Is the stated value within tolerance of the truth? (verdict, scope graded against)."""
    kind = it["kind"]
    scope = "footage" if FOOTAGE.search(text) else "match"
    v = tv[scope]
    asked = clubs_in(q, clubs)
    one = asked[0] if len(asked) == 1 else None
    if kind in ("score", "leader"):
        truth_score = v["score"]
        said = scoreline(text, clubs)
        if said is None:
            gs = goals_said(text, clubs)
            if gs and all(s is not None for s, _ in gs):
                said = {k: sum(s == k for s, _ in gs) for k in ("home", "away")}
            elif NO_GOAL.search(text) and not gs:
                said = {"home": 0, "away": 0}
        if kind == "score":
            return said is not None and said == truth_score, scope
        lead_side = (
            "level"
            if truth_score["home"] == truth_score["away"]
            else ("home" if truth_score["home"] > truth_score["away"] else "away")
        )
        if said is not None:
            got = (
                "level"
                if said["home"] == said["away"]
                else ("home" if said["home"] > said["away"] else "away")
            )
            return got == lead_side, scope
        return claimed_side(text, clubs) == lead_side, scope
    if kind in ("goals", "moments"):
        truth_goals = [g for g in v["goals"] if one is None or g["team"] == one]
        said = goals_said(text, clubs)
        if not truth_goals:
            if kind == "moments":
                return not said, scope
            # "who scored?" before a goal: says there is none (in words or a 0-0), and states no goal
            none = bool(NO_GOAL.search(text)) or scoreline(text, clubs) == {"home": 0, "away": 0}
            return none and not said, scope
        tm = tol["goal_minute"]
        hit = all(
            any(abs(m - g["minute"]) <= tm and s in (None, g["team"]) for s, m in said) for g in truth_goals
        )
        extra = any(not any(abs(m - g["minute"]) <= tm for g in v["goals"]) for _, m in said)
        wrong_name = False
        for s in sentences(text):
            if re.search(r"\bscor\w*", s, re.I):
                for n in names_said(s, roster):
                    if n not in {g["name"] for g in v["goals"]}:
                        wrong_name = True
        return hit and not extra and not wrong_name, scope
    if kind == "why":
        goals = [g for g in v["goals"] if g["team"] == "home"]
        if not goals:
            return bool(NO_GOAL.search(text)), scope
        mins = minutes_said(text)
        # every minute it gives is the goal's (lesson 293: "just before it, in minute 32" for a goal in
        # minute 12 is not its build-up)
        when = all(any(abs(m - g["minute"]) <= tol["goal_minute"] for g in goals) for m in mins)
        named = {n for b in v.get("build_up", []) for e in b for n in (e["player"], e["receiver"]) if n}
        how = bool(
            re.search(r"\b(?:pass\w*|cross\w*|played|found|through ball|cut-?back|worked|move)\b", text, re.I)
        )
        return when and how and (
            not names_said(text, roster) or bool(set(names_said(text, roster)) & named)
        ), scope
    if kind == "count":
        lo, hi = v["count_lo"], v["count_hi"]
        # a club's question needs that club's count: an answer that names no club is a total, and a
        # total is neither London's 8 nor right for London when it happens to equal it (lesson 293)
        if one is not None and one not in clubs_in(text, clubs):
            return False, scope
        key = one or "total"
        said = counts_said(text, it["metric"])
        if not said:
            return False, scope
        ok = any(lo[key] <= n <= hi[key] for n in said)
        if not ok and key == "total" and len(said) >= 2:
            ok = lo["total"] <= sum(said[:2]) <= hi["total"]
        return ok, scope
    if kind == "share":
        t = v["possession_home"]
        ps = percents(text, clubs)
        if t is None:
            return (not ps) or None, scope
        homes = [p if s == "home" else 100 - p for s, p in ps if s in ("home", "away")]
        if not homes and one is not None:
            homes = [p if one == "home" else 100 - p for _, p in ps]
        if not homes:
            return False, scope
        return abs(homes[0] - t) <= tol["share_points"], scope
    if kind == "share_pair":
        t = v["territory"]
        ps = [(s, p) for s, p in percents(text, clubs) if s in ("home", "away")]
        if ps:
            return all(t[s] is not None and abs(p - t[s]) <= tol["territory_points"] for s, p in ps), scope
        lead_side = _leader(t["home"], t["away"], tol["leader_margin_points"])
        got = claimed_side(text, clubs)
        if got is None or (got != "level" and len(clubs_in(text, clubs)) < 2):
            return False, scope  # with no shares, only a comparison of the two clubs answers it
        return lead_side == "either" or got == lead_side, scope
    if kind == "club_compare":
        t = v["territory"]
        lead_side = _leader(t["home"], t["away"], tol["leader_margin_points"])
        if lead_side is None:
            return None, scope
        got = claimed_side(text, clubs)
        if got is None:
            return False, scope
        if got != "level" and len(clubs_in(text, clubs)) < 2:
            return False, scope  # a comparison names both clubs (one club's figure compares nothing)
        return lead_side == "either" or got == lead_side, scope
    if kind == "pct":
        t = v["completion"]
        ps = percents(text, clubs)
        if not ps:
            return False, scope
        side, p = ps[0]
        key = side or one or "total"
        return t.get(key) is not None and abs(p - t[key]) <= tol["completion_points"], scope
    if kind == "player":
        ranked = v["ranked"]
        if it["scope"].startswith("club:"):
            ranked = v[f"ranked_{it['scope'].split(':')[1]}"]
        top = [r[0] for r in ranked[: tol["player_rank_top"]]]
        said = names_said(text, roster)
        if not said:
            return False, scope
        return said[0] in top, scope
    if kind == "unmeasured":
        plain = bool(CANT.search(text)) or bool(
            re.search(
                r"\b(?:doesn't|does not|don't|do not) (?:detect|measure|"
                r"track|see|call|rule)\b",
                text,
                re.I,
            )
        )
        invented = bool(re.search(r"\b\d+\s+(?:fouls?|cards?|offsides?|bookings?|yellow|red)\b", text, re.I))
        pointer = bool(re.search(r"\d", text)) or bool(
            re.search(r"\b(?:instead|but|here's|what it can)\b", text, re.I)
        )
        return plain and pointer and not invented, scope
    return None, scope


COMPARE_LEVEL = re.compile(
    r"\b(?:level|the same number|as many|equal(?:ly)?|both had|each had|neither had more"
    r"|neither (?:side|team|club) has|each(?! (?:club|side|team|of)\b))\b",
    re.I,
)
COMPARE_MORE = re.compile(r"\b(?:more|most|ahead|edge)\b", re.I)
COMPARE_FEWER = re.compile(r"\b(?:fewer|less|behind)\b", re.I)


def compared_side(text: str, clubs: dict) -> str | None:
    """The side an answer's lead sentence says is ahead: "level" for "level", "2 each", "neither side
    has had"; the club named first with "more"/"most"/"ahead" ("Lisbon have had more shots"), the
    other club with "fewer"/"less" ("London have had fewer than Lisbon"); None with no comparison."""
    s = lead(text)
    if COMPARE_LEVEL.search(s) and not COMPARE_MORE.search(s):
        return "level"
    named = clubs_in(s, clubs)
    if not named or not (COMPARE_MORE.search(s) or COMPARE_FEWER.search(s)):
        return None
    if COMPARE_FEWER.search(s) and not COMPARE_MORE.search(s):
        return "away" if named[0] == "home" else "home"
    return named[0]


def comparison_direction(text: str, tv: dict, clubs: dict, tol: dict | None = None) -> bool:
    """Detector-bound rows (Kian, Oct 27) lead with a club comparison: the lead sentence names the
    club that truly has more over the footage shown, or says "level" when the truth is level.
    - A count (passes, shots, on target, corners, out of play): the footage count with the count
      tolerance's edge bands (tolerances.json count_edge_s). Where the two clubs' bands overlap the
      truth cannot order them, so "level" or the club ahead on the central count passes (both clubs
      and "level" when the central counts are equal).
    - Completion, said as a direction ("X have passed more accurately than Y"): the footage
      completion of each club; within completion_points of each other, "level" or either club passes.
    No comparison in the lead fails."""
    v = tv["footage"]
    if "completion" in v:
        h, a = v["completion"].get("home"), v["completion"].get("away")
        if h is None or a is None:
            allowed = {"level", "home", "away"}
        elif abs(h - a) <= (tol or {}).get("completion_points", 10):
            allowed = {"level", "home", "away"}
        else:
            allowed = {"home" if h > a else "away"}
    else:
        c, lo, hi = v["count"], v["count_lo"], v["count_hi"]
        if lo["home"] > hi["away"]:
            allowed = {"home"}
        elif lo["away"] > hi["home"]:
            allowed = {"away"}
        elif c["home"] == c["away"]:
            allowed = {"level", "home", "away"} if lo != hi else {"level"}
        else:
            allowed = {"level", "home" if c["home"] > c["away"] else "away"}
    return compared_side(text, clubs) in allowed


CLAIM_KINDS = ("count", "pct")  # the detector-bound rows whose claim is graded (grade_claim)
NEITHER = re.compile(r"\bneither (?:side|team|club) has(?: had)?\b", re.I)
NOT_A_FIGURE = re.compile(
    r"\bminutes? \d{1,3}(?: ?(?:to|until|through|-|–) ?\d{1,3})?\b|\b\d{1,2}:[0-5]\d\b"
    r"|\b\d{1,3}(?:′|')|\b\d{1,3}(?:st|nd|rd|th)\b",
    re.I,
)


def claimed_figures(it: dict, text: str, clubs: dict) -> dict | None:
    """The per-club figures a comparison's lead states: {"home": n, "away": m}, one club's only, or
    None when it states none or they cannot be told apart. "5 to London's 3" after "Lisbon": Lisbon 5,
    London 3; "2 shots each": both 2; "neither side has had a corner": both 0; a completion's
    percentages by the club before each."""
    s = lead(text)
    if it["kind"] == "pct":
        got = {side: v for side, v in percents(s, clubs) if side in ("home", "away")}
        return got or None
    if NEITHER.search(s):
        return {"home": 0, "away": 0}
    nums = [int(x) for x in re.findall(r"\b(\d+)\b(?!\s*%)", NOT_A_FIGURE.sub(" ", s))]
    named = clubs_in(s, clubs)
    if not nums:
        return None
    if len(nums) == 1 and re.search(r"\beach\b", s, re.I) and len(named) == 2:
        return {"home": nums[0], "away": nums[0]}
    if len(nums) == 2 and len(named) == 2:
        return dict(zip(named, nums, strict=True))
    return None


def grade_claim(it: dict, text: str, tv: dict, tol: dict, clubs: dict, strict: bool | None) -> bool:
    """Grade the claim (coordinator, Oct 27; committed before any answer is graded with it). For the
    detector-bound rows (counts, completion): a lead that is a comparison is correct when its
    direction is right (comparison_direction) and every figure it states for a club is within
    tolerance of that club's truth (both apply when both are stated); a lead that is no comparison
    is correct as before (`strict`: the stated number within tolerance); an answer stating neither
    a comparison nor a number fails (strict fails it)."""
    if compared_side(text, clubs) is None:
        return bool(strict)
    if not comparison_direction(text, tv, clubs, tol):
        return False
    figs = claimed_figures(it, text, clubs)
    if figs is None:
        return True
    scope = "footage" if FOOTAGE.search(text) else "match"
    v = tv[scope]
    for side, n in figs.items():
        if it["kind"] == "pct":
            t = v["completion"].get(side)
            if t is None or abs(n - t) > tol["completion_points"]:
                return False
        elif not v["count_lo"][side] <= n <= v["count_hi"][side]:
            return False
    return True


def grade(
    it: dict,
    q: str,
    t: float,
    ans: dict,
    tv: dict | None,
    tol: dict,
    clubs: dict,
    roster: list[list],
    holds: bool | None,
) -> dict:
    """Every check for one answer ({status, text, t_to}). `holds`: do the insights hold the facts?"""
    text = ans.get("text") or ""
    unmeasured = it["kind"] == "unmeasured"
    cant = bool(CANT.search(text))
    answered = bool(text.strip()) if unmeasured else (ans.get("status") == "verified" and not cant)
    rel = None
    if it.get("relevance"):
        rel = bool(re.search(it["relevance"], lead(text), re.I))
    ok, scope = (None, None)
    strict = None
    if tv is not None and it["kind"] != "chip":
        ok, scope = correct(it, q, text, tv, tol, clubs, roster)
        if not answered and not unmeasured:
            ok = False
        if it["kind"] in CLAIM_KINDS:
            strict = ok  # the old strict-number column, kept beside the claim's grade
            ok = answered and grade_claim(it, text, tv, tol, clubs, strict)
    figure = bool(re.search(r"\d", text)) and it["kind"] in ("count", "share", "share_pair", "pct", "player")
    cov = tv["coverage"] if tv else 1.0
    honest = bool(FOOTAGE.search(text)) if (figure and answered and cov < 0.999) else None
    nm = now_minute(t)
    future = [m for m in minutes_said(text) if m > nm]
    t_to = ans.get("t_to")
    no_future = not future and not ans.get("leak")
    span_clipped = t_to is None or t_to <= t + 1.0
    false_unknown = None if unmeasured or holds is None else not (holds and not answered)
    flags = [k for k, rx in NATURAL.items() if rx.search(text)]
    compares = (
        comparison_direction(text, tv, clubs, tol)
        if it["kind"] in ("count", "pct") and tv is not None and answered
        else None
    )
    checks = {
        "answered": answered,
        "relevant": rel,
        "correct": ok,
        "coverage_honest": honest,
        "no_future": no_future,
        "span_clipped": span_clipped,
        "no_false_unknown": false_unknown,
        "natural": not flags,
        "comparison_direction": compares,
        "correct_strict": strict,
    }
    return {"checks": checks, "scope": scope, "flags": flags, "future_minutes": future}


def headline(text: str) -> str:
    """The lead sentence, normalised for the consistency check."""
    return re.sub(r"\s+", " ", lead(text).lower()).strip(" .")


CORE = ("answered", "relevant", "correct", "no_false_unknown")  # the headline: a right answer to the question
OTHERS = (
    "no_future",
    "span_clipped",
    "coverage_honest",
    "natural",
    "consistent",
    "comparison_direction",
    "correct_strict",
)
CHECKS = CORE + OTHERS


def passed(checks: dict) -> bool:
    return all(v is not False for v in checks.values())


def core_passed(checks: dict) -> bool:
    return all(checks.get(c) is not False for c in CORE)
