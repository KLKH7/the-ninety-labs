"""A team's style: dials that change what its players intend, never what happens.

Each dial runs from 0 to 1. The shape dials are read in three bands (low, mid, high) and move
where the team stands and when it goes to the ball. The on-ball dials tilt how the player on the
ball weighs his options (D1, D4) around the mid value, which leaves them as they were. Whether a
press wins the ball or a pass arrives is still decided by perception, physics and execution
error. Only dials the engine acts on are listed here; the rest of
docs/decisions/0002-styles-and-matchups.md arrives as each one is wired. Constants cite
docs/GROUNDING.md (T4). All values *design*.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

LOW, MID, HIGH = 0.2, 0.5, 0.8  # preset values for each band


def tilt(value: float) -> float:
    """A dial as a tilt from -1 to 1 around its mid value (0 at 0.5)."""
    band(value)
    return (value - MID) * 2


def band(value: float) -> str:
    """Read a dial in thirds."""
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"a dial runs from 0 to 1, got {value}")
    return "low" if value < 1 / 3 else "mid" if value < 2 / 3 else "high"


# Pressing intensity: how far the first presser will go to the ball (m), and how close he stands
# to the carrier while jockeying (m). Mid is the engine's behaviour before styles: the presser
# goes from wherever he is once the ball is inside the line of engagement (T3; a fixed 20 m gate
# was removed because it left play unpressed). A low-intensity team keeps that 20 m gate.
ENGAGE_M = {"low": 20.0, "mid": math.inf, "high": math.inf}
PRESS_GAP_M = {"low": 2.5, "mid": 2.0, "high": 1.5}
# Counter-pressing: in the window after losing the ball (T1), whether the team goes to the ball
# wherever it is, and from how far (a low-intensity team too). Low drops straight back into shape.
COUNTER_PRESS_ENGAGE_M = {"low": None, "mid": math.inf, "high": math.inf}
# On the ball. Directness scales the value of ground gained toward goal from where the ball is
# (D1's progress term) by 1 + DIRECTNESS_SPAN x tilt: 0.1 to 1.9 times at the preset values.
# Counter-attacking scales it again, by the same rule, in the window after winning the ball (T1);
# a high counter-attacking team also sends its central midfielders running in behind then (O4).
# Below a dial value of 1/6 a factor would turn negative (valuing ground lost), so each is held at
# 0 or more. Risk scales the cost of losing the ball by 1 - RISK_SPAN x tilt: 1.3 to 0.7 times at
# the preset values, 1.5 to 0.5 over the whole dial.
DIRECTNESS_SPAN = 1.5
COUNTER_ATTACK_SPAN = 1.5
RISK_SPAN = 0.5


@dataclass(frozen=True)
class Style:
    line_height: float = MID  # which block the defensive line holds (T2)
    pressing_height: float = MID  # where the team starts going to the ball (T3)
    pressing_intensity: float = MID  # how far the presser goes, and how tight he stands
    counter_pressing: float = MID  # pressing straight after losing the ball (T1)
    counter_attacking: float = MID  # going forward straight after winning the ball (T1)
    directness: float = MID  # ground gained against keeping the ball (D1)
    risk: float = MID  # how much losing the ball is feared (D1)

    def __post_init__(self) -> None:
        for value in asdict(self).values():
            band(value)

    def level(self, dial: str) -> str:
        return band(getattr(self, dial))

    def progress_weight(self, attacking_transition: bool) -> float:
        """How much the player on the ball values ground gained, against the engine's default."""
        w = max(0.0, 1 + DIRECTNESS_SPAN * tilt(self.directness))
        if attacking_transition:
            w *= max(0.0, 1 + COUNTER_ATTACK_SPAN * tilt(self.counter_attacking))
        return w

    def loss_weight(self) -> float:
        """How much the player on the ball fears losing it, against the engine's default."""
        return 1 - RISK_SPAN * tilt(self.risk)


# Named presets (docs/decisions/0002).
PRESETS = {  # line, pressing height, intensity, counter-press, counter-attack, directness, risk
    "balanced": Style(),
    "high_press": Style(HIGH, HIGH, HIGH, HIGH, HIGH, MID, MID),
    "possession": Style(HIGH, MID, MID, HIGH, LOW, LOW, LOW),
    "counter_attack": Style(MID, LOW, MID, LOW, HIGH, HIGH, MID),
    "low_block": Style(LOW, LOW, LOW, LOW, MID, MID, LOW),
    "direct": Style(MID, MID, MID, MID, MID, HIGH, HIGH),
}


def preset_name(style: Style) -> str | None:
    """The preset a style matches, or None for a custom mix."""
    return next((name for name, preset in PRESETS.items() if preset == style), None)
