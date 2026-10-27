"""The Ask's intent table: what a fan can ask, and how each question is read.

A question is read as exactly one intent (a row of INTENTS) plus its slots: the club it names, the
stretch of the match it names, and which goal. Each row says what the answer needs, the metric its
lead sentence must carry, the stretch it covers when the fan names none, its shape (a count, both
clubs compared, a ranking, a story, or something vision does not measure) and the honest fallback
when its facts are missing. Code reads the question (normalise, then scored patterns with fixed
tie-breaks), and code computes every number (ninety/agents/ask_answers.py); a model, when one is
used, only picks a row of this same table and rephrases code's answer.

Replaces the keyword routing that let the first tool matched decide the reply (lesson 297). The
normalisation, windows, ordinal goals and the injection, prediction and off-topic replies are ported
from #423 (claude/dreamy-bassi-380a97, lesson 288).
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass

HALF_MIN = 45  # Law 7: two halves of 45 minutes (GROUNDING L3, I23)
FULL_MIN = 90
NOW_MIN = (
    15  # "now", "lately", "right now": the last 15 minutes (the stats' window, GROUNDING S4), within the half
)


@dataclass(frozen=True)
class Intent:
    """One row of the table. `tools`: the insight tools (ninety/intel/match_insights.py) its answer
    reads. `lead`: a pattern the answer's first sentence must match (the relevance gate). `window`:
    "so_far" (kick-off to now) or "now" (the last NOW_MIN minutes, within the half), when the fan
    names no stretch. `shape`: count, compare, rank, story, list or unmeasured. `chip`: the
    question the phone offers for it, or None."""

    id: str
    tools: tuple[str, ...]
    lead: str
    window: str
    shape: str
    chip: str | None
    fallback: str  # what the fallback says it gives instead, in a few words (docs and the model's menu)


INTENTS = (
    Intent(
        "score",
        ("score",),
        r"\b(?:goals?|score\w*|level)\b",
        "so_far",
        "compare",
        "What's the score?",
        "the scorebug's reading",
    ),
    Intent(
        "scorers",
        ("score",),
        r"\b(?:scor\w*|goals?)\b",
        "so_far",
        "list",
        "Who scored?",
        "each goal vision spotted, by minute and club",
    ),
    Intent(
        "winning",
        ("score",),
        r"\b(?:winning|ahead|level|goals?|lead\w*|score\w*)\b",
        "so_far",
        "compare",
        "Who's winning?",
        "the scorebug's reading",
    ),
    Intent(
        "on_top",
        ("on_top", "territory"),
        r"\b(?:on top|attacking third|of the ball|close to call)\b",
        "now",
        "compare",
        "Who's on top?",
        "both clubs' share of the ball in their attacking third",
    ),
    Intent(
        "momentum",
        ("on_top", "territory"),
        r"\b(?:on top|attacking third|of the ball|close to call)\b",
        "now",
        "compare",
        None,
        "both clubs' share of the ball in their attacking third",
    ),
    Intent(
        "possession",
        ("possession",),
        r"\b(?:possession|of the ball|on the ball|on top|attacking third|\d+%)",
        "so_far",
        "compare",
        "Who has had more of the ball?",
        "the longest run of passing",
    ),
    Intent(
        "passes",
        ("passing",),
        r"\bpass(?:es)?\b",
        "so_far",
        "count",
        "How many passes?",
        "the passes vision counted",
    ),
    Intent(
        "completion",
        ("passing",),
        r"\b(?:found a teammate|complet\w*|accurate\w*|\d+%|passes)",
        "so_far",
        "compare",
        "Who's passing better?",
        "the passes vision counted",
    ),
    Intent(
        "shots", ("shots",), r"\bshots?\b", "so_far", "count", "How many shots?", "the shots vision spotted"
    ),
    Intent(
        "on_target",
        ("shots", "score"),
        r"\bon target\b",
        "so_far",
        "count",
        "How many shots on target?",
        "the goals and saves vision spotted",
    ),
    Intent(
        "territory",
        ("territory",),
        r"\b(?:attacking third|territory)\b",
        "so_far",
        "compare",
        "Where has the ball been?",
        "both clubs' share of the ball in their attacking third",
    ),
    Intent(
        "corners",
        ("set_pieces",),
        r"\bcorners?\b",
        "so_far",
        "count",
        "How many corners?",
        "the restarts vision spotted",
    ),
    Intent(
        "out_of_play",
        ("set_pieces",),
        r"\b(?:out of play|throw-ins?|goal kicks?|restarts?)\b",
        "so_far",
        "count",
        "How often has the ball gone out?",
        "the restarts vision spotted",
    ),
    Intent(
        "best",
        ("players",),
        r"\b(?:best|most involved|passes|opponents|scored|fastest|km/h|ground)\b",
        "so_far",
        "rank",
        "Who has been the best player?",
        "the players whose passes took most opponents out",
    ),
    Intent("player", ("players", "physical"), r".", "so_far", "rank", None, "what vision tracked of him"),
    Intent(
        "fastest",
        ("physical",),
        r"\b(?:fast\w*|speed|km/h|pace|covered|ground)\b",
        "so_far",
        "rank",
        "Who is the fastest on the pitch?",
        "each club's distance covered",
    ),
    Intent(
        "distance",
        ("physical",),
        r"\b(?:covered|run|ran|distance|km)\b",
        "so_far",
        "rank",
        "Who has run the furthest?",
        "each club's distance covered",
    ),
    Intent(
        "why_goal",
        ("goal_build_up",),
        r"\b(?:pass\w*|move|build-?up|shot|scored|goal)\b",
        "so_far",
        "story",
        "Why did {club} score?",
        "the goal's minute and club",
    ),
    Intent(
        "key_moments",
        ("key_moments",),
        r"\b(?:goals?|scor\w*|shots?|minute|moments?)\b",
        "so_far",
        "list",
        "What have I missed?",
        "the goals so far",
    ),
    Intent(
        "unmeasured",
        ("referee",),
        r"\b(?:not tracked|doesn't|does not|can't|cannot)\b",
        "so_far",
        "unmeasured",
        None,
        "the closest thing vision does measure",
    ),
    Intent("tactics", (), r".", "now", "story", "How are {club} playing?", "the old tool routing"),
    Intent("small_talk", (), r".", "so_far", "unmeasured", None, "suggested questions"),
)
BY_ID = {i.id: i for i in INTENTS}


# ---------------------------------------------------------------------------------------------
# Normalisation (#423, lesson 288): text-speak spelled out, a misspelt football word corrected.
# ---------------------------------------------------------------------------------------------

SHORTHAND = {
    "r": "are",
    "u": "you",
    "ur": "your",
    "hw": "how",
    "wat": "what",
    "wot": "what",
    "wats": "what's",
    "pls": "please",
    "plz": "please",
    "mins": "minutes",
    "min": "minutes",
    "whos": "who's",
    "whats": "what's",
    "hows": "how's",
    "1st": "first",
    "2nd": "second",
    "3rd": "third",
    "4th": "fourth",
    "v": "vs",
    "gk": "keeper",
    "tho": "though",
    "2day": "today",
    "cuz": "because",
    "bc": "because",
    "possesion": "possession",
    "posession": "possession",
    "shtos": "shots",
    "pases": "passes",
    "cornres": "corners",
    "targt": "target",
    "londons": "London's",
    "lisbons": "Lisbon's",
    "motm": "man of the match",
}
# Design: the words the table's patterns need, a close match only (difflib ratio 0.85), never a word
# under five letters (a short typo has too many neighbours).
FOOTBALL_WORDS = (
    "winning",
    "losing",
    "playing",
    "possession",
    "player",
    "players",
    "scored",
    "score",
    "scorer",
    "scoring",
    "pressing",
    "shape",
    "shots",
    "goals",
    "passes",
    "passing",
    "keeper",
    "goalkeeper",
    "offside",
    "corners",
    "territory",
    "counter",
    "overloads",
    "assist",
    "assisted",
    "minutes",
    "equaliser",
    "striker",
    "winger",
    "defending",
    "attacking",
    "happened",
    "dangerous",
    "chances",
    "compact",
    "width",
    "tactics",
    "formation",
    "lineup",
    "referee",
    "penalty",
    "highlights",
    "recap",
    "missed",
    "target",
    "fastest",
    "quickest",
    "furthest",
    "farthest",
    "distance",
    "covered",
    "momentum",
    "dominating",
    "completion",
    "accuracy",
    "throw-ins",
    "stoppages",
    "restarts",
    "involved",
    "standout",
    "press",
    "shot",
    "best",
    "goal",
    "ball",
    "half",
    "first",
    "second",
    "third",
    "last",
    "doing",
    "possesion",
)
FIX_CUTOFF = 0.85
FIX_LEN = 5


def normalise(text: str, words: set[str] = frozenset()) -> str:
    """The question with text-speak spelled out and misspellings of the football words (and of
    `words`: the clubs' and players' names) corrected; a word already known is kept as typed."""
    known = {w for w in (*FOOTBALL_WORDS, *(w.lower() for w in words)) if len(w) >= 4}
    out = re.sub(r"[A-Za-z0-9']+", lambda m: SHORTHAND.get(m.group(0).lower(), m.group(0)), text)
    out = re.sub(r"[’‘]", "'", out)
    for m in reversed(list(re.finditer(r"[A-Za-z]+", out))):
        low = m.group(0).lower()
        if low in known or len(low) < FIX_LEN:
            continue
        close = difflib.get_close_matches(low, known, n=1, cutoff=FIX_CUTOFF)
        if close:
            out = out[: m.start()] + close[0] + out[m.end() :]
    return out


# ---------------------------------------------------------------------------------------------
# Scored patterns. Each intent's patterns add their weight when they match; the highest total wins,
# ties going to the intent first in TIE_BREAK. The weights are design: a word only one intent uses
# weighs more than a word several share.
# ---------------------------------------------------------------------------------------------

UNMEASURED_TOPICS = (
    ("offside", r"\boffsides?\b"),
    ("fouls", r"\bfoul\w*|\bfouled\b|\bdive[ds]?\b|\bhand ?ball"),
    ("cards", r"\bcards?\b|\byellows?\b|\breds?\b|\bbook(?:ed|ing|ings)\b|\bsent off\b|\bcaution\w*"),
    ("saves", r"\bsaves?\b|\bsaved\b"),
    ("tackles", r"\btackl\w*"),
    ("referee", r"\breferee\b|\bref\b|\bvar\b|\bpenalty (?:shout|appeal)"),
)
# A goal named any way a fan names one: a goal, scoring, the opener, the equaliser, the winner, a strike.
GOAL_WORDS = r"\b(?:goals?|scor\w*|opener|equali[sz]\w*|winner|strike|netted|finish)\b"
PATTERNS: dict[str, tuple[tuple[str, int], ...]] = {
    "unmeasured": tuple((p, 8) for _, p in UNMEASURED_TOPICS),
    "why_goal": (
        (r"\b(?:why|how) (?:did|was|were|come)\b.{0,40}" + GOAL_WORDS, 9),
        (
            r"\b(?:talk|walk) me through\b|\bbreak down\b|\bexplain\b|\bdescribe\b|\btell me about\b"
            r"|\bbuild-?up\b|\bled to\b|\bled up to\b|\bhappen\w*\b"
            r"|\bcome about\b|\bset (?:it|the goal) up\b",
            6,
        ),
        (r"\bassist\w*", 6),
        (r"\bbuild[- ]?up\b|\bled (?:up )?to\b|\bhow (?:did|was) (?:that|the|their|his) goal\b", 9),
    ),
    "scorers": (
        (r"\bdid\b.{1,30}\bscore\b", 7),
        (
            r"\bwho(?:'s| has| have| had)?\b.{0,20}\b(?:scored"
            r"|got the goals?|got the goal|netted|found the net"
            r"|put it (?:in|away)|on the scoresheet)",
            9,
        ),
        (r"\b(?:goal ?scorers?|scorers?|scoresheet)\b|\bwhich players? (?:has |have )?scored\b", 8),
    ),
    "score": (
        (r"\bresult\b|\bnil[- ]nil\b|\bnil all\b", 6),
        (r"\bscore ?(?:line|wise)\b|\bscore\b(?!d|rs?\b)|\bwhat(?:'s| is) it(?: at)?(?: now)?\W*$", 6),
        (r"\bhow many goals\b|^\W*goals\W*$", 6),
        (r"\b\d+\s*[-–]\s*\d+\b", 4),
    ),
    "winning": (
        (r"\b(?:the|a) lead\b", 6),
        # Not "losing the ball", "winning it back", "winning the battle": those are about play.
        (
            r"\b(?:winning|losing|leading)\b(?! (?:the (?:ball|battle|duels?|race)|it|possession"
            r"|out|duels?|headers?|tackles?|back|them)\b)"
            r"|\b(?:ahead|in the lead|in front|drawing|behind)\b(?! when)",
            6,
        ),
        (
            r"\b(?:is it|are we|are they|is the game) (?:level|a draw|all square|even)\b"
            r"|\bwho(?:'s| is| has)? (?:up|won)\b"
            r"|\blevel\W*$",
            6,
        ),
    ),
    "on_target": (
        (
            r"\bon (?:target|frame)\b|\bhit the target\b"
            r"|\bkeeper (?:been )?tested\b|\btested the keeper\b"
            r"|\bforced? (?:a |any )?saves?\b",
            9,
        ),
    ),
    "shots": ((r"\bshots?\b|\battempts?\b|\befforts?\b|\bshoot\w*|\bshot\b", 6),),
    "completion": (
        (
            r"\bcomplet\w*|\baccura\w*|\bfinding a team-?mate|\bpassing better\b|\bgood is the passing"
            r"|% of passes|\bsuccess\w*|\bpass(?:ing)? (?:rate|percentage)\b|\bmisplac\w*",
            8,
        ),
    ),
    # A count of passes, not a kind of pass ("the most penetrating pass" is a tactics question).
    "passes": (
        (r"\bpasses (?:by|for|per|from) (?:each|both|team|side)", 8),
        (
            r"\bhow many pass\w*|\bpass(?:es)? (?:count|total|tally)\b|\btotal passes\b|\bnumber of passes\b"
            r"|\bpasses (?:so far|this half|each|made|played|have there|have been)|^\W*passes\W*$",
            8,
        ),
    ),
    "corners": ((r"\bcorners?\b", 8), (r"\bset[- ]pieces?\b|\bpenalt(?:y|ies)\b|\bfree[- ]kicks?\b", 7)),
    "out_of_play": (
        (
            r"\bout of (?:play|bounds)\b|\b(?:gone|go|went|going|goes) out\b|\bthrow[- ]?ins?\b|\bthrows\b"
            r"|\bgoal[- ]kicks?\b|\bstoppages?\b|\brestarts?\b|\bdead ball\b",
            8,
        ),
    ),
    "possession": (
        (r"\bhog\w* (?:the ball|possession)\b|\bthe ball (?:more|most)\b", 8),
        (
            r"(?<!lose )(?<!lost )(?<!loses )(?<!losing )\bposs?ess?ion\b(?! back)"
            r"|\b(?:more|most|much) of the ball\b|\bball more\b"
            r"|\bkeep(?:ing|s)? (?:the ball|it) (?:more|better)\b"
            r"|\bkeep(?:ing|s)? the ball\b|\bwho(?:'s| has| have)? (?:had )?the ball\b"
            r"|\b(?:had|controlled|seeing) (?:more|most) of the ball\b|\bcontroll?ed the ball\b",
            8,
        ),
    ),
    "territory": (
        (r"\bwhere(?:'s| is| has)? (?:the action|the game|the play)\b", 8),
        (
            r"\bterritor\w*|\bwhere(?:'s| has| is| have)? (?:the ball|most of the play|the game|the play)"
            r"|\bball (?:has )?been\b|\bwhich half\b|\b(?:opposition|other|their|opponents?') half\b"
            r"|\bcamped\b|\bpinned\b|\battacking third\b|\bball spending\b",
            8,
        ),
    ),
    "momentum": ((r"\bmomentum\b|\bfinish\w* stronger\b|\bpushing\b|\bstronger\b|\bbetter spell\b", 7),),
    "on_top": (
        (r"\bcontroll?ing (?:it|things|play)\b|\bmore of the (?:game|match)\b|\bstronger side\b", 6),
        (
            r"\bon top\b|\bdominat\w*|\bdominan\w*|\bin control\b"
            r"|\bcontroll?ing the (?:game|match)\b|\bin charge\b"
            r"|\bupper hand\b|\bbetter (?:side|team|football)\b|\bplaying better\b|\bthe edge\b"
            r"|\bfront foot\b|\bbossing\b|\bbeen better\b|\brunning the (?:game|show)\b|\bpressing forward\b"
            r"|\bbetter (?:right now|at the moment|recently|lately)"
            r"|\bhad the better\b|\bwhich (?:team|side) is better\b"
            r"|\bplaying well(?:er)?\b(?=.*\b(?:team|side)\b)",
            6,
        ),
    ),
    "fastest": (
        (
            r"\bfastest\b|\bquickest\b|\bspeed\w*|\bmost pace\b"
            r"|\bhow fast\b|\bpacie\w*|\bquick(?:est)? player\b",
            9,
        ),
    ),
    "distance": (
        (r"\bhow much\b.{0,30}\b(?:run|ran|running|covered)\b", 9),
        (
            r"\b(?:run|ran|running|covered) (?:the )?(?:furthest|farthest|most)\b"
            r"|\bcovered the most\b|\bmost "
            r"(?:ground|distance|running|kilomet\w*|km)\b|\bdistance\b|\bhardest working\b|\bfurthest\b"
            r"|\bfarthest\b|\bkilomet\w*|\bkm\b|\bhow far\b|\bmost running\b|\bwork rate\b|\bhas run most\b",
            9,
        ),
    ),
    "best": (
        (
            r"\bbest\b|\bstar (?:man|player|of the show)\b"
            r"|\bstand-?out\b|\bstood out\b|\b(?:man|player) of the "
            r"(?:match|game)\b|\bkey man\b|\bmost (?:involved|dangerous|influential|effective|impressive)\b"
            r"|\bimpress\w*|\bplayed well\b|\bplaying (?:well|best)\b(?!.*\b(?:team|side)\b)"
            r"|\bunreal\b|\bbeen brilliant\b|\btop performer\b",
            7,
        ),
    ),
    "key_moments": (
        (
            r"\btalking points?\b|\bwhat(?:'s| has)? been going on\b|\bgoing on so far\b"
            r"|\bstory of the (?:game|match)\b",
            8,
        ),
        (
            r"\bkey moments?\b|\bbig moments?\b|\bhighlights?\b|\b(?:have|did) i miss\w*|\bcatch me up\b"
            r"|\bwhat(?:'s| has)? happened|\bsumm(?:ary|ari[sz]e)\b"
            r"|\brecap\b|\banything (?:big |interesting )?happen\w*|\btimeline\b|\bwhat did i miss\b",
            8,
        ),
    ),
}
# The tactics questions the old tool routing answers well (companion_match.TOOL_WORDS): a shape, an
# overload, a pass that cut through, a style. Each match weighs 5.
TACTICS_TOOLS = (
    "style",
    "counter_press",
    "overloads",
    "line_breaks",
    "pass_options",
    "team_shape",
    "halves",
    "passing",
    "lineup",
)
TIE_BREAK = (
    "unmeasured",
    "why_goal",
    "scorers",
    "on_target",
    "completion",
    "fastest",
    "distance",
    "score",
    "winning",
    "corners",
    "out_of_play",
    "possession",
    "territory",
    "momentum",
    "on_top",
    "shots",
    "passes",
    "best",
    "key_moments",
    "tactics",
)
# A word that asks to compare over a stretch: on top in "the last ten minutes" is momentum.
RECENT = re.compile(
    r"\blast (?:\d+|five|ten|fifteen|twenty|thirty)\b|\blately\b|\brecently\b"
    r"|\bsince (?:the|half|minute)\b",
    re.I,
)


# ---------------------------------------------------------------------------------------------
# Not a question about the match (#423 and lesson 287): small talk, an injection, a prediction.
# ---------------------------------------------------------------------------------------------

INJECTION = re.compile(
    r"\b(?:ignore|disregard|forget|override)\b.{0,40}\b(?:rules?|instructions?|prompt|above|previous)\b"
    r"|^\s*(?:system|assistant|developer)\s*:|\b(?:reveal|print|show|repeat|translate|leak)\b.{0,30}"
    r"\b(?:instructions?|system prompt|prompt|rules|ground truth|truth|answer key)\b|\byou are now\b"
    r"|\bpretend\b|\brepeat after me\b|^\s*say\s+['\"]|\btrack ids?\b|\bjailbreak|\bDAN\b"
    r"|</?\w+>|\{\s*\"",
    re.I,
)
FUTURE = re.compile(
    r"\b(?:will (?:win|score|happen|be)|who(?:'s| is)? going to (?:win|score)|predict\w*"
    r"|next (?:match|game|goal)|what will|gonna (?:win|score)|final score (?:be|going))\b",
    re.I,
)
OUTSIDE = re.compile(
    r"\b(?:referee'?s name|name of the referee|who is the referee|weather|rain\w*|sunny|cold|fans|crowd"
    r"|attendance|stadium|tickets?|pay|paid|fee|transfer|salary|wages?|xg|expected goals|in the world"
    r"|of all time|ever|world cup|champions league|premier league table|league table"
    r"|odds|bet|bets|betting)\b",
    re.I,
)
NOT_MATCH = (("inject", INJECTION), ("future", FUTURE), ("outside", OUTSIDE))


# ---------------------------------------------------------------------------------------------
# Windows: the stretch a question names, in whole minutes (minute m is m-1:00 to m:00).
# ---------------------------------------------------------------------------------------------

WORD_N = {"five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "half an hour": 30}
_N = r"(\d+|five|ten|fifteen|twenty|thirty)"


def _n(s: str) -> int:
    return int(s) if s.isdigit() else WORD_N[s]


@dataclass(frozen=True)
class Window:
    """Minutes `lo` to `hi`, both whole minutes already played (hi is the last finished minute, so
    nothing after the question's time is read), `said`: how the answer says it ("so far", "in the
    first half", "from minute 31 to minute 34"); `named`: the fan named it. `empty`: why there is no
    such stretch yet ("The second half hasn't started yet."), else None."""

    lo: int
    hi: int
    said: str
    named: bool
    empty: str | None = None


def played(t: float) -> int:
    """The minutes fully played at match time t: never a minute past now (its bin ends after t)."""
    return max(0, min(FULL_MIN, int(t // 60)))


def window_of(text: str, t: float, default: str = "so_far") -> Window:
    """The stretch the question names, else the row's default: "so_far" is kick-off to now, "now"
    the last NOW_MIN minutes within the current half."""
    s = text.lower()
    done = played(t)
    half_lo = HALF_MIN + 1 if done > HALF_MIN else 1

    def span(lo: int, hi: int, named: bool = True) -> Window:
        lo, hi = max(1, lo), max(1, hi)
        said = (
            "so far"
            if lo == 1 and hi == done
            else f"from minute {lo} to minute {hi}"
            if lo < hi
            else f"in minute {lo}"
        )
        return Window(lo, hi, said, named)

    if re.search(r"\bfirst half\b", s):
        if done < HALF_MIN:  # the first half so far is the match so far: said the same way
            return span(1, done)
        return Window(1, HALF_MIN, "in the first half", True)
    if re.search(
        r"\b(?:second half|since the break|after the break|since half[- ]?time|after half[- ]?time)\b", s
    ):
        if done <= HALF_MIN:
            return Window(1, max(1, done), "so far", True, "The second half hasn't started yet.")
        return Window(HALF_MIN + 1, done, "in the second half", True)
    if re.search(r"\bthis half\b", s):
        return (
            span(half_lo, max(half_lo, done))
            if done <= HALF_MIN
            else Window(half_lo, done, "this half", True)
        )
    m = re.search(rf"\b(?:last|past) {_N}(?: ?min\w*)?\b", s)
    if m:
        return span(done - _n(m.group(1)) + 1, done)
    if re.search(r"\b(?:last|past) half(?: an)? hour\b", s):
        return span(done - 29, done)
    m = re.search(rf"\b(?:first|opening) {_N} ?min\w*\b", s)
    if m:
        return span(1, min(_n(m.group(1)), done))
    if re.search(r"\b(?:since|in) the half[- ]hour\b|\bsince half an hour\b", s):
        if done <= 30:
            return Window(1, max(1, done), "so far", True, "The match hasn't reached the half hour yet.")
        return span(31, done)
    m = re.search(
        r"\b(?:since|from|after) (?:the )?minute (\d+)\b|\bsince the (\d+)(?:st|nd|rd|th)? minute\b", s
    )
    if m:
        lo = int(m.group(1) or m.group(2))
        if lo > done:
            return Window(1, max(1, done), "so far", True, f"Minute {lo} hasn't been played yet.")
        return span(lo, done)
    if re.search(
        r"\b(?:so far|(?:the )?whole (?:match|game)|all (?:match|game)"
        r"|(?:this|the|in the|over the) (?:match|game)"
        r"|today|overall|since kick-?off|from the start)\b",
        s,
    ):
        return span(1, done)
    if default == "now" or re.search(r"\b(?:right now|at the moment|lately|recently|currently)\b", s):
        return span(max(half_lo, done - NOW_MIN + 1), done, named=False)
    return span(1, done, named=False)


# ---------------------------------------------------------------------------------------------
# Goals asked for (#423): "the 2nd goal", "Lisbon's third", "the equaliser", "the winner".
# ---------------------------------------------------------------------------------------------

ORDINALS = {
    "first": 0,
    "opening": 0,
    "second": 1,
    "third": 2,
    "fourth": 3,
    "fifth": 4,
    "last": -1,
    "latest": -1,
    "most recent": -1,
}
GOAL_WORD = r"(?:goal|strike|finish|equali[sz]er|winner)"


def ordinal_of(text: str) -> str | int | None:
    """Which goal: an index into the goals so far (a club's own when one is named), "equaliser",
    "winner", or None for none named."""
    s = text.lower()
    if re.search(r"\bequali[sz]\w*", s):
        return "equaliser"
    if re.search(r"\bwinner\b|\bwinning goal\b", s):
        return "winner"
    if re.search(r"\bopener\b|\bopening goal\b", s):
        return 0
    m = re.search(
        rf"\b(first|opening|second|third|fourth|fifth|last|latest|most recent)\b[\w' ]{{0,20}}{GOAL_WORD}", s
    )
    return ORDINALS[m.group(1)] if m else None


# ---------------------------------------------------------------------------------------------
# Reading a question
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Read:
    """A question read: its intent, the clubs it names (by full name), the stretch, which goal,
    the topic of an unmeasured question, and the normalised text."""

    intent: str
    clubs: tuple[str, ...]
    window: Window
    goal: str | int | None
    topic: str | None
    text: str
    scores: tuple[tuple[str, int], ...] = ()
    player: str | None = None  # a team-sheet name the question names, else None

    @property
    def club(self) -> str | None:
        return self.clubs[0] if len(self.clubs) == 1 else None


def club_names(clubs: dict[str, str], codes: dict[str, str]) -> dict[str, set[str]]:
    """Each club's names a fan uses: the full name, its short name and code, and each word of the full
    name the other's does not share ("Esportes")."""
    words = {t: {w for w in clubs[t].split() if len(w) >= 4} for t in clubs}
    out = {}
    for team in clubs:
        other = words["away" if team == "home" else "home"]
        out[clubs[team]] = {clubs[team], codes[team], *(words[team] - other)}
    return out


def clubs_in(text: str, names: dict[str, set[str]]) -> tuple[str, ...]:
    """The clubs a question names, in the order it names them."""
    hits = []
    for club, ns in names.items():
        at = [m.start() for n in ns for m in re.finditer(rf"\b{re.escape(n)}(?:'s?|s')?\b", text, re.I)]
        if at:
            hits.append((min(at), club))
    return tuple(c for _, c in sorted(hits))


def scores(text: str, tactics: bool = False) -> dict[str, int]:
    s = text.lower()
    out = {iid: sum(w for p, w in pats if re.search(p, s)) for iid, pats in PATTERNS.items()}
    if tactics:
        out["tactics"] = 5
    # "Who's been better in the last 15 minutes?": on top over a stretch is momentum.
    if out.get("on_top") and RECENT.search(s):
        out["momentum"] += out["on_top"] + 1
    # "Explain quantum physics", "talk me through it": a goal's story only when a goal is asked about.
    if out.get("why_goal") and not re.search(GOAL_WORDS + r"|\bassist\w*", s):
        out["why_goal"] = 0
    return {k: v for k, v in out.items() if v > 0}


def classify(
    text: str,
    *,
    clubs: dict[str, str],
    codes: dict[str, str],
    t: float,
    words: set[str] = frozenset(),
    tactics: bool = False,
    player: bool = False,
    small_talk: str | None = None,
) -> Read:
    """One intent and its slots. `tactics`: the old routing finds a tactics tool in it; `player`: it
    names a player or a position; `small_talk`: companion_match.chat_kind's reading, if any."""
    names = club_names(clubs, codes)
    norm = normalise(text, {*words, *(w for ns in names.values() for n in ns for w in n.split())})
    named = clubs_in(norm, names)
    goal = ordinal_of(norm)
    topic = next((k for k, p in UNMEASURED_TOPICS if re.search(p, norm, re.I)), None)
    for kind, pattern in NOT_MATCH:
        if pattern.search(norm):
            return Read("small_talk", named, window_of(norm, t), goal, kind, norm)
    sc = scores(norm, tactics)
    if player and not sc.keys() - {"tactics"}:
        sc["player"] = 5
    if goal is not None and not sc.get("unmeasured"):
        sc["why_goal"] = sc.get("why_goal", 0) + 5  # "the 2nd goal", "the equaliser": that goal's story
    if not sc:
        if small_talk is not None:
            return Read("small_talk", named, window_of(norm, t), goal, small_talk, norm)
        return Read(
            "tactics" if tactics else "small_talk",
            named,
            window_of(norm, t),
            goal,
            None if tactics else "other",
            norm,
        )
    order = {iid: k for k, iid in enumerate((*TIE_BREAK, "player"))}
    intent = max(sc, key=lambda k: (sc[k], -order.get(k, 99)))
    return Read(
        intent,
        named,
        window_of(norm, t, BY_ID[intent].window),
        goal,
        topic,
        norm,
        tuple(sorted(sc.items(), key=lambda kv: -kv[1])),
    )


def chips_table() -> list[dict]:
    """The phone's chips, from the table: each row's question, its intent and the club slot it
    takes ({club} is filled with the fan's club)."""
    return [{"intent": i.id, "q": i.chip, "club_slot": "{club}" in i.chip} for i in INTENTS if i.chip]


def model_menu() -> list[dict]:
    """The rows a model may pick from, as it reads them: id, shape and what the answer leads with."""
    return [{"id": i.id, "shape": i.shape, "fallback": i.fallback} for i in INTENTS]


CHIPS_JSON = "ask_chips.json"  # beside this module: the phone reads the table's chips from it


if __name__ == "__main__":  # writes the chips as JSON, for the phone
    from pathlib import Path

    Path(__file__).with_name(CHIPS_JSON).write_text(json.dumps(chips_table(), indent=1) + "\n")
