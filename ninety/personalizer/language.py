"""Whether a text meant for a Spanish profile reads as English.

The fact-checker holds a Spanish variant that is the verified English text byte for byte
(ninety/personalizer/cues.py). An English sentence with one word changed passes that, so the failure
table also asks this: does the variant carry more English function words than Spanish ones? Ids,
numbers, clocks and team names are in neither list, so they decide nothing.
"""

from __future__ import annotations

import re

# Design: short, common function words of each language. A word both languages write the same way
# ("a", "no") is in neither list.
ENGLISH = frozenset(
    "the of and in with by for that is was are has his her their its to at from as but after into "
    "on an this it".split()
)
SPANISH = frozenset(
    "el la los las un una unos unas de del al y en con por para que se su sus es lo como más pero "
    "sin sobre tras entre hacia desde hasta cuando muy ya este esta".split()
)
WORD = re.compile(r"[a-záéíóúüñ]+")


def reads_english(text: str) -> bool:
    words = WORD.findall(text.lower())
    return sum(w in ENGLISH for w in words) > sum(w in SPANISH for w in words)
