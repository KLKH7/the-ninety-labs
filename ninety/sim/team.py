"""The team brain: twice a second each team reads the game and sets its shape.

It decides the phase of play, how high the defensive line stands, and who should press and
who should cover. These are suggestions for each player's own decisions (step 3 of
docs/ENGINE.md weighs them; a low-teamwork player may ignore them), never outcomes. Constants
cite docs/GROUNDING.md (T1 to T4).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ninety.sim.offball import LENGTH_MAX_M
from ninety.sim.style import COUNTER_PRESS_ENGAGE_M, ENGAGE_M, PRESS_GAP_M, Style

PITCH_X, PITCH_Y = 105.0, 68.0
TRANSITION_S = 5.0  # T1: the window after the ball changes hands (counter-press about 5 to 6 s)
# T2: defensive line, metres from own goal line, by block (low 12-22, mid 25-35, high 35-50).
BLOCKS = {"low": (12.0, 22.0), "mid": (25.0, 35.0), "high": (35.0, 50.0)}
# T3: where a team starts pressing the ball, metres from its own goal, by pressing height (the
# line of engagement); outside it they hold their shape. *design*, *verify*: published sources wanted.
ENGAGE_FROM_GOAL_M = {"low": 40.0, "mid": 60.0, "high": 105.0}
LINE_FOLLOWS_BALL = 0.5  # design: how far the line moves for each metre the ball moves
GOAL_SIDE_OF_BALL_M = 5.0  # design: with the ball inside the block, the line drops to stay this far goal-side
LINE_FLOOR_M = 5.5  # Law 1: the line drops no deeper than the goal area
LINE_GAPS_M = {"defence": 0.0, "midfield": 12.0, "attack": 24.0}  # design: compact out of possession
SQUEEZE = 0.7  # design: out of possession the shape narrows toward the centre
BALL_SIDE = 0.3  # design: and shifts toward the ball's side
ROLE_LINE = {"RB": "defence", "RCB": "defence", "LCB": "defence", "LB": "defence",
             "RCM": "midfield", "CM": "midfield", "LCM": "midfield",
             "RW": "attack", "ST": "attack", "LW": "attack"}


def own_goal_x(team: str) -> float:
    return 0.0 if team == "home" else PITCH_X


def forward(team: str) -> float:
    return 1.0 if team == "home" else -1.0


@dataclass
class TeamBrain:
    team: str
    style: Style = field(default_factory=Style)
    block: str = ""  # the line's block; from the style unless given
    in_possession: bool = False
    changed_at: float = -99.0
    line_x: float = 0.0
    front_x: float = 0.0  # where the forwards wait out of possession (T3)
    midfield_gap: float = LINE_GAPS_M["midfield"]  # the midfield line ahead of the defence (T3)
    ranked: list[str] = field(default_factory=list)  # out of possession: soonest to the ball first
    pressers: list[str] = field(default_factory=list)
    markers: dict[str, tuple[float, float]] = field(default_factory=dict)  # defender -> spot
    marked: set[str] = field(default_factory=set)  # O2: the attackers those markers have
    # T3: whom the press is on (the carrier, or the kick in flight) and the presser and cover named for it,
    # held while that stays the same.
    press_on: object = None
    held_pressers: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.block = self.block or self.style.level("line_height")
        self.engage_from_goal_m = ENGAGE_FROM_GOAL_M[self.style.level("pressing_height")]
        self.press_gap_m = PRESS_GAP_M[self.style.level("pressing_intensity")]
        self._engage_m = ENGAGE_M[self.style.level("pressing_intensity")]
        self._counter_engage_m = COUNTER_PRESS_ENGAGE_M[self.style.level("counter_pressing")]

    def update(self, now: float, has_ball: bool, ball_x: float, time_to_ball: dict[str, float]) -> None:
        """Read the game: who has the ball, where it is, and who of ours could reach it soonest.
        `time_to_ball` maps each outfield player of this team to his time to reach the ball."""
        if has_ball != self.in_possession:
            self.in_possession = has_ball
            self.changed_at = now
        lo, hi = BLOCKS[self.block]
        ball_from_goal = abs(ball_x - own_goal_x(self.team))
        depth = min(hi, max(lo, ball_from_goal * LINE_FOLLOWS_BALL))
        # The block holds while the ball is in front of it; a ball inside it pulls the line back
        # toward the box, so the defence stays between the ball and the goal.
        depth = min(depth, max(LINE_FLOOR_M, ball_from_goal - GOAL_SIDE_OF_BALL_M))
        # T3: the forwards wait at the team's line of engagement, so that when the ball comes
        # inside it the first presser is already close; never past the ball, and never closer
        # to their own goal than the front of the block.
        front = max(depth + LINE_GAPS_M["attack"], min(ball_from_goal, self.engage_from_goal_m))
        # R8: without the ball the team is more compact than with it, so it is no longer than the
        # cap it keeps in possession (O6): when the forwards wait high, as a high press does up to a
        # goal kick, the line steps up behind them. The forwards wait at most at the ball, so the
        # line stays well goal-side of it. Until October 2026 only the team on the ball was capped,
        # and a high press stood 49 m long (77 m with a low line), its back line in its own half.
        depth = max(depth, front - LENGTH_MAX_M)
        self.line_x = own_goal_x(self.team) + forward(self.team) * depth
        # T3: like the forwards, the midfield line never stands past the ball. With the ball inside
        # the block it recovers to level with the ball, between it and the line, rather than waiting
        # upfield of play (recovery runs are a large share of high-intensity running out of
        # possession, Ade et al. 2016; the level is *design*). Until October 2026 it kept 12 m ahead
        # of the line wherever the ball was, so a ball 30 m from goal had the midfield behind it.
        self.midfield_gap = min(LINE_GAPS_M["midfield"], max(0.0, ball_from_goal - depth))
        self.front_x = own_goal_x(self.team) + forward(self.team) * front
        self.ranked = [] if has_ball else sorted(time_to_ball, key=time_to_ball.get)
        # The suggestion: first presser, then cover. Each named player still decides (P17).
        self.pressers = self.ranked[:2]

    def counter_pressing(self, now: float) -> bool:
        """In the window after losing the ball (T1), and the style counter-presses."""
        return self._counter_engage_m is not None and now - self.changed_at < TRANSITION_S

    def attacking_transition(self, now: float) -> bool:
        """In the window after winning the ball (T1), when a counter-attack is on."""
        return self.in_possession and now - self.changed_at < TRANSITION_S

    def presses(self, now: float, ball_x: float) -> bool:
        """Out of possession, does the team go to the ball? Straight after losing it (the
        counter-press window, T1), or once the ball is inside its line of engagement (T3)."""
        if self.in_possession:
            return False
        if self.counter_pressing(now):
            return True
        return abs(ball_x - own_goal_x(self.team)) <= self.engage_from_goal_m

    def engage_m(self, now: float) -> float:
        """How far the first presser will go to the ball: further while counter-pressing, if
        the style says so."""
        if self.counter_pressing(now):
            return max(self._engage_m, self._counter_engage_m)
        return self._engage_m

    def slot(self, role: str, anchor_y: float, ball_y: float) -> tuple[float, float] | None:
        """Where a player of this role belongs out of possession: his line's height from the
        defensive line, squeezed toward the centre and shifted toward the ball's side."""
        line = ROLE_LINE.get(role)
        if line is None or self.in_possession:
            return None
        gap = self.midfield_gap if line == "midfield" else LINE_GAPS_M[line]
        x = self.front_x if line == "attack" else self.line_x + forward(self.team) * gap
        y = PITCH_Y / 2 + (anchor_y - PITCH_Y / 2) * SQUEEZE + (ball_y - PITCH_Y / 2) * BALL_SIDE
        return min(PITCH_X - 1, max(1.0, x)), min(PITCH_Y - 1, max(1.0, y))
