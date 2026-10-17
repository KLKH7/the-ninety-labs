"""A team's style: dials that change what its players intend, never what happens.

Each dial runs from 0 to 1 and is read in three bands (low, mid, high). A dial moves where the
team stands and when it goes to the ball; whether a press wins the ball is still decided by
perception, physics and execution error. Only dials the engine acts on are listed here; the
rest of docs/decisions/0002-styles-and-matchups.md arrives as each one is wired. Constants cite
docs/GROUNDING.md (T4). All band values *design*.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

LOW, MID, HIGH = 0.2, 0.5, 0.8  # preset values for each band


def band(value: float) -> str:
    """Read a dial in thirds."""
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"a dial runs from 0 to 1, got {value}")
    return "low" if value < 1 / 3 else "mid" if value < 2 / 3 else "high"


# Pressing intensity: how far the first presser will go to the ball (m), and how close he stands
# to the carrier while jockeying (m). Mid is the engine's earlier fixed behaviour.
ENGAGE_M = {"low": 15.0, "mid": 20.0, "high": 25.0}
PRESS_GAP_M = {"low": 2.5, "mid": 2.0, "high": 1.5}
# Counter-pressing: in the window after losing the ball (T1), whether the team goes to the ball
# wherever it is, and from how far. Low drops straight back into shape.
COUNTER_PRESS_ENGAGE_M = {"low": None, "mid": 20.0, "high": 30.0}


@dataclass(frozen=True)
class Style:
    line_height: float = MID  # which block the defensive line holds (T2)
    pressing_height: float = MID  # where the team starts going to the ball (T3)
    pressing_intensity: float = MID  # how far the presser goes, and how tight he stands
    counter_pressing: float = MID  # pressing straight after losing the ball (T1)

    def __post_init__(self) -> None:
        for value in asdict(self).values():
            band(value)

    def level(self, dial: str) -> str:
        return band(getattr(self, dial))


# Named presets (docs/decisions/0002). "Direct" waits for the directness and risk dials: on the
# dials wired so far it would be the default.
PRESETS = {  # line height, pressing height, pressing intensity, counter-pressing
    "balanced": Style(),
    "high_press": Style(HIGH, HIGH, HIGH, HIGH),
    "possession": Style(HIGH, MID, MID, HIGH),
    "counter_attack": Style(MID, LOW, MID, LOW),
    "low_block": Style(LOW, LOW, LOW, LOW),
}


def preset_name(style: Style) -> str | None:
    """The preset a style matches, or None for a custom mix."""
    return next((name for name, preset in PRESETS.items() if preset == style), None)
