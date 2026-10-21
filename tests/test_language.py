"""Whether a Spanish profile's text reads as English (ninety/personalizer/language.py)."""

import pytest

from ninety.personalizer.language import reads_english

ENGLISH = {
    "the verified claim": "Away complete a pass of 8 m at 42 km/h.",
    "one word changed": "Away completes a pass of 8 m at 42 km/h.",
    "marked, not translated": "[es] Away complete a pass of 8 m at 42 km/h.",
    "reworded": "h4 finds h9 over 32.5 m in minute 2, and h9 finds h7.",
}
SPANISH = {
    "a pass": "Away completa un pase de 8 m a 42 km/h.",
    "a chain": "En el minuto 2, h4 encuentra a h9 a 32.5 m, y h9 encuentra a h7.",
    "short, no function word but a": "h4 encuentra a h9.",
}


@pytest.mark.parametrize("text", ENGLISH.values(), ids=ENGLISH)
def test_english_reads_english(text):
    assert reads_english(text)


@pytest.mark.parametrize("text", SPANISH.values(), ids=SPANISH)
def test_spanish_does_not(text):
    assert not reads_english(text)
