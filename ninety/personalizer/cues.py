"""From the Personalizer's variants to on-screen cues, through the fact-checker once more.

The Personalizer (core.recheck) already holds every variant to the fact-checker's code half and the
verified claim's facts. Before a variant airs, the live path runs the whole fact-checker on it, as
it does on the claim (ninety/agents/slice.FactCheckExecutor): the code checks and the preservation
rule again (whichever process wrote it), the confidence gate, then the Judge. Only a variant all of
them pass becomes an `insight` cue, in the insight's own slot, for its persona and language.

A variant in another language whose text is still the verified English (the Personalizer's
replacement for one it dropped), or that reads as English (ninety/personalizer/language.py), is not
a translation, so it does not air under that language: that viewer keeps the English template cue.
The one exception is the mock translator's text in a run that asked for it (NINETY_TRANSLATOR=mock):
it says it is a mock, with its "[es] " label on screen (lesson 154).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from jsonschema import validate

from ninety.agents import contracts
from ninety.agents.contracts import Judge, Profile, Variant
from ninety.agents.cues import DISPLAY_SECONDS, SCHEMA
from ninety.agents.factcheck import Claim, Verdict, check, confidence_gate, side_known
from ninety.personalizer.core import SOURCE_LANG, WRITTEN, problem
from ninety.personalizer.language import reads_english
from ninety.personalizer.translate import MOCK_PREFIX

SLOT = "top_right"  # the insight's slot (ninety/agents/live.INSIGHT_SLOT)


def profiles_for(main_event: dict, langs: Sequence[str] = contracts.LANGS) -> list[Profile]:
    """Every written persona in every language, except the analyst in English: that one is the
    verified claim itself. The club and the player are the main event's own: no player-focused
    variant when the detector named nobody, and no club variant when it could not tell the side
    (factcheck.side_known)."""
    out = []
    for lang in langs:
        for persona in WRITTEN:
            if persona == "analyst" and lang == SOURCE_LANG:
                continue
            player = main_event.get("player") if persona == "player_focus" else None
            if persona == "player_focus" and player is None:
                continue  # the detector could not say who it was
            if persona == "club" and not side_known(main_event):
                continue  # nor which side it was, firmly enough to tell it from a club's view
            out.append(Profile(persona, lang, main_event.get("team") if persona == "club" else None, player))
    return out


@dataclass
class Checked:
    shown: list[Variant] = field(default_factory=list)
    # (variant, status, reasons) for each one that may not air
    refused: list[tuple[Variant, str, list[str]]] = field(default_factory=list)


async def verify(
    claim: Claim, variants: Sequence[Variant], known: dict[str, dict], judge: Judge | None = None,
    labelled_mock: bool = False,
) -> Checked:
    """The fact-checker on every variant; status from contracts.status_for, the one mapping. With
    `labelled_mock` (the run asked for the mock translator), its "[es] "-labelled text may air."""
    checked = Checked()
    evidence = [known[i] for i in claim.evidence if i in known]
    for variant in variants:
        if variant.lang != SOURCE_LANG and variant.text == claim.text:
            checked.refused.append((variant, "held", ["no translation: the verified English text"]))
            continue
        mock = labelled_mock and variant.text.startswith(MOCK_PREFIX)
        if variant.lang != SOURCE_LANG and not mock and reads_english(variant.text):
            checked.refused.append((variant, "held", [f"not in {variant.lang}: the text reads as English"]))
            continue
        if variant.evidence != tuple(claim.evidence):
            verdict = Verdict(ok=False, reasons=["evidence changed"], category="unsupported_claim")
        elif why := problem(claim, evidence, variant.text, variant.lang):
            verdict = Verdict(ok=False, reasons=[why], category="unsupported_claim")
        else:
            as_claim = Claim(variant.text, list(variant.evidence))
            verdict = check(as_claim, known)
            if verdict.ok:  # a club's-side variant names a side however it is worded
                verdict = confidence_gate(as_claim, known, team_view=variant.persona == "club")
            if verdict.ok and judge is not None:
                verdict = await judge(as_claim, evidence)
        status = contracts.status_for(verdict)
        if status == "verified":
            checked.shown.append(variant)
        else:
            checked.refused.append((variant, status, verdict.reasons))
    return checked


def variant_cue(variant: Variant, t_in: float) -> dict:
    cue = {
        "id": f"insight-{'-'.join(variant.evidence)}-{variant.persona}-{variant.lang}",
        "t_in": t_in,
        "t_out": round(t_in + DISPLAY_SECONDS, 2),
        "kind": "insight",
        "slot": SLOT,
        "anchor": None,
        "persona": variant.persona,
        "lang": variant.lang,
        "text": variant.text,
        "verified": True,
        "replaces": None,
        "evidence": list(variant.evidence),
    }
    validate(cue, SCHEMA)
    return cue
