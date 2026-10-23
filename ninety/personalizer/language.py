"""Whether a text meant for a Spanish profile reads as English.

The fact-checker holds a Spanish variant that is the verified English text byte for byte, and one
that reads as English (ninety/personalizer/cues.py): more English function words than Spanish ones.
Ids, numbers and clocks are in neither list. Quoted words and capitalised names (a club's English
name) are not counted, so Spanish that quotes English or names an English club still reads as
Spanish (lesson 154). A heuristic: English padded with Spanish function words reads as Spanish.
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
WORD = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")
QUOTED = re.compile(r'"[^"]*"|“[^”]*”|«[^»]*»|‘[^’]*’')
TAG = re.compile(r"\[[a-z]{2}\]")  # a language label such as the mock's "[es]": not a word of the text
SENTENCE_START = re.compile(r"(?:^|[.!?¿¡:]\s+)$")


def counted(text: str) -> list[str]:
    """The text's words, lowercased, without quoted ones or capitalised names (a capital after a
    sentence's start)."""
    text = TAG.sub(" ", QUOTED.sub(" ", text))
    return [m.group().lower() for m in WORD.finditer(text)
            if not m.group()[0].isupper() or SENTENCE_START.search(text[:m.start()])]


def reads_english(text: str) -> bool:
    words = counted(text)
    return sum(w in ENGLISH for w in words) > sum(w in SPANISH for w in words)
