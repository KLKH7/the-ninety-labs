"""Whether a Spanish profile's text reads as English (ninety/personalizer/language.py)."""

import pytest

from ninety.personalizer.language import reads_english

ENGLISH = {
    "the verified claim": "Away complete a pass of 8 m at 42 km/h.",
    "one word changed": "Away completes a pass of 8 m at 42 km/h.",
    "marked, not translated": "[es] Away complete a pass of 8 m at 42 km/h.",
    "reworded": "h4 finds h9 over 32.5 m in minute 2, and h9 finds h7.",
    "a sentence that starts with a capital": "The away side keep the ball in the final third.",
    "its one function word starts it": "In minute 2, h4 finds h9.",
    "the label alone is not Spanish": "[es] h4 finds h9 at 01:28.",
}
SPANISH = {
    "a pass": "Away completa un pase de 8 m a 42 km/h.",
    "a chain": "En el minuto 2, h4 encuentra a h9 a 32.5 m, y h9 encuentra a h7.",
    "short, no function word but a": "h4 encuentra a h9.",
    # Lesson 154: what a Spanish broadcast line can carry in English is not counted.
    "an English club name": "h4 encuentra a h9 ante The Northbridge Rovers.",
    "an English quote": 'El comentarista dijo "this is the pass of the match", y h4 sigue.',
    "a quote in curly marks": "Y el público canta “the best of the best”.",
}


@pytest.mark.parametrize("text", ENGLISH.values(), ids=ENGLISH)
def test_english_reads_english(text):
    assert reads_english(text)


@pytest.mark.parametrize("text", SPANISH.values(), ids=SPANISH)
def test_spanish_does_not(text):
    assert not reads_english(text)
